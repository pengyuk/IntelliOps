# 后端设计

## 当前实现（2026-06-06）

> **实际采用单体 FastAPI 架构**，18 个 `.py` 文件扁平组织，通过相对导入解耦。

### 模块清单

| 文件 | 层 | 功能 |
|------|-----|------|
| `app.py` | API | FastAPI 路由 + 全局初始化（~1250 行） |
| `models.py` | API | 17 个 Pydantic 请求/响应模型 |
| `llm_client.py` | 认知 | 多 provider 异步 LLM（OpenAI/Anthropic/Ollama） |
| `reasoner.py` | 认知 | 四阶段链式根因推理 |
| `log_analyzer.py` | 认知 | 日志智能分析（LLM+规则双模） |
| `copilot.py` | 认知 | 有状态多轮对话智能体 |
| `credibility.py` | 认知 | 可信度评分+证据链+风险评估 |
| `knowledge_distiller.py` | 认知 | 复盘→知识资产蒸馏 |
| `data_service.py` | 数据 | Excel/Word ETL 管道 |
| `knowledge_graph.py` | 数据 | 内存邻接表+BFS 图查询 |
| `alarm_analyze.py` | 数据 | 告警文本解析与系统匹配 |
| `fault_diagnosis.py` | 数据 | 告警根因自动诊断 |
| `db.py` | 基础设施 | SQLite 9 表持久化（aiosqlite, WAL） |
| `vector_search.py` | 基础设施 | sentence-transformers/FAISS 向量检索 |
| `state_machine.py` | 基础设施 | 四象限排查状态机 |
| `websocket_manager.py` | 基础设施 | 按 incident 分组 WebSocket 广播 |

外部模块引用：
| 模块 | 位置 |
|------|------|
| Ontology schema + validation | `src/ontology/validator.py` |
| Skill 文件 | `src/skill/*/SKILL.md` |
| 示例 KG 数据 | `src/kg/sample_kg.json` |

### 接口一览

见 `src/backend/README.md`（含全部 50+ 端点）。

## 与设计目标的差异

| 设计目标 | 当前实现 | 原因 |
|---------|---------|------|
| 微服务拆分 | 单体 FastAPI | 原型阶段，快速迭代 |
| Kafka 消息中间件 | 无 | 数据量小，文件加载足够 |
| 细粒度 RBAC | 角色字符串检查 | 原型阶段，够用 |

## 未来演进

- 按认知层/数据层/API 拆分子目录（当文件数 > 30 时考虑）
- 引入消息队列处理大规模告警流
- 完善 RBAC + API Token 鉴权

