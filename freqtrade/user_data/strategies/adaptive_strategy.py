"""
自适应交易策略 — 根据市场状态自动切换趋势跟踪/均值回归
"""
import logging
from functools import reduce

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame

logger = logging.getLogger(__name__)


class AdaptiveStrategy(IStrategy):
    """
    市场状态自适应策略
    - ADX > 25 → 趋势跟踪（EMA交叉 + 多时间框架确认）
    - ADX < 20 → 均值回归（RSI + 布林带边界）
    - 高波动 → 降低仓位
    - 低波动（BB收窄）→ 等待突破
    """

    INTERFACE_VERSION = 3

    # 基础参数
    timeframe = "5m"
    informative_timeframe = "1h"
    startup_candle_count = 200
    can_short = False
    stoploss = -0.02  # 硬编码止损 -2%

    # 移动止盈
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    # 策略参数
    ema_fast = 9
    ema_slow = 21
    rsi_period = 14
    rsi_oversold = 30
    rsi_overbought = 70
    adx_period = 14
    adx_trend_threshold = 25
    adx_range_threshold = 20
    bb_period = 20
    bb_std = 2.0

    # 仓位管理
    position_adjustment_enable = False

    # PLACEHOLDER_INFORMATIVE

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative_timeframe) for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算所有技术指标"""

        # === EMA（趋势跟踪用） ===
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow)

        # === RSI（均值回归用） ===
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_period)

        # === ADX（市场状态识别） ===
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=self.adx_period)

        # === ATR（波动率） ===
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"] * 100
        # ATR 百分位（判断高波动）
        dataframe["atr_percentile"] = (
            dataframe["atr_pct"].rolling(window=100).rank(pct=True)
        )

        # === 布林带（均值回归 + 波动率） ===
        bollinger = ta.BBANDS(dataframe, timeperiod=self.bb_period, nbdevup=self.bb_std, nbdevdn=self.bb_std)
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]
        # BB 宽度（判断低波动/收窄）
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]
        dataframe["bb_width_percentile"] = (
            dataframe["bb_width"].rolling(window=100).rank(pct=True)
        )

        # === 市场状态标记 ===
        # 趋势市场
        dataframe["is_trending"] = dataframe["adx"] > self.adx_trend_threshold
        # 震荡市场
        dataframe["is_ranging"] = dataframe["adx"] < self.adx_range_threshold
        # 高波动
        dataframe["is_high_vol"] = dataframe["atr_percentile"] > 0.80
        # 低波动（BB 收窄）
        dataframe["is_low_vol"] = dataframe["bb_width_percentile"] < 0.20

        # === 成交量确认 ===
        dataframe["volume_ma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # === 1h 信息时间框架 ===
        if self.dp:
            informative = self.dp.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.informative_timeframe
            )
            if not informative.empty:
                informative["ema_fast_1h"] = ta.EMA(informative, timeperiod=self.ema_fast)
                informative["ema_slow_1h"] = ta.EMA(informative, timeperiod=self.ema_slow)
                informative["rsi_1h"] = ta.RSI(informative, timeperiod=self.rsi_period)
                informative["adx_1h"] = ta.ADX(informative, timeperiod=self.adx_period)
                dataframe = merge_informative_pair(
                    dataframe, informative, self.timeframe, self.informative_timeframe, ffill=True
                )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """生成入场信号 — 多空因子对抗机制"""

        # === 计算多空因子得分 ===
        # 看涨因子
        bull_ema = (dataframe["ema_fast"] > dataframe["ema_slow"]).astype(float) * 0.30
        bull_rsi = ((dataframe["rsi"] > dataframe["rsi"].shift(1)) & (dataframe["rsi"] < 70)).astype(float) * 0.20
        bull_vol = (dataframe["volume"] > dataframe["volume_ma"]).astype(float) * 0.20
        bull_momentum = (dataframe["close"] > dataframe["close"].shift(3)).astype(float) * 0.15
        bull_bb = (dataframe["close"] > dataframe["bb_middle"]).astype(float) * 0.15

        # 看跌因子
        bear_ema = (dataframe["ema_fast"] < dataframe["ema_slow"]).astype(float) * 0.30
        bear_rsi = ((dataframe["rsi"] < dataframe["rsi"].shift(1)) & (dataframe["rsi"] > 30)).astype(float) * 0.20
        bear_vol = (dataframe["volume"] < dataframe["volume_ma"]).astype(float) * 0.20
        bear_momentum = (dataframe["close"] < dataframe["close"].shift(3)).astype(float) * 0.15
        bear_bb = (dataframe["close"] < dataframe["bb_middle"]).astype(float) * 0.15

        dataframe["bull_score"] = bull_ema + bull_rsi + bull_vol + bull_momentum + bull_bb
        dataframe["bear_score"] = bear_ema + bear_rsi + bear_vol + bear_momentum + bear_bb

        # 1h 时间框架加分
        if "ema_fast_1h_1h" in dataframe.columns:
            dataframe["bull_score"] = dataframe["bull_score"] + (
                (dataframe["ema_fast_1h_1h"] > dataframe["ema_slow_1h_1h"]).astype(float) * 0.15
            )
            dataframe["bear_score"] = dataframe["bear_score"] + (
                (dataframe["ema_fast_1h_1h"] < dataframe["ema_slow_1h_1h"]).astype(float) * 0.15
            )

        # 多空净得分
        dataframe["signal_strength"] = dataframe["bull_score"] - dataframe["bear_score"]

        # === 趋势跟踪入场（ADX > 25 + 多空净得分 > 0.3） ===
        trend_conditions = (
            (dataframe["is_trending"])
            & ~(dataframe["is_low_vol"])
            # EMA 金叉
            & (dataframe["ema_fast"] > dataframe["ema_slow"])
            & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))
            # RSI 不超买
            & (dataframe["rsi"] < self.rsi_overbought)
            # 成交量确认
            & (dataframe["volume"] > dataframe["volume_ma"])
            & (dataframe["volume"] > 0)
            # 多空对抗过滤：净得分必须 > 阈值
            & (dataframe["signal_strength"] > 0.3)
        )

        # === 均值回归入场（ADX < 20 + 多空净得分 > 0.1） ===
        revert_conditions = (
            (dataframe["is_ranging"])
            & ~(dataframe["is_low_vol"])
            # RSI 超卖
            & (dataframe["rsi"] < self.rsi_oversold)
            # 价格触及布林带下轨
            & (dataframe["close"] <= dataframe["bb_lower"])
            # 成交量确认
            & (dataframe["volume"] > 0)
            # 多空对抗过滤：均值回归阈值更低
            & (dataframe["signal_strength"] > 0.1)
        )

        # 合并信号
        dataframe.loc[trend_conditions, ["enter_long", "enter_tag"]] = (1, "trend_ema_cross")
        dataframe.loc[revert_conditions, ["enter_long", "enter_tag"]] = (1, "revert_rsi_bb")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """生成出场信号"""

        # === 趋势跟踪出场：EMA 死叉 ===
        dataframe.loc[
            (dataframe["ema_fast"] < dataframe["ema_slow"])
            & (dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1)),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_ema_death_cross")

        # === 均值回归出场：RSI 超买或触及 BB 上轨 ===
        dataframe.loc[
            (dataframe["rsi"] > self.rsi_overbought)
            | (dataframe["close"] >= dataframe["bb_upper"]),
            ["exit_long", "exit_tag"],
        ] = (1, "revert_rsi_bb_exit")

        return dataframe

    def custom_stake_amount(self, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs) -> float:
        """根据波动率调整仓位大小"""
        dataframe, _ = self.dp.get_analyzed_dataframe(kwargs["pair"], self.timeframe)
        if dataframe.empty:
            return proposed_stake

        last = dataframe.iloc[-1]

        # 高波动 → 仓位减半
        if last.get("is_high_vol", False):
            proposed_stake = proposed_stake * 0.5
            logger.info(f"高波动市场，仓位减半: {proposed_stake:.2f}")

        return proposed_stake
