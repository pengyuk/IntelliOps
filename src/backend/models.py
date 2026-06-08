"""Pydantic request/response models for IntelliOps API."""

from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class AlertIn(BaseModel):
    alert_id: str
    severity: int
    metric: str
    timestamp: str
    source: str
    payload: dict = {}


class RawAlertIn(BaseModel):
    """Minimal alert input — everything else is derived by the platform."""
    severity: int
    source: str = ""
    content: str = ""


class ActionExecIn(BaseModel):
    action_id: str
    params: dict = {}
    requested_by: str = "ui-user"
    dry_run: bool = False
    request_id: Optional[str] = None
    incident_id: Optional[str] = None


class ActionRequestIn(BaseModel):
    action_id: str
    incident_id: str
    reason: str = ""
    requested_by: str = "ui-user"


class ActionApprovalIn(BaseModel):
    request_id: str
    approved: bool
    approver: str = "admin"
    comment: str = ""


class ReasoningResult(BaseModel):
    incident_id: str
    kg_context: Dict[str, List[Dict[str, Any]]]
    candidate_root_causes: List[Dict[str, Any]]
    reasoning_steps: List[str]
    evidence: List[str]
    confidence_summary: float


class OntologyValidationResult(BaseModel):
    valid: bool
    errors: List[str] = []


class TimelineEventIn(BaseModel):
    event_type: str
    summary: str
    details: str = ''
    actor: Optional[str] = None


class CopilotDiagnoseIn(BaseModel):
    incident_id: str
    user_id: str = 'ui-user'


class CopilotChatIn(BaseModel):
    incident_id: str
    diagnosis_id: Optional[str] = None
    user_id: str = 'ui-user'
    message: str


class ScriptVerifyIn(BaseModel):
    script_id: Optional[str] = None
    script_code: Optional[str] = None
    user_id: str = 'ui-user'


class ScriptExecuteIn(BaseModel):
    script_id: str
    requested_by: str = 'ui-user'
    request_id: Optional[str] = None
    lifecycle_type: str = 'once'
    incident_id: Optional[str] = None
    diagnosis_id: Optional[str] = None
    feed_to_copilot: bool = True


class DiscussionIn(BaseModel):
    author: str = 'ui-user'
    message: str
    message_type: str = 'maintenance'
    mentions: List[str] = []


class PostmortemIn(BaseModel):
    incident_id: Optional[str] = None
    mark_resolved: bool = True
    requested_by: str = 'ui-user'


class PostmortemApprovalIn(BaseModel):
    approver: str = 'ops-manager'
    publish_scripts: List[str] = []
    create_improvement_tasks: bool = True


class InvestigationStateIn(BaseModel):
    verified: List[Dict[str, Any]] = []
    to_verify: List[Dict[str, Any]] = []
    high_risk: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []


class InvestigationItemIn(BaseModel):
    quadrant: str
    item: Dict[str, Any]


class InvestigationMoveIn(BaseModel):
    item_name: str
    from_quadrant: str
    to_quadrant: str


class IncidentCreateIn(BaseModel):
    """Create a new incident with full details."""
    summary: str
    severity: int = 3
    status: str = "Investigating"
    alert_ids: List[str] = []
    change_ids: List[str] = []
    affected_services: List[str] = []
    root_cause: str = ""
    source: str = "manual"
    alert_description: str = ""


class IncidentSimulateIn(BaseModel):
    """Quick-simulate a new incident from preset templates."""
    scenario: str = ""  # "db_timeout" | "cpu_spike" | "mq_backlog" | "custom"
    summary: str = ""   # override summary (for custom scenario)
    system: str = ""    # target system name
    severity: int = 3
