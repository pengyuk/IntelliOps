# 后端实现待办清单

根据前端优化遇到的缺失功能整理。

## 优先级1: Copilot诊断与多轮对话（核心功能）

### POST /copilot/diagnose
**触发自动诊断**
- 输入：`incident_id`
- 输出：
  - `diagnosis_id` 
  - `candidate_root_causes: [{cause, confidence, evidence_chain, similar_incidents}]`
  - `initial_recommendations: [{step, tools, rationale}]`
  - `diagnostic_session_started: true`

**职责**：
- 自动收集30分钟内的日志异常、关键错误、依赖服务状态、最近变更
- 调用LLM进行多候选根因推理，每个带置信度百分比
- 关联历史案例库查找相似事故
- 初始推荐诊断步骤与对应工具

### POST /copilot/chat
**多轮对话**
- 输入：`{incident_id, diagnosis_id, user_id, message}`
- 输出：
  - `response` (Copilot回复，支持流式)
  - `suggested_actions: [{tool_id, rationale, confidence}]`
  - `script_generation_request: {code, language, confidence, explanation}`

**职责**：
- 维持诊断会话状态
- 根据维护输入不断迭代根因假设
- 推荐具体工具或生成脚本
- 在讨论区发消息时同步更新

## 优先级2: 脚本生成与管理

### GET /script/suggest
**推荐脚本**
- 输入：`{incident_id, diagnosis_id, diagnosis_context}`
- 输出：
  - `suggestions: [{script_id, code, language, confidence, category, risk_level}]`
  - `category`: "approved" | "copilot_generated" | "high_risk"

### POST /script/verify
**脚本预执行（Dry Run）**
- 输入：`{script_id, script_code}`
- 输出：
  - `dry_run_result`
  - `estimated_impact`
  - `approval_recommendation`

### POST /script/execute
**执行脚本**
- 输入：`{script_id, request_id, lifecycle_type}`
- `lifecycle_type`: "once" | "temp" | "permanent"
- 输出：
  - `execution_id`
  - `started_at`
  - 若设为permanent，自动入库为知识资产

### GET /script/{id}
**获取脚本详情**
- 返回：脚本代码、风险等级、审批状态、执行历史

## 优先级3: 讨论区与多角色沟通

### POST /incident/{id}/discussion
**发送讨论消息**（已有`/collaboration`，需扩展）
- 支持 `@mention` 标签
- 支持 `message_type`: "maintenance" | "development" | "copilot_summary"
- Copilot 可订阅讨论消息，自动发送总结

### GET /incident/{id}/discussion
**获取讨论消息流**
- 分页、搜索、类型筛选
- 包含@提及关系

## 优先级4: 自动复盘与知识积累

### POST /incident/{id}/postmortem
**触发自动复盘生成**
- 输入：`incident_id, mark_resolved=true`
- 输出：
  - `postmortem_id`
  - `timeline: [{timestamp, actor, action, result}]`
  - `root_cause_conclusion: {cause, confidence, evidence}`
  - `decisions: [{decision, rationale, timestamp, actor}]`
  - `tools_used: [tool_ids]`
  - `scripts_used: [{script_id, executed_by, result}]`
  - `improvement_suggestions: [...]`

**职责**：
- 聚合故障全程事件
- 生成格式化复盘报告
- 提供脚本永久化决策
- 自动入库知识资产

### GET /postmortem/{id}
**获取复盘报告**

### POST /postmortem/{id}/approve
**审批并发布复盘**
- 选择脚本是否永久化
- 决策是否转为改进任务

## 优先级5: 故障诊断上下文补充

### GET /incident/{id}/related-cases
**获取相似案例**（需增强）
- 输入：`incident_id, limit=5`
- 输出：`cases: [{incident_id, summary, root_cause, resolution_steps, scripts_used}]`
- **职责**：基于KG与历史相似度匹配

### GET /incident/{id}/knowledge-assets
**获取关联知识资产**
- SOP文档、脚本库、变更记录
- 按相关度排序

## 优先级6: LLM集成（如果已有LLM服务）

### 外部LLM配置
- 根因推理LLM
- 脚本生成LLM
- 对话LLM
- 复盘生成LLM
- 特殊：需要支持流式响应

---

## 当前已实现的（不需要改动）

✅ `/incidents` - 事故列表
✅ `/incident/{id}` - 事故详情
✅ `/incident/{id}/timeline` - 时间线
✅ `/incident/{id}/collaboration` - 评论（需扩展为讨论）
✅ `/kg/incident/{id}` - KG子图
✅ `/action/request` - 动作请求
✅ `/action/approve` - 动作审批
✅ `/action/execute` - 动作执行
✅ `/auth/users` - 用户管理

---

## 预估工作量

| 功能 | 复杂度 | 依赖 |
|------|--------|------|
| Copilot诊断 + 多轮对话 | 🔴 高 | LLM服务 |
| 脚本生成与验证 | 🔴 高 | Copilot诊断、LLM |
| 自动复盘与知识积累 | 🟡 中 | 时间线、脚本管理 |
| 讨论区多角色 | 🟡 中 | 无 |
| 相似案例与知识资产 | 🟡 中 | 案例库查询 |

---

## 实施建议

1. **阶段1**（当前）：前端框架优化 + 讨论区消息扩展
2. **阶段2**：Copilot诊断基础（无LLM版本用mock）
3. **阶段3**：脚本管理与LLM集成
4. **阶段4**：自动复盘与知识循环
