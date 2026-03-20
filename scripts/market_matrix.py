#!/usr/bin/env python3
"""市场阶段×策略 回测矩阵 — 在freqtrade容器内运行"""
import subprocess, sys, re

PHASES = [
    # (名称, timerange, 状态)
    ("BULL_2024.3", "20240319-20240401", "BULL"),
    ("BULL_2024.5", "20240501-20240601", "BULL"),
    ("BULL_2024.9-11", "20240901-20241201", "BULL"),
    ("BULL_2025.1", "20250101-20250201", "BULL"),
    ("BULL_2025.4-5", "20250401-20250601", "BULL"),
    ("BULL_2025.7", "20250701-20250801", "BULL"),
    ("BULL_2025.9", "20250901-20251001", "BULL"),
    ("BEAR_2024.4", "20240401-20240501", "BEAR"),
    ("BEAR_2024.6", "20240601-20240701", "BEAR"),
    ("BEAR_2024.8", "20240801-20240901", "BEAR"),
    ("BEAR_2025.2", "20250201-20250301", "BEAR"),
    ("BEAR_2025.8", "20250801-20250901", "BEAR"),
    ("BEAR_2025.11", "20251101-20251201", "BEAR"),
    ("BEAR_2026.1-2", "20260101-20260301", "BEAR"),
    ("RANGE_2024.7", "20240701-20240801", "RANGE"),
    ("RANGE_2024.12", "20241201-20250101", "RANGE"),
    ("RANGE_2025.3", "20250301-20250401", "RANGE"),
    ("RANGE_2025.6", "20250601-20250701", "RANGE"),
    ("RANGE_2025.10", "20251001-20251101", "RANGE"),
    ("RANGE_2025.12", "20251201-20260101", "RANGE"),
]

STRATEGIES = [
    ("ScalpingStrategy", "/freqtrade/base.json", "/freqtrade/scalping.json"),
    ("GridDCAStrategy", "/freqtrade/base.json", "/freqtrade/grid_dca.json"),
    ("SwingTrendStrategy", "/freqtrade/base.json", "/freqtrade/swing_trend.json"),
]

# 汇总
agg = {}
for state in ["BULL", "BEAR", "RANGE"]:
    agg[state] = {}
    for s, _, _ in STRATEGIES:
        agg[state][s] = {"trades": 0, "profit": 0.0, "wins": 0, "losses": 0}

total_runs = len(PHASES) * len(STRATEGIES)
done = 0

for phase_name, tr, state in PHASES:
    for strat, base_cfg, strat_cfg in STRATEGIES:
        done += 1
        sys.stdout.write(f"\r[{done}/{total_runs}] {phase_name} x {strat[:8]}...")
        sys.stdout.flush()

        cmd = [
            "freqtrade", "backtesting",
            "--config", base_cfg,
            "--config", strat_cfg,
            "--strategy", strat,
            "--timerange", tr,
            "--timeframe", "5m",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            out = r.stdout + r.stderr
            for line in out.split("\n"):
                if strat in line and "│" in line:
                    parts = [p.strip() for p in line.split("│") if p.strip()]
                    if len(parts) >= 7:
                        trades = int(parts[1])
                        profit_usdt = float(parts[3].replace("USDT", "").strip())
                        wl = parts[6].strip()
                        m = re.match(r"(\d+)\s+(\d+)\s+(\d+)", wl)
                        if m:
                            wins, draws, losses = int(m.group(1)), int(m.group(2)), int(m.group(3))
                        else:
                            wins, losses = 0, 0
                        agg[state][strat]["trades"] += trades
                        agg[state][strat]["profit"] += profit_usdt
                        agg[state][strat]["wins"] += wins
                        agg[state][strat]["losses"] += losses
        except Exception as e:
            pass

print("\n")
print("=" * 75)
print("市场阶段 × 策略 回测矩阵")
print("=" * 75)

for state in ["BULL", "BEAR", "RANGE"]:
    label = {"BULL": "牛市(11月)", "BEAR": "熊市(8月)", "RANGE": "震荡(6月)"}[state]
    print(f"\n--- {label} ---")
    print(f"{'Strategy':<22} {'Trades':>6} {'Profit':>10} {'Win':>4} {'Loss':>4} {'WinRate':>7}")
    for strat, _, _ in STRATEGIES:
        r = agg[state][strat]
        t = r["wins"] + r["losses"]
        wr = f"{r['wins']/t*100:.0f}%" if t > 0 else "N/A"
        print(f"{strat:<22} {r['trades']:>6} {r['profit']:>9.1f}U {r['wins']:>4} {r['losses']:>4} {wr:>7}")

print(f"\n--- 总计 ---")
print(f"{'Strategy':<22} {'Trades':>6} {'Profit':>10} {'Win':>4} {'Loss':>4} {'WinRate':>7}")
for strat, _, _ in STRATEGIES:
    tt = sum(agg[s][strat]["trades"] for s in agg)
    tp = sum(agg[s][strat]["profit"] for s in agg)
    tw = sum(agg[s][strat]["wins"] for s in agg)
    tl = sum(agg[s][strat]["losses"] for s in agg)
    t = tw + tl
    wr = f"{tw/t*100:.0f}%" if t > 0 else "N/A"
    print(f"{strat:<22} {tt:>6} {tp:>9.1f}U {tw:>4} {tl:>4} {wr:>7}")
