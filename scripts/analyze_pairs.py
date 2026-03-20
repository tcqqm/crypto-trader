"""
按币对分析盈亏 — 判断是否应该移除某些币对
"""
import sys, json, zipfile
from pathlib import Path

results_dir = Path("/freqtrade/user_data/backtest_results")
with open(results_dir / ".last_result.json") as f:
    latest_name = json.load(f)["latest_backtest"]

with zipfile.ZipFile(results_dir / latest_name) as zf:
    with zf.open(latest_name.replace(".zip", ".json")) as jf:
        data = json.load(jf)

for strategy_name, strategy_data in data.get("strategy", {}).items():
    trades = strategy_data.get("trades", [])
    print(f"策略: {strategy_name}")

    # 按币对统计
    pair_stats = {}
    for t in trades:
        pair = t.get("pair", "?")
        if pair not in pair_stats:
            pair_stats[pair] = {"trades": 0, "wins": 0, "losses": 0, "profit": 0,
                                "sl_count": 0, "sl_loss": 0, "win_profit": 0}
        pair_stats[pair]["trades"] += 1
        profit = t.get("profit_abs", 0)
        pair_stats[pair]["profit"] += profit
        if t.get("exit_reason") == "stop_loss":
            pair_stats[pair]["sl_count"] += 1
            pair_stats[pair]["sl_loss"] += profit
            pair_stats[pair]["losses"] += 1
        else:
            pair_stats[pair]["wins"] += 1
            pair_stats[pair]["win_profit"] += profit

    print(f"\n{'币对':>12} | {'笔数':>4} | {'胜':>3} | {'负':>3} | {'胜率':>5} | {'总利润':>8} | {'盈利部分':>8} | {'止损亏损':>8} | {'净值':>8}")
    print("-" * 95)
    for pair, s in sorted(pair_stats.items(), key=lambda x: -x[1]["profit"]):
        wr = f"{s['wins']/(s['wins']+s['losses'])*100:.0f}%" if (s['wins']+s['losses']) > 0 else "N/A"
        print(f"  {pair:>12} | {s['trades']:>4} | {s['wins']:>3} | {s['losses']:>3} | {wr:>5} | {s['profit']:>+8.2f} | {s['win_profit']:>+8.2f} | {s['sl_loss']:>+8.2f} | {'保留' if s['profit'] > 0 else '考虑移除'}")

    # 如果移除DOGE
    doge_profit = pair_stats.get("DOGE/USDT", {}).get("profit", 0)
    total_profit = sum(s["profit"] for s in pair_stats.values())
    print(f"\n总利润: {total_profit:+.2f}U")
    print(f"移除DOGE后: {total_profit - doge_profit:+.2f}U (差异: {-doge_profit:+.2f}U)")

    # 如果移除LINK
    link_profit = pair_stats.get("LINK/USDT", {}).get("profit", 0)
    print(f"移除LINK后: {total_profit - link_profit:+.2f}U (差异: {-link_profit:+.2f}U)")

    # 如果只保留BTC+BNB+AVAX
    keep = ["BTC/USDT", "BNB/USDT", "AVAX/USDT"]
    keep_profit = sum(pair_stats.get(p, {}).get("profit", 0) for p in keep)
    keep_trades = sum(pair_stats.get(p, {}).get("trades", 0) for p in keep)
    print(f"只保留BTC+BNB+AVAX: {keep_profit:+.2f}U, {keep_trades}笔")
