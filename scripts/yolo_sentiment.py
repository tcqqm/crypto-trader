#!/usr/bin/env python3
"""
YoloStrategy 情绪分析定时任务
每4小时运行一次：采集新闻 → Gemini评分 → 写入yolo_sentiment.json
YoloStrategy 在 live/dry-run 时读取该文件过滤入场
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sentiment.news_fetcher import NewsFetcher
from sentiment.cache import SentimentCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")
logger = logging.getLogger("yolo_sentiment")

STATE_FILE = Path(__file__).parent.parent / "freqtrade" / "user_data" / "yolo_sentiment.json"


def score_with_keywords(news_items: list[dict]) -> dict:
    """基于关键词的情绪评分（零成本，不依赖LLM API）"""
    BULLISH = [
        "surge", "rally", "bull", "breakout", "all-time high", "ath", "soar",
        "pump", "moon", "adoption", "etf approved", "institutional", "inflow",
        "upgrade", "partnership", "bullish", "recovery", "gain", "rise",
        "buy", "accumulate", "support", "bounce", "green",
    ]
    BEARISH = [
        "crash", "plunge", "bear", "dump", "hack", "exploit", "ban",
        "regulation", "sec", "lawsuit", "fraud", "scam", "bankrupt",
        "liquidat", "outflow", "sell-off", "selloff", "fear", "panic",
        "decline", "drop", "fall", "red", "warning", "risk", "collapse",
    ]

    bull_count = 0
    bear_count = 0
    for item in news_items:
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        for kw in BULLISH:
            if kw in text:
                bull_count += 1
        for kw in BEARISH:
            if kw in text:
                bear_count += 1

    total = bull_count + bear_count
    if total == 0:
        score = 0.0
        reason = "无明显情绪信号"
    else:
        # 归一化到 [-1, 1]
        score = (bull_count - bear_count) / total
        reason = f"看多关键词{bull_count}个，看空关键词{bear_count}个"

    return {
        "score": round(score, 2),
        "reason": reason,
        "news_count": len(news_items),
        "bull_count": bull_count,
        "bear_count": bear_count,
    }


def run():
    # 1. 采集新闻
    fetcher = NewsFetcher()
    result = fetcher.fetch_all(limit=20)
    news = result["news"]
    logger.info(f"采集到 {len(news)} 条新闻")

    if not news:
        state = {"sentiment": 0.0, "action": "NORMAL", "reason": "无新闻数据", "news_count": 0}
        _save_state(state)
        return

    # 2. 关键词情绪评分（零成本，不依赖LLM API）
    cache = SentimentCache()
    score_result = score_with_keywords(news)
    score_result["cached_at"] = __import__("time").time()
    cache.set(score_result)

    # 3. 生成交易建议
    sentiment = score_result.get("score", 0.0)
    if sentiment < -0.5:
        action = "BLOCK"
    elif sentiment < -0.2:
        action = "CAUTION"
    elif sentiment > 0.5:
        action = "AGGRESSIVE"
    else:
        action = "NORMAL"

    state = {
        "sentiment": sentiment,
        "action": action,
        "reason": score_result.get("reason", ""),
        "news_count": len(news),
        "degraded": result.get("degraded", False),
        "fallback": score_result.get("fallback", False),
    }
    _save_state(state)
    logger.info(f"情绪: {sentiment:.2f} ({action}) — {score_result.get('reason', '')}")


def _save_state(state: dict):
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    logger.info(f"状态已写入 {STATE_FILE}")


if __name__ == "__main__":
    run()
