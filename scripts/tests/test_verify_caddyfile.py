"""Tests for deployment/verify-caddyfile.py route coverage rules.

The Caddy verifier is the deterministic guard that prevents newly registered
FastAPI routes from being omitted from dev/prod proxy allowlists. These tests
cover route-inventory entries that previously caused Caddy to abort live API
requests before FastAPI could return a normal auth error.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_CADDYFILE_PATH = REPO_ROOT / "deployment/verify-caddyfile.py"


def _load_verify_caddyfile_module():
    spec = importlib.util.spec_from_file_location("verify_caddyfile", VERIFY_CADDYFILE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_electronics_pcb_schematic_route_is_verified_and_allowlisted() -> None:
    verifier = _load_verify_caddyfile_module()
    route_prefix = "/v1/electronics/pcb-schematic"

    assert any(route[0] == route_prefix for route in verifier.FASTAPI_ROUTES)

    for caddyfile in (
        REPO_ROOT / "deployment/dev_server/Caddyfile",
        REPO_ROOT / "deployment/prod_server/Caddyfile",
    ):
        paths = verifier.parse_caddyfile_paths(caddyfile.read_text())
        assert verifier.path_is_covered(route_prefix, paths), caddyfile
