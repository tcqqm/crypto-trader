#!/bin/bash
# 环境安装脚本
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== 加密货币交易系统环境安装 ==="

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: 请先安装 Docker"
    exit 1
fi

echo "1. 拉取 Freqtrade Docker 镜像..."
docker pull freqtradeorg/freqtrade:stable

echo "2. 创建必要目录..."
mkdir -p freqtrade/user_data/{strategies,data,logs}
mkdir -p results/charts
mkdir -p sentiment

echo "3. 安装 Python 依赖（情绪分析模块）..."
pip install anthropic requests feedparser 2>/dev/null || \
    pip3 install anthropic requests feedparser 2>/dev/null || \
    echo "警告: Python 依赖安装失败，请手动安装"

echo "4. 验证 Freqtrade..."
docker compose run --rm freqtrade --version

echo ""
echo "=== 安装完成 ==="
echo "下一步: 运行 scripts/backtest.sh 下载数据并回测"
