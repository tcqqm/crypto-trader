"""
情绪评分缓存 — 避免重复调用 Claude API
"""
import json
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILE = Path(__file__).parent.parent / "results" / "sentiment_cache.json"
CACHE_TTL = 1800  # 30 分钟


class SentimentCache:
    """情绪评分缓存管理"""

    def __init__(self, cache_file: Path = None, ttl: int = CACHE_TTL):
        self.cache_file = cache_file or DEFAULT_CACHE_FILE
        self.ttl = ttl
        self.cache = self._load()

    def _load(self) -> dict:
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(self.cache, indent=2))

    def get(self, max_age: int = None) -> dict | None:
        """
        获取缓存的情绪评分
        max_age: 自定义最大缓存年龄（秒），None 则使用默认 TTL
        """
        if "latest" not in self.cache:
            return None
        entry = self.cache["latest"]
        ttl = max_age if max_age is not None else self.ttl
        if time.time() - entry.get("cached_at", 0) > ttl:
            return None
        return entry

    def set(self, score_data: dict):
        """缓存情绪评分"""
        score_data["cached_at"] = time.time()
        self.cache["latest"] = score_data

        # 保留历史记录（最近 100 条）
        history = self.cache.get("history", [])
        history.append(score_data)
        self.cache["history"] = history[-100:]

        self._save()

    def get_average(self, hours: int = 6) -> float:
        """获取最近 N 小时的平均情绪"""
        cutoff = time.time() - hours * 3600
        history = self.cache.get("history", [])
        recent = [h["score"] for h in history if h.get("cached_at", 0) > cutoff]
        if not recent:
            return 0.0
        return sum(recent) / len(recent)
