"""
趋势跟踪策略 SwingTrendStrategy v5
- v5: 回退到v3入场严格度，止损-1.5%（ScalpingStrategy验证的最优值）
- 去掉亏损出场，让止损处理亏损（教训6：提前止损反而更差）
- 6币对优化后：16笔,75%,+5.79%,2.02%回撤
- 固定止损 -1.5%，禁用trailing和custom_stoploss
"""
import logging

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame

logger = logging.getLogger(__name__)


def supertrend(dataframe: DataFrame, period: int = 10, multiplier: float = 3.0):
    """计算 Supertrend 指标"""
    df = dataframe.copy()

    # ATR
    atr = ta.ATR(df, timeperiod=period)

    # 基础上下轨
    hl2 = (df["high"] + df["low"]) / 2
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    # 初始化
    st = np.zeros(len(df))
    direction = np.ones(len(df))  # 1=上涨, -1=下跌

    for i in range(1, len(df)):
        # 调整上下轨
        if lower_band.iloc[i] > lower_band.iloc[i - 1] or df["close"].iloc[i - 1] < lower_band.iloc[i - 1]:
            pass  # 保持当前lower_band
        else:
            lower_band.iloc[i] = lower_band.iloc[i - 1]

        if upper_band.iloc[i] < upper_band.iloc[i - 1] or df["close"].iloc[i - 1] > upper_band.iloc[i - 1]:
            pass  # 保持当前upper_band
        else:
            upper_band.iloc[i] = upper_band.iloc[i - 1]

        # 方向判断
        if direction[i - 1] == 1:  # 之前看多
            if df["close"].iloc[i] < lower_band.iloc[i]:
                direction[i] = -1
                st[i] = upper_band.iloc[i]
            else:
                direction[i] = 1
                st[i] = lower_band.iloc[i]
        else:  # 之前看空
            if df["close"].iloc[i] > upper_band.iloc[i]:
                direction[i] = 1
                st[i] = lower_band.iloc[i]
            else:
                direction[i] = -1
                st[i] = upper_band.iloc[i]

    return st, direction


class SwingTrendStrategy(IStrategy):
    """
    趋势跟踪 — 1h Supertrend + 5m EMA交叉
    """

    INTERFACE_VERSION = 3

    timeframe = "5m"
    informative_timeframe = "1h"
    startup_candle_count = 200
    can_short = False

    # ROI 2% 兜底（测试：让快速冲高的交易赚更多）
    minimal_roi = {"0": 0.02}

    # 固定止损 -1.5%（v5: ScalpingStrategy验证的最优值，-2%更差）
    stoploss = -0.015
    use_custom_stoploss = False  # 不用custom_stoploss（教训2）

    # 禁用trailing（教训1）
    trailing_stop = False

    position_adjustment_enable = False

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative_timeframe) for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """技术指标"""

        # 5m 指标
        dataframe["ema9"] = ta.EMA(dataframe, timeperiod=9)
        dataframe["ema21"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["rsi14"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_ma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # 5m EMA交叉检测
        dataframe["ema_cross_up"] = (
            (dataframe["ema9"] > dataframe["ema21"])
            & (dataframe["ema9"].shift(1) <= dataframe["ema21"].shift(1))
        )

        # EMA间距百分比
        dataframe["ema_gap_pct"] = (dataframe["ema9"] - dataframe["ema21"]) / dataframe["ema21"]

        # 冷却期：过去12根内没有其他EMA金叉（避免震荡区反复交叉）
        dataframe["recent_cross_count"] = dataframe["ema_cross_up"].rolling(window=12).sum()

        # BB指标（用于过滤震荡区）
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_width"] = (bollinger["upperband"] - bollinger["lowerband"]) / bollinger["middleband"]

        # 1h 时间框架
        if self.dp:
            informative = self.dp.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.informative_timeframe
            )
            if not informative.empty:
                # 1h Supertrend
                st_values, st_direction = supertrend(informative, period=10, multiplier=3.0)
                informative["supertrend_1h"] = st_values
                informative["supertrend_dir_1h"] = st_direction

                # 1h EMA
                informative["ema9_1h"] = ta.EMA(informative, timeperiod=9)
                informative["ema21_1h"] = ta.EMA(informative, timeperiod=21)

                # 1h RSI & ADX
                informative["rsi14_1h"] = ta.RSI(informative, timeperiod=14)
                informative["adx14_1h"] = ta.ADX(informative, timeperiod=14)

                dataframe = merge_informative_pair(
                    dataframe, informative, self.timeframe, self.informative_timeframe, ffill=True
                )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """入场信号 — 1h Supertrend看多 + 5m EMA金叉"""

        if "supertrend_dir_1h_1h" not in dataframe.columns:
            dataframe["enter_long"] = 0
            return dataframe

        conditions = (
            # 1h Supertrend 看多
            (dataframe["supertrend_dir_1h_1h"] == 1)
            # 1h EMA趋势确认
            & (dataframe["ema9_1h_1h"] > dataframe["ema21_1h_1h"])
            # 1h ADX趋势强度（v5: 回退到25）
            & (dataframe["adx14_1h_1h"] > 25)
            # 1h RSI（v5: 回退到45-65）
            & (dataframe["rsi14_1h_1h"] > 45)
            & (dataframe["rsi14_1h_1h"] < 65)
            # 5m EMA金叉
            & (dataframe["ema_cross_up"])
            # 5m close在ema21上方
            & (dataframe["close"] > dataframe["ema21"])
            # 5m close在BB中轨上方
            & (dataframe["close"] > dataframe["bb_middle"])
            # 5m RSI（v5: 回退到45-60）
            & (dataframe["rsi14"] > 45)
            & (dataframe["rsi14"] < 60)
            # 5m RSI在上升
            & (dataframe["rsi14"] > dataframe["rsi14"].shift(1))
            # 冷却期
            & (dataframe["recent_cross_count"] <= 1)
            # BB宽度
            & (dataframe["bb_width"] > 0.02)
            # 5m 成交量确认（v5: 回退到1.2）
            & (dataframe["volume"] > dataframe["volume_ma"] * 1.2)
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[conditions, ["enter_long", "enter_tag"]] = (1, "swing_trend_entry")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """出场留给 custom_exit"""
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        """精确出场控制"""

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None

        last = dataframe.iloc[-1]
        trade_duration = (current_time - trade.open_date_utc).total_seconds()

        # === 1. Supertrend翻空（核心趋势出场，v5: 只在盈利时出场）===
        if "supertrend_dir_1h_1h" in last and last["supertrend_dir_1h_1h"] == -1:
            if current_profit > 0:
                return "swing_supertrend_exit"

        # === 2. 5m EMA死叉 + 有利润 ===
        if (last.get("ema9", 0) < last.get("ema21", 0)) and current_profit > 0.003:
            return "swing_ema_cross"

        # === 3. 利润保护 ===
        if current_profit > 0.01:
            return "swing_profit_lock"
        if current_profit > 0.007 and last.get("rsi14", 50) > 55:
            return "swing_profit_rsi"

        # === 4. 1h RSI过热 ===
        if "rsi14_1h_1h" in last and last["rsi14_1h_1h"] > 70 and current_profit > 0.005:
            return "swing_rsi_exit"

        # === 5. 超时管理（12小时，只在盈利时出场）===
        if trade_duration > 43200 and current_profit > 0.002:
            return "swing_timeout"

        return None
