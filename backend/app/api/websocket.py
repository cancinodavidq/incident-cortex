from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List, Callable
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)
ws_router = APIRouter()

# Track active WebSocket connections per incident_id
# Structure: {incident_id: [WebSocket, WebSocket, ...]}
active_connections: Dict[str, List[WebSocket]] = {}


async def broadcast(incident_id: str, data: dict):
    """
    Broadcast a message to all WebSocket clients connected to an incident.
    """
    if incident_id not in active_connections:
        logger.debug(f"No active connections for incident {incident_id}")
        return

    disconnected = []

    for websocket in active_connections[incident_id]:
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.warning(
                f"Failed to send to WebSocket for incident {incident_id}: {e}"
            )
            disconnected.append(websocket)

    # Clean up disconnected clients
    for ws in disconnected:
        active_connections[incident_id].remove(ws)

    # Remove incident entry if no more connections
    if not active_connections[incident_id]:
        del active_connections[incident_id]


def notify_ws_clients(
    incident_id: str,
    phase: str,
    agent: str,
    data: dict
) -> None:
    """
    Called by the orchestrator to notify WebSocket clients of agent progress.

    This wraps the async broadcast in a way that can be called from sync context.
    """
    import asyncio

    message = {
        "phase": phase,
        "agent": agent,
        "data": data,
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If event loop is already running, schedule as a task
            asyncio.create_task(broadcast(incident_id, message))
        else:
            # Otherwise run it directly (shouldn't happen in FastAPI context)
            loop.run_until_complete(broadcast(incident_id, message))
    except RuntimeError:
        # No event loop in current thread, create one
        asyncio.run(broadcast(incident_id, message))


@ws_router.websocket("/ws/{incident_id}")
async def websocket_endpoint(websocket: WebSocket, incident_id: str):
    """
    WebSocket endpoint for streaming incident triage progress.

    Clients connect with /ws/{incident_id} and receive real-time updates
    about the incident analysis progress.
    """
    await websocket.accept()
    logger.info(f"WebSocket connection opened for incident {incident_id}")

    # Register this connection
    if incident_id not in active_connections:
        active_connections[incident_id] = []
    active_connections[incident_id].append(websocket)

    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "phase": "connected",
            "agent": "system",
            "data": {
                "message": f"Connected to incident {incident_id}",
                "incident_id": incident_id
            },
            "timestamp": datetime.utcnow().isoformat()
        })

        # Keep connection open and listen for client messages
        # (mainly for heartbeat/ping-pong)
        while True:
            try:
                data = await websocket.receive_text()
                # Handle heartbeat/ping messages from client
                if data == "ping":
                    await websocket.send_text("pong")
            except Exception as e:
                logger.warning(f"WebSocket receive error for {incident_id}: {e}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for incident {incident_id}")
    except Exception as e:
        logger.error(f"WebSocket error for incident {incident_id}: {e}", exc_info=True)
    finally:
        # Clean up on disconnect
        if incident_id in active_connections:
            try:
                active_connections[incident_id].remove(websocket)
                logger.info(
                    f"Removed connection for incident {incident_id}, "
                    f"remaining: {len(active_connections[incident_id])}"
                )
                if not active_connections[incident_id]:
                    del active_connections[incident_id]
            except ValueError:
                pass
