"""
策略单元测试 — 验证核心逻辑
"""
import sys
import os
import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from risk.manager import RiskManager, RiskConfig


class TestRiskManager:
    """风控引擎测试"""

    def setup_method(self):
        self.rm = RiskManager()

    def test_default_config(self):
        """默认风控参数正确"""
        assert self.rm.config.max_loss_per_trade == -0.02
        assert self.rm.config.max_profit_per_trade == 0.04
        assert self.rm.config.max_open_trades == 3
        assert self.rm.config.daily_max_loss == -0.05
        assert self.rm.config.max_consecutive_losses == 5

    def test_can_open_trade_normal(self):
        """正常情况允许开仓"""
        result = self.rm.can_open_trade(sentiment_score=0.0)
        assert result["allowed"] is True

    def test_sentiment_veto(self):
        """情绪否决：极度恐慌不开多仓"""
        result = self.rm.can_open_trade(sentiment_score=-0.7, side="long")
        assert result["allowed"] is False
        assert "情绪" in result["reason"]

    def test_sentiment_veto_short_allowed(self):
        """情绪否决不影响空仓（如果支持）"""
        result = self.rm.can_open_trade(sentiment_score=-0.7, side="short")
        assert result["allowed"] is True

    def test_daily_loss_limit(self):
        """日亏损达到上限后停止交易"""
        # 模拟连续亏损
        for _ in range(3):
            self.rm.record_trade(-0.02)
        result = self.rm.can_open_trade()
        assert result["allowed"] is False
        assert "日亏损" in result["reason"]

    def test_consecutive_loss_pause(self):
        """连续亏损 5 笔后暂停"""
        for _ in range(5):
            self.rm.record_trade(-0.01)
        assert self.rm.is_paused() is True

    def test_consecutive_loss_reset_on_win(self):
        """盈利后重置连续亏损计数"""
        for _ in range(3):
            self.rm.record_trade(-0.01)
        assert self.rm.state["consecutive_losses"] == 3
        self.rm.record_trade(0.02)
        assert self.rm.state["consecutive_losses"] == 0

    def test_position_size_by_sentiment(self):
        """仓位大小随情绪调整"""
        # 偏多 → 最大仓位
        result = self.rm.can_open_trade(sentiment_score=0.6)
        assert result["position_size"] == 0.20

        # 中性 → 中等仓位
        rm2 = RiskManager()
        result = rm2.can_open_trade(sentiment_score=0.0)
        assert abs(result["position_size"] - 0.15) < 1e-9

        # 偏空 → 最小仓位
        rm3 = RiskManager()
        result = rm3.can_open_trade(sentiment_score=-0.3)
        assert result["position_size"] == 0.10

    def test_status_report(self):
        """状态报告格式正确"""
        status = self.rm.get_status()
        assert "daily_pnl" in status
        assert "consecutive_losses" in status
        assert "is_paused" in status


class TestSentimentCache:
    """情绪缓存测试"""

    def test_cache_set_get(self, tmp_path):
        from sentiment.cache import SentimentCache
        cache = SentimentCache(cache_file=tmp_path / "cache.json", ttl=3600)
        cache.set({"score": 0.3, "reason": "测试"})
        result = cache.get()
        assert result is not None
        assert result["score"] == 0.3

    def test_cache_expired(self, tmp_path):
        from sentiment.cache import SentimentCache
        cache = SentimentCache(cache_file=tmp_path / "cache.json", ttl=0)
        cache.set({"score": 0.3, "reason": "测试"})
        # TTL=0 立即过期
        import time
        time.sleep(0.1)
        result = cache.get()
        assert result is None

    def test_cache_max_age(self, tmp_path):
        """自定义 max_age 参数覆盖默认 TTL"""
        from sentiment.cache import SentimentCache
        cache = SentimentCache(cache_file=tmp_path / "cache.json", ttl=0)
        cache.set({"score": 0.5, "reason": "测试"})
        # TTL=0 但 max_age=7200 应该能获取到
        result = cache.get(max_age=7200)
        assert result is not None
        assert result["score"] == 0.5


class TestTradeMemory:
    """交易记忆系统测试"""

    def setup_method(self, tmp_path=None):
        from memory.trade_memory import TradeMemory
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_memory.db")
        self.tm = TradeMemory(db_path=self.db_path)

    def test_record_and_find(self):
        """记录交易并检索相似案例"""
        features = {"adx": 30, "atr_pct": 2.0, "rsi": 45, "bb_width": 0.05, "sentiment_score": 0.3}
        self.tm.record("BTC/USDT", "long", "trend_ema_cross", features, pnl_pct=0.02)
        self.tm.record("BTC/USDT", "long", "trend_ema_cross", features, pnl_pct=-0.01)

        similar = self.tm.find_similar(features)
        assert len(similar) == 2

    def test_similar_win_rate(self):
        """相似环境胜率计算"""
        features = {"adx": 30, "atr_pct": 2.0, "rsi": 45, "bb_width": 0.05, "sentiment_score": 0.3}
        # 录入 10 笔交易：7 赢 3 亏
        for i in range(7):
            self.tm.record("BTC/USDT", "long", "trend", features, pnl_pct=0.02)
        for i in range(3):
            self.tm.record("BTC/USDT", "long", "trend", features, pnl_pct=-0.01)

        result = self.tm.similar_win_rate(features, min_trades=5)
        assert result["sufficient"] is True
        assert abs(result["win_rate"] - 0.7) < 0.01

    def test_insufficient_data(self):
        """数据不足时返回默认值"""
        features = {"adx": 30, "atr_pct": 2.0, "rsi": 45}
        result = self.tm.similar_win_rate(features, min_trades=5)
        assert result["sufficient"] is False
        assert result["win_rate"] == 0.5

    def test_performance_report_empty(self):
        """空数据库的绩效报告"""
        report = self.tm.performance_report()
        assert report["total_trades"] == 0

    def test_performance_report_with_data(self):
        """有数据时的绩效归因报告"""
        # 趋势市场交易
        self.tm.record("BTC/USDT", "long", "trend", {"adx": 30, "atr_pct": 2.0, "rsi": 50, "bb_width": 0.05, "sentiment_score": 0.3}, pnl_pct=0.03)
        # 震荡市场交易
        self.tm.record("ETH/USDT", "long", "revert", {"adx": 15, "atr_pct": 1.0, "rsi": 28, "bb_width": 0.03, "sentiment_score": 0.0}, pnl_pct=-0.01)

        report = self.tm.performance_report()
        assert report["total_trades"] == 2
        assert "trending" in report["by_regime"]
        assert "ranging" in report["by_regime"]


class TestDynamicPositionSizing:
    """动态仓位管理测试"""

    def setup_method(self):
        self.rm = RiskManager()

    def test_high_vol_min_position(self):
        """高波动 → 固定最小仓位"""
        result = self.rm.can_open_trade(
            sentiment_score=0.3,
            market_context={"adx": 30, "atr_pct": 4.0, "is_high_vol": True}
        )
        assert result["allowed"] is True
        assert result["position_size"] == 0.10
        assert result["sizing_mode"] == "fixed"

    def test_trending_kelly(self):
        """趋势市场 + 足够历史 → Kelly 公式"""
        rm = RiskManager()
        # 填充 10 笔历史交易
        for _ in range(7):
            rm.record_trade(0.03)
        for _ in range(3):
            rm.record_trade(-0.015)

        result = rm.can_open_trade(
            sentiment_score=0.3,
            market_context={"adx": 30, "atr_pct": 2.0, "is_high_vol": False}
        )
        assert result["allowed"] is True
        assert result["sizing_mode"] == "kelly"
        assert 0.10 <= result["position_size"] <= 0.20

    def test_ranging_atr(self):
        """震荡市场 → ATR 仓位法"""
        result = self.rm.can_open_trade(
            sentiment_score=0.0,
            market_context={"adx": 15, "atr_pct": 2.0, "is_high_vol": False}
        )
        assert result["allowed"] is True
        assert result["sizing_mode"] == "atr"
        assert 0.10 <= result["position_size"] <= 0.20

    def test_no_context_fallback(self):
        """无市场上下文 → 回退到固定比例"""
        result = self.rm.can_open_trade(sentiment_score=0.0)
        assert result["allowed"] is True
        assert result["sizing_mode"] == "fixed"

    def test_kelly_insufficient_history(self):
        """Kelly 历史不足 → 回退到固定比例"""
        result = self.rm.can_open_trade(
            sentiment_score=0.3,
            market_context={"adx": 30, "atr_pct": 2.0, "is_high_vol": False}
        )
        # 没有历史交易，Kelly 回退
        assert result["sizing_mode"] == "fixed"


class TestNewsFetcherDegradation:
    """新闻采集降级测试"""

    def test_fetch_all_returns_dict(self):
        """fetch_all 返回字典格式（含降级信息）"""
        from sentiment.news_fetcher import NewsFetcher
        fetcher = NewsFetcher()
        # 不实际请求网络，只验证返回格式
        result = fetcher.fetch_all(limit=5)
        assert isinstance(result, dict)
        assert "news" in result
        assert "source_status" in result
        assert "degraded" in result
