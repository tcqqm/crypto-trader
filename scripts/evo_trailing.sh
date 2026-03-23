#!/bin/bash
# Auto-Evo: 逐个测试 trailing stop 参数变体
cd /Users/yyzhao/workspace/projects/crypto-trader
STRATEGY=freqtrade/user_data/strategies/yolo_strategy.py
cp $STRATEGY ${STRATEGY}.bak

run_test() {
    local trail=$1 offset=$2 desc=$3
    echo ""
    echo "============================================================"
    echo "测试: $desc (trail=$trail, offset=$offset)"
    echo "============================================================"

    # 修改参数
    sed -i '' "s/trailing_stop_positive = .*/trailing_stop_positive = $trail/" $STRATEGY
    sed -i '' "s/trailing_stop_positive_offset = .*/trailing_stop_positive_offset = $offset/" $STRATEGY

    # 回测
    docker compose run --rm yolo backtesting \
        --config /freqtrade/base.json --config /freqtrade/config.json \
        --strategy YoloStrategy --timerange 20240319-20260319 --timeframe 5m 2>&1 | \
        python3 -c "
import sys
for line in sys.stdin:
    if 'YoloStrategy' in line and '│' in line and 'Trades' not in line:
        parts = [p.strip() for p in line.split('│') if p.strip()]
        if len(parts) >= 7:
            print(f'  结果: {line.strip()}')
    elif 'underwater' in line.lower():
        print(f'  {line.strip()}')
"
}

# 5组参数变体
run_test 0.02 0.03 "基线 trail=2% offset=3%"
run_test 0.015 0.025 "激进 trail=1.5% offset=2.5%"
run_test 0.03 0.04 "宽松 trail=3% offset=4%"
run_test 0.02 0.04 "高offset trail=2% offset=4%"
run_test 0.025 0.035 "中间 trail=2.5% offset=3.5%"

# 恢复
cp ${STRATEGY}.bak $STRATEGY
rm ${STRATEGY}.bak
echo ""
echo "============================================================"
echo "全部完成，策略已恢复"
echo "============================================================"
