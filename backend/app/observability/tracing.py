"""
OpenTelemetry tracing setup for Incident Cortex.
Provides distributed tracing for incident triage pipeline.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    logger.warning("OpenTelemetry not installed. Tracing will be disabled.")


_tracer: Optional[object] = None


def setup_tracing(app=None):
    """
    Initialize OpenTelemetry tracing for Incident Cortex.
    Optionally instruments FastAPI app if provided.

    Args:
        app: FastAPI application instance (optional)

    Returns:
        The configured tracer, or None if OpenTelemetry is not available
    """
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not available. Tracing disabled.")
        return None

    global _tracer

    try:
        # Create resource
        resource = Resource.create({"service.name": "incident-cortex"})

        # Create tracer provider
        provider = TracerProvider(resource=resource)

        # Add console exporter (for development)
        # In production, you'd replace this with an exporter like JaegerExporter
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        # Set as global tracer provider
        trace.set_tracer_provider(provider)

        # Get tracer
        _tracer = trace.get_tracer("incident-cortex")

        # Optionally instrument FastAPI
        if app is not None:
            try:
                FastAPIInstrumentor.instrument_app(app)
                logger.info("FastAPI instrumentation enabled")
            except Exception as e:
                logger.warning(f"Failed to instrument FastAPI: {e}")

        logger.info("OpenTelemetry tracing initialized")
        return _tracer

    except Exception as e:
        logger.error(f"Failed to initialize tracing: {e}")
        return None


def get_tracer():
    """
    Get the global tracer instance.
    Returns None if tracing is not initialized or OpenTelemetry is unavailable.
    """
    global _tracer

    if _tracer is None and OTEL_AVAILABLE:
        # Lazy initialization
        _tracer = setup_tracing()

    return _tracer


def start_span(name: str, attributes: dict = None):
    """
    Start a new span in the current trace.
    Returns a context manager for use with 'with' statement.

    Args:
        name: Span name
        attributes: Optional dict of span attributes

    Example:
        with start_span("parse_incident", {"incident_id": "123"}):
            # do work
            pass
    """
    tracer = get_tracer()
    if tracer is None:
        # Return a no-op context manager
        class NoOpSpan:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return NoOpSpan()

    span = tracer.start_span(name)
    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, str(value)[:256])

    class SpanContext:
        def __enter__(ctx_self):
            return span
        def __exit__(ctx_self, *args):
            span.end()

    return SpanContext()
