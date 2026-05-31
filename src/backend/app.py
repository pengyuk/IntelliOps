from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict
import json
import uuid
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.abspath(os.path.join(HERE, '..'))

app = FastAPI(title="IntelliOps Prototype API")

# Load sample KG and ontology
with open(os.path.join(DATA_ROOT, 'kg', 'sample_kg.json'), 'r', encoding='utf-8') as f:
    SAMPLE_KG = json.load(f)
with open(os.path.join(DATA_ROOT, 'ontology', 'sample_ontology.jsonld'), 'r', encoding='utf-8') as f:
    SAMPLE_ONTO = json.load(f)
with open(os.path.join(DATA_ROOT, 'harness', 'sample_actions.json'), 'r', encoding='utf-8') as f:
    SAMPLE_ACTIONS = json.load(f)

# In-memory incidents store
INCIDENTS: Dict[str, Dict[str, Any]] = {
    "inc-1": {
        "incident_id": "inc-1",
        "status": "Resolved",
        "summary": "支付网关延迟异常",
        "related_alerts": ["al-1"],
        "related_changes": ["chg-100"],
        "affected_services": ["svc-001"]
    }
}

class AlertIn(BaseModel):
    alert_id: str
    severity: int
    metric: str
    timestamp: str
    source: str
    payload: dict = {}

class ActionExecIn(BaseModel):
    action_id: str
    params: dict = {}

@app.post('/ingest/alerts')
async def ingest_alert(alert: AlertIn):
    # Simple ingest: create a new incident if severity high
    if alert.severity >= 3:
        inc_id = f"inc-{str(uuid.uuid4())[:8]}"
        INCIDENTS[inc_id] = {
            "incident_id": inc_id,
            "status": "Investigating",
            "summary": f"自动创建：{alert.metric} 异常",
            "related_alerts": [alert.alert_id],
            "related_changes": [],
            "affected_services": []
        }
        return {"created_incident": inc_id}
    return {"status": "ingested"}

@app.get('/incident/{incident_id}')
async def get_incident(incident_id: str):
    inc = INCIDENTS.get(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')
    # enrich with KG-derived context (simple lookup)
    services = []
    for svc in inc.get('affected_services', []):
        svc_node = next((n for n in SAMPLE_KG['nodes'] if n['id'] == svc), None)
        if svc_node:
            services.append(svc_node)
    inc['kg_services'] = services
    return inc

@app.get('/kg/query')
async def kg_query(q: str = ""):
    # naive implementation: return all nodes matching q in name
    hits = [n for n in SAMPLE_KG['nodes'] if q.lower() in n.get('name','').lower()]
    return {"query": q, "hits": hits}

@app.get('/ontology')
async def get_ontology():
    return SAMPLE_ONTO

@app.post('/action/execute')
async def execute_action(req: ActionExecIn):
    action = next((a for a in SAMPLE_ACTIONS if a['action_id'] == req.action_id), None)
    if not action:
        raise HTTPException(status_code=404, detail='action not found')
    # Simulate execution
    exec_id = f"exec-{str(uuid.uuid4())[:8]}"
    result = {
        "exec_id": exec_id,
        "action_id": action['action_id'],
        "status": "success",
        "output": f"模拟执行: {action.get('description')}",
        "params": req.params
    }
    return result

@app.get('/')
async def root():
    return {"service": "IntelliOps Prototype API", "routes": ["/incident/{id}", "/kg/query", "/ontology", "/action/execute"]}

# Mount static UI under /ui (serves src/ui/index.html)
UI_DIR = os.path.join(DATA_ROOT, 'ui')
if os.path.isdir(UI_DIR):
    app.mount('/ui', StaticFiles(directory=UI_DIR, html=True), name='ui')
