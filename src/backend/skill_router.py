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
        
        # Step 3: Build skill context prompt for LLM
        skill_context_prompt = _build_skill_context_prompt(active_skills, intent)
        
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
