"""Verify Task recovery activates only inside the selected private runner."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.ci_task_inline_recovery_epoch import (
    EXPECTED_ENV,
    FIXTURE_FLAG,
    READY,
    TASK_INLINE_SPEC,
    activate_task_inline_recovery,
)


@pytest.fixture
def profile():
    return {
        "name": "openmates-ci",
        "networks": {"default": {"internal": True}},
        "services": {
            "api": {"environment": dict(EXPECTED_ENV)},
            "runner-gateway": {"environment": {"OPENMATES_CI_REAL_INFERENCE_PROXY": "1"}},
        },
    }


# contract-test: tooling
def test_task_recovery_requires_private_profile_and_exact_spec(tmp_path, profile):
    path = tmp_path / "compose.json"
    path.write_text(json.dumps(profile))
    calls = []

    def compose(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(READY))

    options = {"compose_path": path, "require_runner": lambda: None, "compose": compose}
    with pytest.raises(RuntimeError, match="exact inline Task spec"):
        activate_task_inline_recovery("other.spec.ts", **options)
    profile["services"]["api"]["ports"] = ["8000:8000"]
    path.write_text(json.dumps(profile))
    with pytest.raises(RuntimeError, match="private real-inference profile"):
        activate_task_inline_recovery(TASK_INLINE_SPEC, **options)
    assert calls == []
    del profile["services"]["api"]["ports"]
    path.write_text(json.dumps(profile))
    assert activate_task_inline_recovery(TASK_INLINE_SPEC, **options) == READY
    assert calls[0][:5] == ("exec", "-T", "-e", f"{FIXTURE_FLAG}=1", "api")
