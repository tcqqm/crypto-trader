# Crypto Trader — AutoDev 工作指南

## 项目概述
加密货币自适应交易系统，基于 Freqtrade 框架，通过市场状态识别自动切换策略。

## 技术栈
- Freqtrade + FreqAI（交易引擎）
- Python 3.11+（策略代码）
- ccxt（交易所接口）
- Claude API（情绪分析）
- Docker（运行环境）

## 关键文件
- `freqtrade/user_data/strategies/adaptive_strategy.py` — 核心策略
- `freqtrade/config.json` — Freqtrade 配置
- `risk/manager.py` — 风控引擎（硬编码规则，不可随意修改）
- `sentiment/scorer.py` — Claude 情绪评分
- `results/backtest_history.json` — 回测历史

## 回测命令
```bash
docker compose run --rm freqtrade backtesting \
  --config /freqtrade/config.json \
  --strategy AdaptiveStrategy \
  --timerange 20250901-20260301 \
  --timeframe 5m
```

## 迭代规则
1. 每次修改策略后必须运行完整回测
2. 回测结果记录到 results/backtest_history.json
3. 只保留指标改善的版本
4. 避免过拟合：train/test 分割验证，差异 < 20%
5. 参数微调不应导致大幅变化（过拟合信号）

## 风控规则（不可修改）
- 单笔止损 -2%，止盈 +4%（移动止盈）
- 盈亏比最低 1:2
- 单笔仓位 10-20%，同时最多 3 仓
- 日亏损 -5% 停止，连亏 5 笔暂停 24h
- 情绪 < -0.5 不开多仓

## 代码规范
- 策略代码注释用中文
- 变量名用英文
- 无未来函数/数据泄露
- 所有指标在 populate_indicators 中计算
