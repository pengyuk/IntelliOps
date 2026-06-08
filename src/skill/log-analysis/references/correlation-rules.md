# 跨源日志关联规则

## 规则说明

跨源关联分析的目标是在不同来源的日志中检测同时出现的异常模式，从而推断因果链。规则按置信度排序。

## 关联规则

### 规则 1：应用 + 数据库（置信度 82%）

**触发条件**：
- 应用日志中出现 `connection pool exhausted` 或 `timeout waiting for DB connection`
- 同时数据库日志中出现 `too many connections` 或 `slow query`

**推断**：数据库连接池耗尽导致应用层请求排队超时，可能伴随慢查询阻塞连接。

**处置建议**：
1. 检查连接池配置是否匹配业务负载
2. 分析慢查询是否需要优化
3. 考虑临时增加连接池上限作为缓解措施

---

### 规则 2：应用 + 主机资源（置信度 75%）

**触发条件**：
- 应用日志中出现 `OOM`、`GC overhead`、`timeout`
- 同时主机日志中出现 `disk full`、`CPU throttled`、`swap usage`

**推断**：主机资源（CPU/内存/磁盘）耗尽直接导致应用进程异常。

**处置建议**：
1. 检查主机资源使用趋势
2. 评估是否需要扩容或调整资源限制
3. 检查是否有资源泄漏进程

---

### 规则 3：应用 + K8s（置信度 78%）

**触发条件**：
- 应用日志中出现 `connection refused`、`503 Service Unavailable`
- 同时 K8s Events 中出现 `OOMKilled`、`Liveness probe failed`、`BackOff`

**推断**：容器层面的资源限制或健康检查配置问题导致 Pod 反复重启。

**处置建议**：
1. 检查 Pod 的 memory/cpu limits 是否过小
2. 检查 liveness/readiness probe 配置是否合理
3. 查看 Pod 重启前后的资源使用峰值

---

### 规则 4：部署 + 应用异常（置信度 88%）

**触发条件**：
- 部署事件（`deployment rolled out`）时间戳
- 应用日志在部署后出现 `ClassNotFoundException`、`configuration key changed`、新类型错误

**推断**：最近的部署引入了不兼容的代码或配置变更。

**处置建议**：
1. 优先考虑回滚到上一个稳定版本
2. 对比新旧版本的配置差异
3. 检查是否有未同步的环境变量或依赖

---

### 规则 5：级联故障（置信度 70%）

**触发条件**：
- 服务 A 出现 `circuit breaker OPEN`
- 服务 B（A 的上游调用方）出现 `timeout calling service A`
- 服务 C（B 的上游调用方）出现 `503 Service Unavailable`

**推断**：故障从下游向上游级联传播，A 是起点。

**处置建议**：
1. 优先修复最下游的故障服务 A
2. 临时调整上游服务的超时和重试策略
3. 评估是否需要熔断降级策略

## 使用方式

分析多源日志时：
1. 先按来源分组（app/、db/、host/、k8s/）
2. 检查各组是否同时出现上述规则的触发条件
3. 按置信度排序输出关联发现
4. 关联发现附带处置建议
