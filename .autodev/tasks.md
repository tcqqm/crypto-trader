# 任务列表

## 🔴 紧急 — 基础设施
- [x] INFRA-001: 安装 Freqtrade + FreqAI 环境（Docker）
- [x] INFRA-002: 配置回测框架和指标计算
- [ ] INFRA-003: 下载6个月历史K线数据

## 🟠 高优先级 — 核心策略
- [ ] STRAT-001: 实现市场状态识别模块（ADX+ATR+BB）
- [ ] STRAT-002: 实现趋势跟踪子策略（EMA交叉+多时间框架）
- [ ] STRAT-003: 实现均值回归子策略（RSI+BB边界）
- [ ] STRAT-004: 实现策略切换逻辑
- [ ] STRAT-005: 实现风控模块（止损/止盈/仓位管理）
- [ ] STRAT-006: 第一轮回测 + 结果分析

## 🟡 中优先级 — AI 增强
- [ ] AI-001: 实现新闻采集模块（CryptoPanic/RSS）
- [ ] AI-002: 实现 Claude 情绪评分
- [ ] AI-003: 情绪信号融合到策略
- [ ] AI-004: FreqAI ML 模型集成（LightGBM）

## 🟢 低优先级 — 优化迭代
- [ ] OPT-001: 参数优化（hyperopt）
- [ ] OPT-002: 多市场环境回测验证
- [ ] OPT-003: 过拟合检测和防护
- [ ] OPT-004: 模拟交易验证（dry-run 2周）
