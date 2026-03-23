#!/bin/bash
# Crypto Trader 监控脚本 — 检查 unified + yolo bot 状态，异常时 Telegram 告警
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

BOT_TOKEN="8484351681:AAEHfWrCnylZESB05Tm9O6uX783gSXYedCA"
CHAT_ID="-5228891470"
AUTH="freqtrader:freqtrader"

send_alert() {
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" -d "text=$1" -d "parse_mode=Markdown" > /dev/null 2>&1
}

check_bot() {
    local name=$1 container=$2 port=$3
    local API_URL="http://localhost:${port}/api/v1"

    # 1. 检查容器是否运行
    if ! docker ps --format '{{.Names}}' | grep -q "$container"; then
        send_alert "🚨 *Crypto Trader 告警*: ${name} 容器已停止！"
        echo "$(date '+%Y-%m-%d %H:%M') | ${name} 异常 | 容器已停止"
        return 1
    fi

    # 2. 检查 API 是否响应
    PING=$(curl -s -u $AUTH --max-time 5 "$API_URL/ping" 2>/dev/null)
    if [ "$PING" != '{"status":"pong"}' ]; then
        send_alert "🚨 *Crypto Trader 告警*: ${name} API 无响应！"
        echo "$(date '+%Y-%m-%d %H:%M') | ${name} 异常 | API 无响应"
        return 1
    fi

    # 3. 检查最近日志是否有严重错误
    ERRORS=$(docker compose -f ~/workspace/projects/crypto-trader/docker-compose.yml logs "$name" --since 10m 2>&1 | grep -c "Could not load markets\|RequestTimeout.*exchangeInfo\|CRITICAL")
    if [ "$ERRORS" -gt 3 ]; then
        send_alert "🚨 *Crypto Trader 告警*: ${name} 最近10分钟有 ${ERRORS} 次连接错误！"
    fi

    # 4. 获取当前状态摘要
    PROFIT=$(curl -s -u $AUTH --max-time 5 "$API_URL/profit" 2>/dev/null)
    TRADES=$(echo "$PROFIT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'交易: {d[\"trade_count\"]}笔, 已平仓: {d[\"closed_trade_count\"]}笔, 利润: {d[\"profit_closed_coin\"]:.2f}U')" 2>/dev/null)

    if [ -n "$TRADES" ]; then
        echo "$(date '+%Y-%m-%d %H:%M') | ${name} 正常 | $TRADES"
    else
        echo "$(date '+%Y-%m-%d %H:%M') | ${name} 正常 | 无交易数据"
    fi
}

# 检查两个 bot
check_bot "unified" "crypto-unified" 8083
check_bot "yolo" "crypto-yolo" 8084
