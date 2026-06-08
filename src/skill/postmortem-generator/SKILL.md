---
name: postmortem-generator
description: >
  自动生成故障复盘报告并提取知识资产。触发词：复盘、总结、报告、回顾、postmortem、故障分析报告、改进措施、写报告、生成报告。使用场景：故障恢复后需要生成复盘文档时、需要提炼经验教训时、需要将脚本永久化入库时。
argument-hint: '<incident_id>'
---

# 复盘报告生成

## 何时使用

- 故障已标记为 Resolved 后
- 用户要求生成复盘报告时
- 需要从故障中提取可复用知识时
- 需要将验证过的脚本永久化入库时

## 前提条件

在生成复盘前确认：
1. 故障状态已更新（建议先标记为 Resolved）
2. 诊断会话中已有根因结论
3. 执行日志中有完整的操作记录

## 核心流程

### 步骤 1：生成复盘报告

调用后端 API：

```
POST {{base_url}}/incident/{{incident_id}}/postmortem
Content-Type: application/json

{
  "incident_id": "{{incident_id}}",
  "mark_resolved": true,
  "requested_by": "{{current_user_id}}"
}
```

响应中包含：
- `postmortem_id`：复盘报告 ID
- `timeline`：完整的事件时间线
- `root_cause_conclusion`：根因结论（含置信度）
- `decisions`：关键决策记录
- `tools_used`：使用的工具列表
- `scripts_used`：使用的脚本列表
- `improvement_suggestions`：改进建议
- `knowledge`：自动蒸馏的知识资产

### 步骤 2：展示复盘报告

以结构化格式展示：

```
📋 复盘报告：{{postmortem_id}}

🔍 根因结论
  • 根因：数据库连接池参数与业务负载不匹配
  • 置信度：85%

⏱️ 事件时间线
  14:20  告警触发：支付网关P99延迟异常
  14:22  AI诊断：识别为连接池耗尽型延迟
  14:25  执行：连接池指标检查
  14:30  确认：活跃连接450/500，慢查询27条
  14:35  决策：临时放宽连接池上限
  14:50  恢复：延迟回归正常

📊 知识资产（自动提取）
  🧠 根因规则：连接池参数不匹配导致高峰期连接耗尽
  ⚠️  预警信号：连接池使用率 > 80% 应触发告警
  📋 SOP：连接池故障处理流程（6步）
  🔧 脚本：连接池指标检查脚本（已入库）

💡 改进建议
  1. 连接池参数变更需增加审批流程
  2. 添加连接池使用率告警
  3. 将验证脚本沉淀为知识资产
```

### 步骤 3：审批与发布

如果用户确认报告无误，调用审批：

```
POST {{base_url}}/postmortem/{{postmortem_id}}/approve
Content-Type: application/json

{
  "approver": "{{current_user_id}}",
  "publish_scripts": ["script-metrics-inc-1"],
  "create_improvement_tasks": true
}
```

- `publish_scripts`：选择要永久化入库的脚本 ID 列表
- `create_improvement_tasks`：是否将改进建议转为跟踪任务

### 步骤 4：知识资产后续

生成的 `knowledge` 包含：

| 资产类型 | 说明 | 用途 |
|---------|------|------|
| `root_cause_rules` | 泛化的根因模式 | 未来自动匹配相似故障 |
| `warning_signals` | 预警指标和阈值 | 配置到监控系统 |
| `sop_templates` | 标准化操作流程 | 新人培训、下次参考 |
| `script_recommendations` | 可复用脚本 | 脚本库积累 |
| `key_learnings` | 关键经验教训 | 团队分享 |

通过 `GET /postmortem/{{postmortem_id}}/knowledge` 可随时获取。

## 注意事项

- 复盘报告一旦审批发布，内容不可修改（审计要求）
- 知识资产会自动去除具体主机名、IP、时间戳等敏感信息
- 如果故障涉及多个团队，建议审批前先同步各方确认内容
