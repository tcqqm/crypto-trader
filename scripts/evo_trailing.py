#!/usr/bin/env python3
"""Auto-Evo: 批量测试 trailing stop 参数变体"""
import subprocess
import re
import shutil
from pathlib import Path

STRATEGY_FILE = Path(__file__).parent.parent / "freqtrade" / "user_data" / "strategies" / "yolo_strategy.py"
BACKUP = STRATEGY_FILE.with_suffix(".py.bak")

# 参数变体
VARIANTS = [
    # (trailing_stop_positive, trailing_stop_positive_offset, 描述)
    (0.02, 0.03, "基线 trail=2% offset=3%"),
    (0.015, 0.025, "激进 trail=1.5% offset=2.5%"),
    (0.03, 0.04, "宽松 trail=3% offset=4%"),
    (0.02, 0.04, "高offset trail=2% offset=4%"),
    (0.025, 0.035, "中间 trail=2.5% offset=3.5%"),
]

def run_backtest(trail, offset, desc):
    """修改策略参数并回测"""
    code = STRATEGY_FILE.read_text()

    # 替换参数
    code = re.sub(r'trailing_stop_positive = [\d.]+', f'trailing_stop_positive = {trail}', code)
    code = re.sub(r'trailing_stop_positive_offset = [\d.]+', f'trailing_stop_positive_offset = {offset}', code)
    STRATEGY_FILE.write_text(code)

    # 运行回测
    cmd = [
        "docker", "compose", "run", "--rm", "yolo", "backtesting",
        "--config", "/freqtrade/base.json", "--config", "/freqtrade/config.json",
        "--strategy", "YoloStrategy",
        "--timerange", "20240319-20260319",
        "--timeframe", "5m"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                          cwd=str(Path(__file__).parent.parent))
    output = result.stdout + result.stderr

    # 解析结果
    trades = re.search(r'│\s*YoloStrategy\s*│\s*(\d+)', output)
    profit = re.search(r'Tot Profit USDT\s*│\s*([-\d.]+)', output)
    profit_pct = re.search(r'Tot Profit %\s*│\s*([-\d.]+)', output)
    win_rate = re.search(r'Win%\s*│\s*([\d.]+)', output)
    # 从 STRATEGY SUMMARY 行解析
    summary = re.search(r'YoloStrategy\s*│\s*(\d+)\s*│\s*([-\d.]+)\s*│\s*([-\d.]+)\s*│\s*([-\d.]+)\s*│\s*[\d:]+\s*│\s*(\d+)\s+\d+\s+(\d+)\s+([\d.]+)', output)
    drawdown = re.search(r'Drawdown\s*│[^│]*│\s*([-\d.]+)\s*USDT\s+([\d.]+)%', output)

    if summary:
        return {
            "desc": desc,
            "trail": trail,
            "offset": offset,
            "trades": int(summary.group(1)),
            "avg_profit": float(summary.group(2)),
            "tot_profit": float(summary.group(3)),
            "tot_pct": float(summary.group(4)),
            "wins": int(summary.group(5)),
            "losses": int(summary.group(6)),
            "win_rate": float(summary.group(7)),
        }
    return {"desc": desc, "trail": trail, "offset": offset, "error": "解析失败", "raw": output[-500:]}


if __name__ == "__main__":
    # 备份原始策略
    shutil.copy2(STRATEGY_FILE, BACKUP)

    results = []
    for trail, offset, desc in VARIANTS:
        print(f"\n{'='*60}")
        print(f"测试: {desc}")
        print(f"{'='*60}")
        r = run_backtest(trail, offset, desc)
        results.append(r)
        if "error" not in r:
            print(f"  笔数={r['trades']}, 利润={r['tot_profit']:.1f}U ({r['tot_pct']:.0f}%), 胜率={r['win_rate']:.1f}%")
        else:
            print(f"  错误: {r['error']}")

    # 恢复原始策略
    shutil.copy2(BACKUP, STRATEGY_FILE)
    BACKUP.unlink()

    # 汇总
    print(f"\n{'='*60}")
    print("Auto-Evo 汇总")
    print(f"{'='*60}")
    print(f"{'描述':<30} {'笔数':>5} {'利润U':>8} {'利润%':>8} {'胜率':>6}")
    print("-" * 60)
    for r in results:
        if "error" not in r:
            print(f"{r['desc']:<30} {r['trades']:>5} {r['tot_profit']:>8.1f} {r['tot_pct']:>7.0f}% {r['win_rate']:>5.1f}%")
        else:
            print(f"{r['desc']:<30}  解析失败")
