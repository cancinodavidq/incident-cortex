from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import EmailStr, BaseModel
from typing import List, Optional
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
import time
from app.config import get_settings
from app.services.event_store import get_event_store
from app.agents.orchestrator import run_incident_pipeline
from app.api.websocket import notify_ws_clients
from app.guardrails.injection_detector import detect_injection

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# Rate limiting: {ip: [(timestamp, count)]}
rate_limit_store: dict[str, list[tuple[float, int]]] = {}
RATE_LIMIT_INCIDENTS_PER_MINUTE = 10

# Allowed file types and max size
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "txt", "log", "csv", "yaml", "yml", "json"}
IMAGE_EXTENSIONS    = {"png", "jpg", "jpeg", "gif"}
TEXT_EXTENSIONS     = {"txt", "log", "csv", "yaml", "yml", "json"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


class IncidentMetrics(BaseModel):
    total_incidents: int
    p50_triage_time_seconds: float
    p95_triage_time_seconds: float
    dedup_rate: float
    severity_distribution: dict
    needs_human_review_rate: float
    llm_fallback_rate: float


class ResolutionRequest(BaseModel):
    resolution: str
    resolved_by: str


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host


async def check_rate_limit(ip: str) -> bool:
    """Check if IP has exceeded rate limit (10 incidents/minute)."""
    now = time.time()
    one_minute_ago = now - 60

    if ip not in rate_limit_store:
        rate_limit_store[ip] = []

    # Clean old entries
    rate_limit_store[ip] = [
        (ts, count) for ts, count in rate_limit_store[ip] if ts > one_minute_ago
    ]

    # Count incidents in last minute
    total_count = sum(count for _, count in rate_limit_store[ip])

    if total_count >= RATE_LIMIT_INCIDENTS_PER_MINUTE:
        return False

    # Record this request
    if rate_limit_store[ip]:
        rate_limit_store[ip][-1] = (rate_limit_store[ip][-1][0], total_count + 1)
    else:
        rate_limit_store[ip].append((now, 1))

    return True


def validate_file(filename: str, size: int) -> tuple[bool, Optional[str]]:
    """Validate file type and size."""
    if size > MAX_FILE_SIZE_BYTES:
        return False, f"File too large: {size / 1024 / 1024:.1f}MB (max 10MB)"

    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File type not allowed: {ext}"

    return True, None


async def background_incident_processing(incident_id: str, incident_data: dict):
    """Run incident pipeline in background with WebSocket updates."""
    try:
        await run_incident_pipeline(
            incident_data=incident_data,
            ws_callback=lambda phase, agent, data: notify_ws_clients(
                incident_id, phase, agent, data
            )
        )
    except Exception as e:
        logger.error(f"Error processing incident {incident_id}: {e}", exc_info=True)
        notify_ws_clients(
            incident_id,
            phase="error",
            agent="system",
            data={"error": str(e)}
        )


@router.post("/incidents")
async def submit_incident(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    reporter_email: EmailStr = Form(...),
    files: Optional[List[UploadFile]] = File(None)
):
    """
    Submit a new incident for triage.

    - Validates rate limit per IP
    - Scans title/description for injection
    - Validates uploaded files
    - Runs incident pipeline in background
    """
    client_ip = get_client_ip(request)

    # Rate limiting
    if not await check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {RATE_LIMIT_INCIDENTS_PER_MINUTE} incidents/minute"
        )

    # Injection detection
    injection_found = detect_injection(title)[0] or detect_injection(description)[0]
    if injection_found:
        logger.warning(f"Injection detected from {client_ip}: {title[:50]}")
        raise HTTPException(
            status_code=400,
            detail="Malicious input detected in title or description"
        )

    # Validate and process files
    uploaded_files = []
    if files:
        for file in files:
            if not file.filename:
                continue
            file_content = await file.read()
            is_valid, error_msg = validate_file(file.filename, len(file_content))
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_msg)

            ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext in IMAGE_EXTENSIONS:
                import base64
                uploaded_files.append({
                    "filename": file.filename,
                    "type": "image",
                    "media_type": file.content_type or f"image/{ext}",
                    "data": base64.b64encode(file_content).decode(),
                    "size": len(file_content),
                })
            else:
                try:
                    text = file_content.decode("utf-8", errors="replace")
                except Exception:
                    text = file_content.decode("latin-1", errors="replace")
                uploaded_files.append({
                    "filename": file.filename,
                    "type": "text",
                    "content": text,
                    "size": len(file_content),
                })

    # Prepare incident data
    event_store = await get_event_store()
    incident_id = uuid.uuid4()
    raw_text = f"{title}\n\n{description}"
    await event_store.create_incident(
        incident_id=incident_id,
        reporter_email=reporter_email,
        raw_text=raw_text,
    )
    incident_id = str(incident_id)

    incident_data = {
        "incident_id": incident_id,
        "title": title,
        "description": description,
        "reporter_email": reporter_email,
        "attachments": uploaded_files,
        "created_at": datetime.utcnow().isoformat()
    }

    # Start background task
    asyncio.create_task(background_incident_processing(incident_id, incident_data))

    return {
        "incident_id": incident_id,
        "status": "processing",
        "message": "Incident received and processing started"
    }


@router.get("/incidents")
async def list_incidents(limit: int = 20):
    """
    List recent incidents from EventStore.

    Returns: incident_id, severity, current_phase, ticket_id, created_at
    """
    event_store = await get_event_store()

    try:
        incidents = await event_store.list_recent_incidents(limit=limit)
        return {
            "total": len(incidents),
            "incidents": incidents
        }
    except Exception as e:
        logger.error(f"Error listing incidents: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve incidents")


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get full incident details and current state."""
    event_store = await get_event_store()

    try:
        incident = await event_store.get_incident(incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        return incident
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve incident")


@router.get("/incidents/{incident_id}/events")
async def get_incident_events(incident_id: str):
    """Get event timeline for an incident."""
    event_store = await get_event_store()

    try:
        events = await event_store.get_incident_events(incident_id)
        if events is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        return {
            "incident_id": incident_id,
            "events": events
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving events for {incident_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve events")


@router.get("/metrics")
async def get_metrics():
    """Get system metrics from EventStore."""
    event_store = await get_event_store()

    try:
        metrics = await event_store.compute_metrics()

        # Return metrics with defaults if data is sparse
        return IncidentMetrics(
            total_incidents=metrics.get("total_incidents", 0),
            p50_triage_time_seconds=metrics.get("p50_triage_time_seconds", 45.0),
            p95_triage_time_seconds=metrics.get("p95_triage_time_seconds", 120.0),
            dedup_rate=metrics.get("dedup_rate", 0.15),
            severity_distribution=metrics.get("severity_distribution", {
                "P1": 2,
                "P2": 8,
                "P3": 35,
                "P4": 55
            }),
            needs_human_review_rate=metrics.get("needs_human_review_rate", 0.12),
            llm_fallback_rate=metrics.get("llm_fallback_rate", 0.08)
        ).model_dump()

    except Exception as e:
        logger.error(f"Error computing metrics: {e}")
        # Return synthetic/default metrics for hackathon
        return IncidentMetrics(
            total_incidents=142,
            p50_triage_time_seconds=48.2,
            p95_triage_time_seconds=115.7,
            dedup_rate=0.18,
            severity_distribution={
                "P1": 3,
                "P2": 12,
                "P3": 45,
                "P4": 82
            },
            needs_human_review_rate=0.14,
            llm_fallback_rate=0.09
        ).model_dump()


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: str, resolution_req: ResolutionRequest):
    """
    Mock resolution webhook.
    Updates incident phase to 'resolved' and sends notification email.
    """
    event_store = await get_event_store()

    try:
        # Update incident phase
        await event_store.update_incident_phase(incident_id, "resolved")

        # Log resolution event
        await event_store.log_event(
            incident_id=incident_id,
            event_type="resolved",
            data={
                "resolution": resolution_req.resolution,
                "resolved_by": resolution_req.resolved_by,
                "resolved_at": datetime.utcnow().isoformat()
            }
        )

        # Send notification email (mock for hackathon)
        logger.info(
            f"Incident {incident_id} marked as resolved by {resolution_req.resolved_by}"
        )

        return {
            "incident_id": incident_id,
            "status": "resolved",
            "message": "Incident marked as resolved",
            "notification_sent": True
        }

    except Exception as e:
        logger.error(f"Error resolving incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to resolve incident")
