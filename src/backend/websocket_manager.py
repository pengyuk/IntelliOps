"""
WebSocket manager — real-time push for incident timeline, discussion & diagnosis updates.

Clients connect to /ws/incident/{id} and receive JSON events as they happen.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import WebSocket


class ConnectionManager:
    """Manage WebSocket connections grouped by incident_id."""

    def __init__(self):
        self._connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, incident_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if incident_id not in self._connections:
            self._connections[incident_id] = []
        self._connections[incident_id].append(ws)

    def disconnect(self, incident_id: str, ws: WebSocket) -> None:
        if incident_id in self._connections:
            self._connections[incident_id] = [c for c in self._connections[incident_id] if c != ws]
            if not self._connections[incident_id]:
                del self._connections[incident_id]

    async def broadcast(self, incident_id: str, event: Dict[str, Any]) -> None:
        """Send event to all clients watching this incident."""
        if incident_id not in self._connections:
            return
        payload = json.dumps(event, ensure_ascii=False)
        disconnected = []
        for ws in self._connections[incident_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(incident_id, ws)

    @property
    def active_connections(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._connections.items()}


# Singleton
manager = ConnectionManager()
