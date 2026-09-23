"""Focused policy and lifecycle tests for the privileged command broker."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BROKER_PATH = ROOT / "scripts" / "openmates_command_apparmor.py"


@pytest.fixture()
def broker():
    spec = importlib.util.spec_from_file_location("openmates_command_apparmor_test", BROKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_request(**overrides: object) -> dict:
    request = {
        "protocol_version": 1,
        "action": "prepare",
        "execution_id": "run-1",
        "project_root_digest": "a" * 64,
        "private_policy_digest": "b" * 64,
        "private_globs": ["config/secrets.txt"],
        "exact_private_aliases": [{"path": "aliases/secret.txt", "kind": "file"}],
        "exact_readonly_paths": [{"path": "AGENTS.md", "kind": "file"}],
    }
    request.update(overrides)
    return request


def rendered_profile(broker, request: dict | None = None) -> str:
    policy = broker.normalize_prepare(request or prepare_request())
    digest = broker.definition_digest(policy)
    return broker.render_profile(f"openmates-command.1000.{digest}", policy)


# contract-test: direct surface=cli assertions=code-run.remote.private-path-deny
def test_broker_mandatory_policy_matches_shared_product_credentials(broker) -> None:
    source = (ROOT / "frontend/packages/ui/src/utils/projectSearchProtocol.ts").read_text(encoding="utf-8")
    block = re.search(
        r"PROJECT_CREDENTIAL_GLOBS\s*=\s*\[(.*?)\]\s*as const",
        source,
        flags=re.DOTALL,
    )
    assert block is not None
    shared_patterns = set(re.findall(r'"([^"\\]+)"', block.group(1)))
    shared_patterns.update({".openmates/permissions.yml", "**/.openmates/permissions.yml"})

    mandatory = set(broker.MANDATORY_PRIVATE)
    # The broker's **/ form covers both the Project root and descendants.
    canonical_shared = {
        pattern if pattern.startswith("**/") else f"**/{pattern}"
        for pattern in shared_patterns
    }
    # Terminal Git config is represented by an empty compatibility view; its
    # actual file remains denied even after an external unlink/replacement.
    canonical_shared.add("**/.git/config")
    assert mandatory == canonical_shared


# contract-test: direct surface=cli assertions=code-run.remote.private-path-deny
def test_git_style_patterns_compile_case_insensitively_without_policy_injection(broker) -> None:
    assert broker.path_expression("**/.Env", pattern=True) == "/project/{,**/}.[eE][nN][vV]{,/**}"
    assert broker.path_expression("Config/[a-z]/*.KEY", pattern=True) == (
        "/project/[cC][oO][nN][fF][iI][gG]/?/*.[kK][eE][yY]{,/**}"
    )
    assert broker.path_expression('safe/na"me@{token}', pattern=True) == (
        '/project/[sS][aA][fF][eE]/[nN][aA]\\"[mM][eE]\\@\\{[tT][oO][kK][eE][nN]\\}{,/**}'
    )
    unicode_expression = broker.path_expression("private/Ü-secret", pattern=True)
    assert "Ü" not in unicode_expression
    assert unicode_expression == "/project/[pP][rR][iI][vV][aA][tT][eE]/*-[sS][eE][cC][rR][eE][tT]{,/**}"

    for malicious in ("../secret", "!public", "bad\\path", "bad\nprofile evil {"):
        with pytest.raises(broker.PolicyError):
            broker.path_expression(malicious, pattern=True)


# contract-test: direct surface=cli assertions=code-run.remote.private-path-deny
def test_profile_denies_ancestor_relocation_without_blocking_leading_glob_root(broker) -> None:
    profile = rendered_profile(
        broker,
        prepare_request(private_globs=["config/secrets.txt", "**/*.key"]),
    )

    assert 'audit deny "/project/[cC][oO][nN][fF][iI][gG]/" w,' in profile
    assert 'audit deny "/project/" w,' not in profile
    assert 'audit deny "/project/{,**/}*.[kK][eE][yY]{,/**}" rwklmx,' in profile
    assert "flags=(mediate_deleted)" in profile
    assert "  /** ix," in profile
    assert "  audit deny /** l," in profile


# contract-test: direct surface=cli assertions=code-run.remote.private-path-deny
def test_prepare_reuses_immutable_profile_and_release_only_deletes_lease(
    broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parser_calls: list[list[str]] = []
    loaded = iter((False, True, True, True))
    leases = iter(("1" * 32, "2" * 32))

    monkeypatch.setattr(broker, "profile_is_loaded", lambda _name: next(loaded))
    monkeypatch.setattr(broker.secrets, "token_hex", lambda _size: next(leases))
    monkeypatch.setattr(
        broker,
        "read_private",
        lambda path: json.loads(path.read_text(encoding="utf-8")),
    )

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        parser_calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(broker.subprocess, "run", run)

    first = broker.prepare(prepare_request(), 1000, tmp_path)
    second = broker.prepare(prepare_request(execution_id="run-2"), 1000, tmp_path)

    assert first["profile_name"] == second["profile_name"]
    assert first["definition_digest"] == second["definition_digest"]
    assert first["lease_id"] != second["lease_id"]
    assert len(parser_calls) == 1
    assert parser_calls[0][1:3] == ["--add", "--skip-cache"]
    assert len(list(tmp_path.glob("*.profile"))) == 1
    assert len(list(tmp_path.glob("*.lease"))) == 2

    response = broker.release(
        {
            "protocol_version": 1,
            "action": "release",
            "lease_id": first["lease_id"],
            "definition_digest": first["definition_digest"],
        },
        tmp_path,
    )

    assert response == {
        "released": False,
        "retained": True,
        "definition_digest": first["definition_digest"],
    }
    assert not (tmp_path / f"{first['lease_id']}.lease").exists()
    assert (tmp_path / f"{second['lease_id']}.lease").exists()
    assert len(list(tmp_path.glob("*.profile"))) == 1
    assert len(parser_calls) == 1


# contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
def test_prepare_rejects_a_changed_existing_immutable_profile(
    broker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy = broker.normalize_prepare(prepare_request())
    digest = broker.definition_digest(policy)
    (tmp_path / f"{digest}.profile").write_text("tampered", encoding="utf-8")
    monkeypatch.setattr(broker, "profile_is_loaded", lambda _name: True)

    with pytest.raises(broker.PolicyError, match="immutable AppArmor policy differs"):
        broker.prepare(prepare_request(), 1000, tmp_path)


# contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
def test_prepare_validation_is_strict_and_bounded(broker, monkeypatch: pytest.MonkeyPatch) -> None:
    invalid_requests = [
        prepare_request(private_globs=["value"] * (broker.MAX_GLOBS + 1)),
        prepare_request(
            exact_private_aliases=[{"path": f"path-{index}", "kind": "file"} for index in range(broker.MAX_PATHS + 1)]
        ),
        prepare_request(private_globs=["x" * 513]),
        {**prepare_request(), "unexpected": True},
        prepare_request(project_root_digest="not-a-digest"),
        prepare_request(execution_id="../run"),
    ]
    for request in invalid_requests:
        with pytest.raises(broker.PolicyError):
            broker.normalize_prepare(request)

    policy = broker.normalize_prepare(prepare_request())
    digest = broker.definition_digest(policy)
    monkeypatch.setattr(broker, "MAX_PROFILE_BYTES", 64)
    with pytest.raises(broker.PolicyError, match="too large"):
        broker.render_profile(f"openmates-command.1000.{digest}", policy)


# contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
def test_generated_profile_is_accepted_by_local_apparmor_parser_when_available(
    broker, tmp_path: Path
) -> None:
    parser = shutil.which("apparmor_parser")
    if parser is None:
        pytest.skip("apparmor_parser is not installed")
    profile_path = tmp_path / "profile"
    profile_path.write_text(rendered_profile(broker), encoding="utf-8")

    result = subprocess.run(
        [parser, "-Q", "-T", str(profile_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
