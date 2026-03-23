#!/bin/bash
# 逐币种回测 — 2年完整周期
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

TIMERANGE="20240319-20260319"
echo "=== YoloStrategy 币种筛查 2年 (${TIMERANGE}) ==="
echo ""
printf "%-22s %6s %12s %8s %10s\n" "PAIR" "TRADES" "PROFIT_USDT" "WIN%" "DRAWDOWN%"
echo "-------------------------------------------------------------------"

for PAIR in "${PAIRS[@]}"; do
  RESULT=$(docker compose run --rm yolo backtesting \
    --config /freqtrade/base.json --config /freqtrade/config.json \
    --strategy YoloStrategy --timerange "$TIMERANGE" --timeframe 5m \
    --pairs "$PAIR" 2>&1)

  # 从 BACKTESTING REPORT 提取单币种行（不是 STRATEGY SUMMARY）
  LINE=$(echo "$RESULT" | grep "$PAIR" | head -1)
  if [ -n "$LINE" ]; then
    TRADES=$(echo "$LINE" | awk -F'│' '{print $3}' | xargs)
    PROFIT=$(echo "$LINE" | awk -F'│' '{print $4}' | xargs)
    WININFO=$(echo "$LINE" | awk -F'│' '{print $7}' | xargs)
    WINPCT=$(echo "$WININFO" | awk '{print $NF}')

    # 提取 drawdown
    DD=$(echo "$RESULT" | grep "Absolute drawdown" | awk -F'│' '{print $2}' | grep -oE '[0-9]+\.[0-9]+%')

    printf "%-22s %6s %12s %8s %10s\n" "$PAIR" "$TRADES" "$PROFIT" "$WINPCT" "$DD"
  else
    printf "%-22s %6s %12s %8s %10s\n" "$PAIR" "0" "0.000" "N/A" "N/A"
  fi
done

echo ""
echo "=== 筛查完成 ==="
