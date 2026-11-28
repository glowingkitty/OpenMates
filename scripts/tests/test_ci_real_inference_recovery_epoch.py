"""Verify real-inference recovery activates only inside the selected private runner."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.ci_environment import CODEX_REAL_INFERENCE_SPECS
from scripts.ci_real_inference_recovery_epoch import (
    EXPECTED_ENV,
    FIXTURE_FLAG,
    READY,
    activate_real_inference_recovery,
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
@pytest.mark.parametrize("spec", [
    "real-inference-task-inline-embeds.spec.ts",
    "real-inference-tui-artifact-steering.spec.ts",
    "real-inference-tui-chat-processing.spec.ts",
])
def test_recovery_requires_private_profile_and_exact_spec(tmp_path, profile, spec):
    path = tmp_path / "compose.json"
    path.write_text(json.dumps(profile))
    calls = []

    def compose(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(READY))

    options = {"compose_path": path, "require_runner": lambda: None, "compose": compose}
    with pytest.raises(RuntimeError, match="approved real-inference spec"):
        activate_real_inference_recovery("other.spec.ts", **options)
    profile["services"]["api"]["ports"] = ["8000:8000"]
    path.write_text(json.dumps(profile))
    with pytest.raises(RuntimeError, match="private real-inference profile"):
        activate_real_inference_recovery(spec, **options)
    assert calls == []
    del profile["services"]["api"]["ports"]
    if spec in CODEX_REAL_INFERENCE_SPECS:
        path.write_text(json.dumps(profile))
        with pytest.raises(RuntimeError, match="private real-inference profile"):
            activate_real_inference_recovery(spec, **options)
        assert calls == []
        profile["services"]["runner-gateway"]["environment"]["OPENMATES_CI_REAL_INFERENCE_PROXY"] = "codex"
    path.write_text(json.dumps(profile))
    assert activate_real_inference_recovery(spec, **options) == READY
    assert calls[0][:5] == ("exec", "-T", "-e", f"{FIXTURE_FLAG}=1", "api")
