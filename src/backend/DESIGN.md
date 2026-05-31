# 后端设计

## 目标

实现支撑前端与能力层的后端服务：数据采集、KG 服务、推荐/规则引擎、执行接口与权限管理。

## 服务拆分（建议微服务）

- Ingest Service：采集并标准化外部数据（T-CMDB/T-OPM/优云）
- KG Service：图 DB 抽象，提供实体/关系 CRUD 与查询
- Recommendation Service：基于 KG 的排查/根因推荐
- Harness API：执行模板/脚本的受控执行接口
- Auth & Audit：认证/授权/审计日志
- Frontend API：聚合各能力供 UI 使用

## 接口示例（REST）

- `POST /ingest/alerts` -> 收到告警并入库
- `GET /incident/{id}` -> 获取事件详情（含 KG 关联）
- `POST /action/execute` -> 调用 Harness 执行（需权限）
- `GET /kg/query` -> 自定义图查询

## 非功能需求

- 高可用：关键服务冗余部署
- 可扩展：消息中间件（Kafka）解耦流量峰值
- 安全：细粒度 RBAC 与审计链路

