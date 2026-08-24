#!/usr/bin/env python3
"""Linux-safe unit tests for the Apple cross-client E2E control plane.

The tests use synthetic commands and manifests only. They never invoke Apple,
web, CLI, credentials, or a network service.
"""

from __future__ import annotations

# contract-test-file: tooling

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/apple_cross_client_e2e.py"


def load_module():
    spec = importlib.util.spec_from_file_location("apple_cross_client_e2e", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_validation_rejects_wrong_run_id(tmp_path):
    module = load_module()
    path = module.manifest_path(tmp_path, "run", "web-producer")
    path.write_text('{"schema_version": 1, "run_id": "other", "chat_id": "opaque"}', encoding="utf-8")
    with pytest.raises(module.ControlPlaneError, match="run ID"):
        module.validate_manifest(tmp_path, "run", "web-producer")


def test_run_requires_every_ordered_stage():
    module = load_module()
    with pytest.raises(module.ControlPlaneError, match="missing configured"):
        module.run({"web-producer": "true"})


def test_run_executes_stages_in_order_and_validates_each_manifest(monkeypatch):
    module = load_module()
    calls = []

    def fake_run_stage(command, environment):
        stage = command
        calls.append(stage)
        for manifest_name in module.REQUIRED_MANIFESTS[stage]:
            module.manifest_path(Path(environment["APPLE_CROSS_CLIENT_ARTIFACT_DIR"]), environment["APPLE_CROSS_CLIENT_RUN_ID"], manifest_name).write_text(
                '{"schema_version": 1, "run_id": "' + environment["APPLE_CROSS_CLIENT_RUN_ID"] + '", "chat_id": "opaque"}',
                encoding="utf-8",
            )

    monkeypatch.setattr(module, "run_stage", fake_run_stage)
    stages = {stage: stage for stage in module.STAGES}
    run_id = module.run(stages)
    assert len(run_id) == 32
    assert calls == list(module.STAGES)
