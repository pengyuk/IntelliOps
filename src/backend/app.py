from collections import deque
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Set
import json
import uuid
import os
import datetime

from .reasoner import IncidentReasoner

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.abspath(os.path.join(HERE, '..'))

app = FastAPI(title="IntelliOps Prototype API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:3000", "http://127.0.0.1:8080", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load sample KG and ontology
with open(os.path.join(DATA_ROOT, 'kg', 'sample_kg.json'), 'r', encoding='utf-8') as f:
    SAMPLE_KG = json.load(f)
with open(os.path.join(DATA_ROOT, 'ontology', 'sample_ontology.jsonld'), 'r', encoding='utf-8') as f:
    SAMPLE_ONTO = json.load(f)
with open(os.path.join(DATA_ROOT, 'harness', 'sample_actions.json'), 'r', encoding='utf-8') as f:
    SAMPLE_ACTIONS = json.load(f)

ACTION_LOGS: List[Dict[str, Any]] = []
ACTION_REQUESTS: List[Dict[str, Any]] = []
DIAGNOSES: Dict[str, Dict[str, Any]] = {}
COPILOT_MESSAGES: List[Dict[str, Any]] = []
SCRIPTS: Dict[str, Dict[str, Any]] = {}
POSTMORTEMS: Dict[str, Dict[str, Any]] = {}

ONTOLOGY_VERSION = 'v0.1'
ONTOLOGY_SCHEMA = {
    'version': ONTOLOGY_VERSION,
    'required': ['@context', '@graph'],
    'classes': ['Incident', 'Alert', 'Service', 'Host', 'Change', 'WorkOrder', 'Action', 'Person', 'SOP'],
    'relations': ['related_to', 'runs_on', 'affects', 'depends_on', 'used_in', 'documented_in'],
    'properties': {
        'Incident': ['incident_id', 'summary', 'status', 'related_alerts', 'related_changes', 'affected_services'],
        'Alert': ['alert_id', 'severity', 'metric', 'timestamp', 'source'],
        'Service': ['service_id', 'name', 'owner'],
        'Change': ['change_id', 'name', 'author', 'timestamp']
    }
}

USERS: Dict[str, Dict[str, Any]] = {
    'ui-user': {'user_id': 'ui-user', 'name': '运维人员', 'role': 'operator'},
    'dev-user': {'user_id': 'dev-user', 'name': '开发人员', 'role': 'developer'},
    'ops-manager': {'user_id': 'ops-manager', 'name': '审批经理', 'role': 'approver'},
    'admin': {'user_id': 'admin', 'name': '系统管理员', 'role': 'admin'},
}

PERMISSIONS: Dict[str, List[str]] = {
    'create_request': ['operator'],
    'approve_request': ['approver', 'admin'],
    'execute_action': ['operator'],
    'add_comment': ['operator', 'developer', 'approver', 'admin'],
    'add_timeline': ['operator'],
}

COLLAB_MESSAGES: List[Dict[str, Any]] = [
    {
        'comment_id': 'cmt-1',
        'incident_id': 'inc-1',
        'author': 'ops-manager',
        'role': 'approver',
        'message': '请先确认后台 payment-service 的负载情况。',
        'created_at': '2026-06-01T10:10:00Z'
    }
]

TIMELINE_EVENTS: List[Dict[str, Any]] = [
    {
        'event_id': 'evt-1',
        'incident_id': 'inc-1',
        'event_type': 'alert',
        'summary': '支付网关延迟告警触发',
        'actor': 'system',
        'role': 'system',
        'timestamp': '2026-06-01T10:00:00Z',
        'details': '检测到支付网关请求延迟超过阈值。'
    },
    {
        'event_id': 'evt-2',
        'incident_id': 'inc-2',
        'event_type': 'alert',
        'summary': '订单服务失败率升高',
        'actor': 'system',
        'role': 'system',
        'timestamp': '2026-06-01T11:30:00Z',
        'details': '监控发现订单 API 5 分钟失败率持续上升。'
    }
]


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def _get_user(user_id: str) -> Dict[str, Any]:
    user = USERS.get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail='未知用户或未授权')
    return user


def _check_permission(user_id: str, permission: str):
    user = _get_user(user_id)
    allowed = PERMISSIONS.get(permission, [])
    if user['role'] not in allowed:
        raise HTTPException(status_code=403, detail=f'用户 {user_id} 没有执行 {permission} 的权限')


def _add_timeline_event(incident_id: str, event_type: str, summary: str, actor: str, role: str, details: str = '') -> Dict[str, Any]:
    event = {
        'event_id': f'evt-{str(uuid.uuid4())[:8]}',
        'incident_id': incident_id,
        'event_type': event_type,
        'summary': summary,
        'actor': actor,
        'role': role,
        'timestamp': _now_iso(),
        'sequence': len(TIMELINE_EVENTS) + 1,
        'details': details,
    }
    TIMELINE_EVENTS.append(event)
    return event


def _incident_timeline(incident_id: str) -> List[Dict[str, Any]]:
    return sorted(
        [event for event in TIMELINE_EVENTS if event['incident_id'] == incident_id],
        key=lambda x: (x['timestamp'], x.get('sequence', 0)),
        reverse=True
    )


def _incident_comments(incident_id: str) -> List[Dict[str, Any]]:
    return sorted(
        [msg for msg in COLLAB_MESSAGES if msg['incident_id'] == incident_id],
        key=lambda x: x['created_at'],
        reverse=True
    )


def _record_collaboration_comment(incident_id: str, author: str, message: str, record_timeline: bool = False) -> Dict[str, Any]:
    user = _get_user(author)
    comment = {
        'comment_id': f'cmt-{str(uuid.uuid4())[:8]}',
        'incident_id': incident_id,
        'author': author,
        'role': user['role'],
        'message': message,
        'message_type': 'discussion',
        'created_at': _now_iso()
    }
    COLLAB_MESSAGES.append(comment)
    if record_timeline:
        _add_timeline_event(incident_id, 'decision', f'记录关键协同结论：{message[:50]}', author, user['role'], message)
    return comment


def _record_action_request(incident_id: str, request_id: str, action_id: str, author: str) -> None:
    user = _get_user(author)
    _add_timeline_event(incident_id, 'action_request', f'创建动作审批请求 {request_id}', author, user['role'], f'动作 {action_id} 申请执行')


def _record_action_approval(incident_id: str, request_id: str, approver: str, approved: bool) -> None:
    user = _get_user(approver)
    status = '批准' if approved else '拒绝'
    _add_timeline_event(
        incident_id,
        'action_approval',
        f'审批请求 {request_id} 已{status}',
        approver,
        user['role'],
        f'请求 {request_id} 已{status}。'
    )


def _fetch_kg_nodes(ids: List[str]) -> List[Dict[str, Any]]:
    return [node for node in SAMPLE_KG['nodes'] if node.get('id') in ids]


# In-memory incidents store
INCIDENTS: Dict[str, Dict[str, Any]] = {
    "inc-1": {
        "incident_id": "inc-1",
        "status": "Resolved",
        "summary": "支付网关延迟异常",
        "related_alerts": ["al-1"],
        "related_changes": ["chg-100"],
        "affected_services": ["svc-001"]
    },
    "inc-2": {
        "incident_id": "inc-2",
        "status": "Investigating",
        "summary": "订单服务失败率上升",
        "related_alerts": ["al-2"],
        "related_changes": ["chg-101"],
        "affected_services": ["svc-002"]
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
    requested_by: str = "ui-user"
    dry_run: bool = False
    request_id: Optional[str] = None
    incident_id: Optional[str] = None

class ActionRequestIn(BaseModel):
    action_id: str
    incident_id: str
    reason: str = ""
    requested_by: str = "ui-user"

class ActionApprovalIn(BaseModel):
    request_id: str
    approved: bool
    approver: str = "admin"
    comment: str = ""

class ReasoningResult(BaseModel):
    incident_id: str
    kg_context: Dict[str, List[Dict[str, Any]]]
    candidate_root_causes: List[Dict[str, Any]]
    reasoning_steps: List[str]
    evidence: List[str]
    confidence_summary: float

class OntologyValidationResult(BaseModel):
    valid: bool
    errors: List[str] = []

class TimelineEventIn(BaseModel):
    event_type: str
    summary: str
    details: str = ''
    actor: Optional[str] = None

class CopilotDiagnoseIn(BaseModel):
    incident_id: str
    user_id: str = 'ui-user'

class CopilotChatIn(BaseModel):
    incident_id: str
    diagnosis_id: Optional[str] = None
    user_id: str = 'ui-user'
    message: str

class ScriptVerifyIn(BaseModel):
    script_id: Optional[str] = None
    script_code: Optional[str] = None
    user_id: str = 'ui-user'

class ScriptExecuteIn(BaseModel):
    script_id: str
    requested_by: str = 'ui-user'
    request_id: Optional[str] = None
    lifecycle_type: str = 'once'
    incident_id: Optional[str] = None
    diagnosis_id: Optional[str] = None
    feed_to_copilot: bool = True

class DiscussionIn(BaseModel):
    author: str = 'ui-user'
    message: str
    message_type: str = 'maintenance'
    mentions: List[str] = []

class PostmortemIn(BaseModel):
    incident_id: Optional[str] = None
    mark_resolved: bool = True
    requested_by: str = 'ui-user'

class PostmortemApprovalIn(BaseModel):
    approver: str = 'ops-manager'
    publish_scripts: List[str] = []
    create_improvement_tasks: bool = True


def _fetch_kg_edges(node_ids: List[str] = None) -> List[Dict[str, Any]]:
    if node_ids:
        return [
            edge for edge in SAMPLE_KG['edges']
            if edge.get('from') in node_ids or edge.get('to') in node_ids
        ]
    return SAMPLE_KG['edges']


def _query_kg(q: str = "", node_type: str = "") -> Dict[str, Any]:
    nodes = SAMPLE_KG['nodes']
    if q:
        nodes = [n for n in nodes if q.lower() in n.get('name', '').lower()]
    if node_type:
        nodes = [n for n in nodes if n.get('type') == node_type]
    return {"query": q, "type": node_type, "nodes": nodes}


def _incident_graph(incident_id: str) -> Dict[str, Any]:
    inc = INCIDENTS.get(incident_id)
    if not inc:
        raise KeyError('incident not found')
    node_ids = set(inc.get('affected_services', []) + inc.get('related_alerts', []) + inc.get('related_changes', []))
    return {
        'incident_id': incident_id,
        'nodes': _fetch_kg_nodes(list(node_ids)),
        'edges': _fetch_kg_edges(list(node_ids)),
    }


def _subgraph(node_id: str, depth: int = 1) -> Dict[str, Any]:
    found = {node_id}
    queue = deque([(node_id, 0)])
    nodes = {}
    edges = []

    while queue:
        current, level = queue.popleft()
        node = next((n for n in SAMPLE_KG['nodes'] if n['id'] == current), None)
        if node:
            nodes[current] = node

        if level >= depth:
            continue

        for edge in SAMPLE_KG['edges']:
            if edge.get('from') == current:
                edges.append(edge)
                neighbor = edge.get('to')
                if neighbor not in found:
                    found.add(neighbor)
                    queue.append((neighbor, level + 1))
            if edge.get('to') == current:
                edges.append(edge)
                neighbor = edge.get('from')
                if neighbor not in found:
                    found.add(neighbor)
                    queue.append((neighbor, level + 1))

    return {
        'center': node_id,
        'depth': depth,
        'nodes': [n for n in SAMPLE_KG['nodes'] if n['id'] in list(found)],
        'edges': edges,
    }


def _history_incidents(service_id: str = '', alert_id: str = '', change_id: str = '') -> List[Dict[str, Any]]:
    results = []
    for inc in INCIDENTS.values():
        if service_id and service_id in inc.get('affected_services', []):
            results.append(inc)
            continue
        if alert_id and alert_id in inc.get('related_alerts', []):
            results.append(inc)
            continue
        if change_id and change_id in inc.get('related_changes', []):
            results.append(inc)
            continue
    return results


def _related_incidents(incident_id: str) -> List[Dict[str, Any]]:
    inc = INCIDENTS.get(incident_id)
    if not inc:
        raise KeyError('incident not found')

    related_ids = set()
    for other_id, other in INCIDENTS.items():
        if other_id == incident_id:
            continue
        if set(other.get('affected_services', [])) & set(inc.get('affected_services', [])):
            related_ids.add(other_id)
        if set(other.get('related_alerts', [])) & set(inc.get('related_alerts', [])):
            related_ids.add(other_id)
        if set(other.get('related_changes', [])) & set(inc.get('related_changes', [])):
            related_ids.add(other_id)

    return [INCIDENTS[i] for i in related_ids]


def _validate_ontology_payload(payload: Any) -> (bool, List[str]):
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, ['Ontology payload must be a JSON object']
    if '@context' not in payload or not isinstance(payload['@context'], dict):
        errors.append('Missing or invalid @context')
    if '@graph' not in payload or not isinstance(payload['@graph'], list):
        errors.append('Missing or invalid @graph')
    if isinstance(payload.get('@graph'), list):
        for index, item in enumerate(payload['@graph']):
            if not isinstance(item, dict):
                errors.append(f'@graph[{index}] must be an object')
                continue
            if '@id' not in item or not isinstance(item['@id'], str):
                errors.append(f'@graph[{index}] missing @id or invalid type')
            if '@type' not in item or not isinstance(item['@type'], str):
                errors.append(f'@graph[{index}] missing @type or invalid type')
            name = item.get('name')
            if name is None or not isinstance(name, str):
                errors.append(f'@graph[{index}] missing name or invalid name')
    return len(errors) == 0, errors

def _find_node(node_id: str) -> Optional[Dict[str, Any]]:
    return next((node for node in SAMPLE_KG['nodes'] if node.get('id') == node_id), None)

def _node_names(ids: List[str]) -> List[str]:
    return [node.get('name', node_id) for node_id in ids for node in [_find_node(node_id)] if node]

def _confidence_level(confidence: float) -> str:
    if confidence >= 0.75:
        return 'high'
    if confidence >= 0.55:
        return 'medium'
    return 'low'

def _related_cases_for_incident(incident_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    incident = INCIDENTS.get(incident_id)
    if not incident:
        raise KeyError('incident not found')

    cases = []
    current_services = set(incident.get('affected_services', []))
    current_changes = set(incident.get('related_changes', []))
    current_alerts = set(incident.get('related_alerts', []))
    for other_id, other in INCIDENTS.items():
        if other_id == incident_id:
            continue
        score = 0
        score += 3 * len(current_services & set(other.get('affected_services', [])))
        score += 2 * len(current_changes & set(other.get('related_changes', [])))
        score += len(current_alerts & set(other.get('related_alerts', [])))
        if not score:
            continue
        cases.append({
            'incident_id': other_id,
            'summary': other.get('summary'),
            'status': other.get('status'),
            'similarity_score': score,
            'root_cause': other.get('root_cause', '历史案例未记录最终根因'),
            'resolution_steps': other.get('resolution_steps', ['查看关联告警', '核对最近变更', '复用已验证脚本']),
            'scripts_used': other.get('scripts_used', []),
        })
    return sorted(cases, key=lambda item: item['similarity_score'], reverse=True)[:limit]

def _build_recommendations(incident: Dict[str, Any], reasoning: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions = {action['action_id']: action for action in SAMPLE_ACTIONS}
    service_names = _node_names(incident.get('affected_services', []))
    recommendations = [
        {
            'step': '补齐最近 30 分钟关键日志与错误摘要',
            'tools': ['act-001'] if 'act-001' in actions else [],
            'rationale': '日志摘要能快速验证当前根因假设，并为下一轮 Copilot 对话提供证据。',
            'confidence': 0.82,
        },
        {
            'step': '核对受影响服务的最近变更',
            'tools': [],
            'rationale': f'当前受影响服务为 {", ".join(service_names) or "未知服务"}，变更窗口与告警时间需要优先对齐。',
            'confidence': 0.74,
        },
    ]
    if any(cause.get('confidence', 0) > 0.7 for cause in reasoning.get('candidate_root_causes', [])):
        recommendations.append({
            'step': '对高置信候选根因执行低风险验证动作',
            'tools': ['act-001'] if 'act-001' in actions else [],
            'rationale': '先用只读动作验证，再决定是否进入审批执行。',
            'confidence': 0.78,
        })
    return recommendations

def _upsert_script(script: Dict[str, Any]) -> Dict[str, Any]:
    SCRIPTS[script['script_id']] = script
    return script

def _script_suggestions(incident_id: str, diagnosis_id: Optional[str] = None) -> List[Dict[str, Any]]:
    incident = INCIDENTS.get(incident_id)
    if not incident:
        raise KeyError('incident not found')
    service = incident.get('affected_services', ['svc-001'])[0] if incident.get('affected_services') else 'svc-001'
    suggestions = [
        {
            'script_id': f'script-log-{incident_id}',
            'name': '采集服务关键错误日志',
            'language': 'bash',
            'code': f'journalctl -u {service} --since "30 minutes ago" | grep -E "ERROR|WARN|timeout|slow"',
            'confidence': 0.84,
            'category': 'approved',
            'risk_level': 'low',
            'explanation': '只读采集日志，用于验证延迟、超时或异常堆栈。',
            'approval_required': False,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
        },
        {
            'script_id': f'script-metrics-{incident_id}',
            'name': '检查连接池与慢查询指标',
            'language': 'python',
            'code': 'print("db_pool_active=450 db_pool_max=500 slow_queries=27 p99_latency_ms=1850")',
            'confidence': 0.76,
            'category': 'copilot_generated',
            'risk_level': 'medium',
            'explanation': '模拟指标检查脚本，适合作为预执行验证样例。',
            'approval_required': False,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
        },
        {
            'script_id': f'script-restart-{incident_id}',
            'name': '重启受影响服务',
            'language': 'bash',
            'code': f'systemctl restart {service}',
            'confidence': 0.48,
            'category': 'high_risk',
            'risk_level': 'high',
            'explanation': '高风险恢复动作，需要审批后执行。',
            'approval_required': True,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
        },
    ]
    return [_upsert_script(script) for script in suggestions]

def _simulate_script_output(script: Dict[str, Any], incident: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    script_id = script.get('script_id', '')
    service_names = _node_names((incident or {}).get('affected_services', []))
    service_text = ', '.join(service_names) or '受影响服务'
    if 'metrics' in script_id:
        output = 'db_pool_active=450 db_pool_max=500 slow_queries=27 p99_latency_ms=1850'
        conclusion = f'{service_text} 的连接池接近上限，慢查询数量偏高，根因更偏向数据库连接池耗尽或慢查询堆积。'
        next_suggestion = '建议开发人员确认连接池配置和最近发布；运维继续采集慢查询样本，暂不直接重启。'
    elif 'log' in script_id:
        output = 'ERROR timeout waiting for DB connection; WARN slow query detected; WARN retry payment callback'
        conclusion = f'{service_text} 日志出现数据库连接等待超时与慢查询告警，支持“服务延迟由下游资源或连接池压力触发”的假设。'
        next_suggestion = '建议继续检查 DB_CONN_ACTIVE、慢查询 SQL 与最近变更窗口。'
    elif 'restart' in script_id:
        output = f'systemctl restart requested for {service_text}; simulated restart completed'
        conclusion = f'{service_text} 已完成模拟重启动作，但该动作属于恢复手段，不应替代根因确认。'
        next_suggestion = '建议观察错误率和延迟是否回落，并补充最终根因说明。'
    else:
        output = f"模拟执行脚本：{script.get('name')}"
        conclusion = '脚本执行完成，需要结合监控指标判断是否改善。'
        next_suggestion = '建议把执行结果补充到诊断上下文后继续分析。'
    return {
        'output': output,
        'conclusion': conclusion,
        'next_suggestion': next_suggestion,
    }

def _append_copilot_execution_feedback(incident_id: str, diagnosis_id: Optional[str], execution: Dict[str, Any]) -> Dict[str, Any]:
    response = (
        f"已收到执行结果：{execution.get('output')}。"
        f"结论：{execution.get('conclusion')} "
        f"下一步：{execution.get('next_suggestion')}"
    )
    message = {
        'comment_id': f'cmt-{str(uuid.uuid4())[:8]}',
        'incident_id': incident_id,
        'author': 'copilot',
        'role': 'copilot',
        'message': response,
        'message_type': 'execution_analysis',
        'execution_id': execution.get('execution_id'),
        'diagnosis_id': diagnosis_id,
        'created_at': _now_iso()
    }
    COLLAB_MESSAGES.append(message)
    COPILOT_MESSAGES.append({
        'message_id': f'cp-{str(uuid.uuid4())[:8]}',
        'incident_id': incident_id,
        'diagnosis_id': diagnosis_id,
        'response': response,
        'execution_result': execution,
        'created_at': _now_iso(),
        'user_id': 'copilot',
    })
    return message

def _generate_postmortem(incident_id: str, requested_by: str = 'ui-user', mark_resolved: bool = True) -> Dict[str, Any]:
    incident = INCIDENTS.get(incident_id)
    if not incident:
        raise KeyError('incident not found')
    if mark_resolved:
        incident['status'] = 'Resolved'
        _add_timeline_event(incident_id, 'status', '事故已标记恢复，进入复盘', requested_by, _get_user(requested_by)['role'])

    diagnosis = next((d for d in DIAGNOSES.values() if d.get('incident_id') == incident_id), None)
    if not diagnosis:
        reasoning = IncidentReasoner.infer_root_causes(incident, {
            'services': _fetch_kg_nodes(incident.get('affected_services', [])),
            'alerts': _fetch_kg_nodes(incident.get('related_alerts', [])),
            'changes': _fetch_kg_nodes(incident.get('related_changes', [])),
        })
    else:
        reasoning = diagnosis

    top_cause = (reasoning.get('candidate_root_causes') or [{}])[0]
    postmortem_id = f'pm-{str(uuid.uuid4())[:8]}'
    used_logs = [log for log in ACTION_LOGS if log.get('request_id') or log.get('action_id')]
    report = {
        'postmortem_id': postmortem_id,
        'incident_id': incident_id,
        'status': 'draft',
        'created_at': _now_iso(),
        'created_by': requested_by,
        'timeline': _incident_timeline(incident_id),
        'root_cause_conclusion': {
            'cause': top_cause.get('cause', '待确认根因'),
            'confidence': top_cause.get('confidence', reasoning.get('confidence_summary', 0.5)),
            'evidence': reasoning.get('evidence', []),
        },
        'decisions': [
            {
                'decision': '优先执行低风险只读验证，再进入审批动作',
                'rationale': '降低误操作风险，同时保证证据链可审计。',
                'timestamp': _now_iso(),
                'actor': requested_by,
            }
        ],
        'tools_used': [log.get('action_id') for log in used_logs],
        'scripts_used': [script for script in SCRIPTS.values() if script.get('diagnosis_id') == reasoning.get('diagnosis_id')],
        'improvement_suggestions': [
            '将本次高置信根因与验证脚本沉淀为知识资产。',
            '为受影响服务补充连接池、慢查询和变更窗口的联合告警。',
            '把高风险动作纳入审批模板，保留审计链路。',
        ],
    }
    POSTMORTEMS[postmortem_id] = report
    return report

@app.post('/ingest/alerts')
async def ingest_alert(alert: AlertIn):
    # Simple ingest: create a new incident if severity high
    if alert.severity >= 3:
        inc_id = f"inc-{str(uuid.uuid4())[:8]}"
        incident_services = []
        if isinstance(alert.payload, dict):
            service_id = alert.payload.get('service_id')
            if service_id:
                incident_services.append(service_id)

        INCIDENTS[inc_id] = {
            "incident_id": inc_id,
            "status": "Investigating",
            "summary": f"自动创建：{alert.metric} 异常",
            "related_alerts": [alert.alert_id],
            "related_changes": [],
            "affected_services": incident_services
        }
        return {"created_incident": inc_id}
    return {"status": "ingested"}

@app.get('/incident/{incident_id}')
async def get_incident(incident_id: str):
    inc = INCIDENTS.get(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')

    kg_context = {
        'services': _fetch_kg_nodes(inc.get('affected_services', [])),
        'alerts': _fetch_kg_nodes(inc.get('related_alerts', [])),
        'changes': _fetch_kg_nodes(inc.get('related_changes', [])),
    }
    inc['kg_context'] = kg_context
    return inc

@app.get('/incident/{incident_id}/reason', response_model=ReasoningResult)
async def get_incident_reasoning(incident_id: str):
    inc = INCIDENTS.get(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')

    kg_context = {
        'services': _fetch_kg_nodes(inc.get('affected_services', [])),
        'alerts': _fetch_kg_nodes(inc.get('related_alerts', [])),
        'changes': _fetch_kg_nodes(inc.get('related_changes', [])),
    }

    reasoning = IncidentReasoner.infer_root_causes(inc, kg_context)
    reasoning['kg_context'] = kg_context
    return reasoning

@app.get('/incidents')
async def list_incidents():
    incidents = list(INCIDENTS.values())
    summary = {
        'total': len(incidents),
        'open': len([i for i in incidents if i['status'] != 'Resolved']),
        'resolved': len([i for i in incidents if i['status'] == 'Resolved']),
        'services': list({svc for inc in incidents for svc in inc.get('affected_services', [])})
    }
    return {'incidents': incidents, 'summary': summary}

@app.get('/kg/query')
async def kg_query(q: str = ""):
    hits = [n for n in SAMPLE_KG['nodes'] if q.lower() in n.get('name', '').lower()]
    return {"query": q, "hits": hits}

@app.get('/kg/nodes')
async def kg_nodes(q: str = "", type: str = ""):
    return _query_kg(q=q, node_type=type)

@app.get('/kg/edges')
async def kg_edges(from_id: str = "", to_id: str = "", rel: str = ""):
    edges = SAMPLE_KG['edges']
    if from_id:
        edges = [e for e in edges if e.get('from') == from_id]
    if to_id:
        edges = [e for e in edges if e.get('to') == to_id]
    if rel:
        edges = [e for e in edges if e.get('rel') == rel]
    return {"from": from_id, "to": to_id, "rel": rel, "edges": edges}

@app.get('/kg/incident/{incident_id}')
async def kg_incident_graph(incident_id: str):
    try:
        return _incident_graph(incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.get('/kg/incident/{incident_id}/related')
async def kg_related_incidents(incident_id: str):
    try:
        return {"incident_id": incident_id, "related_incidents": _related_incidents(incident_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.get('/kg/subgraph')
async def kg_subgraph(node_id: str, depth: int = 1):
    return _subgraph(node_id, depth)

@app.get('/kg/history')
async def kg_history(service_id: str = '', alert_id: str = '', change_id: str = ''):
    if not (service_id or alert_id or change_id):
        raise HTTPException(status_code=400, detail='请提供 service_id、alert_id 或 change_id 之一')
    return {
        'query': {'service_id': service_id, 'alert_id': alert_id, 'change_id': change_id},
        'incidents': _history_incidents(service_id=service_id, alert_id=alert_id, change_id=change_id)
    }

@app.get('/auth/users')
async def list_users():
    return {'users': list(USERS.values())}

@app.get('/auth/me')
async def get_current_user(user_id: str = 'ui-user'):
    return _get_user(user_id)

@app.get('/incident/{incident_id}/timeline')
async def incident_timeline(incident_id: str):
    if incident_id not in INCIDENTS:
        raise HTTPException(status_code=404, detail='incident not found')
    return {'incident_id': incident_id, 'timeline': _incident_timeline(incident_id)}

@app.post('/incident/{incident_id}/timeline')
async def add_timeline_event(incident_id: str, event: TimelineEventIn):
    if incident_id not in INCIDENTS:
        raise HTTPException(status_code=404, detail='incident not found')
    actor = event.actor or 'ui-user'
    _check_permission(actor, 'add_timeline')
    return _add_timeline_event(incident_id, event.event_type, event.summary, actor, USERS[actor]['role'], event.details)

@app.get('/incident/{incident_id}/collaboration')
async def incident_collaboration(incident_id: str):
    if incident_id not in INCIDENTS:
        raise HTTPException(status_code=404, detail='incident not found')
    return {'incident_id': incident_id, 'comments': _incident_comments(incident_id)}

@app.post('/incident/{incident_id}/collaboration')
async def add_collaboration_comment(incident_id: str, payload: Dict[str, Any]):
    if incident_id not in INCIDENTS:
        raise HTTPException(status_code=404, detail='incident not found')
    author = payload.get('author', 'ui-user')
    message = payload.get('message', '')
    if not message:
        raise HTTPException(status_code=400, detail='message is required')
    _check_permission(author, 'add_comment')
    return _record_collaboration_comment(incident_id, author, message)

@app.get('/actions')
async def list_actions():
    return {"actions": SAMPLE_ACTIONS}

@app.get('/incident/{incident_id}/actions')
async def incident_actions(incident_id: str):
    if incident_id not in INCIDENTS:
        raise HTTPException(status_code=404, detail='incident not found')
    return {"incident_id": incident_id, "actions": SAMPLE_ACTIONS}

@app.get('/action/logs')
async def action_logs():
    return {"logs": ACTION_LOGS}

@app.post('/copilot/diagnose')
async def copilot_diagnose(req: CopilotDiagnoseIn):
    _check_permission(req.user_id, 'add_comment')
    inc = INCIDENTS.get(req.incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')

    kg_context = {
        'services': _fetch_kg_nodes(inc.get('affected_services', [])),
        'alerts': _fetch_kg_nodes(inc.get('related_alerts', [])),
        'changes': _fetch_kg_nodes(inc.get('related_changes', [])),
    }
    reasoning = IncidentReasoner.infer_root_causes(inc, kg_context)
    diagnosis_id = f'diag-{str(uuid.uuid4())[:8]}'
    cases = _related_cases_for_incident(req.incident_id)
    candidates = []
    for cause in reasoning.get('candidate_root_causes', []):
        candidates.append({
            **cause,
            'confidence_level': _confidence_level(cause.get('confidence', 0)),
            'evidence_chain': reasoning.get('evidence', []),
            'similar_incidents': cases,
        })
    diagnosis = {
        'diagnosis_id': diagnosis_id,
        'incident_id': req.incident_id,
        'kg_context': kg_context,
        'candidate_root_causes': candidates,
        'reasoning_steps': reasoning.get('reasoning_steps', []),
        'evidence': reasoning.get('evidence', []),
        'confidence_summary': reasoning.get('confidence_summary', 0),
        'initial_recommendations': _build_recommendations(inc, reasoning),
        'diagnostic_session_started': True,
        'created_at': _now_iso(),
        'created_by': req.user_id,
    }
    DIAGNOSES[diagnosis_id] = diagnosis
    _script_suggestions(req.incident_id, diagnosis_id)
    _add_timeline_event(req.incident_id, 'diagnosis', f'Copilot 诊断会话 {diagnosis_id} 已生成', req.user_id, _get_user(req.user_id)['role'])
    return diagnosis

@app.post('/copilot/chat')
async def copilot_chat(req: CopilotChatIn):
    _check_permission(req.user_id, 'add_comment')
    if req.incident_id not in INCIDENTS:
        raise HTTPException(status_code=404, detail='incident not found')
    if not req.message.strip():
        raise HTTPException(status_code=400, detail='message is required')

    diagnosis = DIAGNOSES.get(req.diagnosis_id or '')
    if not diagnosis:
        diagnosis = await copilot_diagnose(CopilotDiagnoseIn(incident_id=req.incident_id, user_id=req.user_id))
    top_cause = (diagnosis.get('candidate_root_causes') or [{}])[0]
    suggested_actions = [
        {
            'tool_id': rec['tools'][0],
            'rationale': rec['rationale'],
            'confidence': rec['confidence'],
        }
        for rec in diagnosis.get('initial_recommendations', [])
        if rec.get('tools')
    ]
    scripts = _script_suggestions(req.incident_id, diagnosis.get('diagnosis_id'))
    response = (
        f"我已把你的补充纳入当前诊断。优先假设是：{top_cause.get('cause', '待确认根因')}。"
        f"建议先执行只读验证，确认日志、变更窗口和依赖状态；高风险动作需要审批。"
    )
    message = {
        'message_id': f'cp-{str(uuid.uuid4())[:8]}',
        'incident_id': req.incident_id,
        'diagnosis_id': diagnosis.get('diagnosis_id'),
        'user_message': req.message,
        'response': response,
        'suggested_actions': suggested_actions,
        'script_generation_request': scripts[1] if len(scripts) > 1 else None,
        'created_at': _now_iso(),
        'user_id': req.user_id,
    }
    COPILOT_MESSAGES.append(message)
    _record_collaboration_comment(req.incident_id, req.user_id, req.message)
    COLLAB_MESSAGES.append({
        'comment_id': f'cmt-{str(uuid.uuid4())[:8]}',
        'incident_id': req.incident_id,
        'author': 'copilot',
        'role': 'copilot',
        'message': response,
        'message_type': 'copilot_analysis',
        'created_at': _now_iso()
    })
    return message

@app.get('/script/suggest')
async def suggest_scripts(incident_id: str, diagnosis_id: str = ''):
    try:
        return {'incident_id': incident_id, 'diagnosis_id': diagnosis_id, 'suggestions': _script_suggestions(incident_id, diagnosis_id or None)}
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.post('/script/verify')
async def verify_script(req: ScriptVerifyIn):
    script = SCRIPTS.get(req.script_id or '') if req.script_id else None
    code = req.script_code or (script or {}).get('code')
    if not code:
        raise HTTPException(status_code=400, detail='script_id or script_code is required')
    risk = (script or {}).get('risk_level', 'medium')
    return {
        'script_id': req.script_id,
        'dry_run_result': '通过预执行检查：未发现破坏性写操作' if risk != 'high' else '需要审批：检测到高风险服务变更动作',
        'estimated_impact': '只读验证，不影响业务' if risk == 'low' else '可能影响受影响服务，建议审批后执行',
        'approval_recommendation': 'auto_approve' if risk == 'low' else 'manual_approval',
        'risk_level': risk,
    }

@app.post('/script/execute')
async def execute_script(req: ScriptExecuteIn):
    script = SCRIPTS.get(req.script_id)
    if not script:
        raise HTTPException(status_code=404, detail='script not found')
    _check_permission(req.requested_by, 'execute_action')
    if script.get('approval_required') and not req.request_id:
        raise HTTPException(status_code=403, detail='script requires approval request_id')
    incident_id = req.incident_id or script.get('incident_id')
    incident = INCIDENTS.get(incident_id or '') if incident_id else None
    simulation = _simulate_script_output(script, incident)
    exec_id = f'sexec-{str(uuid.uuid4())[:8]}'
    result = {
        'execution_id': exec_id,
        'script_id': req.script_id,
        'incident_id': incident_id,
        'diagnosis_id': req.diagnosis_id or script.get('diagnosis_id'),
        'script_name': script.get('name'),
        'status': 'success',
        'started_at': _now_iso(),
        'requested_by': req.requested_by,
        'lifecycle_type': req.lifecycle_type,
        'output': simulation['output'],
        'conclusion': simulation['conclusion'],
        'next_suggestion': simulation['next_suggestion'],
        'fed_to_copilot': False,
    }
    ACTION_LOGS.append({
        'exec_id': exec_id,
        'execution_id': exec_id,
        'action_id': req.script_id,
        'incident_id': incident_id,
        'diagnosis_id': result['diagnosis_id'],
        'script_name': script.get('name'),
        'status': 'success',
        'output': result['output'],
        'conclusion': result['conclusion'],
        'next_suggestion': result['next_suggestion'],
        'requested_by': req.requested_by,
        'request_id': req.request_id,
        'created_at': result['started_at'],
    })
    if incident_id:
        _add_timeline_event(
            incident_id,
            'action_result',
            f"执行 {script.get('name')} 并形成观察结论",
            req.requested_by,
            _get_user(req.requested_by)['role'],
            f"{result['conclusion']} 下一步：{result['next_suggestion']}"
        )
    if req.feed_to_copilot and incident_id:
        _append_copilot_execution_feedback(incident_id, result['diagnosis_id'], result)
        result['fed_to_copilot'] = True
    if req.lifecycle_type == 'permanent':
        script['knowledge_asset'] = True
    return result

@app.get('/script/{script_id}')
async def get_script(script_id: str):
    script = SCRIPTS.get(script_id)
    if not script:
        raise HTTPException(status_code=404, detail='script not found')
    history = [log for log in ACTION_LOGS if log.get('action_id') == script_id]
    return {**script, 'execution_history': history}

@app.get('/incident/{incident_id}/discussion')
async def get_discussion(incident_id: str, message_type: str = ''):
    if incident_id not in INCIDENTS:
        raise HTTPException(status_code=404, detail='incident not found')
    comments = _incident_comments(incident_id)
    if message_type:
        comments = [msg for msg in comments if msg.get('message_type') == message_type]
    return {'incident_id': incident_id, 'messages': comments}

@app.post('/incident/{incident_id}/discussion')
async def add_discussion(incident_id: str, payload: DiscussionIn):
    if incident_id not in INCIDENTS:
        raise HTTPException(status_code=404, detail='incident not found')
    _check_permission(payload.author, 'add_comment')
    user = _get_user(payload.author)
    comment = {
        'comment_id': f'cmt-{str(uuid.uuid4())[:8]}',
        'incident_id': incident_id,
        'author': payload.author,
        'role': user['role'],
        'message': payload.message,
        'message_type': payload.message_type,
        'mentions': payload.mentions,
        'created_at': _now_iso()
    }
    COLLAB_MESSAGES.append(comment)
    if payload.message_type in ('decision', 'conclusion', 'handoff'):
        _add_timeline_event(incident_id, payload.message_type, f'记录{payload.message_type}：{payload.message[:40]}', payload.author, user['role'], payload.message)
    return comment

@app.post('/incident/{incident_id}/postmortem')
async def create_postmortem(incident_id: str, payload: PostmortemIn):
    try:
        target_id = payload.incident_id or incident_id
        return _generate_postmortem(target_id, payload.requested_by, payload.mark_resolved)
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.get('/postmortem/{postmortem_id}')
async def get_postmortem(postmortem_id: str):
    report = POSTMORTEMS.get(postmortem_id)
    if not report:
        raise HTTPException(status_code=404, detail='postmortem not found')
    return report

@app.post('/postmortem/{postmortem_id}/approve')
async def approve_postmortem(postmortem_id: str, payload: PostmortemApprovalIn):
    report = POSTMORTEMS.get(postmortem_id)
    if not report:
        raise HTTPException(status_code=404, detail='postmortem not found')
    _check_permission(payload.approver, 'approve_request')
    report['status'] = 'published'
    report['approved_by'] = payload.approver
    report['approved_at'] = _now_iso()
    report['published_scripts'] = payload.publish_scripts
    report['improvement_tasks_created'] = payload.create_improvement_tasks
    for script_id in payload.publish_scripts:
        if script_id in SCRIPTS:
            SCRIPTS[script_id]['knowledge_asset'] = True
    return report

@app.get('/incident/{incident_id}/related-cases')
async def related_cases(incident_id: str, limit: int = 5):
    try:
        return {'incident_id': incident_id, 'cases': _related_cases_for_incident(incident_id, limit)}
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.get('/incident/{incident_id}/knowledge-assets')
async def knowledge_assets(incident_id: str):
    inc = INCIDENTS.get(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')
    assets = []
    for action in SAMPLE_ACTIONS:
        assets.append({
            'asset_id': action['action_id'],
            'type': 'action_template',
            'title': action.get('name'),
            'description': action.get('description'),
            'relevance': 0.75 if not action.get('requires_approval') else 0.58,
        })
    for script in SCRIPTS.values():
        if script.get('knowledge_asset') or script.get('diagnosis_id'):
            assets.append({
                'asset_id': script['script_id'],
                'type': 'script',
                'title': script.get('name'),
                'description': script.get('explanation'),
                'relevance': script.get('confidence', 0.5),
            })
    return {'incident_id': incident_id, 'assets': sorted(assets, key=lambda item: item['relevance'], reverse=True)}

@app.get('/ontology')
async def get_ontology():
    return SAMPLE_ONTO

@app.get('/ontology/version')
async def get_ontology_version():
    return {"version": ONTOLOGY_VERSION}

@app.get('/ontology/schema')
async def get_ontology_schema():
    return ONTOLOGY_SCHEMA

@app.post('/ontology/validate', response_model=OntologyValidationResult)
async def validate_ontology(payload: Dict[str, Any]):
    valid, errors = _validate_ontology_payload(payload)
    return {"valid": valid, "errors": errors}

@app.post('/action/execute')
async def execute_action(req: ActionExecIn):
    action = next((a for a in SAMPLE_ACTIONS if a['action_id'] == req.action_id), None)
    if not action:
        raise HTTPException(status_code=404, detail='action not found')

    if action.get('requires_approval', False) and not req.request_id and not req.dry_run:
        raise HTTPException(status_code=403, detail='此动作需要审批，请先创建请求并批准后再执行。')

    if req.request_id:
        request = next((r for r in ACTION_REQUESTS if r['request_id'] == req.request_id), None)
        if not request:
            raise HTTPException(status_code=404, detail='request not found')
        if request['status'] != 'approved' and not req.dry_run:
            raise HTTPException(status_code=403, detail='请求尚未批准，不能执行。')
        request['status'] = 'executed'
        request['executed_by'] = req.requested_by

    if not req.dry_run:
        _check_permission(req.requested_by, 'execute_action')

    exec_id = f"exec-{str(uuid.uuid4())[:8]}"
    status = 'dry_run' if req.dry_run else 'success'
    result = {
        "exec_id": exec_id,
        "action_id": action['action_id'],
        "status": status,
        "output": f"{ 'Dry run: 模拟执行' if req.dry_run else '模拟执行' }: {action.get('description')}",
        "params": req.params,
        "requested_by": req.requested_by,
        "dry_run": req.dry_run,
        "request_id": req.request_id,
    }
    ACTION_LOGS.append(result)
    incident_id = request['incident_id'] if req.request_id else (req.incident_id or '')
    if incident_id:
        _add_timeline_event(incident_id, 'action_execution', f'执行动作 {req.action_id}', req.requested_by, _get_user(req.requested_by)['role'], result['output'])
    return result

@app.post('/action/request')
async def create_action_request(req: ActionRequestIn):
    action = next((a for a in SAMPLE_ACTIONS if a['action_id'] == req.action_id), None)
    if not action:
        raise HTTPException(status_code=404, detail='action not found')
    _check_permission(req.requested_by, 'create_request')
    request_id = f"req-{str(uuid.uuid4())[:8]}"
    request = {
        'request_id': request_id,
        'action_id': req.action_id,
        'incident_id': req.incident_id,
        'reason': req.reason,
        'requested_by': req.requested_by,
        'status': 'pending',
        'approver': None,
        'comment': None,
        'created_at': _now_iso()
    }
    ACTION_REQUESTS.append(request)
    _record_action_request(req.incident_id, request_id, req.action_id, req.requested_by)
    return request

@app.get('/action/requests')
async def list_action_requests():
    return {'requests': ACTION_REQUESTS}

@app.post('/action/approve')
async def approve_action_request(req: ActionApprovalIn):
    request = next((r for r in ACTION_REQUESTS if r['request_id'] == req.request_id), None)
    if not request:
        raise HTTPException(status_code=404, detail='request not found')
    _check_permission(req.approver, 'approve_request')
    request['status'] = 'approved' if req.approved else 'rejected'
    request['approver'] = req.approver
    request['comment'] = req.comment
    request['approved_at'] = _now_iso()
    _record_action_approval(request['incident_id'], req.request_id, req.approver, req.approved)
    return request

@app.get('/')
async def root():
    return {
        "service": "IntelliOps Prototype API",
        "routes": [
            "/incident/{id}",
            "/incident/{id}/reason",
            "/kg/query",
            "/kg/nodes",
            "/kg/edges",
            "/kg/incident/{id}",
            "/kg/incident/{id}/related",
            "/kg/subgraph?node_id=svc-001&depth=1",
            "/kg/history?service_id=svc-001",
            "/auth/users",
            "/auth/me?user_id=ui-user",
            "/incident/{id}/timeline",
            "/incident/{id}/collaboration",
            "/ontology",
            "/ontology/version",
            "/ontology/schema",
            "/ontology/validate",
            "/actions",
            "/action/execute",
            "/action/request",
            "/action/requests",
            "/action/approve",
            "/action/logs",
            "/copilot/diagnose",
            "/copilot/chat",
            "/script/suggest?incident_id=inc-1",
            "/script/verify",
            "/script/execute",
            "/script/{id}",
            "/incident/{id}/discussion",
            "/incident/{id}/postmortem",
            "/postmortem/{id}",
            "/incident/{id}/related-cases",
            "/incident/{id}/knowledge-assets",
            "/ui/"
        ]
    }

# Mount static UI under /ui (serves src/ui/index.html)
UI_DIR = os.path.join(DATA_ROOT, 'ui')
if os.path.isdir(UI_DIR):
    app.mount('/ui', StaticFiles(directory=UI_DIR, html=True), name='ui')
