# backend/tests/test_tracing/test_privacy_filter.py
# @privacy-promise: telemetry-privacy-filter
# contract-test-file: tooling
"""Contract tests for privacy-safe OpenTelemetry attribute export.

The exporter is a strict allowlist in every environment. Normal traces retain
only low-cardinality operational fields; approved diagnostic traces may add
exact non-content counts and reviewed identifiers. Content, stable product
identifiers, secrets, and raw errors are never exported.
"""

import os
import time
from unittest.mock import MagicMock, patch

from opentelemetry.sdk.trace.export import SpanExportResult


def _export(attributes: dict, environment: str = "production") -> dict:
    from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

    inner = MagicMock()
    inner.export.return_value = SpanExportResult.SUCCESS
    exporter = TracePrivacyFilter(inner=inner)
    span = MagicMock()
    span.attributes = attributes
    span.resource.attributes = {}

    with patch.dict(os.environ, {"SERVER_ENVIRONMENT": environment}):
        exporter.export([span])

    return inner.export.call_args[0][0][0].attributes


class TestTracePrivacyFilterAllowlist:
    # contract-test: direct surface=rest_api assertions=ai-request-observability.exporter.allowlist,ai-request-observability.structural-traces.content-free
    def test_keeps_reviewed_operational_attributes(self):
        attributes = {
            "service.name": "app-ai-worker",
            "http.method": "POST",
            "http.route": "/v1/ws",
            "http.status_code": 200,
            "ws.message_type": "chat_message_added",
            "cache.hit": True,
            "celery.queue": "app_ai",
            "ai.phase": "preprocess",
            "ai.status_class": "ok",
            "ai.model_family": "fast_routing_llm",
            "ai.capability_category": "web_search",
            "ai.duration_ms": 125.5,
            "ai.provider_purpose": "postprocess",
            "ai.terminal_class": "completed",
            "ai.first_token_ms": 800.0,
            "ai.final_marker_ms": 10_000.0,
            "ai.worker_tail_ms": 5_000.0,
            "ai.token_count_bucket": "10k_50k",
            "ai.retry_count_bucket": "0",
        }

        assert _export(attributes) == attributes

    # contract-test: direct surface=rest_api assertions=ai-request-observability.exporter.allowlist,ai-request-observability.default-metrics.identity-free
    def test_drops_unknown_content_identifiers_secrets_and_raw_errors(self):
        attributes = {
            "service.name": "api",
            "unknown.future.attribute": "must not pass",
            "enduser.id": "user-private",
            "chat.id": "chat-private",
            "message.id": "message-private",
            "celery.task_id": "task-private",
            "http.request.header.authorization": "Bearer secret",
            "http.request.header.cookie": "session=secret",
            "db.statement": "SELECT private_data",
            "rpc.request.body": '{"prompt":"private"}',
            "cache.key": "user:private",
            "cache.value": "private",
            "skill.params": "private",
            "exception.message": "private provider response",
            "exception.stacktrace": "private stack",
            "url.full": "https://example.invalid/private",
            "server.address": "private-provider.example",
            "messaging.destination.name": "chat_stream::private-chat-id",
            "file.name": "private.pdf",
        }

        assert _export(attributes) == {"service.name": "api"}

    # contract-test: direct surface=rest_api assertions=ai-request-observability.exporter.allowlist
    def test_dev_uses_the_same_strict_allowlist(self):
        attributes = {
            "service.name": "api",
            "enduser.id": "user-private",
            "rpc.request.body": "private",
            "unknown.future.attribute": "private",
        }

        assert _export(attributes, environment="dev") == {"service.name": "api"}

    # contract-test: direct surface=rest_api assertions=ai-request-observability.structural-traces.content-free
    def test_drops_span_events_and_link_attributes(self):
        from backend.shared.python_utils.tracing.privacy_filter import _FilteredSpan

        original = MagicMock()
        original.events = [MagicMock(attributes={"exception.message": "private"})]
        original.links = [MagicMock(attributes={"user.id": "private"})]
        original.status.status_code = MagicMock()
        original.status.description = "private provider response"
        from opentelemetry.sdk.resources import Resource

        filtered = _FilteredSpan(
            original,
            {"service.name": "api"},
            Resource({"service.name": "api"}),
        )

        assert filtered.events == ()
        assert filtered.links == ()
        assert filtered.status.description is None

    # contract-test: direct surface=rest_api assertions=ai-request-observability.exporter.allowlist,ai-request-observability.structural-traces.content-free
    def test_filters_resource_attributes_before_otlp_export(self):
        from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

        inner = MagicMock()
        inner.export.return_value = SpanExportResult.SUCCESS
        span = MagicMock()
        span.attributes = {"ai.phase": "main"}
        span.resource.attributes = {
            "service.name": "app-ai-worker",
            "server.address": "private-provider.example",
            "messaging.destination.name": "chat_stream::private-chat-id",
            "deployment.environment": "private-environment",
        }

        TracePrivacyFilter(inner).export([span])

        filtered_span = inner.export.call_args[0][0][0]
        assert dict(filtered_span.resource.attributes) == {
            "service.name": "app-ai-worker",
        }


class TestTracePrivacyFilterDiagnosticMode:
    # contract-test: direct surface=rest_api assertions=ai-request-observability.diagnostic-mode.bounded,ai-request-observability.exporter.allowlist
    def test_admin_or_opt_in_keeps_only_reviewed_exact_non_content_fields(self):
        attributes = {
            "enduser.is_admin": True,
            "service.name": "app-ai-worker",
            "ai.token_count": 39521,
            "ai.character_count": 158000,
            "ai.message_count": 18,
            "ai.request_count": 2,
            "ai.result_count": 12,
            "ai.retry_count": 1,
            "ai.model_id": "reviewed-model",
            "ai.app_id": "web",
            "ai.skill_id": "search",
            "enduser.id": "admin-private",
            "rpc.request.body": "private prompt",
            "exception.stacktrace": "private stack",
            "unknown.future.attribute": "private",
        }

        now = time.time()
        with patch.dict(os.environ, {
            "OTEL_DIAGNOSTIC_AUDIT_ID": "incident-scope",
            "OTEL_DIAGNOSTIC_OWNER": "on-call",
            "OTEL_DIAGNOSTIC_REASON": "slow-turn-investigation",
            "OTEL_DIAGNOSTIC_STARTED_AT": str(now - 60),
            "OTEL_DIAGNOSTIC_EXPIRES_AT": str(now + 3600),
        }):
            assert _export(attributes) == {
                "service.name": "app-ai-worker",
                "ai.token_count": 39521,
                "ai.character_count": 158000,
                "ai.message_count": 18,
                "ai.request_count": 2,
                "ai.result_count": 12,
                "ai.retry_count": 1,
                "ai.model_id": "reviewed-model",
                "ai.app_id": "web",
                "ai.skill_id": "search",
            }

    # contract-test: direct surface=rest_api assertions=ai-request-observability.diagnostic-mode.bounded
    def test_expired_diagnostic_scope_drops_exact_fields(self):
        attributes = {
            "enduser.is_admin": True,
            "service.name": "app-ai-worker",
            "ai.token_count": 39521,
        }
        with patch.dict(os.environ, {
            "OTEL_DIAGNOSTIC_AUDIT_ID": "expired-incident",
            "OTEL_DIAGNOSTIC_OWNER": "on-call",
            "OTEL_DIAGNOSTIC_REASON": "slow-turn-investigation",
            "OTEL_DIAGNOSTIC_STARTED_AT": str(time.time() - 3600),
            "OTEL_DIAGNOSTIC_EXPIRES_AT": str(time.time() - 1),
        }):
            assert _export(attributes) == {"service.name": "app-ai-worker"}

    def test_incomplete_diagnostic_scope_drops_exact_fields(self):
        attributes = {
            "enduser.is_admin": True,
            "service.name": "app-ai-worker",
            "ai.token_count": 39521,
        }
        with patch.dict(os.environ, {
            "OTEL_DIAGNOSTIC_AUDIT_ID": "missing-owner-and-reason",
            "OTEL_DIAGNOSTIC_EXPIRES_AT": str(time.time() + 3600),
        }, clear=True):
            assert _export(attributes) == {"service.name": "app-ai-worker"}

    # contract-test: direct surface=rest_api assertions=ai-request-observability.diagnostic-mode.bounded
    def test_regular_trace_drops_exact_diagnostic_fields(self):
        attributes = {
            "enduser.is_admin": False,
            "enduser.debug_opted_in": False,
            "service.name": "app-ai-worker",
            "ai.token_count": 39521,
            "ai.model_id": "reviewed-model",
            "ai.token_count_bucket": "10k_50k",
        }

        assert _export(attributes) == {
            "service.name": "app-ai-worker",
            "ai.token_count_bucket": "10k_50k",
        }


class TestDetermineUserTier:
    def test_admin_users_get_tier_3(self):
        from backend.shared.python_utils.tracing.user_tier import determine_user_tier

        assert determine_user_tier({"enduser.is_admin": True}) == 3

    def test_opted_in_users_get_tier_3(self):
        from backend.shared.python_utils.tracing.user_tier import determine_user_tier

        assert determine_user_tier({"enduser.debug_opted_in": True}) == 3

    def test_error_status_spans_get_tier_2(self):
        from backend.shared.python_utils.tracing.user_tier import determine_user_tier

        assert determine_user_tier({"otel.status_code": "ERROR"}) == 2

    def test_normal_spans_from_regular_users_get_tier_1(self):
        from backend.shared.python_utils.tracing.user_tier import determine_user_tier

        assert determine_user_tier({"otel.status_code": "OK"}) == 1
