# contract-test-file: tooling
"""Canonical-safe private profile routing; no migration files or Docker needed."""

import json
import sys
from pathlib import Path

import pytest

from scripts import ci_environment as runtime


ROOT = Path(__file__).resolve().parents[2]
NATIVE_SPEC = "cli-rust-tui-proof.spec.ts"
SOURCE_HASH = "a" * 40


def prepare_profile(tmp_path, monkeypatch, selected):
    """Run the actual trusted prepare selector with only git/process I/O mocked."""
    candidate = tmp_path / "candidate"
    (candidate / "scripts").mkdir(parents=True, mode=0o700)
    (candidate / "scripts/ci_coverage_manifest.json").write_bytes(
        (ROOT / "scripts/ci_coverage_manifest.json").read_bytes()
    )
    config = candidate / "backend/config/backend_config.dev.yml"
    config.parent.mkdir(parents=True)
    config.write_text("{}\n")
    compose = candidate / "test-results/ci-private/compose.json"
    monkeypatch.setattr(runtime, "SOURCE", str(candidate))
    monkeypatch.setattr(runtime, "COMPOSE_PATH", compose)
    monkeypatch.setattr(sys, "argv", ["ci_environment.py", "prepare"])
    for key, value in {
        "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_RUN_ID": "123456", "CI_HARNESS_COMMIT": "b" * 40,
        "CI_TEST_MODE": "e2e", "CI_SPECS_JSON": json.dumps(selected),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    def git_revision(command, **kwargs):
        assert command == ["git", "rev-parse", "HEAD"]
        assert kwargs == {"cwd": str(candidate), "text": True}
        return SOURCE_HASH + "\n"

    monkeypatch.setattr(runtime.subprocess, "check_output", git_revision)
    runtime.main()
    return candidate, compose, json.loads(compose.read_text())


@pytest.fixture
def generated_profile(tmp_path, monkeypatch):
    return prepare_profile(tmp_path, monkeypatch, [NATIVE_SPEC])


def test_native_exact_selector_uses_private_backend_without_unrelated_fixtures(generated_profile):
    candidate, compose, profile = generated_profile
    assert runtime.PRIVATE_BACKEND_SPECS == {NATIVE_SPEC}
    assert profile["networks"] == {"default": {"internal": True}, "ingress": {}}
    services = profile["services"]
    assert not {"ai-worker", "mailpit", "object-storage", "uploads"}.intersection(services)
    assert "ports" not in services["api"] and "ports" not in services["cms"]
    gateway = services["runner-gateway"]
    assert gateway["networks"] == ["default", "ingress"]
    assert gateway["ports"] == ["127.0.0.1:8000:8000", "127.0.0.1:8055:8055"]
    assert gateway["command"] == ["python", "/ci_tcp_gateway.py"]
    assert gateway["environment"] == {"OPENMATES_CI_GATEWAY": "github-isolated"}
    assert any(str(ROOT / "scripts/ci_tcp_gateway.py") in str(mount) for mount in gateway["volumes"])
    for service in services.values():
        assert service["labels"]["org.openmates.source"] == SOURCE_HASH
        env = service.get("environment", {})
        for flag in ("OPENMATES_CI_AI_FIXTURES", "OPENMATES_STORAGE_CAPACITY_FIXTURES",
                     "OPENMATES_CI_MAIL_CAPTURE", "OPENMATES_CI_PUBLIC_PROVIDER_PROXY", "HTTPS_PROXY"):
            assert flag not in env
        for provider in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "BREVO_API_KEY"):
            assert provider not in env
    assert compose.stat().st_mode & 0o777 == 0o600
    evidence = json.loads((candidate / "test-results/ci-environment.json").read_text())
    assert evidence["source_commit"] == SOURCE_HASH
    assert evidence["harness_commit"] == "b" * 40


@pytest.mark.parametrize("selected", [[], ["cli-rust-tui-proof-extra.spec.ts"], ["nested/cli-rust-tui-proof.spec.ts"]])
def test_unknown_or_similar_spec_does_not_select_private_backend(tmp_path, monkeypatch, selected):
    _, _, profile = prepare_profile(tmp_path, monkeypatch, selected)
    assert profile.get("networks", {}).get("default", {}).get("internal") is not True
    assert "runner-gateway" not in profile["services"]


def test_private_backend_option_does_not_change_unselected_or_weather_profiles():
    ordinary = runtime.compose_profile(SOURCE_HASH)
    assert ordinary.get("networks", {}).get("default", {}).get("internal") is not True
    assert "runner-gateway" not in ordinary["services"]
    assert ordinary["services"]["api"]["ports"] == ["8000:8000"]
    assert ordinary["services"]["cms"]["ports"] == ["8055:8055"]
    with pytest.raises(ValueError, match="separate batch"):
        runtime.compose_profile(SOURCE_HASH, private_backend=True, workflows=True)


def test_native_profile_activation_requires_the_trusted_harness_script():
    workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    assert "ref: ${{ inputs.harness_commit || github.sha }}\n          path: tooling" in workflow
    assert "run: |\n          python3 ../tooling/scripts/ci_environment.py prepare" in workflow
    assert "python3 scripts/ci_environment.py prepare" not in workflow
