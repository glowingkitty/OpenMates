# backend/tests/test_tracing/conftest.py
"""
Shared test fixtures for OpenTelemetry tracing tests.

Provides mock TracerProvider, InMemorySpanExporter, and sample span
attribute dictionaries for each privacy tier.
"""

import sys
from pathlib import Path

# Add project root to sys.path so 'backend.shared...' imports resolve
_project_root = str(Path(__file__).resolve().parents[3])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest
from unittest.mock import MagicMock
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes


@pytest.fixture
def in_memory_exporter():
    """Create an InMemorySpanExporter for capturing exported spans."""
    return InMemorySpanExporter()


@pytest.fixture
def mock_tracer_provider(in_memory_exporter):
    """Create a TracerProvider with an InMemorySpanExporter for testing."""
    resource = Resource.create({ResourceAttributes.SERVICE_NAME: "test-service"})
    provider = TracerProvider(resource=resource)
    processor = SimpleSpanProcessor(in_memory_exporter)
    provider.add_span_processor(processor)
    return provider


@pytest.fixture
def tier1_span_attributes():
    """Sample span attributes for a Tier 1 (regular user, normal span) scenario."""
    return {
        "http.method": "POST",
        "http.route": "/api/v1/chat",
        "http.status_code": 200,
        "http.request.header.authorization": "Bearer eyJ...",
        "http.request.header.cookie": "session=abc123",
        "http.request.header.authorization_type": "Bearer",
        "http.request.header.content_type": "application/json",
        "service.name": "api",
        "enduser.id": "user-f21b15a5",
        "enduser.is_admin": False,
        "enduser.debug_opted_in": False,
        "db.statement": "SELECT * FROM users WHERE id = ?",
        "db.query_timing": 12.5,
        "rpc.request.body": '{"message": "hello"}',
        "ws.payload_size": 1024,
        "cache.key": "chat:abc:messages",
        "cache.value": '{"encrypted": "..."}',
        "cache.hit": True,
        "llm.timing": 2500,
        "llm.token_count": 150,
        "skill.params": '{"skill_id": "ask"}',
        "exception.stacktrace": "Traceback ...",
        "celery.task_id": "task-uuid-123",
        "celery.queue": "ai-queue",
        "otel.status_code": "OK",
    }


@pytest.fixture
def tier2_span_attributes():
    """Sample span attributes for a Tier 2 (error span from regular user) scenario."""
    attrs = {
        "http.method": "POST",
        "http.route": "/api/v1/chat",
        "http.status_code": 500,
        "http.request.header.authorization": "Bearer eyJ...",
        "http.request.header.cookie": "session=abc123",
        "http.request.header.authorization_type": "Bearer",
        "http.request.header.content_type": "application/json",
        "service.name": "api",
        "enduser.id": "user-f21b15a5",
        "enduser.is_admin": False,
        "enduser.debug_opted_in": False,
        "db.statement": "SELECT * FROM users WHERE id = ?",
        "db.query_timing": 12.5,
        "rpc.request.body": '{"message": "hello"}',
        "ws.payload_size": 1024,
        "cache.key": "chat:abc:messages",
        "cache.value": '{"encrypted": "..."}',
        "cache.hit": True,
        "llm.timing": 2500,
        "llm.token_count": 150,
        "skill.params": '{"skill_id": "ask"}',
        "exception.stacktrace": "Traceback ...",
        "celery.task_id": "task-uuid-123",
        "celery.queue": "ai-queue",
        "otel.status_code": "ERROR",
    }
    return attrs


@pytest.fixture
def tier3_span_attributes():
    """Sample span attributes for a Tier 3 (admin user) scenario."""
    attrs = {
        "http.method": "POST",
        "http.route": "/api/v1/chat",
        "http.status_code": 200,
        "http.request.header.authorization": "Bearer eyJ...",
        "http.request.header.cookie": "session=abc123",
        "http.request.header.authorization_type": "Bearer",
        "http.request.header.content_type": "application/json",
        "service.name": "api",
        "enduser.id": "admin-f21b15a5",
        "enduser.is_admin": True,
        "enduser.debug_opted_in": False,
        "db.statement": "SELECT * FROM users WHERE id = ?",
        "db.query_timing": 12.5,
        "rpc.request.body": '{"message": "hello"}',
        "ws.payload_size": 1024,
        "cache.key": "chat:abc:messages",
        "cache.value": '{"encrypted": "..."}',
        "cache.hit": True,
        "llm.timing": 2500,
        "llm.token_count": 150,
        "skill.params": '{"skill_id": "ask"}',
        "exception.stacktrace": "Traceback ...",
        "celery.task_id": "task-uuid-123",
        "celery.queue": "ai-queue",
        "otel.status_code": "OK",
    }
    return attrs
