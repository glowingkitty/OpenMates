# contract-test-file: tooling
"""Synthetic private fixture IPC/files only; no Node, application or network."""

import base64
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest


def context(tmp_path, monkeypatch):
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "require_runner", lambda: None)
    root = tmp_path / "ci-private"
    root.mkdir(mode=0o700)
    state = root / ("state-14-" + "a" * 16)
    state.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "COMPOSE_PATH", root / "compose.json")
    session = dict(
        apiUrl=runner.API,
        sessionId="synthetic-session",
        wsToken="synthetic-old-ws",
        cookies={"auth_refresh_token": "synthetic-old-cookie"},
        masterKeyStorage="file",
        masterKeyExportedB64=base64.b64encode(bytes([7]) * 32).decode(),
        hashedEmail=base64.b64encode(
            hashlib.sha256(b"ci-synthetic@example.com").digest()
        ).decode(),
        userEmailSalt="synthetic-email-salt",
        createdAt=12345,
        activeTeamId=None,
    )
    path = state / "session.json"
    path.write_text(json.dumps(session))
    path.chmod(0o600)
    return (
        runner,
        {
            "OPENMATES_STATE_DIR": str(state),
            "OPENMATES_TEST_ACCOUNT_EMAIL": "ci-synthetic@example.com",
        },
        path,
        session,
    )


def test_exact_fixture_explicit_stdin_and_private_rotation_roundtrip(
    tmp_path, monkeypatch
):
    runner, account, path, session = context(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENMATES_CI_NODE", "/tmp/openmates-ci-node-Synthetic/node")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    observed = []
    rotated = {
        "cookies": {"auth_refresh_token": "synthetic-rotated-cookie"},
        "wsToken": "synthetic-new-ws",
    }

    def transport(command, **kwargs):
        explicit = json.loads(kwargs["input"])
        assert explicit == session
        assert "new OpenMatesClient({apiUrl: process.argv[2], session})" in command[3]
        assert 'JSON.parse(readFileSync(0, "utf8"))' in command[3]
        for secret in [
            session["masterKeyExportedB64"],
            session["cookies"]["auth_refresh_token"],
        ]:
            assert secret not in json.dumps(command) and secret not in json.dumps(
                kwargs["env"]
            )
        assert "/v1/auth/accept-gift" in command[3]
        assert (
            "client.whoAmI()" in command[3]
            and "client.getSession().cookies" in command[3]
        )
        assert kwargs["capture_output"] is True and kwargs["text"] is True
        observed.append(True)
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"credits": 1000, "sessionUpdate": rotated})
        )

    monkeypatch.setattr(runner.subprocess, "run", transport)
    assert runner.accept_fixture_credits(account) == 1000
    after = json.loads(path.read_bytes())
    assert after == {**session, **rotated}
    assert (
        after["masterKeyStorage"] == "file"
        and after["masterKeyExportedB64"] == session["masterKeyExportedB64"]
    )
    assert observed == [True]
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize(
    "defect",
    [
        "ambient",
        "other-parent",
        "name",
        "state-link",
        "file-link",
        "hardlink",
        "file-mode",
        "state-mode",
        "missing",
        "keyring",
        "legacy-encrypted",
        "wrong-api",
        "wrong-owner",
        "bad-key",
        "no-cookie",
        "cookie-newline",
        "team",
        "createdAt",
    ],
)
def test_unsupported_or_unowned_fixture_refuses_without_process_or_profile_fallback(
    tmp_path, monkeypatch, defect
):
    runner, account, path, session = context(tmp_path, monkeypatch)
    if defect == "ambient":
        account = {}
    elif defect == "other-parent":
        account["OPENMATES_STATE_DIR"] = str(tmp_path / "real-profile")
    elif defect == "name":
        account["OPENMATES_STATE_DIR"] = str(path.parent.parent / ".openmates")
    elif defect == "state-link":
        link = path.parent.parent / ("state-15-" + "b" * 16)
        link.symlink_to(path.parent, target_is_directory=True)
        account["OPENMATES_STATE_DIR"] = str(link)
    elif defect == "file-link":
        saved = path.with_name("saved")
        path.rename(saved)
        path.symlink_to(saved)
    elif defect == "hardlink":
        os.link(path, path.with_name("alias"))
    elif defect == "file-mode":
        path.chmod(0o644)
    elif defect == "state-mode":
        path.parent.chmod(0o755)
    elif defect == "missing":
        path.unlink()
    else:
        if defect == "keyring":
            session["masterKeyStorage"] = "keychain"
        elif defect == "legacy-encrypted":
            session["masterKeyStorage"] = "encrypted"
        elif defect == "wrong-api":
            session["apiUrl"] = "https://api.openmates.org"
        elif defect == "wrong-owner":
            session["hashedEmail"] = "different-owner"
        elif defect == "bad-key":
            session["masterKeyExportedB64"] = "bad"
        elif defect == "no-cookie":
            session["cookies"] = {}
        elif defect == "cookie-newline":
            session["cookies"]["auth_refresh_token"] = "private\nvalue"
        elif defect == "team":
            session["activeTeamId"] = "other-team"
        elif defect == "createdAt":
            session["createdAt"] = True
        path.write_text(json.dumps(session))
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: pytest.fail("fixture refusal must precede Node/process launch"),
    )
    with pytest.raises(RuntimeError) as error:
        runner.accept_fixture_credits(account)
    assert str(tmp_path) not in str(error.value)
    assert session["masterKeyExportedB64"] not in str(error.value)
    assert "synthetic-old-cookie" not in str(error.value)


@pytest.mark.parametrize(
    "defect",
    [
        "owner-change",
        "concurrent-write",
        "bad-cookie",
        "bad-ws",
        "extra-field",
        "busy-lock",
    ],
)
def test_rotation_never_restores_changed_owner_or_invalid_credentials(
    tmp_path, monkeypatch, defect
):
    runner, account, path, session = context(tmp_path, monkeypatch)
    snapshot = runner.fresh_fixture_session(account)
    update = {
        "cookies": {"auth_refresh_token": "synthetic-rotated-cookie"},
        "wsToken": "synthetic-new-ws",
    }
    if defect == "owner-change":
        session["sessionId"] = "different-owner"
        path.write_text(json.dumps(session))
    elif defect == "concurrent-write":
        session["cookies"]["auth_refresh_token"] = "newer-cookie"
        path.write_text(json.dumps(session))
    elif defect == "bad-cookie":
        update["cookies"] = {"auth_refresh_token": "bad\r\nvalue"}
    elif defect == "bad-ws":
        update["wsToken"] = {"invalid": True}
    elif defect == "extra-field":
        update["masterKeyExportedB64"] = "untrusted-key"
    elif defect == "busy-lock":
        (path.parent / "session.json.write.lock").mkdir(mode=0o700)
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        runner.persist_fresh_fixture_session(snapshot, update)
    assert path.read_bytes() == before


def test_runner_admission_precedes_any_fixture_read(monkeypatch):
    from scripts import ci_run_tests as runner

    def refuse():
        raise RuntimeError("runner-only")

    monkeypatch.setattr(runner, "require_runner", refuse)
    with pytest.raises(RuntimeError, match="runner-only"):
        runner.fresh_fixture_session({})


@pytest.mark.parametrize("slot", [14, 20, 100, 107])
def test_existing_fresh_fixture_producer_slot_shapes_are_accepted(
    tmp_path, monkeypatch, slot
):
    runner, account, path, session = context(tmp_path, monkeypatch)
    target = path.parent.with_name("state-" + str(slot) + "-" + "a" * 16)
    if target != path.parent:
        path.parent.rename(target)
    account["OPENMATES_STATE_DIR"] = str(target)
    assert runner.fresh_fixture_session(account)["session"] == session


def test_api_key_uses_same_explicit_fixture_and_rotated_cookie_handoff(
    tmp_path, monkeypatch
):
    runner, account, path, session = context(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENMATES_CI_NODE", "/tmp/openmates-ci-node-Synthetic/node")
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    account["OPENMATES_TEST_ACCOUNT_OTP_KEY"] = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    update = {
        "cookies": {"auth_refresh_token": "new-api-key-cookie"},
        "wsToken": "new-api-key-ws",
    }

    def transport(command, **kwargs):
        assert json.loads(kwargs["input"]) == session
        assert "new OpenMatesClient({apiUrl: process.argv[2], session})" in command[3]
        assert "client.verifyTotpForCurrentSession" in command[3]
        assert (
            "client.createApiKey" in command[3]
            and "FIXTURE_KEY_LIFETIME_MS" in command[3]
        )
        assert "d.api_key_id === result.key.id" in command[3]
        assert "chats.send" not in command[3]
        assert session["masterKeyExportedB64"] not in json.dumps(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"api_key": "sk-api-synthetic", "sessionUpdate": update}),
        )

    monkeypatch.setattr(runner.subprocess, "run", transport)
    assert runner.provision_api_key(account) == "sk-api-synthetic"
    assert json.loads(path.read_bytes()) == {**session, **update}


def test_api_key_refuses_unowned_profile_before_totp_wait_or_process(monkeypatch):
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(
        runner.time,
        "sleep",
        lambda *args: pytest.fail("no TOTP pacing before fixture ownership"),
    )
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("no process before fixture ownership"),
    )
    with pytest.raises(RuntimeError):
        runner.provision_api_key({})


def test_wrong_business_balance_cannot_promote_or_persist_session(
    tmp_path, monkeypatch
):
    runner, account, path, session = context(tmp_path, monkeypatch)
    before = path.read_bytes()
    monkeypatch.setenv("OPENMATES_CI_NODE", "/tmp/openmates-ci-node-Synthetic/node")
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "credits": 0,
                    "sessionUpdate": {
                        "cookies": {"auth_refresh_token": "bad-result-cookie"},
                        "wsToken": None,
                    },
                }
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="balance mismatch"):
        runner.accept_fixture_credits(account)
    assert path.read_bytes() == before


def test_owned_private_fifo_is_opened_nonblocking_then_refused(tmp_path, monkeypatch):
    runner, account, path, session = context(tmp_path, monkeypatch)
    path.unlink()
    os.mkfifo(path, mode=0o600)
    original_open = runner.os.open
    seen = []

    def nonblocking_open(name, flags, *args, **kwargs):
        if name == "session.json":
            # Assert before the actual syscall so the former blocking variant
            # fails safely rather than hanging a regression run.
            assert flags & os.O_NONBLOCK
            assert flags & os.O_NOFOLLOW
            seen.append(True)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(runner.os, "open", nonblocking_open)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: pytest.fail("FIFO refusal precedes process launch"),
    )
    with pytest.raises(RuntimeError, match="ownership is invalid"):
        runner.accept_fixture_credits(account)
    assert seen == [True]
    assert path.is_fifo() and path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("sdk_mode", ["legacy-self-save", "caller-owned-no-save"])
@pytest.mark.parametrize("business", ["gift", "api-key"])
@pytest.mark.parametrize("email_policy", ["absent", "file"])
def test_old_and_new_sdk_isolated_copy_preserves_original_cas_and_empty_helper_search(
    tmp_path, monkeypatch, sdk_mode, business, email_policy
):
    import shutil

    runner, account, path, session = context(tmp_path, monkeypatch)
    if email_policy == "file":
        session.update(
            emailEncryptionKeyStorage="file",
            emailEncryptionKeyB64=base64.b64encode(bytes([9]) * 32).decode(),
        )
        path.write_text(json.dumps(session))
    before = path.read_bytes()
    (path.parent / "do-not-copy.json").write_text('{"synthetic":"cache"}')
    ambient = tmp_path / "ambient-helpers"
    ambient.mkdir(mode=0o700)
    for name in ("secret-tool", "security", "ioreg"):
        helper = ambient / name
        helper.write_text("#!/bin/sh\nexit 99\n")
        helper.chmod(0o700)
        assert shutil.which(name, path=str(ambient)) == str(helper)
    monkeypatch.setenv("PATH", str(ambient))
    monkeypatch.chdir(ambient)  # Catches accidental empty-string PATH/cwd search.
    parent_path, parent_home = os.environ["PATH"], os.environ.get("HOME")
    monkeypatch.setenv("OPENMATES_CI_NODE", "/tmp/openmates-ci-node-Synthetic/node")
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    account["OPENMATES_TEST_ACCOUNT_OTP_KEY"] = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    update = {
        "cookies": {"auth_refresh_token": "synthetic-child-rotated"},
        "wsToken": "synthetic-child-ws",
    }
    copies = []

    def transport(command, **kwargs):
        state = Path(kwargs["env"]["OPENMATES_STATE_DIR"])
        search = Path(kwargs["env"]["PATH"])
        assert (
            command[0] == "/tmp/openmates-ci-node-Synthetic/node"
            and Path(command[0]).is_absolute()
        )
        assert (
            state != path.parent and state.parent.parent == runner.COMPOSE_PATH.parent
        )
        assert state.parent == search.parent and state != search
        assert sorted(x.name for x in state.iterdir()) == ["session.json"]
        assert (
            not list(search.iterdir())
            and search.is_absolute()
            and os.pathsep not in str(search)
        )
        for directory in (state.parent, state, search):
            assert (
                directory.stat().st_mode & 0o777 == 0o700
                and directory.stat().st_uid == os.getuid()
            )
        copied = state / "session.json"
        assert copied.read_bytes() == before and copied.stat().st_mode & 0o777 == 0o600
        assert (copied.stat().st_dev, copied.stat().st_ino) != (
            path.stat().st_dev,
            path.stat().st_ino,
        )
        assert copied.stat().st_nlink == 1 and json.loads(kwargs["input"]) == session
        assert kwargs["env"].get("HOME") == parent_home
        for name in ("secret-tool", "security", "ioreg"):
            assert shutil.which(name, path=kwargs["env"]["PATH"]) is None
        if sdk_mode == "legacy-self-save":
            # Model the reviewed old saveSession writing its selected file backend.
            copied.write_text(json.dumps({**session, **update}))
            (state / "legacy-cache.json").write_text("{}")
        else:
            assert copied.read_bytes() == before
        assert path.read_bytes() == before  # Strict original preimage during child.
        copies.append(state.parent)
        payload = (
            {"credits": 1000} if business == "gift" else {"api_key": "sk-api-synthetic"}
        )
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({**payload, "sessionUpdate": update})
        )

    monkeypatch.setattr(runner.subprocess, "run", transport)
    result = (
        runner.accept_fixture_credits(account)
        if business == "gift"
        else runner.provision_api_key(account)
    )
    assert result == (1000 if business == "gift" else "sk-api-synthetic")
    assert json.loads(path.read_bytes()) == {**session, **update}
    assert all(not copy.exists() for copy in copies)
    assert os.environ["PATH"] == parent_path and os.environ.get("HOME") == parent_home


@pytest.mark.parametrize("sdk_mode", ["legacy-self-save", "caller-owned-no-save"])
@pytest.mark.parametrize(
    "fault",
    ["nonzero", "timeout", "wrong-balance", "invalid-json", "concurrent-original"],
)
def test_isolated_copy_cleanup_on_all_child_outcomes_and_strict_parent_cas(
    tmp_path, monkeypatch, sdk_mode, fault
):
    import subprocess

    runner, account, path, session = context(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENMATES_CI_NODE", "/tmp/openmates-ci-node-Synthetic/node")
    before = path.read_bytes()
    update = {
        "cookies": {"auth_refresh_token": "synthetic-child-rotated"},
        "wsToken": None,
    }
    copies = []
    newer = {**session, "cookies": {"auth_refresh_token": "synthetic-concurrent-newer"}}

    def transport(command, **kwargs):
        state = Path(kwargs["env"]["OPENMATES_STATE_DIR"])
        copies.append(state.parent)
        if sdk_mode == "legacy-self-save":
            (state / "session.json").write_text(json.dumps({**session, **update}))
        assert path.read_bytes() == before
        if fault == "concurrent-original":
            path.write_text(json.dumps(newer))
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if fault == "nonzero":
            return SimpleNamespace(returncode=1)
        if fault == "invalid-json":
            return SimpleNamespace(returncode=0, stdout="not-json")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "credits": 0 if fault == "wrong-balance" else 1000,
                    "sessionUpdate": update,
                }
            ),
        )

    monkeypatch.setattr(runner.subprocess, "run", transport)
    expected = (
        subprocess.TimeoutExpired
        if fault == "timeout"
        else ValueError
        if fault == "invalid-json"
        else RuntimeError
    )
    with pytest.raises(expected):
        runner.accept_fixture_credits(account)
    assert all(not copy.exists() for copy in copies)
    assert path.read_bytes() == (
        json.dumps(newer).encode() if fault == "concurrent-original" else before
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"masterKeyEncrypted": "synthetic-external-reference"},
        {"emailEncryptionKeyStorage": "keychain"},
        {
            "emailEncryptionKeyStorage": "encrypted",
            "emailEncryptionKeyEncrypted": "synthetic",
        },
        {
            "emailEncryptionKeyStorage": "plaintext",
            "emailEncryptionKeyB64": base64.b64encode(bytes(32)).decode(),
        },
        {"emailEncryptionKeyB64": base64.b64encode(bytes(32)).decode()},
        {"emailEncryptionKeyStorage": "file"},
        {"emailEncryptionKeyStorage": "file", "emailEncryptionKeyB64": "malformed"},
        {
            "emailEncryptionKeyStorage": "file",
            "emailEncryptionKeyB64": base64.b64encode(bytes(32)).decode(),
            "emailEncryptionKeyEncrypted": "inconsistent",
        },
    ],
)
def test_external_or_inconsistent_key_references_refuse_before_copy_or_child(
    tmp_path, monkeypatch, fields
):
    runner, account, path, session = context(tmp_path, monkeypatch)
    session.update(fields)
    path.write_text(json.dumps(session))
    before = path.read_bytes()
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: pytest.fail("unsupported storage cannot launch child"),
    )
    with pytest.raises(RuntimeError):
        runner.accept_fixture_credits(account)
    assert path.read_bytes() == before
    assert sorted(x.name for x in runner.COMPOSE_PATH.parent.iterdir()) == [
        path.parent.name
    ]


def test_path_separator_in_private_root_refuses_single_path_violation_and_cleans_copy(
    tmp_path, monkeypatch
):
    runner, account, path, session = context(tmp_path, monkeypatch)
    original = path.parent.parent
    colon = original.with_name("ci:private")
    original.rename(colon)
    state = colon / path.parent.name
    account["OPENMATES_STATE_DIR"] = str(state)
    monkeypatch.setattr(runner, "COMPOSE_PATH", colon / "compose.json")
    monkeypatch.setenv("OPENMATES_CI_NODE", "/tmp/openmates-ci-node-Synthetic/node")
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: pytest.fail("PATH components must not split"),
    )
    before = (state / "session.json").read_bytes()
    with pytest.raises(RuntimeError, match="one empty executable search"):
        runner.accept_fixture_credits(account)
    assert (state / "session.json").read_bytes() == before
    assert sorted(x.name for x in colon.iterdir()) == [state.name]
