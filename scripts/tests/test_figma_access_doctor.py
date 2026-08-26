# contract-test-file: tooling
"""Tests for the safe Figma access doctor.

Purpose: make sure rate-limit diagnosis remains useful without exposing tokens,
private Figma response bodies, or unreleased design data. The tests use mocked
network responses only. Run with
`python3 -m pytest scripts/tests/test_figma_access_doctor.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/figma_access_doctor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_figma_access_doctor", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str]) -> None:
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_build_probe_endpoints_encodes_node_id() -> None:
    module = load_module()

    endpoints = module.build_probe_endpoints("file key", "4944:31418")

    assert endpoints[0] == ("file_outline", "/files/file%20key?depth=1")
    assert endpoints[1] == ("node_json", "/files/file%20key/nodes?ids=4944%3A31418")
    assert "ids=4944%3A31418" in endpoints[2][1]


def test_tokens_use_control_plane_root() -> None:
    module = load_module()

    assert module.TOKEN_FILES == (
        module.CONTROL_PLANE_ROOT / ".env.figma.local",
        module.CONTROL_PLANE_ROOT / ".env",
    )


def test_mcp_launcher_uses_git_common_directory() -> None:
    source = (ROOT / "scripts" / "run_figma_mcp.sh").read_text(encoding="utf-8")

    assert "rev-parse --git-common-dir" in source
    assert "Cannot resolve the OpenMates control-plane checkout" in source
    assert 'TOKEN_FILE="${CONTROL_PLANE_ROOT}/.env.figma.local"' in source


def test_probe_endpoint_reports_rate_limit_headers_without_token(monkeypatch) -> None:
    module = load_module()
    token = "private-token-value"

    def fail_request(*_args, **_kwargs):
        raise HTTPError(
            url="https://api.figma.com/v1/files/file-key/nodes",
            code=429,
            msg="Too Many Requests",
            hdrs={
                "retry-after": "123",
                "x-figma-plan-tier": "starter",
                "x-figma-rate-limit-type": "high",
            },
            fp=None,
        )

    monkeypatch.setattr(module, "urlopen", fail_request)

    result = module.probe_endpoint("node_json", "/files/file-key/nodes?ids=1%3A2", token)

    assert result.status == 429
    assert result.retry_after == "123"
    assert result.plan_tier == "starter"
    assert result.rate_limit_type == "high"
    assert token not in str(result)


def test_probe_endpoint_reports_success_headers(monkeypatch) -> None:
    module = load_module()

    def ok_request(*_args, **_kwargs):
        return FakeResponse(200, {})

    monkeypatch.setattr(module, "urlopen", ok_request)

    result = module.probe_endpoint("image_export", "/images/file-key?ids=1%3A2", "token")

    assert result.status == 200
    assert result.retry_after is None
    assert result.error is None


def test_recommendations_explain_starter_high_limit() -> None:
    module = load_module()

    recommendations = module._recommendations(
        [
            module.ProbeResult(
                name="node_json",
                endpoint="/files/file/nodes?ids=1%3A2",
                status=429,
                retry_after="123",
                plan_tier="starter",
                rate_limit_type="high",
                upgrade_link=None,
            )
        ]
    )

    assert any("Starter plan" in item for item in recommendations)
    assert any("Dev/Full" in item for item in recommendations)
