from __future__ import annotations
from typing import TypedDict, Optional, Literal, Any
from pydantic import BaseModel, field_validator, model_validator
from datetime import datetime
import uuid


# --- Sub-models ---

class Attachment(BaseModel):
    filename: str
    content_type: str
    data: bytes  # base64 decoded
    size_bytes: int


class FileReference(BaseModel):
    file_path: str
    relevance_score: float
    reason: str
    key_lines: Optional[str] = None
    exists_in_codebase: bool = True

    @field_validator("relevance_score")
    @classmethod
    def score_range(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("relevance_score must be 0-1")
        return round(v, 4)


class FunctionRef(BaseModel):
    function_name: str
    file_path: str
    reason: str


class SimilarIncident(BaseModel):
    incident_id: str
    title: str
    similarity_score: float
    ticket_id: Optional[str] = None
    ticket_url: Optional[str] = None
    resolution: Optional[str] = None


class AgentError(BaseModel):
    agent: str
    error_type: str
    message: str
    timestamp: datetime = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


# --- Primary output models ---

class ParsedIncident(BaseModel):
    title: str
    description: str
    affected_service: Optional[str] = None
    error_type: Optional[str] = None
    symptoms: list[str] = []
    extracted_from_image: Optional[str] = None
    information_sufficient: bool = True
    missing_info: list[str] = []


class CodeAnalysis(BaseModel):
    relevant_files: list[FileReference] = []
    suspected_functions: list[FunctionRef] = []
    analysis_summary: str
    files_verified: bool = True
    degraded: bool = False
    _used_fallback: bool = False


class DedupResult(BaseModel):
    is_duplicate: bool = False
    similar_incidents: list[SimilarIncident] = []
    highest_similarity: float = 0.0
    recommendation: Literal["create_new", "link_existing", "merge"] = "create_new"


class TriageVerdict(BaseModel):
    severity: Literal["P1", "P2", "P3", "P4"]
    severity_reasoning: str
    confidence: float
    needs_human_review: bool = False
    root_cause_hypothesis: str
    affected_components: list[str] = []
    suggested_investigation_steps: list[str] = []
    suggested_assignee_team: str = "sre-team"
    estimated_impact: str = ""

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("confidence must be 0-1")
        return round(v, 4)

    def model_post_init(self, __context):
        # Coherence: P1 with low confidence → degrade to P2
        if self.severity == "P1" and self.confidence < 0.5:
            self.severity = "P2"
            self.needs_human_review = True
        # Low confidence always requires human review
        if self.confidence < 0.6:
            self.needs_human_review = True


# --- Pipeline State ---

class IncidentState(TypedDict, total=False):
    # Identity
    incident_id: str

    # Input
    raw_text: str
    attachments: list[dict]
    reporter_email: str
    submitted_at: str

    # Intake output
    parsed_incident: Optional[dict]  # ParsedIncident.model_dump()

    # Parallel analysis outputs
    code_analysis: Optional[dict]   # CodeAnalysis.model_dump()
    dedup_result: Optional[dict]    # DedupResult.model_dump()

    # Triage output
    triage_verdict: Optional[dict]  # TriageVerdict.model_dump()

    # Routing outputs
    ticket_id: Optional[str]
    ticket_url: Optional[str]
    notifications_sent: list[str]
    escalation_triggered: bool  # True for P1 incidents

    # Control flow
    current_phase: str
    errors: list[dict]
    retry_count: dict[str, int]
    confidence: float


# --- Helper functions ---

def state_to_incident_id(state: IncidentState) -> str:
    """Extract or generate incident_id from state."""
    if "incident_id" in state and state["incident_id"]:
        return state["incident_id"]
    return str(uuid.uuid4())


def add_error_to_state(
    state: IncidentState,
    agent: str,
    error_type: str,
    message: str
) -> IncidentState:
    """Add an error record to state.errors."""
    error = AgentError(
        agent=agent,
        error_type=error_type,
        message=message,
        timestamp=datetime.utcnow()
    )
    if "errors" not in state:
        state["errors"] = []
    state["errors"].append(error.model_dump())
    return state
