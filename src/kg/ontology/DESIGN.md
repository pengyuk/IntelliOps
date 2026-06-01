# 本体设计（Ontology）

## 目标

构建用于知识图谱的标准化语义层，明确实体、属性、关系与约束，便于跨模块共享。

## 推荐实体集

- `Incident`, `Alert`, `Service`, `Host`, `Change`, `WorkOrder`, `Action`, `Person`, `SOP`

## 属性与类型（示例）

- `Incident.status` (enum)
- `Alert.severity` (int)
- `Service.owner` (Person)
- `Change.affected_entities` (list)

## 关系模式

- `Incident` - `related_to` -> `Alert`
- `Service` - `depends_on` -> `Service/Host`
- `Change` - `affects` -> `Service/Host`
- `Action` - `used_in` -> `SOP` / `Incident`

## 格式化与版本管理

- 初期以 JSON-LD 或 TTL 表达，后期导出 OWL 供推理使用
- 使用语义版本号（v0.1, v0.2）并记录变更日志

## 校验与一致性

- 提供本体验证工具（JSON Schema）确保入图数据符合本体约定
- 定期跑一致性检查（例如循环依赖、孤立实体）

