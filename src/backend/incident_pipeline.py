"""
Incident Auto-Analysis Pipeline — triggered when an incident is created or simulated.

This module orchestrates the full "arrival → ready" flow:
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
    # P0-1: 扩展上下游ID到incident，供检索和相似案例匹配使用
    incident['_upstream_ids'] = kg_context.get('upstream_ids', [])
    incident['_downstream_ids'] = kg_context.get('downstream_ids', [])
    incident['_all_change_ids'] = kg_context.get('all_change_ids', [])
    
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
    
    # ── P0-1: 检索上下游系统的变更记录 ──
    # 上游系统的变更可能直接影响本服务
    upstream_change_ids = list(upstream_ids - set(related_changes))
    upstream_changes = _fetch_kg_nodes(upstream_change_ids) if upstream_change_ids else []
    # 下游系统的变更也可能揭示问题（如回滚操作）
    downstream_change_ids = list(downstream_ids - set(related_changes))
    downstream_changes = _fetch_kg_nodes(downstream_change_ids) if downstream_change_ids else []
    # 合并所有变更
    all_changes = list(changes) + upstream_changes + downstream_changes
    all_change_ids = set(related_changes) | upstream_ids | downstream_ids
    all_node_ids |= all_change_ids
    
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
        # ── P0-1: 扩展变更上下文 ──
        'upstream_changes': upstream_changes,
        'downstream_changes': downstream_changes,
        'all_changes': all_changes,
        'all_change_ids': list(all_change_ids),
        'all_nodes': _fetch_kg_nodes(list(all_node_ids)),
        'edges': all_edges,
        'impact_scope': impact_scope,
        'dependency_chain': dependency_chain,
        'summary': _build_kg_summary(services, upstream_nodes, downstream_nodes, changes, alerts,
                                       upstream_changes, downstream_changes),
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


def _build_kg_summary(services, upstream, downstream, changes, alerts,
                       upstream_changes=None, downstream_changes=None) -> str:
    """Build a human-readable KG summary for timeline."""
    parts = []
    if services:
        names = [s.get('name', '?') for s in services]
        parts.append(f"受影响服务: {', '.join(names)}")
    if upstream:
        names = [s.get('name', '?') for s in upstream]
        parts.append(f"上游依赖: {', '.join(names)}（这些系统会影响本服务）")
    if downstream:
        names = [s.get('name', '?') for s in downstream]
        parts.append(f"下游影响: {', '.join(names)}（本服务故障会影响这些系统）")
    if changes:
        names = [s.get('name', '?') for s in changes]
        parts.append(f"关联变更: {', '.join(names)}")
    # P0-1: 上下游变更提示
    if upstream_changes:
        names = [s.get('name', '?') for s in upstream_changes]
        parts.append(f"⚠️ 上游系统变更: {', '.join(names)}（上游变更可能传导至本服务）")
    if downstream_changes:
        names = [s.get('name', '?') for s in downstream_changes]
        parts.append(f"下游系统变更: {', '.join(names)}")
    return '; '.join(parts) if parts else '知识图谱上下文已构建'


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
    return {'summary': '日志分析待执行', 'key_events': [], 'anomalies': []}


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
        user_message=incident.get('summary', '故障诊断'),
        incident=incident,
    )
    
    # Build candidates
    candidates = []
    for i, cause in enumerate(reasoning.get('candidate_root_causes', [])):
        conf = cause.get('confidence', 0)
        rc_id = f"rc-{incident.get('incident_id', '')}-{i+1}"
        candidates.append({
            **cause,
            'root_cause_id': rc_id,
            'confidence_level': 'high' if conf >= 0.75 else 'medium' if conf >= 0.55 else 'low',
            'evidence_chain': reasoning.get('evidence', []),
            'similar_incidents': related_cases[:3],
        })
    
    if not candidates:
        candidates = [{
            'cause': '待收集更多证据后确定根因',
            'confidence': 0.3,
            'confidence_level': 'low',
            'detail': '自动分析尚未发现高置信度根因，建议通过Copilot交互补充信息。',
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
    
    if any('延迟' in c.get('cause', '') or '超时' in c.get('cause', '') for c in causes):
        recs.append({
            'step': '采集最近30分钟关键日志与错误摘要',
            'priority': 'high',
            'rationale': '延迟/超时类故障需要日志证据确认具体瓶颈点。',
        })
    
    if any('变更' in c.get('cause', '') for c in causes):
        recs.append({
            'step': '核对故障时间窗口内的变更记录',
            'priority': 'high',
            'rationale': '变更是故障的常见触发因素，优先排除。',
        })
    
    recs.append({
        'step': '检查受影响服务的上下游依赖健康状态',
        'priority': 'medium',
        'rationale': '确认故障是否由上游系统传导或已影响下游系统。',
    })
    
    if any(c.get('confidence', 0) > 0.7 for c in causes):
        recs.append({
            'step': '对高置信候选根因执行低风险验证动作',
            'priority': 'high',
            'rationale': '先用只读动作验证，再决定是否进入审批执行。',
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
    kg_summary = kg_context.get('summary', '知识图谱上下文已构建')
    upstream_count = len(kg_context.get('upstream', []))
    downstream_count = len(kg_context.get('downstream', []))
    detail = kg_summary
    if upstream_count or downstream_count:
        detail += f"（发现 {upstream_count} 个上游依赖, {downstream_count} 个下游影响系统）"
    e1 = await _add_timeline_fn(
        incident_id, 'kg_context',
        f'知识图谱分析完成: {kg_summary[:80]}',
        'system', 'system', detail,
    )
    events.append(e1)
    
    # Event 2: Log analysis
    log_summary = log_analysis.get('summary', '')
    anomaly_count = len(log_analysis.get('anomalies', []))
    if log_summary:
        e2 = await _add_timeline_fn(
            incident_id, 'log_analysis',
            f'日志分析完成: 发现 {anomaly_count} 个异常模式 — {log_summary[:80]}',
            'system', 'system', log_summary,
        )
        events.append(e2)
    
    # Event 3: Related cases found
    cases_count = pipeline_results.get('steps', {}).get('related_cases', {}).get('count', 0)
    if cases_count > 0:
        e3 = await _add_timeline_fn(
            incident_id, 'knowledge',
            f'历史案例匹配: 找到 {cases_count} 个相似故障案例',
            'system', 'system', f'通过向量检索和历史复盘报告匹配到 {cases_count} 个相似案例',
        )
        events.append(e3)
    
    # Event 4: Diagnosis results
    confidence = diagnosis.get('confidence_summary', 0)
    causes = diagnosis.get('candidate_root_causes', [])
    top_cause = causes[0].get('cause', '待确认') if causes else '待确认'
    top_conf = causes[0].get('confidence', 0) if causes else 0
    top_rc_id = causes[0].get('root_cause_id', '') if causes else ''
    
    diag_detail = f'根因推理置信度: {confidence:.0%}。主要假设: {top_cause}（{top_conf:.0%}）'
    if len(causes) > 1:
        diag_detail += f'。另有 {len(causes)-1} 个候选假设'
    
    active_skills = diagnosis.get('active_skills', [])
    skill_str = '、'.join(active_skills[:3]) if active_skills else '无'
    
    e4 = await _add_timeline_fn(
        incident_id, 'diagnosis',
        f'智能诊断完成: {top_cause}（置信度 {top_conf:.0%}）',
        'system', 'system',
        f'{diag_detail}\n激活技能: {skill_str}',
        related_root_cause_id=top_rc_id,
    )
    events.append(e4)
    
    # Event 5: Ready for interaction
    e5 = await _add_timeline_fn(
        incident_id, 'status',
        f'事故分析准备就绪 — 可通过Copilot进行交互式排查',
        'system', 'system',
        f'KG上下文、日志分析、历史案例、根因假设均已就绪。'
        f'建议优先验证: {top_cause}',
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
    script_name = execution_result.get('script_name', '未知脚本')
    # P0-3: 获取关联的根因假设ID
    related_rc_id = execution_result.get('related_root_cause_id', '')
    
    # Create meaningful timeline event
    if _add_timeline_fn and conclusion:
        await _add_timeline_fn(
            incident_id, 'script_execution',
            f'脚本执行完成: {script_name} — {conclusion[:100]}',
            'copilot', 'copilot',
            f'执行输出: {output[:200]}\n结论: {conclusion}\n下一步建议: {next_suggestion}',
            related_root_cause_id=related_rc_id,
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
                user_message=f'[脚本执行结果] 脚本"{script_name}"已执行完成。\n输出: {output}\n结论: {conclusion}\n下一步建议: {next_suggestion}\n请根据此结果更新根因假设。',
                action_logs=[],
                skill_context=diagnosis.get('_skill_context'),
            )
            
            await DB.upsert_diagnosis(diagnosis)
            
            # Add timeline event if root causes updated
            if copilot_result.get('confidence_trend') != 'stable':
                causes = diagnosis.get('candidate_root_causes', [])
                top = causes[0] if causes else {}
                top_rc_id = top.get('root_cause_id', related_rc_id) if top else related_rc_id
                await _add_timeline_fn(
                    incident_id, 'diagnosis_update',
                    f'根因假设已更新: {top.get("cause", "")} 置信度 {top.get("confidence", 0):.0%}',
                    'copilot', 'copilot',
                    f'脚本执行结果已纳入分析，置信度趋势: {copilot_result.get("confidence_trend")}',
                    related_root_cause_id=top_rc_id,
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
            f'复盘Agent已启动 — 正在生成结构化复盘报告',
            requested_by, _get_user_fn(requested_by).get('role', 'operator'),
            '激活技能: postmortem-generator',
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
            'cause': top_cause.get('cause', '待确认'),
            'confidence': top_cause.get('confidence', diagnosis.get('confidence_summary', 0.5)),
            'evidence': diagnosis.get('evidence', []),
        },
        'decisions': [
            {
                'decision': '优先执行低风险只读验证，再进入审批动作',
                'rationale': '降低误操作风险，同时保证证据链可审计。',
                'timestamp': _now_iso(),
                'actor': requested_by,
            }
        ],
        'scripts_used': [s for s in await DB.list_scripts() 
                        if s.get('diagnosis_id') == diagnosis.get('diagnosis_id')],
        'improvement_suggestions': [
            '将本次高置信根因与验证脚本沉淀为知识资产',
            '为受影响服务补充上下游依赖的联合告警规则',
            '把高风险动作纳入审批模板，保留审计链路',
        ],
        'agent_name': 'postmortem-generator',
        'skill_used': pm_skill.name if pm_skill else 'postmortem-generator',
    }
    
    await DB.upsert_postmortem(report)
    
    if _add_timeline_fn:
        await _add_timeline_fn(
            incident_id, 'postmortem',
            f'复盘报告已生成: {postmortem_id}。根因: {top_cause.get("cause", "待确认")}，'
            f'提炼 {len(report["improvement_suggestions"])} 条改进建议',
            requested_by, _get_user_fn(requested_by).get('role', 'operator'),
            f'复盘报告ID: {postmortem_id}',
        )
    
    # ── P1-2: Knowledge Feedback Loop ──
    # When postmortem is generated, apply feedback to referenced knowledge rules
    try:
        from .knowledge_distiller import apply_knowledge_feedback, KnowledgeFeedbackManager
        
        # Check if any historical knowledge rules were referenced in this incident
        similar_cases = incident.get('related_cases', [])
        for case in similar_cases:
            # Find knowledge assets from the case's root cause
            knowledge_id = case.get('knowledge_id', '')
            if knowledge_id:
                # The root cause matched → verified
                knowledge_asset = case.get('knowledge_asset', {})
                if knowledge_asset:
                    updated = apply_knowledge_feedback(
                        knowledge_asset, was_correct=True,
                        incident_id=incident_id,
                    )
                    new_weight = updated.get('dynamic_weight', 0)
                    new_level = KnowledgeFeedbackManager.get_reliability_level(updated)
                    print(f"[Postmortem] Knowledge feedback: {knowledge_id} "
                          f"verified → weight={new_weight:.0%}, level={new_level}")
        
        # Also record the current root cause conclusion for future feedback
        diagnosis_causes = diagnosis.get('candidate_root_causes', [])
        for cause in diagnosis_causes:
            rc_id = cause.get('root_cause_id', '')
            if rc_id:
                # Initialize feedback fields for this root cause rule
                cause.setdefault('verified_count', 0)
                cause.setdefault('false_positive_count', 0)
                cause.setdefault('dynamic_weight', cause.get('confidence', 0.5))
                cause.setdefault('last_feedback_at', '')
    except Exception as e:
        print(f"[Postmortem] Knowledge feedback skipped: {e}")
    
    return report
