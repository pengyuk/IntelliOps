# 脚本操作风险分级矩阵

## 风险等级定义

| 等级 | 标识 | 含义 | 审批要求 | 示例 |
|------|------|------|---------|------|
| `low` | 🟢 | 只读操作，无副作用 | 无需审批 | 查询日志、检查指标、查看配置 |
| `medium` | 🟡 | 有限影响，可回滚 | 建议审批 | 调整日志级别、清理临时文件 |
| `high` | 🔴 | 破坏性操作，不可逆 | 必须审批 | 重启服务、修改数据库、删除资源 |

## 操作分类

### 诊断类（Diagnosis）

| 操作 | 风险 | 说明 |
|------|------|------|
| 查看日志（tail/grep/journalctl） | low | 只读 |
| 查询数据库（SELECT/SHOW/DESCRIBE） | low | 只读，注意不要全表扫描大表 |
| 检查指标（curl metrics endpoint） | low | 只读 |
| 抓取线程堆栈（jstack/kill -3） | low | 可能短暂暂停线程 |
| 采集 heap dump | medium | 可能导致短暂停顿 |
| tcpdump 抓包 | medium | 可能影响网络性能 |

### 处置类（Mitigation）

| 操作 | 风险 | 说明 |
|------|------|------|
| 调整连接池大小（扩大） | medium | 有限影响，但需确认资源充足 |
| 清理临时文件/缓存 | medium | 确认文件可安全删除 |
| 重启应用服务 | high | 需要审批，可能中断服务 |
| 回滚部署版本 | high | 需要审批 |
| 修改数据库配置 | high | 需要审批 + DBA 确认 |
| 执行数据库写操作 | high | 需要审批 + 回滚脚本 |
| 重启数据库/中间件 | high | 需要审批，影响面大 |

### 验证类（Verification）

| 操作 | 风险 | 说明 |
|------|------|------|
| 健康检查（curl /health） | low | 只读 |
| 连接测试（telnet/nc） | low | 只读 |
| 配置校验（diff 对比） | low | 只读 |
| 灰度验证（小流量测试） | medium | 可能影响少量用户 |

## 审批流程

```
高风险脚本执行流程：
  用户发起 → AI 展示风险警告 → Dry-Run 预检 →
  → 创建审批请求（POST /action/request）
  → 审批人批准/拒绝（POST /action/approve）
  → 执行（POST /script/execute 带 request_id）
  → 结果回写审计日志
```

## 常见场景速查

| 用户意图 | 推荐操作 | 风险 | 注意事项 |
|---------|---------|------|---------|
| "查一下日志" | log grep | low | 指定时间范围 |
| "看连接数" | metrics query | low | 注意不要高频查询 |
| "临时放宽连接池" | config adjust | medium | 确认有回滚方案 |
| "重启试试" | service restart | high | 必须先走审批！ |
| "清一下缓存" | cache clear | medium | 确认缓存可安全清除 |
| "回滚上一个版本" | deploy rollback | high | 必须审批 + 通知相关方 |
