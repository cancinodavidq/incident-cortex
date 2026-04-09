"""LangGraph orchestrator — defines the complete incident triage workflow."""

import logging
import uuid
from datetime import datetime
from typing import Optional, Callable

from langgraph.graph import StateGraph, END
from langgraph.constants import Send

from app.config import get_settings
from app.models.incident import IncidentState
from app.services.event_store import EventStore
from app.agents.intake import intake_agent
from app.agents.code_analysis import code_analysis_agent
from app.agents.deduplication import dedup_agent
from app.agents.triage_synth import triage_synthesizer
from app.agents.ticket_agent import ticket_agent
from app.agents.notification import notification_agent

logger = logging.getLogger(__name__)


async def clarity_agent(state: IncidentState) -> dict:
    """Send clarification request and return."""
    logger.info(f"Clarification requested for {state.get('incident_id')}")
    return {
        "current_phase": "request_clarity"
    }


def _route_after_triage(state: IncidentState) -> str:
    """Route after triage: escalate (P1), ticket (P2-P4), or link_existing (duplicate)."""
    dedup = state.get("dedup_result", {})

    # Confirmed duplicate → skip ticket, just notify
    if dedup.get("is_duplicate") and dedup.get("highest_similarity", 0) >= 0.85:
        return "link_existing"

    # P1 critical incidents → escalation fast path
    verdict = state.get("triage_verdict") or {}
    if verdict.get("severity") == "P1":
        return "escalate"

    return "ticket"


def _join_node(state: IncidentState) -> dict:
    """Reduction node — waits for parallel branches."""
    return state


def build_graph(incident_id: str = "", emit=None):
    """
    Build and compile the LangGraph workflow.

    Args:
        incident_id: Used for live broadcasting
        emit: async callable(phase, agent, data) for WebSocket broadcasting
    """

    async def _emit(phase: str, agent: str, data: dict):
        if emit:
            try:
                await emit(phase, agent, data)
            except Exception as e:
                logger.warning(f"WS emit failed: {e}")

    # --- Agent wrappers with broadcast ---

    async def intake_node(state: IncidentState) -> dict:
        await _emit("agent_started", "intake", {"message": "Parsing incident report..."})
        result = await intake_agent(state)
        parsed = result.get("parsed_incident") or {}
        await _emit("agent_completed", "intake", {
            "title": parsed.get("title", ""),
            "affected_service": parsed.get("affected_service", ""),
            "error_type": parsed.get("error_type", ""),
            "information_sufficient": parsed.get("information_sufficient", True),
        })
        return result

    async def code_analysis_node(state: IncidentState) -> dict:
        await _emit("agent_started", "code_analysis", {"message": "Searching codebase for relevant files..."})
        result = await code_analysis_agent(state)
        analysis = result.get("code_analysis") or {}
        await _emit("agent_completed", "code_analysis", {
            "relevant_files": analysis.get("relevant_files", []),
            "summary": analysis.get("analysis_summary", ""),
            "degraded": analysis.get("degraded", False),
        })
        return result

    async def dedup_node(state: IncidentState) -> dict:
        await _emit("agent_started", "dedup", {"message": "Checking for duplicate incidents..."})
        result = await dedup_agent(state)
        dedup = result.get("dedup_result") or {}
        await _emit("agent_completed", "dedup", {
            "is_duplicate": dedup.get("is_duplicate", False),
            "highest_similarity": dedup.get("highest_similarity", 0.0),
            "recommendation": dedup.get("recommendation", "create_new"),
            "linked_incident_id": dedup.get("linked_incident_id", ""),
        })
        return result

    async def triage_node(state: IncidentState) -> dict:
        await _emit("agent_started", "triage_synth", {"message": "Synthesizing severity and root cause..."})
        result = await triage_synthesizer(state)
        verdict = result.get("triage_verdict") or {}
        await _emit("agent_completed", "triage_synth", {
            "severity": verdict.get("severity", ""),
            "confidence": verdict.get("confidence", 0),
            "root_cause_hypothesis": verdict.get("root_cause_hypothesis", ""),
            "investigation_steps": verdict.get("investigation_steps", []),
            "runbook": verdict.get("runbook", []),
            "suggested_assignee_team": verdict.get("suggested_assignee_team", "sre-team"),
            "needs_human_review": verdict.get("needs_human_review", False),
        })
        return result

    async def escalate_node(state: IncidentState) -> dict:
        """P1 fast path: emit urgent alert before creating ticket."""
        verdict = state.get("triage_verdict") or {}
        parsed = state.get("parsed_incident") or {}
        await _emit("agent_started", "escalate", {"message": "P1 detected — triggering escalation..."})
        await _emit("agent_completed", "escalate", {
            "severity": "P1",
            "title": parsed.get("title", ""),
            "assignee_team": verdict.get("suggested_assignee_team", "sre-team"),
            "message": "Oncall paged. Escalation path activated."
        })
        return {"escalation_triggered": True, "current_phase": "escalating"}

    async def ticket_node(state: IncidentState) -> dict:
        await _emit("agent_started", "ticket", {"message": "Creating Jira ticket..."})
        result = await ticket_agent(state)
        await _emit("agent_completed", "ticket", {
            "ticket_id": result.get("ticket_id", ""),
            "ticket_url": result.get("ticket_url", ""),
        })
        return result

    async def notify_node(state: IncidentState) -> dict:
        await _emit("agent_started", "notify", {"message": "Sending notifications..."})
        result = await notification_agent(state)
        await _emit("agent_completed", "notify", {
            "notifications_sent": result.get("notifications_sent", []),
        })
        return result

    async def clarity_node(state: IncidentState) -> dict:
        await _emit("agent_completed", "intake", {"information_sufficient": False,
                                                   "message": "Insufficient information — clarification requested."})
        return await clarity_agent(state)

    # --- Build graph ---
    graph = StateGraph(IncidentState)

    graph.add_node("intake", intake_node)
    graph.add_node("run_code_analysis", code_analysis_node)
    graph.add_node("dedup", dedup_node)
    graph.add_node("join_analysis", _join_node)
    graph.add_node("triage_synth", triage_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("ticket", ticket_node)
    graph.add_node("notify", notify_node)
    graph.add_node("request_clarity", clarity_node)

    graph.set_entry_point("intake")

    def _route_intake(state: IncidentState):
        parsed = state.get("parsed_incident", {})
        if parsed.get("information_sufficient", True):
            return [Send("run_code_analysis", state), Send("dedup", state)]
        return "request_clarity"

    graph.add_conditional_edges(
        "intake",
        _route_intake,
        {
            "run_code_analysis": "run_code_analysis",
            "dedup": "dedup",
            "request_clarity": "request_clarity"
        }
    )

    graph.add_edge("run_code_analysis", "join_analysis")
    graph.add_edge("dedup", "join_analysis")
    graph.add_edge("join_analysis", "triage_synth")

    graph.add_conditional_edges(
        "triage_synth",
        _route_after_triage,
        {
            "ticket": "ticket",
            "escalate": "escalate",
            "link_existing": "notify"
        }
    )

    graph.add_edge("escalate", "ticket")
    graph.add_edge("ticket", "notify")
    graph.add_edge("notify", END)
    graph.add_edge("request_clarity", END)

    compiled_graph = graph.compile()
    logger.info("LangGraph compiled successfully")
    return compiled_graph


async def run_incident_pipeline(
    incident_data: dict,
    ws_callback: Optional[Callable] = None
) -> dict:
    """
    Run the incident triage pipeline.

    Args:
        incident_data: Dict with raw_text, attachments, reporter_email
        ws_callback: Optional sync/async callback(phase, agent, data) for WebSocket streaming

    Returns:
        Final state dict
    """
    from app.services.event_store import get_event_store
    settings = get_settings()
    event_store = await get_event_store()

    incident_id = incident_data.get("incident_id", str(uuid.uuid4()))
    submitted_at = datetime.utcnow().isoformat()

    async def emit(phase: str, agent: str, data: dict):
        if ws_callback:
            try:
                ws_callback(phase, agent, data)
            except Exception as e:
                logger.warning(f"ws_callback error: {e}")

    initial_state: IncidentState = {
        "incident_id": incident_id,
        "submitted_at": submitted_at,
        "raw_text": incident_data.get("raw_text", f"{incident_data.get('title', '')}\n\n{incident_data.get('description', '')}"),
        "attachments": incident_data.get("attachments", []),
        "reporter_email": incident_data.get("reporter_email", ""),
        "parsed_incident": None,
        "extracted_from_image": None,
        "code_analysis": None,
        "dedup_result": None,
        "triage_verdict": None,
        "ticket_id": None,
        "ticket_url": None,
        "notifications_sent": [],
        "current_phase": "initialized"
    }

    await event_store.log_event(
        incident_id=uuid.UUID(incident_id),
        phase="pipeline_started",
        agent="orchestrator",
        payload={"submitted_at": submitted_at}
    )

    # Emit pipeline start
    await emit("pipeline_started", "orchestrator", {
        "incident_id": incident_id,
        "agents": ["intake", "code_analysis", "dedup", "triage_synth", "ticket", "notify"]
    })

    logger.info(f"Starting incident pipeline for {incident_id}")

    compiled = build_graph(incident_id=incident_id, emit=emit)

    try:
        final_state = await compiled.ainvoke(initial_state)

        verdict = final_state.get("triage_verdict") or {}
        dedup = final_state.get("dedup_result") or {}
        code_analysis = final_state.get("code_analysis") or {}

        pipeline_summary = {
            "incident_id": incident_id,
            "severity": verdict.get("severity"),
            "confidence": verdict.get("confidence"),
            "root_cause_hypothesis": verdict.get("root_cause_hypothesis"),
            "investigation_steps": verdict.get("investigation_steps", []),
            "runbook": verdict.get("runbook", []),
            "suggested_assignee_team": verdict.get("suggested_assignee_team", "sre-team"),
            "needs_human_review": verdict.get("needs_human_review", False),
            "escalation_triggered": final_state.get("escalation_triggered", False),
            "ticket_id": final_state.get("ticket_id"),
            "ticket_url": final_state.get("ticket_url"),
            "is_duplicate": dedup.get("is_duplicate", False),
            "highest_similarity": dedup.get("highest_similarity", 0),
            "linked_incident_id": dedup.get("linked_incident_id", ""),
            "notifications_sent": final_state.get("notifications_sent", []),
            "relevant_files": code_analysis.get("relevant_files", []),
            # Full agent outputs for UI reconstruction
            "intake": final_state.get("parsed_incident") or {},
            "code_analysis": code_analysis,
            "dedup_result": dedup,
            "triage_verdict": verdict,
        }

        # Persist so UI can load it even after WS disconnects
        await event_store.save_pipeline_result(incident_id, pipeline_summary)

        await emit("pipeline_completed", "orchestrator", pipeline_summary)

        await event_store.log_event(
            incident_id=uuid.UUID(incident_id),
            phase="pipeline_completed",
            agent="orchestrator",
            payload={
                "final_phase": final_state.get("current_phase"),
                "ticket_id": final_state.get("ticket_id"),
                "severity": verdict.get("severity") if verdict else None
            }
        )

        logger.info(f"Pipeline completed for {incident_id}: {final_state.get('current_phase')}")
        return final_state

    except Exception as e:
        logger.exception(f"Pipeline execution failed for {incident_id}: {e}")
        await emit("pipeline_failed", "orchestrator", {"error": str(e)})
        await event_store.log_event(
            incident_id=uuid.UUID(incident_id),
            phase="pipeline_failed",
            agent="orchestrator",
            payload={"error": str(e)}
        )
        raise


def get_orchestrator():
    """Get the compiled graph (singleton-like pattern)."""
    return build_graph()
