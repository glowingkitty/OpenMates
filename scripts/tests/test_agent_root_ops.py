# contract-test-file: tooling
"""Unit tests for scripts/agent_root_ops.py (no root needed; fake runner, temp paths)."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "agent_root_ops", Path(__file__).resolve().parents[1] / "agent_root_ops.py"
)
ops = importlib.util.module_from_spec(SPEC)
sys.modules["agent_root_ops"] = ops
SPEC.loader.exec_module(ops)

UID = 4242
CADDYFILE = b"example.org {\n  respond ok\n}\n"


class FakeRunner:
    """Records calls; returns scripted results keyed by the command's action."""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    def __call__(self, args, env):
        self.calls.append((list(args), env))
        for key, value in self.results.items():
            if key in args:
                if isinstance(value, list):
                    return value.pop(0)
                return value
        return 0, ""


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    dev = home / "alice" / "projects" / "OpenMates" / "deployment" / "dev_server"
    dev.mkdir(parents=True)
    (dev / "Caddyfile").write_bytes(CADDYFILE)
    live = tmp_path / "etc" / "Caddyfile"
    live.parent.mkdir()
    live.write_bytes(b"old config\n")
    live.chmod(0o640)
    runner = FakeRunner()
    ctx = ops.Context(
        live_caddyfile=live, backup_dir=tmp_path / "backups", apparmor_dir=tmp_path / "aa",
        home_root=home, runner=runner, sudo_user="alice", sudo_uid=UID,
        require_root_owned=False,
    )
    return ctx, runner, dev / "Caddyfile", live


def call(ctx, *argv):
    logs = []
    code = ops.run(list(argv), ctx, logs.append)
    return code, logs


def test_unknown_verb_exit_2(env):
    ctx, runner, _, _ = env
    assert call(ctx, "rm", "-rf", "/")[0] == 2
    assert call(ctx)[0] == 2
    assert runner.calls == []


@pytest.mark.parametrize("unit", ["sshd.service", "user@0.service", "user@1.service", "caddy", "caddy.service;id"])
def test_unit_allowlist_refuses(env, unit):
    ctx, runner, _, _ = env
    assert call(ctx, "systemctl", "start", unit)[0] == 2
    assert runner.calls == []


def test_unit_allowlist_accepts_and_logs(env):
    ctx, runner, _, _ = env
    code, logs = call(ctx, "systemctl", "start", f"user@{UID}.service")
    assert code == 0
    assert runner.calls[0][0] == [ctx.systemctl, "start", f"user@{UID}.service"]
    assert call(ctx, "systemctl", "restart", f"user@{UID}.service")[0] == 2
    assert call(ctx, "systemctl", "restart", "caddy.service")[0] == 0
    assert "user=alice" in logs[0] and "result=ok" in logs[0]
    assert call(ctx, "systemctl", "reload", "caddy.service")[0] == 0
    assert call(ctx, "systemctl", "reload", f"user@{UID}.service")[0] == 2
    assert call(ctx, "systemctl", "stop", "caddy.service")[0] == 2


@pytest.mark.parametrize("name", ["../etc/passwd", "other-profile", "openmates/x", "OpenmatesX", "openmates " + "a" * 5, "openmates" + "a" * 61])
def test_profile_name_pattern_refuses(env, name):
    ctx, runner, _, _ = env
    assert call(ctx, "apparmor", "reload", name)[0] == 2
    assert runner.calls == []


def test_profile_name_matches_managed_profile():
    ops.validate_profile_name("openmates-command-bwrap")


def test_apparmor_reload_existing_profile(env):
    ctx, runner, _, _ = env
    ctx.apparmor_dir.mkdir()
    (ctx.apparmor_dir / "openmates-command-bwrap").write_text("profile")
    (ctx.apparmor_dir / "openmates-command-bwrap").chmod(0o644)
    assert call(ctx, "apparmor", "reload", "openmates-command-bwrap")[0] == 0
    assert runner.calls[0][0][1] == "-r"
    assert call(ctx, "apparmor", "reload", "openmates-missing")[0] == 2


def test_apparmor_refuses_non_root_owned(env):
    ctx, runner, _, _ = env
    ctx.apparmor_dir.mkdir()
    (ctx.apparmor_dir / "openmates-x").write_text("profile")
    (ctx.apparmor_dir / "openmates-x").chmod(0o644)
    strict = ops.Context(**{**ctx.__dict__, "require_root_owned": True})
    if os.geteuid() != 0:
        assert call(strict, "apparmor", "reload", "openmates-x")[0] == 2


def test_apply_hash_mismatch_refused(env):
    ctx, runner, _, live = env
    assert call(ctx, "caddy", "apply", "0" * 64)[0] == 2
    assert call(ctx, "caddy", "apply", "nothex")[0] == 2
    assert live.read_bytes() == b"old config\n"
    assert runner.calls == []


def test_apply_symlinked_caddyfile_refused(env, tmp_path):
    ctx, runner, dev_file, live = env
    target = tmp_path / "evil"
    target.write_bytes(CADDYFILE)
    dev_file.unlink()
    dev_file.symlink_to(target)
    assert call(ctx, "caddy", "apply", hashlib.sha256(CADDYFILE).hexdigest())[0] == 2
    assert live.read_bytes() == b"old config\n"


def test_apply_symlinked_parent_refused(env, tmp_path):
    ctx, _, dev_file, live = env
    real = tmp_path / "real_dev"
    dev_file.parent.rename(real)
    dev_file.parent.symlink_to(real)
    assert call(ctx, "caddy", "apply", hashlib.sha256(CADDYFILE).hexdigest())[0] == 2


def test_apply_size_cap(env):
    ctx, _, dev_file, live = env
    big = b"a" * (ops.MAX_CADDYFILE_BYTES + 1)
    dev_file.write_bytes(big)
    assert call(ctx, "caddy", "apply", hashlib.sha256(big).hexdigest())[0] == 2


def test_apply_success_backs_up_and_replaces(env):
    ctx, runner, _, live = env
    digest = hashlib.sha256(CADDYFILE).hexdigest()
    assert call(ctx, "caddy", "apply", digest)[0] == 0
    assert live.read_bytes() == CADDYFILE
    assert stat.S_IMODE(live.stat().st_mode) == 0o640
    backups = list(ctx.backup_dir.glob("Caddyfile.*"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"old config\n"
    validate = runner.calls[0][0]
    assert validate[1:2] == ["validate"] and "--adapter" in validate
    assert runner.calls[-1][0][1:] == ["reload", "caddy.service"]


def test_apply_validate_failure_leaves_live_untouched(env):
    ctx, runner, _, live = env
    runner.results["validate"] = (1, "bad config")
    assert call(ctx, "caddy", "apply", hashlib.sha256(CADDYFILE).hexdigest())[0] == 2
    assert live.read_bytes() == b"old config\n"
    assert not ctx.backup_dir.exists()
    assert all("reload" not in c[0] for c in runner.calls)


def test_apply_reload_failure_restores_backup(env):
    ctx, runner, _, live = env
    runner.results["reload"] = [(1, "reload failed"), (0, "")]
    assert call(ctx, "caddy", "apply", hashlib.sha256(CADDYFILE).hexdigest())[0] == 1
    assert live.read_bytes() == b"old config\n"
    assert sum(1 for c in runner.calls if "reload" in c[0]) == 2


def test_backup_pruning_keeps_newest_20(env):
    ctx, _, _, _ = env
    ctx.backup_dir.mkdir()
    for index in range(25):
        (ctx.backup_dir / f"Caddyfile.2020010{index:02d}").write_text("x")
    ops._prune_backups(ctx.backup_dir)
    names = sorted(p.name for p in ctx.backup_dir.iterdir())
    assert len(names) == 20 and names[0] == "Caddyfile.202001005"


def test_caddy_reload_requires_valid_live_config(env):
    ctx, runner, _, _ = env
    runner.results["validate"] = (1, "bad")
    assert call(ctx, "caddy", "reload")[0] == 2
    assert all("reload" not in c[0] for c in runner.calls)


def test_dns_token_dummy_only_when_needed():
    assert ops._validation_env(b"tls {\n dns gandi {env.X}\n}") == {"GANDI_BEARER_TOKEN": ops.DUMMY_DNS_TOKEN}
    assert ops._validation_env(CADDYFILE) == {}


def _fake_stat(uid=0, mode=0o100755):
    return lambda path: os.stat_result((mode, 0, 0, 1, uid, 0, 0, 0, 0, 0))


def test_self_check_accepts_root_owned():
    ops.check_self_integrity("/usr/local/sbin/x", _fake_stat(), homes={"/home", "/root"})


def test_self_check_refuses_non_root_owner():
    with pytest.raises(ops.OpsError):
        ops.check_self_integrity("/usr/local/sbin/x", _fake_stat(uid=1000), homes=set())


def test_self_check_refuses_group_world_writable():
    for mode in (0o100775, 0o100757):
        with pytest.raises(ops.OpsError):
            ops.check_self_integrity("/usr/local/sbin/x", _fake_stat(mode=mode), homes=set())


def test_self_check_refuses_home_location():
    with pytest.raises(ops.OpsError):
        ops.check_self_integrity("/home/alice/repo/x", _fake_stat(), homes={"/home"})
    with pytest.raises(ops.OpsError):
        ops.check_self_integrity("/srv/u/x", _fake_stat(), homes={"/srv/u"})


def test_main_refuses_non_root_and_help_works(capsys):
    if os.geteuid() != 0:
        assert ops.main(["systemctl", "start", "caddy.service"]) == 2
    assert ops.main(["--help"]) == 0
    assert "Allowed verbs" in capsys.readouterr().out
