---
name: script-operations
description: >
  应急脚本生成、预执行校验与安全执行。触发词：脚本、执行、运行、命令、修复、重启、检查、预执行、dry-run、dry run、生成脚本、写个脚本、执行脚本。使用场景：需要生成诊断/处置脚本时、需要验证脚本安全性时、需要执行处置操作时。
argument-hint: '<脚本用途描述>'
---

# 应急脚本操作

## 何时使用

- 诊断确认根因后需要执行处置操作
- 需要生成诊断检查脚本
- 执行前需要验证脚本安全性
- 需要管理脚本生命周期（一次性/临时/永久）

## 安全原则（最重要）

**始终遵守以下安全规则：**

1. **只读优先**：优先推荐只读脚本（查询、检查、采集），避免直接修改
2. **Dry-Run 强制**：任何新生成或未经验证的脚本，必须先执行 `POST /script/verify` 进行 dry-run
3. **高风险审批**：标记为 `risk_level: high` 的脚本必须经过审批后才能执行
4. **执行审计**：每次执行都会记录到审计日志，包含操作人、时间、输出

参考 [风险分级矩阵](./references/risk-matrix.md) 判断脚本风险等级。

## 核心流程

### 步骤 1：获取脚本建议

调用后端 API 获取推荐的脚本：

```
GET {{base_url}}/script/suggest?incident_id=<incident_id>&diagnosis_id=<diagnosis_id>
```

响应中每个脚本包含：
- `script_id`：唯一标识
- `name`：脚本名称
- `category`：`approved`（已验证可用）/ `copilot_generated`（AI生成待验证）/ `high_risk`（高风险需审批）
- `risk_level`：`low` / `medium` / `high`
- `approval_required`：是否需要审批
- `explanation`：脚本用途说明
- `code`：脚本代码

### 步骤 2：风险判断

根据 `risk_level` 决定流程：

| risk_level | 含义 | 流程 |
|-----------|------|------|
| `low` | 只读操作，无破坏性 | 展示代码 → 用户确认 → 执行 |
| `medium` | 可能有影响，但可回滚 | 展示代码 → dry-run → 用户确认 → 执行 |
| `high` | 破坏性操作，不可逆 | 展示代码 → dry-run → 审批 → 执行 |

**高风险脚本示例**：服务重启、数据库写操作、配置变更、删除操作。

### 步骤 3：预执行验证（Dry-Run）

对需要验证的脚本执行 dry-run：

```
POST {{base_url}}/script/verify
Content-Type: application/json

{
  "script_id": "<script_id>",
  "user_id": "{{current_user_id}}"
}
```

向用户展示 dry-run 结果：
- "通过预执行检查"：可以继续
- "需要审批"：走审批流程
- 任何警告信息

### 步骤 4：执行脚本

用户确认后执行：

```
POST {{base_url}}/script/execute
Content-Type: application/json

{
  "script_id": "<script_id>",
  "requested_by": "{{current_user_id}}",
  "lifecycle_type": "once",
  "incident_id": "<incident_id>",
  "diagnosis_id": "<diagnosis_id>",
  "feed_to_copilot": true
}
```

`lifecycle_type` 说明：
- `once`：一次性执行，不保存
- `temp`：临时保留 24 小时
- `permanent`：永久入库，成为知识资产

### 步骤 5：结果解读与回传

执行结果包含：
- `output`：脚本输出
- `conclusion`：AI 对结果的解读
- `next_suggestion`：下一步建议

如果 `feed_to_copilot: true`，结果自动回传给 Copilot 更新诊断上下文。

将结果展示给用户，并根据 `next_suggestion` 引导下一步：

```
✅ 脚本执行成功

📤 输出：db_pool_active=450, db_pool_max=500, slow_queries=27

🤖 AI 解读：连接池接近上限，慢查询数量偏高。根因更偏向数据库连接池耗尽。

💡 建议：建议开发确认连接池配置；运维继续采集慢查询样本。

📋 脚本状态：已回传 Copilot 继续分析
```

## 脚本生成（无现成脚本时）

如果 `GET /script/suggest` 没有合适的脚本，可以生成新脚本：

1. 根据诊断上下文确定需要的操作类型
2. 生成脚本代码（使用 [脚本模板](./assets/script-template.py)）
3. 执行前**必须** dry-run
4. 执行成功后建议设置为 `permanent` 入库

## 注意事项

- 生产环境执行前确认当前用户有执行权限（`role: operator`）
- 高风险脚本必须走审批流程，不能跳过
- 执行结果中的敏感信息（密码、密钥）应在展示前脱敏
