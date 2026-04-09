import logging
from typing import Dict, Any, Tuple, List
from enum import Enum

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Incident severity levels."""
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class OutputValidator:
    """Validates LLM output structure and content."""

    VALID_SEVERITIES = {s.value for s in Severity}
    CONFIDENCE_MIN = 0.0
    CONFIDENCE_MAX = 1.0
    MIN_REASON_LENGTH = 10
    MAX_REASON_LENGTH = 2000

    @staticmethod
    def validate_triage_result(result: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validate LLM triage result structure.
        Returns (is_valid, reason, sanitized_result)
        """
        sanitized = {}

        # Check severity
        severity = result.get("severity")
        if severity not in OutputValidator.VALID_SEVERITIES:
            logger.warning(f"Invalid severity: {severity}")
            return False, f"Invalid severity: {severity}", {}

        sanitized["severity"] = severity

        # Check confidence score
        confidence = result.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            logger.warning(f"Invalid confidence value: {confidence}")
            return False, "Confidence must be a number between 0 and 1", {}

        if not (OutputValidator.CONFIDENCE_MIN <= confidence <= OutputValidator.CONFIDENCE_MAX):
            logger.warning(f"Confidence out of range: {confidence}")
            return False, "Confidence must be between 0 and 1", {}

        sanitized["confidence"] = confidence

        # Check root cause hypothesis
        hypothesis = result.get("root_cause_hypothesis", "")
        if not isinstance(hypothesis, str):
            hypothesis = str(hypothesis)

        if len(hypothesis) < OutputValidator.MIN_REASON_LENGTH:
            logger.warning("Root cause hypothesis too short")
            return False, "Root cause hypothesis must be at least 10 characters", {}

        if len(hypothesis) > OutputValidator.MAX_REASON_LENGTH:
            logger.warning("Root cause hypothesis too long")
            hypothesis = hypothesis[: OutputValidator.MAX_REASON_LENGTH]

        sanitized["root_cause_hypothesis"] = hypothesis.strip()

        # Check recommended_files (optional)
        files = result.get("recommended_files", [])
        if not isinstance(files, list):
            files = []

        sanitized["recommended_files"] = [
            {"path": str(f.get("path", ""))[:500], "relevance_score": float(f.get("relevance_score", 0.0))}
            for f in files
            if isinstance(f, dict) and f.get("path")
        ][:20]  # Limit to 20 files

        # Check additional metadata
        metadata = result.get("metadata", {})
        if isinstance(metadata, dict):
            sanitized["metadata"] = {
                k: str(v)[:200] for k, v in metadata.items() if isinstance(k, str)
            }
        else:
            sanitized["metadata"] = {}

        return True, "", sanitized

    @staticmethod
    def validate_streaming_update(update: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate a streaming phase update.
        Returns (is_valid, reason).
        """
        phase = update.get("phase")
        valid_phases = {"submitted", "parsing", "analyzing", "triaging", "complete"}

        if phase not in valid_phases:
            logger.warning(f"Invalid phase: {phase}")
            return False, f"Invalid phase: {phase}"

        # If analyzing phase, check files list
        if phase == "analyzing":
            files = update.get("files", [])
            if not isinstance(files, list):
                logger.warning("Files must be a list")
                return False, "Files must be a list"

        # Check message length
        message = update.get("message", "")
        if len(str(message)) > 1000:
            logger.warning("Message too long")
            return False, "Message must be less than 1000 characters"

        return True, ""

    @staticmethod
    def sanitize_streaming_update(update: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize a streaming update, removing any potentially harmful content.
        Returns cleaned update dict.
        """
        sanitized = {}

        # Phase is already validated
        sanitized["phase"] = update.get("phase", "unknown")

        # Sanitize message
        message = str(update.get("message", "")).strip()
        sanitized["message"] = message[:1000]

        # Sanitize files list for analyzing phase
        if sanitized["phase"] == "analyzing":
            files = update.get("files", [])
            sanitized["files"] = [
                {"name": str(f.get("name", ""))[:500], "status": str(f.get("status", ""))[:50]}
                for f in files
                if isinstance(f, dict)
            ][:50]  # Limit to 50 files in stream

        # Optional timestamp
        timestamp = update.get("timestamp")
        if timestamp:
            sanitized["timestamp"] = str(timestamp)[:50]

        return sanitized

    @staticmethod
    def log_anomaly(anomaly_type: str, details: Dict[str, Any]):
        """Log output validation anomalies for monitoring."""
        logger.warning(f"Output anomaly: {anomaly_type} | {details}")
