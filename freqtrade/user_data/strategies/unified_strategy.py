"""
统一策略 UnifiedStrategy — 合并3个策略的入场信号到一个策略
目的：共享1000U资金池，提高资金利用率
- bb_deep_bounce: 来自ScalpingStrategy（BB下轨深度反弹）
- mean_revert: 来自GridDCAStrategy（BB下轨+下影线+连续超卖）
- swing_trend: 来自SwingTrendStrategy（1h Supertrend+5m EMA金叉）

每个信号保持原策略的严格条件，不做任何放宽
出场也按原策略逻辑，根据enter_tag区分
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
    atr = ta.ATR(df, timeperiod=period)
    hl2 = (df["high"] + df["low"]) / 2
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    st = np.zeros(len(df))
    direction = np.ones(len(df))

    for i in range(1, len(df)):
        if lower_band.iloc[i] > lower_band.iloc[i - 1] or df["close"].iloc[i - 1] < lower_band.iloc[i - 1]:
            pass
        else:
            lower_band.iloc[i] = lower_band.iloc[i - 1]

        if upper_band.iloc[i] < upper_band.iloc[i - 1] or df["close"].iloc[i - 1] > upper_band.iloc[i - 1]:
            pass
        else:
            upper_band.iloc[i] = upper_band.iloc[i - 1]

        if direction[i - 1] == 1:
            if df["close"].iloc[i] < lower_band.iloc[i]:
                direction[i] = -1
                st[i] = upper_band.iloc[i]
            else:
                direction[i] = 1
                st[i] = lower_band.iloc[i]
        else:
            if df["close"].iloc[i] > upper_band.iloc[i]:
                direction[i] = 1
                st[i] = lower_band.iloc[i]
            else:
                direction[i] = -1
                st[i] = upper_band.iloc[i]

    return st, direction


class UnifiedStrategy(IStrategy):
    """
    统一策略 — 合并3个策略信号，共享资金池
    """

    INTERFACE_VERSION = 3

    timeframe = "5m"
    informative_timeframe = "1h"
    startup_candle_count = 200
    can_short = False

    # ROI 2%（三策略统一）
    minimal_roi = {"0": 0.02}

    # 止损 -2%（取Scalping和GridDCA的值，SwingTrend的-1.5%在custom_exit中处理）
    stoploss = -0.02
    use_custom_stoploss = False
    trailing_stop = False
    position_adjustment_enable = False

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative_timeframe) for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """合并所有指标"""

        # === Scalping + GridDCA 共用指标 ===
        dataframe["rsi7"] = ta.RSI(dataframe, timeperiod=7)
        dataframe["rsi14"] = ta.RSI(dataframe, timeperiod=14)

        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]
        dataframe["dist_to_mid"] = (dataframe["close"] - dataframe["bb_middle"]) / dataframe["bb_middle"]
        dataframe["volume_ma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # GridDCA专用：下影线
        dataframe["lower_shadow"] = (dataframe[["open", "close"]].min(axis=1) - dataframe["low"]) / dataframe["close"]

        # === SwingTrend 专用指标 ===
        dataframe["ema9"] = ta.EMA(dataframe, timeperiod=9)
        dataframe["ema21"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)

        # EMA交叉检测
        dataframe["ema_cross_up"] = (
            (dataframe["ema9"] > dataframe["ema21"])
            & (dataframe["ema9"].shift(1) <= dataframe["ema21"].shift(1))
        )
        dataframe["ema_gap_pct"] = (dataframe["ema9"] - dataframe["ema21"]) / dataframe["ema21"]
        dataframe["recent_cross_count"] = dataframe["ema_cross_up"].rolling(window=12).sum()

        # === 1h 时间框架 ===
        if self.dp:
            informative = self.dp.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.informative_timeframe
            )
            if not informative.empty:
                informative["ema9_1h"] = ta.EMA(informative, timeperiod=9)
                informative["ema21_1h"] = ta.EMA(informative, timeperiod=21)
                informative["ema50_1h"] = ta.EMA(informative, timeperiod=50)
                informative["rsi14_1h"] = ta.RSI(informative, timeperiod=14)
                informative["adx14_1h"] = ta.ADX(informative, timeperiod=14)

                # Supertrend
                st_values, st_direction = supertrend(informative, period=10, multiplier=3.0)
                informative["supertrend_1h"] = st_values
                informative["supertrend_dir_1h"] = st_direction

                dataframe = merge_informative_pair(
                    dataframe, informative, self.timeframe, self.informative_timeframe, ffill=True
                )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """三策略入场信号合并"""

        if "ema9_1h_1h" not in dataframe.columns:
            dataframe["enter_long"] = 0
            return dataframe

        # === 时间过滤：禁止高风险时段入场 ===
        # UTC 18-19: 最大亏损时段（7笔亏5笔）
        # UTC 0: 凌晨流动性差，假信号多
        safe_hours = ~dataframe["date"].dt.hour.isin([0, 18, 19])

        # === 1. Scalping: BB下轨深度反弹（原版14条件）===
        uptrend_1h = dataframe["ema9_1h_1h"] > dataframe["ema21_1h_1h"]
        not_crashing = dataframe["rsi14_1h_1h"] > 35
        not_overbought_1h = dataframe["rsi14_1h_1h"] < 75

        scalping_entry = (
            uptrend_1h
            & not_crashing
            & not_overbought_1h
            & (dataframe["low"] <= dataframe["bb_lower"])
            & (dataframe["close"] > dataframe["bb_lower"])
            & (dataframe["close"] > dataframe["bb_lower"] * 1.003)
            & (dataframe["rsi7"] < 30)
            & (dataframe["rsi7"] > dataframe["rsi7"].shift(1))
            & (dataframe["rsi14"] < 40)
            & (dataframe["dist_to_mid"] < -0.01)
            & (dataframe["volume"] > dataframe["volume_ma"] * 1.2)
            & (dataframe["volume"] > 0)
            & (dataframe["bb_width"] > 0.02)
        )

        # === 2. GridDCA: BB下轨+下影线+连续超卖 ===
        grid_entry = (
            uptrend_1h
            & (dataframe["rsi14_1h_1h"] > 38)
            & not_overbought_1h
            & (dataframe["low"] <= dataframe["bb_lower"])
            & (dataframe["close"] > dataframe["bb_lower"])
            & (dataframe["close"] > dataframe["bb_lower"] * 1.003)
            & (dataframe["lower_shadow"] > 0.003)
            & (dataframe["rsi7"] < 28)
            & (dataframe["rsi7"] > dataframe["rsi7"].shift(1))
            & (dataframe["rsi14"] < 38)
            & (dataframe["rsi7"].shift(1) < 30)
            & (dataframe["dist_to_mid"] < -0.012)
            & (dataframe["volume"] > dataframe["volume_ma"] * 1.1)
            & (dataframe["volume"] > 0)
            & (dataframe["bb_width"] > 0.025)
        )

        # === 3. SwingTrend: 1h Supertrend + 5m EMA金叉 ===
        swing_entry = (
            (dataframe["supertrend_dir_1h_1h"] == 1)
            & (dataframe["ema9_1h_1h"] > dataframe["ema21_1h_1h"])
            & (dataframe["ema21_1h_1h"] > dataframe["ema50_1h_1h"])
            & (dataframe["adx14_1h_1h"] > 25)
            & (dataframe["rsi14_1h_1h"] > 45)
            & (dataframe["rsi14_1h_1h"] < 65)
            & (dataframe["ema_cross_up"])
            & (dataframe["close"] > dataframe["ema21"])
            & (dataframe["close"] > dataframe["bb_middle"])
            & (dataframe["rsi14"] > 45)
            & (dataframe["rsi14"] < 60)
            & (dataframe["rsi14"] > dataframe["rsi14"].shift(1))
            & (dataframe["recent_cross_count"] <= 1)
            & (dataframe["bb_width"] > 0.02)
            & (dataframe["volume"] > dataframe["volume_ma"] * 1.2)
            & (dataframe["volume"] > 0)
        )

        # 按优先级标记（避免同一根K线多个信号）
        # Scalping优先（最高胜率），然后GridDCA，最后SwingTrend
        dataframe.loc[swing_entry & safe_hours, ["enter_long", "enter_tag"]] = (1, "swing_trend")
        dataframe.loc[grid_entry & safe_hours, ["enter_long", "enter_tag"]] = (1, "mean_revert")
        dataframe.loc[scalping_entry & safe_hours, ["enter_long", "enter_tag"]] = (1, "bb_deep_bounce")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        """根据enter_tag使用不同的出场逻辑"""

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None

        last = dataframe.iloc[-1]
        trade_duration = (current_time - trade.open_date_utc).total_seconds()
        tag = trade.enter_tag or ""

        if tag == "bb_deep_bounce":
            return self._exit_scalping(last, trade_duration, current_rate, current_profit)
        elif tag == "mean_revert":
            return self._exit_grid(last, trade_duration, current_rate, current_profit)
        elif tag == "swing_trend":
            return self._exit_swing(last, trade_duration, current_rate, current_profit)

        # 默认出场（兜底）
        if current_profit > 0.01:
            return "profit_lock"
        if trade_duration > 21600 and current_profit > -0.005:
            return "timeout_cut"
        return None

    def _exit_scalping(self, last, trade_duration, current_rate, current_profit):
        """Scalping出场逻辑"""
        if current_rate >= last["bb_middle"] and current_profit > 0.003:
            return "bb_middle_target"
        if current_profit > 0.01:
            return "profit_lock"
        if current_profit > 0.007 and last.get("rsi7", 50) > 50:
            return "profit_rsi_exit"
        if last.get("rsi7", 50) > 65 and current_profit > 0.004:
            return "rsi_neutral"
        if trade_duration > 10800 and current_profit > 0.002:
            return "time_profit"
        if trade_duration > 21600 and current_profit > -0.005:
            return "timeout_cut"
        return None

    def _exit_grid(self, last, trade_duration, current_rate, current_profit):
        """GridDCA出场逻辑"""
        if current_rate >= last["bb_middle"] and current_profit > 0.003:
            return "mr_target"
        if current_profit > 0.01:
            return "mr_profit_lock"
        if current_profit > 0.007 and last.get("rsi7", 50) > 50:
            return "mr_profit_rsi"
        if last.get("rsi7", 50) > 60 and current_profit > 0.003:
            return "mr_rsi_exit"
        if trade_duration > 10800 and current_profit > 0.002:
            return "mr_time_profit"
        if trade_duration > 21600 and current_profit > 0:
            return "mr_timeout"
        if trade_duration > 7200 and current_profit < -0.01:
            return "mr_revert_fail"
        return None

    def _exit_swing(self, last, trade_duration, current_rate, current_profit):
        """SwingTrend出场逻辑（原止损-1.5%，通过custom_exit实现）"""
        # SwingTrend专用提前止损（-1.5%，比全局-2%更紧）
        if current_profit < -0.015:
            return "swing_early_stop"
        if "supertrend_dir_1h_1h" in last and last["supertrend_dir_1h_1h"] == -1:
            if current_profit > 0:
                return "swing_supertrend_exit"
        if (last.get("ema9", 0) < last.get("ema21", 0)) and current_profit > 0.003:
            return "swing_ema_cross"
        if current_profit > 0.01:
            return "swing_profit_lock"
        if current_profit > 0.007 and last.get("rsi14", 50) > 55:
            return "swing_profit_rsi"
        if "rsi14_1h_1h" in last and last["rsi14_1h_1h"] > 70 and current_profit > 0.005:
            return "swing_rsi_exit"
        if trade_duration > 43200 and current_profit > 0.002:
            return "swing_timeout"
        return None
