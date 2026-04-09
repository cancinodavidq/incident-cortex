"""Notification agent — sends emails and Slack notifications."""

import logging
import asyncio
import httpx
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import get_settings
from app.services.event_store import EventStore
from app.models.incident import IncidentState

logger = logging.getLogger(__name__)


async def notification_agent(state: IncidentState) -> dict:
    """
    Send notifications to team and reporter.

    1. Load all state data
    2. Send 3 notifications in parallel:
       a. Email to team
       b. Email to reporter
       c. Slack webhook
    3. Track successes in notifications_sent
    4. Return notifications_sent and phase
    """
    settings = get_settings()
    event_store = EventStore()

    try:
        incident_id = state.get("incident_id", "")
        parsed = state.get("parsed_incident", {})
        verdict = state.get("triage_verdict") or {}
        code_analysis = state.get("code_analysis", {})
        dedup_result = state.get("dedup_result", {})
        ticket_id = state.get("ticket_id", "")
        reporter_email = state.get("reporter_email", "")

        notifications_sent = []

        # Prepare email content
        team_email_html = _build_team_email_html(
            incident_id=incident_id,
            parsed=parsed,
            verdict=verdict,
            code_analysis=code_analysis,
            ticket_id=ticket_id,
            dedup_result=dedup_result
        )

        if dedup_result.get("is_duplicate"):
            reporter_subject = f"Incident #{incident_id} - Linked to Existing Ticket"
            reporter_html = _build_reporter_duplicate_html(
                incident_id=incident_id,
                linked_id=dedup_result.get("linked_incident_id", ""),
                linked_title=dedup_result.get("linked_incident_title", "")
            )
        else:
            sev = verdict.get("severity", "P3")
            urgency_prefix = "🚨 [CRITICAL] " if sev == "P1" else ""
            reporter_subject = f"{urgency_prefix}Incident #{incident_id[:8]} - {sev} Triaged"
            reporter_html = _build_reporter_email_html(
                incident_id=incident_id,
                severity=sev,
                ticket_id=ticket_id,
                root_cause=verdict.get("root_cause_hypothesis", "")
            )

        severity = verdict.get("severity", "P3")
        escalation_triggered = state.get("escalation_triggered", False)

        slack_message = _build_slack_message(
            incident_id=incident_id,
            severity=severity,
            root_cause=verdict.get("root_cause_hypothesis", ""),
            ticket_id=ticket_id,
            title=parsed.get("title", ""),
            escalation=escalation_triggered,
            assignee_team=verdict.get("suggested_assignee_team", "sre-team"),
        )

        # Run notifications in parallel
        results = await asyncio.gather(
            _send_team_email(team_email_html),
            _send_reporter_email(reporter_email, reporter_subject, reporter_html),
            _send_slack_notification(slack_message),
            return_exceptions=True
        )

        # Process results
        team_email_ok = results[0] is True
        reporter_email_ok = results[1] is True
        slack_ok = results[2] is True

        if team_email_ok:
            notifications_sent.append("team_email")
            logger.info("Team email sent")
        else:
            logger.error(f"Team email failed: {results[0]}")

        if reporter_email and reporter_email_ok:
            notifications_sent.append("reporter_email")
            logger.info("Reporter email sent")
        elif reporter_email:
            logger.error(f"Reporter email failed: {results[1]}")

        if slack_ok:
            notifications_sent.append("slack")
            logger.info("Slack notification sent")
        else:
            logger.error(f"Slack notification failed: {results[2]}")

        # Log to event store
        await event_store.log_event(
            incident_id=incident_id,
            event_type="notifications_sent",
            data={
                "notifications_sent": notifications_sent,
                "team_email": team_email_ok,
                "reporter_email": reporter_email_ok if reporter_email else None,
                "slack": slack_ok
            }
        )

        return {
            "notifications_sent": notifications_sent,
            "current_phase": "notifying"
        }

    except Exception as e:
        logger.exception(f"Notification agent failed: {e}")
        return {
            "notifications_sent": [],
            "current_phase": "notifying"
        }


def _build_team_email_html(
    incident_id: str,
    parsed: dict,
    verdict: dict,
    code_analysis: dict,
    ticket_id: str,
    dedup_result: dict
) -> str:
    """Build professional HTML email for team."""
    severity = verdict.get("severity", "P3")
    confidence = verdict.get("confidence", 0)
    title = parsed.get("title", "Incident")
    description = parsed.get("description", "")
    root_cause = verdict.get("root_cause_hypothesis", "")
    relevant_files = code_analysis.get("relevant_files", [])

    files_html = "".join(f"<li>{f}</li>" for f in relevant_files) if relevant_files else "<li>None identified</li>"

    severity_color = {
        "P1": "#d32f2f",
        "P2": "#f57c00",
        "P3": "#fbc02d",
        "P4": "#388e3c"
    }.get(severity, "#666")

    html = f"""
    <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #333; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: {severity_color}; color: white; padding: 20px; border-radius: 4px 4px 0 0; }}
                .header h1 {{ margin: 0; font-size: 24px; }}
                .severity-badge {{ display: inline-block; background-color: rgba(255,255,255,0.2); padding: 4px 8px; border-radius: 3px; font-weight: bold; margin-top: 10px; }}
                .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .section {{ margin-bottom: 20px; }}
                .section h3 {{ border-bottom: 2px solid {severity_color}; padding-bottom: 10px; color: #333; }}
                .meta {{ background-color: #fff; padding: 10px; border-left: 4px solid {severity_color}; margin: 10px 0; }}
                .files-list {{ background-color: #fff; padding: 10px; }}
                .footer {{ background-color: #f0f0f0; padding: 15px; border-radius: 0 0 4px 4px; border: 1px solid #ddd; border-top: none; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{title}</h1>
                    <div class="severity-badge">{severity} • Confidence: {confidence*100:.0f}%</div>
                </div>
                <div class="content">
                    <div class="section">
                        <h3>Incident Summary</h3>
                        <p><strong>ID:</strong> {incident_id}</p>
                        <p><strong>Service:</strong> {parsed.get('affected_service', 'Unknown')}</p>
                        <p><strong>Error Type:</strong> {parsed.get('error_type', 'Unknown')}</p>
                        <p><strong>Ticket:</strong> <a href="#">{ticket_id}</a></p>
                    </div>

                    <div class="section">
                        <h3>Description</h3>
                        <p>{description}</p>
                    </div>

                    <div class="section">
                        <h3>Root Cause Hypothesis</h3>
                        <p>{root_cause}</p>
                    </div>

                    <div class="section">
                        <h3>Investigation Steps</h3>
                        <ol>
    """

    for step in verdict.get("investigation_steps", []):
        html += f"<li>{step}</li>"

    html += """
                        </ol>
                    </div>

                    <div class="section">
                        <h3>Relevant Code Files</h3>
                        <ul class="files-list">
    """
    html += files_html
    html += """
                        </ul>
                    </div>
                </div>
                <div class="footer">
                    Generated by Incident Cortex • Automated SRE Triage System
                </div>
            </div>
        </body>
    </html>
    """
    return html


def _build_reporter_email_html(incident_id: str, severity: str, ticket_id: str, root_cause: str) -> str:
    """Build HTML email for reporter."""
    severity_color = {
        "P1": "#d32f2f",
        "P2": "#f57c00",
        "P3": "#fbc02d",
        "P4": "#388e3c"
    }.get(severity, "#666")

    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: {severity_color};">Incident Triaged</h2>
                <p>Hi,</p>
                <p>Your incident report <strong>#{incident_id}</strong> has been received and triaged.</p>

                <div style="background-color: #f5f5f5; padding: 15px; border-left: 4px solid {severity_color}; margin: 20px 0;">
                    <p><strong>Severity:</strong> {severity}</p>
                    <p><strong>Ticket:</strong> {ticket_id}</p>
                    <p><strong>Root Cause (preliminary):</strong> {root_cause}</p>
                </div>

                <p>Our team is investigating this incident and will provide updates as they become available.</p>
                <p>Best regards,<br/>Incident Cortex</p>
            </div>
        </body>
    </html>
    """
    return html


def _build_reporter_duplicate_html(incident_id: str, linked_id: str, linked_title: str) -> str:
    """Build HTML email for duplicate incident reporter."""
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2>Incident Linked to Existing Report</h2>
                <p>Hi,</p>
                <p>Your incident report <strong>#{incident_id}</strong> has been analyzed and linked to an existing incident.</p>

                <div style="background-color: #f5f5f5; padding: 15px; border-left: 4px solid #388e3c; margin: 20px 0;">
                    <p><strong>Linked to:</strong> {linked_id}</p>
                    <p><strong>Title:</strong> {linked_title}</p>
                    <p>This helps our team consolidate related issues and avoid duplicate work.</p>
                </div>

                <p>Thank you for reporting!</p>
                <p>Best regards,<br/>Incident Cortex</p>
            </div>
        </body>
    </html>
    """
    return html


def _build_slack_message(
    incident_id: str,
    severity: str,
    root_cause: str,
    ticket_id: str,
    title: str,
    escalation: bool = False,
    assignee_team: str = "sre-team",
) -> dict:
    """Build Slack message payload with severity-based urgency."""
    severity_emoji = {
        "P1": ":red_circle:",
        "P2": ":orange_circle:",
        "P3": ":yellow_circle:",
        "P4": ":green_circle:"
    }.get(severity, ":grey_question:")

    header_text = f"{severity_emoji} {severity}: {title}"
    if escalation:
        header_text = f"🚨 CRITICAL ESCALATION — {title}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True}
        },
    ]

    if escalation:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*@oncall* — P1 incident requires immediate attention. Assigned to *{assignee_team}*."
            }
        })

    blocks.append({
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*Incident ID:*\n`{incident_id[:8]}`"},
            {"type": "mrkdwn", "text": f"*Ticket:*\n{ticket_id or 'pending'}"},
            {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
            {"type": "mrkdwn", "text": f"*Team:*\n{assignee_team}"},
        ]
    })
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*Root Cause Hypothesis:*\n{root_cause}"}
    })
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Generated by *Incident Cortex* · Automated SRE Triage"}]
    })

    return {
        "text": f"{severity_emoji} {severity} incident triaged: {title}",
        "channel": "#incidents",
        "username": "Incident Cortex",
        "blocks": blocks,
    }


async def _send_team_email(html_body: str) -> bool:
    """Send email to team via MailHog SMTP."""
    settings = get_settings()
    team_email = settings.team_email

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "New Incident Triaged"
        msg["From"] = settings.notification_from_email
        msg["To"] = team_email
        msg.attach(MIMEText(html_body, "html"))

        async with aiosmtplib.SMTP(
            hostname=settings.mailhog_smtp_host,
            port=settings.mailhog_smtp_port
        ) as smtp:
            await smtp.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Team email send failed: {e}")
        return False


async def _send_reporter_email(email: str, subject: str, html_body: str) -> bool:
    """Send email to reporter via MailHog SMTP."""
    if not email:
        return True  # Skip if no email

    settings = get_settings()

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.notification_from_email
        msg["To"] = email
        msg.attach(MIMEText(html_body, "html"))

        async with aiosmtplib.SMTP(
            hostname=settings.mailhog_smtp_host,
            port=settings.mailhog_smtp_port
        ) as smtp:
            await smtp.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Reporter email send failed: {e}")
        return False


async def _send_slack_notification(payload: dict) -> bool:
    """Send notification to Slack webhook."""
    settings = get_settings()
    slack_url = settings.slack_mock_url
    webhook_url = f"{slack_url}/webhook"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10.0)
            response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Slack webhook send failed: {e}")
        return False
