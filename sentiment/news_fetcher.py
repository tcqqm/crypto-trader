"""
加密新闻采集模块 — 从 CryptoPanic 和 RSS 获取新闻
"""
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# CryptoPanic 免费 API（无需 key 也可获取公开新闻）
CRYPTOPANIC_API = "https://cryptopanic.com/api/free/v1/posts/"
# 备用 RSS 源
RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]


class NewsFetcher:
    """加密新闻采集器"""

    def __init__(self, cryptopanic_token: str = None):
        self.cryptopanic_token = cryptopanic_token

    def fetch_cryptopanic(self, limit: int = 20) -> list[dict]:
        """从 CryptoPanic 获取新闻"""
        import requests

        params = {"public": "true"}
        if self.cryptopanic_token:
            params["auth_token"] = self.cryptopanic_token

        try:
            resp = requests.get(CRYPTOPANIC_API, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for post in data.get("results", [])[:limit]:
                results.append({
                    "title": post.get("title", ""),
                    "summary": "",
                    "source": post.get("source", {}).get("title", "CryptoPanic"),
                    "url": post.get("url", ""),
                    "published": post.get("published_at", ""),
                })
            return results
        except Exception as e:
            logger.error(f"CryptoPanic 采集失败: {e}")
            return []

    def fetch_rss(self, limit: int = 10) -> list[dict]:
        """从 RSS 源获取新闻"""
        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser 未安装，跳过 RSS 采集")
            return []

        results = []
        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:limit]:
                    results.append({
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", "")[:200],
                        "source": feed.feed.get("title", feed_url),
                        "url": entry.get("link", ""),
                        "published": entry.get("published", ""),
                    })
            except Exception as e:
                logger.error(f"RSS 采集失败 {feed_url}: {e}")
        return results

    def fetch_all(self, limit: int = 20) -> dict:
        """
        采集所有来源的新闻，支持降级策略
        返回: {"news": list, "source_status": dict, "degraded": bool}
        - CryptoPanic 失败 → 降级到 RSS
        - RSS 也失败 → 返回空列表（情绪设为中性）
        """
        source_status = {"cryptopanic": "ok", "rss": "ok"}
        news = []

        # 第一优先级：CryptoPanic
        cp_news = self.fetch_cryptopanic(limit=limit)
        if cp_news:
            news.extend(cp_news)
        else:
            source_status["cryptopanic"] = "failed"
            logger.warning("CryptoPanic 不可用，降级到 RSS")

        # 第二优先级：RSS（CryptoPanic 失败时加大 RSS 采集量）
        rss_limit = limit if not cp_news else limit // 2
        rss_news = self.fetch_rss(limit=rss_limit)
        if rss_news:
            news.extend(rss_news)
        else:
            source_status["rss"] = "failed"
            if not cp_news:
                logger.warning("所有新闻源不可用，情绪将设为中性")

        # 去重（按标题）
        seen = set()
        unique = []
        for item in news:
            if item["title"] not in seen:
                seen.add(item["title"])
                unique.append(item)

        degraded = source_status["cryptopanic"] == "failed" or source_status["rss"] == "failed"
        if degraded:
            logger.info(f"降级模式采集到 {len(unique)} 条新闻，源状态: {source_status}")
        else:
            logger.info(f"采集到 {len(unique)} 条新闻")

        return {
            "news": unique[:limit],
            "source_status": source_status,
            "degraded": degraded,
        }
