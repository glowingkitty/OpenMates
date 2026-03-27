# backend/shared/python_utils/tracing/__init__.py
"""
OpenTelemetry Tracing Module for OpenMates Backend.

Provides centralized OTel SDK initialization, auto-instrumentation for
FastAPI, httpx, Celery, and Redis, and a privacy-aware span exporter
that enforces a 3-tier attribute filtering model before spans reach
OpenObserve.

Usage: Call setup_tracing(service_name="api") before FastAPI() creation.
Gated by OTEL_TRACING_ENABLED env var (default: true).

Architecture context: docs/architecture/observability.md
"""

from backend.shared.python_utils.tracing.config import setup_tracing

__all__ = ["setup_tracing"]
