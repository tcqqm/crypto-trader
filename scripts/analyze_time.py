"""
分析交易的时间分布 — 找出止损集中的时段
"""
import sys, json, zipfile
from pathlib import Path
from collections import defaultdict

results_dir = Path("/freqtrade/user_data/backtest_results")
with open(results_dir / ".last_result.json") as f:
    latest_name = json.load(f)["latest_backtest"]

with zipfile.ZipFile(results_dir / latest_name) as zf:
    with zf.open(latest_name.replace(".zip", ".json")) as jf:
        data = json.load(jf)

for strategy_name, strategy_data in data.get("strategy", {}).items():
    trades = strategy_data.get("trades", [])
    print(f"策略: {strategy_name}, 总交易: {len(trades)}")

    # 按小时统计
    hour_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "profit": 0})
    for t in trades:
        hour = int(t.get("open_date", "2024-01-01T00:00")[11:13])
        profit = t.get("profit_abs", 0)
        hour_stats[hour]["profit"] += profit
        if t.get("exit_reason") == "stop_loss" or t.get("exit_reason") == "swing_early_stop":
            hour_stats[hour]["losses"] += 1
        else:
            hour_stats[hour]["wins"] += 1

    print(f"\n按入场小时(UTC):")
    print(f"{'小时':>4} | {'赢':>3} | {'亏':>3} | {'利润':>8} | {'胜率':>5}")
    print("-" * 40)
    for hour in range(24):
        s = hour_stats[hour]
        total = s["wins"] + s["losses"]
        if total > 0:
            wr = f"{s['wins']/total*100:.0f}%"
            print(f"  {hour:02d}  | {s['wins']:>3} | {s['losses']:>3} | {s['profit']:>+8.2f} | {wr:>5}")

    # 按星期统计
    from datetime import datetime
    weekday_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "profit": 0})
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for t in trades:
        dt = datetime.fromisoformat(t.get("open_date", "2024-01-01T00:00:00").replace("+00:00", ""))
        wd = dt.weekday()
        profit = t.get("profit_abs", 0)
        weekday_stats[wd]["profit"] += profit
        if t.get("exit_reason") == "stop_loss" or t.get("exit_reason") == "swing_early_stop":
            weekday_stats[wd]["losses"] += 1
        else:
            weekday_stats[wd]["wins"] += 1

    print(f"\n按星期:")
    print(f"{'星期':>4} | {'赢':>3} | {'亏':>3} | {'利润':>8} | {'胜率':>5}")
    print("-" * 40)
    for wd in range(7):
        s = weekday_stats[wd]
        total = s["wins"] + s["losses"]
        if total > 0:
            wr = f"{s['wins']/total*100:.0f}%"
            print(f"  {weekday_names[wd]}  | {s['wins']:>3} | {s['losses']:>3} | {s['profit']:>+8.2f} | {wr:>5}")

    # 止损交易的详细时间
    print(f"\n止损交易时间详情:")
    sl_trades = [t for t in trades if t.get("exit_reason") in ("stop_loss", "swing_early_stop")]
    for t in sl_trades:
        pair = t.get("pair", "?")
        open_date = t.get("open_date", "?")[:16]
        dt = datetime.fromisoformat(t.get("open_date", "2024-01-01T00:00:00").replace("+00:00", ""))
        hour = dt.hour
        wd = weekday_names[dt.weekday()]
        profit = t.get("profit_abs", 0)
        print(f"  {pair:>12} | {open_date} | {wd} {hour:02d}:xx | {profit:+.2f}U")
