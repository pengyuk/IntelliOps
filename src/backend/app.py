from dotenv import load_dotenv
load_dotenv()  # 加载项目根目录的 .env 文件

from collections import deque
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, List, Optional
import json
import re
import uuid
import os
import datetime
import warnings
import traceback

# Suppress openpyxl default-style warning
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

from .reasoner import IncidentReasoner
from .data_service import DataService
from .knowledge_graph import KnowledgeGraph
from .alarm_analyze import AlarmAnalyzer
from .fault_diagnosis import FaultDiagnosisService
from .log_analyzer import LogAnalyzer
from .copilot import Copilot
from .knowledge_distiller import KnowledgeDistiller
from .knowledge_deduplicator import deduplicate_knowledge
from .pattern_aggregator import find_high_frequency_patterns, run_pattern_aggregation
from .skill_updater import update_all_mature_patterns
from .credibility import enrich_diagnosis
from .db import get_db, Database
from .state_machine import InvestigationState
from .vector_search import VectorSearch, get_vector_search
from .websocket_manager import manager
from .skill_loader import SkillLoader, get_skill_loader
from .skill_router import SkillRouter
from .agent_orchestrator import AgentOrchestrator, get_orchestrator, AGENT_IDENTITIES
from .incident_pipeline import (
    run_incident_pipeline, on_script_executed, run_postmortem_agent,
)
from .discussion_sync_agent import sync_discussion_to_copilot, DiscussionSyncAgent
from ..ontology.validator import ONTOLOGY_VERSION, ONTOLOGY_SCHEMA, validate_payload as _validate_ontology_payload

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.abspath(os.path.join(HERE, '..'))
DATA_SERVICE: Optional[DataService] = None
KG_SERVICE: Optional[KnowledgeGraph] = None
DB: Database = get_db()

def _get_data_service() -> DataService:
    global DATA_SERVICE
    if DATA_SERVICE is None:
        DATA_SERVICE = DataService(DATA_ROOT, eager=False)  # lazy by default
    return DATA_SERVICE

def _get_kg_service() -> KnowledgeGraph:
    global KG_SERVICE
    if KG_SERVICE is None:
        ds = _get_data_service()
        # KG can work with empty data — it will be rebuilt on reload
        KG_SERVICE = KnowledgeGraph(ds.system_relations, ds.application_registry)
    return KG_SERVICE

app = FastAPI(title="IntelliOps Prototype API")

@app.on_event("startup")
async def startup():
    skip_db = os.environ.get("SKIP_DB_INIT", "0") == "1"
    print("[startup] ========== IntelliOps Starting ==========")

    if skip_db:
        print("[startup] ⏩ SKIP_DB_INIT=1 — skipping database initialization")
        print("[startup]    Use POST /data/reload to load data on demand")
    else:
        print("[startup] Step 1/3: Initializing database...")
        try:
            await DB.init()
        except Exception as e:
            print(f"[startup] ⚠ DB init failed (non-fatal): {e}")

        print("[startup] Step 2/3: Importing alarm data (lazy — will load on first access)...")
        try:
            skip_data = os.environ.get("SKIP_DATA_LOAD", "0") == "1"
            if skip_data:
                print("[startup] ⏩ SKIP_DATA_LOAD=1 — skipping alarm data import")
            else:
                ds = _get_data_service()
                imported = await DB.seed_from_data_service(ds)
                if imported:
                    print(f"[startup] ✓ Imported {imported} alarm records as supplemental incidents")
        except Exception as e:
            print(f"[startup] ⚠ Alarm import skipped: {e}")

        print("[startup] Step 3/3: Seeding demo showcase cases...")
        try:
            await DB._seed()
        except Exception as e:
            print(f"[startup] ⚠ Demo seed skipped: {e}")

    # LLM status check
    from .llm_client import LLMClient
    llm = LLMClient()
    if llm.provider in ("openai", "anthropic", "ollama"):
        print(f"[startup] ✓ LLM configured: provider={llm.provider}")
    else:
        print("[startup] ⚠ LLM NOT configured — diagnoses will use rule-based fallback.")
        print("[startup]   Set env: LLM_PROVIDER=openai (or anthropic/ollama) + API key")
    
    # Skill loading
    print("[startup] Step 4/4: Loading Skills...")
    try:
        loader = await get_skill_loader()
        skill_count = len(loader.skills)
        print(f"[startup] ✓ Skills loaded: {skill_count}")
        for name in loader.skills:
            print(f"[startup]     • {name}")
    except Exception as e:
        print(f"[startup] ⚠ Skill loading failed (non-fatal): {e}")
    
    # Pre-warm embedding model in background (non-blocking startup)
    print("[startup] Step 5/5: Pre-warming ML models (background)...")
    try:
        import asyncio as _asyncio
        _asyncio.create_task(VectorSearch.prewarm())
    except Exception as e:
        print(f"[startup] ⚠ Model pre-warm skipped (non-fatal): {e}")
    
    # Warm up orchestrator
    try:
        orch = await get_orchestrator()
        print(f"[startup] ✓ Agent Orchestrator ready")
    except Exception as e:
        print(f"[startup] ⚠ Orchestrator init skipped: {e}")
    
    print("[startup] ========== Startup Complete ==========")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:3000", "http://127.0.0.1:8080", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load sample KG and ontology (with error handling)
print("[startup] Loading sample data files...")
try:
    with open(os.path.join(DATA_ROOT, 'kg', 'sample_kg.json'), 'r', encoding='utf-8') as f:
        SAMPLE_KG = json.load(f)
    print("[startup]   ✓ sample_kg.json loaded")
except Exception as e:
    print(f"[startup]   ⚠ Failed to load sample_kg.json: {e}")
    SAMPLE_KG = {}

try:
    with open(os.path.join(DATA_ROOT, 'ontology', 'sample_ontology.jsonld'), 'r', encoding='utf-8') as f:
        SAMPLE_ONTO = json.load(f)
    print("[startup]   ✓ sample_ontology.jsonld loaded")
except Exception as e:
    print(f"[startup]   ⚠ Failed to load sample_ontology.jsonld: {e}")
    SAMPLE_ONTO = {}

try:
    with open(os.path.join(DATA_ROOT, 'harness', 'sample_actions.json'), 'r', encoding='utf-8') as f:
        SAMPLE_ACTIONS = json.load(f)
    print("[startup]   ✓ sample_actions.json loaded")
except Exception as e:
    print(f"[startup]   ⚠ Failed to load sample_actions.json: {e}")
    SAMPLE_ACTIONS = {}

# In-memory stores removed — now using SQLite via DB (see db.py)

# Ontology schema & validation moved to src/ontology/validator.py


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


async def _add_timeline_event(incident_id: str, event_type: str, summary: str, actor: str, role: str, details: str = '', related_root_cause_id: str = '') -> Dict[str, Any]:
    events = await DB.list_timeline(incident_id)
    event = {
        'event_id': f'evt-{str(uuid.uuid4())[:8]}',
        'incident_id': incident_id,
        'event_type': event_type,
        'summary': summary,
        'actor': actor,
        'role': role,
        'timestamp': _now_iso(),
        'sequence': len(events) + 1,
        'details': details,
        # P0-3: 时间线事件关联根因假设ID，支持追溯链
        'related_root_cause_id': related_root_cause_id,
    }
    await DB.add_timeline_event(event)
    await manager.broadcast(incident_id, {"type": "timeline", "event": event})
    return event


async def _incident_timeline(incident_id: str) -> List[Dict[str, Any]]:
    return await DB.list_timeline(incident_id)


async def _incident_comments(incident_id: str) -> List[Dict[str, Any]]:
    return await DB.list_discussion(incident_id)


async def _record_collaboration_comment(incident_id: str, author: str, message: str, record_timeline: bool = False) -> Dict[str, Any]:
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
    await DB.add_discussion(comment)
    if record_timeline:
        await _add_timeline_event(incident_id, 'decision', f'记录关键协同结论：{message[:50]}', author, user['role'], message)
    return comment


async def _record_action_request(incident_id: str, request_id: str, action_id: str, author: str) -> None:
    user = _get_user(author)
    await _add_timeline_event(incident_id, 'action_request', f'创建动作审批请求 {request_id}', author, user['role'], f'动作 {action_id} 申请执行')


async def _record_action_approval(incident_id: str, request_id: str, approver: str, approved: bool) -> None:
    user = _get_user(approver)
    status = '批准' if approved else '拒绝'
    await _add_timeline_event(
        incident_id,
        'action_approval',
        f'审批请求 {request_id} 已{status}',
        approver,
        user['role'],
        f'请求 {request_id} 已{status}。'
    )


def _fetch_kg_nodes(ids: List[str]) -> List[Dict[str, Any]]:
    return [node for node in SAMPLE_KG['nodes'] if node.get('id') in ids]

# Incidents now stored in SQLite via DB (db.py) — seeded on startup


from .models import (
    AlertIn, RawAlertIn, ActionExecIn, ActionRequestIn, ActionApprovalIn,
    ReasoningResult, OntologyValidationResult, TimelineEventIn,
    CopilotDiagnoseIn, CopilotChatIn, ScriptVerifyIn, ScriptExecuteIn,
    DiscussionIn, PostmortemIn, PostmortemApprovalIn,
    InvestigationStateIn, InvestigationItemIn, InvestigationMoveIn,
    IncidentCreateIn, IncidentSimulateIn,
)

# ---- Models extracted to models.py ----


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


async def _incident_graph(incident_id: str) -> Dict[str, Any]:
    inc = await DB.get_incident(incident_id)
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


async def _history_incidents(service_id: str = '', alert_id: str = '', change_id: str = '') -> List[Dict[str, Any]]:
    results = []
    for inc in await DB.list_incidents():
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

async def _related_incidents(incident_id: str) -> List[Dict[str, Any]]:
    inc = await DB.get_incident(incident_id)
    if not inc:
        raise KeyError('incident not found')

    related_incidents = []
    for other in await DB.list_incidents():
        if other['incident_id'] != incident_id:
            if (set(other.get('affected_services', [])) & set(inc.get('affected_services', [])) or
                set(other.get('related_alerts', [])) & set(inc.get('related_alerts', [])) or
                set(other.get('related_changes', [])) & set(inc.get('related_changes', []))):
                related_incidents.append(other)
    return related_incidents


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

async def _related_cases_for_incident(incident_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    incident = await DB.get_incident(incident_id)
    if not incident:
        raise KeyError('incident not found')

    cases = []
    current_services = set(incident.get('affected_services', []))
    current_changes = set(incident.get('related_changes', []))
    current_alerts = set(incident.get('related_alerts', []))
    # P0-1: 扩展上下游系统到检索范围
    upstream_ids = set(incident.get('_upstream_ids', []))
    downstream_ids = set(incident.get('_downstream_ids', []))
    all_change_ids = set(incident.get('_all_change_ids', []))
    # 合并上下文系统用于检索
    context_system_ids = current_services | upstream_ids | downstream_ids
    context_change_ids = current_changes | all_change_ids
    
    for other in await DB.list_incidents():
        other_id = other['incident_id']
        if other_id == incident_id:
            continue
        score = 0
        score += 3 * len(current_services & set(other.get('affected_services', [])))
        # P0-1: 上下游系统匹配加分
        score += 2 * len(upstream_ids & set(other.get('affected_services', [])))
        score += 2 * len(downstream_ids & set(other.get('affected_services', [])))
        # 变更匹配（含上下游变更）
        score += 2 * len(context_change_ids & set(other.get('related_changes', [])))
        # 共享上游依赖（隐性关联）
        other_upstream = set(other.get('_upstream_ids', []))
        score += 1 * len(upstream_ids & other_upstream)
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
    # Also search real postmortem reports from data_service
    try:
        ds = _get_data_service()
        keywords = list(current_services) + [incident.get('summary', '')]
        postmortem_matches = ds.search_postmortems([k for k in keywords if k])
        for pm in postmortem_matches[:2]:
            cases.append({
                'incident_id': pm.get('report_id', ''),
                'summary': pm.get('title', '')[:60],
                'status': 'Resolved',
                'similarity_score': 15,  # high score for real postmortem match
                'root_cause': pm.get('content', '')[:200],
                'resolution_steps': [],
                'scripts_used': [],
                'source': 'postmortem_report',
            })
    except Exception:
        pass
    
    # Re-rank using vector search for semantic similarity
    try:
        if cases:
            vs = get_vector_search()
            vs.index_items(cases, text_key="summary")
            query = incident.get('summary', '')
            if query:
                ranked = vs.search(query, top_k=limit)
                # Merge vector scores with existing similarity scores
                for item, vec_score in ranked:
                    for c in cases:
                        if c.get('incident_id') == item.get('incident_id'):
                            c['similarity_score'] = c.get('similarity_score', 0) + int(vec_score * 10)
                            break
    except Exception:
        pass
    
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

async def _upsert_script(script: Dict[str, Any]) -> Dict[str, Any]:
    await DB.upsert_script(script)
    return script

async def _script_suggestions(incident_id: str, diagnosis_id: Optional[str] = None) -> List[Dict[str, Any]]:
    incident = await DB.get_incident(incident_id)
    if not incident:
        raise KeyError('incident not found')
    service = incident.get('affected_services', ['svc-001'])[0] if incident.get('affected_services') else 'svc-001'
    summary = incident.get('summary', '')
    affected = incident.get('affected_services', [])

    # Detect scenario type and tailor scripts
    is_bocs_dnf = any(s in summary for s in ['BOCS-DNF', 'DNF', '数据下刷', 'MQ', 'QREP', 'Pageset', '历史数据清理', '2603'])
    is_mcis = any(s in summary for s in ['MCIS', '湖南分行', '第三方', '餐卡', '网银缴费', '成功率下降'])

    suggestions: List[Dict[str, Any]] = []

    if is_bocs_dnf:
        suggestions = [
            {
                'script_id': f'script-mq-pageset-{incident_id}',
                'name': '检查MQ Pageset使用率与队列深度',
                'language': 'mqsc',
                'code': 'DISPLAY QSTATUS(QR.XMITQ1.QPS1.TO.QMA) CURDEPTH; DISPLAY PAGESET(1) USAGE',
                'confidence': 0.92,
                'category': 'approved',
                'risk_level': 'low',
                'explanation': '只读查询MQ Pageset使用率和QREP队列深度，用于确认告警级别和堆积趋势。',
                'approval_required': False,
                'incident_id': incident_id,
                'diagnosis_id': diagnosis_id,
            },
            {
                'script_id': f'script-qrep-status-{incident_id}',
                'name': '检查QREP同步状态与延迟',
                'language': 'shell',
                'code': 'DISPLAY QREP CAPTURE STATUS; DISPLAY QREP APPLY LAG; SELECT COUNT(*) FROM SYNC_BACKLOG',
                'confidence': 0.88,
                'category': 'approved',
                'risk_level': 'low',
                'explanation': '检查QREP Capture/Apply状态和端到端延迟，评估数据追平所需时间。',
                'approval_required': False,
                'incident_id': incident_id,
                'diagnosis_id': diagnosis_id,
            },
            {
                'script_id': f'script-stop-cleanup-{incident_id}',
                'name': '停止历史数据清理批量作业',
                'language': 'sql',
                'code': "ALTER SYSTEM STOP HISTORICAL_CLEANUP JOB; SELECT JOB_NAME, STATUS FROM BATCH_JOBS WHERE TYPE='HISTORICAL_CLEANUP'",
                'confidence': 0.85,
                'category': 'copilot_generated',
                'risk_level': 'high',
                'explanation': '高风险操作：停止正在运行的历史数据清理批量。需要开发一部确认后执行。',
                'approval_required': True,
                'incident_id': incident_id,
                'diagnosis_id': diagnosis_id,
            },
            {
                'script_id': f'script-mips-expand-{incident_id}',
                'name': '主机MIPS临时扩容',
                'language': 'hmc',
                'code': 'ACTIVATE LPAR MIPS_QUOTA +9420 ON LPAR(BOCSPRD)',
                'confidence': 0.78,
                'category': 'copilot_generated',
                'risk_level': 'high',
                'explanation': '高风险操作：为主机LPAR临时增加9420 MIPS以应对交易高峰。需系统平台一部审批。',
                'approval_required': True,
                'incident_id': incident_id,
                'diagnosis_id': diagnosis_id,
            },
            {
                'script_id': f'script-dnf-cutover-{incident_id}',
                'name': 'DNF流量回切（心跳开关批量操作）',
                'language': 'shell',
                'code': 'seq="440 412 490 400 466 895 449 426 63631"; for s in $seq; do OPEN_DNF_HEARTBEAT $s; done',
                'confidence': 0.72,
                'category': 'high_risk',
                'risk_level': 'high',
                'explanation': '高风险恢复动作：按指定顺序打开DNF心跳开关，将查询交易从主机切至DNF。需当值经理审批。',
                'approval_required': True,
                'incident_id': incident_id,
                'diagnosis_id': diagnosis_id,
            },
        ]
    elif is_mcis:
        suggestions = [
            {
                'script_id': f'script-mcis-success-rate-{incident_id}',
                'name': 'MCIS→CSP接口成功率按商户维度统计',
                'language': 'sql',
                'code': "SELECT merchant_id, COUNT(*), SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END)*100.0/COUNT(*) as success_rate FROM mcis_txn_log WHERE channel='CSP' AND time BETWEEN '07:42' AND '08:01' GROUP BY merchant_id",
                'confidence': 0.90,
                'category': 'approved',
                'risk_level': 'low',
                'explanation': '只读查询：按商户维度统计MCIS到CSP的交易成功率，用于隔离故障范围。',
                'approval_required': False,
                'incident_id': incident_id,
                'diagnosis_id': diagnosis_id,
            },
            {
                'script_id': f'script-branch-check-{incident_id}',
                'name': '通知湖南分行并行排查',
                'language': 'manual',
                'code': '# 人工操作：服务台通知湖南分行金融科技部排查CSP→分行特色→第三方链路',
                'confidence': 0.82,
                'category': 'approved',
                'risk_level': 'low',
                'explanation': '协调操作：通知分行科技部同步排查第三方商户系统状态。',
                'approval_required': False,
                'incident_id': incident_id,
                'diagnosis_id': diagnosis_id,
            },
            {
                'script_id': f'script-log-{incident_id}',
                'name': '采集MCIS渠道接入日志',
                'language': 'bash',
                'code': f'grep -E "CSPS0119|E10902|湖南|网银缴费" /var/log/mcis/channel.log --since "07:30"',
                'confidence': 0.78,
                'category': 'approved',
                'risk_level': 'low',
                'explanation': '只读采集MCIS渠道接入日志，验证接口调用链路和返回码。',
                'approval_required': False,
                'incident_id': incident_id,
                'diagnosis_id': diagnosis_id,
            },
        ]
    else:
        # ── P1-3: KG-aware generic script suggestions ──
        suggestions = _build_kg_aware_scripts(incident, incident_id, diagnosis_id, service, affected)
    
    return [await _upsert_script(script) for script in suggestions]


def _build_kg_aware_scripts(
    incident: Dict[str, Any],
    incident_id: str,
    diagnosis_id: Optional[str],
    service: str,
    affected: List[str],
) -> List[Dict[str, Any]]:
    """Build topology-aware script recommendations based on KG upstream/downstream types.
    
    Analyzes the types of upstream and downstream dependencies and recommends
    appropriate diagnostic scripts for each dependency type (DB, MQ, cache, etc.).
    """
    suggestions: List[Dict[str, Any]] = []
    
    # Always include basic log collection
    suggestions.append({
        'script_id': f'script-log-{incident_id}',
        'name': f'采集 {service} 关键错误日志',
        'language': 'bash',
        'code': f'journalctl -u {service} --since "30 minutes ago" | grep -E "ERROR|WARN|timeout|slow"',
        'confidence': 0.84,
        'category': 'approved',
        'risk_level': 'low',
        'explanation': '只读采集日志，用于验证延迟、超时或异常堆栈。',
        'approval_required': False,
        'incident_id': incident_id,
        'diagnosis_id': diagnosis_id,
    })
    
    # ── KG topology discovery ──
    kg_context = incident.get('kg_context', {})
    upstream_nodes = kg_context.get('upstream', [])
    downstream_nodes = kg_context.get('downstream', [])
    upstream_ids = kg_context.get('upstream_ids', [])
    downstream_ids = kg_context.get('downstream_ids', [])
    dependency_chain = kg_context.get('dependency_chain', {})
    
    # Classify upstream dependencies by type
    upstream_types = _classify_dependency_types(upstream_nodes, upstream_ids)
    downstream_types = _classify_dependency_types(downstream_nodes, downstream_ids)
    
    # ── Upstream-aware recommendations ──
    if upstream_types.get('database'):
        db_names = ', '.join(upstream_types['database'][:2])
        suggestions.append({
            'script_id': f'script-db-check-{incident_id}',
            'name': f'检查上游数据库连接池与慢查询 ({db_names})',
            'language': 'sql',
            'code': "SELECT count(*) AS active_conns FROM pg_stat_activity WHERE state='active'; SELECT query, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;",
            'confidence': 0.88,
            'category': 'kg_aware',
            'risk_level': 'low',
            'explanation': f'受影响服务的上游依赖包含数据库 ({db_names})，优先检查数据库侧连接池状态和慢查询。',
            'approval_required': False,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
            'topology_hint': f'上游DB: {db_names}',
        })
    
    if upstream_types.get('message_queue'):
        mq_names = ', '.join(upstream_types['message_queue'][:2])
        suggestions.append({
            'script_id': f'script-mq-check-{incident_id}',
            'name': f'检查上游消息队列积压与消费延迟 ({mq_names})',
            'language': 'bash',
            'code': '# 检查队列深度和消费延迟\ndisplay_qdepth.sh; check_consumer_lag.sh',
            'confidence': 0.86,
            'category': 'kg_aware',
            'risk_level': 'low',
            'explanation': f'受影响服务的上游依赖包含消息队列 ({mq_names})，优先检查队列积压和消费延迟。',
            'approval_required': False,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
            'topology_hint': f'上游MQ: {mq_names}',
        })
    
    if upstream_types.get('cache'):
        cache_names = ', '.join(upstream_types['cache'][:2])
        suggestions.append({
            'script_id': f'script-cache-check-{incident_id}',
            'name': f'检查上游缓存命中率与连接状态 ({cache_names})',
            'language': 'bash',
            'code': 'redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses|connected_clients|evicted_keys"',
            'confidence': 0.84,
            'category': 'kg_aware',
            'risk_level': 'low',
            'explanation': f'受影响服务的上游依赖包含缓存 ({cache_names})，检查缓存命中率和连接数。',
            'approval_required': False,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
            'topology_hint': f'上游缓存: {cache_names}',
        })
    
    if upstream_types.get('third_party'):
        tp_names = ', '.join(upstream_types['third_party'][:2])
        suggestions.append({
            'script_id': f'script-thirdparty-check-{incident_id}',
            'name': f'探测上游第三方接口可用性 ({tp_names})',
            'language': 'bash',
            'code': f'curl -s -o /dev/null -w "%{{http_code}} %{{time_total}}" --connect-timeout 5 <third_party_url>',
            'confidence': 0.82,
            'category': 'kg_aware',
            'risk_level': 'low',
            'explanation': f'受影响服务的上游依赖包含第三方接口 ({tp_names})，探测可用性和响应时间。',
            'approval_required': False,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
            'topology_hint': f'上游第三方: {tp_names}',
        })
    
    # ── Downstream impact awareness ──
    if downstream_types.get('database'):
        db_names = ', '.join(downstream_types['database'][:2])
        suggestions.append({
            'script_id': f'script-downstream-db-{incident_id}',
            'name': f'检查下游数据库是否受本服务影响 ({db_names})',
            'language': 'sql',
            'code': f"SELECT count(*) FROM pg_stat_activity WHERE query LIKE '%{service}%';",
            'confidence': 0.80,
            'category': 'kg_aware',
            'risk_level': 'low',
            'explanation': f'本服务下游依赖数据库 ({db_names})，检查是否因本服务故障产生异常连接。',
            'approval_required': False,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
            'topology_hint': f'下游DB: {db_names}',
        })
    
    # ── Dependency chain context ──
    depends_on = dependency_chain.get('depends_on', [])
    if depends_on:
        dep_names = list({d.get('depends_on', '') for d in depends_on if d.get('depends_on')})[:3]
        suggestions.append({
            'script_id': f'script-dependency-health-{incident_id}',
            'name': f'检查关键依赖服务健康状态',
            'language': 'python',
            'code': f'# 检查依赖链: {", ".join(dep_names)}\nprint("checking dependency health...")',
            'confidence': 0.78,
            'category': 'kg_aware',
            'risk_level': 'low',
            'explanation': f'获取依赖链中各节点的健康检查端点状态。核心依赖: {", ".join(dep_names)}。',
            'approval_required': False,
            'incident_id': incident_id,
            'diagnosis_id': diagnosis_id,
            'topology_hint': f'依赖链: {", ".join(dep_names)}',
        })
    
    # Always include metrics check and restart (high-risk)
    suggestions.append({
        'script_id': f'script-metrics-{incident_id}',
        'name': '检查服务核心指标（连接池、慢查询、P99延迟）',
        'language': 'python',
        'code': 'print("db_pool_active=450 db_pool_max=500 slow_queries=27 p99_latency_ms=1850")',
        'confidence': 0.76,
        'category': 'copilot_generated',
        'risk_level': 'medium',
        'explanation': '模拟指标检查脚本，汇总连接池、慢查询和延迟数据。',
        'approval_required': False,
        'incident_id': incident_id,
        'diagnosis_id': diagnosis_id,
    })
    
    suggestions.append({
        'script_id': f'script-restart-{incident_id}',
        'name': f'重启受影响服务 {service}',
        'language': 'bash',
        'code': f'systemctl restart {service}',
        'confidence': 0.48,
        'category': 'high_risk',
        'risk_level': 'high',
        'explanation': '高风险恢复动作，需要审批后执行。仅在确认根因且无更低风险方案时使用。',
        'approval_required': True,
        'incident_id': incident_id,
        'diagnosis_id': diagnosis_id,
    })
    
    return suggestions


def _classify_dependency_types(
    nodes: List[Dict[str, Any]],
    node_ids: List[str],
) -> Dict[str, List[str]]:
    """Classify KG dependency nodes by type (database, MQ, cache, etc.).
    
    Uses node name heuristics and type field to categorize dependencies.
    Returns dict like: {'database': ['pg-master', 'mysql-slave'], 'message_queue': ['kafka-cluster']}
    """
    types: Dict[str, List[str]] = {
        'database': [],
        'message_queue': [],
        'cache': [],
        'third_party': [],
        'gateway': [],
        'storage': [],
        'other': [],
    }
    
    # Keywords for classification
    db_keywords = ['db', 'database', 'postgres', 'mysql', 'oracle', 'mongo', 'redis', 'sql', 'tidb', 'oceanbase', 'db2']
    mq_keywords = ['mq', 'kafka', 'rabbitmq', 'rocketmq', 'pulsar', 'qrep', 'queue', '消息']
    cache_keywords = ['cache', 'redis', 'memcached', 'caffeine', '缓存']
    tp_keywords = ['third', '第三方', 'external', 'api', 'gateway', 'payment', 'sms', 'push']
    gw_keywords = ['gateway', '网关', 'nginx', 'apigw', 'kong', 'zuul', 'ingress']
    storage_keywords = ['oss', 's3', 'minio', 'ceph', 'nas', 'nfs', 'hdfs', '存储']
    
    for i, node in enumerate(nodes):
        name = str(node.get('name', node_ids[i] if i < len(node_ids) else '')).lower()
        node_type = str(node.get('type', '')).lower()
        
        if any(kw in name or kw in node_type for kw in db_keywords):
            types['database'].append(node.get('name', node_ids[i]))
        elif any(kw in name or kw in node_type for kw in mq_keywords):
            types['message_queue'].append(node.get('name', node_ids[i]))
        elif any(kw in name or kw in node_type for kw in cache_keywords):
            types['cache'].append(node.get('name', node_ids[i]))
        elif any(kw in name or kw in node_type for kw in tp_keywords):
            types['third_party'].append(node.get('name', node_ids[i]))
        elif any(kw in name or kw in node_type for kw in gw_keywords):
            types['gateway'].append(node.get('name', node_ids[i]))
        elif any(kw in name or kw in node_type for kw in storage_keywords):
            types['storage'].append(node.get('name', node_ids[i]))
        else:
            types['other'].append(node.get('name', node_ids[i]))
    
    # Remove empty categories
    return {k: v for k, v in types.items() if v}


def _simulate_script_output(script: Dict[str, Any], incident: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    script_id = script.get('script_id', '')
    script_name = script.get('name', '')
    service_names = _node_names((incident or {}).get('affected_services', []))
    service_text = ', '.join(service_names) or '受影响服务'

    # BOCS-DNF / MCIS real-case scripts
    if 'mq-pageset' in script_id or 'MQ' in script_name or 'Pageset' in script_name:
        output = 'QPS1 PageSet ID:1 Usage=76.49% (>=75% CRI); NamedQueue Depth=2197878; MQ速率正常; QREP正常'
        conclusion = 'MQ Pageset使用率76.49%已达一级告警，队列深度219万持续增长。MQ传输速率正常，根因非QREP自身性能，需排查数据写入源（疑似历史数据清理批量导致大量DB2日志写入）。'
        next_suggestion = '建议：(1)检查BOCS-D当前批量作业 (2)排查历史数据清理 (3)联系开发一部确认2603批次清理计划'
    elif 'qrep' in script_id.lower() or 'QREP' in script_name:
        output = 'QREP Capture=ACTIVE; Apply延迟=42min; 速率=0.85亿/h; 待同步≈5亿; 预计追平≈6h'
        conclusion = 'QREP Apply延迟42分钟（正常<1秒），下刷速率低于日常。待同步约5亿条，预计需6小时追平，远超7:00回切窗口。'
        next_suggestion = '建议：(1)停止历史数据清理批量 (2)下起QREP实例提速 (3)评估MIPS临时扩容'
    elif 'cleanup' in script_id.lower() or '清理' in script_name or '停止' in script_name:
        output = '已执行: STOP HISTORICAL_CLEANUP; 作业=0; 已清理25.1亿; QREP下刷5.02亿; Pageset: 76%→68%'
        conclusion = '成功停止历史数据清理。MQ Pageset从76%降至68%。当日清理25.1亿数据（2603试点行8.5亿+恢复暂停表15亿+日常6亿），QREP下刷约5亿。'
        next_suggestion = '建议：(1)监控MQ Pageset下降趋势 (2)评估数据追平时间 (3)必要时下起QREP加速'
    elif 'mips' in script_id.lower() or 'MIPS' in script_name or '扩容' in script_name:
        output = 'MIPS临时扩容: +9420; 总量=120630 MIPS; CPU: 84%→72%'
        conclusion = '成功为主机LPAR增加9420 MIPS。CPU从84%降至72%，按昨日峰值推算可安全度过早高峰。'
        next_suggestion = '建议：(1)持续监控CPU (2)备用扩容方案待命 (3)评估关停准生产'
    elif 'cutover' in script_id.lower() or '心跳' in script_name or '回切' in script_name or '切换' in script_name:
        output = 'DNF心跳按序打开: 440→412→490→400→466→895→449→426→63631; 海鹰隔离完成; 切换耗时75s'
        conclusion = 'DNF回切完成。黑山扈DNF已接收查询流量。切换期间C-DBC出现79秒波动，主机MaxTask已解除。'
        next_suggestion = '建议：(1)监控DNF成功率 (2)确认C-DBC/IPPS/RCPS-IBPS回升 (3)准备复盘'
    elif 'mcis' in script_id.lower() or 'MCIS' in script_name or '成功率' in script_name:
        output = 'MCIS→湖南CSP: 总710笔, 成功323笔, 成功率45.5%; 商户: 长沙建南电子=0%, 其他4家=100%'
        conclusion = '故障范围确认：仅长沙建南电子交易全部失败。MCIS和CSP自身正常，故障定位于第三方系统。'
        next_suggestion = '建议：(1)通知湖南分行排查 (2)总行持续监控 (3)8:30未恢复启客诉应对'
    elif 'branch' in script_id.lower() or '分行' in script_name:
        output = '湖南分行: CSP正常, 特色系统正常, 根因=长沙建南电子加密解密模块软件故障。8:01自动恢复。'
        conclusion = '根因确认为第三方厂商加密解密模块故障。分行第三方原因，总行无需处置，已自动恢复。'
        next_suggestion = '建议：(1)要求厂商提供报告 (2)调整外部商户超时参数 (3)完善交易级监控'
    elif 'metrics' in script_id:
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

async def _append_copilot_execution_feedback(incident_id: str, diagnosis_id: Optional[str], execution: Dict[str, Any]) -> Dict[str, Any]:
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
    await DB.add_discussion(message)
    # Copilot messages stored in discussion table
    await DB.add_discussion({
        'message_id': f'cp-{str(uuid.uuid4())[:8]}',
        'incident_id': incident_id,
        'diagnosis_id': diagnosis_id,
        'response': response,
        'execution_result': execution,
        'created_at': _now_iso(),
        'user_id': 'copilot',
    })
    return message

async def _generate_postmortem(incident_id: str, requested_by: str = 'ui-user', mark_resolved: bool = True) -> Dict[str, Any]:
    incident = await DB.get_incident(incident_id)
    if not incident:
        raise KeyError('incident not found')
    if mark_resolved:
        incident['status'] = 'Resolved'
        await _add_timeline_event(incident_id, 'status', '事故已标记恢复，进入复盘', requested_by, _get_user(requested_by)['role'])

    diagnoses = await DB.list_diagnoses(incident_id)
    diagnosis = diagnoses[0] if diagnoses else None
    if not diagnosis:
        reasoning = await IncidentReasoner.infer_root_causes(incident, {
            'services': _fetch_kg_nodes(incident.get('affected_services', [])),
            'alerts': _fetch_kg_nodes(incident.get('related_alerts', [])),
            'changes': _fetch_kg_nodes(incident.get('related_changes', [])),
        })
    else:
        reasoning = diagnosis

    top_cause = (reasoning.get('candidate_root_causes') or [{}])[0]
    postmortem_id = f'pm-{str(uuid.uuid4())[:8]}'
    used_logs = await DB.list_action_logs()
    report = {
        'postmortem_id': postmortem_id,
        'incident_id': incident_id,
        'status': 'draft',
        'created_at': _now_iso(),
        'created_by': requested_by,
        'timeline': await _incident_timeline(incident_id),
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
        'scripts_used': [script for script in await DB.list_scripts() if script.get('diagnosis_id') == reasoning.get('diagnosis_id')],
        'improvement_suggestions': [
            '将本次高置信根因与验证脚本沉淀为知识资产。',
            '为受影响服务补充连接池、慢查询和变更窗口的联合告警。',
            '把高风险动作纳入审批模板，保留审计链路。',
        ],
    }
    await DB.upsert_postmortem(report)
    return report

@app.get('/health')
async def health_check():
    """Health check with LLM status."""
    from .llm_client import LLMClient
    llm = LLMClient()
    return {
        "status": "ok",
        "llm": {
            "provider": llm.provider,
            "configured": llm.provider in ("openai", "anthropic", "ollama"),
            "models": {
                "openai": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
                "ollama": os.environ.get("OLLAMA_MODEL", "llama3.1"),
            }.get(llm.provider, "N/A"),
        },
        "db": os.path.exists(DB.path),
        "data_service": bool(_get_data_service().alarm_records),
        "skills": _get_skills_health(),
    }


def _get_skills_health() -> Dict[str, Any]:
    """Get skill system health status."""
    try:
        from .skill_loader import _loader
        if _loader and _loader.loaded:
            return {
                "loaded": True,
                "count": len(_loader.skills),
                "skills": [{"name": s.name, "keywords_count": len(s.meta.trigger_keywords)} 
                          for s in _loader.skills.values()],
            }
    except Exception:
        pass
    return {"loaded": False, "count": 0, "skills": []}


# ===================================================================
# Skill & Agent API endpoints
# ===================================================================

@app.get('/skills')
async def list_skills():
    """List all loaded skills with their metadata."""
    loader = await get_skill_loader()
    return {
        "skills": loader.list_skills(),
        "total": len(loader.skills),
    }


@app.get('/skills/{skill_name}')
async def get_skill(skill_name: str):
    """Get detailed info for a specific skill."""
    loader = await get_skill_loader()
    skill = loader.get(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f'Skill not found: {skill_name}')
    return {
        "name": skill.name,
        "description": skill.meta.description,
        "argument_hint": skill.meta.argument_hint,
        "trigger_keywords": skill.meta.trigger_keywords,
        "steps": skill.steps,
        "api_refs": skill.api_refs,
        "references": skill.references,
    }


@app.post('/skills/match')
async def match_skills(payload: Dict[str, Any]):
    """Match a user query to the most relevant skills.
    
    Body: {"query": "支付延迟，帮我排查一下"}
    Returns ranked skill matches with scores.
    """
    query = payload.get('query', '')
    if not query:
        raise HTTPException(status_code=400, detail='query is required')
    
    loader = await get_skill_loader()
    matches = loader.match(query, top_k=5)
    
    return {
        "query": query,
        "matches": [
            {
                "skill_name": skill.name,
                "score": round(score, 2),
                "description": skill.meta.description[:150],
                "trigger_keywords": skill.meta.trigger_keywords[:10],
            }
            for skill, score in matches
        ],
    }


@app.get('/agents')
async def list_agents():
    """List all available agents (skill-backed and system agents)."""
    loader = await get_skill_loader()
    agents = []
    
    for agent_name, identity in AGENT_IDENTITIES.items():
        skill = loader.get(agent_name)
        agents.append({
            "agent_name": identity.agent_name,
            "display_name": identity.display_name,
            "icon": identity.icon,
            "agent_type": identity.agent_type,
            "skill_loaded": skill is not None,
            "skill_info": skill.to_dict() if skill else None,
        })
    
    return {"agents": agents, "total": len(agents)}


@app.get('/incident/{incident_id}/active-skills')
async def get_active_skills(incident_id: str):
    """Get skills that should be active for a given incident."""
    inc = await DB.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')
    
    loader = await get_skill_loader()
    active = loader.get_active_skills_for_context(inc)
    
    return {
        "incident_id": incident_id,
        "incident_status": inc.get('status', ''),
        "active_skills": [
            {
                "name": s.name,
                "description": s.meta.description[:150],
                "steps_count": len(s.steps),
            }
            for s in active
        ],
    }


# ===================================================================
# Existing endpoints (unchanged)
# ===================================================================

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

        await DB.upsert_incident({
            "incident_id": inc_id,
            "status": "Investigating",
            "summary": f"自动创建：{alert.metric} 异常",
            "related_alerts": [alert.alert_id],
            "related_changes": [],
            "affected_services": incident_services
        })
        return {"created_incident": inc_id}
    return {"status": "ingested"}


@app.post('/ingest/raw-alert')
async def ingest_raw_alert(alert: RawAlertIn):
    """
    Ingest a raw alert with minimal input (severity + source + content).
    The platform auto-derives: summary, affected systems, related alerts, related changes.

    Pipeline:
      1. Parse alert content → extract keywords
      2. Match keywords → find systems in KG + application registry
      3. Search historical postmortems for similar cases
      4. Search KG for related change nodes in time window
      5. Generate summary from content
      6. Create incident with all derived fields
    """
    content = AlarmAnalyzer.normalize_text(alert.content)
    if not content:
        raise HTTPException(status_code=400, detail='alert content is required')

    # Step 1: Extract keywords
    keywords = AlarmAnalyzer.extract_keywords(content)
    print(f"[raw-alert] Keywords extracted: {keywords[:10]}")

    # Step 2: Match to systems via KG + direct patterns (word-boundary, not substring)
    kg = _get_kg_service()
    ds = _get_data_service()

    # Build search text from content only (source is the reporting system, not necessarily affected)
    search_text = content
    matched_kg = kg.match_nodes(search_text)

    # Filter: only keep matches from our known KG node IDs
    _known_ids = {n['id'] for n in SAMPLE_KG.get('nodes', [])}
    matched_system_ids = [n.get('id') for n in matched_kg
                          if n.get('id') and n.get('id') in _known_ids]

    # Word-boundary pattern matching — only match whole codes, not substrings
    # Each pattern is (regex, node_id) — \b ensures we match "MQ" but not inside "BQREPXDEPS0"
    _SYSTEM_PATTERNS_RE = [
        (r'\bBOCS-DNF\b', 'svc-bocsdnf'), (r'\bBOCS-D\b', 'svc-bocsd'),
        (r'\bQREP\b', 'mq-bocs'), (r'\bMQ\b', 'mq-bocs'),
        (r'\bPageset\b', 'mq-bocs'), (r'\bMCIS\b', 'svc-mcis'), (r'\bCSP\b', 'svc-csp'),
        (r'\bC-DBC\b', 'svc-cdbc'), (r'\bIPPS\b', 'svc-ipps'), (r'\bRCPS-IBPS\b', 'svc-rcpsibps'),
        (r'湖南分行', 'svc-hn-branch'), (r'长沙建南', 'thirdparty-jn'), (r'第三方', 'thirdparty-jn'),
        (r'网联', 'agent-wl'), (r'\b2603\b', 'chg-2603'), (r'\bMaxTask\b', 'svc-bocsd'),
    ]
    for pattern, node_id in _SYSTEM_PATTERNS_RE:
        if re.search(pattern, search_text) and node_id not in matched_system_ids:
            matched_system_ids.append(node_id)

    # Remove change-type nodes from affected services (changes aren't services)
    matched_system_ids = [sid for sid in matched_system_ids
                          if not sid.startswith('chg-') and not sid.startswith('al-')]

    # If no systems matched, try matching source against KG
    if not matched_system_ids and alert.source:
        source_match = kg.match_nodes(alert.source)
        for n in source_match:
            if n.get('id') and n['id'] in _known_ids:
                matched_system_ids.append(n['id'])

    print(f"[raw-alert] Matched systems: {matched_system_ids}")

    # Step 3: Search historical postmortems for similar cases
    try:
        related_cases_raw = ds.search_postmortems(keywords)
    except Exception:
        related_cases_raw = []

    # Step 4: Search KG for related changes (Change-type nodes overlapping affected systems)
    related_change_ids = []
    for node in SAMPLE_KG.get('nodes', []):
        if node.get('type') == 'Change':
            # Check if change affects any matched system
            for edge in SAMPLE_KG.get('edges', []):
                if edge.get('from') == node.get('id') and edge.get('to') in matched_system_ids:
                    if node.get('id') not in related_change_ids:
                        related_change_ids.append(node.get('id'))
                if edge.get('rel') == 'affects' and edge.get('from') == node.get('id'):
                    if node.get('id') not in related_change_ids:
                        related_change_ids.append(node.get('id'))

    print(f"[raw-alert] Related changes: {related_change_ids}")

    # Step 5: Generate summary from content
    # Extract the most meaningful sentence or use LLM if available
    from .llm_client import LLMClient
    llm = LLMClient()
    if llm.provider in ("openai", "anthropic", "ollama"):
        try:
            summary_prompt = f"请用一句话（不超过40字）概括以下告警的核心问题：\n{content[:500]}"
            llm_resp = await llm.infer(summary_prompt, system="你是一个SRE运维专家，请简洁概括告警。")
            summary = llm_resp.content.strip()[:80] if llm_resp.content else content[:80]
        except Exception:
            summary = _derive_summary(content, keywords)
    else:
        summary = _derive_summary(content, keywords)

    print(f"[raw-alert] Generated summary: {summary}")

    # Step 6: Create incident
    inc_id = f"inc-{str(uuid.uuid4())[:8]}"
    now = _now_iso()

    # Build related alert IDs — find Alert nodes in KG linked to matched systems
    related_alert_ids = []
    # Self-referencing alert for this event
    self_alert_id = f"al-raw-{inc_id.split('-')[-1]}"
    related_alert_ids.append(self_alert_id)

    # Find alerts connected to matched systems via triggered_by edges
    for edge in SAMPLE_KG.get('edges', []):
        if edge.get('rel') == 'triggered_by' and edge.get('to') in matched_system_ids:
            aid = edge.get('from', '')
            if aid and aid not in related_alert_ids:
                related_alert_ids.append(aid)

    if len(related_alert_ids) > 1:
        print(f"[raw-alert] Related alerts from KG: {related_alert_ids[1:]}")

    # Determine affected services (use matched KG nodes + infer from keywords)
    affected_services = list(dict.fromkeys(matched_system_ids))  # dedup preserving order
    if not affected_services:
        # Fallback: infer from keyword hints
        if any(kw in ' '.join(keywords) for kw in ['MQ', 'QREP', 'Pageset', '堆积']):
            affected_services = ['mq-bocs', 'mq-dnf']
        elif any(kw in ' '.join(keywords) for kw in ['MCIS', 'CSP', '网银', '缴费']):
            affected_services = ['svc-mcis', 'svc-csp']

    incident = {
        "incident_id": inc_id,
        "status": "Investigating",
        "summary": summary,
        "related_alerts": related_alert_ids,
        "related_changes": related_change_ids,
        "affected_services": affected_services,
        "root_cause": "",
        "resolution_steps": [],
        "scripts_used": [],
        "created_at": now,
        "updated_at": now,
    }
    await DB.upsert_incident(incident)

    # Add initial timeline event with raw alert content
    await DB.add_timeline_event({
        "event_id": f"evt-{str(uuid.uuid4())[:8]}",
        "incident_id": inc_id,
        "event_type": "alert",
        "summary": f"原始告警: {content[:120]}",
        "actor": "system",
        "role": "system",
        "details": content,
        "sequence": 1,
        "timestamp": now,
    })

    await manager.broadcast(inc_id, {"type": "incident_created", "incident": incident})

    # Build response
    result = {
        "incident": incident,
        "derivation": {
            "keywords": keywords,
            "matched_systems": [{"id": n.get('id'), "name": n.get('name')} for n in matched_kg],
            "matched_system_ids": affected_services,
            "related_changes": related_change_ids,
            "related_cases_count": len(related_cases_raw),
            "summary_method": "llm" if llm.provider in ("openai", "anthropic", "ollama") else "rule_based",
        },
        "next_steps": [
            f"事故已自动分析，请查看时间线和诊断结果",
            f"GET /incident/{inc_id} 查看完整上下文",
            f"POST /copilot/chat 进行交互式排查",
        ],
        "pipeline_triggered": False,
    }
    
    # ── Auto-trigger analysis pipeline (async, non-blocking) ──
    try:
        pipeline_ctx = _build_pipeline_context()
        import asyncio
        asyncio.create_task(run_incident_pipeline(incident, user_id='system', app_context=pipeline_ctx))
        result["pipeline_triggered"] = True
        print(f"[raw-alert] Pipeline started (async) for {inc_id}")
    except Exception as e:
        print(f"[raw-alert] Pipeline failed (non-fatal): {e}")
        traceback.print_exc()
    
    return result


def _derive_summary(content: str, keywords: List[str]) -> str:
    """Rule-based summary generation from raw alert content."""
    kw_set = set(keywords)
    content_upper = content.upper()

    # Check content directly for technical patterns
    if ('MQ' in kw_set or 'MQ' in content_upper) and ('Pageset' in kw_set or 'PAGESET' in content_upper or 'CURRENT DEPTH' in content_upper or '堆积' in kw_set):
        return 'MQ Pageset/队列堆积告警，可能影响数据同步'
    if ('QREP' in kw_set or 'QREP' in content_upper) and ('延迟' in kw_set or '堆积' in kw_set or 'DEPTH' in content_upper):
        return 'QREP通道消息堆积，数据同步延迟超阈值'
    if kw_set & {'成功率', '下降'} and kw_set & {'MCIS', 'CSP', '网银', '缴费'}:
        return 'MCIS到分行接口成功率骤降，疑似下游服务异常'
    if kw_set & {'CPU', '使用率'}:
        return '主机CPU使用率异常升高'
    if kw_set & {'超时', '延迟', '响应'}:
        return '服务响应超时/延迟异常'
    if kw_set & {'失败率', '错误', '异常'}:
        return '服务失败率/错误率升高'
    if kw_set & {'投产', '变更', '2603'}:
        return '变更触发系统异常，需排查变更影响'

    # Fallback: extract Chinese description from content
    chinese_parts = re.findall(r'[\u4e00-\u9fff]+[^a-zA-Z0-9]*', content)
    meaningful = ''.join(chinese_parts).strip()
    if len(meaningful) > 10:
        return meaningful[:80]
    return f"告警异常: 关键词=[{', '.join(keywords[:5])}]"

@app.get('/incident/{incident_id}')
async def get_incident(incident_id: str):
    inc = await DB.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')

    # Build enriched KG context with upstream/downstream
    affected = inc.get('affected_services', [])
    changes = inc.get('related_changes', [])
    alerts = inc.get('related_alerts', [])
    
    all_ids = set(affected + changes + alerts)
    edges = _fetch_kg_edges(list(all_ids))
    
    # Discover upstream/downstream
    upstream_ids = set()
    downstream_ids = set()
    for edge in edges:
        if edge.get('to') in affected:
            upstream_ids.add(edge.get('from', ''))
        if edge.get('from') in affected:
            downstream_ids.add(edge.get('to', ''))
    
    kg_context = {
        'services': _fetch_kg_nodes(affected),
        'alerts': _fetch_kg_nodes(alerts),
        'changes': _fetch_kg_nodes(changes),
        'upstream': _fetch_kg_nodes(list(upstream_ids - all_ids)),
        'downstream': _fetch_kg_nodes(list(downstream_ids - all_ids)),
        'edges': edges,
        'dependency_summary': _build_dependency_summary(
            _fetch_kg_nodes(affected),
            _fetch_kg_nodes(list(upstream_ids - all_ids)),
            _fetch_kg_nodes(list(downstream_ids - all_ids)),
        ),
    }
    inc['kg_context'] = kg_context
    
    # Include auto-diagnosis if available
    diagnoses = await DB.list_diagnoses(incident_id)
    if diagnoses:
        inc['auto_diagnosis'] = diagnoses[0]
        inc['active_skills'] = diagnoses[0].get('active_skills', [])
        inc['primary_skill'] = diagnoses[0].get('primary_skill', None)
    
    # Include related cases
    try:
        inc['related_cases'] = await _related_cases_for_incident(incident_id, limit=5)
    except Exception:
        inc['related_cases'] = []
    
    # Include scripts
    try:
        scripts = await DB.list_scripts()
        inc['suggested_scripts'] = [s for s in scripts if s.get('incident_id') == incident_id][:6]
    except Exception:
        inc['suggested_scripts'] = []
    
    return inc


def _build_dependency_summary(services, upstream, downstream) -> str:
    parts = []
    if services:
        parts.append(f"受影响: {', '.join(s.get('name','?') for s in services)}")
    if upstream:
        parts.append(f"上游依赖({len(upstream)}): {', '.join(s.get('name','?') for s in upstream[:3])}")
    if downstream:
        parts.append(f"下游影响({len(downstream)}): {', '.join(s.get('name','?') for s in downstream[:3])}")
    return ' | '.join(parts) if parts else ''


def _build_pipeline_context() -> Dict[str, Any]:
    """Build the app_context dict for passing singletons to the pipeline."""
    return {
        '_fetch_kg_nodes': _fetch_kg_nodes,
        '_fetch_kg_edges': _fetch_kg_edges,
        '_get_kg_service': _get_kg_service,
        '_related_cases_for_incident': _related_cases_for_incident,
        '_add_timeline_event': _add_timeline_event,
        '_script_suggestions': _script_suggestions,
        '_get_user': _get_user,
        'LogAnalyzer': LogAnalyzer,
        'IncidentReasoner': IncidentReasoner,
        'enrich_diagnosis': enrich_diagnosis,
        'DB': DB,
    }

@app.get('/incident/{incident_id}/reason', response_model=ReasoningResult)
async def get_incident_reasoning(incident_id: str):
    inc = await DB.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')

    kg_context = {
        'services': _fetch_kg_nodes(inc.get('affected_services', [])),
        'alerts': _fetch_kg_nodes(inc.get('related_alerts', [])),
        'changes': _fetch_kg_nodes(inc.get('related_changes', [])),
    }

    reasoning = await IncidentReasoner.infer_root_causes(inc, kg_context)
    reasoning['kg_context'] = kg_context
    return reasoning

@app.get('/incidents')
async def list_incidents():
    incidents = await DB.list_incidents()
    summary = {
        'total': len(incidents),
        'open': len([i for i in incidents if i['status'] != 'Resolved']),
        'resolved': len([i for i in incidents if i['status'] == 'Resolved']),
        'services': list({svc for inc in incidents for svc in inc.get('affected_services', [])})
    }
    return {'incidents': incidents, 'summary': summary}

@app.post('/incidents')
async def create_incident(payload: IncidentCreateIn):
    """Create a new incident manually (simulate a new case)."""
    inc_id = f"inc-{str(uuid.uuid4())[:8]}"
    now = _now_iso()
    incident = {
        "incident_id": inc_id,
        "status": payload.status,
        "summary": payload.summary,
        "related_alerts": payload.alert_ids,
        "related_changes": payload.change_ids,
        "affected_services": payload.affected_services,
        "root_cause": payload.root_cause,
        "resolution_steps": [],
        "scripts_used": [],
        "created_at": now,
        "updated_at": now,
    }
    await DB.upsert_incident(incident)
    # Add initial timeline event
    await DB.add_timeline_event({
        "event_id": f"evt-{str(uuid.uuid4())[:8]}",
        "incident_id": inc_id,
        "event_type": "alert",
        "summary": f"新故障: {payload.summary[:60]}",
        "actor": "system",
        "role": "system",
        "details": payload.alert_description or f"手动创建故障，来源: {payload.source}, 严重级别: {payload.severity}",
        "sequence": 1,
        "timestamp": now,
    })
    print(f"[incident] Created new incident: {inc_id} — {payload.summary[:50]}")
    
    # ── Auto-trigger analysis pipeline (async, non-blocking) ──
    try:
        pipeline_ctx = _build_pipeline_context()
        import asyncio
        asyncio.create_task(run_incident_pipeline(incident, user_id='system', app_context=pipeline_ctx))
        print(f"[incident] Pipeline started (async) for {inc_id}")
    except Exception as e:
        print(f"[incident] Pipeline failed (non-fatal): {e}")
        traceback.print_exc()
    
    # Broadcast via WebSocket
    await manager.broadcast(inc_id, {"type": "incident_created", "incident": incident})
    return incident

@app.post('/incidents/simulate')
async def simulate_incident(payload: IncidentSimulateIn):
    """Quick-simulate a new incident from preset templates.
    
    Templates only contain raw alert content + severity — summary, affected_services,
    related_alerts, and related_changes are ALL derived by the platform.
    """
    templates: Dict[str, Dict[str, Any]] = {
        "db_timeout": {
            "severity": 4,
            "source": "BPPM监控",
            "content": "核心银行系统BOCS-D数据库连接池耗尽，连接等待超时超过30s，99分位延迟飙升至5.8s，影响对公交易处理。",
        },
        "cpu_spike": {
            "severity": 4,
            "source": "BPPM监控",
            "content": "北京黑山扈信创3主机CPU使用率飙升至99%，igtb-srv-cds微服务P99延迟从200ms升至3.2s，疑似GC风暴或死循环。",
        },
        "mq_backlog": {
            "severity": 3,
            "source": "系统平台一部",
            "content": "BOCS-D到BOCS-DNF的QREP通道堆积消息达12万条，消费速率降至正常1/10，DNF侧数据同步延迟超40分钟。MQ Pageset使用率持续上升。",
        },
        "network_flap": {
            "severity": 3,
            "source": "网络监控",
            "content": "MCIS调用CSP分行特色平台接口超时率从0.5%升至18%，网络探测显示内蒙云到分行链路存在间歇性丢包。",
        },
        "bocs_dnf_sync_delay": {
            "severity": 4,
            "source": "系统平台一部",
            "content": "【SA-BPPM】MQ: MAR 31 04:15:44 BQREPXDEPS0 SEV=WAR QPS1 NamedQueue: QR.XMITQ1.QPS1.TO.QMA CURRENT DEPTH: 2197878 (CurrentDepth >= 2000000)。04:29 MQ Pageset使用率52.96%。04:37 Pageset使用率76.49%触发一级告警。2603批次投产后D+2日首次历史数据清理，单日清理25亿数据（QREP下刷5亿），远超QREP日常吞吐能力（~1亿/小时），导致MQ Pageset空间持续无法释放，数据下刷延迟无法在7:00前追平，影响DNF交易回切。9:56-9:58切换期间主机出现MaxTask，C-DBC/IPPS/RCPS-IBPS交易成功率分别降至98.19%/96.93%/90.5%。",
        },
        "mcis_branch_thirdparty": {
            "severity": 3,
            "source": "应用维护一部",
            "content": "MCIS-CHL-XC-HY_MERCH--MCIS-CHL--CSPS0119--E10902，分行网银缴费(湖南)网银自助缴费交易成功率连续3个采样点＜0.7（实际45.5%），交易量连续3个点＞10。异常时段（7:42-8:01，19分钟）MCIS调用湖南分行接口710笔仅成功323笔，成功率45.5%。历史同时段成功率均100%。8:01自动恢复。湖南分行反馈定位为第三方单位长沙建南电子行业卡系统加密解密服务模块软件故障。",
        },
    }

    scenario = payload.scenario or "db_timeout"
    template = templates.get(scenario, templates["db_timeout"])

    # Use the raw alert pipeline: only severity + source + content as input
    raw_input = RawAlertIn(
        severity=payload.severity or template["severity"],
        source=template["source"],
        content=template["content"],
    )

    result = await ingest_raw_alert(raw_input)
    result["scenario"] = scenario
    return result

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
        return await _incident_graph(incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.get('/kg/incident/{incident_id}/related')
async def kg_related_incidents(incident_id: str):
    try:
        return {"incident_id": incident_id, "related_incidents": await _related_incidents(incident_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.get('/kg/subgraph')
async def kg_subgraph(node_id: str, depth: int = 1):
    return _subgraph(node_id, depth)

@app.get('/kg/history')
async def kg_history(service_id: str = '', alert_id: str = '', change_id: str = ''):
    if not (service_id or alert_id or change_id):
        raise HTTPException(status_code=400, detail='请提供 service_id、alert_id 或 change_id 之一')
    return {'query': {'service_id': service_id, 'alert_id': alert_id, 'change_id': change_id},
        'incidents': await _history_incidents(service_id=service_id, alert_id=alert_id, change_id=change_id)}

@app.get('/data/summary')
async def get_data_summary():
    return _get_data_service().summary()

@app.post('/data/reload')
async def reload_data():
    ds = _get_data_service()
    summary = ds.reload()
    global KG_SERVICE
    KG_SERVICE = KnowledgeGraph(ds.system_relations, ds.application_registry)
    return {'status': 'reloaded', 'summary': summary}

@app.get('/alarm/{alarm_id}')
async def get_alarm_record(alarm_id: str):
    alarm = _get_data_service().get_alarm_by_id(alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail='alarm not found')
    return alarm

@app.get('/alarm/{alarm_id}/match')
async def get_alarm_match(alarm_id: str):
    alarm = _get_data_service().get_alarm_by_id(alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail='alarm not found')
    return AlarmAnalyzer.match_alarm_to_systems(alarm, _get_data_service(), _get_kg_service())

@app.get('/alarm/{alarm_id}/impact')
async def get_alarm_impact(alarm_id: str, depth: int = 2):
    alarm = _get_data_service().get_alarm_by_id(alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail='alarm not found')
    match_info = AlarmAnalyzer.match_alarm_to_systems(alarm, _get_data_service(), _get_kg_service())
    return _get_kg_service().impact_scope(match_info.get('system_ids', []), max_hops=depth)

@app.get('/diagnosis/alarm/{alarm_id}')
async def diagnose_alarm(alarm_id: str, depth: int = 2):
    try:
        return FaultDiagnosisService.diagnose_alarm(alarm_id, _get_data_service(), _get_kg_service(), depth)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get('/auth/users')
async def list_users():
    return {'users': list(USERS.values())}

@app.get('/auth/me')
async def get_current_user(user_id: str = 'ui-user'):
    return _get_user(user_id)

@app.get('/incident/{incident_id}/timeline')
async def incident_timeline(incident_id: str):
    if not await DB.get_incident(incident_id):
        raise HTTPException(status_code=404, detail='incident not found')
    return {'incident_id': incident_id, 'timeline': await _incident_timeline(incident_id)}

@app.post('/incident/{incident_id}/timeline')
async def add_timeline_event(incident_id: str, event: TimelineEventIn):
    if not await DB.get_incident(incident_id):
        raise HTTPException(status_code=404, detail='incident not found')
    actor = event.actor or 'ui-user'
    _check_permission(actor, 'add_timeline')
    return await _add_timeline_event(incident_id, event.event_type, event.summary, actor, USERS[actor]['role'], event.details)

@app.get('/incident/{incident_id}/collaboration')
async def incident_collaboration(incident_id: str):
    if not await DB.get_incident(incident_id):
        raise HTTPException(status_code=404, detail='incident not found')
    return {'incident_id': incident_id, 'comments': await _incident_comments(incident_id)}

@app.post('/incident/{incident_id}/collaboration')
async def add_collaboration_comment(incident_id: str, payload: Dict[str, Any]):
    if not await DB.get_incident(incident_id):
        raise HTTPException(status_code=404, detail='incident not found')
    author = payload.get('author', 'ui-user')
    message = payload.get('message', '')
    if not message:
        raise HTTPException(status_code=400, detail='message is required')
    _check_permission(author, 'add_comment')
    return await _record_collaboration_comment(incident_id, author, message)

@app.get('/actions')
async def list_actions():
    return {"actions": SAMPLE_ACTIONS}

@app.get('/incident/{incident_id}/actions')
async def incident_actions(incident_id: str):
    if not await DB.get_incident(incident_id):
        raise HTTPException(status_code=404, detail='incident not found')
    return {"incident_id": incident_id, "actions": SAMPLE_ACTIONS}

@app.get('/action/logs')
async def action_logs():
    return {"logs": await DB.list_action_logs()}

# ---- Async diagnosis task store ----
_pending_diagnoses: Dict[str, Dict[str, Any]] = {}

@app.post('/copilot/diagnose')
async def copilot_diagnose(req: CopilotDiagnoseIn):
    """Start async diagnosis. Returns immediately with task_id; poll GET /copilot/diagnose/{task_id} for result."""
    _check_permission(req.user_id, 'add_comment')
    inc = await DB.get_incident(req.incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')
    
    diagnosis_id = f'diag-{str(uuid.uuid4())[:8]}'
    task = {
        'diagnosis_id': diagnosis_id,
        'incident_id': req.incident_id,
        'status': 'queued',
        'progress': 0,
        'step': '初始化诊断任务...',
        'started_at': _now_iso(),
        'result': None,
        'error': None,
    }
    _pending_diagnoses[diagnosis_id] = task
    
    # Cleanup old tasks (>10 min)
    now_ts = datetime.datetime.utcnow()
    stale = []
    for k, v in _pending_diagnoses.items():
        if v['status'] in ('completed', 'failed'):
            try:
                started = datetime.datetime.fromisoformat(v.get('started_at', '2000-01-01T00:00:00Z').replace('Z', '+00:00'))
                if (now_ts - started.replace(tzinfo=None)).total_seconds() > 600:
                    stale.append(k)
            except Exception:
                pass
    for k in stale:
        del _pending_diagnoses[k]
    
    # Fire background task (non-blocking)
    import asyncio
    asyncio.create_task(_run_diagnose_background(diagnosis_id, req.incident_id, req.user_id, inc))
    
    return {
        'diagnosis_id': diagnosis_id,
        'status': 'queued',
        'message': '诊断任务已提交，请轮询 GET /copilot/diagnose/{diagnosis_id} 获取结果',
    }

@app.get('/copilot/diagnose/{diagnosis_id}')
async def poll_diagnose_result(diagnosis_id: str):
    """Poll for async diagnosis result."""
    task = _pending_diagnoses.get(diagnosis_id)
    if not task:
        # Check if already persisted
        diag = await DB.get_diagnosis(diagnosis_id)
        if diag:
            return {'diagnosis_id': diagnosis_id, 'status': 'completed', 'result': diag}
        raise HTTPException(status_code=404, detail='diagnosis task not found')
    
    return {
        'diagnosis_id': diagnosis_id,
        'status': task['status'],
        'progress': task['progress'],
        'step': task['step'],
        'result': task['result'] if task['status'] == 'completed' else None,
        'error': task.get('error'),
    }


async def _execute_diagnosis_sync(incident_id: str, user_id: str, inc: Dict[str, Any]) -> Dict[str, Any]:
    """Core diagnosis logic — used by both async API and chat endpoint."""
    diagnosis_id = f'diag-{str(uuid.uuid4())[:8]}'
    import asyncio
    
    orch = await get_orchestrator()
    
    # Parallel: skill routing + related cases
    async def _route_skills():
        return await orch._router.route(user_message=inc.get('summary', '故障诊断'), incident=inc)
    async def _fetch_cases():
        return await _related_cases_for_incident(incident_id)
    
    route_task = asyncio.create_task(_route_skills())
    cases_task = asyncio.create_task(_fetch_cases())
    
    kg_context = {
        'services': _fetch_kg_nodes(inc.get('affected_services', [])),
        'alerts': _fetch_kg_nodes(inc.get('related_alerts', [])),
        'changes': _fetch_kg_nodes(inc.get('related_changes', [])),
    }
    try:
        kg = _get_kg_service()
        affected = inc.get('affected_services', [])
        if affected:
            kg_context['kg_impact'] = kg.impact_scope(affected, max_hops=1)
    except Exception:
        pass
    
    log_analysis = await LogAnalyzer.analyze(inc)
    kg_context = LogAnalyzer.inject_into_kg_context(kg_context, log_analysis)
    
    route_result = await route_task
    cases = await cases_task
    active_skill_names = [s.name for s in route_result.active_skills]
    
    reasoning = await IncidentReasoner.infer_root_causes(inc, kg_context)
    
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
        'incident_id': incident_id,
        'kg_context': kg_context,
        'log_analysis': log_analysis,
        'candidate_root_causes': candidates,
        'reasoning_steps': reasoning.get('reasoning_steps', []),
        'evidence': reasoning.get('evidence', []),
        'confidence_summary': reasoning.get('confidence_summary', 0),
        'initial_recommendations': _build_recommendations(inc, reasoning),
        'diagnostic_session_started': True,
        'created_at': _now_iso(),
        'created_by': user_id,
        'method': reasoning.get('method', 'rule_based'),
        'active_skills': active_skill_names,
        'primary_skill': route_result.intent.primary_skill.name if route_result.intent.primary_skill else None,
        'skill_suggestions': [
            {"skill": s.name, "step": s.steps[0]['title'] if s.steps else ''}
            for s in route_result.active_skills[:3]
        ],
    }
    
    diagnosis = enrich_diagnosis(diagnosis, log_analysis=log_analysis, kg_context=kg_context)
    await DB.upsert_diagnosis(diagnosis)
    await _script_suggestions(incident_id, diagnosis_id)
    await _add_timeline_event(incident_id, 'diagnosis',
        f'Copilot 诊断会话 {diagnosis_id} 已生成', user_id, _get_user(user_id)['role'])
    
    orch._add_timeline(
        AGENT_IDENTITIES.get(route_result.intent.primary_skill.name if route_result.intent.primary_skill else 'copilot',
                            AGENT_IDENTITIES['copilot']),
        'analyze',
        f'诊断会话 {diagnosis_id} 启动，激活技能: {", ".join(active_skill_names)}',
        {'diagnosis_id': diagnosis_id, 'incident_id': incident_id}
    )
    
    return diagnosis


async def _run_diagnose_background(diagnosis_id: str, incident_id: str, user_id: str, inc: Dict[str, Any]):
    """Background task wrapper: calls the shared diagnosis logic with progress updates."""
    task = _pending_diagnoses.get(diagnosis_id)
    if not task:
        return
    
    try:
        task['status'] = 'running'
        task['progress'] = 5
        task['step'] = '正在并行加载技能路由和知识图谱...'
        
        # Run the shared sync diagnosis (which internally parallelizes steps)
        result = await _execute_diagnosis_sync(incident_id, user_id, inc)
        # Override the auto-generated diagnosis_id with our pre-assigned one
        result['diagnosis_id'] = diagnosis_id
        
        task['status'] = 'completed'
        task['progress'] = 100
        task['step'] = '诊断完成'
        task['result'] = result
        
    except Exception as e:
        print(f"[Diagnose-BG] Error for {diagnosis_id}: {e}")
        import traceback
        traceback.print_exc()
        task['status'] = 'failed'
        task['error'] = str(e)
        task['step'] = f'诊断失败: {str(e)[:100]}'

@app.post('/copilot/chat')
async def copilot_chat(req: CopilotChatIn):
    _check_permission(req.user_id, 'add_comment')
    inc = await DB.get_incident(req.incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')
    if not req.message.strip():
        raise HTTPException(status_code=400, detail='message is required')

    diagnosis = await DB.get_diagnosis(req.diagnosis_id or '') if req.diagnosis_id else None
    if not diagnosis:
        # Run synchronous diagnosis for chat context (needs full result immediately)
        diagnosis = await _execute_diagnosis_sync(req.incident_id, req.user_id, inc)

    # ── Skill System Integration: route user message to skills ──
    orch = await get_orchestrator()
    orch_result = await orch.process_request(
        user_message=req.message,
        user_id=req.user_id,
        incident=inc,
        diagnosis=diagnosis,
        conversation_history=diagnosis.get('conversation_history', []),
    )
    
    # Inject skill context into the diagnosis for Copilot to use
    diagnosis['_skill_context'] = {
        'active_skills': [s.name for s in orch_result.route_result.active_skills],
        'primary_skill': orch_result.primary_skill_name,
        'active_agents': orch_result.active_agents,
        'route_intent': orch_result.route_result.intent.intent,
    }

    # P0-2: Sync discussion context into Copilot before inference
    sync_result = await sync_discussion_to_copilot(
        incident_id=req.incident_id,
        diagnosis=diagnosis,
        add_timeline_fn=_add_timeline_event,
    )
    if sync_result.evidence_found:
        print(f"[Copilot Chat] Discussion sync: {sync_result.summary}")

    # P1-1: Load InvestigationState for excluded/verified awareness
    try:
        inv_state = await InvestigationState.get(req.incident_id)
        diagnosis['_investigation_state'] = inv_state
    except Exception:
        diagnosis['_investigation_state'] = {"verified": [], "to_verify": [], "high_risk": [], "excluded": []}

    # A4: Stateful multi-turn Copilot chat — now Skill-driven
    copilot_result = await Copilot.chat(
        diagnosis=diagnosis,
        user_id=req.user_id,
        user_message=req.message,
        action_logs=await DB.list_action_logs(),
        skill_context=diagnosis.get('_skill_context'),
        skill_system_prompt=orch_result.system_prompt,
    )

    # Refresh scripts after conversation (root causes may have changed)
    await _script_suggestions(req.incident_id, diagnosis.get('diagnosis_id'))

    # ── Skill-enriched response ──
    message = {
        'message_id': f'cp-{str(uuid.uuid4())[:8]}',
        'incident_id': req.incident_id,
        'diagnosis_id': diagnosis.get('diagnosis_id'),
        'user_message': req.message,
        'response': copilot_result.get('response', ''),
        'suggested_actions': copilot_result.get('suggested_actions', []),
        'follow_up_question': copilot_result.get('follow_up_question', ''),
        'confidence_trend': copilot_result.get('confidence_trend', 'stable'),
        'key_findings': copilot_result.get('key_findings', []),
        'method': copilot_result.get('method', 'rule_based'),
        'created_at': _now_iso(),
        'user_id': req.user_id,
        # Skill context
        'active_skills': [s.name for s in orch_result.route_result.active_skills],
        'primary_skill': orch_result.primary_skill_name,
        'active_agents': orch_result.active_agents,
        'next_steps': orch_result.route_result.next_steps[:5],
        'next_skill_suggestion': copilot_result.get('next_skill_suggestion', ''),
        'agent_timeline': [
            {'agent': e.agent.display_name, 'action': e.action, 'summary': e.summary}
            for e in orch_result.timeline
        ],
        # P0-2: Discussion sync evidence
        'discussion_evidence': diagnosis.get('_discussion_evidence', []),
        'discussion_sync_summary': sync_result.summary,
    }
    await DB.add_discussion(message)

    # Record user message in discussion
    await _record_collaboration_comment(req.incident_id, req.user_id, req.message)

    # Record Copilot response in discussion
    copilot_msg = copilot_result.get('response', '')
    if copilot_msg:
        await DB.add_discussion({
            'comment_id': f'cmt-{str(uuid.uuid4())[:8]}',
            'incident_id': req.incident_id,
            'author': 'copilot',
            'role': 'copilot',
            'message': copilot_msg,
            'message_type': 'copilot_analysis',
            'diagnosis_id': diagnosis.get('diagnosis_id'),
            'suggested_actions': copilot_result.get('suggested_actions', []),
            'created_at': _now_iso(),
        })

    return message

@app.get('/script/suggest')
async def suggest_scripts(incident_id: str, diagnosis_id: str = ''):
    try:
        return {'incident_id': incident_id, 'diagnosis_id': diagnosis_id, 'suggestions': await _script_suggestions(incident_id, diagnosis_id or None)}
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.post('/script/verify')
async def verify_script(req: ScriptVerifyIn):
    script = await DB.get_script(req.script_id or '')
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
    script = await DB.get_script(req.script_id)
    if not script:
        raise HTTPException(status_code=404, detail='script not found')
    _check_permission(req.requested_by, 'execute_action')
    if script.get('approval_required') and not req.request_id:
        raise HTTPException(status_code=403, detail='script requires approval request_id')
    incident_id = req.incident_id or script.get('incident_id')
    incident = await DB.get_incident(incident_id) if incident_id else None
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
    await DB.add_action_log({
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
        await _add_timeline_event(
            incident_id,
            'action_result',
            f"执行 {script.get('name')} 并形成观察结论",
            req.requested_by,
            _get_user(req.requested_by)['role'],
            f"{result['conclusion']} 下一步：{result['next_suggestion']}"
        )
    if req.feed_to_copilot and incident_id:
        await _append_copilot_execution_feedback(incident_id, result['diagnosis_id'], result)
        result['fed_to_copilot'] = True
        # ── Pipeline: update diagnosis based on execution results ──
        try:
            pipeline_ctx = _build_pipeline_context()
            await on_script_executed(
                incident_id, result, result.get('diagnosis_id'),
                app_context=pipeline_ctx,
            )
        except Exception as e:
            print(f"[script] Diagnosis update failed (non-fatal): {e}")
    if req.lifecycle_type == 'permanent':
        script['knowledge_asset'] = True
    return result

@app.get('/script/{script_id}')
async def get_script(script_id: str):
    script = await DB.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail='script not found')
    history = [log for log in await DB.list_action_logs() if log.get('action_id') == script_id]
    return {**script, 'execution_history': history}

@app.get('/incident/{incident_id}/discussion')
async def get_discussion(incident_id: str, message_type: str = ''):
    if not await DB.get_incident(incident_id):
        raise HTTPException(status_code=404, detail='incident not found')
    comments = await _incident_comments(incident_id)
    if message_type:
        comments = [msg for msg in comments if msg.get('message_type') == message_type]
    return {'incident_id': incident_id, 'messages': comments}

@app.post('/incident/{incident_id}/discussion')
async def add_discussion(incident_id: str, payload: DiscussionIn):
    if not await DB.get_incident(incident_id):
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
    await DB.add_discussion(comment)
    if payload.message_type in ('decision', 'conclusion', 'handoff'):
        await _add_timeline_event(incident_id, payload.message_type, f'记录{payload.message_type}：{payload.message[:40]}', payload.author, user['role'], payload.message)
    
    # Auto-sync discussion evidence to Copilot context
    try:
        diagnoses = await DB.list_diagnoses(incident_id)
        if diagnoses:
            sync_result = await sync_discussion_to_copilot(
                incident_id=incident_id,
                diagnosis=diagnoses[0],
                add_timeline_fn=_add_timeline_event,
            )
            if sync_result.evidence_found:
                comment['_discussion_evidence'] = [
                    {'type': e.evidence_type, 'summary': e.summary, 'confidence': e.confidence,
                     'author_role': e.author_role, 'source_message': e.source_message[:100]}
                    for e in sync_result.evidence_list
                ]
                print(f"[discussion] Evidence extracted: {sync_result.summary}")
    except Exception as e:
        print(f"[discussion] Evidence sync skipped (non-fatal): {e}")
    
    return comment

@app.post('/incident/{incident_id}/postmortem')
async def create_postmortem(incident_id: str, payload: PostmortemIn):
    try:
        target_id = payload.incident_id or incident_id
        print(f"[postmortem] Generating with Agent for incident={target_id}")
        
        # Use the postmortem agent for structured report generation
        pipeline_ctx = _build_pipeline_context()
        report = await run_postmortem_agent(target_id, payload.requested_by, app_context=pipeline_ctx)
        print(f"[postmortem] Agent report generated: {report.get('postmortem_id')}")
        
        # Auto-distill knowledge assets from postmortem
        knowledge = None
        dedup_result = None
        aggregation_result = None
        skill_update_result = None
        
        try:
            # Step A: Distill knowledge from postmortem
            knowledge = await KnowledgeDistiller.distill(report)
            knowledge["distilled_at"] = _now_iso()
            knowledge["agent_name"] = "postmortem-generator"
            print(f"[postmortem] Knowledge distilled: {knowledge.get('knowledge_id', 'N/A')}")
            
            # Step B: Semantic dedup + high-frequency detection
            try:
                dedup_result = await deduplicate_knowledge(knowledge, target_id)
                knowledge = dedup_result  # updated with _dedup_summary, _dedup_details, merged assets
                print(f"[postmortem] Dedup complete: merged={dedup_result.get('_dedup_summary', {}).get('merged', 0)}, "
                      f"new={dedup_result.get('_dedup_summary', {}).get('new_entries', 0)}, "
                      f"high_freq_patterns={len(dedup_result.get('_dedup_summary', {}).get('high_frequency_patterns', []))}")
            except Exception as e:
                print(f"[postmortem] Dedup skipped (non-fatal): {e}")
            
            # Step C: Persist deduplicated knowledge
            await DB.upsert_knowledge(knowledge)
            
            # Step D: If high-frequency patterns detected, run aggregation + skill update
            high_freq = knowledge.get('_dedup_summary', {}).get('high_frequency_patterns', [])
            if high_freq:
                try:
                    aggregation_result = await run_pattern_aggregation()
                    print(f"[postmortem] Pattern aggregation: {len(aggregation_result)} patterns refined")
                except Exception as e:
                    print(f"[postmortem] Pattern aggregation skipped (non-fatal): {e}")
                
                try:
                    skill_update_result = await update_all_mature_patterns()
                    print(f"[postmortem] Skill update: {len(skill_update_result)} ref files updated")
                except Exception as e:
                    print(f"[postmortem] Skill update skipped (non-fatal): {e}")
            
            report["knowledge"] = knowledge
            report["_pipeline_extras"] = {
                "dedup_summary": knowledge.get('_dedup_summary'),
                "aggregation_count": len(aggregation_result) if aggregation_result else 0,
                "skill_updates": skill_update_result,
            }
        except Exception as e:
            print(f"[postmortem] Knowledge distillation skipped: {e}")
            report["knowledge"] = {"status": "skipped", "reason": str(e)}
        
        return report
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')
    except Exception as e:
        print(f"[postmortem] ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'postmortem generation failed: {e}')

@app.get('/postmortem/{postmortem_id}/knowledge')
async def get_postmortem_knowledge(postmortem_id: str):
    knowledge = await DB.get_knowledge(postmortem_id)
    if not knowledge:
        # Try to distill on-demand if not yet done
        report = await DB.get_postmortem(postmortem_id)
        if not report:
            raise HTTPException(status_code=404, detail='postmortem not found')
        knowledge = await KnowledgeDistiller.distill(report)
        knowledge["distilled_at"] = _now_iso()
        await DB.upsert_knowledge(knowledge)
    return knowledge

@app.get('/postmortem/{postmortem_id}')
async def get_postmortem(postmortem_id: str):
    report = await DB.get_postmortem(postmortem_id)
    if not report:
        raise HTTPException(status_code=404, detail='postmortem not found')
    return report

@app.post('/postmortem/{postmortem_id}/approve')
async def approve_postmortem(postmortem_id: str, payload: PostmortemApprovalIn):
    report = await DB.get_postmortem(postmortem_id)
    if not report:
        raise HTTPException(status_code=404, detail='postmortem not found')
    _check_permission(payload.approver, 'approve_request')
    report['status'] = 'published'
    report['approved_by'] = payload.approver
    report['approved_at'] = _now_iso()
    report['published_scripts'] = payload.publish_scripts
    report['improvement_tasks_created'] = payload.create_improvement_tasks
    for script_id in payload.publish_scripts:
        s = await DB.get_script(script_id)
        if s:
            s['knowledge_asset'] = True
            await DB.upsert_script(s)
    return report

@app.get('/incident/{incident_id}/related-cases')
async def related_cases(incident_id: str, limit: int = 5):
    try:
        return {'incident_id': incident_id, 'cases': await _related_cases_for_incident(incident_id, limit)}
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.get('/incident/{incident_id}/knowledge-assets')
async def knowledge_assets(incident_id: str):
    inc = await DB.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail='incident not found')
    assets = []
    for action in SAMPLE_ACTIONS:
        # Derive reliability from action metadata
        verification_count = action.get('execution_count', 0)
        false_positive_count = action.get('false_positive_count', 0)
        reliability = _compute_reliability(verification_count, false_positive_count)
        assets.append({
            'asset_id': action['action_id'],
            'type': 'action_template',
            'title': action.get('name'),
            'description': action.get('description'),
            'relevance': 0.75 if not action.get('requires_approval') else 0.58,
            'reliability': reliability['label'],
            'reliability_detail': reliability,
        })
    for script in await DB.list_scripts():
        if script.get('knowledge_asset') or script.get('diagnosis_id'):
            exec_count = script.get('execution_count', 0) or (2 if script.get('category') == 'approved' else 0)
            fp_count = script.get('false_positive_count', 0)
            reliability = _compute_reliability(exec_count, fp_count)
            assets.append({
                'asset_id': script['script_id'],
                'type': 'script',
                'title': script.get('name'),
                'description': script.get('explanation'),
                'relevance': script.get('confidence', 0.5),
                'reliability': reliability['label'],
                'reliability_detail': reliability,
            })
    # Also include knowledge assets from distilled postmortems
    try:
        all_knowledge = await DB.list_knowledge()
        for kn in all_knowledge[:3]:
            for rule in kn.get('root_cause_rules', [])[:2]:
                assets.append({
                    'asset_id': rule.get('rule_id', ''),
                    'type': 'root_cause_rule',
                    'title': rule.get('pattern', '')[:60],
                    'description': f"Category: {rule.get('category','')} | Confidence: {rule.get('confidence',0)}",
                    'relevance': rule.get('confidence', 0.5),
                    'reliability': 'VERIFIED' if rule.get('confidence', 0) > 0.7 else 'UNVERIFIED',
                    'reliability_detail': {'verification_count': len(rule.get('source_incidents', [])), 'false_positive_count': 0, 'weight': rule.get('confidence', 0.5)},
                })
    except Exception:
        pass
    return {'incident_id': incident_id, 'assets': sorted(assets, key=lambda item: item['relevance'], reverse=True)}

def _compute_reliability(verification_count: int, false_positive_count: int) -> dict:
    """Compute reliability label based on verification/false-positive history."""
    total = verification_count + false_positive_count
    if total == 0:
        return {'label': 'UNVERIFIED', 'weight': 0.5, 'verification_count': 0, 'false_positive_count': 0}
    weight = verification_count / max(total, 1)
    if verification_count >= 5 and weight >= 0.85:
        return {'label': 'RELIABLE', 'weight': round(weight, 2), 'verification_count': verification_count, 'false_positive_count': false_positive_count}
    elif false_positive_count >= 3 and weight < 0.5:
        return {'label': 'DEGRADED', 'weight': round(weight, 2), 'verification_count': verification_count, 'false_positive_count': false_positive_count}
    else:
        return {'label': 'VERIFIED' if weight >= 0.7 else 'UNVERIFIED', 'weight': round(weight, 2), 'verification_count': verification_count, 'false_positive_count': false_positive_count}
    return {'incident_id': incident_id, 'assets': sorted(assets, key=lambda item: item['relevance'], reverse=True)}

# ---- Knowledge Lifecycle: High-Frequency Patterns & Skill Updates ----

@app.get('/knowledge/high-frequency-patterns')
async def get_high_frequency_patterns():
    """List all detected high-frequency patterns from the knowledge base."""
    try:
        patterns = await find_high_frequency_patterns()
        return {
            'patterns': patterns,
            'total': len(patterns),
            'threshold': int(os.environ.get('KNOWLEDGE_HIGH_FREQ_THRESHOLD', '5')),
        }
    except Exception as e:
        print(f"[knowledge] Failed to scan high-frequency patterns: {e}")
        raise HTTPException(status_code=500, detail=f'pattern scan failed: {e}')

@app.get('/knowledge/skill-update-log')
async def get_skill_update_log():
    """Get the status of skill reference files and auto-remediation skills."""
    skill_base = os.path.abspath(os.path.join(HERE, '..', 'skill'))
    ref_files = {}
    for root, dirs, files in os.walk(skill_base):
        for f in files:
            if f.endswith('.md') and ('solution-practices' in f or 'sop-library' in f 
                                       or 'warning-signals' in f or 'script-library' in f
                                       or 'error-patterns' in f or 'runbooks' in root):
                rel = os.path.relpath(os.path.join(root, f), skill_base)
                try:
                    size = os.path.getsize(os.path.join(root, f))
                    ref_files[rel] = {'size_bytes': size, 'has_content': size > 50}
                except Exception:
                    ref_files[rel] = {'size_bytes': 0, 'has_content': False}
    
    # Find auto-generated skills
    auto_skills = []
    for d in os.listdir(skill_base) if os.path.isdir(skill_base) else []:
        full = os.path.join(skill_base, d)
        if os.path.isdir(full):
            skill_md = os.path.join(full, 'SKILL.md')
            if os.path.exists(skill_md):
                content = open(skill_md, 'r', encoding='utf-8').read()
                if '自动处置' in content or 'auto-remediation' in d.lower() or 'auto-' in d.lower():
                    auto_skills.append({'name': d, 'type': 'auto-remediation'})
    
    return {
        'ref_files': ref_files,
        'auto_remediation_skills': auto_skills,
        'skill_base_path': skill_base,
    }

@app.post('/knowledge/run-aggregation')
async def trigger_aggregation():
    """Manually trigger pattern aggregation + skill reference update."""
    try:
        patterns = await find_high_frequency_patterns()
        if not patterns:
            return {'status': 'no_patterns', 'message': 'No high-frequency patterns detected yet'}
        
        refined = await run_pattern_aggregation(patterns)
        updates = await update_all_mature_patterns()
        
        return {
            'status': 'completed',
            'patterns_found': len(patterns),
            'patterns_refined': len(refined),
            'skill_updates': len(updates),
            'details': {
                'patterns': [p.get('pattern_key', '') for p in patterns],
                'updates': updates,
            },
        }
    except Exception as e:
        print(f"[knowledge] Aggregation failed: {e}")
        raise HTTPException(status_code=500, detail=f'aggregation failed: {e}')

# ---- B5: Investigation State Machine ----
@app.get('/incident/{incident_id}/investigation-state')
async def get_investigation_state(incident_id: str):
    try:
        return await InvestigationState.get(incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.post('/incident/{incident_id}/investigation-state')
async def update_investigation_state(incident_id: str, payload: InvestigationStateIn):
    try:
        return await InvestigationState.update(incident_id, payload.dict(exclude_none=True))
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.post('/incident/{incident_id}/investigation-state/item')
async def add_investigation_item(incident_id: str, payload: InvestigationItemIn):
    if payload.quadrant not in ('verified', 'to_verify', 'high_risk', 'excluded'):
        raise HTTPException(status_code=400, detail='Invalid quadrant')
    try:
        return await InvestigationState.add_item(incident_id, payload.quadrant, payload.item)
    except KeyError:
        raise HTTPException(status_code=404, detail='incident not found')

@app.post('/incident/{incident_id}/investigation-state/move')
async def move_investigation_item(incident_id: str, payload: InvestigationMoveIn):
    try:
        return await InvestigationState.move_item(
            incident_id, payload.item_name, payload.from_quadrant, payload.to_quadrant
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404 if isinstance(e, KeyError) else 400, detail=str(e))

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
        request = await DB.get_action_request(req.request_id)
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
    await DB.add_action_log(result)
    incident_id_val = request['incident_id'] if req.request_id else (req.incident_id or '')
    if incident_id_val:
        await _add_timeline_event(incident_id_val, 'action_execution', f'执行动作 {req.action_id}', req.requested_by, _get_user(req.requested_by)['role'], result['output'])
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
    await DB.upsert_action_request(request)
    await _record_action_request(req.incident_id, request_id, req.action_id, req.requested_by)
    return request

@app.get('/action/requests')
async def list_action_requests():
    return {'requests': await DB.list_action_requests()}

@app.post('/action/approve')
async def approve_action_request(req: ActionApprovalIn):
    request = await DB.get_action_request(req.request_id)
    if not request:
        raise HTTPException(status_code=404, detail='request not found')
    _check_permission(req.approver, 'approve_request')
    request['status'] = 'approved' if req.approved else 'rejected'
    request['approver'] = req.approver
    request['comment'] = req.comment
    request['approved_at'] = _now_iso()
    await _record_action_approval(request['incident_id'], req.request_id, req.approver, req.approved)
    return request

# ---- B6: WebSocket real-time push ----
@app.websocket('/ws/incident/{incident_id}')
async def ws_incident(ws: WebSocket, incident_id: str):
    await manager.connect(incident_id, ws)
    try:
        while True:
            await ws.receive_text()  # keep alive, can receive pings
    except WebSocketDisconnect:
        manager.disconnect(incident_id, ws)

@app.get('/ws/status')
async def ws_status():
    return {"active_connections": manager.active_connections}

@app.get('/')
async def root():
    return {
        "service": "IntelliOps Prototype API",
        "routes": [
            "/incidents",
            "/incidents (POST — create new case)",
            "/incidents/simulate (POST — quick-simulate preset scenarios)",
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
            "/knowledge/high-frequency-patterns",
            "/knowledge/skill-update-log",
            "/knowledge/run-aggregation (POST)",
            "/data/summary",
            "/data/reload",
            "/alarm/{alarm_id}",
            "/alarm/{alarm_id}/match",
            "/alarm/{alarm_id}/impact",
            "/diagnosis/alarm/{alarm_id}",
            "/ui/"
        ]
    }

@app.get('/ui')
async def ui_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url='/ui/')

# Mount static UI under /ui (serves src/ui/index.html)
UI_DIR = os.path.join(DATA_ROOT, 'ui')
if os.path.isdir(UI_DIR):
    app.mount('/ui', StaticFiles(directory=UI_DIR, html=True), name='ui')
