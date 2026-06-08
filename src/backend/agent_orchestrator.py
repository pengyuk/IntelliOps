"""
Agent Orchestrator — coordinates multiple skills and agents during incident response.

The Orchestrator is the "brain" that:
1. Receives a user request with full incident context
2. Routes to the right skill(s) via SkillRouter
3. Builds an enriched LLM prompt with skill context
4. Manages multi-turn conversation state across agents
5. Tracks which agent said what (Agent Timeline)
6. Decides when to escalate or switch skills

This replaces the hardcoded orchestration logic previously embedded in app.py routes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .skill_loader import SkillLoader, Skill, get_skill_loader
from .skill_router import SkillRouter, IntentResult, RouteResult


# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------

@dataclass
class AgentIdentity:
    """Identifies which agent/skill is speaking."""
    agent_type: str       # "skill" | "system" | "human"
    agent_name: str       # skill name or "copilot" / "system"
    display_name: str     # Human-readable name
    icon: str = "🤖"


# Predefined agent identities
AGENT_IDENTITIES = {
    "incident-diagnosis": AgentIdentity(
        agent_type="skill", agent_name="incident-diagnosis",
        display_name="诊断 Agent", icon="🔍",
    ),
    "log-analysis": AgentIdentity(
        agent_type="skill", agent_name="log-analysis",
        display_name="日志分析 Agent", icon="📋",
    ),
    "script-operations": AgentIdentity(
        agent_type="skill", agent_name="script-operations",
        display_name="脚本执行 Agent", icon="⚡",
    ),
    "postmortem-generator": AgentIdentity(
        agent_type="skill", agent_name="postmortem-generator",
        display_name="复盘生成 Agent", icon="📝",
    ),
    "knowledge-retrieval": AgentIdentity(
        agent_type="skill", agent_name="knowledge-retrieval",
        display_name="知识检索 Agent", icon="📚",
    ),
    "war-room-coordination": AgentIdentity(
        agent_type="skill", agent_name="war-room-coordination",
        display_name="协同指挥 Agent", icon="📢",
    ),
    "copilot": AgentIdentity(
        agent_type="system", agent_name="copilot",
        display_name="IntelliOps Copilot", icon="🧠",
    ),
    "system": AgentIdentity(
        agent_type="system", agent_name="system",
        display_name="系统", icon="⚙️",
    ),
}


# ---------------------------------------------------------------------------
# Agent timeline entry
# ---------------------------------------------------------------------------

@dataclass
class AgentTimelineEntry:
    """Records an action taken by an agent."""
    timestamp: str
    agent: AgentIdentity
    action: str                       # "analyze" | "suggest" | "execute" | "ask" | "respond"
    summary: str
    detail: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """Coordinates multi-agent skill execution for incident response."""
    
    def __init__(self, loader: Optional[SkillLoader] = None):
        self._loader = loader
        self._router: Optional[SkillRouter] = None
        self._timeline: List[AgentTimelineEntry] = []
        self._active_skill: Optional[str] = None
    
    async def _init(self) -> None:
        if self._loader is None:
            self._loader = await get_skill_loader()
        if self._router is None:
            self._router = SkillRouter(self._loader)
    
    async def process_request(
        self,
        user_message: str,
        user_id: str,
        incident: Dict[str, Any],
        diagnosis: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> OrchestratorResult:
        """Process a user request through the agent orchestration pipeline.
        
        Returns enriched context for the LLM + metadata for the UI.
        """
        await self._init()
        
        # Step 1: Route to skills
        route_result = await self._router.route(user_message, incident, diagnosis)
        
        # Step 2: Record agent activity
        primary_skill = route_result.intent.primary_skill
        if primary_skill:
            self._active_skill = primary_skill.name
            agent_id = AGENT_IDENTITIES.get(primary_skill.name, AGENT_IDENTITIES["copilot"])
            self._add_timeline(agent_id, "analyze", 
                             f"Skill [{primary_skill.name}] activated for intent: {route_result.intent.intent}")
        
        # Step 3: Build the enriched system prompt
        system_prompt = self._build_orchestrated_system_prompt(route_result, incident, diagnosis)
        
        # Step 4: Build the user prompt with skill guidance
        user_prompt = self._build_orchestrated_user_prompt(
            user_message, route_result, incident, diagnosis, conversation_history
        )
        
        # Step 5: Collect UI-facing metadata
        active_agents = []
        for skill in route_result.active_skills:
            agent_id = AGENT_IDENTITIES.get(skill.name)
            if agent_id:
                active_agents.append({
                    "name": agent_id.agent_name,
                    "display_name": agent_id.display_name,
                    "icon": agent_id.icon,
                    "is_primary": (skill.name == (primary_skill.name if primary_skill else "")),
                })
        
        return OrchestratorResult(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            route_result=route_result,
            active_agents=active_agents,
            primary_skill_name=primary_skill.name if primary_skill else None,
            timeline=self._timeline[-5:],  # last 5 entries
        )
    
    def _add_timeline(self, agent: AgentIdentity, action: str, summary: str, 
                      detail: Dict[str, Any] = None) -> None:
        from datetime import datetime
        self._timeline.append(AgentTimelineEntry(
            timestamp=datetime.utcnow().isoformat() + 'Z',
            agent=agent,
            action=action,
            summary=summary,
            detail=detail or {},
        ))
    
    def _build_orchestrated_system_prompt(
        self,
        route: RouteResult,
        incident: Dict[str, Any],
        diagnosis: Optional[Dict[str, Any]],
    ) -> str:
        """Build system prompt with skill context injected."""
        parts = []
        
        # Base Copilot identity
        parts.append("""你是一个 IntelliOps 故障应急 Copilot，正在协助运维人员排查线上故障。

你的核心职责：
1. 理解当前诊断上下文并按照激活技能的步骤执行
2. 根据运维人员的输入更新根因假设
3. 信息不足时提出精准追问（每次最多1-2个）
4. 推荐下一步可执行动作（只读优先，高风险需标注）
5. 以友好、专业、简洁的风格回复

## 输出格式（严格JSON）
{
  "response": "对运维人员的回复（自然语言）",
  "active_skill": "当前使用的技能名称",
  "updated_root_causes": [
    {"cause": "根因描述", "confidence": 0.0-1.0, "change": "increased|decreased|unchanged|new", "rationale": "理由"}
  ],
  "suggested_actions": [
    {"action": "建议动作", "type": "query|verify|mitigate|escalate", "risk": "low|medium|high", "rationale": "理由"}
  ],
  "follow_up_question": "下一个追问（可为空）",
  "confidence_trend": "improving|stable|declining",
  "key_findings": ["关键发现"],
  "next_skill_suggestion": "建议下一个激活的技能（可为空）"
}
""")
        
        # Inject skill context
        if route.skill_context_prompt:
            parts.append(route.skill_context_prompt)
        
        # Safety rules
        parts.append("""
## 安全规则
- 优先使用只读验证动作（查日志、看指标），避免直接建议重启或变更
- 高风险操作（risk: high）必须标注并建议走审批流程
- 每次回复最多提1个追问
""")
        
        return "\n\n".join(parts)
    
    def _build_orchestrated_user_prompt(
        self,
        user_message: str,
        route: RouteResult,
        incident: Dict[str, Any],
        diagnosis: Optional[Dict[str, Any]],
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> str:
        """Build user prompt with full incident + skill context."""
        parts = []
        
        # Incident context
        parts.append(f"## 当前事件\n事件ID: {incident.get('incident_id', 'N/A')}")
        parts.append(f"摘要: {incident.get('summary', 'N/A')}")
        parts.append(f"状态: {incident.get('status', 'Investigating')}")
        parts.append(f"影响服务: {incident.get('affected_services', [])}")
        
        # Diagnosis context
        if diagnosis:
            causes = diagnosis.get('candidate_root_causes', [])
            if causes:
                parts.append("\n### 当前根因假设")
                for i, c in enumerate(causes[:5], 1):
                    conf = c.get('confidence', 0)
                    parts.append(f"{i}. [{conf:.0%}] {c.get('cause', '未知')}")
            
            log_summary = diagnosis.get('log_analysis', {}).get('summary', '')
            if log_summary:
                parts.append(f"\n### 日志分析摘要\n{log_summary[:300]}")
        
        # Conversation history
        if conversation_history:
            parts.append("\n### 历史对话")
            for turn in conversation_history[-6:]:
                role = turn.get('role', 'unknown')
                content = turn.get('content', '')[:200]
                parts.append(f"[{role}]: {content}")
        
        # Active skills summary
        skill_names = [s.name for s in route.active_skills]
        parts.append(f"\n### 激活技能\n{', '.join(skill_names)}")
        
        # User message
        parts.append(f"\n---\n## 运维人员最新输入\n{user_message}")
        parts.append("\n请根据以上上下文给出你的分析回复（JSON）。")
        
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class OrchestratorResult:
    """Complete result from orchestrator processing."""
    system_prompt: str
    user_prompt: str
    route_result: RouteResult
    active_agents: List[Dict[str, Any]]
    primary_skill_name: Optional[str]
    timeline: List[AgentTimelineEntry]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_orchestrator: Optional[AgentOrchestrator] = None


async def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
        await _orchestrator._init()
    return _orchestrator


def reset_orchestrator() -> None:
    global _orchestrator
    _orchestrator = None
