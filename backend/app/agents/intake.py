"""Incident intake agent — parses raw incident reports and extracts structured data."""

import logging
import json
from typing import Optional
from pydantic import BaseModel, Field
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import get_settings
from app.services.llm_client import LLMClient
from app.services.event_store import EventStore
from app.models.incident import IncidentState

logger = logging.getLogger(__name__)


class ParsedIncident(BaseModel):
    """Structured incident data extracted from raw report."""
    title: str = Field(..., description="Brief incident title")
    description: str = Field(..., description="Detailed incident description")
    affected_service: Optional[str] = Field(None, description="Affected service/component")
    error_type: Optional[str] = Field(None, description="Type of error (e.g., 500, timeout, memory leak)")
    symptoms: list[str] = Field(default_factory=list, description="List of observed symptoms")
    information_sufficient: bool = Field(True, description="Whether critical info is present")
    missing_info: list[str] = Field(default_factory=list, description="List of missing info if insufficient")
    extracted_from_image: Optional[str] = Field(None, description="Text extracted from attached images")


async def intake_agent(state: IncidentState) -> dict:
    """
    Parse incident report into structured ParsedIncident.

    1. Extract raw_text, attachments, reporter_email
    2. For image attachments, use Claude vision to extract text
    3. Parse into ParsedIncident via LLM
    4. If insufficient info, send clarification email
    5. Return state update with parsed_incident and phase
    """
    settings = get_settings()
    llm_client = LLMClient()
    event_store = EventStore()

    try:
        # Extract from state
        raw_text = state.get("raw_text", "")
        attachments = state.get("attachments", [])
        reporter_email = state.get("reporter_email", "")
        incident_id = state.get("incident_id", "")

        extracted_from_image = None

        # Process attachments
        image_texts = []
        text_attachment_parts = []
        for att in attachments:
            att_type = att.get("type", "")
            if att_type == "image":
                try:
                    image_data = att.get("data", "")
                    vision_prompt = "Extract any visible error messages, stack traces, logs, or relevant technical information from this image."
                    vision_result = await llm_client.vision_extract(image_data, vision_prompt)
                    if vision_result:
                        image_texts.append(f"[Image: {att.get('filename', 'attachment')}]\n{vision_result}")
                except Exception as e:
                    logger.warning(f"Vision extraction failed for {att.get('filename')}: {e}")
            elif att_type == "text":
                content = att.get("content", "")[:8000]
                text_attachment_parts.append(f"[File: {att.get('filename', 'attachment')}]\n{content}")

        if image_texts:
            extracted_from_image = "\n".join(image_texts)

        # Build prompt for LLM
        full_incident_text = raw_text
        if extracted_from_image:
            full_incident_text += f"\n\n[Extracted from images]\n{extracted_from_image}"
        if text_attachment_parts:
            full_incident_text += "\n\n[Attached files]\n" + "\n\n".join(text_attachment_parts)

        system_prompt = """You are an SRE incident intake agent for a Node.js e-commerce platform.
Parse the incident report and identify the affected service, error type, and symptoms.
Be conservative — only mark information_sufficient=false if critical info is genuinely missing
(no description, no error type, no affected service)."""

        user_prompt = f"""Parse this incident report into structured JSON matching this schema:
{{
  "title": "Brief incident title",
  "description": "Detailed description",
  "affected_service": "Service name or null",
  "error_type": "Error type or null",
  "symptoms": ["symptom1", "symptom2"],
  "information_sufficient": true|false,
  "missing_info": ["list of missing fields if insufficient"]
}}

Incident report:
{full_incident_text}

Return ONLY valid JSON."""

        response = await llm_client.call(system_prompt, user_prompt)

        # Parse JSON response
        try:
            parsed_json = json.loads(LLMClient.extract_json(response))
            parsed = ParsedIncident(**parsed_json)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            # Fallback: minimal parsing
            parsed = ParsedIncident(
                title=raw_text[:100],
                description=raw_text,
                information_sufficient=False,
                missing_info=["Structured parsing failed"]
            )

        # Send clarification email if needed
        if not parsed.information_sufficient and reporter_email:
            try:
                await _send_clarification_email(
                    reporter_email=reporter_email,
                    incident_id=incident_id,
                    missing_info=parsed.missing_info
                )
                logger.info(f"Sent clarification email to {reporter_email}")
            except Exception as e:
                logger.error(f"Failed to send clarification email: {e}")

        # Log to event store
        await event_store.log_event(
            incident_id=incident_id,
            event_type="intake_completed",
            data={
                "parsed_incident": parsed.model_dump(),
                "information_sufficient": parsed.information_sufficient
            }
        )

        current_phase = "parsing" if parsed.information_sufficient else "request_clarity"

        return {
            "parsed_incident": parsed.model_dump(),
            "extracted_from_image": extracted_from_image,
            "current_phase": current_phase
        }

    except Exception as e:
        logger.exception(f"Intake agent failed: {e}")
        raise


async def _send_clarification_email(
    reporter_email: str,
    incident_id: str,
    missing_info: list[str]
) -> None:
    """Send clarification request email via MailHog SMTP."""
    settings = get_settings()

    missing_list = "\n".join(f"  - {item}" for item in missing_info)

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Incident Clarification Required</h2>
            <p>Hi,</p>
            <p>Your incident report (#{incident_id}) requires additional information to proceed with triage:</p>
            <ul style="background-color: #f5f5f5; padding: 15px; border-left: 4px solid #ff9800;">
    """

    for item in missing_info:
        html_body += f"        <li>{item}</li>\n"

    html_body += """
            </ul>
            <p>Please reply to this email with the missing details.</p>
            <p>Best regards,<br/>Incident Cortex</p>
        </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Incident Clarification Required - #{incident_id}"
    msg["From"] = settings.notification_from_email
    msg["To"] = reporter_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        async with aiosmtplib.SMTP(hostname=settings.mailhog_smtp_host, port=settings.mailhog_smtp_port) as smtp:
            await smtp.send_message(msg)
    except Exception as e:
        logger.error(f"SMTP error sending to {reporter_email}: {e}")
        raise
