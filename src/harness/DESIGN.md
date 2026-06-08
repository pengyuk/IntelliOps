# Harness 设计（自动化执行）— 已吸收，无需独立模块

## 结论

> **IntelliOps 不需要独立的 Harness 模块。** 其设计目标已被 Person A 的后端 API 和 Skill 体系完全覆盖。

## 判断依据

### 1. Harness.io 与本项目的 "Harness" 是不同概念

| 维度 | Harness.io（业界平台） | IntelliOps "Harness" |
|------|----------------------|---------------------|
| 定位 | 开源 CI/CD 平台（36k+ GitHub stars） | 应急操作执行框架 |
| 语言 | Go + TypeScript | Python（FastAPI） |
| 核心功能 | 代码托管、CI/CD 流水线、制品仓库 | 脚本执行、审批、审计、回滚 |
| 与 IntelliOps 关系 | **无关**（不同领域） | 项目内部概念 |

Harness.io 是 DevOps 流水线平台，不提供 Runbook 自动化或故障响应能力。如果未来需要 CI/CD 能力，可以直接部署 Harness.io 作为**外部依赖**，但这不是当前原型的范围。

### 2. 原 Harness 设计目标已被现有实现覆盖

原设计文档列出的需求及对应实现：

| 原 Harness 需求 | 现有实现 | 位置 |
|----------------|---------|------|
| 模板库（操作定义） | `sample_actions.json` + `_script_suggestions()` | `src/harness/sample_actions.json`, `app.py` |
| 执行器（异步/超时/重试） | `POST /script/execute`（含模拟执行） | `app.py` |
| 权限与审批 | `POST /action/request` + `POST /action/approve` | `app.py` |
| 监控与审计 | `ACTION_LOGS` + `GET /action/logs` | `app.py` |
| 模拟模式（dry-run） | `POST /script/verify` | `app.py` |
| 回滚机制 | `sample_actions.json` 中 `rollback` 字段 | 数据层 |

此外，Skill 层的 `script-operations` Skill 教会 AI 代理：
- 何时调用哪个执行 API
- 如何判断风险等级
- 何时走审批流程
- 如何解读执行结果并回传 Copilot

### 3. 架构简化收益

取消独立 Harness 模块后：

```
Before（四模块）:
  能力层 = Skill 引擎 + Harness + 协同引擎 + 规则引擎

After（三模块）:
  能力层 = Skill 体系（含执行编排） + 协同引擎 + 规则引擎
```

Harness 的"执行编排"职责由 Skill 的 `script-operations` 接管，"脚本管理"由 `app.py` 的 `/script/*` 端点接管。减少一个模块意味着更少的接口契约、更简单的部署、更清晰的责任边界。

## 保留内容

| 文件 | 处理方式 |
|------|---------|
| `src/harness/sample_actions.json` | ✅ 保留（作为示例数据，被 `app.py` 加载使用） |
| `src/harness/DESIGN.md` | ✅ 保留（本文档，记录决策理由） |

## 未来扩展

如果原型验证后需要更强大的执行能力（分布式执行、真实沙箱、多步骤流水线），有两类方案：

**方案 A：增强现有端点**
- 将 `_simulate_script_output()` 替换为真实执行器
- 添加 `POST /script/execute/batch` 支持多步骤
- 保持架构简洁

**方案 B：引入外部 Runbook 工具**
- Rundeck（开源 Runbook 自动化）
- StackStorm（事件驱动自动化）
- 通过 API 集成，而非自建

当前原型阶段选择方案 A。

---

## 术语对照

| 项目术语 | 业界对应 |
|---------|---------|
| Harness（原概念） | Runbook Automation / SOAR |
| Harness.io（同名平台） | CI/CD Platform（不相关） |

