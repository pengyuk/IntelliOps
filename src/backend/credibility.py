"""
Credibility Framework — confidence scoring, evidence provenance & risk assessment.

Provides:
- Multi-dimensional confidence scoring (LLM confidence × evidence quality × source reliability)
- Evidence chain construction with provenance tracking
- Risk assessment for recommended actions
- Uncertainty quantification and explanation

Integrates into the diagnosis pipeline to enrich reasoning output with credibility metadata.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _evidence_quality_score(evidence: List[str], candidate: Dict[str, Any]) -> float:
    """Score evidence quality: more distinct evidence sources → higher score."""
    evidence_items = candidate.get("evidence_items", evidence)
    n = len(evidence_items)
    if n == 0:
        return 0.3
    if n == 1:
        return 0.6
    if n <= 3:
        return 0.8
    return 0.95


def _source_reliability_score(method: str, has_log_analysis: bool) -> float:
    """Score source reliability: LLM > rules, with log analysis boosting both."""
    base = 0.9 if method == "llm" else 0.65
    if has_log_analysis:
        base = min(1.0, base + 0.1)
    return base


def _contradiction_penalty(candidates: List[Dict[str, Any]]) -> float:
    """Check for contradictory hypotheses — high variance in confidence suggests uncertainty."""
    if len(candidates) <= 1:
        return 1.0  # no penalty
    confidences = [c.get("confidence", 0.5) for c in candidates]
    # If top two candidates are very close, there's uncertainty
    sorted_conf = sorted(confidences, reverse=True)
    gap = sorted_conf[0] - sorted_conf[1] if len(sorted_conf) > 1 else 1.0
    if gap < 0.1:
        return 0.85  # high uncertainty — close candidates
    if gap < 0.2:
        return 0.92
    return 1.0  # clear winner


def assess_confidence(
    raw_confidence: float,
    method: str,
    evidence: List[str],
    candidate: Dict[str, Any],
    all_candidates: List[Dict[str, Any]],
    has_log_analysis: bool = False,
) -> Dict[str, Any]:
    """Calculate credibility-adjusted confidence score.

    Formula: adjusted = raw × evidence_quality × source_reliability × contradiction_penalty
    """
    eq = _evidence_quality_score(evidence, candidate)
    sr = _source_reliability_score(method, has_log_analysis)
    cp = _contradiction_penalty(all_candidates)
    adjusted = round(raw_confidence * eq * sr * cp, 2)

    credibility_level = "high" if adjusted >= 0.7 else ("medium" if adjusted >= 0.5 else "low")

    return {
        "raw_confidence": raw_confidence,
        "adjusted_confidence": adjusted,
        "credibility_level": credibility_level,
        "factors": {
            "evidence_quality": round(eq, 2),
            "source_reliability": round(sr, 2),
            "contradiction_penalty": round(cp, 2),
        },
        "explanation": _build_confidence_explanation(eq, sr, cp, adjusted, credibility_level),
    }


def _build_confidence_explanation(
    eq: float, sr: float, cp: float, adjusted: float, level: str,
) -> str:
    parts = []
    if eq < 0.7:
        parts.append("证据数量较少")
    else:
        parts.append("证据来源较充分")
    if sr < 0.8:
        parts.append("基于规则推理（非LLM）")
    else:
        parts.append("LLM推理+日志分析支撑")
    if cp < 0.95:
        parts.append("存在竞争假设，不确定性较高")
    else:
        parts.append("候选根因之间区分明显")
    return f"{'；'.join(parts)}。综合可信度：{level}（{adjusted:.0%}）。"


# ---------------------------------------------------------------------------
# Evidence chain construction
# ---------------------------------------------------------------------------

def build_evidence_chain(
    reasoning: Dict[str, Any],
    log_analysis: Optional[Dict[str, Any]] = None,
    kg_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build a traceable evidence chain with provenance."""
    chain = []

    # Source 1: Incident data
    chain.append({
        "source": "incident",
        "type": "事件数据",
        "content": f"事件状态与摘要",
        "reliability": "high",
    })

    # Source 2: KG context
    if kg_context:
        services = kg_context.get("services", [])
        alerts = kg_context.get("alerts", [])
        changes = kg_context.get("changes", [])
        if changes:
            chain.append({
                "source": "kg",
                "type": "变更记录",
                "content": f"关联 {len(changes)} 条变更",
                "reliability": "high",
            })
        if alerts:
            chain.append({
                "source": "kg",
                "type": "告警记录",
                "content": f"关联 {len(alerts)} 条告警",
                "reliability": "high",
            })
        if services:
            chain.append({
                "source": "kg",
                "type": "服务依赖",
                "content": f"受影响服务: {len(services)} 个",
                "reliability": "high",
            })

    # Source 3: Log analysis
    if log_analysis:
        method = log_analysis.get("method", "unknown")
        reliability = "high" if method == "llm" else "medium"
        chain.append({
            "source": "log_analyzer",
            "type": "日志分析",
            "content": log_analysis.get("summary", "")[:120],
            "reliability": reliability,
        })
        for corr in log_analysis.get("correlations", [])[:2]:
            chain.append({
                "source": "log_analyzer",
                "type": "跨源关联",
                "content": corr.get("pattern_description", "")[:120],
                "reliability": "medium",
            })

    # Source 4: Reasoning method
    method = reasoning.get("method", "unknown")
    chain.append({
        "source": "reasoner",
        "type": "推理引擎",
        "content": f"推理方法: {method}" + (f", 模型: {reasoning.get('model', '')}" if method == "llm" else ""),
        "reliability": "high" if method == "llm" else "medium",
    })

    return chain


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------

_RISK_PATTERNS = [
    (["restart", "reboot", "重启"], "high", "涉及服务重启，可能扩大影响范围"),
    (["delete", "drop", "truncate", "删除"], "high", "涉及数据破坏性操作，不可逆"),
    (["config", "配置", "参数"], "medium", "配置变更需验证回滚方案"),
    (["query", "查询", "select", "describe", "show"], "low", "只读操作，无破坏性"),
    (["log", "日志", "tail", "grep", "journalctl"], "low", "只读日志采集"),
    (["metric", "指标", "monitor"], "low", "只读指标检查"),
]


def assess_action_risk(action: Dict[str, Any]) -> Dict[str, Any]:
    """Assess risk level for a recommended action."""
    action_text = (action.get("action", "") + " " + action.get("name", "")).lower()
    risk = action.get("risk", "medium")

    for keywords, level, explanation in _RISK_PATTERNS:
        if any(kw in action_text for kw in keywords):
            risk = level
            return {
                "risk_level": risk,
                "risk_explanation": explanation,
                "requires_approval": risk == "high",
                "recommendation": "建议审批后执行" if risk == "high" else ("建议验证后执行" if risk == "medium" else "可直接执行"),
            }

    return {
        "risk_level": risk,
        "risk_explanation": "未匹配已知风险模式，请人工评估",
        "requires_approval": risk == "high",
        "recommendation": "建议人工评估后执行",
    }


def assess_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bulk risk assessment for a list of actions."""
    return [
        {**action, "risk_assessment": assess_action_risk(action)}
        for action in actions
    ]


# ---------------------------------------------------------------------------
# Main integration point
# ---------------------------------------------------------------------------

def enrich_diagnosis(
    diagnosis: Dict[str, Any],
    log_analysis: Optional[Dict[str, Any]] = None,
    kg_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Enrich a diagnosis with credibility metadata.

    This is the main hook called after diagnosis creation.
    It adds credibility scores, evidence chains, and risk assessments.
    """
    reasoning_method = diagnosis.get("method", diagnosis.get("candidate_root_causes", [{}])[0].get("method", "rule_based") if diagnosis.get("candidate_root_causes") else "rule_based")
    has_log = bool(log_analysis and log_analysis.get("summary"))

    # Enrich each candidate root cause with credibility
    candidates = diagnosis.get("candidate_root_causes", [])
    enriched_candidates = []
    for c in candidates:
        credibility = assess_confidence(
            raw_confidence=c.get("confidence", 0.5),
            method=diagnosis.get("method", reasoning_method),
            evidence=c.get("evidence_items", diagnosis.get("evidence", [])),
            candidate=c,
            all_candidates=candidates,
            has_log_analysis=has_log,
        )
        enriched_candidates.append({
            **c,
            "credibility": credibility,
        })
    diagnosis["candidate_root_causes"] = enriched_candidates

    # Build evidence chain
    diagnosis["evidence_chain"] = build_evidence_chain(
        reasoning=diagnosis,
        log_analysis=log_analysis,
        kg_context=kg_context,
    )

    # Update confidence summary with adjusted scores
    adjusted_scores = [c["credibility"]["adjusted_confidence"] for c in enriched_candidates]
    diagnosis["confidence_summary"] = round(sum(adjusted_scores) / max(len(adjusted_scores), 1), 2)

    # Risk-assess recommendations
    recommendations = diagnosis.get("initial_recommendations", [])
    if recommendations:
        # Map to action format for assessment
        actions = [{"action": r.get("step", ""), "risk": "medium"} for r in recommendations]
        assessed = assess_actions(actions)
        for i, rec in enumerate(recommendations):
            if i < len(assessed):
                rec["risk_assessment"] = assessed[i].get("risk_assessment", {})

    return diagnosis
