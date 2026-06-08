"""
Knowledge Deduplicator — incrementally merges new distilled knowledge into the knowledge base.

Strategy:
  1. For each new knowledge asset type (solution_summaries, sop_templates, warning_signals,
     script_recommendations, key_learnings), compute semantic similarity against existing assets.
  2. If similarity > MERGE_THRESHOLD → merge (union key_points, scenario, solution steps, 
     keep longer verification).
  3. If similarity > STORE_THRESHOLD but < MERGE_THRESHOLD → suggest as variant.
  4. If similarity <= STORE_THRESHOLD → store as new entry.
  5. Track frequency per pattern to detect "high-frequency alert" patterns — collapses repeated
     solution knowledge into one authoritative SKILL asset instead of storing N identical entries.
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
"""Cosine similarity >= this → merge into existing entry (union key_points/sources)."""

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
    if asset_type == "solution_summaries":
        parts.append(asset.get("problem", ""))
        parts.append(asset.get("solution", ""))
        parts.extend(asset.get("key_points", []))
        parts.extend(asset.get("scenario", []))
        parts.append(asset.get("verification", ""))
    elif asset_type == "sop_templates":
        parts.append(asset.get("title", ""))
        parts.extend(asset.get("steps", []))
        parts.append(asset.get("scenario", ""))
        parts.append(asset.get("verification_method", ""))
        parts.extend(asset.get("key_points", []))
    elif asset_type == "warning_signals":
        parts.append(asset.get("metric", ""))
        parts.append(asset.get("description", ""))
    elif asset_type == "script_recommendations":
        parts.append(asset.get("name", ""))
        parts.append(asset.get("description", ""))
        parts.append(asset.get("code", "")[:200])
        parts.append(asset.get("scenario", ""))
    elif asset_type == "key_learnings":
        parts.append(asset if isinstance(asset, str) else asset.get("practice_summary", asset.get("_text", str(asset))))
    else:
        parts.append(str(asset))
    return " ".join(p for p in parts if p)


async def load_existing_assets(asset_type: str) -> List[Dict[str, Any]]:
    """
    Load all existing knowledge assets of a given type from the DB.

    Returns a flat list so each item carries a '_source_knowledge_id' and '_source_incident'
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
                item["_source_knowledge_id"] = kn.get("knowledge_id", "")
                item["_source_incident"] = (
                    item.get("source_incidents", [None])[0]
                    if isinstance(item.get("source_incidents"), list) and item["source_incidents"]
                    else kn.get("postmortem_id", "")
                )
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
            [{"summary": t, "_id": item.get("_id", "")} for t, item in zip(texts, existing)],
            text_key="summary",
        )
    else:
        vs.index_items([], text_key="summary")

    for item in new_items:
        if isinstance(item, str):
            item = {"_text": item}

        text = _make_text_for_embedding(item, asset_type)
        if not text or not text.strip():
            new_entries.append(item)
            continue

        results = vs.search(text, top_k=3)

        # Find best match
        best_score = 0.0
        best_match = None
        for row, score in results:
            # score already from tuple
            if score > best_score:
                best_score = score
                matched_id = row.get("_id", "")
                for ex in existing:
                    ex_id = ex.get("_id", "")
                    if ex_id == matched_id:
                        best_match = ex
                        break

        if best_match and best_score >= MERGE_THRESHOLD:
            merged_item = await _merge_into(best_match, item, asset_type)
            merged_item = _ensure_sources(merged_item, asset_type, source_incident)
            merged.append(merged_item)
        elif best_match and best_score >= VARIANT_THRESHOLD:
            item = _ensure_sources(item, asset_type, source_incident)
            variants.append({
                "item": item,
                "similar_to": best_match,
                "score": best_score,
            })
        else:
            item = _ensure_sources(item, asset_type, source_incident)
            new_entries.append(item)

    vs.reset()  # clear temp index
    return merged, variants, new_entries


async def _merge_into(
    existing: Dict[str, Any],
    new: Dict[str, Any],
    asset_type: str,
) -> Dict[str, Any]:
    """
    Merge new solution/summary into existing item.
    - Union key_points and scenario判断
    - Keep longer / more detailed verification steps
    - Union of source_incidents
    """
    merged = dict(existing)

    # Source incidents union
    if "source_incidents" in existing or "source_incidents" in new:
        existing_sources = set(existing.get("source_incidents", []))
        new_sources = set(new.get("source_incidents", []))
        merged["source_incidents"] = list(existing_sources | new_sources)

    merged["_merge_count"] = existing.get("_merge_count", 1) + 1

    # --- solution_summaries specific merge ---
    if asset_type == "solution_summaries":
        # Union key_points
        existing_kp = set(existing.get("key_points", []))
        new_kp = set(new.get("key_points", []))
        merged["key_points"] = list(existing_kp | new_kp)

        # Union scenario判断
        existing_sc = set(existing.get("scenario", []))
        new_sc = set(new.get("scenario", []))
        merged["scenario"] = list(existing_sc | new_sc)

        # Keep longer verification
        existing_ver = existing.get("verification", "")
        new_ver = new.get("verification", "")
        if len(new_ver) > len(existing_ver):
            merged["verification"] = new_ver

        # Keep longer / more complete solution
        existing_sol = existing.get("solution", "")
        new_sol = new.get("solution", "")
        if len(new_sol) > len(existing_sol):
            merged["solution"] = new_sol

        # Keep longer problem description
        existing_prob = existing.get("problem", "")
        new_prob = new.get("problem", "")
        if len(new_prob) > len(existing_prob):
            merged["problem"] = new_prob

    # Generic merge: union of steps
    if "steps" in existing and "steps" in new:
        existing_steps = existing.get("steps", [])
        new_steps = new.get("steps", [])
        merged_steps = list(existing_steps)
        seen = set(existing_steps)
        for s in new_steps:
            if s not in seen:
                merged_steps.append(s)
                seen.add(s)
        merged["steps"] = merged_steps

    # SOP template specific merge
    if asset_type == "sop_templates":
        existing_sc = set(existing.get("scenario", []))
        new_sc = set(new.get("scenario", []))
        merged["scenario"] = list(existing_sc | new_sc)

        existing_kp = set(existing.get("key_points", []))
        new_kp = set(new.get("key_points", []))
        merged["key_points"] = list(existing_kp | new_kp)

        existing_vm = existing.get("verification_method", "")
        new_vm = new.get("verification_method", "")
        if len(new_vm) > len(existing_vm):
            merged["verification_method"] = new_vm

    # Script recommendation specific
    if asset_type == "script_recommendations":
        existing_sc = set(existing.get("scenario", []))
        new_sc = set(new.get("scenario", []))
        merged["scenario"] = list(existing_sc | new_sc)

    return merged


def _ensure_sources(item: Any, asset_type: str, source_incident: str) -> Dict[str, Any]:
    """Ensure a new asset entry has source_incidents populated."""
    if isinstance(item, str):
        item = {"key_learning": item, "_text": item}
    if isinstance(item, dict):
        if "source_incidents" not in item or not item["source_incidents"]:
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
      - _dedup_details: details per asset type
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
        "solution_summaries",
        "sop_templates",
        "warning_signals",
        "script_recommendations",
        "key_learnings",
    ]

    final_assets: Dict[str, List] = {t: [] for t in ASSET_TYPES}

    for asset_type in ASSET_TYPES:
        new_items = knowledge.get(asset_type, [])
        if not new_items:
            continue

        merged, variants, new_entries = await deduplicate_asset_list(
            new_items, asset_type, source_incident,
        )

        if asset_type == "key_learnings":
            # Key learnings — simple set dedup on text
            merged_set = set()
            for m in merged:
                val = m if isinstance(m, str) else m.get("key_learning", m.get("_text", ""))
                merged_set.add(val)
            for n in new_entries:
                val = n if isinstance(n, str) else n.get("key_learning", n.get("_text", ""))
                merged_set.add(val)
            final_assets[asset_type] = list(merged_set)
        else:
            existing_pool = {}
            for m in merged:
                key = m.get("_id", m.get("problem", m.get("pattern", m.get("title", m.get("name", "")))))
                existing_pool[key] = m

            existing_all = await load_existing_assets(asset_type)
            for ex in existing_all:
                key = ex.get("_id", ex.get("problem", ex.get("pattern", ex.get("title", ex.get("name", "")))))
                if key in existing_pool:
                    continue
                # Check if variant of merged — keep existing as-is
                is_variant_of = False
                for v in variants:
                    similar = v.get("similar_to", {})
                    if isinstance(similar, dict) and similar.get("_id") == ex.get("_id"):
                        is_variant_of = True
                        break
                if not is_variant_of:
                    existing_pool[key] = ex

            for n in new_entries:
                key = n.get("_id", n.get("problem", n.get("pattern", n.get("title", n.get("name", "")))))
                existing_pool[key] = n

            final_assets[asset_type] = list(existing_pool.values())

        summary["merged"] += len(merged)
        summary["variants"] += len(variants)
        summary["new_entries"] += len(new_entries)
        dedup_details[asset_type] = {
            "merged": [m.get("_id", m.get("problem", m.get("pattern", m.get("title", "")))) for m in merged],
            "variants": [
                {
                    "item": v.get("item", {}).get("problem", v.get("item", {}).get("_id", "")),
                    "similar_to": _safe_get_id(v.get("similar_to", {})),
                    "score": round(v.get("score", 0), 2),
                }
                for v in variants
            ],
            "new_entries": [n.get("_id", n.get("problem", n.get("pattern", n.get("title", "")))) for n in new_entries],
        }

        # High-frequency detection
        for item in final_assets[asset_type]:
            if isinstance(item, dict):
                sources = item.get("source_incidents", [])
                merge_count = item.get("_merge_count", 1)
                effective_count = max(len(sources), merge_count)
                if effective_count >= HIGH_FREQ_THRESHOLD:
                    label = item.get("problem", item.get("pattern", item.get("title", item.get("name", ""))))
                    summary["high_frequency_patterns"].append({
                        "label": label,
                        "count": effective_count,
                        "asset_type": asset_type,
                    })

    knowledge["_dedup_summary"] = summary
    knowledge["_dedup_details"] = dedup_details

    for asset_type in ASSET_TYPES:
        knowledge[asset_type] = final_assets[asset_type]

    return knowledge


def _safe_get_id(obj: Any) -> str:
    """Safely get _id from a dict or return empty string."""
    return obj.get("_id", "") if isinstance(obj, dict) else ""
