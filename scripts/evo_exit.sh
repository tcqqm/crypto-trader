#!/bin/bash
# Auto-Evo: 测试出场参数变体（custom_exit阈值）
cd /Users/yyzhao/workspace/projects/crypto-trader
STRATEGY=freqtrade/user_data/strategies/yolo_strategy.py
cp $STRATEGY ${STRATEGY}.bak

run_test() {
    local bb_profit=$1 rsi_profit=$2 rsi_val=$3 timeout_h=$4 desc=$5
    echo ""
    echo "============================================================"
    echo "测试: $desc"
    echo "============================================================"

    # 恢复原始再修改
    cp ${STRATEGY}.bak $STRATEGY

    # 修改 bb_mid_target 利润阈值
    sed -i '' "s/current_profit > 0.01 and current_rate >= last\[\"bb_middle\"\]/current_profit > $bb_profit and current_rate >= last[\"bb_middle\"]/" $STRATEGY

    # 修改 rsi_profit_exit 利润和RSI阈值
    sed -i '' "s/current_profit > 0.03 and last.get(\"rsi7\", 50) > 65/current_profit > $rsi_profit and last.get(\"rsi7\", 50) > $rsi_val/" $STRATEGY

    # 修改超时时间
    local timeout_sec=$((timeout_h * 3600))
    sed -i '' "s/trade_duration > 14400/trade_duration > $timeout_sec/" $STRATEGY

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

# 基线: bb_profit=0.01, rsi_profit=0.03, rsi_val=65, timeout=4h
run_test 0.01 0.03 65 4 "基线 bb>1%+mid, rsi>3%+65, timeout=4h"
run_test 0.005 0.03 65 4 "bb>0.5%+mid（更早止盈）"
run_test 0.01 0.02 60 4 "rsi>2%+60（更早RSI出场）"
run_test 0.01 0.03 65 3 "timeout=3h（更早超时）"
run_test 0.01 0.03 65 6 "timeout=6h（更晚超时）"
run_test 0.005 0.02 60 3 "全激进（所有出场更早）"

# 恢复
cp ${STRATEGY}.bak $STRATEGY
rm ${STRATEGY}.bak
echo ""
echo "============================================================"
echo "全部完成，策略已恢复"
echo "============================================================"
