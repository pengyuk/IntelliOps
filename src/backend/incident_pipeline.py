"""
Incident Auto-Analysis Pipeline 鈥?triggered when an incident is created or simulated.

This module orchestrates the full "arrival 鈫?ready" flow:
  1. KG context building (services + upstream/downstream dependencies)
  2. Related case search (vector + postmortem)
  3. Log analysis (simulated for prototype)
  4. Initial skill-aware diagnosis
  5. Script suggestions
  6. Meaningful timeline events

All results are stored in the DB and returned as part of the incident response,
so the user opens the page to find everything pre-computed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .db import get_db
from .skill_loader import get_skill_loader
from .agent_orchestrator import get_orchestrator, AGENT_IDENTITIES
from .knowledge_distiller import KnowledgeDistiller
from .knowledge_deduplicator import deduplicate_knowledge
from .pattern_aggregator import run_pattern_aggregation, find_high_frequency_patterns
from .skill_updater import update_skill_refs
import logging
logger = logging.getLogger(__name__)



DB = get_db()


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

async def run_incident_pipeline(
    incident: Dict[str, Any],
    user_id: str = 'system',
    app_context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Run the full auto-analysis pipeline for a newly created incident.
    
    Args:
        incident: The incident dict (must have incident_id, summary, affected_services, etc.)
        user_id: Who triggered this (default 'system')
        app_context: Dict with references to app-level singletons (for _fetch_kg_nodes etc.)
    
    Returns:
        Dict with 'pipeline_results' containing all analysis outputs
    """
    incident_id = incident.get('incident_id', '')
    print(f"[Pipeline] ========== Auto-analysis for {incident_id} ==========")
    
    results = {
        'pipeline_run_id': f'pipe-{str(uuid.uuid4())[:8]}',
        'incident_id': incident_id,
        'started_at': _now_iso(),
        'steps': {},
    }
    
    # Step 1: Build KG context with dependency analysis
    print("[Pipeline] Step 1/6: Building KG context...")
    kg_context = await _build_enriched_kg_context(incident, app_context)
    results['steps']['kg_context'] = {'status': 'done', 'node_count': len(kg_context.get('all_nodes', []))}
    
    # Step 2: Search related cases
    print("[Pipeline] Step 2/6: Searching related cases...")
    related_cases = await _search_related_cases(incident, app_context)
    results['steps']['related_cases'] = {'status': 'done', 'count': len(related_cases)}
    
    # Step 3: Run log analysis
    print("[Pipeline] Step 3/6: Running log analysis...")
    log_analysis = await _run_log_analysis(incident, app_context)
    results['steps']['log_analysis'] = {'status': 'done', 
                                          'summary': log_analysis.get('summary', '')[:80]}
    
    # Step 4: Run skill-aware diagnosis
    print("[Pipeline] Step 4/6: Running skill-aware diagnosis...")
    diagnosis = await _run_skill_diagnosis(incident, kg_context, log_analysis, related_cases, app_context)
    results['steps']['diagnosis'] = {
        'status': 'done',
        'diagnosis_id': diagnosis.get('diagnosis_id', ''),
        'confidence': diagnosis.get('confidence_summary', 0),
        'root_causes': len(diagnosis.get('candidate_root_causes', [])),
    }
    
    # Step 5: Generate script suggestions
    print("[Pipeline] Step 5/6: Generating script suggestions...")
    scripts = await _generate_script_suggestions(incident, diagnosis, app_context)
    results['steps']['scripts'] = {'status': 'done', 'count': len(scripts)}
    
    # Step 6: Create meaningful timeline events
    print("[Pipeline] Step 6/6: Creating timeline events...")
    timeline_events = await _create_pipeline_timeline(incident_id, results, kg_context, 
                                                       log_analysis, diagnosis, user_id,
                                                       app_context)
    results['steps']['timeline'] = {'status': 'done', 'events': len(timeline_events)}
    
    # Store pipeline results on the incident
    incident['_pipeline'] = results
    incident['kg_context'] = kg_context
    incident['related_cases'] = related_cases
    incident['auto_diagnosis'] = diagnosis
    incident['active_skills'] = diagnosis.get('active_skills', [])
    
    print(f"[Pipeline] ========== Complete: {incident_id} ==========")
    return results


# ---------------------------------------------------------------------------
# Step 1: Enriched KG Context
# ---------------------------------------------------------------------------

async def _build_enriched_kg_context(
    incident: Dict[str, Any],
    app_context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Build KG context including upstream/downstream dependency analysis."""
    ctx = app_context or {}
    _fetch_kg_nodes = ctx.get('_fetch_kg_nodes', lambda ids: [])
    _fetch_kg_edges = ctx.get('_fetch_kg_edges', lambda ids: [])
    _get_kg_service = ctx.get('_get_kg_service')
    
    affected = incident.get('affected_services', [])
    related_changes = incident.get('related_changes', [])
    related_alerts = incident.get('related_alerts', [])
    
    # Basic nodes
    services = _fetch_kg_nodes(affected)
    changes = _fetch_kg_nodes(related_changes)
    alerts = _fetch_kg_nodes(related_alerts)
    
    all_node_ids = set(affected + related_changes + related_alerts)
    all_edges = _fetch_kg_edges(list(all_node_ids))
    
    # Discover upstream/downstream from edges
    upstream_ids = set()
    downstream_ids = set()
    for edge in all_edges:
        if edge.get('to') in affected:
            upstream_ids.add(edge.get('from', ''))
        if edge.get('from') in affected:
            downstream_ids.add(edge.get('to', ''))
    
    upstream_nodes = _fetch_kg_nodes(list(upstream_ids - all_node_ids))
    downstream_nodes = _fetch_kg_nodes(list(downstream_ids - all_node_ids))
    all_node_ids |= upstream_ids | downstream_ids
    all_edges = _fetch_kg_edges(list(all_node_ids))
    
    # Impact scope via KG service
    impact_scope = {}
    if _get_kg_service and affected:
        try:
            kg = _get_kg_service()
            impact_scope = kg.impact_scope(affected, max_hops=2)
        except Exception:
            pass
    
    # Dependency chain: who depends on me, who do I depend on
    dependency_chain = _analyze_dependency_chain(affected, all_edges, _fetch_kg_nodes)
    
    return {
        'services': services,
        'changes': changes,
        'alerts': alerts,
        'upstream': upstream_nodes,
        'downstream': downstream_nodes,
        'upstream_ids': list(upstream_ids),
        'downstream_ids': list(downstream_ids),
        'all_nodes': _fetch_kg_nodes(list(all_node_ids)),
        'edges': all_edges,
        'impact_scope': impact_scope,
        'dependency_chain': dependency_chain,
        'summary': _build_kg_summary(services, upstream_nodes, downstream_nodes, changes, alerts),
    }


def _analyze_dependency_chain(
    service_ids: List[str],
    edges: List[Dict[str, Any]],
    fetch_nodes,
) -> Dict[str, Any]:
    """Analyze who depends on whom."""
    chain = {'depends_on': [], 'depended_by': [], 'shared_dependencies': []}
    if not service_ids:
        return chain
    
    for sid in service_ids:
        node = fetch_nodes([sid])
        node_name = node[0].get('name', sid) if node else sid
        
        # Who does this service depend on (upstream)?
        for edge in edges:
            if edge.get('to') == sid and edge.get('from') not in service_ids:
                dep_node = fetch_nodes([edge['from']])
                dep_name = dep_node[0].get('name', edge['from']) if dep_node else edge['from']
                chain['depends_on'].append({
                    'service': node_name,
                    'depends_on': dep_name,
                    'relation': edge.get('rel', 'depends_on'),
                })
        
        # Who depends on this service (downstream)?
        for edge in edges:
            if edge.get('from') == sid and edge.get('to') not in service_ids:
                dep_node = fetch_nodes([edge['to']])
                dep_name = dep_node[0].get('name', edge['to']) if dep_node else edge['to']
                chain['depended_by'].append({
                    'service': node_name,
                    'depended_by': dep_name,
                    'relation': edge.get('rel', 'depends_on'),
                })
    
    return chain


def _build_kg_summary(services, upstream, downstream, changes, alerts) -> str:
    """Build a human-readable KG summary for timeline."""
    parts = []
    if services:
        names = [s.get('name', '?') for s in services]
        parts.append(f"鍙楀奖鍝嶆湇鍔? {', '.join(names)}")
    if upstream:
        names = [s.get('name', '?') for s in upstream]
        parts.append(f"涓婃父渚濊禆: {', '.join(names)}锛堣繖浜涚郴缁熶細褰卞搷鏈湇鍔★級")
    if downstream:
        names = [s.get('name', '?') for s in downstream]
        parts.append(f"涓嬫父褰卞搷: {', '.join(names)}锛堟湰鏈嶅姟鏁呴殰浼氬奖鍝嶈繖浜涚郴缁燂級")
    if changes:
        names = [s.get('name', '?') for s in changes]
        parts.append(f"鍏宠仈鍙樻洿: {', '.join(names)}")
    return '; '.join(parts) if parts else '鐭ヨ瘑鍥捐氨涓婁笅鏂囧凡鏋勫缓'


# ---------------------------------------------------------------------------
# Step 2: Related Cases Search
# ---------------------------------------------------------------------------

async def _search_related_cases(
    incident: Dict[str, Any],
    app_context: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Search for related historical cases."""
    ctx = app_context or {}
    _related_cases_fn = ctx.get('_related_cases_for_incident')
    if _related_cases_fn:
        try:
            return await _related_cases_fn(incident['incident_id'], limit=5)
        except Exception:
            pass
    return []


# ---------------------------------------------------------------------------
# Step 3: Log Analysis
# ---------------------------------------------------------------------------

async def _run_log_analysis(
    incident: Dict[str, Any],
    app_context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Run log analysis for the incident."""
    ctx = app_context or {}
    LogAnalyzer = ctx.get('LogAnalyzer')
    if LogAnalyzer:
        try:
            result = await LogAnalyzer.analyze(incident)
            return result
        except Exception:
            pass
    return {'summary': '鏃ュ織鍒嗘瀽寰呮墽琛?, 'key_events': [], 'anomalies': []}


# ---------------------------------------------------------------------------
# Step 4: Skill-Aware Diagnosis
# ---------------------------------------------------------------------------

async def _run_skill_diagnosis(
    incident: Dict[str, Any],
    kg_context: Dict[str, Any],
    log_analysis: Dict[str, Any],
    related_cases: List[Dict[str, Any]],
    app_context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Run diagnosis with skill context injected."""
    ctx = app_context or {}
    IncidentReasoner = ctx.get('IncidentReasoner')
    enrich_diagnosis = ctx.get('enrich_diagnosis')
    
    diagnosis_id = f'diag-{str(uuid.uuid4())[:8]}'
    
    # Run reasoning
    reasoning = {}
    if IncidentReasoner:
        try:
            reasoning = await IncidentReasoner.infer_root_causes(incident, kg_context)
        except Exception:
            pass
    
    # Determine active skills
    loader = await get_skill_loader()
    orch = await get_orchestrator()
    route_result = await orch._router.route(
        user_message=incident.get('summary', '鏁呴殰璇婃柇'),
        incident=incident,
    )
    
    # Build candidates
    candidates = []
    for cause in reasoning.get('candidate_root_causes', []):
        conf = cause.get('confidence', 0)
        candidates.append({
            **cause,
            'confidence_level': 'high' if conf >= 0.75 else 'medium' if conf >= 0.55 else 'low',
            'evidence_chain': reasoning.get('evidence', []),
            'similar_incidents': related_cases[:3],
        })
    
    if not candidates:
        candidates = [{
            'cause': '寰呮敹闆嗘洿澶氳瘉鎹悗纭畾鏍瑰洜',
            'confidence': 0.3,
            'confidence_level': 'low',
            'detail': '鑷姩鍒嗘瀽灏氭湭鍙戠幇楂樼疆淇″害鏍瑰洜锛屽缓璁€氳繃Copilot浜や簰琛ュ厖淇℃伅銆?,
            'evidence_items': [],
        }]
    
    diagnosis = {
        'diagnosis_id': diagnosis_id,
        'incident_id': incident.get('incident_id'),
        'kg_context': kg_context,
        'log_analysis': log_analysis,
        'candidate_root_causes': candidates,
        'reasoning_steps': reasoning.get('reasoning_steps', []),
        'evidence': reasoning.get('evidence', []),
        'confidence_summary': reasoning.get('confidence_summary', 0),
        'initial_recommendations': _build_initial_recommendations(incident, reasoning),
        'diagnostic_session_started': True,
        'created_at': _now_iso(),
        'created_by': 'system',
        'method': reasoning.get('method', 'rule_based'),
        'active_skills': [s.name for s in route_result.active_skills],
        'primary_skill': route_result.intent.primary_skill.name if route_result.intent.primary_skill else None,
        'skill_suggestions': [
            {'skill': s.name, 'step': s.steps[0]['title'] if s.steps else ''}
            for s in route_result.active_skills[:3]
        ],
    }
    
    # Enrich with credibility
    if enrich_diagnosis:
        try:
            diagnosis = enrich_diagnosis(diagnosis, log_analysis=log_analysis, kg_context=kg_context)
        except Exception:
            pass
    
    # Store in DB
    await DB.upsert_diagnosis(diagnosis)
    
    return diagnosis


def _build_initial_recommendations(incident: Dict[str, Any], reasoning: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build initial action recommendations."""
    recs = []
    causes = reasoning.get('candidate_root_causes', [])
    
    if any('寤惰繜' in c.get('cause', '') or '瓒呮椂' in c.get('cause', '') for c in causes):
        recs.append({
            'step': '閲囬泦鏈€杩?0鍒嗛挓鍏抽敭鏃ュ織涓庨敊璇憳瑕?,
            'priority': 'high',
            'rationale': '寤惰繜/瓒呮椂绫绘晠闅滈渶瑕佹棩蹇楄瘉鎹‘璁ゅ叿浣撶摱棰堢偣銆?,
        })
    
    if any('鍙樻洿' in c.get('cause', '') for c in causes):
        recs.append({
            'step': '鏍稿鏁呴殰鏃堕棿绐楀彛鍐呯殑鍙樻洿璁板綍',
            'priority': 'high',
            'rationale': '鍙樻洿鏄晠闅滅殑甯歌瑙﹀彂鍥犵礌锛屼紭鍏堟帓闄ゃ€?,
        })
    
    recs.append({
        'step': '妫€鏌ュ彈褰卞搷鏈嶅姟鐨勪笂涓嬫父渚濊禆鍋ュ悍鐘舵€?,
        'priority': 'medium',
        'rationale': '纭鏁呴殰鏄惁鐢变笂娓哥郴缁熶紶瀵兼垨宸插奖鍝嶄笅娓哥郴缁熴€?,
    })
    
    if any(c.get('confidence', 0) > 0.7 for c in causes):
        recs.append({
            'step': '瀵归珮缃俊鍊欓€夋牴鍥犳墽琛屼綆椋庨櫓楠岃瘉鍔ㄤ綔',
            'priority': 'high',
            'rationale': '鍏堢敤鍙鍔ㄤ綔楠岃瘉锛屽啀鍐冲畾鏄惁杩涘叆瀹℃壒鎵ц銆?,
        })
    
    return recs


# ---------------------------------------------------------------------------
# Step 5: Script Suggestions
# ---------------------------------------------------------------------------

async def _generate_script_suggestions(
    incident: Dict[str, Any],
    diagnosis: Dict[str, Any],
    app_context: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Generate script suggestions based on incident and diagnosis."""
    ctx = app_context or {}
    _script_suggestions_fn = ctx.get('_script_suggestions')
    if _script_suggestions_fn:
        try:
            return await _script_suggestions_fn(
                incident['incident_id'],
                diagnosis.get('diagnosis_id'),
            )
        except Exception:
            pass
    return []


# ---------------------------------------------------------------------------
# Step 6: Meaningful Timeline Events
# ---------------------------------------------------------------------------

async def _create_pipeline_timeline(
    incident_id: str,
    pipeline_results: Dict[str, Any],
    kg_context: Dict[str, Any],
    log_analysis: Dict[str, Any],
    diagnosis: Dict[str, Any],
    user_id: str,
    app_context: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Create detailed, meaningful timeline events."""
    ctx = app_context or {}
    _add_timeline_fn = ctx.get('_add_timeline_event')
    if not _add_timeline_fn:
        return []
    
    events = []
    
    # Event 1: KG context built
    kg_summary = kg_context.get('summary', '鐭ヨ瘑鍥捐氨涓婁笅鏂囧凡鏋勫缓')
    upstream_count = len(kg_context.get('upstream', []))
    downstream_count = len(kg_context.get('downstream', []))
    detail = kg_summary
    if upstream_count or downstream_count:
        detail += f"锛堝彂鐜?{upstream_count} 涓笂娓镐緷璧? {downstream_count} 涓笅娓稿奖鍝嶇郴缁燂級"
    e1 = await _add_timeline_fn(
        incident_id, 'kg_context',
        f'鐭ヨ瘑鍥捐氨鍒嗘瀽瀹屾垚: {kg_summary[:80]}',
        'system', 'system', detail,
    )
    events.append(e1)
    
    # Event 2: Log analysis
    log_summary = log_analysis.get('summary', '')
    anomaly_count = len(log_analysis.get('anomalies', []))
    if log_summary:
        e2 = await _add_timeline_fn(
            incident_id, 'log_analysis',
            f'鏃ュ織鍒嗘瀽瀹屾垚: 鍙戠幇 {anomaly_count} 涓紓甯告ā寮?鈥?{log_summary[:80]}',
            'system', 'system', log_summary,
        )
        events.append(e2)
    
    # Event 3: Related cases found
    cases_count = pipeline_results.get('steps', {}).get('related_cases', {}).get('count', 0)
    if cases_count > 0:
        e3 = await _add_timeline_fn(
            incident_id, 'knowledge',
            f'鍘嗗彶妗堜緥鍖归厤: 鎵惧埌 {cases_count} 涓浉浼兼晠闅滄渚?,
            'system', 'system', f'閫氳繃鍚戦噺妫€绱㈠拰鍘嗗彶澶嶇洏鎶ュ憡鍖归厤鍒?{cases_count} 涓浉浼兼渚?,
        )
        events.append(e3)
    
    # Event 4: Diagnosis results
    confidence = diagnosis.get('confidence_summary', 0)
    causes = diagnosis.get('candidate_root_causes', [])
    top_cause = causes[0].get('cause', '寰呯‘璁?) if causes else '寰呯‘璁?
    top_conf = causes[0].get('confidence', 0) if causes else 0
    
    diag_detail = f'鏍瑰洜鎺ㄧ悊缃俊搴? {confidence:.0%}銆備富瑕佸亣璁? {top_cause}锛坽top_conf:.0%}锛?
    if len(causes) > 1:
        diag_detail += f'銆傚彟鏈?{len(causes)-1} 涓€欓€夊亣璁?
    
    active_skills = diagnosis.get('active_skills', [])
    skill_str = '銆?.join(active_skills[:3]) if active_skills else '鏃?
    
    e4 = await _add_timeline_fn(
        incident_id, 'diagnosis',
        f'鏅鸿兘璇婃柇瀹屾垚: {top_cause}锛堢疆淇″害 {top_conf:.0%}锛?,
        'system', 'system',
        f'{diag_detail}\n婵€娲绘妧鑳? {skill_str}',
    )
    events.append(e4)
    
    # Event 5: Ready for interaction
    e5 = await _add_timeline_fn(
        incident_id, 'status',
        f'浜嬫晠鍒嗘瀽鍑嗗灏辩华 鈥?鍙€氳繃Copilot杩涜浜や簰寮忔帓鏌?,
        'system', 'system',
        f'KG涓婁笅鏂囥€佹棩蹇楀垎鏋愩€佸巻鍙叉渚嬨€佹牴鍥犲亣璁惧潎宸插氨缁€?
        f'寤鸿浼樺厛楠岃瘉: {top_cause}',
    )
    events.append(e5)
    
    return events


# ---------------------------------------------------------------------------
# Post-execution feedback: update diagnosis after script runs
# ---------------------------------------------------------------------------

async def on_script_executed(
    incident_id: str,
    execution_result: Dict[str, Any],
    diagnosis_id: Optional[str] = None,
    app_context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Called after a script executes to update diagnosis and timeline."""
    ctx = app_context or {}
    _add_timeline_fn = ctx.get('_add_timeline_event')
    DB = ctx.get('DB') or get_db()
    
    output = execution_result.get('output', '')
    conclusion = execution_result.get('conclusion', '')
    next_suggestion = execution_result.get('next_suggestion', '')
    script_name = execution_result.get('script_name', '鏈煡鑴氭湰')
    
    # Create meaningful timeline event
    if _add_timeline_fn and conclusion:
        await _add_timeline_fn(
            incident_id, 'script_execution',
            f'鑴氭湰鎵ц瀹屾垚: {script_name} 鈥?{conclusion[:100]}',
            'copilot', 'copilot',
            f'鎵ц杈撳嚭: {output[:200]}\n缁撹: {conclusion}\n涓嬩竴姝ュ缓璁? {next_suggestion}',
        )
    
    # Update diagnosis if available
    if diagnosis_id:
        diagnosis = await DB.get_diagnosis(diagnosis_id)
        if diagnosis:
            # Feed execution result into Copilot
            from .copilot import Copilot
            copilot_result = await Copilot.chat(
                diagnosis=diagnosis,
                user_id='system',
                user_message=f'[鑴氭湰鎵ц缁撴灉] 鑴氭湰"{script_name}"宸叉墽琛屽畬鎴愩€俓n杈撳嚭: {output}\n缁撹: {conclusion}\n涓嬩竴姝ュ缓璁? {next_suggestion}\n璇锋牴鎹缁撴灉鏇存柊鏍瑰洜鍋囪銆?,
                action_logs=[],
                skill_context=diagnosis.get('_skill_context'),
            )
            
            await DB.upsert_diagnosis(diagnosis)
            
            # Add timeline event if root causes updated
            if copilot_result.get('confidence_trend') != 'stable':
                causes = diagnosis.get('candidate_root_causes', [])
                top = causes[0] if causes else {}
                await _add_timeline_fn(
                    incident_id, 'diagnosis_update',
                    f'鏍瑰洜鍋囪宸叉洿鏂? {top.get("cause", "")} 缃俊搴?{top.get("confidence", 0):.0%}',
                    'copilot', 'copilot',
                    f'鑴氭湰鎵ц缁撴灉宸茬撼鍏ュ垎鏋愶紝缃俊搴﹁秼鍔? {copilot_result.get("confidence_trend")}',
                )
            
            return copilot_result
    
    return {'status': 'recorded'}


# ---------------------------------------------------------------------------
# Postmortem Agent
# ---------------------------------------------------------------------------

async def run_postmortem_agent(
    incident_id: str,
    requested_by: str = 'ui-user',
    app_context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Run the postmortem agent to generate a structured report and distill knowledge."""
    ctx = app_context or {}
    DB = ctx.get('DB') or get_db()
    _add_timeline_fn = ctx.get('_add_timeline_event')
    _get_user_fn = ctx.get('_get_user', lambda uid: {'role': 'operator'})
    
    incident = await DB.get_incident(incident_id)
    if not incident:
        raise KeyError('incident not found')
    
    # Activate postmortem skill
    loader = await get_skill_loader()
    orch = await get_orchestrator()
    pm_skill = loader.get('postmortem-generator')
    
    if _add_timeline_fn:
        await _add_timeline_fn(
            incident_id, 'postmortem',
            f'澶嶇洏Agent宸插惎鍔?鈥?姝ｅ湪鐢熸垚缁撴瀯鍖栧鐩樻姤鍛?,
            requested_by, _get_user_fn(requested_by).get('role', 'operator'),
            '婵€娲绘妧鑳? postmortem-generator',
        )
    
    # Mark resolved
    incident['status'] = 'Resolved'
    
    # Get diagnosis
    diagnoses = await DB.list_diagnoses(incident_id)
    diagnosis = diagnoses[0] if diagnoses else {}
    
    # Get timeline
    timeline = await DB.list_timeline(incident_id)
    
    # Generate postmortem
    top_cause = (diagnosis.get('candidate_root_causes') or [{}])[0]
    postmortem_id = f'pm-{str(uuid.uuid4())[:8]}'
    
    report = {
        'postmortem_id': postmortem_id,
        'incident_id': incident_id,
        'status': 'draft',
        'created_at': _now_iso(),
        'created_by': requested_by,
        'timeline': timeline,
        'root_cause_conclusion': {
            'cause': top_cause.get('cause', '寰呯‘璁?),
            'confidence': top_cause.get('confidence', diagnosis.get('confidence_summary', 0.5)),
            'evidence': diagnosis.get('evidence', []),
        },
        'decisions': [
            {
                'decision': '浼樺厛鎵ц浣庨闄╁彧璇婚獙璇侊紝鍐嶈繘鍏ュ鎵瑰姩浣?,
                'rationale': '闄嶄綆璇搷浣滈闄╋紝鍚屾椂淇濊瘉璇佹嵁閾惧彲瀹¤銆?,
                'timestamp': _now_iso(),
                'actor': requested_by,
            }
        ],
        'scripts_used': [s for s in await DB.list_scripts() 
                        if s.get('diagnosis_id') == diagnosis.get('diagnosis_id')],
        'improvement_suggestions': [
            '灏嗘湰娆￠珮缃俊鏍瑰洜涓庨獙璇佽剼鏈矇娣€涓虹煡璇嗚祫浜?,
            '涓哄彈褰卞搷鏈嶅姟琛ュ厖涓婁笅娓镐緷璧栫殑鑱斿悎鍛婅瑙勫垯',
            '鎶婇珮椋庨櫓鍔ㄤ綔绾冲叆瀹℃壒妯℃澘锛屼繚鐣欏璁￠摼璺?,
        ],
        'agent_name': 'postmortem-generator',
        'skill_used': pm_skill.name if pm_skill else 'postmortem-generator',
    }
    
    await DB.upsert_postmortem(report)
    
    if _add_timeline_fn:
        await _add_timeline_fn(
            incident_id, 'postmortem',
            f'澶嶇洏鎶ュ憡宸茬敓鎴? {postmortem_id}銆傛牴鍥? {top_cause.get("cause", "寰呯‘璁?)}锛?
            f'鎻愮偧 {len(report["improvement_suggestions"])} 鏉℃敼杩涘缓璁?,
            requested_by, _get_user_fn(requested_by).get('role', 'operator'),
            f'澶嶇洏鎶ュ憡ID: {postmortem_id}',
        )
        # ------------------------------------------------------------------
    # Step 5: Knowledge Distillation + Deduplication (non-blocking)
    # ------------------------------------------------------------------
    try:
        # 5a. Run KnowledgeDistiller on the postmortem report
        knowledge = await KnowledgeDistiller.distill(report)

        # 5b. Deduplicate: merge with existing knowledge base
        knowledge = await deduplicate_knowledge(knowledge, incident_id)

        # 5c. Store deduplicated knowledge in DB
        knowledge["postmortem_id"] = postmortem_id
        knowledge["distilled_at"] = _now_iso()
        await DB.upsert_knowledge(knowledge)

        dedup_summary = knowledge.get("_dedup_summary", {})
        if _add_timeline_fn:
            merged = dedup_summary.get("merged", 0)
            new_entries = dedup_summary.get("new_entries", 0)
            await _add_timeline_fn(
                incident_id, "knowledge",
                f"鐭ヨ瘑钂搁瀹屾垚: 鍚堝苟 {merged} 鏉? 鏂板 {new_entries} 鏉? 楂橀妯″紡 {len(dedup_summary.get('high_frequency_patterns', []))} 涓?,
                "system", "system",
                f"鐭ヨ瘑璧勪骇宸插幓閲嶅苟瀛樺偍, knowledge_id={knowledge.get('knowledge_id', '')}",
            )

        # 5d. Check for high-frequency patterns and trigger batch aggregation
        hf_patterns = dedup_summary.get("high_frequency_patterns", [])
        if hf_patterns:
            refined = await run_pattern_aggregation()
            if refined:
                for ref in refined:
                    await update_skill_refs(
                        ref,
                        ref.get("_asset_type", "root_cause_rules"),
                        ref.get("_source_count", len(hf_patterns)),
                    )
                if _add_timeline_fn:
                    await _add_timeline_fn(
                        incident_id, "knowledge",
                        f"瑙勫垯鑱氬悎: {len(refined)} 涓珮棰戞ā寮忓凡鑱氬悎骞舵洿鏂癝kill鍙傝€冩枃浠?,
                        "system", "system",
                        "鐢╬attern_aggregator鑱氬悎+skill_updater鏇存柊",
                    )
    except Exception as exc:
        logger.warning("Knowledge distillation/dedup failed (non-fatal): %s", exc)

    return report




