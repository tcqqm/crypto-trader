"""
风控引擎 — 硬编码规则，不可被 AI 修改核心参数
"""
import json
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """风控参数（硬编码）"""
    max_loss_per_trade: float = -0.02       # 单笔止损 -2%
    max_profit_per_trade: float = 0.04      # 单笔止盈 +4%
    min_risk_reward_ratio: float = 2.0      # 最低盈亏比 1:2
    position_size_min: float = 0.10         # 单笔最小仓位 10%
    position_size_max: float = 0.20         # 单笔最大仓位 20%
    max_open_trades: int = 3                # 同时最多 3 仓
    daily_max_loss: float = -0.05           # 日最大亏损 -5%
    max_consecutive_losses: int = 5         # 连续亏损 5 笔暂停
    pause_duration_hours: int = 24          # 暂停时长 24h
    sentiment_veto_threshold: float = -0.5  # 情绪否决阈值


class RiskManager:
    """风控管理器"""

    # 仓位计算模式
    MODE_FIXED = "fixed"       # 固定比例（原有逻辑）
    MODE_ATR = "atr"           # ATR 波动率调整
    MODE_KELLY = "kelly"       # Kelly 公式

    def __init__(self, config: RiskConfig = None, state_file: str = None):
        self.config = config or RiskConfig()
        self.state_file = Path(state_file) if state_file else None
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """加载风控状态"""
        default = {
            "daily_pnl": 0.0,
            "daily_trades": 0,
            "consecutive_losses": 0,
            "paused_until": 0,
            "last_reset_date": "",
            "trade_history": [],
        }
        if self.state_file and self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                return default
        return default

    def _save_state(self):
        """持久化风控状态"""
        if self.state_file:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state, indent=2))

    def _reset_daily_if_needed(self):
        """每日重置计数器"""
        from datetime import date
        today = date.today().isoformat()
        if self.state["last_reset_date"] != today:
            self.state["daily_pnl"] = 0.0
            self.state["daily_trades"] = 0
            self.state["last_reset_date"] = today
            self._save_state()

    def is_paused(self) -> bool:
        """检查是否处于暂停状态"""
        if self.state["paused_until"] > time.time():
            remaining = (self.state["paused_until"] - time.time()) / 3600
            logger.warning(f"风控暂停中，剩余 {remaining:.1f} 小时")
            return True
        return False

    def can_open_trade(self, sentiment_score: float = 0.0, side: str = "long",
                       market_context: dict = None) -> dict:
        """
        检查是否允许开仓
        market_context: {"adx": float, "atr_pct": float, "is_high_vol": bool}
        返回: {"allowed": bool, "reason": str, "position_size": float, "sizing_mode": str}
        """
        self._reset_daily_if_needed()

        # 暂停检查
        if self.is_paused():
            return {"allowed": False, "reason": "连续亏损暂停中", "position_size": 0, "sizing_mode": "paused"}

        # 日亏损检查
        if self.state["daily_pnl"] <= self.config.daily_max_loss:
            return {"allowed": False, "reason": f"日亏损已达 {self.state['daily_pnl']:.2%}，当日停止", "position_size": 0, "sizing_mode": "stopped"}

        # 情绪否决（仅限多仓）
        if side == "long" and sentiment_score < self.config.sentiment_veto_threshold:
            return {"allowed": False, "reason": f"市场情绪 {sentiment_score:.2f} < {self.config.sentiment_veto_threshold}，不开多仓", "position_size": 0, "sizing_mode": "vetoed"}

        # 动态仓位计算
        ctx = market_context or {}
        position_size, sizing_mode = self._calculate_position_size(sentiment_score, ctx)

        return {"allowed": True, "reason": "通过风控检查", "position_size": position_size, "sizing_mode": sizing_mode}

    def _calculate_position_size(self, sentiment_score: float, ctx: dict) -> tuple[float, str]:
        """
        动态仓位计算 — 根据市场体制自动选择模式
        - 高波动 → 固定最小仓位
        - 趋势市场 → Kelly 公式
        - 震荡市场 → ATR 仓位法
        - 默认 → 情绪调整的固定比例
        """
        adx = ctx.get("adx", 0)
        atr_pct = ctx.get("atr_pct", 0)
        is_high_vol = ctx.get("is_high_vol", False)

        # 高波动 → 固定最小仓位
        if is_high_vol:
            return self.config.position_size_min, self.MODE_FIXED

        # 趋势市场（ADX > 25）→ Kelly 公式
        if adx > 25:
            kelly_size = self._kelly_position()
            if kelly_size is not None:
                return kelly_size, self.MODE_KELLY

        # 震荡市场（ADX < 20）→ ATR 仓位法
        if adx < 20 and atr_pct > 0:
            atr_size = self._atr_position(atr_pct)
            return atr_size, self.MODE_ATR

        # 默认：情绪调整的固定比例
        return self._fixed_position(sentiment_score), self.MODE_FIXED

    def _fixed_position(self, sentiment_score: float) -> float:
        """固定比例仓位（原有逻辑）"""
        if sentiment_score > 0.5:
            return self.config.position_size_max
        elif sentiment_score > -0.2:
            return (self.config.position_size_min + self.config.position_size_max) / 2
        else:
            return self.config.position_size_min

    def _atr_position(self, atr_pct: float, multiplier: float = 1.5) -> float:
        """
        ATR 仓位法：波动越大仓位越小
        position_size = risk_per_trade / (atr_pct * multiplier)
        """
        risk_per_trade = abs(self.config.max_loss_per_trade)  # 0.02
        raw_size = risk_per_trade / (atr_pct / 100.0 * multiplier)
        # 限制在 min/max 范围内
        return max(self.config.position_size_min,
                   min(raw_size, self.config.position_size_max))

    def _kelly_position(self) -> float | None:
        """
        Kelly 公式：基于历史胜率动态调整
        f = (win_rate * avg_win - (1-win_rate) * avg_loss) / avg_win
        使用半 Kelly（更保守）
        """
        history = self.state.get("trade_history", [])
        if len(history) < 10:
            return None  # 样本不足，回退到默认

        wins = [t["pnl_pct"] for t in history if t["pnl_pct"] > 0]
        losses = [abs(t["pnl_pct"]) for t in history if t["pnl_pct"] < 0]

        if not wins or not losses:
            return None

        win_rate = len(wins) / len(history)
        avg_win = sum(wins) / len(wins)
        avg_loss = sum(losses) / len(losses)

        if avg_win == 0:
            return None

        kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        # 半 Kelly，更保守
        half_kelly = kelly_f / 2

        if half_kelly <= 0:
            return self.config.position_size_min

        # 限制在 min/max 范围内
        return max(self.config.position_size_min,
                   min(half_kelly, self.config.position_size_max))

    def record_trade(self, pnl_pct: float):
        """记录交易结果，更新风控状态"""
        self._reset_daily_if_needed()

        self.state["daily_pnl"] += pnl_pct
        self.state["daily_trades"] += 1
        self.state["trade_history"].append({
            "pnl_pct": pnl_pct,
            "timestamp": time.time(),
        })

        # 连续亏损计数
        if pnl_pct < 0:
            self.state["consecutive_losses"] += 1
            if self.state["consecutive_losses"] >= self.config.max_consecutive_losses:
                self.state["paused_until"] = time.time() + self.config.pause_duration_hours * 3600
                logger.warning(f"连续亏损 {self.state['consecutive_losses']} 笔，暂停 {self.config.pause_duration_hours}h")
        else:
            self.state["consecutive_losses"] = 0

        # 只保留最近 100 条记录
        self.state["trade_history"] = self.state["trade_history"][-100:]
        self._save_state()

    def get_status(self) -> dict:
        """获取当前风控状态摘要"""
        self._reset_daily_if_needed()
        return {
            "daily_pnl": f"{self.state['daily_pnl']:.2%}",
            "daily_trades": self.state["daily_trades"],
            "consecutive_losses": self.state["consecutive_losses"],
            "is_paused": self.is_paused(),
            "paused_until": self.state["paused_until"],
        }
