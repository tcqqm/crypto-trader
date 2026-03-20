"""
市场阶段×策略 回测矩阵分析
在Docker容器内运行，一次性输出所有结果
"""
import subprocess
import re

# 市场阶段定义
phases = {
    # 牛市
    "BULL_2024.3": "20240301-20240401",
    "BULL_2024.5": "20240501-20240601",
    "BULL_2024.9-11": "20240901-20241201",
    "BULL_2025.1": "20250101-20250201",
    "BULL_2025.4-5": "20250401-20250601",
    "BULL_2025.7": "20250701-20250801",
    "BULL_2025.9": "20250901-20251001",
    "BULL_2026.3": "20260301-20260320",
    # 熊市
    "BEAR_2024.4": "20240401-20240501",
    "BEAR_2024.6": "20240601-20240701",
    "BEAR_2024.8": "20240801-20240901",
    "BEAR_2025.2": "20250201-20250301",
    "BEAR_2025.8": "20250801-20250901",
    "BEAR_2025.11": "20251101-20251201",
    "BEAR_2026.1-2": "20260101-20260301",
    # 震荡
    "RANGE_2024.7": "20240701-20240801",
    "RANGE_2024.12": "20241201-20250101",
    "RANGE_2025.3": "20250301-20250401",
    "RANGE_2025.6": "20250601-20250701",
    "RANGE_2025.10": "20251001-20251101",
    "RANGE_2025.12": "20251201-20260101",
}

strategies = [
    ("ScalpingStrategy", "/freqtrade/base.json", "/freqtrade/scalping.json"),
    ("GridDCAStrategy", "/freqtrade/base.json", "/freqtrade/grid_dca.json"),
    ("SwingTrendStrategy", "/freqtrade/base.json", "/freqtrade/swing_trend.json"),
]

# 按市场状态汇总
results = {"BULL": {}, "BEAR": {}, "RANGE": {}}

for phase_name, timerange in phases.items():
    state = phase_name.split("_")[0]
    for strat_name, base_cfg, strat_cfg in strategies:
        cmd = [
            "docker", "compose", "run", "--rm", "scalping",
            "backtesting",
            "--config", base_cfg,
            "--config", strat_cfg,
            "--strategy", strat_name,
            "--timerange", timerange,
            "--timeframe", "5m",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            output = result.stdout + result.stderr
            # 解析结果行
            for line in output.split("\n"):
                if strat_name in line and "│" in line:
                    parts = [p.strip() for p in line.split("│") if p.strip()]
                    if len(parts) >= 7:
                        trades = int(parts[1])
                        avg_profit = float(parts[2])
                        tot_profit_usdt = float(parts[3].replace("USDT", "").strip())
                        tot_profit_pct = float(parts[4])
                        win_info = parts[6].strip()

                        key = strat_name
                        if key not in results[state]:
                            results[state][key] = {"trades": 0, "profit": 0.0, "wins": 0, "losses": 0}
                        results[state][key]["trades"] += trades
                        results[state][key]["profit"] += tot_profit_usdt

                        # 解析胜负
                        win_match = re.search(r"(\d+)\s+\d+\s+(\d+)", win_info)
                        if win_match:
                            results[state][key]["wins"] += int(win_match.group(1))
                            results[state][key]["losses"] += int(win_match.group(2))
        except Exception as e:
            print(f"ERROR: {phase_name} {strat_name}: {e}")

# 输出汇总
print("\n" + "=" * 80)
print("市场阶段 × 策略 回测矩阵")
print("=" * 80)

for state in ["BULL", "BEAR", "RANGE"]:
    state_cn = {"BULL": "牛市", "BEAR": "熊市", "RANGE": "震荡"}[state]
    print(f"\n--- {state_cn} ---")
    print(f"{'策略':<22} {'笔数':>6} {'利润USDT':>10} {'胜':>4} {'负':>4} {'胜率':>6}")
    for strat in ["ScalpingStrategy", "GridDCAStrategy", "SwingTrendStrategy"]:
        if strat in results[state]:
            r = results[state][strat]
            total = r["wins"] + r["losses"]
            wr = f"{r['wins']/total*100:.0f}%" if total > 0 else "N/A"
            print(f"{strat:<22} {r['trades']:>6} {r['profit']:>10.2f} {r['wins']:>4} {r['losses']:>4} {wr:>6}")
        else:
            print(f"{strat:<22}      0       0.00    0    0    N/A")

# 总计
print(f"\n--- 总计 ---")
print(f"{'策略':<22} {'笔数':>6} {'利润USDT':>10} {'胜':>4} {'负':>4} {'胜率':>6}")
for strat in ["ScalpingStrategy", "GridDCAStrategy", "SwingTrendStrategy"]:
    total_trades = sum(results[s].get(strat, {}).get("trades", 0) for s in results)
    total_profit = sum(results[s].get(strat, {}).get("profit", 0) for s in results)
    total_wins = sum(results[s].get(strat, {}).get("wins", 0) for s in results)
    total_losses = sum(results[s].get(strat, {}).get("losses", 0) for s in results)
    total = total_wins + total_losses
    wr = f"{total_wins/total*100:.0f}%" if total > 0 else "N/A"
    print(f"{strat:<22} {total_trades:>6} {total_profit:>10.2f} {total_wins:>4} {total_losses:>4} {wr:>6}")
