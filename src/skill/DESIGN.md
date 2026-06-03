# Skill 设计

## 目标

构建面向故障应急的 Skill 组件，提供：

- 多轮问答式交互
- 结构化排查建议与根因推理
- KG/知识库上下文补全
- 自动化执行建议与权限审计
- 现场信息补录与调查状态跟踪

Skill 是能力层核心，承担“问题→推理→建议→执行”闭环。

## 位置与边界

Skill 组件属于能力层，承接：

- 输入：事件摘要、告警、变更、服务依赖、KG 上下文、用户问题
- 输出：建议步骤、根因候选、可执行动作、补录问题、可信度说明

与其他模块的关系：

- 数据层：消费标准化事件、告警、变更、CMDB、日志元信息
- 知识层：调用知识库/向量检索、KG 查询、历史案例查询
- Harness：生成动作建议并提交执行/审批
- UI：输出卡片、交互式建议、对话历史、KG 子图视图

## 核心能力拆解

### 1. 意图与槽位理解（NLU）

目标：把用户输入映射到运维场景意图与关键实体。

- 典型意图：`query_incident`、`suggest_steps`、`exec_action`、`attach_evidence`、`confirm_action`、`cancel_action`、`fill_context`
- 槽位：`incident_id`、`service_id`、`alert_id`、`time_range`、`change_id`、`evidence_type`
- 结果：标准化的 Skill request 包，如 `{
    "intent": "suggest_steps",
    "incident_id": "inc-001",
    "context": {"service_id": "svc-001", "symptom": "支付延迟"}
}`

### 2. 对话与场景管理

目标：在多轮排查中保持上下文、引导现场补录、避免重复提问。

- 状态机：`AwaitingIncidentId`、`CollectEvidence`、`RecommendAction`、`ConfirmExec`、`Closing`
- 场景：现场信息补录、排查步骤执行、自动化动作审批、复盘条目补全
- 机制：意图识别 → 槽位补全 → 任务生成 → 用户确认

### 3. KG / 知识库上下文补全

目标：结合 KG / 知识库提供关联事实、历史案例、SOP 模板、变更影响。

- KG 查询：服务依赖、受影响资源、相关告警、相关变更、历史事故
- 相似案例：向量检索或文本检索召回近似事件与排查路径
- SOP 映射：从 `suggest_steps` 输出可落地的操作模板或工单建议
- 证据链：把 KG 上下文转成 `evidence`、`reasoning_steps`

### 4. 根因推理与建议生成

目标：在故障场景中输出结构化根因候选、下一步诊断、风险说明。

- 输出结构：`candidate_root_causes`、`recommendation_steps`、`confidence_summary`、`risk_level`
- 技术路径：
  - LLM Prompt + KG/事件上下文
  - 规则与模板回退
  - 结构化 JSON 输出约定
- 典型能力：
  - 识别故障类型与优先排查点
  - 结合变更/告警判断“是否为变更引入”
  - 推荐“收集日志”、“检查链路”、“重启服务”等动作

### 5. 自动化执行与 Harness 集成

目标：把 Skill 的建议连接到 Harness 执行路径，并确保权限与审计。

- `exec_action` 流程：Skill 生成候选动作 → 用户确认 → Harness 下发 → 审计记录
- 参数模板：`action_id`、`params`、`requested_by`、`reason`
- 安全策略：高风险操作必须二次确认或走审批流
- 结果反馈：`audit_id`、`status`、`output`、`execution_record`

### 6. 输出与展示

目标：把 Skill 结果组织成前端可消费的卡片、时间线、KG 视图。

- 建议卡片：当前问题、推荐步骤、证据、置信度
- 操作卡片：自动化脚本、工单模板、复盘建议
- 时间线：已完成/待执行步骤、状态更新、证据补录
- KG 视图：相关服务、告警、变更、历史事件

## 设计原则

- 以事实驱动：优先引用事件字段、告警、变更、KG 关系
- 以可执行性为核心：建议必须落到“下一步动作”或“补录问题”
- 以可信度可解释：输出 `confidence` / `evidence` / `reasoning_steps`
- 以安全为底座：`exec_action` 需权限、审计、审批链
- 以迭代为目标：先用知识库检索与规则回退，后续加 LLM 推理

## 可下载组件 vs 自研模块

### 建议直接下载 / 组合使用

- NLU / 意图识别：Rasa、Dialogflow、LUIS、spaCy、Hugging Face Transformers
- 对话状态机框架：Rasa Core、Botpress、Microsoft Bot Framework、NLU + FSM 组合
- 向量检索与知识检索：FAISS、Milvus、Weaviate、Chromadb、Haystack
- KG/图查询库：Neo4j、py2neo、NetworkX、RDFLib、TigerGraph SDK
- LLM 接入与 SDK：OpenAI、Anthropic、LangChain、llama-cpp、LlamaIndex
- REST/微服务框架：FastAPI、Flask、Express
- 审计与权限基础：现成 RBAC 中间件、JWT、ACL 方案

### 需要自行开发的 Skill 价值层

- 故障场景意图与槽位定义：适配本项目 `Incident` / `Service` / `Change` 语义
- 现场排查流程与状态机：调查步骤、补录问题、排查闭环
- 根因推理 Prompt 设计与可信度框架：`reasoning_steps`、`evidence`、`confidence_summary`
- 推荐步骤与 SOP/Action 映射：从 KG/知识库结果到“可执行动作”
- `exec_action` 审批/二次确认流程：权限、审计、回滚、结果回写
- 事故上下文拼装：事件 + KG + 历史案例的融合规则
- 复盘信息蒸馏与知识更新：自动写入 SOP、故障案例、经验标签
- 本地适配层：公司内现有 CMDB、告警系统、变更平台的数据规范

## 迭代建议

1. MVP 阶段
   - 先做“查询事件 + 推荐排查步骤 + KG 上下文卡片”
   - 采用规则回退 + 简单 LLM Prompt
   - 先用 JSON / 内存 KG 形式验证

2. 第二阶段
   - 加入“多轮问答 + 状态机 + 证据补录”
   - 引入向量检索历史故障
   - 规范返回结构化根因与置信度

3. 第三阶段
   - 提升“执行建议 → Harness 审批/执行 → 结果回写”闭环
   - 加入“知识蒸馏与复盘”能力
   - 考虑从知识库向 KG 子图演进

