---
name: incident-diagnosis
description: >
  故障应急诊断与根因推理。触发词：故障、事故、incident、诊断、根因、排查、告警、延迟、错误率、CPU高、内存泄漏、响应慢、超时、timeout、502、503、服务挂了、出问题了。使用场景：运维人员报告故障时、告警触发时、需要分析根因时、需要排查建议时。
argument-hint: '<incident_id 或故障现象描述>'
user-invocable: true
disable-model-invocation: false
---

# 故障应急诊断

## 何时使用

- 收到告警通知或用户报告故障时
- 运维人员描述故障现象（延迟高、错误率上升、服务不可用等）
- 需要自动生成根因假设和排查建议时
- 已有 incident_id 需要深入分析时

## 核心流程

### 步骤 1：接收故障信息

从用户输入中提取：
- `incident_id`（如果用户提供了）
- 故障现象关键词（延迟、错误率、CPU、内存、超时等）
- 受影响的服务或组件名称

如果用户只描述了现象但没有 incident_id，先通过现象匹配已有事故或建议创建新事故。

### 步骤 2：启动诊断会话

调用后端 API 进行自动诊断：

```
POST {{base_url}}/copilot/diagnose
Content-Type: application/json

{
  "incident_id": "<提取的 incident_id>",
  "user_id": "{{current_user_id}}"
}
```

如果用户没有提供 incident_id，先用 `GET /incidents` 查找匹配的事故。

### 步骤 3：解读诊断结果

从响应中提取并向用户展示：

| 字段 | 含义 | 展示方式 |
|------|------|---------|
| `candidate_root_causes[]` | 候选根因列表 | 按置信度降序展示，每个附带证据链 |
| `log_analysis` | 日志分析摘要 | 展示关键异常和跨源关联 |
| `initial_recommendations[]` | 推荐诊断步骤 | 优先展示低风险只读步骤 |
| `confidence_summary` | 综合置信度 | 用百分比+可信度等级展示 |
| `credibility` | 可信度评估 | 说明置信度受哪些因素影响 |

**解读原则**：
- 优先关注 `credibility_level: high` 的候选根因
- 如果所有候选 `credibility_level` 都是 `low`，建议补充日志或指标数据
- 跨源关联（`log_analysis.correlations`）如果显示"应用+数据库"模式，优先排查数据库侧

### 步骤 4：引导用户补充信息

根据诊断结果缺口，主动提问：

- 如果缺少日志数据 → "需要我帮你分析最近30分钟的日志吗？"
- 如果变更记录为空 → "故障时间窗口内是否有已知的变更？"
- 如果候选根因置信度相近 → "当前有多个可能性相近的假设，建议先排除哪一个？"
- 如果已识别到高置信度根因 → "根因已初步定位，是否需要生成处置脚本？"

### 步骤 5：多轮对话深入分析

调用 `POST /copilot/chat` 进行带状态的交互式诊断：

```
POST {{base_url}}/copilot/chat
Content-Type: application/json

{
  "incident_id": "<incident_id>",
  "diagnosis_id": "<从步骤2获取的 diagnosis_id>",
  "user_id": "{{current_user_id}}",
  "message": "<用户补充的信息>"
}
```

每次对话后关注 `confidence_trend`：
- `improving` → 方向正确，继续
- `stable` → 需要新证据突破
- `declining` → 当前假设可能错误，考虑切换排查方向

### 步骤 6：进入处置阶段

当根因置信度 ≥ 70% 时，建议转入处置：

1. 提示用户：根因已初步确认，建议进入脚本执行阶段
2. 告诉用户使用 `/script` 命令或直接说"生成处置脚本"
3. 如果涉及多人协同，提示使用 `/war-room` 通知相关人员

## 常见诊断模式

参考 [根因模式参考](./references/root-cause-patterns.md) 了解常见故障模式及其诊断路径。

## API 参考

详细的 API 字段说明见 [诊断 API 参考](./references/diagnosis-api.md)。

## 注意事项

- 诊断结果来自 AI 推理，不是 100% 准确的，需要用实际数据验证
- 高风险操作（重启、配置变更）必须在诊断确认后走审批流程
- 如果诊断超过 3 轮仍无明确结论，建议升级为人工主导排查
