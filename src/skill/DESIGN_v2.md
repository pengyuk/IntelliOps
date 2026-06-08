# Skill 组件设计（能力层核心）

## 定位

> Skill 是能力层的核心引擎，承接"故障问题 → 根因推理 → 处置建议 → 执行闭环"的完整链路。它不只是一个问答机器人，而是一个**具备领域认知能力的应急协同智能体**。

在五层架构（数据层 → 认知层 → 智能体层 → 执行层 → 闭环学习层）中，Skill 横跨认知层和智能体层：向下消费 Person A 的推理/分析/蒸馏能力，向上驱动 Person B 的应用层 UI 和执行层 Harness。

```
┌─────────────────────────────────────────────────────────────┐
│                      Skill 引擎（能力层）                      │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ NLU 意图  │  │ 对话管理  │  │ 知识检索  │  │ 执行编排     │ │
│  │ 分类器   │  │ 状态机   │  │ 适配器   │  │ 适配器       │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│       │             │             │               │         │
│  ┌────┴─────────────┴─────────────┴───────────────┴──────┐  │
│  │                  Skill Orchestrator                    │  │
│  │      意图 → 槽位 → 上下文 → 推理 → 建议 → 执行          │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────┬────────────────────────────────────┘
                       │
    ┌──────────────────┼──────────────────┐
    ▼                  ▼                  ▼
┌────────┐    ┌──────────────┐    ┌────────────┐
│ Person A│    │  Person B    │    │  Harness   │
│ 认知引擎│    │  数据平台    │    │  执行框架  │
└────────┘    └──────────────┘    └────────────┘
```

---

## 与已实现模块的关系

Person A 已完成的模块为 Skill 提供了坚实的基础能力：

| 已实现模块 | Skill 消费方式 |
|-----------|---------------|
| `llm_client.py` | Skill 的 LLM 调用入口（意图分类、对话生成、知识检索） |
| `reasoner.py` | 根因推理能力，Skill 直接调用 `infer_root_causes()` |
| `log_analyzer.py` | 日志分析上下文注入 Skill 的诊断流程 |
| `copilot.py` | **已实现 Skill 的核心对话能力**，Skill 层在此基础上抽象为可插拔的 Skill 插件 |
| `credibility.py` | 可信度评分，Skill 输出建议时附带可信度元数据 |
| `knowledge_distiller.py` | 复盘后自动提炼知识，Skill 的知识库更新来源 |

**关键判断**：`copilot.py` 已经实现了 Skill 的"对话+推理"核心闭环。Skill 模块的增量工作是将这套能力**抽象为可配置、可组合的 Skill 插件体系**，而不是重写对话逻辑。

---

## Skill 分类与边界

### 第一类：对话式 Skill（已基本实现）

> 以自然语言对话为载体，引导用户完成故障排查。

- **Incident Diagnosis Skill** → 对应 `copilot.py` + `reasoner.py`，✅ 已实现
- **Log Analysis Skill** → 对应 `log_analyzer.py`，✅ 已实现
- **Knowledge QA Skill** → 基于 KG + 向量检索的问答，🔧 待接入 Person B 的向量检索

### 第二类：任务式 Skill（需新建）

> 以结构化任务流为骨架，自动执行多步诊断或处置。

- **Investigation Checklist Skill** → 按 SOP 模板自动逐项检查，输出检查报告
- **Change Impact Analysis Skill** → 输入变更 ID，自动分析影响范围
- **Postmortem Drafting Skill** → 调用 `knowledge_distiller.py` 自动生成复盘报告

### 第三类：触发式 Skill（远期）

> 由事件驱动自动触发，无需人工交互。

- **Alert Triage Skill** → 告警接入时自动分级、关联历史、预判根因
- **Anomaly Detection Skill** → 指标异常时自动启动诊断流程
- **SLA Breach Prediction Skill** → 预测性告警与提前干预

---

## 核心能力矩阵

| 能力维度 | 实现方式 | 状态 |
|---------|---------|------|
| **意图识别（NLU）** | LLM few-shot 分类 + 规则回退 | 🔧 待封装为独立模块 |
| **槽位填充** | LLM 提取 + JSON Schema 校验 | 🔧 待封装 |
| **对话状态管理** | `copilot.py` 的 `conversation_history` | ✅ 已实现 |
| **知识检索（RAG）** | 待对接 Person B 的向量索引 | 🔜 依赖 Person B |
| **KG 上下文补全** | `app.py` 的 KG 查询 API | ✅ 已实现 |
| **根因推理** | `reasoner.py` 四阶段链式推理 | ✅ 已实现 |
| **日志分析** | `log_analyzer.py` 多模分析 | ✅ 已实现 |
| **可信度评估** | `credibility.py` 多维评分 | ✅ 已实现 |
| **执行编排** | Harness 的 Action API | ✅ 已实现 |
| **知识蒸馏** | `knowledge_distiller.py` | ✅ 已实现 |

---

## 可下载组件 vs 自研模块

### 🟢 建议直接下载/复用的开源组件

| 组件 | 用途 | 推荐方案 | 理由 |
|------|------|---------|------|
| **Embedding 模型** | 向量检索的文本编码 | `sentence-transformers` (all-MiniLM-L6-v2) 或 `BAAI/bge-small-zh` | 成熟、免费、本地部署，无需自研 |
| **向量数据库** | 存储 embeddings + 相似检索 | **ChromaDB**（轻量）或 **FAISS**（高性能） | 开源、Python 原生、与 FastAPI 易集成 |
| **LLM 对话框架** | Prompt 模板、Chain 编排 | **LangChain**（可选，非必需） | 我们的 `llm_client.py` 已覆盖核心能力；LangChain 仅在需要复杂 Chain（如多步 RAG + Tool use）时引入 |
| **NLU 意图分类** | 轻量意图识别 | **LLM 自身**（用 few-shot prompt 做分类） | 现代 LLM 的意图分类能力已经足够好，无需专用 NLU 模型。如需离线方案可用 `Rasa` |
| **JSON Schema 校验** | 结构化输出验证 | **Pydantic**（已在使用） | 项目已依赖，直接用 |
| **异步任务队列** | 后台 Skill 执行 | **Celery + Redis** 或 **FastAPI BackgroundTasks** | 触发式 Skill 需要异步执行 |
| **流式输出** | SSE 推送诊断进度 | **sse-starlette** | FastAPI 生态，轻量引入 |

### 🔴 必须自研的核心模块

| 模块 | 原因 | 复杂度 |
|------|------|--------|
| **Skill Orchestrator** | 编排意图→槽位→推理→建议→执行的完整链路，是 Skill 引擎的核心 IP | 🔴 高 |
| **SRE 领域 Prompt 工程** | 运维场景的 few-shot 模板、思维链设计，需要深厚的领域知识 | 🔴 高 |
| **Skill Registry（插件注册）** | Skill 的注册、发现、热加载机制，支撑可扩展的 Skill 生态 | 🟡 中 |
| **KG 查询适配器** | 将自然语言意图翻译为 KG 查询（Cypher/Gremlin），需要理解我们的本体设计 | 🟡 中 |
| **Harness 执行适配器** | Skill 输出 → Harness Action 的安全转换，含权限校验和审计 | 🟡 中 |
| **Conversation Context Manager** | 跨 Skill 的会话上下文共享，基于 `copilot.py` 扩展 | 🟡 中 |
| **Investigation State Machine** | 跟踪排查四象限（已验证/待验证/高风险/已排除），业务逻辑强定制 | 🟡 中 |
| **Domain Entity Resolver** | 将 NL 中的服务名/主机名映射到 KG 实体 ID，需要对接 CMDB 命名规范 | 🟢 低 |

### 🟡 可部分复用但需定制

| 模块 | 开源基础 | 需定制部分 |
|------|---------|-----------|
| **RAG Pipeline** | LlamaIndex / LangChain 的 RAG 组件 | 需要定制 SRE 文档的分块策略、检索后重排序逻辑 |
| **Alert Enrichment** | 通用的告警丰富化框架 | 需要对接 T-OPM、T-CMDB 的特定数据模型 |
| **Chat UI 组件** | 开源 Chat UI（如 Chatbot UI） | 需要嵌入 War Room 工作间，与非聊天组件（KG图、时间线）联动 |

---

## 推荐技术栈

```
Skill 引擎
├── LLM 推理层:    llm_client.py (已有) + LangChain (可选，复杂 Chain 时引入)
├── 向量检索:      ChromaDB + sentence-transformers (Person B 搭建)
├── 意图分类:      LLM few-shot (原生) + Pydantic 校验
├── 对话管理:      copilot.py (已有) → 抽象为 SkillOrchestrator
├── 异步执行:      FastAPI BackgroundTasks (简单) / Celery (复杂)
├── 流式推送:      sse-starlette + WebSocket (Person B 搭建)
├── 知识存储:      JSON → SQLite → Postgres (Person B 搭建)
└── 监控埋点:      Prometheus metrics (远期)
```

---

## 实现路线图

### 阶段 1（当前）：夯实基础 — 不新建模块，封装已有能力

```
copilot.py + reasoner.py + log_analyzer.py + credibility.py
                    ↓ 封装为
           SkillOrchestrator (新建)
                    ↓
        统一的 Skill 调用入口，支持:
        - 同步/异步调用
        - 标准化输入输出 Schema
        - 错误处理与回退
```

**新增文件**：`src/skill/orchestrator.py`
**依赖**：无新增外部依赖
**产出**：一个 `SkillOrchestrator.run(skill_name, context)` 接口

### 阶段 2（依赖 Person B）：接入知识层

```
SkillOrchestrator
    ├── 对接 ChromaDB 向量检索 → 真实 RAG
    ├── 对接 Neo4j/NetworkX KG → 多跳查询
    └── 对接 Investigation State Machine → 状态感知
```

**新增文件**：`src/skill/knowledge_adapter.py`、`src/skill/state_adapter.py`
**新增依赖**：`chromadb`、`sentence-transformers`

### 阶段 3（远期）：Skill 插件化

```
SkillOrchestrator
    ├── SkillRegistry (技能注册中心)
    ├── IncidentDiagnosisSkill (已注册)
    ├── LogAnalysisSkill (已注册)
    ├── ChangeImpactSkill (新注册)
    ├── AlertTriageSkill (新注册)
    └── PostmortemDraftingSkill (新注册)
```

**新增文件**：`src/skill/registry.py`、各 Skill 插件文件
**新增依赖**：无

---

## 关键接口设计

### SkillOrchestrator 输入

```json
{
  "skill": "incident_diagnosis",
  "incident_id": "inc-1",
  "user_id": "ui-user",
  "message": "用户输入或为空（自动触发）",
  "context": {
    "include_log_analysis": true,
    "include_kg_context": true,
    "max_turns": 10
  }
}
```

### SkillOrchestrator 输出

```json
{
  "skill": "incident_diagnosis",
  "status": "completed",
  "response": {
    "message": "Copilot 的自然语言回复",
    "diagnosis": { "...": "完整诊断结果" },
    "suggested_actions": ["...枚举可执行动作..."],
    "evidence_chain": ["...可追溯证据链..."],
    "credibility": { "adjusted_confidence": 0.72, "level": "high" }
  },
  "next_skills": ["log_analysis", "change_impact"],
  "execution_id": "exec-xxxx"
}
```

---

## 设计原则

1. **组合优于继承**：Skill 通过组合已有模块（reasoner / copilot / credibility）实现，而非重写
2. **LLM 原生**：意图分类、槽位填充、对话生成均使用 LLM，避免传统 NLU 管道的复杂性
3. **渐进式增强**：先用规则 + LLM，再引入 RAG，最后加 Agent 自主决策
4. **安全边界**：所有执行类 Skill 必须经过 Harness 的审批和审计链路
5. **可观测**：每个 Skill 调用记录 trace_id、耗时、token 用量、置信度
6. **中文优先**：所有 Prompt 模板和输出以中文为主，适配信创运维场景

---

## 不做的事情

- ❌ 不构建独立的 NLU 模型训练管线（LLM 原生意图分类已足够）
- ❌ 不实现图数据库查询引擎（由 Person B 的 KG Service 提供）
- ❌ 不实现前端聊天 UI（由 Person B 的应用层负责）
- ❌ 不实现实时消息推送（由 Person B 的 WebSocket 层负责）
- ❌ 不过度抽象——Skill 插件化在阶段 3 才做，现阶段保持简单

---

## 总结：下载 vs 自研决策表

| 层次 | 下载/复用 | 自研 |
|------|----------|------|
| LLM 调用 | — | `llm_client.py` ✅ 已有 |
| 意图分类 | LLM few-shot（免费） | Prompt 模板（自研） |
| 向量检索 | ChromaDB + sentence-transformers | 知识适配器（自研，对接层薄） |
| 对话管理 | — | `copilot.py` + `orchestrator.py`（自研） |
| 根因推理 | — | `reasoner.py` ✅ 已有 |
| 日志分析 | — | `log_analyzer.py` ✅ 已有 |
| 可信度 | — | `credibility.py` ✅ 已有 |
| 知识蒸馏 | — | `knowledge_distiller.py` ✅ 已有 |
| 异步任务 | Celery（可选） | FastAPI BackgroundTasks（优先） |
| 流式推送 | sse-starlette | — |
| 图查询 | — | Person B 自研，Skill 只做适配 |

**结论**：Skill 模块 80% 的能力已由 Person A 实现的模块覆盖。当前阶段只需新建 `orchestrator.py` 做统一封装，阶段 2 引入 ChromaDB 做向量检索，阶段 3 做插件化。**无需引入重量级框架，保持轻量。**
