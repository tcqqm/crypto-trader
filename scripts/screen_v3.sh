#!/bin/bash
# 逐币种独立回测 — 用 --pairs 参数覆盖配置
PAIRS=(
  "DOGE/USDT:USDT" "AVAX/USDT:USDT" "WIF/USDT:USDT" "FET/USDT:USDT"
  "NEAR/USDT:USDT" "INJ/USDT:USDT" "SUI/USDT:USDT" "ARB/USDT:USDT"
  "OP/USDT:USDT" "APT/USDT:USDT" "FIL/USDT:USDT" "ATOM/USDT:USDT"
  "DOT/USDT:USDT" "ADA/USDT:USDT" "XRP/USDT:USDT" "ENA/USDT:USDT"
  "TRX/USDT:USDT" "RENDER/USDT:USDT" "SOL/USDT:USDT" "LINK/USDT:USDT"
  "BTC/USDT:USDT" "ETH/USDT:USDT" "BNB/USDT:USDT" "WLD/USDT:USDT"
  "1000SATS/USDT:USDT"
)

echo "PAIR|TRADES|AVG_PROFIT|TOTAL_USDT|TOTAL_PCT|WIN_PCT"

for PAIR in "${PAIRS[@]}"; do
  # 运行回测，抓取 STRATEGY SUMMARY 行
  OUTPUT=$(docker compose run --rm yolo backtesting \
    --config /freqtrade/base.json --config /freqtrade/config.json \
    --strategy YoloStrategy --timerange 20240319-20260319 --timeframe 5m \
    --pairs "$PAIR" 2>&1)

  # 用 python 解析 rich 表格输出
  PARSED=$(echo "$OUTPUT" | python3 -c "
import sys, re
text = sys.stdin.read()
# 找 Final balance, Total profit %, total trades
trades = re.search(r'Total/Daily Avg Trades\s+.+?(\d+)\s', text)
profit_pct = re.search(r'Total profit %\s+.+?([-\d.]+)%', text)
profit_usdt = re.search(r'Absolute profit\s+.+?([-\d.]+)\s+USDT', text)
final = re.search(r'Final balance\s+.+?([-\d.]+)\s+USDT', text)
t = trades.group(1) if trades else '0'
pp = profit_pct.group(1) if profit_pct else '0'
pu = profit_usdt.group(1) if profit_usdt else '0'
# 找胜率
win = re.findall(r'(\d+)\s+0\s+(\d+)\s+([\d.]+)', text)
wp = win[-1][2] if win else '0'
print(f'{t}|{pu}|{pp}|{wp}')
" 2>/dev/null)

  if [ -n "$PARSED" ]; then
    echo "$PAIR|$PARSED"
  else
    echo "$PAIR|0|0|0|0"
  fi
done
