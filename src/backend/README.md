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
- `GET /ui/` 访问前端原型页面

缺失/待补充后端能力：
- 实时推送/WebSocket 协同更新接口
- 复杂 KG 搜索与图可视化数据接口
- Ontology CRUD 与版本演进管理接口
- 事件更新、备注与协同消息记录接口的持久化和审计增强

LLM 配置：

- `LLM_PROVIDER=openai` 或 `anthropic`
- `OPENAI_API_KEY`（如果使用 OpenAI）
- `OPENAI_MODEL` 可选，默认 `gpt-4o-mini`

注意：示例数据存放在 `src/kg/sample_kg.json`、`src/ontology/sample_ontology.jsonld`、`src/harness/sample_actions.json`。 
