"""
均值回归策略 GridDCAStrategy v8
- v8: 回退到v6出场，加反弹力度确认（close > bb_lower * 1.003）
- v9牛市过滤测试失败（+5.48% vs v8 +6.69%），回退
- 固定止损 -2%，禁用trailing和custom_stoploss
"""
import logging

import talib.abstract as ta
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame

logger = logging.getLogger(__name__)


class GridDCAStrategy(IStrategy):
    """
    均值回归 v5 — 极严格BB下轨反弹，单次入场，只在盈利时出场
    """

    INTERFACE_VERSION = 3

    timeframe = "5m"
    informative_timeframe = "1h"
    startup_candle_count = 200
    can_short = False

    # ROI 2% 兜底（测试：让快速冲高的交易赚更多）
    minimal_roi = {"0": 0.02}

    # 固定止损 -2%（v6: 从-1.5%回退，-2.5%回撤更大不值得）
    stoploss = -0.02
    use_custom_stoploss = False
    trailing_stop = False

    # 禁用DCA
    position_adjustment_enable = False

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative_timeframe) for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """技术指标"""

        # RSI
        dataframe["rsi7"] = ta.RSI(dataframe, timeperiod=7)
        dataframe["rsi14"] = ta.RSI(dataframe, timeperiod=14)

        # BB(20,2)
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]

        # BB宽度
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]

        # 收盘价到BB中轨的距离
        dataframe["dist_to_mid"] = (dataframe["close"] - dataframe["bb_middle"]) / dataframe["bb_middle"]

        # 成交量
        dataframe["volume_ma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # 下影线长度（反弹力度）
        dataframe["lower_shadow"] = (dataframe[["open", "close"]].min(axis=1) - dataframe["low"]) / dataframe["close"]

        # 1h 时间框架
        if self.dp:
            informative = self.dp.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.informative_timeframe
            )
            if not informative.empty:
                informative["ema9_1h"] = ta.EMA(informative, timeperiod=9)
                informative["ema21_1h"] = ta.EMA(informative, timeperiod=21)
                informative["rsi14_1h"] = ta.RSI(informative, timeperiod=14)
                dataframe = merge_informative_pair(
                    dataframe, informative, self.timeframe, self.informative_timeframe, ffill=True
                )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """入场 — BB下轨深度反弹（回退到v3严格度）"""

        if "ema9_1h_1h" not in dataframe.columns:
            dataframe["enter_long"] = 0
            return dataframe

        conditions = (
            # 1h 大趋势向上
            (dataframe["ema9_1h_1h"] > dataframe["ema21_1h_1h"])
            # 1h RSI不在崩盘中
            & (dataframe["rsi14_1h_1h"] > 38)
            # 触及BB下轨
            & (dataframe["low"] <= dataframe["bb_lower"])
            # 收盘在下轨上方（反弹确认）
            & (dataframe["close"] > dataframe["bb_lower"])
            # v8: 反弹力度确认（学习ScalpingStrategy）
            & (dataframe["close"] > dataframe["bb_lower"] * 1.003)
            # 下影线反弹力度
            & (dataframe["lower_shadow"] > 0.003)
            # RSI7深度超卖
            & (dataframe["rsi7"] < 28)
            # RSI7回升（反弹信号）
            & (dataframe["rsi7"] > dataframe["rsi7"].shift(1))
            # RSI14也偏低
            & (dataframe["rsi14"] < 38)
            # 前一根也超卖（连续超卖确认）
            & (dataframe["rsi7"].shift(1) < 30)
            # 离BB中轨至少1.2%
            & (dataframe["dist_to_mid"] < -0.012)
            # 放量
            & (dataframe["volume"] > dataframe["volume_ma"] * 1.1)
            & (dataframe["volume"] > 0)
            # BB宽度要求
            & (dataframe["bb_width"] > 0.025)
        )

        dataframe.loc[conditions, ["enter_long", "enter_tag"]] = (1, "mean_revert")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """出场留给 custom_exit"""
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        """出场控制 — 只在盈利时出场，亏损交给止损"""

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None

        last = dataframe.iloc[-1]
        trade_duration = (current_time - trade.open_date_utc).total_seconds()

        # === 1. BB中轨目标（核心盈利出场）===
        if current_rate >= last["bb_middle"] and current_profit > 0.003:
            return "mr_target"

        # === 2. 利润保护 ===
        if current_profit > 0.01:
            return "mr_profit_lock"
        if current_profit > 0.007 and last["rsi7"] > 50:
            return "mr_profit_rsi"

        # === 3. RSI回到中性 ===
        if last["rsi7"] > 60 and current_profit > 0.003:
            return "mr_rsi_exit"

        # === 4. 超时管理（3小时有利润就走）===
        if trade_duration > 10800 and current_profit > 0.002:
            return "mr_time_profit"

        # === 5. 长超时（6小时，只在盈利时出场）===
        if trade_duration > 21600 and current_profit > 0:
            return "mr_timeout"

        # === 6. 均值回归失败（2小时仍亏损超-1%，趋势可能已反转）===
        if trade_duration > 7200 and current_profit < -0.01:
            return "mr_revert_fail"

        return None
