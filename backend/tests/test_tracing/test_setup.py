# backend/tests/test_tracing/test_setup.py
"""
Tests for OpenTelemetry tracing SDK initialization via setup_tracing().

Verifies that:
- TracerProvider is created with correct service.name resource attribute
- Auto-instrumentors for FastAPI, httpx, Celery, Redis are registered
- setup_tracing() is a no-op when OTEL_TRACING_ENABLED=false

Bug history this test suite guards against:
- Initial implementation — ensures OTel SDK initializes before FastAPI app creation
"""

import os
from unittest.mock import patch, MagicMock
import pytest
from opentelemetry import trace


class TestSetupTracing:
    """Tests for the setup_tracing() function."""

    def setup_method(self):
        """Reset the global tracer provider before each test."""
        # Reset to default NoOpTracerProvider
        trace.set_tracer_provider(trace.ProxyTracerProvider())

    def test_setup_tracing_creates_tracer_provider_with_service_name(self):
        """setup_tracing() creates a TracerProvider with service.name resource attribute."""
        with patch.dict(os.environ, {
            "OTEL_TRACING_ENABLED": "true",
            "OPENOBSERVE_ROOT_EMAIL": "test@example.com",
            "OPENOBSERVE_ROOT_PASSWORD": "testpassword",
        }):
            # Mock auto-instrumentors to prevent side effects
            with patch("backend.shared.python_utils.tracing.config.FastAPIInstrumentor") as mock_fastapi, \
                 patch("backend.shared.python_utils.tracing.config.HTTPXClientInstrumentor") as mock_httpx, \
                 patch("backend.shared.python_utils.tracing.config.CeleryInstrumentor") as mock_celery, \
                 patch("backend.shared.python_utils.tracing.config.RedisInstrumentor") as mock_redis, \
                 patch("backend.shared.python_utils.tracing.config.LoggingInstrumentor") as mock_logging:

                from backend.shared.python_utils.tracing import setup_tracing
                setup_tracing(service_name="test-api")

                provider = trace.get_tracer_provider()
                # The provider should be a real TracerProvider (not NoOp)
                from opentelemetry.sdk.trace import TracerProvider
                assert isinstance(provider, TracerProvider)

                # Check resource has correct service.name
                resource_attrs = dict(provider.resource.attributes)
                assert resource_attrs.get("service.name") == "test-api"

    def test_setup_tracing_registers_auto_instrumentors(self):
        """setup_tracing() registers auto-instrumentors for FastAPI, httpx, Celery, Redis."""
        with patch.dict(os.environ, {
            "OTEL_TRACING_ENABLED": "true",
            "OPENOBSERVE_ROOT_EMAIL": "test@example.com",
            "OPENOBSERVE_ROOT_PASSWORD": "testpassword",
        }):
            with patch("backend.shared.python_utils.tracing.config.FastAPIInstrumentor") as mock_fastapi, \
                 patch("backend.shared.python_utils.tracing.config.HTTPXClientInstrumentor") as mock_httpx, \
                 patch("backend.shared.python_utils.tracing.config.CeleryInstrumentor") as mock_celery, \
                 patch("backend.shared.python_utils.tracing.config.RedisInstrumentor") as mock_redis, \
                 patch("backend.shared.python_utils.tracing.config.LoggingInstrumentor") as mock_logging:

                from backend.shared.python_utils.tracing import setup_tracing
                setup_tracing(service_name="test-api")

                # Verify each instrumentor was called
                mock_fastapi.instrument.assert_called_once()
                mock_httpx.instrument.assert_called_once()
                mock_celery.return_value.instrument.assert_called_once()
                mock_redis.return_value.instrument.assert_called_once()
                mock_logging.return_value.instrument.assert_called_once()

    def test_setup_tracing_noop_when_disabled(self):
        """setup_tracing() is a no-op when OTEL_TRACING_ENABLED=false."""
        with patch.dict(os.environ, {
            "OTEL_TRACING_ENABLED": "false",
        }):
            from backend.shared.python_utils.tracing import setup_tracing
            setup_tracing(service_name="test-api")

            # Provider should NOT be a real TracerProvider
            provider = trace.get_tracer_provider()
            from opentelemetry.sdk.trace import TracerProvider
            assert not isinstance(provider, TracerProvider)
