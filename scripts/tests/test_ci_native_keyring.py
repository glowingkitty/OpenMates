# contract-test-file: tooling
"""Inert route/package admission tests. All provisioning commands are mocked."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest
from scripts import ci_native_keyring as K
from scripts.ci_coverage import partition

ENV = {
    "CI": "true",
    "GITHUB_ACTIONS": "true",
    "RUNNER_ENVIRONMENT": "github-hosted",
    "CI_TEST_MODE": "e2e",
    "OPENMATES_CI_ISOLATED": "1",
}


def test_keyring_exact_no_ai_coverage():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "scripts/ci_coverage_manifest.json").read_text())
    assert partition([K.SPEC], manifest) == ([K.SPEC], {})
    assert manifest["groups"]["native_os_keyring"]["specs"] == [K.SPEC]
    for name in ("cli-rust-native-keyring-extra.spec.ts", "nested/" + K.SPEC):
        allowed, held = partition([name], manifest)
        assert allowed == [] and name in held
    for group in (
        "ai_committed_fixtures",
        "ai_cached_pipeline",
        "ai_cached_public_provider",
    ):
        assert K.SPEC not in manifest["groups"].get(group, {}).get("specs", [])


def test_no_host_or_prefix_provisioning():
    assert K.admitted([K.SPEC], ENV)
    for specs, env in [
        ([K.SPEC], {}),
        (["nested/" + K.SPEC], ENV),
        ([K.SPEC, "other.spec.ts"], ENV),
        ([K.SPEC], {**ENV, "RUNNER_ENVIRONMENT": "self-hosted"}),
        ([K.SPEC], {**ENV, "CI_TEST_MODE": "component"}),
    ]:
        assert not K.admitted(specs, env)
        with patch.object(
            K, "command", side_effect=AssertionError("must not invoke package tool")
        ):
            with pytest.raises(RuntimeError, match="exact_isolated_target"):
                K.prepare(specs, Path("/does-not-exist"), env)


def test_signed_package_invocations_are_bounded_and_scrubbed(tmp_path):
    (tmp_path / "test-results").mkdir()
    calls = []

    def inert(argv, env, deadline):
        calls.append((argv, env, deadline))
        if argv[0] == "/usr/bin/dpkg-query":
            return "".join(name + "=synthetic\n" for name in K.PACKAGES).encode("ascii")
        if argv[0] == "/usr/bin/apt-cache":
            return b"synthetic-policy\n"
        return b""

    with patch.object(K, "command", side_effect=inert):
        K.prepare([K.SPEC], tmp_path, {**ENV, "OPENMATES_API_KEY": "never-forward"})
    assert len(calls) == 4 and len({deadline for _, _, deadline in calls}) == 1
    for argv, env, _ in calls:
        assert "OPENMATES_API_KEY" not in env and "DISPLAY" not in env
        if "/usr/bin/apt-get" in argv:
            assert "Acquire::AllowInsecureRepositories=false" in argv
            assert "APT::Get::AllowUnauthenticated=false" in argv
            assert "--allow-unauthenticated" not in argv
    install = calls[1][0]
    assert "--no-install-recommends" in install
    assert install[-len(K.PACKAGES) :] == list(K.PACKAGES)
    assert {
        "zutty",
        "fonts-dejavu-core",
        "x11-xserver-utils",
        "xdotool",
        "ffmpeg",
        "xvfb",
        "util-linux",
    }.issubset(K.PACKAGES)
    value = json.loads(
        (tmp_path / "test-results/ci-native-keyring-packages.json").read_text()
    )
    assert value["status"] == "passed" and value["scope"] == K.SPEC


def test_shared_attempt_starts_before_package_commands_and_prevents_spawn_after_deadline():
    with (
        patch.object(K.time, "monotonic", return_value=5),
        patch.object(
            K.subprocess, "Popen", side_effect=AssertionError("must not spawn")
        ),
    ):
        with pytest.raises(RuntimeError, match="package_deadline"):
            K.command(["/usr/bin/sudo"], {}, 5)
