"""
Skill Updater — dynamically injects mature knowledge patterns into SKILL.md files.

When a pattern reaches high confidence and appears frequently enough, this module:
  1. Updates the corresponding `references/root-cause-patterns.md` with new patterns.
  2. Updates `references/correlation-rules.md` or `references/error-patterns.md`.
  3. For fully automated SOPs, generates an auto-remediation SKILL.md so the AI
     can autonomously handle future occurrences.
  4. Keeps a changelog of what was updated and when.

This turns "high-frequency alert knowledge" into living documentation that the
AI agent loads automatically on next invocation.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .db import get_db

logger = logging.getLogger(__name__)

# Paths to skill reference files (relative to project root)
SKILL_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "skill"))


# ---------------------------------------------------------------------------
# Ref file updaters
# ---------------------------------------------------------------------------

def _append_to_ref_file(ref_path: str, section_title: str, content_md: str) -> bool:
    """Append a new section to a reference markdown file. Creates file if missing."""
    try:
        os.makedirs(os.path.dirname(ref_path), exist_ok=True)
        if os.path.exists(ref_path):
            existing = open(ref_path, "r", encoding="utf-8").read()
        else:
            existing = ""

        header = f"\n\n## {section_title}\n\n*自动生成于 {datetime.utcnow().isoformat()}*\n\n"

        # Avoid duplicate entries (match based on section title)
        if f"## {section_title}" in existing:
            # Update existing section
            lines = existing.split("\n")
            new_lines = []
            skip = False
            in_section = False
            section_depth = 0
            for line in lines:
                if line.startswith(f"## {section_title}"):
                    in_section = True
                    section_depth = 0
                    skip = True
                    continue
                if in_section:
                    if line.startswith("## "):
                        # Next top-level heading — stop skipping
                        in_section = False
                        skip = False
                        new_lines.append(line)
                        continue
                    # Skip lines within the old section
                    continue
                new_lines.append(line)
            existing = "\n".join(new_lines).rstrip() + header + content_md
        else:
            existing = existing.rstrip() + header + content_md

        with open(ref_path, "w", encoding="utf-8") as f:
            f.write(existing)
        return True
    except Exception as e:
        logger.error("Failed to update ref file %s: %s", ref_path, e)
        return False


def _create_auto_remediation_skill(
    pattern: Dict[str, Any],
    asset_type: str,
) -> Optional[str]:
    """
    Generate a lightweight auto-remediation SKILL.md for fully automatable patterns.

    Returns the skill directory name if created.
    """
    if asset_type != "sop_templates" and asset_type != "root_cause_rules":
        return None

    readiness = pattern.get("auto_remediation_readiness", 0)
    if readiness < 0.7:
        return None  # not automatable enough

    pattern_label = pattern.get("canonical_pattern", pattern.get("pattern", "auto-remediation"))
    safe_name = _slugify(f"auto-{pattern_label[:30]}")
    skill_dir = os.path.join(SKILL_BASE, safe_name)

    if os.path.exists(skill_dir):
        logger.info("Auto-remediation skill already exists: %s", safe_name)
        return safe_name

    conditions = pattern.get("merged_conditions", pattern.get("conditions", []))
    steps = []
    if asset_type == "sop_templates":
        merged_sop = pattern.get("_aggregated_sop", {})
        steps = merged_sop.get("steps", pattern.get("steps", []))
    else:
        # For root cause patterns, generate diagnostic + remediation steps
        steps = [
            f"检测到触发条件：{'、'.join(conditions[:3])}",
            "自动执行诊断脚本收集指标数据",
            "确认故障模式与已知模式匹配",
            "执行标准处置流程（自动审批）",
            "验证服务恢复状态",
            "生成处置报告",
        ]

    trigger_keywords = [f"自动处置", f"自愈", f"{pattern_label}"]
    if conditions:
        trigger_keywords.extend(c[:20] for c in conditions[:3])

    skill_md = f"""---
name: {safe_name}
description: >
  自动处置：{pattern_label}。触发词：{'、'.join(trigger_keywords)}。
  使用场景：检测到匹配已知高频模式时，自动执行标准处置流程。
argument-hint: '<incident_id>'
user-invocable: false
disable-model-invocation: false
---

# 自动处置：{pattern_label}

## 自动化就绪度
{readiness:.0%}

## 来源
聚合自 {pattern.get('_source_count', pattern.get('count', 1))} 个历史 incident。

## 处置步骤
{chr(10).join(f'{i+1}. {step}' for i, step in enumerate(steps))}

## 触发条件
{chr(10).join(f'- {c}' for c in conditions)}

## 参考
- [根因模式库](./references/root-cause-patterns.md)
"""

    try:
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_md)
        logger.info("Created auto-remediation skill: %s", safe_name)
        return safe_name
    except Exception as e:
        logger.error("Failed to create auto-remediation skill %s: %s", safe_name, e)
        return None


def _slugify(text: str) -> str:
    """Convert text to a safe directory name."""
    safe = ""
    for ch in text.lower():
        if ch.isalnum() or ch in "-_.":
            safe += ch
        elif ch in " \t":
            safe += "-"
    return safe.strip("-")[:48] or "auto-skill"


# ---------------------------------------------------------------------------
# Mapping: asset_type → skill reference file
# ---------------------------------------------------------------------------

SKILL_REF_MAP: Dict[str, str] = {
    "root_cause_rules": os.path.join(SKILL_BASE, "incident-diagnosis", "references", "root-cause-patterns.md"),
    "warning_signals": os.path.join(SKILL_BASE, "incident-diagnosis", "references", "diagnosis-api.md"),
    "sop_templates": os.path.join(SKILL_BASE, "script-operations", "references", "risk-matrix.md"),
    "script_recommendations": os.path.join(SKILL_BASE, "script-operations", "references", "risk-matrix.md"),
}


async def update_skill_refs(
    pattern: Dict[str, Any],
    asset_type: str,
    source_count: int,
) -> Dict[str, Any]:
    """
    Update the relevant SKILL.md reference files with a mature pattern.

    Returns a dict describing what was updated.
    """
    result: Dict[str, Any] = {
        "asset_type": asset_type,
        "pattern_key": pattern.get("canonical_pattern", pattern.get("pattern", "")),
        "ref_files_updated": [],
        "auto_skill_created": None,
    }

    # 1. Update reference files
    ref_path = SKILL_REF_MAP.get(asset_type)
    if ref_path and os.path.exists(os.path.dirname(ref_path)):
        pattern_text = pattern.get("canonical_pattern", pattern.get("pattern", ""))
        if not pattern_text:
            pattern_text = pattern.get("title", pattern.get("name", ""))

        # Build markdown content
        md_lines = [f"- **{pattern_text}** (来源: {source_count} 个 incident, 自动化就绪度: {pattern.get('auto_remediation_readiness', 0):.0%})"]

        conditions = pattern.get("merged_conditions", pattern.get("conditions", []))
        if conditions:
            md_lines.append("  - 触发条件：")
            for c in conditions:
                md_lines.append(f"    - {c}")

        calibrations = pattern.get("threshold_calibrations", [])
        if calibrations:
            md_lines.append("  - 监控阈值建议：")
            for cal in calibrations:
                md_lines.append(f"    - {cal.get('metric', '')}: {cal.get('current_threshold', '')} → {cal.get('suggested_threshold', '')}")

        content_md = "\n".join(md_lines)
        section_title = f"高频模式 - {pattern_text[:40]}"

        ok = _append_to_ref_file(ref_path, section_title, content_md)
        if ok:
            result["ref_files_updated"].append(ref_path)

    # 2. Create auto-remediation skill if readiness is high enough
    auto_skill = _create_auto_remediation_skill(pattern, asset_type)
    if auto_skill:
        result["auto_skill_created"] = auto_skill

    return result


async def update_all_mature_patterns() -> List[Dict[str, Any]]:
    """
    Scan for all high-frequency patterns and update skill refs for them.
    Called periodically or after pattern aggregation.
    """
    from .pattern_aggregator import find_high_frequency_patterns

    patterns = await find_high_frequency_patterns()
    results = []
    for pattern in patterns:
        # First, run aggregation if not already done
        from .pattern_aggregator import aggregate_and_refine
        refined = await aggregate_and_refine(
            asset_type=pattern["asset_type"],
            items=pattern["items"],
            source_incidents=pattern["source_incidents"],
        )
        if refined:
            result = await update_skill_refs(
                refined,
                pattern["asset_type"],
                pattern["count"],
            )
            results.append(result)
    return results
