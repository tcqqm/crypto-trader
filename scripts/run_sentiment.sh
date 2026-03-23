#!/bin/bash
# YoloStrategy 情绪分析定时任务
# 每4小时运行：采集新闻 → 关键词评分 → 写入yolo_sentiment.json
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
cd /Users/yyzhao/workspace/projects/crypto-trader

python3 scripts/yolo_sentiment.py >> /tmp/yolo_sentiment.log 2>&1
