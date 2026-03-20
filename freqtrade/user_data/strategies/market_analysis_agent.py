"""
AI市场分析Agent — 用Claude分析BTC技术面+新闻情绪，输出市场状态预测
设计为live/dry-run时每4小时运行一次
输出：BULL/BEAR/RANGE + 置信度 + 建议的策略权重

这个agent不改变回测结果，而是在实盘中提供额外的决策支持：
1. 分析BTC 1h/4h/1d K线形态
2. 分析新闻情绪
3. 输出市场状态预测和策略建议
4. 写入共享文件，各策略可读取
"""
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# 策略权重建议（基于市场矩阵回测结果）
STRATEGY_WEIGHTS = {
    "BULL": {
        "ScalpingStrategy": 0.40,   # 牛市也赚（+25.9U）
        "GridDCAStrategy": 0.10,    # 牛市微亏（-0.6U）
        "SwingTrendStrategy": 0.50, # 牛市最强（+13.5U）
    },
    "BEAR": {
        "ScalpingStrategy": 0.70,   # 熊市也赚（+17.7U）
        "GridDCAStrategy": 0.20,    # 熊市微赚（+1.0U）
        "SwingTrendStrategy": 0.10, # 熊市亏损（-3.4U）
    },
    "RANGE": {
        "ScalpingStrategy": 0.40,   # 震荡赚（+33.5U）
        "GridDCAStrategy": 0.40,    # 震荡最强（+17.9U）
        "SwingTrendStrategy": 0.20, # 震荡微赚（+3.3U）
    },
}

ANALYSIS_PROMPT = """你是一个专业的加密货币市场分析师。根据以下BTC技术数据和新闻，判断当前市场状态。

## BTC技术数据（1h级别）
{technical_data}

## 最近新闻
{news_data}

## 任务
1. 判断当前市场状态：BULL（看涨）/ BEAR（看跌）/ RANGE（震荡）
2. 给出置信度（0-100）
3. 简要说明理由（50字以内）

## 输出格式（严格JSON）
{{"regime": "BULL/BEAR/RANGE", "confidence": 75, "reason": "..."}}"""


class MarketAnalysisAgent:
    """AI市场分析Agent"""

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client = None
        self.state_file = Path("/freqtrade/user_data/market_state.json")
        self.last_analysis = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def get_technical_summary(self, dataframe) -> str:
        """从1h K线数据生成技术摘要"""
        if dataframe is None or dataframe.empty:
            return "无数据"

        last = dataframe.iloc[-1]
        prev_24h = dataframe.iloc[-24] if len(dataframe) >= 24 else dataframe.iloc[0]
        prev_7d = dataframe.iloc[-168] if len(dataframe) >= 168 else dataframe.iloc[0]

        # 价格变化
        price = last["close"]
        change_24h = (price - prev_24h["close"]) / prev_24h["close"] * 100
        change_7d = (price - prev_7d["close"]) / prev_7d["close"] * 100

        # EMA
        import talib.abstract as ta
        ema9 = ta.EMA(dataframe, timeperiod=9).iloc[-1]
        ema21 = ta.EMA(dataframe, timeperiod=21).iloc[-1]
        ema50 = ta.EMA(dataframe, timeperiod=50).iloc[-1]

        # RSI
        rsi14 = ta.RSI(dataframe, timeperiod=14).iloc[-1]

        # ADX
        adx = ta.ADX(dataframe, timeperiod=14).iloc[-1]

        # BB
        bb = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        bb_upper = bb["upperband"].iloc[-1]
        bb_lower = bb["lowerband"].iloc[-1]
        bb_width = (bb_upper - bb_lower) / last["close"] * 100

        # EMA排列
        if ema9 > ema21 > ema50:
            ema_state = "多头排列（EMA9>21>50）"
        elif ema9 < ema21 < ema50:
            ema_state = "空头排列（EMA9<21<50）"
        else:
            ema_state = "交叉混乱"

        summary = f"""BTC/USDT 当前价格: ${price:.0f}
24h变化: {change_24h:+.2f}%
7d变化: {change_7d:+.2f}%
EMA状态: {ema_state} (EMA9={ema9:.0f}, EMA21={ema21:.0f}, EMA50={ema50:.0f})
RSI(14): {rsi14:.1f}
ADX(14): {adx:.1f} ({'有趋势' if adx > 25 else '无趋势/震荡'})
BB宽度: {bb_width:.2f}%
价格位置: {'接近上轨' if price > (bb_upper + bb_lower)/2 else '接近下轨'}"""

        return summary

    def analyze(self, technical_data: str, news_data: str = "无最新新闻") -> dict:
        """调用Claude分析市场状态"""
        prompt = ANALYSIS_PROMPT.format(
            technical_data=technical_data,
            news_data=news_data,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            result = json.loads(response.content[0].text)
            result["timestamp"] = datetime.utcnow().isoformat() + "Z"
            result["weights"] = STRATEGY_WEIGHTS.get(result.get("regime", "RANGE"), STRATEGY_WEIGHTS["RANGE"])
            return result
        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return {
                "regime": "RANGE",
                "confidence": 0,
                "reason": f"分析失败: {e}",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "weights": STRATEGY_WEIGHTS["RANGE"],
                "fallback": True,
            }

    def save_state(self, state: dict):
        """保存市场状态到共享文件"""
        self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        logger.info(f"市场状态已保存: {state['regime']} (置信度{state['confidence']}%)")

    @staticmethod
    def load_state(state_file: str = "/freqtrade/user_data/market_state.json") -> dict:
        """策略内部调用：读取最新市场状态"""
        path = Path(state_file)
        if not path.exists():
            return {"regime": "RANGE", "confidence": 0, "weights": STRATEGY_WEIGHTS["RANGE"]}
        try:
            state = json.loads(path.read_text())
            # 检查是否过期（>8小时）
            ts = datetime.fromisoformat(state.get("timestamp", "2000-01-01T00:00:00Z").rstrip("Z"))
            if datetime.utcnow() - ts > timedelta(hours=8):
                logger.warning("市场状态已过期(>8h)，使用RANGE默认值")
                return {"regime": "RANGE", "confidence": 0, "weights": STRATEGY_WEIGHTS["RANGE"]}
            return state
        except Exception as e:
            logger.error(f"读取市场状态失败: {e}")
            return {"regime": "RANGE", "confidence": 0, "weights": STRATEGY_WEIGHTS["RANGE"]}
