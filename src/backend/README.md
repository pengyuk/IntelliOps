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
- `GET /kg/query?q=支付` 简单 KG 查询
- `POST /ingest/alerts` 模拟告警入库
- `POST /action/execute` 模拟执行动作

注意：示例数据存放在 `src/kg/sample_kg.json`、`src/ontology/sample_ontology.jsonld`、`src/harness/sample_actions.json`。 
