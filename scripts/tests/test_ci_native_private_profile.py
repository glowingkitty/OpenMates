# contract-test-file: tooling
"""Canonical-safe private profile routing; no migration files or Docker needed."""

import json
import sys
from pathlib import Path

import pytest

from scripts import ci_environment as runtime


ROOT = Path(__file__).resolve().parents[2]
NATIVE_SPEC = "cli-rust-tui-proof.spec.ts"
ESSENTIAL_SPEC = "cli-rust-core-essential.spec.ts"
BROWSER_SPEC = "rust-core-browser-session.spec.ts"
PRIVATE_SPECS = (NATIVE_SPEC, ESSENTIAL_SPEC, BROWSER_SPEC)
SOURCE_HASH = "a" * 40


def prepare_profile(
    tmp_path, monkeypatch, selected, *, candidate_ai_specs=(),
    harness_ai_specs=None, candidate_omit_ai_specs=(),
):
    """Run the actual trusted prepare selector with only git/process I/O mocked."""
    candidate = tmp_path / "candidate"
    (candidate / "scripts").mkdir(parents=True, mode=0o700)
    (candidate / "scripts/ci_coverage_manifest.json").write_bytes(
        (ROOT / "scripts/ci_coverage_manifest.json").read_bytes()
    )
    if candidate_ai_specs or candidate_omit_ai_specs:
        coverage_path = candidate / "scripts/ci_coverage_manifest.json"
        coverage = json.loads(coverage_path.read_text())
        for group in ("ai_committed_fixtures", "ai_cached_pipeline", "ai_cached_public_provider"):
            row = coverage["groups"].get(group, {})
            row["specs"] = [spec for spec in row.get("specs", []) if spec not in candidate_omit_ai_specs]
        specs = coverage["groups"]["ai_committed_fixtures"]["specs"]
        specs.extend(spec for spec in candidate_ai_specs if spec not in specs)
        coverage_path.write_text(json.dumps(coverage))
    if harness_ai_specs is not None:
        # Explicit private I/O fixture keeps this test stable after the real
        # trusted manifest also registers the essential selector. Production
        # prepare, manifest union and compose_profile functions remain real.
        trusted_script = Path(runtime.__file__)
        harness_scripts = tmp_path / "harness/scripts"
        harness_scripts.mkdir(parents=True, mode=0o700)
        script = harness_scripts / "ci_environment.py"
        script.write_bytes(trusted_script.read_bytes())
        gateway = trusted_script.with_name("ci_tcp_gateway.py")
        (harness_scripts / gateway.name).write_bytes(gateway.read_bytes())
        coverage = json.loads((ROOT / "scripts/ci_coverage_manifest.json").read_text())
        for group in ("ai_committed_fixtures", "ai_cached_pipeline", "ai_cached_public_provider"):
            row = coverage["groups"].get(group, {})
            row["specs"] = [spec for spec in row.get("specs", []) if spec != ESSENTIAL_SPEC]
        coverage["groups"]["ai_committed_fixtures"]["specs"].extend(harness_ai_specs)
        (harness_scripts / "ci_coverage_manifest.json").write_text(json.dumps(coverage))
        monkeypatch.setattr(runtime, "__file__", str(script))
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


@pytest.fixture(params=[NATIVE_SPEC, BROWSER_SPEC])
def generated_profile(tmp_path, monkeypatch, request):
    return prepare_profile(tmp_path, monkeypatch, [request.param])


def test_native_exact_selector_uses_private_backend_without_unrelated_fixtures(generated_profile):
    candidate, compose, profile = generated_profile
    assert runtime.PRIVATE_BACKEND_SPECS == set(PRIVATE_SPECS)
    assert profile["networks"] == {"default": {"internal": True}, "ingress": {}}
    services = profile["services"]
    assert not {"ai-worker", "mailpit", "object-storage", "uploads"}.intersection(services)
    assert "ports" not in services["api"] and "ports" not in services["cms"]
    gateway = services["runner-gateway"]
    assert gateway["networks"] == ["default", "ingress"]
    assert gateway["ports"] == ["127.0.0.1:8000:8000", "127.0.0.1:8055:8055"]
    assert gateway["command"] == ["python", "/ci_tcp_gateway.py"]
    assert gateway["environment"] == {"OPENMATES_CI_GATEWAY": "github-isolated"}
    trusted_gateway = Path(runtime.__file__).with_name("ci_tcp_gateway.py").resolve()
    assert gateway["volumes"] == [f"{trusted_gateway}:/ci_tcp_gateway.py:ro"]
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


@pytest.mark.parametrize("selected", [
    [], ["cli-rust-tui-proof-extra.spec.ts"], ["nested/cli-rust-tui-proof.spec.ts"],
    ["cli-rust-core-essential-extra.spec.ts"], ["nested/cli-rust-core-essential.spec.ts"],
    ["rust-core-browser-session-extra.spec.ts"], ["nested/rust-core-browser-session.spec.ts"],
])
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


@pytest.mark.parametrize("declaration_owner", ["candidate", "harness"])
def test_essential_fixture_union_adds_only_private_replay_worker(tmp_path, monkeypatch, declaration_owner):
    # Prove both candidate-only admission and a later deployed trusted harness
    # retaining replay even when the candidate omits that requirement.
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-must-not-inherit")
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic-must-not-inherit.invalid:1")
    candidate, compose, profile = prepare_profile(
        tmp_path, monkeypatch, [ESSENTIAL_SPEC],
        candidate_ai_specs=[ESSENTIAL_SPEC] if declaration_owner == "candidate" else [],
        harness_ai_specs=[ESSENTIAL_SPEC] if declaration_owner == "harness" else [],
        candidate_omit_ai_specs=[ESSENTIAL_SPEC] if declaration_owner == "harness" else [],
    )
    harness = json.loads(Path(runtime.__file__).with_name("ci_coverage_manifest.json").read_text())
    candidate_manifest = json.loads((candidate / "scripts/ci_coverage_manifest.json").read_text())
    assert (ESSENTIAL_SPEC in harness["groups"]["ai_committed_fixtures"]["specs"]) == (declaration_owner == "harness")
    assert (ESSENTIAL_SPEC in candidate_manifest["groups"]["ai_committed_fixtures"]["specs"]) == (declaration_owner == "candidate")
    harness_required = {
        spec
        for group in ("ai_committed_fixtures", "ai_cached_pipeline", "ai_cached_public_provider")
        for spec in harness["groups"].get(group, {}).get("specs", [])
    }
    assert runtime.ai_fixture_specs(harness, candidate) == harness_required | {ESSENTIAL_SPEC}
    assert ESSENTIAL_SPEC in runtime.PRIVATE_BACKEND_SPECS
    assert profile["networks"] == {"default": {"internal": True}, "ingress": {}}
    services = profile["services"]
    assert set(services) == {
        "api", "core-worker", "cms-database", "cache", "cms", "cms-setup",
        "vault", "vault-init", "fixture-init", "runner-gateway", "ai-worker",
    }
    ai_worker = services["ai-worker"]
    assert ai_worker["image"] == "openmates-ci-api:local"
    assert ai_worker["command"][:6] == [
        "python", "-m", "celery", "-A", "backend.core.api.app.tasks.celery_config", "worker"
    ]
    assert ai_worker["environment"]["CELERY_QUEUES"] == "app_ai,app_ai_routing"
    assert [part for part in ai_worker["command"] if part.startswith("--queues=")] == [
        "--queues=app_ai,app_ai_routing"
    ]
    for name in ("api", "ai-worker"):
        assert services[name]["environment"]["OPENMATES_CI_AI_FIXTURES"] == "1"
        assert services[name]["environment"]["MOCK_EXTERNAL_APIS"] == "true"
        assert services[name]["environment"]["OPENMATES_CI_ISOLATED"] == "1"
    gateway = services["runner-gateway"]
    assert gateway["image"] == "openmates-ci-api:local"
    trusted_gateway = Path(runtime.__file__).with_name("ci_tcp_gateway.py").resolve()
    assert gateway["volumes"] == [f"{trusted_gateway}:/ci_tcp_gateway.py:ro"]
    assert gateway["networks"] == ["default", "ingress"]
    assert gateway["ports"] == ["127.0.0.1:8000:8000", "127.0.0.1:8055:8055"]
    for name, service in services.items():
        assert service["labels"]["org.openmates.source"] == SOURCE_HASH
        if name != "runner-gateway":
            assert "ports" not in service
            assert service.get("networks", ["default"]) == ["default"]
        assert "network_mode" not in service
        env = service.get("environment", {})
        for flag in (
            "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "OPENMATES_CI_PUBLIC_PROVIDER_PROXY",
            "OPENMATES_CI_MAIL_CAPTURE", "OPENMATES_STORAGE_CAPACITY_FIXTURES", "CI_UPLOADS",
        ):
            assert flag not in env
        for provider in (
            "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
            "BREVO_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY",
        ):
            assert provider not in env
    assert compose.stat().st_mode & 0o777 == 0o600
    evidence = json.loads((candidate / "test-results/ci-environment.json").read_text())
    assert evidence["source_commit"] == SOURCE_HASH
    assert evidence["harness_commit"] == "b" * 40
