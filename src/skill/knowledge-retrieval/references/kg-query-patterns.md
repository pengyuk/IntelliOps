# KG 查询模式参考

## 常用查询模式

### 模式 1：按服务查依赖

**意图**：了解某个服务的上下游依赖

**API**：
```
GET /kg/subgraph?node_id={{service_id}}&depth=2
```

**解读**：
- `depth=1`：直接邻居（直接依赖和被依赖）
- `depth=2`：二级邻居（依赖的依赖）
- 结果中的边类型：
  - `depends_on`：该服务依赖对方
  - `runs_on`：该服务运行在对方（主机/容器）
  - `affects`：变更/告警影响该服务

### 模式 2：按关键词全局搜索

**意图**：快速查找与关键词相关的所有实体

**API**：
```
GET /kg/query?q=支付
```

**适用场景**：用户不确定具体实体 ID，用业务名称搜索。

### 模式 3：按类型筛选实体

**意图**：列出所有服务/主机/告警等

**API**：
```
GET /kg/nodes?type=Service
GET /kg/nodes?type=Alert
GET /kg/nodes?type=Change
```

**可用类型**：Service, Host, Alert, Change, Person, SOP, Action

### 模式 4：查事故关联图

**意图**：查看事故涉及的所有实体和关系

**API**：
```
GET /kg/incident/{{incident_id}}
```

**返回**：事故相关的节点（服务、告警、变更）+ 它们之间的边。

### 模式 5：查服务历史事故

**意图**：查看某个服务历史上关联的所有事故

**API**：
```
GET /kg/history?service_id={{service_id}}
```

也可按告警或变更查询：
```
GET /kg/history?alert_id={{alert_id}}
GET /kg/history?change_id={{change_id}}
```

### 模式 6：查边关系

**意图**：查询特定节点间的关系

**API**：
```
GET /kg/edges?from_id={{node_id}}
GET /kg/edges?to_id={{node_id}}
GET /kg/edges?rel=depends_on
```

## 组合查询策略

复杂排查场景通常需要组合多个查询：

**场景：故障影响面评估**
```
1. GET /kg/incident/{{incident_id}}       → 获取事故涉及的节点
2. 对每个受影响服务：
   GET /kg/subgraph?node_id={{svc}}&depth=2 → 查看依赖链
3. GET /kg/history?service_id={{svc}}    → 查看历史事故
```

**场景：根因假设验证**
```
1. GET /incident/{{id}}/related-cases    → 找相似案例
2. 对高相似案例中的根因服务：
   GET /kg/subgraph?node_id={{svc}}&depth=1 → 查看当前状态
3. GET /kg/edges?to_id={{svc}}           → 查看最近变更
```

## 查询结果解读原则

1. **边越多越需要关注**：被多个服务依赖的节点是瓶颈点
2. **变更靠近故障时间**：时间窗口重叠的变更优先排查
3. **循环依赖**：A→B→A 的环形依赖是高风险设计
4. **孤立节点**：没有上下游连接的节点可能数据不完整
