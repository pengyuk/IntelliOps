"""
Investigation State Machine — tracks what's been verified, excluded, and what still needs checking.

Four quadrants per incident:
  verified    — confirmed normal (with evidence)
  to_verify   — pending checks (with priority)
  high_risk   — high-risk items that need caution
  excluded    — confirmed irrelevant

New joiners can immediately see "what's been checked and what's next" — no more asking "查到哪了".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .db import get_db

# ---------------------------------------------------------------------------
# InvestigationState
# ---------------------------------------------------------------------------

class InvestigationState:
    """Manage the four-quadrant investigation state for an incident."""

    @staticmethod
    async def get(incident_id: str) -> Dict[str, Any]:
        db = get_db()
        incident = await db.get_incident(incident_id)
        if not incident:
            raise KeyError(f"incident {incident_id} not found")

        # Read state from DB (stored as JSON in a custom table, or we can add a column)
        # For simplicity, store in a dedicated table
        return await _load_state(db, incident_id)

    @staticmethod
    async def update(incident_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        db = get_db()
        incident = await db.get_incident(incident_id)
        if not incident:
            raise KeyError(f"incident {incident_id} not found")

        current = await _load_state(db, incident_id)

        for quadrant in ("verified", "to_verify", "high_risk", "excluded"):
            if quadrant in updates:
                items = updates[quadrant]
                if isinstance(items, list):
                    current[quadrant] = items

        await _save_state(db, incident_id, current)
        return current

    @staticmethod
    async def add_item(incident_id: str, quadrant: str, item: Dict[str, Any]) -> Dict[str, Any]:
        db = get_db()
        current = await _load_state(db, incident_id)
        if quadrant not in current:
            raise ValueError(f"Invalid quadrant: {quadrant}. Use: verified, to_verify, high_risk, excluded")
        current[quadrant].append(item)
        await _save_state(db, incident_id, current)
        return current

    @staticmethod
    async def move_item(incident_id: str, item_name: str, from_quadrant: str, to_quadrant: str) -> Dict[str, Any]:
        db = get_db()
        current = await _load_state(db, incident_id)
        if from_quadrant not in current or to_quadrant not in current:
            raise ValueError("Invalid quadrant")
        moved = None
        new_from = []
        for item in current[from_quadrant]:
            if item.get("name") == item_name:
                moved = item
            else:
                new_from.append(item)
        if moved is None:
            raise KeyError(f"Item '{item_name}' not found in {from_quadrant}")
        current[from_quadrant] = new_from
        current[to_quadrant].append(moved)
        await _save_state(db, incident_id, current)
        return current


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

async def _ensure_table(db) -> None:
    conn = await db._get_conn()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS investigation_state (
            incident_id TEXT PRIMARY KEY,
            state_json TEXT DEFAULT '{}',
            updated_at TEXT DEFAULT '',
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        )
    """)
    await conn.commit()


def _default_state() -> Dict[str, Any]:
    return {
        "verified": [],
        "to_verify": [],
        "high_risk": [],
        "excluded": [],
    }


async def _load_state(db, incident_id: str) -> Dict[str, Any]:
    await _ensure_table(db)
    conn = await db._get_conn()
    row = await conn.execute(
        "SELECT state_json FROM investigation_state WHERE incident_id=?",
        (incident_id,),
    )
    r = await row.fetchone()
    if r and r[0]:
        import json
        return json.loads(r[0])
    return _default_state()


async def _save_state(db, incident_id: str, state: Dict[str, Any]) -> None:
    await _ensure_table(db)
    import json
    from datetime import datetime
    conn = await db._get_conn()
    await conn.execute(
        "INSERT OR REPLACE INTO investigation_state VALUES (?,?,?)",
        (
            incident_id,
            json.dumps(state, ensure_ascii=False),
            datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        ),
    )
    await conn.commit()
