---
name: log-analysis
description: >
  智能日志分析与异常检测。触发词：日志、log、ERROR、WARN、堆栈、报错、异常、trace、slow query、连接超时、OOM、NullPointer。使用场景：收到日志片段需要分析时、需要关联多源日志时、需要从日志中提取关键事件时。
argument-hint: '<粘贴日志内容 或 指定日志来源>'
---

# 日志智能分析

## 何时使用

- 用户粘贴了一段或多段日志需要解读
- 故障排查中需要分析日志模式
- 需要关联应用日志、数据库日志、主机日志、K8s Events
- 诊断过程中需要日志证据支撑根因假设

## 核心流程

### 步骤 1：接收日志

从用户输入中提取日志内容。支持多种方式：
- 用户直接粘贴日志片段
- 用户指定服务名（自动从诊断上下文中获取模拟日志）
- 用户提供日志文件路径

如果用户没有提供日志，主动询问："请粘贴相关日志片段，或告诉我哪个服务的日志需要分析。"

### 步骤 2：分析日志

对日志执行以下分析：

**A. 异常级别统计**
- 统计 ERROR、WARN、INFO 各级别数量
- 如果 ERROR > 正常基线的 3 倍，标记为严重

**B. 错误模式匹配**
根据 [错误模式词典](./references/error-patterns.md) 识别已知模式：

| 模式 | 正则关键词 | 严重度 | 典型根因 |
|------|-----------|--------|---------|
| 超时/Timeout | `timeout\|timed out` | high | 下游响应慢、网络问题 |
| 连接池耗尽 | `connection pool exhausted\|too many connections` | high | 连接泄漏、配置不当 |
| 内存耗尽/OOM | `out of memory\|heap space\|OOMKilled` | critical | 内存泄漏、limit过低 |
| 慢查询 | `slow query\|took [0-9]+ms` | medium | 索引缺失、SQL低效 |
| 熔断 | `circuit breaker` | high | 下游不可用 |
| 空指针 | `NullPointerException` | high | 代码缺陷 |
| 类加载异常 | `ClassNotFoundException` | high | 部署问题、版本不兼容 |
| 资源限制 | `disk\|ulimit\|too many open files` | critical | 系统配置不足 |
| GC异常 | `GC pause\|GC overhead` | medium | 堆内存不足 |
| 容器限制 | `CPU throttl\|OOMKilled` | critical | 资源 limits 配置 |

**C. 跨源关联分析**
应用 [跨源关联规则](./references/correlation-rules.md) 检测关联模式：
- 应用层 + 数据库层：连接池/慢查询关联
- 应用层 + 主机层：资源耗尽关联
- 应用层 + K8s：容器限制/健康检查关联

### 步骤 3：输出分析结果

以结构化格式呈现：

```
📊 日志分析结果

📋 摘要：过去XX分钟检测到 N 条异常日志。关键事件：...

🔴 关键事件 (按严重度排序)：
  1. [CRITICAL] host/db-host-01: disk space 92% used
  2. [HIGH] app/payment: connection pool exhausted (450/500)
  ...

🔗 跨源关联：
  • 应用层 + 数据库层：连接超时与数据库错误同时出现（置信度 82%）

📈 错误分类：
  • 连接池异常: 3 条 (43%)
  • 慢查询: 2 条 (29%)
  • 其他: 2 条 (29%)

💡 建议：优先排查数据库连接池配置和慢查询阻塞。
```

### 步骤 4：注入诊断上下文

将分析结果注入当前诊断会话：

1. 如果存在活跃的诊断会话（`diagnosis_id`），通过 `POST /copilot/chat` 将分析结果发送给 Copilot
2. 消息格式：`"日志分析发现：[摘要]。关键事件：[列表]。建议优先排查 [方向]。"`
3. 等待 Copilot 更新根因假设

## 注意事项

- 日志可能包含敏感信息（IP、密码），分析前提醒用户脱敏
- 模拟日志（原型阶段）的准确性有限，生产环境需接入真实日志系统
- 如果日志量过大（>500行），先做聚合统计再逐条分析
