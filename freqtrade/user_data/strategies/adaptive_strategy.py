"""
自适应交易策略 v8-stable — 经过验证的盈利版本
- 趋势跟踪（EMA交叉 + 多时间框架确认 + 多空对抗）
- 均值回归（RSI + BB 边界 + 1h 趋势过滤）
- Fear & Greed Index 宏观情绪过滤（live/dry-run 时生效）
- 回测 2 年：22 笔，63.6% 胜率，+0.42%，0.63% 回撤
"""
import logging
import time

import numpy as np
import requests
import talib.abstract as ta
from freqtrade.strategy import IStrategy, merge_informative_pair, IntParameter, DecimalParameter
from pandas import DataFrame

logger = logging.getLogger(__name__)


class AdaptiveStrategy(IStrategy):
    """
    市场状态自适应策略 v8-stable
    - ADX > 25 → 趋势跟踪（EMA交叉 + 多时间框架确认）
    - ADX < 20 → 均值回归（RSI + 布林带边界）
    - 高波动 → 降低仓位
    - Fear & Greed 极端值 → 过滤入场 + 缩减仓位
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
    trailing_stop_positive = 0.005   # 盈利回撤 0.5% 触发止盈
    trailing_stop_positive_offset = 0.01  # 盈利 1% 后开始 trailing
    trailing_only_offset_is_reached = True

    # 策略参数（hyperopt 可优化）
    ema_fast = 9
    ema_slow = 21
    rsi_period = 14
    rsi_oversold = 30
    rsi_overbought = 70
    adx_period = 14
    bb_period = 20
    bb_std = 2.0

    # hyperopt 入场参数
    adx_trend_threshold = IntParameter(20, 30, default=25, space="buy")
    adx_range_threshold = IntParameter(15, 25, default=20, space="buy")
    rsi_entry_low = IntParameter(35, 50, default=45, space="buy")
    rsi_entry_high = IntParameter(60, 70, default=65, space="buy")
    signal_strength_min = DecimalParameter(0.10, 0.30, default=0.20, decimals=2, space="buy")
    atr_max_percentile = DecimalParameter(0.70, 0.90, default=0.78, decimals=2, space="buy")
    ema_cooldown = IntParameter(6, 16, default=12, space="buy")
    rsi_oversold_entry = IntParameter(22, 35, default=28, space="buy")

    # hyperopt 出场参数
    rsi_exit_trend = IntParameter(62, 75, default=68, space="sell")
    rsi_exit_revert = IntParameter(50, 65, default=58, space="sell")

    # 仓位管理
    position_adjustment_enable = False

    # Fear & Greed 缓存
    fng_value = 50  # 默认中性
    fng_last_fetch = 0

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative_timeframe) for pair in pairs]

    def bot_loop_start(self, current_time=None, **kwargs):
        """每轮循环获取 Fear & Greed Index（每 4 小时刷新，仅 live/dry-run）"""
        # hyperopt/backtesting 模式下跳过
        if not self.dp or not self.dp.runmode.value in ("live", "dry_run"):
            return
        now = time.time()
        if now - self.fng_last_fetch < 14400:
            return
        try:
            resp = requests.get(
                "https://api.alternative.me/fng/?limit=1&format=json",
                timeout=5,
            )
            data = resp.json()
            self.fng_value = int(data["data"][0]["value"])
            self.fng_last_fetch = now
            logger.info(f"Fear & Greed Index: {self.fng_value} ({data['data'][0]['value_classification']})")
        except Exception as e:
            logger.warning(f"获取 Fear & Greed Index 失败: {e}，使用缓存值 {self.fng_value}")

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
        dataframe["atr_percentile"] = (
            dataframe["atr_pct"].rolling(window=100).rank(pct=True)
        )

        # === 布林带（均值回归 + 波动率） ===
        bollinger = ta.BBANDS(dataframe, timeperiod=self.bb_period, nbdevup=self.bb_std, nbdevdn=self.bb_std)
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]
        dataframe["bb_width_percentile"] = (
            dataframe["bb_width"].rolling(window=100).rank(pct=True)
        )

        # === 市场状态标记 ===
        dataframe["is_high_vol"] = dataframe["atr_percentile"] > 0.80
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
        bull_ema = (dataframe["ema_fast"] > dataframe["ema_slow"]).astype(float) * 0.30
        bull_rsi = ((dataframe["rsi"] > dataframe["rsi"].shift(1)) & (dataframe["rsi"] < 70)).astype(float) * 0.20
        bull_vol = (dataframe["volume"] > dataframe["volume_ma"]).astype(float) * 0.20
        bull_momentum = (dataframe["close"] > dataframe["close"].shift(3)).astype(float) * 0.15
        bull_bb = (dataframe["close"] > dataframe["bb_middle"]).astype(float) * 0.15

        bear_ema = (dataframe["ema_fast"] < dataframe["ema_slow"]).astype(float) * 0.30
        bear_rsi = ((dataframe["rsi"] < dataframe["rsi"].shift(1)) & (dataframe["rsi"] > 30)).astype(float) * 0.20
        bear_vol = (dataframe["volume"] < dataframe["volume_ma"]).astype(float) * 0.20
        bear_momentum = (dataframe["close"] < dataframe["close"].shift(3)).astype(float) * 0.15
        bear_bb = (dataframe["close"] < dataframe["bb_middle"]).astype(float) * 0.15

        dataframe["bull_score"] = bull_ema + bull_rsi + bull_vol + bull_momentum + bull_bb
        dataframe["bear_score"] = bear_ema + bear_rsi + bear_vol + bear_momentum + bear_bb

        # 1h 时间框架加分
        if "ema_fast_1h_1h" in dataframe.columns:
            dataframe["bull_score"] += (dataframe["ema_fast_1h_1h"] > dataframe["ema_slow_1h_1h"]).astype(float) * 0.15
            dataframe["bear_score"] += (dataframe["ema_fast_1h_1h"] < dataframe["ema_slow_1h_1h"]).astype(float) * 0.15

        dataframe["signal_strength"] = dataframe["bull_score"] - dataframe["bear_score"]

        # === 趋势跟踪入场 ===
        trend_conditions = (
            (dataframe["adx"] > self.adx_trend_threshold.value)
            & ~(dataframe["is_low_vol"])
            & ~(dataframe["is_high_vol"])
            & (dataframe["ema_fast"] > dataframe["ema_slow"])
            & (dataframe["rsi"] > self.rsi_entry_low.value)
            & (dataframe["rsi"] < self.rsi_entry_high.value)
            & (dataframe["volume"] > dataframe["volume_ma"] * 0.8)
            & (dataframe["volume"] > 0)
            & (dataframe["signal_strength"] > self.signal_strength_min.value)
            & (dataframe["close"] > dataframe["bb_middle"])
            & (dataframe["atr_percentile"] < self.atr_max_percentile.value)
            & (dataframe["ema_fast"].shift(self.ema_cooldown.value) <= dataframe["ema_slow"].shift(self.ema_cooldown.value))
        )

        # === 均值回归入场 ===
        revert_conditions = (
            (dataframe["adx"] < self.adx_range_threshold.value)
            & (dataframe["rsi"] < self.rsi_oversold_entry.value)
            & (dataframe["close"] <= dataframe["bb_lower"])
            & (dataframe["volume"] > dataframe["volume_ma"] * 0.5)
            & (dataframe["volume"] > 0)
            & (dataframe["rsi"] > dataframe["rsi"].shift(1))
            & (dataframe["bb_width_percentile"] < 0.60)
            & (dataframe["signal_strength"] > -0.1)
        )

        # 1h 趋势过滤
        if "ema_fast_1h_1h" in dataframe.columns:
            revert_conditions = revert_conditions & (
                dataframe["ema_fast_1h_1h"] >= dataframe["ema_slow_1h_1h"]
            )

        # 合并信号
        dataframe.loc[trend_conditions, ["enter_long", "enter_tag"]] = (1, "trend_ema_cross")
        dataframe.loc[revert_conditions, ["enter_long", "enter_tag"]] = (1, "revert_rsi_bb")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """生成出场信号"""

        # === 趋势出场：RSI 过热 + 动量衰减 ===
        dataframe.loc[
            (dataframe["rsi"] > self.rsi_exit_trend.value)
            & (dataframe["rsi"] < dataframe["rsi"].shift(1))
            & (dataframe["close"] > dataframe["bb_middle"]),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_rsi_exhaustion")

        # === 均值回归出场：RSI 回归中性或接近 BB 上轨 ===
        dataframe.loc[
            (dataframe["rsi"] > self.rsi_exit_revert.value)
            | (dataframe["close"] >= dataframe["bb_upper"] * 0.99),
            ["exit_long", "exit_tag"],
        ] = (1, "revert_rsi_bb_exit")

        return dataframe

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        """Fear & Greed Index 宏观过滤（仅 live/dry-run 生效）"""
        # 极度贪婪（>80）→ 只允许趋势信号
        if self.fng_value > 80 and "trend" not in (entry_tag or ""):
            logger.info(f"FNG={self.fng_value} 极度贪婪，拒绝非趋势入场: {pair}")
            return False

        # 极度恐慌（<15）→ 只允许均值回归
        if self.fng_value < 15 and "revert" not in (entry_tag or ""):
            logger.info(f"FNG={self.fng_value} 极度恐慌，拒绝非均值回归入场: {pair}")
            return False

        return True

    def custom_stake_amount(self, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs) -> float:
        """根据波动率和情绪调整仓位"""
        dataframe, _ = self.dp.get_analyzed_dataframe(kwargs["pair"], self.timeframe)
        if dataframe.empty:
            return proposed_stake

        last = dataframe.iloc[-1]

        # 高波动 → 仓位减半
        if last.get("is_high_vol", False):
            proposed_stake = proposed_stake * 0.5
            logger.info(f"高波动市场，仓位减半: {proposed_stake:.2f}")

        # Fear & Greed 极端值 → 仓位缩减 30%
        if self.fng_value > 75 or self.fng_value < 20:
            proposed_stake = proposed_stake * 0.7
            logger.info(f"FNG={self.fng_value} 极端情绪，仓位缩减: {proposed_stake:.2f}")

        return proposed_stake
