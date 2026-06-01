# 原型开发任务分工（能力轴·低耦合）

## 总体思路

为提高原型开发效率，建议两人按“能力轴”并行协作：Person A 专注大模型认知能力，Person B 专注数据与应用落地。双方通过明确的 JSON Schema/REST 接口解耦。

## 角色说明

### Person A：大模型认知引擎

主要负责：

- LLM 集成与 API 适配
- Prompt / few-shot 设计与评估
- Root Cause Reasoner、Log Analyzer、Credibility Framework、Knowledge Distiller
- 输出：推理结果 API（JSON）、置信度与依据链

典型交付：

- Prompt 模板与评估报告
- 推理结果服务接口规范（JSON Schema）
- 单元/集成测试脚本用于验证推理质量

### Person B：数据平台与应用层

主要负责：

- 数据源接入与 ETL（CMDB/告警/日志/变更/工单）
- 知识库与向量索引、Incident Graph
- Investigation State Machine、War Room Agent、UI 与执行层
- 输出：标准化数据接口（JSON Schema）、执行审计

典型交付：

- ETL 脚本与样本数据集
- 向量索引与相似案例检索接口
- 前端原型（事故看板、事件详情、Action 执行）

## 协作方式与契约

- 接口优先：双方在阶段 A 完成前必须就主要接口（推理输入/输出、事件模型、Action 执行）达成 JSON Schema 共识
- 并行迭代：Person A/B 可各自独立开发与单元测试，集成时以接口契约为准
- 流程对齐：每日/隔日站会对接口变更与集成问题快速决策

## 推荐里程碑（原型三阶段）

1. 阶段 A（周 1-2）：数据管道 + 知识库 + UI 骨架；Person A 准备 LLM 环境与基本 Prompt 框架
2. 阶段 B（周 3-4）：上线 Root Cause Reasoner、Log Analyzer、Incident Copilot；完成推理结果对接与展示
3. 阶段 C（周 5-7）：War Room Agent、Knowledge Distiller、Incident Simulator；完成端到端演练与复盘闭环

## 交付验收点

- 阶段 A：可运行的 ETL、知识库、基础 UI（能展示 test incident）
- 阶段 B：可调用的推理 API、日志分析结果、copilot 对话能力
- 阶段 C：协同场景自动化、知识蒸馏样例、演练报告

---

更多细节见 `README.md` 中的原型交付与分工章节。
