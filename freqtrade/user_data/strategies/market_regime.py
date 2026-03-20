"""
市场状态检测器 v5 — EMA三线排列 + 20日收益率双确认
72%月度准确率，BEAR precision 50%, BULL precision 59%
用于策略内部的市场状态过滤
"""
import pandas as pd


def detect_regime_series(dataframe: pd.DataFrame) -> pd.Series:
    """
    在1h dataframe上逐行计算市场状态
    返回 Series: "BULL" / "BEAR" / "RANGE"
    直接在 populate_indicators 中调用，merge到5m数据
    """
    df = dataframe.copy()

    # EMA三线
    ema9 = df["close"].ewm(span=9, adjust=False).mean()
    ema21 = df["close"].ewm(span=21, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()

    # 20日收益率（1h K线，20天=480根）
    ret20 = df["close"].pct_change(480)

    # EMA层级判断
    ema_bull = (ema9 > ema21) & (ema21 > ema50)
    ema_bear = (ema9 < ema21) & (ema21 < ema50)

    # 收益率判断
    ret_bull = ret20 > 0.05
    ret_bear = ret20 < -0.05

    # v5组合逻辑：EMA层级 + 收益率方向不矛盾
    regime = pd.Series("RANGE", index=df.index)
    regime[ema_bull & ~ret_bear] = "BULL"
    regime[ema_bear & ~ret_bull] = "BEAR"

    return regime
