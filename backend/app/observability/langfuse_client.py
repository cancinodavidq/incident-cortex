"""
Langfuse wrapper with fallback to plain logging if Langfuse is not configured.
Provides LLM call logging and event tracking for the incident triage pipeline.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class LangfuseClient:
    """
    Client for logging LLM calls and events to Langfuse.
    Falls back to plain logging if Langfuse is not configured.
    """

    def __init__(self):
        """Initialize Langfuse client with fallback to logging."""
        self._enabled = False
        self._client = None

        try:
            # Try to import settings
            from app.config import get_settings

            settings = get_settings()
            self._enabled = bool(settings.langfuse_public_key and settings.langfuse_secret_key)

            if self._enabled:
                try:
                    from langfuse import Langfuse

                    self._client = Langfuse(
                        public_key=settings.langfuse_public_key,
                        secret_key=settings.langfuse_secret_key,
                        host=settings.langfuse_host or "https://cloud.langfuse.com",
                    )
                    logger.info("Langfuse client initialized successfully")
                except ImportError:
                    logger.warning("langfuse package not installed. Falling back to logging.")
                    self._enabled = False
                except Exception as e:
                    logger.warning(f"Langfuse initialization failed: {e}. Falling back to logging.")
                    self._enabled = False
        except ImportError:
            logger.warning("Settings module not found. Langfuse will be disabled.")
            self._enabled = False

    def log_llm_call(
        self,
        incident_id: str,
        model: str,
        prompt: str,
        completion: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        used_fallback: bool = False,
    ):
        """
        Log an LLM call to Langfuse (or plain logging if unavailable).

        Args:
            incident_id: The incident being triaged
            model: Model name (e.g., "claude-3-5-sonnet-20241022")
            prompt: Input prompt
            completion: LLM completion
            input_tokens: Input token count
            output_tokens: Output token count
            latency_ms: Latency in milliseconds
            used_fallback: Whether a fallback model was used
        """
        if self._enabled and self._client:
            try:
                generation = self._client.generation(
                    name="triage-llm-call",
                    model=model,
                    input=prompt[:2000],  # Truncate for safety
                    output=completion[:2000],
                    usage={"input": input_tokens, "output": output_tokens},
                    metadata={
                        "incident_id": incident_id,
                        "used_fallback": used_fallback,
                        "latency_ms": latency_ms,
                    },
                )
                if used_fallback:
                    logger.warning(f"LLM fallback used for incident {incident_id}")
            except Exception as e:
                logger.error(f"Langfuse logging failed: {e}")
        else:
            # Fallback to plain logging
            logger.info(
                f"LLM call | incident={incident_id} model={model} "
                f"tokens={input_tokens + output_tokens} latency={latency_ms:.0f}ms "
                f"fallback={used_fallback}"
            )

    def log_event(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Log an event to Langfuse (or plain logging if unavailable).

        Args:
            name: Event name (e.g., "triage_complete", "ticket_created")
            metadata: Optional metadata dict
        """
        if metadata is None:
            metadata = {}

        if self._enabled and self._client:
            try:
                self._client.event(name=name, metadata=metadata)
            except Exception as e:
                logger.error(f"Langfuse event logging failed: {e}")
        else:
            # Fallback to plain logging
            logger.info(f"Event: {name} | {metadata}")

    def log_trace_start(self, incident_id: str, trace_name: str = "incident_triage"):
        """
        Start a trace for an incident triage session.

        Args:
            incident_id: The incident being triaged
            trace_name: Trace name (default: "incident_triage")

        Returns:
            Trace object if Langfuse enabled, None otherwise
        """
        if self._enabled and self._client:
            try:
                trace = self._client.trace(name=trace_name, input={"incident_id": incident_id})
                return trace
            except Exception as e:
                logger.error(f"Langfuse trace creation failed: {e}")
                return None
        return None

    def is_enabled(self) -> bool:
        """Check if Langfuse is enabled."""
        return self._enabled


# Global singleton instance
_client: Optional[LangfuseClient] = None


def get_langfuse() -> LangfuseClient:
    """
    Get or create the global Langfuse client instance.

    Returns:
        LangfuseClient instance (may be in fallback logging mode)
    """
    global _client
    if _client is None:
        _client = LangfuseClient()
    return _client
