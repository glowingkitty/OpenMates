# backend/shared/python_utils/tracing/config.py
"""
OpenTelemetry SDK initialization and auto-instrumentation configuration.

Sets up TracerProvider with OTLP HTTP exporter targeting OpenObserve,
wrapped by TracePrivacyFilter for privacy-aware span export. Registers
auto-instrumentors for FastAPI, httpx, Celery, Redis, and logging.

Must be called BEFORE FastAPI() app creation so that auto-instrumentation
can patch the framework's request handling.

Architecture context: docs/architecture/observability.md
"""

import base64
import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

logger = logging.getLogger(__name__)

# OTLP endpoint for OpenObserve traces ingestion
OTLP_ENDPOINT = "http://openobserve:5080/api/default/v1/traces"

# Environment variable controlling whether tracing is enabled
OTEL_TRACING_ENABLED_VAR = "OTEL_TRACING_ENABLED"
OTEL_TRACING_ENABLED_DEFAULT = "true"


def _build_auth_header() -> str:
    """
    Build HTTP Basic auth header for OpenObserve from environment variables.

    Uses the same credentials as the existing OpenObserve log collector:
    OPENOBSERVE_ROOT_EMAIL and OPENOBSERVE_ROOT_PASSWORD.

    Returns:
        str: Base64-encoded Basic auth header value.
    """
    email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")
    credentials = f"{email}:{password}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def setup_tracing(service_name: str = "api") -> None:
    """
    Initialize OpenTelemetry SDK with TracerProvider, OTLP exporter, and
    auto-instrumentation for FastAPI, httpx, Celery, Redis, and logging.

    Gated by OTEL_TRACING_ENABLED env var (default: "true"). When disabled,
    this function is a no-op and no TracerProvider is registered.

    Must be called BEFORE FastAPI() creation so auto-instrumentation patches
    the framework's request handling middleware.

    Args:
        service_name: The service.name resource attribute for this service.
            Use "api" for the central gateway, "app-{name}" for microservices.
    """
    enabled = os.getenv(OTEL_TRACING_ENABLED_VAR, OTEL_TRACING_ENABLED_DEFAULT)
    if enabled.lower() != "true":
        logger.info("OpenTelemetry tracing disabled (OTEL_TRACING_ENABLED=%s)", enabled)
        return

    logger.info("Initializing OpenTelemetry tracing for service '%s'", service_name)

    # Create resource identifying this service
    resource = Resource.create({"service.name": service_name})

    # Create OTLP HTTP exporter targeting OpenObserve
    otlp_exporter = OTLPSpanExporter(
        endpoint=OTLP_ENDPOINT,
        headers={"Authorization": _build_auth_header()},
    )

    # Wrap the OTLP exporter with the privacy filter
    privacy_exporter = TracePrivacyFilter(inner=otlp_exporter)

    # Create TracerProvider with resource
    provider = TracerProvider(resource=resource)

    # Add BatchSpanProcessor with the privacy-filtered exporter
    processor = BatchSpanProcessor(privacy_exporter)
    provider.add_span_processor(processor)

    # Set as global tracer provider
    trace.set_tracer_provider(provider)

    # Register auto-instrumentors (all use instance-level .instrument() in 0.61b0+)
    FastAPIInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    RedisInstrumentor().instrument()
    LoggingInstrumentor().instrument()

    logger.info(
        "OpenTelemetry tracing initialized: service=%s, endpoint=%s",
        service_name,
        OTLP_ENDPOINT,
    )
