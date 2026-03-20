"""
分析Scalping止损交易特征 — 从zip文件读取
"""
import sys
sys.path.insert(0, "/freqtrade")

import json
import zipfile
from pathlib import Path

results_dir = Path("/freqtrade/user_data/backtest_results")

with open(results_dir / ".last_result.json") as f:
    latest_name = json.load(f)["latest_backtest"]

zip_path = results_dir / latest_name
print(f"分析: {latest_name}")

with zipfile.ZipFile(zip_path) as zf:
    json_name = latest_name.replace(".zip", ".json")
    with zf.open(json_name) as jf:
        data = json.load(jf)

for strategy_name, strategy_data in data.get("strategy", {}).items():
    trades = strategy_data.get("trades", [])
    print(f"\n策略: {strategy_name}, 总交易: {len(trades)}")

    sl_trades = [t for t in trades if t.get("exit_reason") == "stop_loss"]
    win_trades = [t for t in trades if t.get("exit_reason") != "stop_loss"]
    print(f"止损: {len(sl_trades)}笔, 盈利: {len(win_trades)}笔")

    # 止损交易详情
    print(f"\n{'='*70}")
    print("止损交易详情")
    print(f"{'='*70}")
    for t in sl_trades:
        pair = t.get("pair", "?")
        open_date = t.get("open_date", "?")[:16]
        profit_pct = t.get("profit_ratio", 0) * 100
        duration = t.get("trade_duration", 0)
        profit_abs = t.get("profit_abs", 0)
        print(f"  {pair:>12} | {open_date} | {profit_pct:+.2f}% | {profit_abs:+.2f}U | {duration}min")

    # 按币对统计止损
    print(f"\n止损按币对:")
    sl_by_pair = {}
    for t in sl_trades:
        pair = t.get("pair", "?")
        if pair not in sl_by_pair:
            sl_by_pair[pair] = {"count": 0, "loss": 0}
        sl_by_pair[pair]["count"] += 1
        sl_by_pair[pair]["loss"] += t.get("profit_abs", 0)
    for pair, s in sorted(sl_by_pair.items(), key=lambda x: x[1]["loss"]):
        print(f"  {pair}: {s['count']}笔, {s['loss']:+.2f}U")

    # 按月份统计止损
    print(f"\n止损按月份:")
    sl_by_month = {}
    for t in sl_trades:
        month = t.get("open_date", "")[:7]
        sl_by_month[month] = sl_by_month.get(month, 0) + 1
    for month, count in sorted(sl_by_month.items()):
        print(f"  {month}: {count}笔")

    # 止损持仓时间
    print(f"\n止损持仓时间(分钟):")
    durations = sorted([t.get("trade_duration", 0) for t in sl_trades])
    for d in durations:
        print(f"  {d}min")

    # 盈利交易利润分布
    print(f"\n盈利交易利润分布:")
    win_profits = sorted([t.get("profit_ratio", 0) * 100 for t in win_trades])
    buckets = [("0-0.3%", 0, 0.3), ("0.3-0.5%", 0.3, 0.5), ("0.5-1%", 0.5, 1.0),
               ("1-1.5%", 1.0, 1.5), ("1.5-2%", 1.5, 2.0), ("2%+", 2.0, 999)]
    for label, lo, hi in buckets:
        count = sum(1 for p in win_profits if lo <= p < hi)
        print(f"  {label}: {count}笔")

    # 出场原因汇总
    print(f"\n出场原因:")
    exit_stats = {}
    for t in trades:
        reason = t.get("exit_reason", "unknown")
        if reason not in exit_stats:
            exit_stats[reason] = {"count": 0, "profit": 0, "durations": []}
        exit_stats[reason]["count"] += 1
        exit_stats[reason]["profit"] += t.get("profit_abs", 0)
        exit_stats[reason]["durations"].append(t.get("trade_duration", 0))

    for reason, stats in sorted(exit_stats.items(), key=lambda x: -x[1]["profit"]):
        avg_dur = sum(stats["durations"]) / len(stats["durations"])
        print(f"  {reason:>20}: {stats['count']:>3}笔 | {stats['profit']:>+8.2f}U | avg {avg_dur:.0f}min")
