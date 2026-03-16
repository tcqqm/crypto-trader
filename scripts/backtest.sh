#!/bin/bash
# 回测脚本 — 下载数据 + 运行回测
# 用法: ./backtest.sh [--pessimistic] [--validate]
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 解析参数
PESSIMISTIC=false
VALIDATE=false
for arg in "$@"; do
    case $arg in
        --pessimistic) PESSIMISTIC=true ;;
        --validate) VALIDATE=true ;;
    esac
done

# 默认回测时间范围：最近6个月
END_DATE=$(date +%Y%m%d)
START_DATE=$(date -v-6m +%Y%m%d 2>/dev/null || date -d "6 months ago" +%Y%m%d)
TIMERANGE="${START_DATE}-${END_DATE}"
PAIRS="BTC/USDT ETH/USDT SOL/USDT BNB/USDT XRP/USDT"

echo "=== 加密货币回测 ==="
echo "时间范围: $TIMERANGE"
echo "交易对: $PAIRS"
if [ "$PESSIMISTIC" = true ]; then
    echo "模式: 悲观假设（滑点 0.1%，手续费 0.2%）"
fi
echo ""

# 1. 下载历史数据
echo "1. 下载历史数据..."
docker compose run --rm freqtrade download-data \
    --config /freqtrade/config.json \
    --timerange "$TIMERANGE" \
    --timeframe 5m 1h \
    --pairs $PAIRS

# 2. 运行回测
echo ""
echo "2. 运行回测..."
EXTRA_ARGS=""
if [ "$PESSIMISTIC" = true ]; then
    EXTRA_ARGS="--fee 0.002"
fi

docker compose run --rm freqtrade backtesting \
    --config /freqtrade/config.json \
    --strategy AdaptiveStrategy \
    --timerange "$TIMERANGE" \
    --timeframe 5m \
    --export trades \
    --export-filename /freqtrade/user_data/backtest_results.json \
    $EXTRA_ARGS

echo ""
echo "=== 回测完成 ==="
echo "结果: freqtrade/user_data/backtest_results.json"

# 3. 可选：运行 walk-forward 验证
if [ "$VALIDATE" = true ]; then
    echo ""
    echo "3. 运行 Walk-Forward 验证..."
    python3 scripts/validate.py
fi
