"""
YoloStrategy — 10U 搏大合约策略（Auto-Evo V2）
10x杠杆 + 只做多 + trailing stop 让利润奔跑

回测结果（2024.3-2026.3，4币对 DOGE/AVAX/XRP/ATOM）：
- 10U → 66.6U，+566%
- 109笔交易，67.9%胜率
- 最大回撤28.59%
- Train(648%,72.4%) / Test(-12%,57.6%) — test段市场-20.77%

Auto-Evo优化：
- 去掉LINK（-103%拖后腿）→ 利润305%→566%
- trailing_stop 1.5%/2.5%（更早锁利）→ 全面优于基线2%/3%

核心逻辑：
- 入场：BB下轨深度反弹 + RSI超卖回升 + 1h趋势向上 + 放量
- 出场：trailing stop（利润>2.5%后回撤1.5%平仓）/ BB中轨目标 / 超时4h
- 止损：-5%（10x下价格跌0.5%触发，每笔最多亏5U）
"""
import json
import logging
from pathlib import Path

import talib.abstract as ta
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame

logger = logging.getLogger(__name__)

# 情绪状态文件路径
SENTIMENT_FILE = Path("/freqtrade/user_data/yolo_sentiment.json")


class YoloStrategy(IStrategy):
    """10U 合约搏大策略 — 10x杠杆只做多"""

    INTERFACE_VERSION = 3

    timeframe = "5m"
    informative_timeframe = "1h"
    startup_candle_count = 200

    # 只做多（做空在牛市中逆势）
    can_short = False

    # 不设固定ROI，让trailing stop管理出场
    minimal_roi = {"0": 1}

    # 止损 -5%（10x下价格只需跌0.5%）
    stoploss = -0.05
    use_custom_stoploss = False

    # 移动止盈：利润>2.5%后，回撤1.5%就平仓（Auto-Evo最优）
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.025
    trailing_only_offset_is_reached = True

    position_adjustment_enable = False

    def _get_sentiment(self) -> dict:
        """读取情绪状态文件"""
        try:
            if SENTIMENT_FILE.exists():
                data = json.loads(SENTIMENT_FILE.read_text())
                # 检查是否过期（>8小时）
                from datetime import datetime, timezone, timedelta
                ts = datetime.fromisoformat(data.get("timestamp", "2000-01-01T00:00:00+00:00"))
                if datetime.now(timezone.utc) - ts > timedelta(hours=8):
                    return {"sentiment": 0.0, "action": "NORMAL"}
                return data
        except Exception as e:
            logger.warning(f"读取情绪文件失败: {e}")
        return {"sentiment": 0.0, "action": "NORMAL"}

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force, current_time, entry_tag, side, **kwargs):
        """情绪过滤：极度恐慌时阻止开仓"""
        sentiment = self._get_sentiment()
        action = sentiment.get("action", "NORMAL")

        if action == "BLOCK":
            logger.info(f"情绪过滤：{pair} 入场被阻止（sentiment={sentiment.get('sentiment', 0):.2f}, BLOCK）")
            return False

        return True

    def leverage(self, pair, current_time, current_rate, proposed_leverage, max_leverage, entry_tag, side, **kwargs):
        """固定10x杠杆"""
        return 10.0

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative_timeframe) for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算指标"""

        # RSI
        dataframe["rsi7"] = ta.RSI(dataframe, timeperiod=7)
        dataframe["rsi14"] = ta.RSI(dataframe, timeperiod=14)

        # 布林带
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]

        # 收盘价距BB中轨距离
        dataframe["dist_to_mid"] = (dataframe["close"] - dataframe["bb_middle"]) / dataframe["bb_middle"]

        # 成交量均线
        dataframe["volume_ma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # === 1h 时间框架 ===
        if self.dp:
            informative = self.dp.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.informative_timeframe
            )
            if not informative.empty:
                informative["ema9_1h"] = ta.EMA(informative, timeperiod=9)
                informative["ema21_1h"] = ta.EMA(informative, timeperiod=21)

                dataframe = merge_informative_pair(
                    dataframe, informative, self.timeframe, self.informative_timeframe, ffill=True
                )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """做多入场信号：BB下轨深度反弹"""

        if "ema9_1h_1h" not in dataframe.columns:
            dataframe["enter_long"] = 0
            return dataframe

        # 1h 趋势向上
        uptrend_1h = dataframe["ema9_1h_1h"] > dataframe["ema21_1h_1h"]

        # BB下轨深度反弹 + RSI超卖 + 放量
        long_entry = (
            uptrend_1h
            & (dataframe["low"] <= dataframe["bb_lower"])
            & (dataframe["close"] > dataframe["bb_lower"] * 1.003)  # 强反弹确认
            & (dataframe["rsi7"] < 30)  # 深度超卖
            & (dataframe["rsi7"] > dataframe["rsi7"].shift(1))  # RSI回升
            & (dataframe["rsi14"] < 40)  # RSI14也偏低
            & (dataframe["dist_to_mid"] < -0.01)  # 远离中轨
            & (dataframe["bb_width"] > 0.02)  # BB有足够宽度
            & (dataframe["volume"] > dataframe["volume_ma"] * 1.2)  # 放量
        )

        dataframe.loc[long_entry, ["enter_long", "enter_tag"]] = (1, "yolo_long")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """不使用信号出场，全靠ROI/止损/custom_exit"""
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        """自定义出场：BB中轨目标 + RSI反转 + 超时平仓"""

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None

        last = dataframe.iloc[-1]
        trade_duration = (current_time - trade.open_date_utc).total_seconds()

        # BB中轨目标（利润>1%就走）
        if current_profit > 0.01 and current_rate >= last["bb_middle"]:
            return "bb_mid_target"

        # 利润>3%时RSI反转出场
        if current_profit > 0.03 and last.get("rsi7", 50) > 65:
            return "rsi_profit_exit"

        # 超时4小时平仓（不恋战）
        if trade_duration > 14400 and current_profit > -0.01:
            return "timeout_4h"

        return None
