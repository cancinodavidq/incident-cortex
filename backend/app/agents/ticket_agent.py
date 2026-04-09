"""Ticket agent — creates JIRA tickets for triaged incidents."""

import logging
import json
import httpx
from typing import Optional

from app.config import get_settings
from app.services.event_store import EventStore
from app.models.incident import IncidentState

logger = logging.getLogger(__name__)


async def ticket_agent(state: IncidentState) -> dict:
    """
    Create JIRA ticket for triaged incident.

    1. Load triage_verdict, parsed_incident, code_analysis
    2. Build ticket payload
    3. POST to JIRA_MOCK_URL/api/issues
    4. Retry once on failure
    5. Return ticket_id and ticket_url
    """
    settings = get_settings()
    event_store = EventStore()

    try:
        incident_id = state.get("incident_id", "")
        verdict = state.get("triage_verdict", {})
        parsed = state.get("parsed_incident", {})
        code_analysis = state.get("code_analysis", {})

        if not verdict or not parsed:
            logger.error("Missing verdict or parsed_incident in state")
            return {
                "ticket_id": "MANUAL-REQUIRED",
                "ticket_url": "",
                "current_phase": "ticketing"
            }

        # Map severity to JIRA priority
        severity_to_priority = {
            "P1": "Critical",
            "P2": "High",
            "P3": "Medium",
            "P4": "Low"
        }

        severity = verdict.get("severity", "P3")
        priority = severity_to_priority.get(severity, "Medium")

        # Build ticket payload
        title = parsed.get("title", "Incident")
        description = f"""## Incident Report

**Service:** {parsed.get('affected_service', 'Unknown')}
**Error Type:** {parsed.get('error_type', 'Unknown')}

### Description
{parsed.get('description', 'No description')}

### Symptoms
- {chr(10).join(f"- {s}" for s in parsed.get('symptoms', []))}

### Root Cause Hypothesis
{verdict.get('root_cause_hypothesis', 'Pending investigation')}

### Affected Components
- {chr(10).join(f"- {c}" for c in verdict.get('affected_components', []))}

### Investigation Steps
1. {chr(10).join(f"{i+1}. {s}" for i, s in enumerate(verdict.get('investigation_steps', [])))}

### Code Analysis
{code_analysis.get('analysis_summary', 'No code analysis available')}

**Relevant Files:**
{chr(10).join(f"- {f}" for f in code_analysis.get('relevant_files', []))}

### Metadata
- Incident ID: {incident_id}
- Confidence: {verdict.get('confidence', 0) * 100:.0f}%
- Needs Review: {verdict.get('needs_human_review', False)}
"""

        labels = ["incident-cortex", severity, "auto-triaged"]
        if verdict.get("needs_human_review"):
            labels.append("needs-review")

        ticket_payload = {
            "summary": f"[{severity}] {title}",
            "description": description,
            "priority": priority,
            "labels": labels,
            "incident_id": incident_id,
            "confidence": verdict.get("confidence", 0),
            "needs_human_review": verdict.get("needs_human_review", False)
        }

        logger.info(f"Creating JIRA ticket for {incident_id}: {ticket_payload['summary']}")

        # POST to JIRA mock
        jira_url = settings.jira_mock_url
        ticket_endpoint = f"{jira_url}/api/issues"

        ticket_id = "MANUAL-REQUIRED"
        ticket_url = ""
        retry_count = 0

        while retry_count < 2:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        ticket_endpoint,
                        json=ticket_payload,
                        timeout=10.0
                    )
                    response.raise_for_status()

                    result = response.json()
                    ticket_id = result.get("key", result.get("id", "MANUAL-REQUIRED"))
                    ticket_url = result.get("url", "")

                    logger.info(f"Created ticket {ticket_id}")
                    break

            except Exception as e:
                retry_count += 1
                logger.warning(f"JIRA POST attempt {retry_count} failed: {e}")
                if retry_count >= 2:
                    logger.error(f"JIRA ticket creation failed after retries")
                    ticket_id = "MANUAL-REQUIRED"

        # Log to event store
        await event_store.log_event(
            incident_id=incident_id,
            event_type="ticket_created",
            data={
                "ticket_id": ticket_id,
                "ticket_url": ticket_url,
                "severity": severity,
                "priority": priority
            }
        )

        return {
            "ticket_id": ticket_id,
            "ticket_url": ticket_url,
            "current_phase": "ticketing"
        }

    except Exception as e:
        logger.exception(f"Ticket agent failed: {e}")
        return {
            "ticket_id": "MANUAL-REQUIRED",
            "ticket_url": "",
            "current_phase": "ticketing"
        }
