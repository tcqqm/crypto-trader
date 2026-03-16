"""
交易记忆系统 — SQLite 存储交易环境特征 + 相似案例检索
来源：TradingAgents 交易记忆 + ai-investment-advisor 决策记忆
"""
import json
import math
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "results" / "trade_memory.db"


class TradeMemory:
    """交易记忆：记录市场环境特征和交易结果，支持相似案例检索"""

    def __init__(self, db_path: str = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    side TEXT NOT NULL DEFAULT 'long',
                    entry_tag TEXT DEFAULT '',
                    -- 市场环境特征
                    adx REAL DEFAULT 0,
                    atr_pct REAL DEFAULT 0,
                    rsi REAL DEFAULT 0,
                    bb_width REAL DEFAULT 0,
                    sentiment_score REAL DEFAULT 0,
                    bull_score REAL DEFAULT 0,
                    bear_score REAL DEFAULT 0,
                    -- 交易结果
                    pnl_pct REAL DEFAULT 0,
                    duration_minutes INTEGER DEFAULT 0,
                    exit_reason TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_pair ON trades(pair)
            """)

    def record(self, pair: str, side: str, entry_tag: str,
               features: dict, pnl_pct: float = 0.0,
               duration_minutes: int = 0, exit_reason: str = ""):
        """记录一笔交易及其市场环境特征"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO trades (timestamp, pair, side, entry_tag,
                    adx, atr_pct, rsi, bb_width, sentiment_score,
                    bull_score, bear_score,
                    pnl_pct, duration_minutes, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                pair, side, entry_tag,
                features.get("adx", 0),
                features.get("atr_pct", 0),
                features.get("rsi", 0),
                features.get("bb_width", 0),
                features.get("sentiment_score", 0),
                features.get("bull_score", 0),
                features.get("bear_score", 0),
                pnl_pct, duration_minutes, exit_reason,
            ))
        logger.info(f"记录交易: {pair} {side} pnl={pnl_pct:.2%}")

    def find_similar(self, features: dict, limit: int = 20) -> list[dict]:
        """
        检索相似市场环境的历史交易
        使用欧氏距离计算特征相似度（归一化后）
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT 500"
            ).fetchall()

        if not rows:
            return []

        # 归一化参考范围
        norm = {
            "adx": 50.0, "atr_pct": 5.0, "rsi": 100.0,
            "bb_width": 0.1, "sentiment_score": 2.0,
        }
        target = {k: features.get(k, 0) / norm.get(k, 1) for k in norm}

        scored = []
        for row in rows:
            row_dict = dict(row)
            dist = math.sqrt(sum(
                (target[k] - row_dict.get(k, 0) / norm.get(k, 1)) ** 2
                for k in norm
            ))
            row_dict["distance"] = dist
            scored.append(row_dict)

        scored.sort(key=lambda x: x["distance"])
        return scored[:limit]

    def similar_win_rate(self, features: dict, min_trades: int = 5) -> dict:
        """
        计算相似环境的历史胜率
        返回: {"win_rate": float, "sample_size": int, "avg_pnl": float, "sufficient": bool}
        """
        similar = self.find_similar(features, limit=30)
        if len(similar) < min_trades:
            return {"win_rate": 0.5, "sample_size": len(similar),
                    "avg_pnl": 0.0, "sufficient": False}

        wins = sum(1 for t in similar if t["pnl_pct"] > 0)
        avg_pnl = sum(t["pnl_pct"] for t in similar) / len(similar)
        return {
            "win_rate": wins / len(similar),
            "sample_size": len(similar),
            "avg_pnl": avg_pnl,
            "sufficient": True,
        }

    def performance_report(self) -> dict:
        """
        生成绩效归因报告：按市场状态分类统计
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trades").fetchall()

        if not rows:
            return {"total_trades": 0, "by_regime": {}}

        # 按市场状态分类
        regimes = {"trending": [], "ranging": [], "high_vol": [], "other": []}
        for row in rows:
            r = dict(row)
            if r["adx"] > 25:
                regimes["trending"].append(r)
            elif r["adx"] < 20:
                regimes["ranging"].append(r)
            elif r["atr_pct"] > 3.0:
                regimes["high_vol"].append(r)
            else:
                regimes["other"].append(r)

        report = {"total_trades": len(rows), "by_regime": {}}
        for regime, trades in regimes.items():
            if not trades:
                continue
            wins = sum(1 for t in trades if t["pnl_pct"] > 0)
            total_pnl = sum(t["pnl_pct"] for t in trades)
            report["by_regime"][regime] = {
                "count": len(trades),
                "win_rate": wins / len(trades),
                "total_pnl": round(total_pnl, 4),
                "avg_pnl": round(total_pnl / len(trades), 4),
            }

        return report
