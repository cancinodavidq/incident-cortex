"""Models package for Incident Cortex."""

from .incident import (
    Attachment,
    FileReference,
    FunctionRef,
    SimilarIncident,
    AgentError,
    ParsedIncident,
    CodeAnalysis,
    DedupResult,
    TriageVerdict,
    IncidentState,
    state_to_incident_id,
    add_error_to_state,
)

from .events import (
    IncidentEvent,
    SystemStatus,
)

__all__ = [
    # Incident models
    "Attachment",
    "FileReference",
    "FunctionRef",
    "SimilarIncident",
    "AgentError",
    "ParsedIncident",
    "CodeAnalysis",
    "DedupResult",
    "TriageVerdict",
    "IncidentState",
    "state_to_incident_id",
    "add_error_to_state",
    # Event models
    "IncidentEvent",
    "SystemStatus",
]
