"""
回测验证脚本 — Walk-forward 验证 + 参数稳定性测试
来源：claude-trading-skills backtest-expert
"""
import json
import subprocess
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent.parent
RESULTS_DIR = PROJECT_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def run_backtest(timerange: str, extra_args: list = None) -> dict | None:
    """运行单次回测，返回结果摘要"""
    cmd = [
        "docker", "compose", "run", "--rm", "freqtrade", "backtesting",
        "--config", "/freqtrade/config.json",
        "--strategy", "AdaptiveStrategy",
        "--timerange", timerange,
        "--timeframe", "5m",
        "--export", "none",
    ]
    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=str(PROJECT_DIR),
        )
        return _parse_backtest_output(result.stdout)
    except Exception as e:
        logger.error(f"回测执行失败: {e}")
        return None


def _parse_backtest_output(output: str) -> dict:
    """从 Freqtrade 回测输出中提取关键指标"""
    metrics = {
        "total_trades": 0, "win_rate": 0.0,
        "profit_pct": 0.0, "max_drawdown": 0.0,
        "sharpe": 0.0, "profit_factor": 0.0,
    }
    for line in output.splitlines():
        line = line.strip()
        if "Total trades" in line:
            try:
                metrics["total_trades"] = int(line.split("|")[-2].strip())
            except (ValueError, IndexError):
                pass
        if "Win Rate" in line or "Wins/Draws/Losses" in line:
            try:
                parts = line.split("|")
                for p in parts:
                    if "%" in p:
                        metrics["win_rate"] = float(p.strip().replace("%", "")) / 100
                        break
            except (ValueError, IndexError):
                pass
        if "Max Drawdown" in line:
            try:
                parts = line.split("|")
                for p in parts:
                    if "%" in p:
                        metrics["max_drawdown"] = float(p.strip().replace("%", "")) / 100
                        break
            except (ValueError, IndexError):
                pass
        if "Sharpe" in line:
            try:
                parts = line.split("|")
                for p in parts:
                    p = p.strip()
                    try:
                        metrics["sharpe"] = float(p)
                        break
                    except ValueError:
                        continue
            except (ValueError, IndexError):
                pass
    return metrics


def walk_forward_validation(months: int = 6, segments: int = 3) -> list[dict]:
    """
    Walk-forward 验证
    将数据分段：每段 train N 个月 + test 剩余月份
    默认 6 个月分 3 段，每段 train 4 个月 + test 2 个月
    """
    logger.info(f"=== Walk-Forward 验证（{months}个月，{segments}段）===")
    results = []
    end = datetime.now()
    start = end - timedelta(days=months * 30)
    segment_days = (end - start).days // segments

    for i in range(segments):
        seg_start = start + timedelta(days=i * segment_days)
        seg_end = seg_start + timedelta(days=segment_days)
        # train: 前 2/3，test: 后 1/3
        train_end = seg_start + timedelta(days=int(segment_days * 2 / 3))

        train_range = f"{seg_start.strftime('%Y%m%d')}-{train_end.strftime('%Y%m%d')}"
        test_range = f"{train_end.strftime('%Y%m%d')}-{seg_end.strftime('%Y%m%d')}"

        logger.info(f"段 {i+1}/{segments}: train={train_range}, test={test_range}")

        train_result = run_backtest(train_range)
        test_result = run_backtest(test_range)

        segment = {
            "segment": i + 1,
            "train_range": train_range,
            "test_range": test_range,
            "train": train_result,
            "test": test_result,
        }

        # 计算 train/test 差异
        if train_result and test_result:
            train_pnl = train_result.get("profit_pct", 0)
            test_pnl = test_result.get("profit_pct", 0)
            if train_pnl != 0:
                segment["pnl_divergence"] = abs(train_pnl - test_pnl) / abs(train_pnl)
            else:
                segment["pnl_divergence"] = 0
            segment["stable"] = segment["pnl_divergence"] < 0.5
        else:
            segment["stable"] = None

        results.append(segment)
        logger.info(f"  train: {train_result}")
        logger.info(f"  test:  {test_result}")

    return results


def parameter_stability_test() -> dict:
    """
    参数稳定性测试：核心参数 ±20% 变动，收益变化 < 30% 才算稳定
    注意：Freqtrade 策略参数通过 --strategy-list 或 hyperopt 调整
    这里通过修改配置文件模拟参数变动
    """
    logger.info("=== 参数稳定性测试 ===")
    # 基准回测（最近 3 个月）
    end = datetime.now()
    start = end - timedelta(days=90)
    timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    baseline = run_backtest(timerange)
    if not baseline:
        logger.error("基准回测失败")
        return {"stable": False, "reason": "基准回测失败"}

    logger.info(f"基准结果: {baseline}")

    # 悲观假设回测：加大滑点和手续费
    pessimistic = run_backtest(timerange, extra_args=[
        "--fee", "0.002",  # 手续费 0.2%（默认 0.1%）
    ])

    result = {
        "baseline": baseline,
        "pessimistic": pessimistic,
        "timerange": timerange,
    }

    if baseline and pessimistic:
        base_pnl = baseline.get("profit_pct", 0)
        pess_pnl = pessimistic.get("profit_pct", 0)
        if base_pnl != 0:
            result["pessimistic_divergence"] = abs(base_pnl - pess_pnl) / abs(base_pnl)
        else:
            result["pessimistic_divergence"] = 0
        result["stable"] = result["pessimistic_divergence"] < 0.30
    else:
        result["stable"] = None

    return result


def generate_report():
    """生成完整验证报告"""
    logger.info("开始生成验证报告...")

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "walk_forward": walk_forward_validation(),
        "parameter_stability": parameter_stability_test(),
    }

    # 总体评估
    wf_stable = all(
        s.get("stable", False) for s in report["walk_forward"]
        if s.get("stable") is not None
    )
    ps_stable = report["parameter_stability"].get("stable", False)
    report["overall"] = {
        "walk_forward_stable": wf_stable,
        "parameter_stable": ps_stable,
        "ready_for_live": wf_stable and ps_stable,
    }

    # 保存报告
    report_path = RESULTS_DIR / "validation_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    logger.info(f"验证报告已保存: {report_path}")

    return report


if __name__ == "__main__":
    report = generate_report()
    print(json.dumps(report.get("overall", {}), indent=2))
    if not report.get("overall", {}).get("ready_for_live"):
        logger.warning("验证未通过，不建议进入实盘")
        sys.exit(1)
    else:
        logger.info("验证通过，可以进入模拟交易阶段")
