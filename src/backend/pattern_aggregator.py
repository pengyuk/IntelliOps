"""
Pattern Aggregator — detects high-frequency alert patterns and triggers batch refinement.

When the same root cause rule / SOP template accumulates N source incidents:
  1. Triggers a batch LLM distillation across all source incidents to produce a
     refined, high-quality "canonical" pattern.
  2. Generates auto-remediation readiness score (if SOP steps are fully automatable).
  3. Produces threshold calibration suggestions for monitoring.
  4. Marks the pattern as "mature" so SkillUpdater can inject it into SKILL.md.

This solves the "高频告警重复知识" problem by collapsing many similar incidents
into one authoritative knowledge asset, rather than storing N near-identical entries.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .db import get_db
from .llm_client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt templates for batch refinement
# ---------------------------------------------------------------------------

PATTERN_REFINEMENT_SYSTEM = """\
你是 SRE 知识工程专家。你的任务是将多个相似故障案例聚合并提炼为一个权威的故障模式。

输入：多个来源于不同 incident 的同类根因规则 / SOP / 预警信号。
输出：一个精炼后的权威版本，包含：

1. **权威模式描述** — 合并所有案例的共性，去掉个例噪声
2. **触发条件（全集）** — 合并所有案例中出现的触发条件，去重排序
3. **综合置信度** — 基于出现频率和每条置信度的加权平均
4. **自动化就绪度** (0-1) — 表示该模式的处置步骤是否可完全自动化
5. **监控阈值校准建议** — 基于告警出现模式，建议调整的监控阈值
6. **跨服务影响模式** — 该故障是否会在多个服务间传播

输出严格 JSON 格式。
"""

PATTERN_REFINEMENT_USER = """\
## 聚合任务：{asset_type}

该类资产已出现 {count} 次，需要聚合为一个权威模式。

### 现有资产列表
{items_json}

### 来源 Incident 上下文摘要
{contexts_json}

请生成聚合后的权威 JSON（严格 JSON 格式，无 markdown 包裹）：
{{
  "canonical_pattern": "精炼后的权威模式描述",
  "merged_conditions": ["条件1", "条件2"],
  "confidence": 0.0-1.0,
  "auto_remediation_readiness": 0.0-1.0,
  "auto_remediation_reason": "打分理由",
  "threshold_calibrations": [
    {{
      "metric": "监控指标",
      "current_threshold": "当前值",
      "suggested_threshold": "建议值",
      "rationale": "调整理由"
    }}
  ],
  "cross_service_pattern": "跨服务传播模式描述（若无则填'无'）",
  "source_incidents": {source_incidents}
}}
"""


async def aggregate_and_refine(
    asset_type: str,
    items: List[Dict[str, Any]],
    source_incidents: List[str],
) -> Optional[Dict[str, Any]]:
    """
    Use LLM to batch-refine multiple similar assets into one canonical version.

    Returns refined canonical asset dict, or None if LLM unavailable.
    """
    client = LLMClient()
    if client.provider not in ("openai", "anthropic", "ollama"):
        logger.info("No LLM available for pattern refinement; using heuristic merge.")
        return _heuristic_merge(items, asset_type, source_incidents)

    # Compact items for prompt efficiency
    compact_items = []
    for item in items[:10]:  # limit to 10 to stay within token budget
        c = dict(item)
        if "code" in c:
            c["code"] = (c["code"] or "")[:300]
        compact_items.append(c)

    contexts = []
    db = get_db()
    for sid in source_incidents[:10]:
        inc = await db.get_incident(sid)
        if inc:
            contexts.append({
                "incident_id": sid,
                "title": inc.get("title", inc.get("alert_summary", "")),
                "severity": inc.get("severity", ""),
            })
        else:
            contexts.append({"incident_id": sid, "title": "", "severity": ""})

    user_prompt = PATTERN_REFINEMENT_USER.format(
        asset_type=asset_type,
        count=len(source_incidents),
        items_json=json.dumps(compact_items, ensure_ascii=False, indent=2),
        contexts_json=json.dumps(contexts, ensure_ascii=False, indent=2),
        source_incidents=json.dumps(source_incidents),
    )

    try:
        response: LLMResponse = await client.infer(
            prompt=user_prompt,
            system=PATTERN_REFINEMENT_SYSTEM,
            json_mode=(client.provider == "openai"),
            temperature=0.1,
            max_tokens=2048,
        )
        result = _extract_json(response.text.strip())
        result["_aggregated"] = True
        result["_source_count"] = len(source_incidents)
        result["_asset_type"] = asset_type
        result["method"] = "llm_batch_refine"
        result["model"] = response.model
        return result
    except Exception as e:
        logger.warning(f"LLM batch refinement failed: {e}; falling back to heuristic merge.")
        return _heuristic_merge(items, asset_type, source_incidents)


def _heuristic_merge(
    items: List[Dict[str, Any]],
    asset_type: str,
    source_incidents: List[str],
) -> Dict[str, Any]:
    """Merge similar items using rule-based heuristics (no LLM)."""
    if asset_type == "root_cause_rules":
        patterns = [i.get("pattern", "") for i in items if i.get("pattern")]
        # Use the most detailed pattern
        best_pattern = max(patterns, key=len) if patterns else "合并模式"

        all_conditions: List[str] = []
        seen_conds = set()
        for i in items:
            for c in i.get("conditions", []):
                if c not in seen_conds:
                    all_conditions.append(c)
                    seen_conds.add(c)

        confidences = [i.get("confidence", 0.5) for i in items]
        avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.5

        # Most common category
        categories = [i.get("category", "") for i in items if i.get("category")]
        top_cat = max(set(categories), key=categories.count) if categories else "performance"

        return {
            "canonical_pattern": best_pattern,
            "merged_conditions": all_conditions,
            "confidence": avg_conf,
            "auto_remediation_readiness": 0.5,
            "auto_remediation_reason": "基于规则合并，未使用LLM精炼",
            "threshold_calibrations": [],
            "cross_service_pattern": "无",
            "source_incidents": source_incidents,
            "method": "heuristic_merge",
        }

    elif asset_type == "sop_templates":
        # Combine all steps into a master SOP
        all_steps: List[str] = []
        seen_steps = set()
        for i in items:
            for step in i.get("steps", []):
                if step not in seen_steps:
                    all_steps.append(step)
                    seen_steps.add(step)

        titles = [i.get("title", "") for i in items if i.get("title")]
        best_title = max(titles, key=len) if titles else "标准处置流程"

        return {
            "canonical_pattern": best_title,
            "merged_conditions": [],
            "confidence": 0.7,
            "auto_remediation_readiness": 0.6 if len(all_steps) <= 5 else 0.3,
            "auto_remediation_reason": "SOP合并完成，自动化程度取决于步骤数量和复杂度",
            "threshold_calibrations": [],
            "cross_service_pattern": "无",
            "source_incidents": source_incidents,
            "method": "heuristic_merge",
            "_aggregated_sop": {
                "title": best_title,
                "steps": all_steps,
                "source_count": len(source_incidents),
            },
        }

    else:
        return {
            "canonical_pattern": f"合并{asset_type}（{len(source_incidents)}个来源）",
            "merged_conditions": [],
            "confidence": 0.5,
            "auto_remediation_readiness": 0.3,
            "source_incidents": source_incidents,
            "method": "heuristic_merge",
        }


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from LLM response (handles markdown fences)."""
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
        raise


async def find_high_frequency_patterns() -> List[Dict[str, Any]]:
    """
    Scan the knowledge base for asset types with >= HIGH_FREQ_THRESHOLD source incidents.
    Returns a list of patterns ready for batch refinement.
    """
    db = get_db()
    all_knowledge = await db.list_knowledge()

    patterns_to_refine: List[Dict[str, Any]] = []

    # Count source incidents per pattern
    from .knowledge_deduplicator import HIGH_FREQ_THRESHOLD

    asset_type_counts: Dict[str, Dict[str, Dict]] = {}

    for kn in all_knowledge:
        for asset_type in ["root_cause_rules", "sop_templates", "warning_signals"]:
            items = kn.get(asset_type, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                sources = item.get("source_incidents", [])
                # Also consider _merge_count
                merge_count = item.get("_merge_count", 1)
                total_count = max(len(sources), merge_count)

                if total_count >= HIGH_FREQ_THRESHOLD:
                    pattern_key = item.get("pattern", item.get("title", item.get("name", "")))
                    if not pattern_key:
                        continue
                    if asset_type not in asset_type_counts:
                        asset_type_counts[asset_type] = {}
                    if pattern_key not in asset_type_counts[asset_type]:
                        asset_type_counts[asset_type][pattern_key] = {
                            "items": [],
                            "source_incidents": set(),
                        }
                    asset_type_counts[asset_type][pattern_key]["items"].append(item)
                    asset_type_counts[asset_type][pattern_key]["source_incidents"].update(sources)

    for asset_type, patterns in asset_type_counts.items():
        for pattern_key, data in patterns.items():
            patterns_to_refine.append({
                "asset_type": asset_type,
                "pattern_key": pattern_key,
                "items": data["items"],
                "source_incidents": sorted(data["source_incidents"]),
                "count": len(data["source_incidents"]),
            })

    return patterns_to_refine


async def run_pattern_aggregation(
    patterns: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Main entry point for pattern aggregation.

    If patterns is None, scans the DB automatically for high-frequency patterns.
    Returns a list of refined canonical patterns.
    """
    if patterns is None:
        patterns = await find_high_frequency_patterns()

    refined_patterns = []
    for pattern in patterns:
        logger.info(
            "Aggregating %s pattern '%s' (%d incidents)",
            pattern["asset_type"],
            pattern["pattern_key"],
            pattern["count"],
        )
        result = await aggregate_and_refine(
            asset_type=pattern["asset_type"],
            items=pattern["items"],
            source_incidents=pattern["source_incidents"],
        )
        if result:
            refined_patterns.append(result)

    return refined_patterns
