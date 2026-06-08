# 知识图谱设计（KG）

## 当前实现（2026-06-06）

> **实际采用轻量级内存图**，快速验证关联查询和影响面分析场景。

| 维度 | 设计目标 | 实际实现 |
|------|---------|---------|
| 图 DB | Neo4j / JanusGraph | `knowledge_graph.py` 内存邻接表 |
| ETL | Kafka + Airflow | `data_service.py` Excel/Word 直接加载 |
| 数据源 | T-CMDB/T-OPM/优云 | 本地 Excel（系统访问关系 + 应用管理报表） |
| 查询 | Cypher / Gremlin | BFS 子图遍历 + 关键词匹配 |

### 实现文件

| 文件 | 位置 | 功能 |
|------|------|------|
| `knowledge_graph.py` | `src/backend/` | 邻接表构建、BFS 子图、影响范围 `impact_scope()`、模糊匹配 `match_nodes()` |
| `data_service.py` | `src/backend/` | 从 Excel 加载系统关系、从 Word 加载复盘报告 |
| `sample_kg.json` | `src/kg/` | 示例静态图数据（原型早期使用，现已被真实数据替代） |

### 已实现的查询场景

- ✅ 根据 Incident 查找相关 Service / Change / Alert
- ✅ BFS 子图探索（`GET /kg/subgraph?node_id=X&depth=N`）
- ✅ 影响范围分析（`GET /alarm/{id}/impact`）
- ✅ 服务历史关联事故（`GET /kg/history`）
- ✅ 模糊匹配系统名（`match_nodes()` 用于告警→系统关联）
- 🟡 向量检索相似案例 → `vector_search.py`（独立模块）

## 未来演进方向

当数据量和查询复杂度增长时：

1. **子图入图**：将关键服务及最近 3-6 个月变更/告警导入 Neo4j
2. **多跳推理**：`Service → depends_on → Service → affected_by → Change` 路径查询
3. **图可视化**：前端 D3/ECharts 渲染依赖拓扑（B7 待完成）

