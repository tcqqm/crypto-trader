#!/bin/bash
# Auto-Evo: 测试止损参数变体
cd /Users/yyzhao/workspace/projects/crypto-trader
STRATEGY=freqtrade/user_data/strategies/yolo_strategy.py
cp $STRATEGY ${STRATEGY}.bak

run_test() {
    local sl=$1 desc=$2
    echo ""
    echo "============================================================"
    echo "测试: $desc (stoploss=$sl)"
    echo "============================================================"

    cp ${STRATEGY}.bak $STRATEGY
    sed -i '' "s/stoploss = -0.05/stoploss = $sl/" $STRATEGY

    docker compose run --rm yolo backtesting \
        --config /freqtrade/base.json --config /freqtrade/config.json \
        --strategy YoloStrategy --timerange 20240319-20260319 --timeframe 5m 2>&1 | \
        python3 -c "
import sys
for line in sys.stdin:
    if 'YoloStrategy' in line and '│' in line and 'Trades' not in line:
        print(line.strip())
    elif 'underwater' in line.lower():
        print(line.strip())
"
}

run_test -0.05 "基线 -5%"
run_test -0.04 "收紧 -4%"
run_test -0.06 "放宽 -6%"
run_test -0.03 "激进 -3%"
run_test -0.08 "宽松 -8%"

cp ${STRATEGY}.bak $STRATEGY
rm ${STRATEGY}.bak
echo ""
echo "============================================================"
echo "全部完成，策略已恢复"
echo "============================================================"
