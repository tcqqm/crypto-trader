"""
Claude 情绪评分模块 — 分析加密新闻情绪
"""
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SentimentScorer:
    """使用 Claude API 对加密新闻进行情绪评分"""

    SYSTEM_PROMPT = """你是一个加密货币市场情绪分析师。
根据提供的新闻标题和摘要，评估市场情绪。
返回 JSON 格式：{"score": float, "reason": str}
score 范围 -1.0（极度恐慌）到 +1.0（极度贪婪）
- -1.0 ~ -0.5: 极度恐慌（监管打击、交易所暴雷、黑天鹅）
- -0.5 ~ -0.2: 偏空（利空消息、资金流出）
- -0.2 ~ 0.2: 中性
- 0.2 ~ 0.5: 偏多（利好消息、资金流入）
- 0.5 ~ 1.0: 极度贪婪（FOMO、全民炒币）"""

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514", fallback_cache=None):
        self.api_key = api_key
        self.model = model
        self._client = None
        self._fallback_cache = fallback_cache  # SentimentCache 实例，用于 API 降级

    @property
    def client(self):
        """延迟初始化 Anthropic 客户端"""
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def score(self, news_items: list[dict]) -> dict:
        """
        对新闻列表进行情绪评分
        news_items: [{"title": str, "summary": str, "source": str}, ...]
        返回: {"score": float, "reason": str, "timestamp": str}
        """
        if not news_items:
            return {"score": 0.0, "reason": "无新闻数据", "timestamp": _now()}

        news_text = "\n".join(
            f"- [{item.get('source', '未知')}] {item['title']}"
            + (f": {item['summary']}" if item.get("summary") else "")
            for item in news_items[:20]  # 最多 20 条
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"分析以下新闻的市场情绪：\n\n{news_text}"}],
            )
            result = json.loads(response.content[0].text)
            result["timestamp"] = _now()
            result["news_count"] = len(news_items)
            return result
        except Exception as e:
            logger.error(f"情绪评分失败: {e}")
            # 降级：尝试使用缓存的最近评分（< 2h）
            if self._fallback_cache:
                cached = self._fallback_cache.get(max_age=7200)
                if cached:
                    logger.warning(f"Claude API 不可用，使用缓存评分: {cached['score']}")
                    cached["fallback"] = True
                    cached["timestamp"] = _now()
                    return cached
            return {"score": 0.0, "reason": f"评分失败且无可用缓存: {e}", "timestamp": _now(), "fallback": True}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"
