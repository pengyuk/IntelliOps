"""
Pattern Aggregator — detects high-frequency alert patterns and triggers batch refinement.

When the same solution summary / SOP accumulates N source incidents:
  1. Triggers a batch LLM distillation across all source incidents to produce a
     refined, high-quality "canonical" solution summary.
  2. Generates auto-remediation solution steps + verification method.
  3. Produces solution practice recommendations (key points summary).
  4. Marks the solution as "mature" so SkillUpdater can inject it into SKILL.md.

This solves the "高频告警重复知识" problem by collapsing many similar solution summaries
into one authoritative knowledge asset — the SKILL — rather than storing N near-identical entries.
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
# Prompt templates for batch refinement — focused on SOLUTION SUMMARIES
# ---------------------------------------------------------------------------

PATTERN_REFINEMENT_SYSTEM = """\
你是 SRE 知识工程专家。你的任务是将多个来源于相似故障的解决方法聚合并提炼为一个权威的处置经验沉淀。

输入：多个来源于不同 incident 的同类解决方法描述。
输出：一个精炼后的权威版本，包含：

1. **问题模式 (problem)** — 合并所有案例的共性故障现象，去掉个例噪声
2. **解决方法 (solution)** — 合并后的最优处置步骤，按执行顺序排列
3. **使用场景 (scenario)** — 什么样的告警/现象下应该使用此方法
4. **处置要点 (key_points)** — 执行该方法时的关键注意事项、避坑指南
5. **验证方法 (verification)** — 如何验证该方法已生效
6. **自动处置脚本 (auto_remediation_script)** — 如果能自动化，给出脚本伪代码或具体命令

输出严格 JSON 格式，无 markdown 包裹。
不要输出置信度分数，SRE 知识是确定性的实践总结。
"""

PATTERN_REFINEMENT_USER = """\
## 聚合任务：{asset_type}

该类资产已出现 {count} 次，需要聚合为一个权威解决方法。

### 现有资产列表
{items_json}

### 来源 Incident 上下文摘要
{contexts_json}

请生成聚合后的权威 JSON（严格 JSON 格式，无 markdown 包裹）：
{{
  "problem": "精炼后的问题模式描述",
  "solution": "按顺序排列的解决方法",
  "scenario": ["使用场景1", "使用场景2"],
  "key_points": ["处置要点1", "处置要点2", "处置要点3"],
  "verification": "验证方法详细描述",
  "auto_remediation_script": "可选的自动处置脚本",
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

    Returns refined canonical solution summary, or None if LLM unavailable.
    """
    client = LLMClient()
    if client.provider not in ("openai", "anthropic", "ollama"):
        logger.info("No LLM available for pattern refinement; using heuristic merge.")
        return _heuristic_merge(items, asset_type, source_incidents)

    # Compact items for prompt efficiency
    compact_items = []
    for item in items[:10]:
        c = dict(item)
        if "code" in c:
            c["code"] = (c["code"] or "")[:300]
        # Strip internal fields
        for skip in ("_id", "_source_knowledge_id", "_source_incident", "_merge_count"):
            c.pop(skip, None)
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
        logger.warning("LLM refinement failed for %s: %s", asset_type, e)
        return _heuristic_merge(items, asset_type, source_incidents)


def _heuristic_merge(
    items: List[Dict[str, Any]],
    asset_type: str,
    source_incidents: List[str],
) -> Dict[str, Any]:
    """Rule-based merge when LLM is unavailable."""
    if asset_type == "solution_summaries":
        # Merge solution summaries heuristically
        all_problems = [it.get("problem", "") for it in items if it.get("problem")]
        all_solutions = [it.get("solution", "") for it in items if it.get("solution")]
        all_key_points = []
        all_scenarios = []
        all_verifications = []

        for it in items:
            all_key_points.extend(it.get("key_points", []))
            all_scenarios.extend(it.get("scenario", []))
            ver = it.get("verification", "")
            if ver:
                all_verifications.append(ver)

        # Dedup
        seen_kp = set()
        unique_key_points = []
        for kp in all_key_points:
            if kp not in seen_kp:
                seen_kp.add(kp)
                unique_key_points.append(kp)

        seen_sc = set()
        unique_scenarios = []
        for sc in all_scenarios:
            if sc not in seen_sc:
                seen_sc.add(sc)
                unique_scenarios.append(sc)

        # Pick longest problem/solution
        best_problem = max(all_problems, key=len) if all_problems else ""
        best_solution = max(all_solutions, key=len) if all_solutions else ""
        best_verification = max(all_verifications, key=len) if all_verifications else ""

        return {
            "problem": best_problem,
            "solution": best_solution,
            "scenario": unique_scenarios,
            "key_points": unique_key_points,
            "verification": best_verification,
            "auto_remediation_script": "",
            "source_incidents": source_incidents,
            "_aggregated": True,
            "_source_count": len(source_incidents),
            "_asset_type": asset_type,
            "method": "heuristic_merge",
        }

    elif asset_type == "sop_templates":
        # Merge SOP templates
        all_titles = [it.get("title", "") for it in items if it.get("title")]
        all_steps = []
        seen_steps = set()
        for it in items:
            for step in it.get("steps", []):
                if step not in seen_steps:
                    seen_steps.add(step)
                    all_steps.append(step)
        best_title = max(all_titles, key=len) if all_titles else ""

        all_kp = []
        seen_kp = set()
        for it in items:
            for kp in it.get("key_points", []):
                if kp not in seen_kp:
                    seen_kp.add(kp)
                    all_kp.append(kp)

        all_sc = []
        seen_sc = set()
        for it in items:
            for sc in it.get("scenario", []):
                if sc not in seen_sc:
                    seen_sc.add(sc)
                    all_sc.append(sc)

        return {
            "title": best_title,
            "steps": all_steps,
            "scenario": all_sc,
            "key_points": all_kp,
            "verification_method": max([it.get("verification_method", "") for it in items], key=len) if items else "",
            "source_incidents": source_incidents,
            "method": "heuristic_merge",
            "_aggregated": True,
            "_source_count": len(source_incidents),
            "_asset_type": asset_type,
        }

    else:
        return {
            "problem": f"合并{asset_type}（{len(source_incidents)}个来源）",
            "solution": "",
            "scenario": [],
            "key_points": [],
            "verification": "",
            "source_incidents": source_incidents,
            "method": "heuristic_merge",
            "_aggregated": True,
            "_source_count": len(source_incidents),
            "_asset_type": asset_type,
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

    from .knowledge_deduplicator import HIGH_FREQ_THRESHOLD

    asset_type_counts: Dict[str, Dict[str, Dict]] = {}

    for kn in all_knowledge:
        for asset_type in ["solution_summaries", "sop_templates", "warning_signals"]:
            items = kn.get(asset_type, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                sources = item.get("source_incidents", [])
                merge_count = item.get("_merge_count", 1)
                total_count = max(len(sources), merge_count)

                if total_count >= HIGH_FREQ_THRESHOLD:
                    pattern_key = item.get("problem", item.get("pattern", item.get("title", item.get("name", ""))))
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
