"""
Focused logout route regression tests.

These tests protect session teardown ordering around encrypted chat completion
recovery. They intentionally inspect source structure instead of importing the
route because lightweight host pytest gates do not install the full FastAPI task
and auth-schema dependency graph.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _logout_source() -> str:
    source = (REPO_ROOT / "backend/core/api/app/routes/auth_routes/auth_logout.py").read_text(
        encoding="utf-8",
    )
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, ast.AsyncFunctionDef) and item.name == "logout"
    )
    return ast.get_source_segment(source, node) or ""


def test_logout_invalidates_recovery_lease_before_session_removal() -> None:
    source = _logout_source()

    assert "invalidate_recovery_leases_for_device" in source
    assert "directus_service.logout_user" in source
    assert "delete(cache_key)" in source
    assert source.index("invalidate_recovery_leases_for_device") < source.index(
        "directus_service.logout_user",
    )
    assert source.index("invalidate_recovery_leases_for_device") < source.index(
        "delete(cache_key)",
    )


def test_logout_recovery_invalidation_failure_is_visible_but_non_blocking() -> None:
    source = _logout_source()

    assert "except ChatRecoveryProtocolError as recovery_error" in source
    assert "recovery_error.status_code == 404" in source
    assert "logger.warning" in source
    assert "Failed to invalidate recovery leases during logout" in source
