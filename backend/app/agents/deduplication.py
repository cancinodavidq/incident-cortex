"""Deduplication agent — detects duplicate incidents using semantic search."""

import logging
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.vector_store import VectorStore
from app.services.event_store import EventStore
from app.models.incident import IncidentState

logger = logging.getLogger(__name__)


class DedupResult(BaseModel):
    """Deduplication analysis result."""
    is_duplicate: bool = Field(False, description="Whether this is a duplicate incident")
    recommendation: str = Field(..., description="'create_new', 'link_existing', or 'link_existing_soft'")
    highest_similarity: float = Field(0.0, description="Highest similarity score found (0-1)")
    linked_incident_id: str = Field("", description="ID of linked incident if duplicate")
    linked_incident_title: str = Field("", description="Title of linked incident if duplicate")


async def dedup_agent(state: IncidentState) -> dict:
    """
    Detect duplicate incidents via semantic search.

    1. Load ParsedIncident
    2. Build dedup query from title + description + service
    3. Search incident embeddings (n_results=5)
    4. Compute highest_similarity
    5. Apply thresholds:
       - >= DUPLICATE_THRESHOLD: is_duplicate=True, "link_existing"
       - >= SUGGESTION_THRESHOLD: recommendation="link_existing" (soft), is_duplicate=False
       - else: "create_new"
    6. Store embedding for THIS incident
    7. Return dedup_result
    """
    settings = get_settings()
    vector_store = VectorStore()
    event_store = EventStore()

    try:
        incident_id = state.get("incident_id", "")
        parsed = state.get("parsed_incident", {})

        if not parsed:
            logger.warning("No parsed_incident in state, skipping dedup")
            return {
                "dedup_result": DedupResult(
                    recommendation="create_new",
                    highest_similarity=0.0
                ).model_dump()
            }

        # Build dedup query
        title = parsed.get("title", "")
        description = parsed.get("description", "")
        affected_service = parsed.get("affected_service", "")

        dedup_query = f"{title} {description} {affected_service or ''}"
        logger.info(f"Dedup query: {dedup_query[:100]}")

        # Search for similar incidents
        try:
            similar = vector_store.find_similar_incidents(dedup_query, n_results=5)
        except Exception as e:
            logger.error(f"Dedup search failed: {e}")
            similar = []

        # Compute highest similarity
        highest_similarity = 0.0
        linked_id = ""
        linked_title = ""

        if similar:
            highest_result = similar[0]
            highest_similarity = highest_result.get("relevance_score", 0.0)
            linked_id = highest_result.get("incident_id", "")
            linked_title = highest_result.get("title", "")

            logger.info(f"Highest similarity: {highest_similarity} (linked: {linked_id})")

        # Apply thresholds
        duplicate_threshold = settings.dedup_duplicate_threshold
        suggestion_threshold = settings.dedup_suggestion_threshold

        if highest_similarity >= duplicate_threshold:
            is_duplicate = True
            recommendation = "link_existing"
        elif highest_similarity >= suggestion_threshold:
            is_duplicate = False
            recommendation = "link_existing_soft"
        else:
            is_duplicate = False
            recommendation = "create_new"

        # Store embedding for this incident
        try:
            vector_store.add_incident_embedding(
                incident_id=incident_id,
                title=title,
                description=description,
                service=affected_service
            )
            logger.info(f"Stored embedding for incident {incident_id}")
        except Exception as e:
            logger.error(f"Failed to store incident embedding: {e}")

        result = DedupResult(
            is_duplicate=is_duplicate,
            recommendation=recommendation,
            highest_similarity=highest_similarity,
            linked_incident_id=linked_id,
            linked_incident_title=linked_title
        )

        # Log to event store
        await event_store.log_event(
            incident_id=incident_id,
            event_type="dedup_completed",
            data={
                "is_duplicate": is_duplicate,
                "recommendation": recommendation,
                "highest_similarity": highest_similarity,
                "linked_incident_id": linked_id
            }
        )

        return {"dedup_result": result.model_dump()}

    except Exception as e:
        logger.exception(f"Dedup agent failed: {e}")
        return {
            "dedup_result": DedupResult(
                recommendation="create_new",
                highest_similarity=0.0
            ).model_dump()
        }
