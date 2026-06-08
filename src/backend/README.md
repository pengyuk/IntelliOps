# Backend 快速运行说明

安装依赖：

```bash
pip install -r requirements.txt
```

运行服务（开发模式）：

```bash
uvicorn src.backend.app:app --reload --host 0.0.0.0 --port 8000
```

API 示例：

- `GET /` 根信息
- `GET /incident/inc-1` 获取示例事件
- `GET /incident/inc-1/reason` 获取根因推理结果（如果配置 LLM，则使用 LLM；否则使用本地回退规则）
- `GET /kg/query?q=支付` 简单 KG 查询
- `GET /kg/nodes?type=Service` 查询 KG 节点
- `GET /kg/edges?from_id=svc-001` 查询 KG 边
- `GET /kg/incident/inc-1` 获取事故相关 KG 子图
- `GET /kg/incident/inc-1/related` 获取相关历史事故
- `GET /kg/subgraph?node_id=svc-001&depth=1` 查询节点子图
- `GET /kg/history?service_id=svc-001` 查询服务历史关联事故
- `GET /ontology` 获取本体示例
- `GET /ontology/version` 获取本体版本
- `GET /ontology/schema` 获取本体验证规则
- `POST /ontology/validate` 校验本体结构
- `GET /actions` 列出可执行动作
- `POST /action/request` 创建动作审批请求
- `GET /action/requests` 列出审批请求
- `POST /action/approve` 批准或拒绝请求
- `POST /action/execute` 执行动作（支持 request_id / dry_run）
- `GET /action/logs` 查看执行审计日志
- `GET /auth/users` 列出用户角色
- `GET /auth/me?user_id=...` 查询当前用户信息
- `GET /incident/{id}/timeline` 查询事故时间线
- `POST /incident/{id}/timeline` 新增时间线事件
- `GET /incident/{id}/collaboration` 查询协作评论
- `POST /incident/{id}/collaboration` 添加协作评论
- `POST /copilot/diagnose` 启动 Copilot 根因诊断会话
- `POST /copilot/chat` 进行诊断多轮对话并同步讨论区
- `GET /script/suggest?incident_id=...` 获取脚本与处置建议
- `POST /script/verify` 预执行/风险校验脚本
- `POST /script/execute` 模拟执行脚本并写入审计日志
- `GET /script/{id}` 获取脚本详情与执行历史
- `GET /incident/{id}/discussion` 查询扩展讨论消息
- `POST /incident/{id}/discussion` 发送扩展讨论消息
- `POST /incident/{id}/postmortem` 自动生成复盘报告
- `GET /postmortem/{id}` 查询复盘报告
- `POST /postmortem/{id}/approve` 审批并发布复盘
- `GET /incident/{id}/related-cases` 查询相似历史案例
- `GET /incident/{id}/knowledge-assets` 查询关联知识资产
- `GET /data/summary` 查询已加载数据摘要
- `POST /data/reload` 重新加载 data 目录数据
- `GET /alarm/{alarm_id}` 查询告警记录及解析结果
- `GET /alarm/{alarm_id}/match` 告警系统与负责人匹配
- `GET /alarm/{alarm_id}/impact` 计算告警影响范围
- `GET /diagnosis/alarm/{alarm_id}` 执行告警自动诊断
- `GET /incident/{id}/investigation-state` 查看排查状态（四象限）
- `POST /incident/{id}/investigation-state` 更新排查状态
- `POST /incident/{id}/investigation-state/item` 添加排查项
- `POST /incident/{id}/investigation-state/move` 移动排查项
- `WS /ws/incident/{id}` WebSocket 实时推送
- `GET /ws/status` WebSocket 连接状态
- `GET /postmortem/{id}/knowledge` 获取蒸馏知识资产
- `GET /ui/` 访问前端原型页面

新增能力（Person B 完成）：
- ✅ WebSocket 实时推送：`WS /ws/incident/{id}` + 时间线自动广播
- ✅ SQLite 持久化：`db.py` 9 表，重启不丢数据
- ✅ 排查状态机：`GET/POST /incident/{id}/investigation-state`
- ✅ 向量检索：`vector_search.py`（sentence-transformers + FAISS）
- ✅ 告警诊断管线：`alarm_analyze.py` + `fault_diagnosis.py` + `knowledge_graph.py`
- ✅ 知识蒸馏：`GET /postmortem/{id}/knowledge`
- ✅ Docker 部署：`Dockerfile` + `docker-compose.yml`

缺失/待补充：
- Ontology CRUD 与版本演进管理
- 前端 React 重构 + 图可视化（B7）

LLM 配置：

- `LLM_PROVIDER=openai` 或 `anthropic`
- `OPENAI_API_KEY`（如果使用 OpenAI）
- `OPENAI_MODEL` 可选，默认 `gpt-4o-mini`

注意：示例数据存放在 `src/kg/sample_kg.json`、`src/ontology/sample_ontology.jsonld`、`src/harness/sample_actions.json`。 
