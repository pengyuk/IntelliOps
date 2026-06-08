"""
Ontology validation — schema definition and payload validation.

The ontology defines the semantic layer for knowledge graph entities:
Incident, Alert, Service, Host, Change, WorkOrder, Action, Person, SOP.
"""

from typing import Any, Dict, List, Tuple

ONTOLOGY_VERSION = "v0.1"

ONTOLOGY_SCHEMA: Dict[str, Any] = {
    "version": ONTOLOGY_VERSION,
    "required": ["@context", "@graph"],
    "classes": [
        "Incident", "Alert", "Service", "Host",
        "Change", "WorkOrder", "Action", "Person", "SOP",
    ],
    "relations": [
        "related_to", "runs_on", "affects",
        "depends_on", "used_in", "documented_in",
    ],
    "properties": {
        "Incident": ["incident_id", "summary", "status", "related_alerts", "related_changes", "affected_services"],
        "Alert": ["alert_id", "severity", "metric", "timestamp", "source"],
        "Service": ["service_id", "name", "owner"],
        "Change": ["change_id", "name", "author", "timestamp"],
    },
}


def validate_payload(payload: Any) -> Tuple[bool, List[str]]:
    """Validate an ontology JSON-LD payload against the schema.

    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []

    if not isinstance(payload, dict):
        return False, ["Ontology payload must be a JSON object"]

    if "@context" not in payload or not isinstance(payload["@context"], dict):
        errors.append("Missing or invalid @context")

    if "@graph" not in payload or not isinstance(payload["@graph"], list):
        errors.append("Missing or invalid @graph")

    if isinstance(payload.get("@graph"), list):
        for index, item in enumerate(payload["@graph"]):
            if not isinstance(item, dict):
                errors.append(f"@graph[{index}] must be an object")
                continue
            if "@id" not in item or not isinstance(item["@id"], str):
                errors.append(f"@graph[{index}] missing @id or invalid type")
            if "@type" not in item or not isinstance(item["@type"], str):
                errors.append(f"@graph[{index}] missing @type or invalid type")
            name = item.get("name")
            if name is None or not isinstance(name, str):
                errors.append(f"@graph[{index}] missing name or invalid name")

    return len(errors) == 0, errors
