"""
Skill Router — matches user intent to the best skill(s) and dispatches execution.

This is the bridge between the API layer and the Skill system.
Instead of directly calling copilot.py/reasoner.py, the router:
1. Receives a user request (text + incident context)
2. Matches to the most relevant skill(s)
3. Injects skill context (steps, API refs, guidance) into the LLM prompt
4. Coordinates multi-skill workflows when needed

Usage:
    router = SkillRouter(loader)
    result = await router.route(user_message, incident, diagnosis)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .skill_loader import SkillLoader, Skill, get_skill_loader


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

# Intent definitions with their primary skill mapping
INTENT_MAP = {
    "diagnose": {
        "skill": "incident-diagnosis",
        "keywords_cn": ["诊断", "排查", "根因", "分析", "什么原因", "为什么", "帮我看看",
                       "怎么回事", "出问题了", "挂了", "异常"],
        "keywords_en": ["diagnose", "diagnosis", "root cause", "troubleshoot", "investigate",
                       "what happened", "why", "incident"],
    },
    "analyze_logs": {
        "skill": "log-analysis",
        "keywords_cn": ["日志", "log", "错误日志", "报错", "堆栈", "trace", "异常"],
        "keywords_en": ["log", "error", "stack trace", "exception", "warn"],
    },
    "execute_script": {
        "skill": "script-operations",
        "keywords_cn": ["执行", "脚本", "运行", "命令", "重启", "修复", "检查"],
        "keywords_en": ["execute", "run", "script", "command", "restart", "fix"],
    },
    "generate_postmortem": {
        "skill": "postmortem-generator",
        "keywords_cn": ["复盘", "总结", "报告", "回顾", "postmortem", "改进"],
        "keywords_en": ["postmortem", "report", "summary", "review", "retrospective"],
    },
    "search_knowledge": {
        "skill": "knowledge-retrieval",
        "keywords_cn": ["查", "搜索", "案例", "SOP", "知识库", "有没有", "类似的", "历史"],
        "keywords_en": ["search", "find", "lookup", "similar", "history", "knowledge"],
    },
    "coordinate": {
        "skill": "war-room-coordination",
        "keywords_cn": ["通知", "@", "同步", "协同", "拉人", "指派", "DBA", "开发"],
        "keywords_en": ["notify", "@", "sync", "coordinate", "assign", "who"],
    },
}


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: str
    primary_skill: Optional[Skill]
    confidence: float
    alternative_skills: List[Tuple[Skill, float]] = field(default_factory=list)
    extracted_entities: Dict[str, str] = field(default_factory=dict)


@dataclass
class RouteResult:
    """Result of skill routing."""
    intent: IntentResult
    active_skills: List[Skill]
    skill_context_prompt: str        # Injected into LLM system prompt
    suggested_apis: List[str]        # APIs the skill suggests calling
    next_steps: List[str]            # Next steps from matched skills


# ---------------------------------------------------------------------------
# SkillRouter
# ---------------------------------------------------------------------------

class SkillRouter:
    """Routes user queries to appropriate skills and builds execution context."""
    
    def __init__(self, loader: Optional[SkillLoader] = None):
        self._loader = loader
    
    async def _get_loader(self) -> SkillLoader:
        if self._loader is None:
            self._loader = await get_skill_loader()
        return self._loader
    
    async def classify_intent(self, user_message: str) -> IntentResult:
        """Classify user message into a high-level intent."""
        loader = await self._get_loader()
        msg_lower = user_message.lower()
        
        best_intent = "diagnose"  # default
        best_score = 0.0
        
        for intent_name, config in INTENT_MAP.items():
            score = 0.0
            for kw in config["keywords_cn"]:
                if kw in user_message:
                    score += len(kw) * 1.0
            for kw in config["keywords_en"]:
                if kw.lower() in msg_lower:
                    score += len(kw) * 0.8
            
            if score > best_score:
                best_score = score
                best_intent = intent_name
        
        # Get primary skill
        primary_skill_name = INTENT_MAP[best_intent]["skill"]
        primary_skill = loader.get(primary_skill_name)
        
        # Get alternatives from keyword matching
        alternatives = loader.match(user_message, top_k=3)
        # Filter out the primary
        alternatives = [(s, sc) for s, sc in alternatives if s.name != primary_skill_name]
        
        # Extract simple entities
        entities = _extract_entities(user_message)
        
        return IntentResult(
            intent=best_intent,
            primary_skill=primary_skill,
            confidence=min(best_score / 20.0, 0.95),  # normalize
            alternative_skills=alternatives,
            extracted_entities=entities,
        )
    
    async def route(self, user_message: str,
                    incident: Optional[Dict[str, Any]] = None,
                    diagnosis: Optional[Dict[str, Any]] = None) -> RouteResult:
        """Full routing: classify intent, load skills, build context."""
        loader = await self._get_loader()
        
        # Step 1: Classify intent
        intent = await self.classify_intent(user_message)
        
        # Step 2: Determine active skills
        active_skills: List[Skill] = []
        if intent.primary_skill:
            active_skills.append(intent.primary_skill)
        
        # Add contextual skills based on incident state
        if incident:
            contextual = loader.get_active_skills_for_context(incident, diagnosis)
            for skill in contextual:
                if skill.name not in {s.name for s in active_skills}:
                    active_skills.append(skill)
        
        # ── P2: Topology-aware skill augmentation ──
        topology_skills, topology_hints = _get_topology_aware_skills(incident, loader)
        for skill in topology_skills:
            if skill and skill.name not in {s.name for s in active_skills}:
                active_skills.append(skill)
        
        # Step 3: Build skill context prompt for LLM
        skill_context_prompt = _build_skill_context_prompt(active_skills, intent)
        
        # Append topology hints to the context prompt
        if topology_hints:
            skill_context_prompt += "\n\n## 🔗 拓扑感知建议\n" + topology_hints
        
        # Step 4: Collect suggested APIs and next steps
        suggested_apis: List[str] = []
        next_steps: List[str] = []
        for skill in active_skills:
            suggested_apis.extend(skill.api_refs)
            for step in skill.steps[:3]:  # first 3 steps most relevant
                next_steps.append(f"[{skill.name}] {step.get('title', '')}")
        
        # Dedup
        suggested_apis = list(dict.fromkeys(suggested_apis))
        
        return RouteResult(
            intent=intent,
            active_skills=active_skills,
            skill_context_prompt=skill_context_prompt,
            suggested_apis=suggested_apis,
            next_steps=next_steps[:8],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_entities(text: str) -> Dict[str, str]:
    """Extract simple named entities from user text."""
    entities = {}
    
    # Extract incident ID (inc-XXXX)
    inc_match = re.search(r'inc-[a-zA-Z0-9]+', text)
    if inc_match:
        entities['incident_id'] = inc_match.group(0)
    
    # Extract service names (simple pattern)
    svc_match = re.search(r'svc-[a-zA-Z0-9]+', text)
    if svc_match:
        entities['service_id'] = svc_match.group(0)
    
    return entities


import re  # at top would be cleaner, but placed here to avoid circular issues


def _build_skill_context_prompt(skills: List[Skill], intent: IntentResult) -> str:
    """Build a compact skill context prompt for injection into LLM system prompt.
    
    This tells the LLM:
    - Which skills are active and what they do
    - Key steps to follow
    - Available APIs to call
    """
    if not skills:
        return ""
    
    lines = [
        "## 当前激活的技能 (Active Skills)",
        "",
    ]
    
    for skill in skills:
        is_primary = (skill.name == intent.primary_skill.name) if intent.primary_skill else False
        marker = "★ 主技能" if is_primary else "  辅助技能"
        lines.append(f"### {marker}: {skill.name}")
        lines.append(f"**用途**: {skill.meta.description[:200]}")
        
        if skill.steps:
            lines.append("**关键步骤**:")
            for step in skill.steps[:4]:
                lines.append(f"  {step['step']}. {step['title']}")
        
        if skill.api_refs:
            lines.append(f"**可用API**: {', '.join(skill.api_refs[:5])}")
        
        lines.append("")
    
    # Add routing guidance
    lines.append("## 路由指导")
    lines.append(f"当前意图: {intent.intent}")
    lines.append(f"主技能: {intent.primary_skill.name if intent.primary_skill else 'none'}")
    lines.append("请优先按照主技能的步骤执行，辅助技能提供补充能力。")
    lines.append("")
    
    return "\n".join(lines)


def _get_topology_aware_skills(
    incident: Optional[Dict[str, Any]],
    loader: Any,
) -> Tuple[List[Any], str]:
    """P2: Analyze KG topology to recommend context-aware skills.
    
    Returns:
        (additional_skills, topology_hints_text)
    """
    if not incident:
        return [], ""
    
    kg_context = incident.get('kg_context', {})
    upstream_nodes = kg_context.get('upstream', [])
    downstream_nodes = kg_context.get('downstream', [])
    upstream_ids = kg_context.get('upstream_ids', [])
    downstream_ids = kg_context.get('downstream_ids', [])
    upstream_changes = kg_context.get('upstream_changes', [])
    
    if not upstream_nodes and not downstream_nodes:
        return [], ""
    
    additional_skills = []
    hints = []
    
    # Classify upstream types (reuse the classification logic)
    upstream_types = _classify_node_types(upstream_nodes, upstream_ids)
    downstream_types = _classify_node_types(downstream_nodes, downstream_ids)
    
    all_types = {**upstream_types, **downstream_types}
    
    # Database found in topology → recommend knowledge-retrieval with DB focus
    if all_types.get('database'):
        kr_skill = loader.get('knowledge-retrieval')
        if kr_skill:
            additional_skills.append(kr_skill)
        db_names = ', '.join(all_types['database'][:3])
        hints.append(
            f"🔍 当前服务的上下游包含**数据库** ({db_names})。"
            f"建议通过 `knowledge-retrieval` 技能查询这些数据库的历史故障和已知问题。"
            f"优先检查：连接池配置、慢查询日志、锁等待、复制延迟。"
        )
    
    # Message queue → check MQ status
    if all_types.get('message_queue'):
        la_skill = loader.get('log-analysis')
        if la_skill and la_skill.name not in {s.name for s in additional_skills}:
            additional_skills.append(la_skill)
        mq_names = ', '.join(all_types['message_queue'][:3])
        hints.append(
            f"📨 当前服务的上下游包含**消息队列** ({mq_names})。"
            f"建议通过 `log-analysis` 检查MQ的队列积压深度、消费延迟和死信情况。"
        )
    
    # Third-party API → check external dependencies
    if all_types.get('third_party'):
        kr_skill = loader.get('knowledge-retrieval')
        if kr_skill and kr_skill.name not in {s.name for s in additional_skills}:
            additional_skills.append(kr_skill)
        tp_names = ', '.join(all_types['third_party'][:3])
        hints.append(
            f"🌐 当前服务的上下游包含**第三方接口** ({tp_names})。"
            f"建议查询这些第三方接口的SLA状态、历史故障模式和降级方案。"
        )
    
    # Cache → check cache health
    if all_types.get('cache'):
        hints.append(
            f"💾 当前服务的上下游包含**缓存** ({', '.join(all_types['cache'][:3])})。"
            f"建议检查缓存命中率、过期策略和内存使用情况。"
        )
    
    # Upstream has changes → high priority alert
    if upstream_changes:
        change_names = [c.get('name', '?') for c in upstream_changes[:3]]
        hints.insert(0,
            f"⚠️ **上游系统有变更记录**: {', '.join(change_names)}。"
            f"上游变更是根因的高概率来源，请优先排查这些变更与当前故障的时间关联性。"
        )
    
    # Downstream impact → consider war-room coordination
    if downstream_nodes and len(downstream_nodes) >= 2:
        wr_skill = loader.get('war-room-coordination')
        if wr_skill and wr_skill.name not in {s.name for s in additional_skills}:
            additional_skills.append(wr_skill)
        hints.append(
            f"📢 当前故障影响了 {len(downstream_nodes)} 个下游系统，"
            f"可能造成级联影响。建议通过 `war-room-coordination` 同步通知下游负责人。"
        )
    
    hints_text = '\n\n'.join(hints) if hints else ""
    return additional_skills, hints_text


# Simple topology type classification (mirrors app.py _classify_dependency_types)
def _classify_node_types(
    nodes: List[Dict[str, Any]],
    node_ids: List[str],
) -> Dict[str, List[str]]:
    """Classify nodes by type using name heuristics."""
    types: Dict[str, List[str]] = {
        'database': [], 'message_queue': [], 'cache': [],
        'third_party': [], 'gateway': [], 'storage': [], 'other': [],
    }
    
    db_kw = ['db', 'database', 'postgres', 'mysql', 'oracle', 'mongo', 'sql', 'db2', 'tidb']
    mq_kw = ['mq', 'kafka', 'rabbitmq', 'rocketmq', 'pulsar', 'qrep', 'queue']
    cache_kw = ['cache', 'redis', 'memcached', 'caffeine']
    tp_kw = ['third', 'external', 'api', 'gateway', 'payment', 'sms', 'push']
    gw_kw = ['gateway', 'nginx', 'apigw', 'kong', 'zuul', 'ingress']
    storage_kw = ['oss', 's3', 'minio', 'ceph', 'nas', 'nfs', 'hdfs']
    
    for i, node in enumerate(nodes):
        name = str(node.get('name', node_ids[i] if i < len(node_ids) else '')).lower()
        node_type = str(node.get('type', '')).lower()
        
        if any(k in name or k in node_type for k in db_kw):
            types['database'].append(node.get('name', node_ids[i]))
        elif any(k in name or k in node_type for k in mq_kw):
            types['message_queue'].append(node.get('name', node_ids[i]))
        elif any(k in name or k in node_type for k in cache_kw):
            types['cache'].append(node.get('name', node_ids[i]))
        elif any(k in name or k in node_type for k in tp_kw):
            types['third_party'].append(node.get('name', node_ids[i]))
        elif any(k in name or k in node_type for k in gw_kw):
            types['gateway'].append(node.get('name', node_ids[i]))
        elif any(k in name or k in node_type for k in storage_kw):
            types['storage'].append(node.get('name', node_ids[i]))
        else:
            types['other'].append(node.get('name', node_ids[i]))
    
    return {k: v for k, v in types.items() if v}
