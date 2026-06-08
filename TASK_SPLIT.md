# 原型开发任务分工（能力轴·低耦合）

## 总体思路

为提高原型开发效率，建议两人按“能力轴”并行协作：Person A 专注大模型认知能力，Person B 专注数据与应用落地。双方通过明确的 JSON Schema/REST 接口解耦。
---

## 当前实现状态总览

### ✅ 后端 API 已全部覆盖（含 2026-06-06 新增端点）

所有前后端约定的 REST 端点均已有实现。**之前的 Mock/Stub 已全部替换为真实实现**：

| 模块 | 文件 | 现状（2026-06-06） |
|------|------|---------------------|
| LLM Client | `src/backend/llm_client.py` | ✅ 全异步、3 provider、流式、JSON mode、Token 追踪 |
| Root Cause Reasoner | `src/backend/reasoner.py` | ✅ 四阶段链式推理、json_mode、LLM+规则双模 |
| 存储层 | `src/backend/db.py` | ✅ SQLite 9 表持久化（aiosqlite, WAL） |
| 知识图谱 | `src/backend/knowledge_graph.py` | ✅ 邻接表+BFS+影响范围分析+模糊匹配 |
| 相似案例检索 | `src/backend/vector_search.py` | ✅ embedding/FAISS/TF-IDF 向量检索 |
| 脚本执行 | `app.py` `/script/execute` | ✅ 模拟执行+审计日志+Copilot 回传 |


## 待开发功能按层级梳理（现状：13/18 已完成）

### 🔴 高优先级（核心能力缺口）— ✅ 全部完成

| # | 缺口 | 状态 |
|---|------|------|
| 1 | **真实 LLM 根因推理** | ✅ `reasoner.py` 四阶段链式推理 |
| 2 | **日志智能分析** | ✅ `log_analyzer.py` LLM+规则双模 |
| 3 | **Copilot 多轮对话增强** | ✅ `copilot.py` 有状态会话 |
| 4 | **知识库 + 向量检索** | ✅ `vector_search.py` embedding/FAISS |
| 5 | **持久化存储** | ✅ `db.py` SQLite 9 表 |

### 🟡 中优先级（架构增强）— ✅ 全部完成

| # | 缺口 | 状态 |
|---|------|------|
| 6 | **WebSocket 实时推送** | ✅ `websocket_manager.py` + `/ws/incident/{id}` |
| 7 | **排查状态机** | ✅ `state_machine.py` 四象限 |
| 8 | **War Room Agent** | ✅ 讨论区 + WebSocket 广播 |
| 9 | **ETL 数据管道** | ✅ `data_service.py` 真实银行数据 |
| 10 | **真实知识图谱** | ✅ `knowledge_graph.py` 邻接表+BFS |
| 11 | **Skill 引擎独立模块** | ✅ `src/skill/` 9 个 SKILL.md |

### 🟢 低优先级（工程化与体验）— 5/7 部分完成

| # | 缺口 | 状态 |
|---|------|------|
| 12 | 前端重构为 React/Vue | ❌ B7 待开始 |
| 13 | Ontology CRUD 与版本演进 | ❌ 待开始 |
| 14 | 流式 LLM 响应（SSE/Stream） | ✅ `llm_client.py` `infer_stream()` |
| 15 | 真实 RBAC + API Token 鉴权 | 🟡 基础角色检查已实现 |
| 16 | 单元测试 + 集成测试 | ❌ 待开始 |
| 17 | Docker Compose + CI/CD | ✅ `Dockerfile` + `docker-compose.yml` |
| 18 | 复盘知识蒸馏自动入库 | ✅ `knowledge_distiller.py` |

---

## 角色说明

### Person A：大模型认知引擎

**职责**：让 AI "学会思考"——推理、分析、对话、蒸馏

主要负责：

- LLM 集成与 API 适配（流式响应、多模型切换、Token 管理）
- Prompt / few-shot 设计与评估（分阶段推理链）
- Root Cause Reasoner、Log Analyzer、Credibility Framework、Knowledge Distiller
- Copilot 多轮对话：上下文记忆、状态跟踪、动态追问
- 输出：推理结果 API（JSON）、置信度与依据链

典型交付：

- Prompt 模板库与评估报告
- 推理结果服务接口规范（JSON Schema）
- 单元/集成测试脚本用于验证推理质量

---

### Person B：数据平台与应用层

**职责**：让系统"有数据可用、有地方存、有界面看"——数据、存储、UI、部署

主要负责：

- 数据源接入与 ETL（CMDB/告警/日志/变更/工单）
- 持久化存储（SQLite → Postgres）
- 知识库与向量索引（Embedding 检索）
- Incident Graph（图数据库入图 + 多跳查询）
- Investigation State Machine、War Room Agent
- WebSocket 实时推送
- 前端增强与图可视化
- Docker 部署与 CI/CD
- 输出：标准化数据接口（JSON Schema）、执行审计

典型交付：

- ETL 脚本与样本数据集
- 向量索引与相似案例检索接口
- 前端原型（事故看板、事件详情、Action 执行、图可视化）
- Docker Compose 一键启动脚本


## 详细任务拆解（带估算）

### Person A：大模型认知引擎

| 编号 | 任务 | 具体内容 | 产出 | 预估 |
|------|------|----------|------|------|
| A1 | **LLM 集成升级** | 完善 `llm_client.py`：支持流式响应（SSE）、多模型切换（openai/anthropic/本地）、Token 用量管理、超时与重试 | 可配置的 LLM Client，环境变量驱动 | 3d |
| A2 | **Root Cause Reasoner 增强** | 设计分阶段 Prompt：现象归类 → 系统依赖 → 变更窗口 → 根因排序。每阶段输出中间推理，最终合并为置信度+证据链 | 真实 LLM 推理结果 JSON，非规则回退 | 3d |
| A3 | **Log Analyzer 日志智能分析** | 日志自动摘要（关键错误/异常/频率变化）、异常模式识别（与历史故障模式匹配）、多源日志关联（应用+中间件+主机+K8s Event） | `/copilot/diagnose` 自动注入日志分析上下文 | 4d |
| A4 | **Copilot 多轮对话增强** | 会话状态记忆（`diagnosis_id` 绑定上下文）、动态追问策略（信息不足时主动问）、排查进度感知（结合 Person B 的状态机） | 有状态诊断会话，逐步收窄根因 | 4d |
| A5 | **Knowledge Distiller 知识蒸馏** | 从复盘报告自动提炼：根因规则模式、预警条件、可复用 SOP 模板、脚本推荐 | 事后自动生成可入库的知识条目 | 3d |
| A6 | **Credibility Framework 可信度框架** | 为每个推理结果生成：置信度评分（0-1）、依据链列表、风险等级（high/medium/low）、不确定性说明 | 推理结果附带完整的可解释性信息 | 2d |

**Person A 总预估：≈ 19 人天** ✅ **已全部完成**

---

### Person B：数据平台与应用层

| 编号 | 任务 | 状态 | 具体内容 | 产出 | 预估 |
|------|------|------|----------|------|------|
| B1 | **持久化存储** | ✅ | SQLite（aiosqlite）9 表：incidents / timeline_events / discussions / scripts / diagnoses / action_logs / action_requests / postmortems / knowledge_assets。WAL 模式，全 async API，app.py 全部内存→DB 迁移 | 重启不丢数据，所有 CRUD 经 `db.py` | 3d |
| B2 | **ETL 数据管道** | ✅ | `data_service.py` 从 Excel/Word 加载真实数据：系统上下游关系、应用管理报表、告警记录、复盘报告。标准化实体 ID、时间戳、source_system | 可运行的 ETL + 真实银行数据（7 个文件） | 4d |
| B3 | **知识库 + 向量检索** | ✅ | `vector_search.py`：sentence-transformers 优先，TF-IDF fallback。FAISS 加速（可选）。替换集合交集逻辑 | 相似案例召回，支持 Top-K + 阈值 | 3d |
| B4 | **KG 入图** | ✅ | `knowledge_graph.py`：邻接表 + BFS 子图探索 + `impact_scope()` 影响范围分析 + 模糊匹配。`alarm_analyze.py` + `fault_diagnosis.py` 告警诊断管线 | 真实图查询 + 告警→系统→影响面 | 4d |
| B5 | **排查状态机** | ✅ | `state_machine.py`：verified / to_verify / high_risk / excluded 四象限。API：GET/POST /incident/{id}/investigation-state + /item + /move。DB 持久化 | 新加入者可立刻接管排查上下文 | 2d |
| B6 | **War Room + WebSocket** | ✅ | `websocket_manager.py`：按 incident 分组的 ConnectionManager。端点：WS /ws/incident/{id} + GET /ws/status。时间线写入自动广播 | 多人协同实时推送 | 4d |
| B7 | **前端增强** | ✅ | React + Vite + ECharts + Zustand + WebSocket。14 个源文件：App + 8 组件 + store + hooks。服务依赖力导向图、Copilot 流式对话、四象限面板布局 | 生产可用的 React SPA | 5d |
| B8 | **部署** | ✅ | `Dockerfile`（Python 3.12-slim）+ `docker-compose.yml`（单服务 + healthcheck）。环境变量模板 `.env.example` | 一键 `docker-compose up` 启动 | 3d |

**Person B 已完成：8/8 ✅ 全部完成**

---

## 共享接口契约（集成关键点）

双方在以下 5 个接口上必须对齐 JSON Schema，可各自独立开发与测试：

| 接口 | 提供方 | 消费方 | 关键字段 |
|------|--------|--------|----------|
| `POST /copilot/diagnose` 输出 | Person A | Person B（前端展示） | `candidate_root_causes[].cause` / `confidence` / `evidence_chain` / `confidence_level` |
| `POST /copilot/chat` 流式格式 | Person A | Person B（WebSocket 推送） | SSE event 格式，`response`、`suggested_actions[].tool_id`、`script_generation_request` |
| `GET /kg/*` 增强查询 | Person B | Person A（Prompt 上下文） | 多跳查询结果、节点属性、边类型 |
| `GET /incident/{id}` 扩展 | Person B | Person A（推理输入） | `kg_context`、`investigation_state`、`log_summary`（Person A 产出） |
| WebSocket 消息协议 | Person B | Person A（Copilot 订阅讨论） | `event_type`（timeline/diagnosis/discussion/execution）、`payload`、`incident_id`、`timestamp` |

---

## 协作方式与契约


- 接口优先：双方在阶段 1 完成前必须就上述 5 个接口达成 JSON Schema 共识
- 并行迭代：Person A/B 可各自独立开发与单元测试，集成时以接口契约为准
- 流程对齐：每日/隔日站会对接口变更与集成问题快速决策
- 独立可测：Person A 可用 mock 数据测试推理质量；Person B 可用 stub 推理结果测试 UI 与存储

---

## 推荐迭代顺序（两人并行三阶段）

```
阶段 1（Week 1-2）：打地基
  Person A:
    ├─ A1: LLM 集成升级 ─── 真实 LLM 调通，SSE 流式跑通
    └─ A2: Reasoner 增强 ─── 分阶段 Prompt，真实推理输出
  Person B:
    ├─ B1: 持久化存储 ────── SQLite 建表，内存→DB 迁移
    └─ B2: ETL 数据管道 ──── 丰富样本数据，标准化入库
  集成点: 确认 /copilot/diagnose 输出 Schema 对齐

阶段 2（Week 3-4）：能力上线
  Person A:
    ├─ A3: Log Analyzer ──── 日志摘要+异常识别+多源关联
    └─ A4: Copilot 多轮对话 ─ 有状态会话，动态追问
  Person B:
    ├─ B3: 向量检索 ──────── Embedding + FAISS/ChromaDB
    ├─ B4: KG 入图 ───────── NetworkX/Neo4j 多跳查询
    └─ B5: 排查状态机 ────── 四象限状态跟踪
  集成点: WebSocket 消息格式对齐，流式对话联调

阶段 3（Week 5-6）：闭环与交付
  Person A:
    ├─ A5: Knowledge Distiller ─ 复盘→知识条目
    └─ A6: Credibility Framework ─ 可信度+依据链
  Person B:
    ├─ B6: War Room + WebSocket ─ 实时推送+自动通知
    ├─ B7: 前端增强 ──────────── React + 图可视化 + 流式展示
    └─ B8: 部署 + CI/CD ──────── Docker Compose + Actions
  集成点: 端到端演练（告警→诊断→协同→执行→复盘）
```

---

## 交付验收点

| 阶段 | Person A 验收标准 | Person B 验收标准 |
|------|-------------------|-------------------|
| 阶段 1 | 真实 LLM 推理返回结构化根因（非规则回退）；Prompt 模板可评估 | SQLite 持久化运行，重启不丢数据；ETL 产出 ≥5 事故样本 |
| 阶段 2 | 日志分析摘要注入诊断上下文；Copilot 多轮对话保持状态不丢失 | 向量检索返回相似案例（非集合交集）；KG 支持 2-hop 查询；状态机 API 可读写 |
| 阶段 3 | ✅ 复盘→知识条目自动生成；推理结果附带完整可信度+依据链 | ✅ WebSocket 实时推送可用；Docker Compose 一键启动 |
| 终验 | ✅ 端到端：告警 → 诊断 → 对话 → 执行 → 复盘 → 知识入库 | 🟡 仅 B7 前端增强（React + 图可视化）待开始 |

---

## 架构对应关系（2026-06-06 实际实现）（2026-06-06 实际实现）

```
┌─────────────────────────────────────────────────────────┐
│                    Person A: 认知引擎 ✅                   │
│  llm_client.py  →  reasoner.py  →  Log Analyzer          │
│       ↓                     ↓                              │
│  Copilot Chat   ←  Credibility Framework                  │
│       ↓                                                    │
│  Knowledge Distiller (复盘→知识)                           │
└──────────────────────┬──────────────────────────────────┘
                       │ JSON Schema 契约
┌──────────────────────┴──────────────────────────────────┐
│                Person B: 数据平台与应用层 🟡               │
│  data_service.py → knowledge_graph.py → vector_search.py  │
│       ↓                    ↓                ↓              │
│  alarm_analyzer → fault_diagnosis → db.py (SQLite)       │
│       ↓                                                    │
│  state_machine.py → websocket_manager.py                  │
│       ↓                                                    │
│  Dockerfile + docker-compose.yml ✅                     │
│  ❌ React UI + 图可视化（B7 待开始）                       │
└─────────────────────────────────────────────────────────┘
```

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM API 不可用或延迟高 | Person A 全部任务阻塞 | 保留规则回退路径；本地模型（Ollama）做 fallback |
| 真实数据源（T-CMDB 等）无法接入 | Person B ETL 阻塞 | 用脚本生成更丰富的模拟数据，保留标准化接口后续接入 |
| 接口契约理解不一致 | 集成阶段大面积返工 | 阶段 1 结束前用 Postman/curl 互相验证对方接口输出 |
| 前端重构工作量超预期 | B7 延期 | B7 可拆为两步：先保留 HTML 原型但接 WebSocket，再迁移 React |
| 图数据库部署复杂 | B4 延期 | 优先 NetworkX + JSON 文件，验证场景后再换 Neo4j |

---

更多细节见 `MODULE_ARCHITECTURE.md`、`UPGRADE_PLAN.md`、`BACKEND_TODO.md`。
