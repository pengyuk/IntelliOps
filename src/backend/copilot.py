"""
Copilot — stateful multi-turn diagnostic conversation agent.

Features:
- Per-diagnosis conversation history (memory across turns)
- Dynamic follow-up questions when evidence is insufficient
- Root cause confidence updating based on new user input
- Structured responses: analysis + updated causes + suggested actions + next question
- LLM-powered with rule-based fallback
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient, LLMResponse

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

COPILOT_SYSTEM = """\
你是一个 IntelliOps 故障应急 Copilot（副驾驶），正在协助运维人员排查线上故障。

你的职责：
1. 理解当前诊断上下文（根因假设、置信度、已收集的证据）
2. 根据运维人员的新输入，更新根因假设或确认已有推论
3. 如果信息不足，提出 1-2 个精准的追问（不要一次问太多）
4. 推荐下一步可执行的动作（只读优先，高风险需标注）
5. 以友好、专业、简洁的风格回复

输出格式（严格 JSON）：
{
  "response": "对运维人员的回复（自然语言，2-4句话）",
  "updated_root_causes": [
    {"cause": "根因描述", "confidence": 0.0-1.0, "change": "increased|decreased|unchanged|new", "rationale": "调整理由"}
  ],
  "suggested_actions": [
    {"action": "建议动作描述", "type": "query|verify|mitigate|escalate", "risk": "low|medium|high", "rationale": "推荐理由"}
  ],
  "follow_up_question": "如果需要更多信息，这里是下一个追问（可为空字符串）",
  "confidence_trend": "improving|stable|declining",
  "key_findings": ["本次对话中确认的关键发现"]
}

对话原则：
- 优先使用只读验证动作（查日志、看指标），避免直接建议重启或变更
- 当多个证据指向同一根因时，提高该根因的置信度
- 当用户提供的信息与当前假设矛盾时，降低置信度并探索新假设
- 每次回复最多提 1 个追问，不要让运维人员感到压迫
"""

COPILOT_USER_TEMPLATE = """\
## 当前诊断上下文
诊断ID: {diagnosis_id}
事件: {incident_summary}
状态: {incident_status}

### 当前根因假设
{root_causes_text}

### 已收集的日志分析摘要
{log_summary}

### 已执行的脚本/动作
{executed_actions}

### 历史对话
{conversation_history}

---
## 运维人员最新输入
{user_message}

请根据以上上下文给出你的分析回复（JSON）。"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_root_causes(causes: List[Dict[str, Any]]) -> str:
    if not causes:
        return "（暂无根因假设）"
    lines = []
    for i, c in enumerate(causes, 1):
        conf = c.get("confidence", 0)
        cause = c.get("cause", "未知")
        evidence = c.get("evidence_items", [])
        ev_str = "; ".join(evidence[:3]) if evidence else "无"
        lines.append(f"{i}. [{conf:.0%}] {cause}")
        lines.append(f"   证据: {ev_str}")
    return "\n".join(lines)


def _format_conversation_history(history: List[Dict[str, str]]) -> str:
    if not history:
        return "（尚无对话历史）"
    lines = []
    for turn in history[-6:]:  # last 6 turns to keep context manageable
        lines.append(f"[{turn.get('role', 'unknown')}]: {turn.get('content', '')}")
    return "\n".join(lines)


def _format_executed_actions(logs: List[Dict[str, Any]], incident_id: str) -> str:
    relevant = [log for log in logs if log.get("incident_id") == incident_id]
    if not relevant:
        return "（尚未执行任何脚本或动作）"
    lines = []
    for log in relevant[-5:]:
        lines.append(f"- {log.get('script_name', log.get('action_id', 'unknown'))}: {log.get('conclusion', log.get('output', ''))[:100]}")
    return "\n".join(lines)


def _extract_json(text: str) -> Dict[str, Any]:
    """Robust JSON extraction from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start >= 0:
        brace_level = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                brace_level += 1
            elif ch == "}":
                brace_level -= 1
                if brace_level == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError("Failed to extract JSON from LLM response")


# ---------------------------------------------------------------------------
# Skill context helpers — inject Skill/Agent awareness into prompts
# ---------------------------------------------------------------------------

_SKILL_DISPLAY_NAMES = {
    'incident-diagnosis': '🔍 故障诊断',
    'log-analysis': '📋 日志分析',
    'script-operations': '⚡ 脚本执行',
    'postmortem-generator': '📝 复盘生成',
    'knowledge-retrieval': '📚 知识检索',
    'war-room-coordination': '📢 应急协同',
}


def _format_skill_context_for_user_prompt(skill_context: Dict[str, Any]) -> str:
    """Build a skill context block for insertion into the user prompt."""
    lines = ["## 🧠 当前激活的智能体 (Active Agents)"]
    
    active_skills = skill_context.get('active_skills', [])
    primary = skill_context.get('primary_skill', '')
    intent = skill_context.get('route_intent', '')
    agents = skill_context.get('active_agents', [])
    
    if agents:
        for agent in agents:
            marker = '★ 主Agent' if agent.get('is_primary') else '  辅助Agent'
            lines.append(f"- {marker}: {agent.get('display_name', agent.get('name', ''))} ({agent.get('name', '')})")
    elif active_skills:
        for s in active_skills:
            marker = '★' if s == primary else ' '
            display = _SKILL_DISPLAY_NAMES.get(s, s)
            lines.append(f"- {marker} {display} ({s})")
    
    if intent:
        lines.append(f"\n当前意图: {intent}")
    
    lines.append("\n请按照激活智能体的职责和步骤来组织你的分析和建议。")
    return '\n'.join(lines)


def _inject_skill_into_system(base_system: str, skill_context: Dict[str, Any]) -> str:
    """Inject skill context into the system prompt."""
    skill_block = _format_skill_context_for_user_prompt(skill_context)
    
    # Insert after the first paragraph (the role description)
    lines = base_system.split('\n')
    injected_lines = []
    injected = False
    for line in lines:
        injected_lines.append(line)
        if not injected and line.startswith('你的职责'):
            injected_lines.append('')
            injected_lines.append(skill_block)
            injected = True
    
    return '\n'.join(injected_lines)


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------

class Copilot:
    """Stateful diagnostic conversation agent — now Skill-aware."""

    @staticmethod
    def _build_user_prompt(
        diagnosis: Dict[str, Any],
        user_message: str,
        action_logs: List[Dict[str, Any]],
        skill_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        base = COPILOT_USER_TEMPLATE.format(
            diagnosis_id=diagnosis.get("diagnosis_id", ""),
            incident_summary=diagnosis.get("incident_id", ""),
            incident_status="Investigating",
            root_causes_text=_format_root_causes(diagnosis.get("candidate_root_causes", [])),
            log_summary=diagnosis.get("log_analysis", {}).get("summary", "无日志分析"),
            executed_actions=_format_executed_actions(action_logs, diagnosis.get("incident_id", "")),
            conversation_history=_format_conversation_history(diagnosis.get("conversation_history", [])),
            user_message=user_message,
        )
        # Inject skill context if available
        if skill_context:
            skill_block = _format_skill_context_for_user_prompt(skill_context)
            # Insert skill context right before the user message
            base = base.replace(
                "## 运维人员最新输入",
                skill_block + "\n\n---\n## 运维人员最新输入"
            )
        return base

    @staticmethod
    async def chat(
        diagnosis: Dict[str, Any],
        user_id: str,
        user_message: str,
        action_logs: Optional[List[Dict[str, Any]]] = None,
        skill_context: Optional[Dict[str, Any]] = None,
        skill_system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a user message and return Copilot's response.

        Updates diagnosis in-place with new conversation history and root causes.
        
        Args:
            skill_context: Dict with active_skills, primary_skill, active_agents, route_intent
            skill_system_prompt: Pre-built system prompt from orchestrator (overrides COPILOT_SYSTEM)
        """
        if action_logs is None:
            action_logs = []

        # Initialize conversation history if needed
        if "conversation_history" not in diagnosis:
            diagnosis["conversation_history"] = []

        # Append user message to history
        diagnosis["conversation_history"].append({
            "role": "operator",
            "user_id": user_id,
            "content": user_message,
            "timestamp": diagnosis.get("created_at", ""),
        })

        # Store skill context in diagnosis for future turns
        if skill_context:
            diagnosis["_skill_context"] = skill_context

        client = LLMClient()

        if client.provider in ("openai", "anthropic", "ollama"):
            try:
                print(f"[Copilot] Using LLM provider: {client.provider}")
                result = await Copilot._llm_chat(
                    diagnosis, user_message, action_logs, client,
                    skill_context=skill_context,
                    skill_system_prompt=skill_system_prompt,
                )
                result["method"] = "llm"
                return result
            except Exception as e:
                print(f"[Copilot] LLM failed, falling back to rule-based: {e}")
                pass  # fall through to rule-based

        print("[Copilot] Using rule-based fallback")
        result = Copilot._rule_based_chat(diagnosis, user_message, action_logs, skill_context=skill_context)
        result["method"] = "rule_based"
        return result

    @staticmethod
    async def _llm_chat(
        diagnosis: Dict[str, Any],
        user_message: str,
        action_logs: List[Dict[str, Any]],
        client: LLMClient,
        skill_context: Optional[Dict[str, Any]] = None,
        skill_system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """LLM-powered chat turn — now with skill context injection."""
        user_prompt = Copilot._build_user_prompt(
            diagnosis, user_message, action_logs,
            skill_context=skill_context,
        )

        # Use orchestrator's system prompt if provided, else inject skill into hardcoded
        system_prompt = skill_system_prompt if skill_system_prompt else COPILOT_SYSTEM
        if skill_context and not skill_system_prompt:
            system_prompt = _inject_skill_into_system(COPILOT_SYSTEM, skill_context)

        print(f"[Copilot] System prompt length: {len(system_prompt)} chars")

        response: LLMResponse = await client.infer(
            prompt=user_prompt,
            system=system_prompt,
            json_mode=(client.provider == "openai"),
            temperature=0.2,
            max_tokens=2048,
        )

        parsed = _extract_json(response.text)

        # Update diagnosis with new root causes if LLM provided them
        updated_causes = parsed.get("updated_root_causes")
        if updated_causes:
            # Merge: update existing, add new
            existing_causes = {c.get("cause", ""): c for c in diagnosis.get("candidate_root_causes", [])}
            merged = []
            for uc in updated_causes:
                cause_text = uc.get("cause", "")
                if cause_text in existing_causes:
                    existing = existing_causes[cause_text]
                    existing["confidence"] = uc.get("confidence", existing.get("confidence", 0.5))
                    existing["detail"] = uc.get("rationale", existing.get("detail", ""))
                    merged.append(existing)
                else:
                    merged.append({
                        "cause": cause_text,
                        "confidence": uc.get("confidence", 0.5),
                        "detail": uc.get("rationale", ""),
                        "evidence_items": [uc.get("rationale", "")],
                        "confidence_level": "medium",
                    })
            for cause_text, existing in existing_causes.items():
                if cause_text not in {uc.get("cause", "") for uc in updated_causes}:
                    merged.append(existing)
            diagnosis["candidate_root_causes"] = merged

        # Build response message
        result = {
            "response": parsed.get("response", "我已收到你的补充信息，正在分析中。"),
            "updated_root_causes": updated_causes or [],
            "suggested_actions": parsed.get("suggested_actions", []),
            "follow_up_question": parsed.get("follow_up_question", ""),
            "confidence_trend": parsed.get("confidence_trend", "stable"),
            "key_findings": parsed.get("key_findings", []),
            "method": "llm",
        }

        # Append Copilot response to history
        diagnosis["conversation_history"].append({
            "role": "copilot",
            "content": result["response"],
            "timestamp": "",
        })

        return result

    @staticmethod
    def _rule_based_chat(
        diagnosis: Dict[str, Any],
        user_message: str,
        action_logs: List[Dict[str, Any]],
        skill_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Rule-based fallback chat (no LLM) — now skill-aware."""
        msg_lower = user_message.lower()
        causes = diagnosis.get("candidate_root_causes", [])
        log_summary = diagnosis.get("log_analysis", {}).get("summary", "")
        
        # Use skill context to improve response quality
        primary_skill = (skill_context or {}).get('primary_skill', '')
        active_skills = (skill_context or {}).get('active_skills', [])

        # Detect user providing new evidence
        evidence_keywords = {
            "日志": "log",
            "log": "log",
            "指标": "metrics",
            "metric": "metrics",
            "连接池": "connection_pool",
            "connection pool": "connection_pool",
            "慢查询": "slow_query",
            "slow query": "slow_query",
            "变更": "change",
            "部署": "deploy",
            "cpu": "cpu",
            "内存": "memory",
            "memory": "memory",
        }
        detected_evidence = []
        for kw, ev_type in evidence_keywords.items():
            if kw in msg_lower:
                detected_evidence.append(ev_type)

        # Find matching root cause and boost confidence
        updated_causes = []
        confidence_trend = "stable"
        for c in causes:
            cause_text = c.get("cause", "").lower()
            boost = 0
            if detected_evidence:
                for ev in detected_evidence:
                    if ev in cause_text or any(
                        kw in cause_text for kw in evidence_keywords if evidence_keywords[kw] == ev
                    ):
                        boost += 0.05
            if boost > 0:
                c["confidence"] = min(1.0, c.get("confidence", 0.5) + boost)
                confidence_trend = "improving"
            updated_causes.append(c)

        # Generate response — now skill-aware
        skill_tag = ""
        if primary_skill:
            display = _SKILL_DISPLAY_NAMES.get(primary_skill, primary_skill)
            skill_tag = f"[{display}] "
        
        if detected_evidence:
            evidence_str = "、".join(detected_evidence)
            response = (
                f"{skill_tag}收到！你补充的{evidence_str}相关信息已纳入分析。"
                f"当前最可疑的假设是：{causes[0].get('cause', '待确认') if causes else '待确认'}（置信度 {causes[0].get('confidence', 0):.0%}）。"
                f"建议下一步：检查相关指标趋势，确认异常是否持续。"
            )
        elif "?" in user_message or "？" in user_message or "怎么" in user_message or "如何" in user_message:
            response = (
                f"{skill_tag}根据当前诊断上下文，日志分析显示：{log_summary[:80]}...。"
                f"建议按优先级排查：1) 确认最近变更 2) 检查依赖服务状态 3) 分析具体错误日志。"
                f"你有具体想深入了解的方面吗？"
            )
        else:
            response = (
                f"{skill_tag}已记录你的补充信息。当前有 {len(causes)} 个候选根因假设。"
                f"高置信度假设：{causes[0].get('cause', '暂无') if causes else '暂无'}。"
                f"建议继续收集证据来验证或排除当前假设。"
            )

        # Build suggested actions based on what's missing
        suggested_actions = []
        if "连接池" not in msg_lower and "connection" not in msg_lower:
            suggested_actions.append({
                "action": "检查数据库连接池状态（活跃连接数、等待队列）",
                "type": "query",
                "risk": "low",
                "rationale": "连接池耗尽是最常见的延迟根因之一，低成本验证。",
            })
        if "变更" not in msg_lower and "change" not in msg_lower and "部署" not in msg_lower:
            suggested_actions.append({
                "action": "核对故障时间窗口内的变更记录",
                "type": "query",
                "risk": "low",
                "rationale": "变更是故障的常见触发因素，优先排除。",
            })

        follow_up = ""
        if not detected_evidence:
            follow_up = "你有最近30分钟的日志片段或监控截图可以分享吗？"

        result = {
            "response": response,
            "updated_root_causes": updated_causes,
            "suggested_actions": suggested_actions,
            "follow_up_question": follow_up,
            "confidence_trend": confidence_trend,
            "key_findings": detected_evidence,
            "method": "rule_based",
        }

        # Append to history
        diagnosis["conversation_history"].append({
            "role": "copilot",
            "content": response,
            "timestamp": "",
        })

        return result
