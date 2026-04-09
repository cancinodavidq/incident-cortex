"""
ReAct Tool-Calling Orchestrator — Incident Cortex

Replaces the fixed LangGraph StateGraph with a dynamic Claude tool-calling loop.
Claude receives the incident, reasons about what to investigate, and autonomously
decides which tools to call (and in what order) until it reaches a final verdict.

Pattern:
  1. Claude receives incident + available tools
  2. Claude emits tool_use blocks (can call multiple tools in one turn)
  3. Tools execute (in parallel when multiple called simultaneously)
  4. Results fed back as tool_result content blocks
  5. Repeat until Claude emits stop_reason = "end_turn"
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, Callable, Any

from app.config import get_settings
from app.models.incident import IncidentState
from app.services.event_store import EventStore

logger = logging.getLogger(__name__)

# ── Tool schemas (Anthropic tool use format) ─────────────────────────────────

TOOLS = [
    {
        "name": "parse_incident",
        "description": (
            "Parse the raw incident report into structured data: title, affected service, "
            "error type, symptoms. ALWAYS call this first before any other tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_text": {"type": "string", "description": "The raw incident report text"},
                "reporter_email": {"type": "string", "description": "Reporter email address"}
            },
            "required": ["raw_text"]
        }
    },
    {
        "name": "search_codebase",
        "description": (
            "Search the indexed e-commerce codebase for code relevant to this incident "
            "using semantic RAG. Returns file paths and code snippets. "
            "Call after parse_incident, in parallel with check_duplicates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query combining service name, error type, and symptoms"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "check_duplicates",
        "description": (
            "Check if this incident is semantically similar to an existing open incident. "
            "Returns similarity score and linked incident ID if duplicate found. "
            "Call after parse_incident, in parallel with search_codebase."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "incident_text": {
                    "type": "string",
                    "description": "Combined title + description to search against past incidents"
                }
            },
            "required": ["incident_text"]
        }
    },
    {
        "name": "synthesize_triage",
        "description": (
            "Produce the final triage verdict: severity (P1-P4), confidence score, "
            "root cause hypothesis, investigation steps, remediation runbook with commands, "
            "and suggested assignee team. Call after search_codebase and check_duplicates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "escalate_p1",
        "description": (
            "Trigger P1 escalation: page oncall, mark incident as critical, "
            "emit urgent alert. ONLY call this when severity is P1. "
            "Call before create_ticket for P1 incidents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Incident title"},
                "assignee_team": {
                    "type": "string",
                    "description": "Team to page: sre-team, backend, data, platform"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "create_ticket",
        "description": (
            "Create a Jira ticket for this incident with severity-based priority. "
            "Skip this if the incident is a confirmed duplicate (check_duplicates returned is_duplicate=true)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "send_notifications",
        "description": (
            "Send email notifications to the team and reporter, and post to Slack. "
            "ALWAYS call this as the final step."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "query_metrics",
        "description": (
            "[SKILL] Query real-time service metrics for the affected service: error rate, "
            "request latency (p50/p95), memory usage, and anomaly detection. "
            "Call this in parallel with search_codebase and check_duplicates to enrich triage "
            "with live observability data. Skip if the service name is unknown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Name of the affected service (e.g. checkout, payment, auth)"
                },
                "window_minutes": {
                    "type": "integer",
                    "description": "Look-back window in minutes (default: 30)",
                    "default": 30
                }
            },
            "required": ["service"]
        }
    }
]

SYSTEM_PROMPT = """You are an expert SRE triage orchestrator. You will receive an incident report
and must investigate it thoroughly using the available tools.

REQUIRED workflow:
1. parse_incident — always first
2. search_codebase AND check_duplicates AND query_metrics — call all three simultaneously in a single turn
3. synthesize_triage — produce severity, root cause, runbook
4. If severity is P1: call escalate_p1 before create_ticket
5. If NOT a duplicate: call create_ticket
6. send_notifications — always last

query_metrics is a SKILL that provides live observability data (error rate, latency, anomalies).
Always call it in step 2 alongside the other parallel tools — it enriches the triage verdict.

Be decisive. Do not ask clarifying questions. Use all tools in sequence.
When you can call multiple tools simultaneously (step 2), do so in a single response."""


# ── Tool handlers ─────────────────────────────────────────────────────────────

async def _handle_parse_incident(inputs: dict, state: dict) -> dict:
    from app.agents.intake import intake_agent
    state.update({"raw_text": inputs.get("raw_text", state.get("raw_text", ""))})
    result = await intake_agent(state)
    state.update(result)
    return result.get("parsed_incident", {})


async def _handle_search_codebase(inputs: dict, state: dict) -> dict:
    from app.agents.code_analysis import code_analysis_agent
    result = await code_analysis_agent(state)
    state.update(result)
    ca = result.get("code_analysis", {})
    return {
        "relevant_files": ca.get("relevant_files", []),
        "analysis_summary": ca.get("analysis_summary", ""),
        "functions_involved": ca.get("functions_involved", []),
        "degraded": ca.get("degraded", False),
    }


async def _handle_check_duplicates(inputs: dict, state: dict) -> dict:
    from app.agents.deduplication import dedup_agent
    result = await dedup_agent(state)
    state.update(result)
    return result.get("dedup_result", {})


async def _handle_synthesize_triage(inputs: dict, state: dict) -> dict:
    from app.agents.triage_synth import triage_synthesizer
    result = await triage_synthesizer(state)
    state.update(result)
    verdict = result.get("triage_verdict") or {}
    return {
        "severity": verdict.get("severity"),
        "confidence": verdict.get("confidence"),
        "root_cause_hypothesis": verdict.get("root_cause_hypothesis"),
        "runbook_steps": len(verdict.get("runbook", [])),
        "suggested_assignee_team": verdict.get("suggested_assignee_team"),
        "needs_human_review": verdict.get("needs_human_review"),
    }


async def _handle_escalate_p1(inputs: dict, state: dict) -> dict:
    state["escalation_triggered"] = True
    logger.info(f"P1 escalation triggered for: {inputs.get('title')}")
    return {
        "escalated": True,
        "team_paged": inputs.get("assignee_team", "sre-team"),
        "message": "Oncall paged. Incident marked critical.",
    }


async def _handle_create_ticket(inputs: dict, state: dict) -> dict:
    from app.agents.ticket_agent import ticket_agent
    result = await ticket_agent(state)
    state.update(result)
    return {
        "ticket_id": result.get("ticket_id"),
        "ticket_url": result.get("ticket_url"),
    }


async def _handle_send_notifications(inputs: dict, state: dict) -> dict:
    from app.agents.notification import notification_agent
    result = await notification_agent(state)
    state.update(result)
    return {"notifications_sent": result.get("notifications_sent", [])}


async def _handle_query_metrics(inputs: dict, state: dict) -> dict:
    """
    [SKILL] Simulate querying Prometheus/Grafana metrics for the affected service.
    Returns error rate, latency percentiles, memory usage, and anomaly flag.
    In production this would call a real metrics API.
    """
    import random, math

    service = inputs.get("service", "unknown").lower()
    window  = inputs.get("window_minutes", 30)

    # Seed by service name so results are consistent per service within a pipeline run
    rng = random.Random(hash(service + state.get("incident_id", "")))

    # Simulate degraded metrics correlated with the incident
    parsed = state.get("parsed_incident") or {}
    is_critical = any(w in str(parsed).lower() for w in ["timeout", "500", "crash", "down", "unavailable"])

    base_error_rate = rng.uniform(0.15, 0.45) if is_critical else rng.uniform(0.01, 0.08)
    p50 = rng.randint(180, 600) if is_critical else rng.randint(40, 180)
    p95 = int(p50 * rng.uniform(2.5, 5.0))
    memory_pct = rng.randint(72, 95) if is_critical else rng.randint(40, 70)
    anomaly = base_error_rate > 0.10 or p95 > 1000 or memory_pct > 85

    result = {
        "service": service,
        "window_minutes": window,
        "error_rate": round(base_error_rate, 4),
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "memory_usage_pct": memory_pct,
        "anomaly_detected": anomaly,
        "metric_summary": (
            f"{service}: error_rate={base_error_rate:.1%}, "
            f"p50={p50}ms, p95={p95}ms, mem={memory_pct}% "
            f"{'⚠ ANOMALY' if anomaly else '✓ normal'}"
        ),
    }
    state["metrics_result"] = result
    logger.info(f"Metrics for {service}: {result['metric_summary']}")
    return result


TOOL_HANDLERS: dict[str, Any] = {
    "parse_incident":     _handle_parse_incident,
    "search_codebase":    _handle_search_codebase,
    "check_duplicates":   _handle_check_duplicates,
    "synthesize_triage":  _handle_synthesize_triage,
    "escalate_p1":        _handle_escalate_p1,
    "create_ticket":      _handle_create_ticket,
    "send_notifications": _handle_send_notifications,
    "query_metrics":      _handle_query_metrics,
}

# Map tool name → WS agent id (for UI pipeline panel)
TOOL_TO_AGENT_ID = {
    "parse_incident":     "intake",
    "search_codebase":    "code_analysis",
    "check_duplicates":   "dedup",
    "synthesize_triage":  "triage_synth",
    "escalate_p1":        "escalate",
    "create_ticket":      "ticket",
    "send_notifications": "notify",
    "query_metrics":      "metrics",
}

TOOL_START_MSG = {
    "parse_incident":     "Parsing incident report...",
    "search_codebase":    "Searching codebase for relevant files...",
    "check_duplicates":   "Checking for duplicate incidents...",
    "synthesize_triage":  "Synthesizing triage verdict and runbook...",
    "escalate_p1":        "P1 detected — triggering escalation...",
    "create_ticket":      "Creating Jira ticket...",
    "send_notifications": "Sending email and Slack notifications...",
    "query_metrics":      "Querying service metrics (error rate, latency)...",
}


# ── ReAct loop ────────────────────────────────────────────────────────────────

async def run_incident_pipeline(
    incident_data: dict,
    ws_callback: Optional[Callable] = None,
) -> dict:
    """
    Run the incident triage pipeline using ReAct tool-calling.

    Claude drives the workflow by calling tools in the right order.
    Multiple tools can be called simultaneously in a single turn.
    """
    import anthropic as anthropic_sdk

    settings = get_settings()
    from app.services.event_store import get_event_store as _get_event_store
    event_store = await _get_event_store()

    incident_id = incident_data.get("incident_id", str(uuid.uuid4()))
    submitted_at = datetime.utcnow().isoformat()

    # ── emit helper ──────────────────────────────────────────────────────────
    async def emit(phase: str, agent: str, data: dict):
        if ws_callback:
            try:
                ws_callback(phase, agent, data)
            except Exception as e:
                logger.warning(f"ws_callback error: {e}")

    # ── initial state ────────────────────────────────────────────────────────
    state: dict = {
        "incident_id": incident_id,
        "submitted_at": submitted_at,
        "raw_text": incident_data.get(
            "raw_text",
            f"{incident_data.get('title', '')}\n\n{incident_data.get('description', '')}"
        ),
        "attachments": incident_data.get("attachments", []),
        "reporter_email": incident_data.get("reporter_email", ""),
        "parsed_incident": None,
        "code_analysis": None,
        "dedup_result": None,
        "triage_verdict": None,
        "ticket_id": None,
        "ticket_url": None,
        "notifications_sent": [],
        "escalation_triggered": False,
        "current_phase": "initialized",
    }

    await event_store.log_event(
        incident_id=uuid.UUID(incident_id),
        phase="pipeline_started",
        agent="orchestrator",
        payload={"submitted_at": submitted_at, "pattern": "react_tool_calling"}
    )

    await emit("pipeline_started", "orchestrator", {
        "incident_id": incident_id,
        "pattern": "react_tool_calling",
        "agents": list(TOOL_TO_AGENT_ID.values()),
    })

    # ── build Anthropic client ────────────────────────────────────────────────
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY required for ReAct tool-calling")

    client = anthropic_sdk.Anthropic(api_key=settings.anthropic_api_key)

    # ── initial message ───────────────────────────────────────────────────────
    messages = [
        {
            "role": "user",
            "content": (
                f"Triage this incident:\n\n"
                f"Title: {incident_data.get('title', '')}\n"
                f"Description: {incident_data.get('description', '') or incident_data.get('raw_text', '')}\n"
                f"Reporter: {incident_data.get('reporter_email', '')}\n"
                f"Incident ID: {incident_id}"
            )
        }
    ]

    MAX_ITERATIONS = 15
    loop = asyncio.get_event_loop()

    try:
        for iteration in range(MAX_ITERATIONS):
            # ── call Claude with tools ────────────────────────────────────────
            logger.info(f"ReAct iteration {iteration + 1}")
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=4096,
                        system=SYSTEM_PROMPT,
                        tools=TOOLS,
                        messages=messages,
                    )
                ),
                timeout=90.0
            )

            # ── collect tool_use blocks ───────────────────────────────────────
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if response.stop_reason == "end_turn" or not tool_uses:
                logger.info(f"ReAct loop complete after {iteration + 1} iterations")
                break

            # ── emit started for all tools in this turn ───────────────────────
            for tu in tool_uses:
                agent_id = TOOL_TO_AGENT_ID.get(tu.name, tu.name)
                await emit("agent_started", agent_id, {
                    "message": TOOL_START_MSG.get(tu.name, f"Running {tu.name}..."),
                    "turn": iteration + 1,
                    "parallel": len(tool_uses) > 1,
                    "inputs": tu.input,
                })

            # ── execute all tools in this turn (parallel if multiple) ─────────
            async def run_tool(tu) -> tuple[str, str, dict, Exception | None]:
                """Execute one tool call, return (tool_use_id, name, result, error)."""
                handler = TOOL_HANDLERS.get(tu.name)
                if not handler:
                    return tu.id, tu.name, {"error": f"Unknown tool: {tu.name}"}, None
                try:
                    result = await handler(tu.input, state)
                    return tu.id, tu.name, result, None
                except Exception as e:
                    logger.exception(f"Tool {tu.name} failed: {e}")
                    return tu.id, tu.name, {"error": str(e)}, e

            tool_results_raw = await asyncio.gather(*[run_tool(tu) for tu in tool_uses])

            # ── emit completed + build tool_result content blocks ────────────
            tool_result_blocks = []
            for (tu_id, name, result, err) in tool_results_raw:
                agent_id = TOOL_TO_AGENT_ID.get(name, name)
                await emit("agent_completed", agent_id, {
                    **result,
                    "turn": iteration + 1,
                    "parallel": len(tool_uses) > 1,
                })

                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "content": json.dumps(result),
                })

            # ── update message history ────────────────────────────────────────
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_result_blocks})

        # ── build pipeline summary ────────────────────────────────────────────
        verdict = state.get("triage_verdict") or {}
        dedup   = state.get("dedup_result") or {}
        code_a  = state.get("code_analysis") or {}

        pipeline_summary = {
            "incident_id":          incident_id,
            "pattern":              "react_tool_calling",
            "severity":             verdict.get("severity"),
            "confidence":           verdict.get("confidence"),
            "root_cause_hypothesis":verdict.get("root_cause_hypothesis"),
            "investigation_steps":  verdict.get("investigation_steps", []),
            "runbook":              verdict.get("runbook", []),
            "suggested_assignee_team": verdict.get("suggested_assignee_team", "sre-team"),
            "needs_human_review":   verdict.get("needs_human_review", False),
            "escalation_triggered": state.get("escalation_triggered", False),
            "ticket_id":            state.get("ticket_id"),
            "ticket_url":           state.get("ticket_url"),
            "is_duplicate":         dedup.get("is_duplicate", False),
            "highest_similarity":   dedup.get("highest_similarity", 0),
            "linked_incident_id":   dedup.get("linked_incident_id", ""),
            "notifications_sent":   state.get("notifications_sent", []),
            "relevant_files":       code_a.get("relevant_files", []),
            "iterations":           iteration + 1,
            # Full agent outputs for UI reconstruction
            "intake":          state.get("parsed_incident") or {},
            "code_analysis":   code_a,
            "dedup_result":    dedup,
            "triage_verdict":  verdict,
            "metrics_result":  state.get("metrics_result") or {},
        }

        await event_store.save_pipeline_result(incident_id, pipeline_summary)
        await emit("pipeline_completed", "orchestrator", pipeline_summary)
        await event_store.log_event(
            incident_id=uuid.UUID(incident_id),
            phase="pipeline_completed",
            agent="orchestrator",
            payload={
                "ticket_id": state.get("ticket_id"),
                "severity": verdict.get("severity"),
                "iterations": iteration + 1,
            }
        )

        logger.info(
            f"Pipeline completed for {incident_id} in {iteration + 1} ReAct iterations"
        )
        return state

    except Exception as e:
        logger.exception(f"ReAct pipeline failed for {incident_id}: {e}")
        await emit("pipeline_failed", "orchestrator", {"error": str(e)})
        await event_store.log_event(
            incident_id=uuid.UUID(incident_id),
            phase="pipeline_failed",
            agent="orchestrator",
            payload={"error": str(e)}
        )
        raise


# ── Compat shim (API routes call get_orchestrator) ────────────────────────────

def get_orchestrator():
    """Backward-compat shim — returns the run function directly."""
    return run_incident_pipeline


