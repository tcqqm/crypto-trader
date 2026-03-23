#!/bin/bash
# 逐币种回测 YoloStrategy，筛选适合的币种
# 用近1年数据（山寨币波动大，近期更有参考价值）

PAIRS=(
  "DOGE/USDT:USDT" "AVAX/USDT:USDT" "PEPE/USDT:USDT" "WIF/USDT:USDT"
  "SHIB/USDT:USDT" "FLOKI/USDT:USDT" "FET/USDT:USDT" "NEAR/USDT:USDT"
  "INJ/USDT:USDT" "SUI/USDT:USDT" "ARB/USDT:USDT" "OP/USDT:USDT"
  "APT/USDT:USDT" "FIL/USDT:USDT" "MATIC/USDT:USDT" "ATOM/USDT:USDT"
  "DOT/USDT:USDT" "ADA/USDT:USDT" "XRP/USDT:USDT" "ENA/USDT:USDT"
  "TRX/USDT:USDT" "RENDER/USDT:USDT" "SOL/USDT:USDT" "LINK/USDT:USDT"
  "BTC/USDT:USDT" "ETH/USDT:USDT" "BNB/USDT:USDT" "WLD/USDT:USDT"
  "BONK/USDT:USDT" "1000SATS/USDT:USDT"
)

TIMERANGE="20250319-20260319"
echo "=== YoloStrategy 币种筛查 (${TIMERANGE}) ==="
echo ""
printf "%-22s %6s %10s %8s %10s\n" "PAIR" "TRADES" "PROFIT%" "WIN%" "DRAWDOWN%"
echo "--------------------------------------------------------------"

for PAIR in "${PAIRS[@]}"; do
  # 临时修改配置只测单个币种
  RESULT=$(docker compose run --rm -e FREQTRADE_CONFIG=/freqtrade/config.json yolo backtesting \
    --config /freqtrade/base.json --config /freqtrade/config.json \
    --strategy YoloStrategy --timerange "$TIMERANGE" --timeframe 5m \
    --pairs "$PAIR" 2>&1)

  # 提取关键指标
  SUMMARY=$(echo "$RESULT" | grep "YoloStrategy" | tail -1)
  if [ -n "$SUMMARY" ]; then
    TRADES=$(echo "$SUMMARY" | awk -F'│' '{print $3}' | xargs)
    PROFIT=$(echo "$SUMMARY" | awk -F'│' '{print $5}' | xargs)
    WINRATE=$(echo "$SUMMARY" | awk -F'│' '{print $7}' | xargs | awk '{print $NF}')
    DRAWDOWN=$(echo "$SUMMARY" | awk -F'│' '{print $8}' | xargs | awk '{print $NF}')
    printf "%-22s %6s %10s %8s %10s\n" "$PAIR" "$TRADES" "$PROFIT" "$WINRATE" "$DRAWDOWN"
  else
    printf "%-22s %6s %10s %8s %10s\n" "$PAIR" "0" "N/A" "N/A" "N/A"
  fi
done

echo ""
echo "=== 筛查完成 ==="
