#!/bin/bash
# YoloStrategy 情绪分析定时任务
# 每4小时运行：采集新闻 → Claude评分 → 写入yolo_sentiment.json
cd /Users/yyzhao/workspace/projects/crypto-trader
source ~/.zshrc 2>/dev/null

# 使用中转站 API
export ANTHROPIC_API_KEY=$(grep -o '"secret": "[^"]*"' configs/base.json | head -1 | cut -d'"' -f4 2>/dev/null || echo "")

# 如果没有从 base.json 获取到，尝试环境变量
if [ -z "$ANTHROPIC_API_KEY" ]; then
    export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
fi

python3 scripts/yolo_sentiment.py >> /tmp/yolo_sentiment.log 2>&1
