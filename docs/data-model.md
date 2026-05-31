# 数据模型设计

## 目标

定义支撑故障排查的标准化实体、属性与关系，保障多源数据能在知识层中统一关联与查询。

## 核心实体（示例）

- `Service`：业务服务，属性：`service_id, name, owner, tags`
- `Host/Instance`：计算资源，属性：`host_id, ip, hostname, os, capacity`
- `Alert`：告警事件，属性：`alert_id, severity, metric, timestamp, source`
- `Incident`：故障事件，属性：`incident_id, status, start_time, impact`
- `Change`：变更记录，属性：`change_id, type, author, time, affected_entities`
- `WorkOrder`：工单，属性：`ticket_id, assignee, status, timeline`
- `Action`：操作/脚本，属性：`action_id, script, precheck, rollback`
- `Person`：角色与联系人，属性：`person_id, role, contact`

## 关系（示例）

- `Service` -[runs_on]-> `Host`
- `Alert` -[related_to]-> `Service` / `Host`
- `Incident` -[triggered_by]-> `Alert`
- `Incident` -[caused_by]-> `Change`
- `WorkOrder` -[resolves]-> `Incident`
- `Action` -[executed_by]-> `Person`

## 数据源映射

- T-CMDB -> `Service`, `Host`, 依赖关系
- T-OPM -> `Alert`, `Incident` 基本事件
- 优云导出 -> 监控指标、容量基线（用于告警上下文）
- 变更清单 -> `Change`
- 工单系统 -> `WorkOrder`

## 存储与访问策略

- 实体与关系在图数据库建模（快速关联查询）
- 时序指标与监控存入时序 DB，KG 保存聚合/异常摘要
- 变更与工单入关系库/Postgres用于事务与审计

## 示例 JSON-LD（Service）

{
  "@context": "http://schema.org/",
  "@type": "Service",
  "service_id": "svc-001",
  "name": "支付网关",
  "owner": "支付组",
  "runs_on": ["host-01", "host-02"]
}

