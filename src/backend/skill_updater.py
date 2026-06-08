"""
Skill Updater — dynamically injects mature solution summaries and practices into SKILL.md files.

When a solution summary reaches high frequency (N source incidents), this module:
  1. Updates the corresponding `references/solution-practices.md` with the authoritative solution.
  2. Updates `references/runbooks/` or `references/error-patterns.md`.
  3. For fully automated SOPs, generates an auto-remediation SKILL.md so the AI
     can autonomously handle future occurrences.
  4. Keeps a changelog of what was updated and when.

This turns "high-frequency alert knowledge" into living documentation that the
AI agent loads automatically on next invocation — eliminating repeated knowledge accumulation.
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


def _append_or_update_ref_file(ref_path: str, section_title: str, content_md: str) -> bool:
    """Append a new section or update existing section in a reference markdown file."""
    try:
        os.makedirs(os.path.dirname(ref_path), exist_ok=True)
        if os.path.exists(ref_path):
            existing = open(ref_path, "r", encoding="utf-8").read()
        else:
            existing = ""

        header = f"\n\n## {section_title}\n\n*自动生成于 {datetime.utcnow().isoformat()}*\n\n"

        if f"## {section_title}" in existing:
            lines = existing.split("\n")
            new_lines = []
            in_section = False
            for line in lines:
                if line.startswith(f"## {section_title}"):
                    in_section = True
                    continue
                if in_section:
                    if line.startswith("## "):
                        in_section = False
                        new_lines.append(line)
                        continue
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
    if asset_type == "solution_summaries":
        # Check if auto_remediation_script is present and meaningful
        script = pattern.get("auto_remediation_script", "")
        if not script or not isinstance(script, str) or len(script.strip()) < 10:
            return None

        problem = pattern.get("problem", "auto-remediation")
        safe_name = _slugify(f"auto-{problem[:30]}")
        skill_dir = os.path.join(SKILL_BASE, safe_name)

        if os.path.exists(skill_dir):
            logger.info("Auto-remediation skill already exists: %s", safe_name)
            return safe_name

        key_points = pattern.get("key_points", [])
        scenario = pattern.get("scenario", [])
        verification = pattern.get("verification", "")
        solution = pattern.get("solution", "")

        skill_md = f"""---
name: {safe_name}
description: >
  自动处置：{problem}。使用场景：{'、'.join(scenario[:3])}。
  当检测到匹配的高频告警模式时，自动执行标准处置流程。
argument-hint: '<incident_id>'
user-invocable: false
disable-model-invocation: false
---

# 自动处置：{problem}

## 来源
聚合自 {pattern.get('_source_count', pattern.get('count', 1))} 个历史 incident。

## 问题描述
{problem}

## 处置方案
{solution}

## 处置要点
{chr(10).join(f'- {kp}' for kp in key_points)}

## 验证方法
{verification}

## 自动处置脚本
```bash
{script}
```

## 使用场景
{chr(10).join(f'- {s}' for s in scenario)}

## 参考
- [解决方案实践库](./references/solution-practices.md)
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

    elif asset_type == "sop_templates":
        steps = pattern.get("steps", [])
        if len(steps) < 2:
            return None

        title = pattern.get("title", "auto-sop")
        safe_name = _slugify(f"sop-{title[:30]}")
        skill_dir = os.path.join(SKILL_BASE, safe_name)

        if os.path.exists(skill_dir):
            logger.info("SOP skill already exists: %s", safe_name)
            return safe_name

        key_points = pattern.get("key_points", [])
        scenario = pattern.get("scenario", [])
        verification_method = pattern.get("verification_method", "")

        skill_md = f"""---
name: {safe_name}
description: >
  自动处置 SOP：{title}。使用场景：{'、'.join(scenario[:3])}。
  标准操作流程，可自动执行。
argument-hint: '<incident_id>'
user-invocable: false
disable-model-invocation: false
---

# 自动处置 SOP：{title}

## 来源
聚合自 {pattern.get('_source_count', pattern.get('count', 1))} 个历史 incident。

## 操作步骤
{chr(10).join(f'{i+1}. {step}' for i, step in enumerate(steps))}

## 处置要点
{chr(10).join(f'- {kp}' for kp in key_points)}

## 验证方法
{verification_method}

## 使用场景
{chr(10).join(f'- {s}' for s in scenario)}

## 参考
- [解决方案实践库](./references/solution-practices.md)
"""

        try:
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(skill_md)
            logger.info("Created SOP skill: %s", safe_name)
            return safe_name
        except Exception as e:
            logger.error("Failed to create SOP skill %s: %s", safe_name, e)
            return None

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
    "solution_summaries": os.path.join(SKILL_BASE, "incident-diagnosis", "references", "solution-practices.md"),
    "sop_templates": os.path.join(SKILL_BASE, "script-operations", "references", "sop-library.md"),
    "warning_signals": os.path.join(SKILL_BASE, "incident-diagnosis", "references", "warning-signals.md"),
    "script_recommendations": os.path.join(SKILL_BASE, "script-operations", "references", "script-library.md"),
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
        "pattern_key": pattern.get("problem", pattern.get("pattern", pattern.get("title", ""))),
        "ref_files_updated": [],
        "auto_skill_created": None,
    }

    # 1. Update reference files
    ref_path = SKILL_REF_MAP.get(asset_type)
    if ref_path and os.path.exists(os.path.dirname(ref_path)):
        problem_text = pattern.get("problem", pattern.get("pattern", pattern.get("title", "")))
        if not problem_text:
            problem_text = pattern.get("title", pattern.get("name", ""))

        md_lines = [
            f"- **{problem_text}** (来源: {source_count} 个 incident)"
        ]

        solution = pattern.get("solution", "")
        if solution:
            md_lines.append(f"  - 解决方法：{solution[:200]}")

        key_points = pattern.get("key_points", [])
        if key_points:
            md_lines.append("  - 处置要点：")
            for kp in key_points:
                md_lines.append(f"    - {kp}")

        scenario = pattern.get("scenario", [])
        if scenario:
            md_lines.append("  - 使用场景：")
            for sc in scenario:
                md_lines.append(f"    - {sc}")

        verification = pattern.get("verification", pattern.get("verification_method", ""))
        if verification:
            md_lines.append(f"  - 验证方法：{verification[:200]}")

        script = pattern.get("auto_remediation_script", "")
        if script:
            md_lines.append(f"  - 自动处置脚本：\n```bash\n{script[:300]}\n```")

        content_md = "\n".join(md_lines)
        section_title = f"实践总结 - {problem_text[:40]}"

        ok = _append_or_update_ref_file(ref_path, section_title, content_md)
        if ok:
            result["ref_files_updated"].append(ref_path)

    # 2. Create auto-remediation skill if applicable
    auto_skill = _create_auto_remediation_skill(pattern, asset_type)
    if auto_skill:
        result["auto_skill_created"] = auto_skill

    return result


async def update_all_mature_patterns() -> List[Dict[str, Any]]:
    """
    Scan for all high-frequency patterns and update skill refs for them.
    Called periodically or after pattern aggregation.
    """
    from .pattern_aggregator import find_high_frequency_patterns, aggregate_and_refine

    patterns = await find_high_frequency_patterns()
    results = []
    for pattern in patterns:
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
