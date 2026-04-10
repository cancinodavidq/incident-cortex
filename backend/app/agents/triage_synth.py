"""Triage synthesizer agent — produces final triage verdict from all inputs."""

import logging
import json
from typing import Optional
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.services.llm_client import LLMClient
from app.services.event_store import EventStore
from app.models.incident import IncidentState

logger = logging.getLogger(__name__)


class RunbookStep(BaseModel):
    """A single runbook remediation step."""
    action: str = Field(..., description="What to do")
    command: str = Field("", description="Shell/kubectl/SQL command if applicable")
    rationale: str = Field("", description="Why this step matters")


class TriageVerdict(BaseModel):
    """Final triage verdict from LLM."""
    severity: str = Field(..., description="P1, P2, P3, or P4")
    confidence: float = Field(..., description="Confidence score 0.0-1.0")
    root_cause_hypothesis: str = Field(..., description="Suspected root cause")
    affected_components: list[str] = Field(default_factory=list, description="Affected system components")
    investigation_steps: list[str] = Field(default_factory=list, description="Recommended investigation steps")
    runbook: list[RunbookStep] = Field(default_factory=list, description="Step-by-step remediation runbook")
    suggested_assignee_team: str = Field("sre-team", description="Team to assign: sre-team, backend, data, platform")
    needs_human_review: bool = Field(False, description="Whether human review is required")

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v):
        if v not in ["P1", "P2", "P3", "P4"]:
            raise ValueError(f"severity must be P1-P4, got {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got {v}")
        return v

    def __post_init__(self):
        """Validate P1/confidence coherence."""
        # P1 should have high confidence, P4 can have lower
        if self.severity == "P1" and self.confidence < 0.6:
            logger.warning(
                f"P1 severity with low confidence ({self.confidence}) — consider human review"
            )
            self.needs_human_review = True


async def triage_synthesizer(state: IncidentState) -> dict:
    """
    Synthesize final triage verdict from all analysis.

    1. Load ParsedIncident, CodeAnalysis, DedupResult
    2. If duplicate with high similarity -> return early
    3. Build comprehensive prompt
    4. Get TriageVerdict from LLM
    5. If confidence < 0.6 -> log warning to Langfuse
    6. Return triage_verdict and phase
    """
    settings = get_settings()
    llm_client = LLMClient()
    event_store = EventStore()

    try:
        incident_id = state.get("incident_id", "")
        parsed = state.get("parsed_incident", {})
        code_analysis = state.get("code_analysis", {})
        dedup_result = state.get("dedup_result", {})
        attachments = state.get("attachments", [])

        # Early exit for confirmed duplicates
        if dedup_result.get("is_duplicate") and dedup_result.get("highest_similarity", 0) >= 0.85:
            logger.info(f"Duplicate incident detected, skipping triage synthesis")
            return {
                "current_phase": "triage_skipped",
                "triage_verdict": None
            }

        # Build comprehensive prompt
        is_code_degraded = code_analysis.get("degraded", False)

        # Build attachment context section
        attachment_section = ""
        for att in attachments:
            if att.get("type") == "text":
                attachment_section += f"\n\n[Attached file: {att.get('filename')}]\n```\n{att.get('content', '')[:6000]}\n```"
            elif att.get("type") == "image":
                attachment_section += f"\n\n[Image attachment: {att.get('filename')} — see extracted text in INCIDENT DETAILS]"

        verdict_prompt = f"""You are an expert SRE synthesizer. Given an incident report, code analysis,
and deduplication results, produce a comprehensive triage verdict WITH a concrete remediation runbook.

INCIDENT DETAILS:
{json.dumps(parsed, indent=2)}

CODE ANALYSIS (degraded={is_code_degraded}):
{json.dumps(code_analysis, indent=2)}

DEDUP RESULT:
{json.dumps(dedup_result, indent=2)}{attachment_section}

Produce a JSON response matching EXACTLY this schema:
{{
  "severity": "P1|P2|P3|P4",
  "confidence": 0.0-1.0,
  "root_cause_hypothesis": "Specific hypothesis about root cause",
  "affected_components": ["component1", "component2"],
  "investigation_steps": ["Concrete diagnostic step 1", "Concrete diagnostic step 2"],
  "runbook": [
    {{
      "action": "Short imperative description of what to do",
      "command": "Actual shell/kubectl/SQL/curl command or empty string if N/A",
      "rationale": "Why this step resolves or mitigates the issue"
    }}
  ],
  "suggested_assignee_team": "sre-team|backend|data|platform",
  "needs_human_review": true|false
}}

Severity guidelines:
- P1: Customer-facing outage, data loss, security breach — page oncall NOW
- P2: Degraded service, partial outage, significant business impact
- P3: Non-critical degradation, internal tooling, isolated failures
- P4: Minor issue, cosmetic, no user impact

Runbook must contain 3-6 concrete steps with real commands where applicable.
Consider: service affected, error type, code context, whether data is at risk.
Return ONLY valid JSON."""

        system_prompt = """You are an expert SRE synthesizer. Produce calibrated triage verdicts with
confidence scores that reflect uncertainty."""

        response = await llm_client.call(system_prompt, verdict_prompt)

        # Parse verdict
        try:
            verdict_json = json.loads(LLMClient.extract_json(response))
            # Coerce runbook items to RunbookStep if they're plain strings
            raw_runbook = verdict_json.get("runbook", [])
            if raw_runbook and isinstance(raw_runbook[0], str):
                verdict_json["runbook"] = [{"action": s, "command": "", "rationale": ""} for s in raw_runbook]
            verdict = TriageVerdict(**verdict_json)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse triage verdict: {e}")
            # Fallback: conservative verdict
            verdict = TriageVerdict(
                severity="P3",
                confidence=0.5,
                root_cause_hypothesis="Unable to determine — requires manual review",
                needs_human_review=True
            )

        # Log warning if low confidence
        if verdict.confidence < 0.6:
            logger.warning(
                f"Low confidence triage verdict ({verdict.confidence}): {verdict.severity} "
                f"({verdict.root_cause_hypothesis})"
            )

        # Log to event store
        await event_store.log_event(
            incident_id=incident_id,
            event_type="triage_completed",
            data={
                "verdict": verdict.model_dump(),
                "code_analysis_degraded": is_code_degraded
            }
        )

        return {
            "triage_verdict": verdict.model_dump(),
            "confidence": verdict.confidence,
            "escalation_triggered": verdict.severity == "P1",
            "current_phase": "triaging"
        }

    except Exception as e:
        logger.exception(f"Triage synthesizer failed: {e}")
        # Return conservative fallback
        return {
            "triage_verdict": TriageVerdict(
                severity="P3",
                confidence=0.3,
                root_cause_hypothesis="Triage synthesis failed",
                needs_human_review=True
            ).model_dump(),
            "confidence": 0.3,
            "current_phase": "triaging"
        }
