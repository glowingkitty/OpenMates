# backend/tests/test_tracing/test_privacy_filter.py
"""
Tests for TracePrivacyFilter (wrapping SpanExporter) and determine_user_tier().

Verifies the 3-tier privacy model:
- Tier 1: Regular users, normal spans — strips sensitive attributes, pseudonymizes user_id
- Tier 2: Error spans from regular users — keeps operational attrs, strips high-sensitivity
- Tier 3: Admin/opted-in users — keeps all attributes unchanged
- Dev server: Keeps all attributes regardless of tier

Bug history this test suite guards against:
- Initial implementation — ensures privacy filtering works before spans reach OpenObserve
"""

import os
from datetime import date
from unittest.mock import patch, MagicMock
import pytest
from opentelemetry.sdk.trace.export import SpanExportResult


class TestTracePrivacyFilterTier1:
    """Tests for Tier 1 (regular user, normal span) filtering."""

    def test_tier1_removes_sensitive_attributes(self, tier1_span_attributes):
        """TracePrivacyFilter at Tier 1 removes sensitive attributes."""
        from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

        mock_inner = MagicMock()
        mock_inner.export.return_value = SpanExportResult.SUCCESS
        filter_exporter = TracePrivacyFilter(inner=mock_inner)

        # Create a mock span with tier1 attributes
        mock_span = MagicMock()
        mock_span.attributes = tier1_span_attributes
        mock_span.name = "POST /api/v1/chat"
        mock_span.context = MagicMock()
        mock_span.status = MagicMock()

        with patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"}):
            filter_exporter.export([mock_span])

        # Verify inner exporter was called
        mock_inner.export.assert_called_once()
        exported_spans = mock_inner.export.call_args[0][0]
        exported_attrs = exported_spans[0].attributes

        # These attributes should be REMOVED at Tier 1
        stripped_attrs = [
            "http.request.header.authorization",
            "http.request.header.cookie",
            "db.statement",
            "rpc.request.body",
            "ws.payload_size",
            "cache.key",
            "cache.value",
            "llm.timing",
            "skill.params",
        ]
        for attr in stripped_attrs:
            assert attr not in exported_attrs, f"Tier 1 should strip '{attr}'"

    def test_tier1_keeps_safe_attributes(self, tier1_span_attributes):
        """TracePrivacyFilter at Tier 1 keeps safe operational attributes."""
        from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

        mock_inner = MagicMock()
        mock_inner.export.return_value = SpanExportResult.SUCCESS
        filter_exporter = TracePrivacyFilter(inner=mock_inner)

        mock_span = MagicMock()
        mock_span.attributes = tier1_span_attributes
        mock_span.name = "POST /api/v1/chat"
        mock_span.context = MagicMock()
        mock_span.status = MagicMock()

        with patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"}):
            filter_exporter.export([mock_span])

        exported_spans = mock_inner.export.call_args[0][0]
        exported_attrs = exported_spans[0].attributes

        # These attributes should be KEPT at Tier 1
        kept_attrs = ["http.method", "http.route", "http.status_code", "service.name"]
        for attr in kept_attrs:
            assert attr in exported_attrs, f"Tier 1 should keep '{attr}'"

    def test_tier1_pseudonymizes_user_id(self, tier1_span_attributes):
        """TracePrivacyFilter at Tier 1 pseudonymizes 'enduser.id' to a 12-char hex hash."""
        from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

        mock_inner = MagicMock()
        mock_inner.export.return_value = SpanExportResult.SUCCESS
        filter_exporter = TracePrivacyFilter(inner=mock_inner)

        mock_span = MagicMock()
        mock_span.attributes = tier1_span_attributes
        mock_span.name = "POST /api/v1/chat"
        mock_span.context = MagicMock()
        mock_span.status = MagicMock()

        with patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"}):
            filter_exporter.export([mock_span])

        exported_spans = mock_inner.export.call_args[0][0]
        exported_attrs = exported_spans[0].attributes

        # enduser.id should be pseudonymized (12 hex chars, not the original value)
        assert "enduser.id" in exported_attrs
        user_id = exported_attrs["enduser.id"]
        assert user_id != "user-f21b15a5", "Tier 1 should pseudonymize user_id"
        assert len(user_id) == 12, "Pseudonymized user_id should be 12 hex chars"
        assert all(c in "0123456789abcdef" for c in user_id), "Should be hex string"


class TestTracePrivacyFilterTier2:
    """Tests for Tier 2 (error span from regular user) filtering."""

    def test_tier2_keeps_operational_attrs_but_strips_high_sensitivity(self, tier2_span_attributes):
        """TracePrivacyFilter at Tier 2 keeps operational attrs but strips high-sensitivity ones."""
        from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

        mock_inner = MagicMock()
        mock_inner.export.return_value = SpanExportResult.SUCCESS
        filter_exporter = TracePrivacyFilter(inner=mock_inner)

        mock_span = MagicMock()
        mock_span.attributes = tier2_span_attributes
        mock_span.name = "POST /api/v1/chat"
        mock_span.context = MagicMock()
        mock_span.status = MagicMock()

        with patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"}):
            filter_exporter.export([mock_span])

        exported_spans = mock_inner.export.call_args[0][0]
        exported_attrs = exported_spans[0].attributes

        # Tier 2 should KEEP these (they are tier 2+ attrs)
        assert "http.request.header.authorization_type" in exported_attrs
        assert "cache.hit" in exported_attrs
        assert "exception.stacktrace" in exported_attrs
        assert "celery.task_id" in exported_attrs

        # Tier 2 should STRIP tier 3 only attrs
        assert "cache.value" not in exported_attrs
        assert "llm.timing" not in exported_attrs
        assert "skill.params" not in exported_attrs

        # Always strip regardless of tier
        assert "http.request.header.cookie" not in exported_attrs
        assert "http.request.header.authorization" not in exported_attrs

    def test_tier2_keeps_real_user_id(self, tier2_span_attributes):
        """TracePrivacyFilter at Tier 2 keeps real 'enduser.id' (no pseudonymization)."""
        from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

        mock_inner = MagicMock()
        mock_inner.export.return_value = SpanExportResult.SUCCESS
        filter_exporter = TracePrivacyFilter(inner=mock_inner)

        mock_span = MagicMock()
        mock_span.attributes = tier2_span_attributes
        mock_span.name = "POST /api/v1/chat"
        mock_span.context = MagicMock()
        mock_span.status = MagicMock()

        with patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"}):
            filter_exporter.export([mock_span])

        exported_spans = mock_inner.export.call_args[0][0]
        exported_attrs = exported_spans[0].attributes

        assert exported_attrs.get("enduser.id") == "user-f21b15a5"


class TestTracePrivacyFilterTier3:
    """Tests for Tier 3 (admin/opted-in user) filtering."""

    def test_tier3_keeps_all_attributes_except_always_strip(self, tier3_span_attributes):
        """TracePrivacyFilter at Tier 3 keeps all attributes unchanged (except always-strip)."""
        from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

        mock_inner = MagicMock()
        mock_inner.export.return_value = SpanExportResult.SUCCESS
        filter_exporter = TracePrivacyFilter(inner=mock_inner)

        mock_span = MagicMock()
        mock_span.attributes = tier3_span_attributes
        mock_span.name = "POST /api/v1/chat"
        mock_span.context = MagicMock()
        mock_span.status = MagicMock()

        with patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"}):
            filter_exporter.export([mock_span])

        exported_spans = mock_inner.export.call_args[0][0]
        exported_attrs = exported_spans[0].attributes

        # Tier 3 should keep everything except always-strip
        assert "ws.payload_size" in exported_attrs
        assert "cache.key" in exported_attrs
        assert "cache.value" in exported_attrs
        assert "llm.timing" in exported_attrs
        assert "skill.params" in exported_attrs
        assert "exception.stacktrace" in exported_attrs
        assert "celery.task_id" in exported_attrs
        assert exported_attrs.get("enduser.id") == "admin-f21b15a5"

        # Always-strip should still be removed
        assert "http.request.header.cookie" not in exported_attrs
        assert "http.request.header.authorization" not in exported_attrs


class TestTracePrivacyFilterDevServer:
    """Tests for dev server mode (bypasses all filtering)."""

    def test_dev_server_keeps_all_attributes(self, tier1_span_attributes):
        """TracePrivacyFilter on dev server keeps all attributes regardless of tier."""
        from backend.shared.python_utils.tracing.privacy_filter import TracePrivacyFilter

        mock_inner = MagicMock()
        mock_inner.export.return_value = SpanExportResult.SUCCESS
        filter_exporter = TracePrivacyFilter(inner=mock_inner)

        mock_span = MagicMock()
        mock_span.attributes = tier1_span_attributes
        mock_span.name = "POST /api/v1/chat"
        mock_span.context = MagicMock()
        mock_span.status = MagicMock()

        with patch.dict(os.environ, {"SERVER_ENVIRONMENT": "dev"}):
            filter_exporter.export([mock_span])

        exported_spans = mock_inner.export.call_args[0][0]
        exported_attrs = exported_spans[0].attributes

        # Dev server should keep ALL attributes unchanged (including normally-stripped ones)
        assert "http.request.header.authorization" in exported_attrs
        assert "http.request.header.cookie" in exported_attrs
        assert "cache.value" in exported_attrs
        assert "llm.timing" in exported_attrs
        assert "skill.params" in exported_attrs
        assert exported_attrs.get("enduser.id") == "user-f21b15a5"


class TestPseudonymization:
    """Tests for user ID pseudonymization with daily salt rotation."""

    def test_pseudonymized_user_id_changes_with_daily_salt(self):
        """Pseudonymized user_id changes when daily salt rotates (different date)."""
        from backend.shared.python_utils.tracing.privacy_filter import _pseudonymize_user_id

        user_id = "user-f21b15a5"

        with patch("backend.shared.python_utils.tracing.privacy_filter.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 27)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            hash_day1 = _pseudonymize_user_id(user_id)

        # Reset cached salt by re-importing or using a fresh instance
        import backend.shared.python_utils.tracing.privacy_filter as pf
        pf._cached_salt = None
        pf._cached_salt_date = None

        with patch("backend.shared.python_utils.tracing.privacy_filter.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 28)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            hash_day2 = _pseudonymize_user_id(user_id)

        assert hash_day1 != hash_day2, "Pseudonymized IDs should differ across days"
        assert len(hash_day1) == 12
        assert len(hash_day2) == 12


class TestDetermineUserTier:
    """Tests for the determine_user_tier() function."""

    def test_admin_users_get_tier_3(self):
        """determine_user_tier returns 3 for admin users."""
        from backend.shared.python_utils.tracing.user_tier import determine_user_tier

        attrs = {"enduser.is_admin": True, "otel.status_code": "OK"}
        assert determine_user_tier(attrs) == 3

    def test_opted_in_users_get_tier_3(self):
        """determine_user_tier returns 3 for opted-in users."""
        from backend.shared.python_utils.tracing.user_tier import determine_user_tier

        attrs = {"enduser.debug_opted_in": True, "otel.status_code": "OK"}
        assert determine_user_tier(attrs) == 3

    def test_error_status_spans_get_tier_2(self):
        """determine_user_tier returns 2 for ERROR status spans."""
        from backend.shared.python_utils.tracing.user_tier import determine_user_tier

        attrs = {
            "enduser.is_admin": False,
            "enduser.debug_opted_in": False,
            "otel.status_code": "ERROR",
        }
        assert determine_user_tier(attrs) == 2

    def test_normal_spans_from_regular_users_get_tier_1(self):
        """determine_user_tier returns 1 for normal spans from regular users."""
        from backend.shared.python_utils.tracing.user_tier import determine_user_tier

        attrs = {
            "enduser.is_admin": False,
            "enduser.debug_opted_in": False,
            "otel.status_code": "OK",
        }
        assert determine_user_tier(attrs) == 1
