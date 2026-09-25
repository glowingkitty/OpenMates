"""Contract tests for the root-owned remote-command AppArmor installer."""

# contract-test-file: infrastructure

from __future__ import annotations

import os
from pathlib import Path
import pwd
import stat
import subprocess

import pytest

from scripts.setup_remote_command_apparmor import (
    BROKER_PREFIX,
    MANAGED_MARKER,
    MASK_SOURCE_MARKER,
    InstallPaths,
    install,
    render_bootstrap_profile,
    render_mask_manifest,
    render_sudoers,
)


COMPILED_MASK = b"fixture-compiled-git-config-mask\n"


def fixture_paths(tmp_path: Path) -> tuple[InstallPaths, str]:
    user = pwd.getpwuid(os.getuid()).pw_name
    libexec = tmp_path / "usr" / "libexec"
    bin_dir = tmp_path / "usr" / "bin"
    sbin = tmp_path / "usr" / "sbin"
    sudoers = tmp_path / "etc" / "sudoers.d"
    profiles = tmp_path / "etc" / "apparmor.d"
    source = tmp_path / "source"
    for directory in (libexec, bin_dir, sbin, sudoers, profiles, source):
        directory.mkdir(parents=True, exist_ok=True)
    tmp_path.chmod(0o755)
    for directory in [tmp_path, *(path for path in tmp_path.rglob("*") if path.is_dir())]:
        directory.chmod(0o755)

    broker_source = source / "openmates_command_apparmor.py"
    broker_source.write_bytes(BROKER_PREFIX + b"print('broker')\n")
    broker_source.chmod(0o644)
    mask_source = source / "openmates_git_config_mask.c"
    mask_source.write_bytes(MASK_SOURCE_MARKER + b"\nint fixture(void) { return 0; }\n")
    mask_source.chmod(0o644)
    for executable, content in (
        (bin_dir / "bwrap", b"fixture-bwrap\n"),
        (bin_dir / "cc", b"fixture-compiler\n"),
        (sbin / "apparmor_parser", b"fixture-parser\n"),
        (sbin / "visudo", b"fixture-visudo\n"),
    ):
        executable.write_bytes(content)
        executable.chmod(0o755)

    return InstallPaths(
        broker_source=broker_source,
        mask_source=mask_source,
        bwrap_source=bin_dir / "bwrap",
        compiler=bin_dir / "cc",
        broker_target=libexec / "openmates-command-apparmor",
        bwrap_target=libexec / "openmates-bwrap",
        mask_target=libexec / "openmates-git-config-mask.so",
        mask_manifest_target=libexec / "openmates-git-config-mask.so.sha256",
        sudoers_target=sudoers / "openmates-command-apparmor",
        profile_target=profiles / "openmates-command-bwrap",
        parser=sbin / "apparmor_parser",
        visudo=sbin / "visudo",
        trust_boundary=tmp_path,
        trusted_uid=os.getuid(),
        trusted_gid=os.getgid(),
    ), user


def passing_runner(calls: list[list[str]]):
    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")
    return run


def passing_compiler(calls: list[tuple[list[str], Path, dict[str, str]]]):
    def run(
        command: list[str],
        cwd: Path,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd, environment))
        assert stat.S_IMODE(cwd.stat().st_mode) == 0o700
        output = Path(command[command.index("-o") + 1])
        output.write_bytes(COMPILED_MASK)
        output.chmod(0o700)
        return subprocess.CompletedProcess(command, 0, "", "")
    return run


def test_installs_exact_root_boundary_and_validates_before_loading(tmp_path: Path) -> None:
    paths, user = fixture_paths(tmp_path)
    calls: list[list[str]] = []
    compiler_calls: list[tuple[list[str], Path, dict[str, str]]] = []

    install(
        user,
        paths=paths,
        runner=passing_runner(calls),
        compiler_runner=passing_compiler(compiler_calls),
    )

    assert paths.broker_target.read_bytes() == paths.broker_source.read_bytes()
    assert paths.bwrap_target.read_bytes() == paths.bwrap_source.read_bytes()
    assert paths.mask_target.read_bytes() == COMPILED_MASK
    assert paths.mask_manifest_target.read_bytes() == render_mask_manifest(COMPILED_MASK)
    assert stat.S_IMODE(paths.broker_target.stat().st_mode) == 0o755
    assert stat.S_IMODE(paths.bwrap_target.stat().st_mode) == 0o750
    assert stat.S_IMODE(paths.mask_target.stat().st_mode) == 0o755
    assert stat.S_IMODE(paths.mask_manifest_target.stat().st_mode) == 0o644
    assert paths.bwrap_target.stat().st_gid == pwd.getpwnam(user).pw_gid
    assert stat.S_IMODE(paths.sudoers_target.stat().st_mode) == 0o440
    assert stat.S_IMODE(paths.profile_target.stat().st_mode) == 0o644
    assert paths.sudoers_target.read_text() == (
        f"{MANAGED_MARKER}\n"
        f"{user} ALL=(root) NOPASSWD: /usr/libexec/openmates-command-apparmor \"\"\n"
    )
    profile = paths.profile_target.read_text()
    assert "profile openmates-bwrap /usr/libexec/openmates-bwrap flags=(unconfined)" in profile
    assert f"change_profile -> openmates-command.{os.getuid()}.[0-9a-f]*," in profile
    assert calls[0][1:3] == ["-cf", calls[0][2]]
    assert calls[1][1:4] == ["-Q", "-T", "-K"]
    assert calls[2] == [str(paths.parser), "-r", "-T", "-K", str(paths.profile_target)]
    compile_command, compile_cwd, compile_environment = compiler_calls[0]
    assert compile_command[:7] == [
        str(paths.compiler), "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
    ]
    assert compile_command[-1] == "-ldl"
    assert compile_cwd.parent == paths.mask_target.parent
    assert not compile_cwd.exists()
    assert compile_environment == {
        "HOME": "/root",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(compile_cwd),
    }


def test_kernel_load_failure_restores_every_previous_file(tmp_path: Path) -> None:
    paths, user = fixture_paths(tmp_path)
    old_mask = b"previous-managed-git-config-mask\n"
    old = {
        paths.broker_target: BROKER_PREFIX + b"print('old broker')\n",
        paths.bwrap_target: paths.bwrap_source.read_bytes(),
        paths.mask_target: old_mask,
        paths.mask_manifest_target: render_mask_manifest(old_mask),
        paths.sudoers_target: render_sudoers(user),
        paths.profile_target: render_bootstrap_profile(os.getuid()),
    }
    for target, content in old.items():
        target.write_bytes(content)
        target.chmod(0o755 if target.parent.name == "libexec" else 0o644)

    load_attempts = 0

    def fail_load(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal load_attempts
        if len(command) > 1 and command[1] == "-r":
            load_attempts += 1
        if load_attempts == 1 and len(command) > 1 and command[1] == "-r":
            return subprocess.CompletedProcess(command, 1, "", "kernel rejected profile")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(RuntimeError, match="kernel rejected profile"):
        install(
            user,
            paths=paths,
            runner=fail_load,
            compiler_runner=passing_compiler([]),
        )

    for target, content in old.items():
        assert target.read_bytes() == content
    assert load_attempts == 2


def test_refuses_unmanaged_profile_and_symlinked_trusted_path(tmp_path: Path) -> None:
    paths, user = fixture_paths(tmp_path)
    paths.profile_target.write_text("foreign profile\n")
    paths.profile_target.chmod(0o644)
    with pytest.raises(RuntimeError, match="unmanaged file"):
        install(user, paths=paths, runner=passing_runner([]), compiler_runner=passing_compiler([]))

    paths.profile_target.unlink()
    real = tmp_path / "real-libexec"
    real.mkdir()
    paths.broker_target.parent.rmdir()
    paths.broker_target.parent.symlink_to(real, target_is_directory=True)
    with pytest.raises(RuntimeError, match="not a real directory"):
        install(user, paths=paths, runner=passing_runner([]), compiler_runner=passing_compiler([]))


def test_refuses_to_replace_a_different_managed_user_rule(tmp_path: Path) -> None:
    paths, user = fixture_paths(tmp_path)
    paths.sudoers_target.write_bytes(
        f"{MANAGED_MARKER}\notheruser ALL=(root) NOPASSWD: /usr/libexec/openmates-command-apparmor \"\"\n".encode()
    )
    paths.sudoers_target.chmod(0o440)

    with pytest.raises(RuntimeError, match="existing managed user or policy"):
        install(user, paths=paths, runner=passing_runner([]), compiler_runner=passing_compiler([]))


def test_refuses_git_config_mask_without_matching_managed_manifest(tmp_path: Path) -> None:
    paths, user = fixture_paths(tmp_path)
    paths.mask_target.write_bytes(b"foreign-library\n")
    paths.mask_target.chmod(0o755)

    with pytest.raises(RuntimeError, match="incomplete Git config mask installation"):
        install(user, paths=paths, runner=passing_runner([]), compiler_runner=passing_compiler([]))

    paths.mask_manifest_target.write_bytes(render_mask_manifest(b"some-other-library\n"))
    paths.mask_manifest_target.chmod(0o644)
    with pytest.raises(RuntimeError, match="unknown Git config mask library"):
        install(user, paths=paths, runner=passing_runner([]), compiler_runner=passing_compiler([]))
