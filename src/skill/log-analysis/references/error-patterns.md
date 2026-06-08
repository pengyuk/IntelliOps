# 运维日志错误模式词典

## 使用说明

此文件包含运维领域常见日志错误模式及其正则表达式。分析日志时，依次匹配以下模式，优先处理严重度 `critical` 和 `high` 的匹配项。

## 模式列表

### CRITICAL（需要立即关注）

| 模式ID | 正则表达式 | 含义 | 典型根因 |
|--------|-----------|------|---------|
| OOM-01 | `(?i)out\s*of\s*memory\|OOM\|heap\s*space` | 内存耗尽 | 内存泄漏、JVM配置不当 |
| OOM-02 | `(?i)OOMKilled` | 容器因OOM被杀 | 容器内存limit过低 |
| DISK-01 | `(?i)disk\s*(full\|space\|usage\|critical)` | 磁盘空间不足 | 日志未轮转、数据堆积 |
| ULIMIT-01 | `(?i)too\s*many\s*open\s*files\|ulimit` | 文件描述符耗尽 | 连接泄漏、配置不足 |
| CPU-01 | `(?i)cpu\s*throttl` | CPU被限流 | 容器CPU limit不足 |

### HIGH（需要尽快处理）

| 模式ID | 正则表达式 | 含义 | 典型根因 |
|--------|-----------|------|---------|
| CONN-01 | `(?i)connection\s*(pool\s*exhausted\|refused\|reset\|timeout)` | 连接池问题 | 连接泄漏、配置过小 |
| CONN-02 | `(?i)too\s*many\s*connections` | 数据库连接超限 | 连接泄漏 |
| NPE-01 | `(?i)NullPointerException\|null\s*pointer` | 空指针异常 | 代码缺陷 |
| CNF-01 | `(?i)ClassNotFoundException\|NoClassDefFoundError` | 类加载失败 | 部署/版本问题 |
| CB-01 | `(?i)circuit\s*breaker\s*(open\|tripped)` | 熔断器打开 | 下游服务不可用 |
| TIMEOUT-01 | `(?i)timeout\s*(waiting\|after\|exceeded)` | 超时 | 下游响应慢、网络问题 |

### MEDIUM（需要关注）

| 模式ID | 正则表达式 | 含义 | 典型根因 |
|--------|-----------|------|---------|
| SLOW-01 | `(?i)slow\s*query.*took\s*\d+ms` | 数据库慢查询 | 索引缺失、SQL低效 |
| GC-01 | `(?i)GC\s*(pause\s*exceeded\|overhead\s*limit)` | GC异常 | 堆内存不足 |
| RETRY-01 | `(?i)retry\s*(exhausted\|failed\|limit)` | 重试耗尽 | 下游不稳定 |
| CACHE-01 | `(?i)cache\s*(miss\|hit\s*ratio\s*drop)` | 缓存命中率下降 | 缓存失效/过期 |
| HEALTH-01 | `(?i)health\s*check\s*fail.*status\s*=\s*DOWN` | 健康检查失败 | 服务不可用 |

### LOW（参考信息）

| 模式ID | 正则表达式 | 含义 |
|--------|-----------|------|
| DEPLOY-01 | `(?i)deploy.*roll(out\|back).*version` | 部署/回滚事件 |
| CONFIG-01 | `(?i)configuration\s*key.*changed` | 配置变更记录 |
| RESTART-01 | `(?i)(service\|pod\|container)\s*(restart\|restarting)` | 服务重启事件 |

## 新增模式指南

添加新模式时：
1. 指定唯一模式ID（CATEGORY-NN）
2. 编写可覆盖多种变体的正则表达式
3. 标注严重度和典型根因
4. 在 `log-analysis/SKILL.md` 的模式表中同步添加
