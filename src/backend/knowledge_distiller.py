"""
Knowledge Distiller — extracts reusable knowledge assets from postmortem reports.

Input:  postmortem report (timeline + root cause + decisions + scripts)
Output: structured knowledge assets ready for the knowledge base:
  - Root cause rules (generalized patterns)
  - Early warning signals
  - SOP templates (step-by-step)
  - Script recommendations (with code snippets)
  - Key learnings (human-readable takeaways)

LLM-powered extraction with rule-based fallback.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient, LLMResponse


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

DISTILLER_SYSTEM = """\
你是一个 SRE 知识工程专家。你的任务是将故障复盘报告提炼为可复用的知识资产。

提炼原则：
1. 根因规则：从具体根因中抽象出通用模式（不包含具体服务名/人名/时间）
2. 预警信号：识别可以提前检测的指标异常模式
3. SOP 模板：将排查步骤转化为步骤化的标准操作流程
4. 脚本推荐：为关键检查点生成可复用的脚本片段
5. 关键教训：用 2-3 句话总结本次故障最重要的经验

输出格式（严格 JSON）：
{
  "knowledge_id": "自动生成",
  "root_cause_rules": [
    {
      "rule_id": "自动生成",
      "pattern": "通用故障模式描述",
      "conditions": ["触发条件1", "触发条件2"],
      "confidence": 0.0-1.0,
      "source_incidents": ["来源事件ID"],
      "category": "performance|availability|capacity|configuration|dependency"
    }
  ],
  "warning_signals": [
    {
      "signal_id": "自动生成",
      "metric": "监控指标名称",
      "threshold": "阈值描述",
      "description": "预警说明",
      "severity": "critical|high|medium"
    }
  ],
  "sop_templates": [
    {
      "sop_id": "自动生成",
      "title": "SOP 标题",
      "steps": ["步骤1", "步骤2", "步骤3"],
      "estimated_time": "预计耗时",
      "required_roles": ["需要的角色"],
      "risk_level": "low|medium|high"
    }
  ],
  "script_recommendations": [
    {
      "script_id": "自动生成",
      "name": "脚本名称",
      "description": "脚本用途",
      "language": "bash|python|sql",
      "code": "脚本代码片段",
      "category": "diagnosis|mitigation|verification"
    }
  ],
  "key_learnings": ["教训1", "教训2", "教训3"],
  "related_tags": ["标签1", "标签2"]
}

重要：根因规则必须泛化——不要包含具体的主机名、IP、人名或时间戳。
"""

DISTILLER_USER = """\
## 复盘报告
{postmortem_json}

请提炼上述复盘报告，生成结构化的知识资产（JSON）。"""


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------

def _rule_based_distill(postmortem: Dict[str, Any]) -> Dict[str, Any]:
    """Extract knowledge assets using heuristics (no LLM)."""
    root_cause = postmortem.get("root_cause_conclusion", {})
    cause_text = root_cause.get("cause", "")
    confidence = root_cause.get("confidence", 0.5)
    incident_id = postmortem.get("incident_id", "")
    timeline = postmortem.get("timeline", [])
    decisions = postmortem.get("decisions", [])
    scripts_used = postmortem.get("scripts_used", [])

    # Extract root cause rules
    rules = []
    if cause_text:
        # Categorize the cause
        category = "performance"
        if any(w in cause_text.lower() for w in ("内存", "cpu", "磁盘", "disk", "memory", "oom")):
            category = "capacity"
        elif any(w in cause_text.lower() for w in ("配置", "config", "参数", "param")):
            category = "configuration"
        elif any(w in cause_text.lower() for w in ("依赖", "dependency", "下游", "上游")):
            category = "dependency"
        elif any(w in cause_text.lower() for w in ("错误", "失败", "error", "fail", "500")):
            category = "availability"

        # Generate conditions from timeline
        conditions = []
        for event in timeline[:5]:
            if event.get("event_type") in ("alert", "diagnosis", "action_result"):
                conditions.append(f"检测到: {event.get('summary', '')[:80]}")

        rules.append({
            "rule_id": f"rule-{incident_id}",
            "pattern": cause_text[:120],
            "conditions": conditions[:3] or ["需补充具体触发条件"],
            "confidence": confidence,
            "source_incidents": [incident_id],
            "category": category,
        })

    # Extract warning signals from timeline
    signals = []
    alert_events = [e for e in timeline if e.get("event_type") == "alert"]
    for event in alert_events[:2]:
        signals.append({
            "signal_id": f"sig-{incident_id}-{len(signals)+1}",
            "metric": event.get("summary", "未知指标")[:60],
            "threshold": "超过基线阈值（具体值需根据历史数据设定）",
            "description": event.get("summary", "")[:100],
            "severity": "high",
        })
    if not signals:
        signals.append({
            "signal_id": f"sig-{incident_id}-1",
            "metric": "服务响应时间 P99",
            "threshold": "> 正常基线的 3 倍",
            "description": "响应时间突然升高通常预示下游资源瓶颈",
            "severity": "high",
        })

    # Generate SOP template from timeline + decisions
    sop_steps = []
    for event in timeline:
        etype = event.get("event_type", "")
        if etype in ("diagnosis", "action_execution", "action_result"):
            sop_steps.append(event.get("summary", "")[:100])
    if not sop_steps:
        sop_steps = [
            "确认告警并创建事故",
            "收集受影响服务的最近30分钟日志",
            "检查关联变更记录",
            "执行只读诊断脚本验证假设",
            "根据诊断结果执行修复动作",
            "确认恢复并关闭事故",
        ]
    sop = {
        "sop_id": f"sop-{incident_id}",
        "title": f"故障处理流程: {cause_text[:40] or '未知根因'}",
        "steps": sop_steps[:7],
        "estimated_time": "30-45 分钟",
        "required_roles": ["运维人员", "开发负责人"],
        "risk_level": "medium",
    }

    # Script recommendations from used scripts
    script_recs = []
    for script in scripts_used[:3]:
        if isinstance(script, dict):
            script_recs.append({
                "script_id": f"rec-{script.get('script_id', '')}",
                "name": script.get("name", "诊断脚本"),
                "description": script.get("explanation", ""),
                "language": script.get("language", "bash"),
                "code": script.get("code", "# 待补充"),
                "category": "diagnosis",
            })

    # Key learnings
    learnings = [
        f"根因: {cause_text[:80]}（置信度 {confidence:.0%}）",
        f"建议将相关指标纳入监控告警以提前发现",
        "复盘后应将验证过的脚本和SOP入库供后续复用",
    ]

    # Tags
    tags = ["故障复盘"]
    for event_type in {e.get("event_type", "") for e in timeline}:
        if "action" in event_type:
            tags.append("自动化处置")
        if "diagnosis" in event_type:
            tags.append("AI诊断")
    if confidence > 0.7:
        tags.append("高置信度")

    return {
        "postmortem_id": postmortem.get("postmortem_id", ""),
        "knowledge_id": f"kn-{incident_id}",
        "root_cause_rules": rules,
        "warning_signals": signals,
        "sop_templates": [sop],
        "script_recommendations": script_recs,
        "key_learnings": learnings,
        "related_tags": list(set(tags)),
        "method": "rule_based",
        "distilled_at": "",
        # P1-2: Feedback loop fields
        "verified_count": 0,
        "false_positive_count": 0,
        "dynamic_weight": confidence,  # starts at original confidence, adjusted by feedback
        "last_feedback_at": "",
    }


# ---------------------------------------------------------------------------
# KnowledgeDistiller
# ---------------------------------------------------------------------------

class KnowledgeDistiller:
    """Distills postmortem reports into reusable knowledge assets."""

    @staticmethod
    async def distill(postmortem: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point — extract knowledge assets from a postmortem."""
        client = LLMClient()

        if client.provider in ("openai", "anthropic", "ollama"):
            try:
                return await KnowledgeDistiller._llm_distill(postmortem, client)
            except Exception:
                pass  # fall through to rule-based

        return _rule_based_distill(postmortem)

    @staticmethod
    async def _llm_distill(
        postmortem: Dict[str, Any],
        client: LLMClient,
    ) -> Dict[str, Any]:
        """LLM-powered knowledge distillation."""
        # Strip large fields for prompt efficiency
        compact = {
            "postmortem_id": postmortem.get("postmortem_id"),
            "incident_id": postmortem.get("incident_id"),
            "root_cause_conclusion": postmortem.get("root_cause_conclusion", {}),
            "decisions": postmortem.get("decisions", [])[:5],
            "timeline": [
                {"type": e.get("event_type"), "summary": e.get("summary", "")}
                for e in postmortem.get("timeline", [])[:15]
            ],
            "scripts_used": [
                {"name": s.get("name", ""), "explanation": s.get("explanation", ""), "code": (s.get("code", "") or "")[:200]}
                for s in postmortem.get("scripts_used", [])[:5]
            ],
            "improvement_suggestions": postmortem.get("improvement_suggestions", [])[:5],
        }

        user_prompt = DISTILLER_USER.format(
            postmortem_json=json.dumps(compact, ensure_ascii=False, indent=2),
        )

        response: LLMResponse = await client.infer(
            prompt=user_prompt,
            system=DISTILLER_SYSTEM,
            json_mode=(client.provider == "openai"),
            temperature=0.1,
            max_tokens=3072,
        )

        text = response.text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            text = "\n".join(lines).strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            if start >= 0:
                brace_level = 0
                for i, ch in enumerate(text[start:], start=start):
                    if ch == "{":
                        brace_level += 1
                    elif ch == "}":
                        brace_level -= 1
                        if brace_level == 0:
                            result = json.loads(text[start : i + 1])
                            break
                else:
                    raise ValueError("JSON extraction failed")
            else:
                raise ValueError("No JSON found in LLM response")

        result["method"] = "llm"
        result["model"] = response.model
        result["latency_ms"] = response.latency_ms
        result["distilled_at"] = ""
        # P1-2: Initialize feedback fields for LLM-distilled knowledge too
        if "verified_count" not in result:
            result["verified_count"] = 0
            result["false_positive_count"] = 0
            result["dynamic_weight"] = result.get("confidence", 0.5)
            result["last_feedback_at"] = ""
        return result


# ---------------------------------------------------------------------------
# P1-2: Knowledge Feedback Loop
# ---------------------------------------------------------------------------

class KnowledgeFeedbackManager:
    """Manages the feedback loop for distilled knowledge assets.
    
    When knowledge is reused in a real incident:
    - If the root cause rule correctly predicted the outcome → verified_count++
    - If the rule led to a wrong diagnosis → false_positive_count++
    
    The dynamic_weight is adjusted based on the verification ratio.
    Rules with high false_positive rates are automatically degraded.
    """
    
    @staticmethod
    def record_verification(
        knowledge_asset: Dict[str, Any],
        was_correct: bool,
        incident_id: str = "",
    ) -> Dict[str, Any]:
        """Record a verification result for a knowledge asset.
        
        Args:
            knowledge_asset: The knowledge asset dict (root_cause_rule, warning_signal, etc.)
            was_correct: True if the knowledge correctly predicted/helped, False if it was wrong
            incident_id: The incident where this verification occurred
        
        Returns:
            Updated knowledge asset with adjusted weight
        """
        from datetime import datetime
        
        if was_correct:
            knowledge_asset['verified_count'] = knowledge_asset.get('verified_count', 0) + 1
        else:
            knowledge_asset['false_positive_count'] = knowledge_asset.get('false_positive_count', 0) + 1
        
        knowledge_asset['last_feedback_at'] = datetime.utcnow().isoformat() + 'Z'
        
        # Recalculate dynamic_weight
        knowledge_asset['dynamic_weight'] = KnowledgeFeedbackManager._calculate_weight(knowledge_asset)
        
        # Track source incidents
        source_list = knowledge_asset.get('source_incidents', [])
        if incident_id and incident_id not in source_list:
            source_list.append(incident_id)
            knowledge_asset['source_incidents'] = source_list
        
        return knowledge_asset
    
    @staticmethod
    def _calculate_weight(asset: Dict[str, Any]) -> float:
        """Calculate dynamic weight based on verification history.
        
        Formula: base_confidence × (verified + 1) / (verified + false_positive + 2)
        This is a smoothed ratio that starts near base_confidence and adjusts with evidence.
        """
        base = asset.get('confidence', asset.get('dynamic_weight', 0.5))
        verified = asset.get('verified_count', 0)
        false_pos = asset.get('false_positive_count', 0)
        
        # Smooth ratio: (verified + 1) / (verified + false_positive + 2)
        # +1/+2 for Laplace smoothing (avoids 0/0)
        ratio = (verified + 1) / (verified + false_pos + 2)
        
        # Blend with original confidence
        weight = round(base * 0.4 + ratio * 0.6, 2)
        return max(0.1, min(1.0, weight))
    
    @staticmethod
    def get_reliability_level(asset: Dict[str, Any]) -> str:
        """Get human-readable reliability level for a knowledge asset."""
        weight = asset.get('dynamic_weight', asset.get('confidence', 0.5))
        verified = asset.get('verified_count', 0)
        false_pos = asset.get('false_positive_count', 0)
        
        if verified + false_pos == 0:
            return "unverified"  # 尚未经过实战验证
        
        if weight >= 0.75:
            return "reliable"     # 多次验证可靠
        elif weight >= 0.5:
            return "moderate"     # 部分验证
        elif false_pos > verified:
            return "degraded"     # 误判较多，已降权
        else:
            return "uncertain"
    
    @staticmethod
    def should_degrade(asset: Dict[str, Any]) -> bool:
        """Check if a knowledge asset should be degraded/warned about."""
        fp = asset.get('false_positive_count', 0)
        v = asset.get('verified_count', 0)
        if fp >= 3 and fp > v:
            return True
        if asset.get('dynamic_weight', 0.5) < 0.3:
            return True
        return False
    
    @staticmethod
    def format_feedback_summary(asset: Dict[str, Any]) -> str:
        """Generate a human-readable feedback summary."""
        v = asset.get('verified_count', 0)
        fp = asset.get('false_positive_count', 0)
        weight = asset.get('dynamic_weight', asset.get('confidence', 0.5))
        level = KnowledgeFeedbackManager.get_reliability_level(asset)
        
        level_emoji = {
            'reliable': '✅', 'moderate': '🟡', 'unverified': '⚪',
            'degraded': '🔴', 'uncertain': '🟠',
        }
        
        return (
            f"{level_emoji.get(level, '⚪')} 可靠性: {level} "
            f"(验证 {v} 次 / 误判 {fp} 次 / 权重 {weight:.0%})"
        )


# Convenience function
def apply_knowledge_feedback(
    knowledge_asset: Dict[str, Any],
    was_correct: bool,
    incident_id: str = "",
) -> Dict[str, Any]:
    """Apply feedback to a knowledge asset and return the updated version."""
    return KnowledgeFeedbackManager.record_verification(knowledge_asset, was_correct, incident_id)
