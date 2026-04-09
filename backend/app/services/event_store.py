"""
Event Store Service for Incident Cortex.

Provides PostgreSQL-backed event log and incident tracking using asyncpg.
"""

import json
import logging
import asyncio
from typing import Any, Optional
from datetime import datetime
import uuid
from uuid import UUID

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)


class EventStore:
    """PostgreSQL event store for incident tracking."""

    def __init__(self, settings=None):
        """
        Initialize event store.

        Args:
            settings: App settings object (uses get_settings() if None)
        """
        self.settings = settings or get_settings()
        self._pool: Optional[asyncpg.Pool] = None

    async def get_pool(self) -> asyncpg.Pool:
        """Get or create asyncpg connection pool."""
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=self.settings.database_url,
                    min_size=5,
                    max_size=20,
                )
                logger.info("PostgreSQL connection pool created")
            except Exception as e:
                logger.error(f"Failed to create connection pool: {e}")
                raise

        return self._pool

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        pool = await self.get_pool()

        schema_sql = """
        CREATE TABLE IF NOT EXISTS incidents (
            id UUID PRIMARY KEY,
            reporter_email VARCHAR(255),
            raw_text TEXT,
            current_phase VARCHAR(50) DEFAULT 'submitted',
            severity VARCHAR(10),
            ticket_id VARCHAR(100),
            ticket_url TEXT,
            pipeline_result JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        ALTER TABLE incidents ADD COLUMN IF NOT EXISTS pipeline_result JSONB;

        CREATE TABLE IF NOT EXISTS incident_events (
            id SERIAL PRIMARY KEY,
            incident_id UUID NOT NULL,
            phase VARCHAR(50) NOT NULL,
            agent VARCHAR(50) NOT NULL,
            payload JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_incident_events_incident_id
        ON incident_events(incident_id);

        CREATE TABLE IF NOT EXISTS system_status (
            key VARCHAR(100) PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """

        try:
            async with pool.acquire() as conn:
                await conn.execute(schema_sql)
            logger.info("Database schema initialized")
        except Exception as e:
            logger.error(f"Failed to initialize schema: {e}")
            raise

    async def create_incident(
        self,
        incident_id: UUID,
        reporter_email: str,
        raw_text: str,
    ) -> None:
        """
        Create a new incident.

        Args:
            incident_id: Unique incident ID
            reporter_email: Reporter's email address
            raw_text: Raw incident report text
        """
        pool = await self.get_pool()

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO incidents (id, reporter_email, raw_text)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    incident_id,
                    reporter_email,
                    raw_text,
                )
            logger.info(f"Created incident {incident_id}")
        except Exception as e:
            logger.error(f"Error creating incident {incident_id}: {e}")
            raise

    async def log_event(
        self,
        incident_id,
        phase: str = "",
        agent: str = "system",
        payload: dict = None,
        # legacy compat kwargs (ignored, use phase/agent/payload)
        event_type: str = None,
        data: dict = None,
    ) -> None:
        """
        Log an event for an incident.

        Args:
            incident_id: Incident ID
            phase: Current phase (parsing, analysis, triage, etc.)
            agent: Agent that produced the event
            payload: Event payload (dict, will be JSON serialized)
        """
        # Coerce string to UUID
        if isinstance(incident_id, str):
            incident_id = uuid.UUID(incident_id)
        # Legacy compat: event_type/data → phase/payload
        if event_type is not None:
            phase = event_type
        if data is not None and payload is None:
            payload = data

        pool = await self.get_pool()

        try:
            payload_json = json.dumps(payload) if payload else None

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO incident_events
                    (incident_id, phase, agent, payload)
                    VALUES ($1, $2, $3, $4)
                    """,
                    incident_id,
                    phase,
                    agent,
                    payload_json,
                )
            logger.debug(
                f"Logged event for incident {incident_id}: {phase} ({agent})"
            )
        except Exception as e:
            logger.error(
                f"Error logging event for incident {incident_id}: {e}"
            )
            raise

    async def get_events(self, incident_id: UUID) -> list[dict]:
        """
        Get all events for an incident.

        Args:
            incident_id: Incident ID

        Returns:
            List of event dicts with: id, phase, agent, payload, created_at
        """
        pool = await self.get_pool()

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, phase, agent, payload, created_at
                    FROM incident_events
                    WHERE incident_id = $1
                    ORDER BY created_at ASC
                    """,
                    incident_id,
                )

            events = []
            for row in rows:
                payload = json.loads(row["payload"]) if row["payload"] else {}
                events.append(
                    {
                        "id": row["id"],
                        "phase": row["phase"],
                        "agent": row["agent"],
                        "payload": payload,
                        "created_at": row["created_at"].isoformat(),
                    }
                )

            return events
        except Exception as e:
            logger.error(f"Error fetching events for incident {incident_id}: {e}")
            return []

    async def update_incident_phase(
        self,
        incident_id: UUID,
        phase: str,
        severity: Optional[str] = None,
        ticket_id: Optional[str] = None,
        ticket_url: Optional[str] = None,
    ) -> None:
        """
        Update incident phase and optional fields.

        Args:
            incident_id: Incident ID
            phase: New phase
            severity: Optional severity level
            ticket_id: Optional ticket ID
            ticket_url: Optional ticket URL
        """
        pool = await self.get_pool()

        try:
            async with pool.acquire() as conn:
                update_parts = [
                    "current_phase = $2",
                    "updated_at = NOW()",
                ]
                params = [incident_id, phase]
                param_index = 3

                if severity is not None:
                    update_parts.append(f"severity = ${param_index}")
                    params.append(severity)
                    param_index += 1

                if ticket_id is not None:
                    update_parts.append(f"ticket_id = ${param_index}")
                    params.append(ticket_id)
                    param_index += 1

                if ticket_url is not None:
                    update_parts.append(f"ticket_url = ${param_index}")
                    params.append(ticket_url)
                    param_index += 1

                update_sql = (
                    f"UPDATE incidents SET {', '.join(update_parts)} "
                    f"WHERE id = $1"
                )

                await conn.execute(update_sql, *params)

            logger.info(
                f"Updated incident {incident_id} phase to {phase}"
            )
        except Exception as e:
            logger.error(
                f"Error updating incident {incident_id} phase: {e}"
            )
            raise

    async def update_system_status(
        self,
        key: str,
        value: str,
    ) -> None:
        """
        Set a system status value.

        Args:
            key: Status key
            value: Status value
        """
        pool = await self.get_pool()

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO system_status (key, value)
                    VALUES ($1, $2)
                    ON CONFLICT (key) DO UPDATE
                    SET value = $2, updated_at = NOW()
                    """,
                    key,
                    value,
                )
            logger.debug(f"Set system status {key} = {value}")
        except Exception as e:
            logger.error(f"Error updating system status {key}: {e}")
            raise

    async def get_system_status(self, key: str) -> Optional[str]:
        """
        Get a system status value.

        Args:
            key: Status key

        Returns:
            Status value or None if not found
        """
        pool = await self.get_pool()

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM system_status WHERE key = $1",
                    key,
                )

            if row:
                return row["value"]
            return None
        except Exception as e:
            logger.error(f"Error fetching system status {key}: {e}")
            return None

    async def save_pipeline_result(self, incident_id, result: dict) -> None:
        """Persist final pipeline result so the UI can load it on refresh."""
        if isinstance(incident_id, str):
            incident_id = uuid.UUID(incident_id)
        pool = await self.get_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE incidents
                    SET pipeline_result = $2,
                        severity        = $3,
                        ticket_id       = $4,
                        current_phase   = 'completed',
                        updated_at      = NOW()
                    WHERE id = $1
                    """,
                    incident_id,
                    json.dumps(result),
                    result.get("severity"),
                    result.get("ticket_id"),
                )
        except Exception as e:
            logger.error(f"Error saving pipeline result for {incident_id}: {e}")

    async def get_incident(self, incident_id: str) -> Optional[dict]:
        """Get incident by ID with its latest state."""
        pool = await self.get_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM incidents WHERE id = $1",
                    uuid.UUID(incident_id),
                )
            if not row:
                return None
            d = dict(row)
            # Deserialize pipeline_result if stored as string
            if d.get("pipeline_result") and isinstance(d["pipeline_result"], str):
                d["pipeline_result"] = json.loads(d["pipeline_result"])
            return d
        except Exception as e:
            logger.error(f"Error fetching incident {incident_id}: {e}")
            raise

    async def list_recent_incidents(self, limit: int = 20) -> list[dict]:
        """List most recent incidents."""
        pool = await self.get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, reporter_email, current_phase, severity, ticket_id, "
                    "ticket_url, raw_text, pipeline_result, created_at "
                    "FROM incidents ORDER BY created_at DESC LIMIT $1",
                    limit,
                )
            result = []
            for r in rows:
                d = dict(r)
                # Normalize field names for frontend compatibility
                d["incident_id"] = str(d.pop("id"))
                d["phase"] = d.pop("current_phase", "submitted")
                # Extract title from pipeline_result or raw_text
                pr = d.get("pipeline_result")
                if pr:
                    if isinstance(pr, str):
                        pr = json.loads(pr)
                    d["title"] = (pr.get("intake") or {}).get("title") or ""
                if not d.get("title"):
                    d["title"] = (d.get("raw_text") or "").split("\n")[0][:80]
                d.pop("pipeline_result", None)
                result.append(d)
            return result
        except Exception as e:
            logger.error(f"Error listing incidents: {e}")
            raise

    async def get_incident_events(self, incident_id: str) -> Optional[list[dict]]:
        """Get event timeline for an incident."""
        pool = await self.get_pool()
        try:
            async with pool.acquire() as conn:
                # Verify incident exists
                exists = await conn.fetchval(
                    "SELECT 1 FROM incidents WHERE id = $1",
                    uuid.UUID(incident_id),
                )
                if not exists:
                    return None
                rows = await conn.fetch(
                    "SELECT phase, agent, payload, created_at FROM incident_events "
                    "WHERE incident_id = $1 ORDER BY created_at ASC",
                    uuid.UUID(incident_id),
                )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching events for {incident_id}: {e}")
            raise

    async def check_indexing_status(self) -> bool:
        """Check if codebase indexing is complete."""
        value = await self.get_system_status("indexing_complete")
        return value is not None

    async def compute_metrics(self) -> dict:
        """Compute incident metrics from DB."""
        pool = await self.get_pool()
        try:
            async with pool.acquire() as conn:
                total = await conn.fetchval("SELECT COUNT(*) FROM incidents") or 0
                severity_rows = await conn.fetch(
                    "SELECT severity, COUNT(*) as cnt FROM incidents "
                    "WHERE severity IS NOT NULL GROUP BY severity"
                )
            severity_dist = {r["severity"]: r["cnt"] for r in severity_rows}
            return {
                "total_incidents": total,
                "severity_distribution": severity_dist,
            }
        except Exception as e:
            logger.error(f"Error computing metrics: {e}")
            return {}

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL connection pool closed")


# Singleton instance
_event_store: EventStore | None = None


async def get_event_store() -> EventStore:
    """Get or create event store singleton."""
    global _event_store
    if _event_store is None:
        _event_store = EventStore()
        await _event_store.initialize()
    return _event_store
