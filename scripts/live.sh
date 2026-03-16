#!/bin/bash
# 实盘/模拟交易启动脚本
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

MODE="${1:-dry}"  # dry（模拟）或 live（实盘）

if [ "$MODE" = "live" ]; then
    echo "⚠️  即将启动实盘交易！"
    echo "请确认已配置 Binance API Key（config.json）"
    read -p "确认启动？(y/N) " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "已取消"
        exit 0
    fi
    # 实盘模式：关闭 dry_run
    docker compose run --rm freqtrade trade \
        --config /freqtrade/config.json \
        --strategy AdaptiveStrategy \
        --db-url sqlite:///freqtrade/user_data/tradesv3_live.sqlite
else
    echo "=== 启动模拟交易（dry-run）==="
    docker compose up -d
    echo "模拟交易已启动"
    echo "查看日志: docker compose logs -f"
    echo "停止: docker compose down"
fi
