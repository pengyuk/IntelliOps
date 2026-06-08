"""
Knowledge Deduplicator — incrementally merges new distilled knowledge into the knowledge base.

Strategy:
  1. For each new knowledge asset type (root_cause_rules, sop_templates, warning_signals,
     script_recommendations, key_learnings), compute semantic similarity against existing assets.
  2. If similarity > MERGE_THRESHOLD → merge (update confidence, append source_incidents).
  3. If similarity > STORE_THRESHOLD but < MERGE_THRESHOLD → suggest as variant.
  4. If similarity <= STORE_THRESHOLD → store as new entry.
  5. Track frequency per pattern to detect "high-frequency alert" patterns.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .db import get_db
from .vector_search import VectorSearch, get_vector_search


# ---------------------------------------------------------------------------
# Thresholds (tunable via env vars)
# ---------------------------------------------------------------------------

MERGE_THRESHOLD = float(__import__("os").environ.get("KNOWLEDGE_MERGE_THRESHOLD", "0.82"))
"""Cosine similarity >= this → merge into existing entry (update confidence + sources)."""

VARIANT_THRESHOLD = float(__import__("os").environ.get("KNOWLEDGE_VARIANT_THRESHOLD", "0.65"))
"""Cosine similarity >= this → suggest as variant of existing entry."""

STORE_THRESHOLD = float(__import__("os").environ.get("KNOWLEDGE_STORE_THRESHOLD", "0.35"))
"""Cosine similarity <= this → store as brand-new entry."""

HIGH_FREQ_THRESHOLD = int(__import__("os").environ.get("KNOWLEDGE_HIGH_FREQ_THRESHOLD", "5"))
"""A pattern with >= this many source incidents is flagged as high-frequency."""


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _make_text_for_embedding(asset: Dict[str, Any], asset_type: str) -> str:
    """Build a flat text representation for similarity comparison."""
    parts = []
    if asset_type == "root_cause_rules":
        parts.append(asset.get("pattern", ""))
        parts.extend(asset.get("conditions", []))
        parts.append(asset.get("category", ""))
    elif asset_type == "sop_templates":
        parts.append(asset.get("title", ""))
        parts.extend(asset.get("steps", []))
    elif asset_type == "warning_signals":
        parts.append(asset.get("metric", ""))
        parts.append(asset.get("description", ""))
    elif asset_type == "script_recommendations":
        parts.append(asset.get("name", ""))
        parts.append(asset.get("description", ""))
        parts.append(asset.get("code", "")[:200])
    elif asset_type == "key_learnings":
        parts.append(asset if isinstance(asset, str) else str(asset))
    else:
        parts.append(str(asset))
    return " ".join(p for p in parts if p)


async def load_existing_assets(asset_type: str) -> List[Dict[str, Any]]:
    """
    Load all existing knowledge assets of a given type from the DB.

    Returns a flat list so each item carries a 'knowledge_id' and 'postmortem_id'
    to trace provenance.
    """
    db = get_db()
    all_knowledge = await db.list_knowledge()
    flat: List[Dict[str, Any]] = []
    for kn in all_knowledge:
        items = kn.get(asset_type, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                item["_postmortem_id"] = kn.get("postmortem_id", "")
                item["_knowledge_id"] = kn.get("knowledge_id", "")
                flat.append(item)
    return flat


async def deduplicate_asset_list(
    new_items: List[Any],
    asset_type: str,
    source_incident: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Deduplicate a list of new assets against the existing knowledge base.

    Returns:
        (merged, variants, new_entries)

    - merged: existing items that were updated (new info merged in).
    - variants: items similar but not identical — suggested as related patterns.
    - new_entries: items with no close match — stored as new knowledge.
    """
    vs: VectorSearch = get_vector_search()
    existing = await load_existing_assets(asset_type)
    merged: List[Dict[str, Any]] = []
    variants: List[Dict[str, Any]] = []
    new_entries: List[Dict[str, Any]] = []

    # Index existing items for vector search
    if existing:
        texts = [_make_text_for_embedding(item, asset_type) for item in existing]
        vs.index_items(
            [{"summary": t} for t in texts],
            text_key="summary",
        )
    else:
        vs.index_items([], text_key="summary")

    for item in new_items:
        if isinstance(item, str):
            item = {"_text": item}

        text = _make_text_for_embedding(item, asset_type)
        if not text.strip():
            new_entries.append(item)
            continue

        results = vs.search(text, top_k=3)

        # Find best match
        best_score = 0.0
        best_idx = -1
        for result_item, score in results:
            if score > best_score:
                best_score = score
                # Find the original existing item index
                match_text = result_item.get("summary", "")
                for idx, ex in enumerate(existing):
                    if _make_text_for_embedding(ex, asset_type) == match_text:
                        best_idx = idx
                        break

        if best_score >= MERGE_THRESHOLD and best_idx >= 0:
            # Merge: update confidence, append source_incidents
            target = existing[best_idx]
            merged_entry = await _merge_into(target, item, asset_type, source_incident)
            merged.append(merged_entry)
        elif best_score >= VARIANT_THRESHOLD:
            variants.append({
                "item": item,
                "similar_to": existing[best_idx] if best_idx >= 0 else None,
                "score": best_score,
                "source_incident": source_incident,
            })
        else:
            # New entry
            entry_with_source = _ensure_source(item, asset_type, source_incident)
            new_entries.append(entry_with_source)

    return merged, variants, new_entries


async def _merge_into(
    target: Dict[str, Any],
    new_item: Dict[str, Any],
    asset_type: str,
    source_incident: str,
) -> Dict[str, Any]:
    """Merge new_item into target, updating confidence and source incidents."""
    if asset_type == "root_cause_rules":
        # Average confidence
        old_conf = target.get("confidence", 0.5)
        new_conf = new_item.get("confidence", 0.5)
        target["confidence"] = round((old_conf + new_conf) / 2, 2)

        # Append unique conditions
        existing_conds = set(target.get("conditions", []))
        for cond in new_item.get("conditions", []):
            if cond not in existing_conds:
                target.setdefault("conditions", []).append(cond)
                existing_conds.add(cond)

        # Append source incidents (deduplicated)
        sources = set(target.get("source_incidents", []))
        if source_incident not in sources:
            target.setdefault("source_incidents", []).append(source_incident)

    elif asset_type == "sop_templates":
        sources = set(target.get("source_incidents", []))
        if source_incident not in sources:
            target.setdefault("source_incidents", []).append(source_incident)
        # Broaden steps if new SOP has more detail
        if len(new_item.get("steps", [])) > len(target.get("steps", [])):
            target["steps"] = new_item.get("steps", [])
            target["estimated_time"] = new_item.get("estimated_time", target.get("estimated_time", ""))

    elif asset_type == "warning_signals":
        sources = set(target.get("source_incidents", []))
        if source_incident not in sources:
            target.setdefault("source_incidents", []).append(source_incident)
        # Update severity if new evidence suggests escalation
        new_sev = new_item.get("severity", "")
        sev_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if sev_order.get(new_sev, 0) > sev_order.get(target.get("severity", ""), 0):
            target["severity"] = new_sev

    elif asset_type == "script_recommendations":
        # Keep the more complete code snippet
        new_code = (new_item.get("code") or "").strip()
        old_code = (target.get("code") or "").strip()
        if len(new_code) > len(old_code):
            target["code"] = new_code
        sources = set(target.get("source_incidents", []))
        if source_incident not in sources:
            target.setdefault("source_incidents", []).append(source_incident)

    elif asset_type == "key_learnings":
        # key_learnings are simple strings — add if unique
        pass  # handled at list level in the caller

    target["_last_merged_at"] = _now_iso()
    target["_merge_count"] = target.get("_merge_count", 1) + 1
    return target


def _ensure_source(
    item: Any,
    asset_type: str,
    source_incident: str,
) -> Dict[str, Any]:
    """Ensure a new asset entry has source_incidents populated."""
    if isinstance(item, str):
        item = {"_text": item}
    if "source_incidents" not in item:
        item["source_incidents"] = [source_incident]
    else:
        sources = set(item.get("source_incidents", []))
        if source_incident not in sources:
            item.setdefault("source_incidents", []).append(source_incident)
    if "_id" not in item:
        item["_id"] = f"{asset_type}-{uuid.uuid4().hex[:8]}"
    return item


async def deduplicate_knowledge(
    knowledge: Dict[str, Any],
    source_incident: str,
) -> Dict[str, Any]:
    """
    Full deduplication pass over a knowledge dict (as produced by KnowledgeDistiller).

    Returns an augmented knowledge dict with:
      - _dedup_summary: stats on what happened
      - _merged / _variants / _new_entries: details per asset type
      - updated asset lists (merged + new entries only; variants reported but not stored)
    """
    summary: Dict[str, Any] = {
        "merged": 0,
        "variants": 0,
        "new_entries": 0,
        "high_frequency_patterns": [],
    }
    dedup_details: Dict[str, Any] = {}

    ASSET_TYPES = [
        "root_cause_rules",
        "sop_templates",
        "warning_signals",
        "script_recommendations",
        "key_learnings",
    ]

    final_assets: Dict[str, List] = {
        t: [] for t in ASSET_TYPES
    }

    for asset_type in ASSET_TYPES:
        new_items = knowledge.get(asset_type, [])
        if not new_items:
            continue

        merged, variants, new_entries = await deduplicate_asset_list(
            new_items, asset_type, source_incident,
        )

        # Key learnings are strings — simple set dedup
        if asset_type == "key_learnings":
            merged_set = set()
            for m in merged:
                merged_set.add(m if isinstance(m, str) else m.get("_text", ""))
            for n in new_entries:
                merged_set.add(n if isinstance(n, str) else n.get("_text", ""))
            final_assets[asset_type] = list(merged_set)
        else:
            # Merged entries: use the updated existing items
            existing_pool = {}
            for m in merged:
                key = m.get("_id", m.get("pattern", m.get("title", m.get("name", ""))))
                existing_pool[key] = m

            # Also keep un-merged existing items (they remain in the knowledge base)
            existing_all = await load_existing_assets(asset_type)
            for ex in existing_all:
                key = ex.get("_id", ex.get("pattern", ex.get("title", ex.get("name", ""))))
                if key in existing_pool:
                    # Already updated via merge
                    pass
                else:
                    # Check if any variant matched — keep existing as-is
                    is_variant_of = False
                    for v in variants:
                        similar = v.get("similar_to", {})
                        if similar.get("_id") == ex.get("_id"):
                            is_variant_of = True
                            break
                    if not is_variant_of:
                        existing_pool[key] = ex

            # Add new entries
            for n in new_entries:
                key = n.get("_id", n.get("pattern", n.get("title", n.get("name", ""))))
                existing_pool[key] = n

            final_assets[asset_type] = list(existing_pool.values())

        summary["merged"] += len(merged)
        summary["variants"] += len(variants)
        summary["new_entries"] += len(new_entries)
        dedup_details[asset_type] = {
            "merged": [m.get("_id", m.get("pattern", m.get("title", ""))) for m in merged],
            "variants": [
                {
                    "item": v.get("item", {}),
                    "similar_to": v.get("similar_to", {}).get("_id", ""),
                    "score": round(v.get("score", 0), 2),
                }
                for v in variants
            ],
            "new_entries": [n.get("_id", n.get("pattern", n.get("title", ""))) for n in new_entries],
        }

        # High-frequency detection
        for item in final_assets[asset_type]:
            if isinstance(item, dict):
                sources = item.get("source_incidents", [])
                if len(sources) >= HIGH_FREQ_THRESHOLD:
                    label = item.get("pattern", item.get("title", item.get("name", "")))
                    summary["high_frequency_patterns"].append({
                        "label": label,
                        "count": len(sources),
                        "asset_type": asset_type,
                    })

    knowledge["_dedup_summary"] = summary
    knowledge["_dedup_details"] = dedup_details

    # Replace asset lists with deduplicated+merged result
    for asset_type in ASSET_TYPES:
        knowledge[asset_type] = final_assets[asset_type]

    return knowledge
