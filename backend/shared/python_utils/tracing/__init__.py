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

import importlib
from types import ModuleType


def setup_tracing(service_name: str = "api") -> None:
    """Import tracing setup lazily so utility modules stay dependency-light."""
    from backend.shared.python_utils.tracing.config import setup_tracing as _setup_tracing

    _setup_tracing(service_name=service_name)


def __getattr__(name: str) -> ModuleType:
    if name == "config":
        return importlib.import_module("backend.shared.python_utils.tracing.config")
    raise AttributeError(name)

__all__ = ["setup_tracing"]
