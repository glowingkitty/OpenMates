"""Real-kernel AppArmor coverage for direct edits of an original Project.

This test is intentionally selectable only in the disposable isolated CI runner.
It installs host packages and the root-owned OpenMates broker, so ordinary local
and shared-development test runs must never execute it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import time

import pytest


pytestmark = pytest.mark.integration

REPOSITORY = Path(__file__).resolve().parents[2]
INSTALLER = REPOSITORY / "scripts/setup_remote_command_apparmor.py"
BROKER = Path("/usr/libexec/openmates-command-apparmor")
BWRAP = Path("/usr/libexec/openmates-bwrap")
AA_EXEC = Path("/usr/bin/aa-exec")
GIT_CONFIG_MASK = Path("/usr/libexec/openmates-git-config-mask.so")


def _require_disposable_ci() -> None:
    if (
        os.environ.get("OPENMATES_CI_ISOLATED") != "1"
        or os.environ.get("GITHUB_ACTIONS") != "true"
    ):
        pytest.skip("requires the disposable isolated GitHub Actions runner")
    if os.geteuid() == 0:
        pytest.fail("the live AppArmor test requires a non-root runner user", pytrace=False)


def _run_checked(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no command output").strip()
        pytest.fail(f"command failed ({command[0]}): {detail[:2_000]}", pytrace=False)
    return result


def _install_boundary() -> None:
    _run_checked(["/usr/bin/sudo", "-n", "/usr/bin/true"])
    _run_checked(["/usr/bin/sudo", "-n", "/usr/bin/apt-get", "update"], timeout=300)
    _run_checked(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/env",
            "DEBIAN_FRONTEND=noninteractive",
            "/usr/bin/apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "apparmor",
            "apparmor-utils",
            "bubblewrap",
        ],
        timeout=300,
    )
    enabled = Path("/sys/module/apparmor/parameters/enabled")
    if not enabled.is_file() or enabled.read_text(encoding="utf-8").strip() != "Y":
        pytest.fail("the isolated runner kernel does not enforce AppArmor", pytrace=False)
    _run_checked(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/python3",
            str(INSTALLER),
            "--user",
            pwd.getpwuid(os.getuid()).pw_name,
        ]
    )
    for executable in (BROKER, BWRAP, AA_EXEC, GIT_CONFIG_MASK):
        metadata = executable.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022 or not os.access(executable, os.X_OK):
            pytest.fail(f"installer left an untrusted executable: {executable}", pytrace=False)


def _broker_call(request: dict) -> dict:
    result = subprocess.run(
        ["/usr/bin/sudo", "-n", "--", str(BROKER)],
        input=json.dumps(request, separators=(",", ":")) + "\n",
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no broker output").strip()
        pytest.fail(f"AppArmor broker failed: {detail[:2_000]}", pytrace=False)
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail("AppArmor broker returned malformed JSON", pytrace=False)
    if not isinstance(response, dict):
        pytest.fail("AppArmor broker returned a non-object response", pytrace=False)
    return response


def _wait_for(path: Path, process: subprocess.Popen[str], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(
                f"confined process exited before synchronization: "
                f"code={process.returncode}, stdout={stdout[:500]!r}, stderr={stderr[:500]!r}",
                pytrace=False,
            )
        time.sleep(0.05)
    process.kill()
    process.wait(timeout=5)
    pytest.fail("timed out waiting for the confined process", pytrace=False)


CONFINED_PROBE = r"""
import errno
import json
import os
from pathlib import Path
import subprocess
import time

root = Path('/project')
denied_errnos = {errno.EACCES, errno.EPERM}

def denied(operation):
    try:
        operation()
    except OSError as error:
        return error.errno in denied_errnos
    return False

(root / 'ordinary.txt').write_text('edited by confined command\n', encoding='utf-8')
dependency_readable = (root / 'node_modules/dependency.txt').read_text(encoding='utf-8') == 'dependency\n'
(root / '.probe-ready').write_text('ready\n', encoding='utf-8')
while not (root / '.probe-go').exists():
    time.sleep(0.02)

child = subprocess.run(
    ['/bin/sh', '-c', 'cat /project/.env'],
    text=True,
    capture_output=True,
    check=False,
)
profile_escape = subprocess.run(
    ['/usr/bin/aa-exec', '-p', 'unconfined', '--', '/bin/true'],
    text=True,
    capture_output=True,
    check=False,
)
git_status = subprocess.run(
    ['/usr/bin/git', '-c', 'safe.directory=/project', 'status', '--short'],
    text=True, capture_output=True, check=False,
)
unmasked_config = subprocess.run(
    ['/usr/bin/python3', '-c', "open('/project/.git/config').read()"],
    env={**os.environ, 'LD_PRELOAD': ''}, text=True, capture_output=True, check=False,
)
result = {
    'dependency_readable': dependency_readable,
    'new_env_filename_visible': '.env' in os.listdir(root),
    'new_env_read_denied': denied(lambda: (root / '.env').read_text(encoding='utf-8')),
    'new_env_write_denied': denied(lambda: (root / '.env').write_text('changed\n', encoding='utf-8')),
    'child_private_read_denied': child.returncode != 0 and child.stdout == '',
    'child_profile_escape_denied': profile_escape.returncode != 0,
    'private_alias_read_denied': denied(lambda: (root / 'private-alias.txt').read_text(encoding='utf-8')),
    'private_rename_denied': denied(lambda: os.rename(root / 'config/private.txt', root / 'exposed.txt')),
    'private_hardlink_denied': denied(lambda: os.link(root / 'config/private.txt', root / 'exposed-link.txt')),
    'private_ancestor_rename_denied': denied(lambda: os.rename(root / 'config', root / 'relocated-config')),
    'git_status_works_with_empty_config': git_status.returncode == 0,
    'git_config_replacement_stays_empty': (root / '.git/config').read_text(encoding='utf-8') == '',
    'git_config_bypass_denied': unmasked_config.returncode != 0 and unmasked_config.stdout == '',
}
print(json.dumps(result, sort_keys=True), flush=True)
"""


# contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.ignored-project-files,code-run.remote.private-path-deny
def test_original_project_direct_edits_enforce_live_private_paths_in_kernel() -> None:
    _require_disposable_ci()
    _install_boundary()

    with tempfile.TemporaryDirectory(prefix="openmates-apparmor-project-") as directory:
        project = Path(directory).resolve()
        _run_checked(["/usr/bin/git", "init", "-q", str(project)])
        (project / "node_modules").mkdir()
        (project / "node_modules/dependency.txt").write_text("dependency\n", encoding="utf-8")
        (project / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        (project / "ordinary.txt").write_text("original\n", encoding="utf-8")
        (project / "config").mkdir()
        private = project / "config/private.txt"
        private.write_text("private\n", encoding="utf-8")
        os.link(private, project / "private-alias.txt")

        request = {
            "protocol_version": 1,
            "action": "prepare",
            "execution_id": "ci-apparmor-live-1",
            "project_root_digest": hashlib.sha256(str(project).encode()).hexdigest(),
            "private_policy_digest": hashlib.sha256(b"ci-private-policy-v1").hexdigest(),
            "private_globs": ["config/private.txt"],
            "exact_private_aliases": [{"path": "private-alias.txt", "kind": "file"}],
            "exact_readonly_paths": [],
        }
        prepared = _broker_call(request)
        profile_name = prepared["profile_name"]
        definition_digest = prepared["definition_digest"]
        assert prepared["private_policy_digest"] == request["private_policy_digest"]

        command = [
            str(BWRAP),
            "--unshare-all",
            "--unshare-user",
            "--disable-userns",
            "--assert-userns-disabled",
            "--die-with-parent",
            "--new-session",
            "--ro-bind",
            "/usr",
            "/usr",
            "--symlink",
            "usr/bin",
            "/bin",
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib64",
            "/lib64",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--bind",
            str(project),
            "/project",
            "--ro-bind",
            "/dev/null",
            "/project/.git/config",
            "--chdir",
            "/project",
            "--setenv",
            "LD_PRELOAD",
            str(GIT_CONFIG_MASK),
            "--setenv",
            "HOME",
            "/tmp",
            "--",
            str(AA_EXEC),
            "--profile",
            profile_name,
            "--",
            "/usr/bin/python3",
            "-c",
            CONFINED_PROBE,
        ]
        process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _wait_for(project / ".probe-ready", process)
            released = _broker_call(
                {
                    "protocol_version": 1,
                    "action": "release",
                    "lease_id": prepared["lease_id"],
                    "definition_digest": definition_digest,
                }
            )
            assert released == {
                "released": False,
                "retained": True,
                "definition_digest": definition_digest,
            }
            (project / ".env").write_text("created after sandbox launch\n", encoding="utf-8")
            (project / ".git/config").unlink()
            (project / ".git/config").write_text(
                '[remote "origin"]\nurl=https://DUMMY_PRIVATE_CANARY@example.invalid/project\n',
                encoding="utf-8",
            )
            (project / ".probe-go").write_text("go\n", encoding="utf-8")
            stdout, stderr = process.communicate(timeout=20)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise

        assert process.returncode == 0, stderr[:1_000]
        result = json.loads(stdout)
        assert result == {
            "child_private_read_denied": True,
            "child_profile_escape_denied": True,
            "dependency_readable": True,
            "git_status_works_with_empty_config": True,
            "git_config_replacement_stays_empty": True,
            "git_config_bypass_denied": True,
            "new_env_filename_visible": True,
            "new_env_read_denied": True,
            "new_env_write_denied": True,
            "private_alias_read_denied": True,
            "private_ancestor_rename_denied": True,
            "private_hardlink_denied": True,
            "private_rename_denied": True,
        }
        assert (project / "ordinary.txt").read_text(encoding="utf-8") == "edited by confined command\n"

        profiles = _run_checked(
            ["/usr/bin/sudo", "-n", "/usr/bin/cat", "/sys/kernel/security/apparmor/profiles"]
        ).stdout
        assert f"{profile_name} (enforce)" in profiles.splitlines()

        reused_request = {**request, "execution_id": "ci-apparmor-live-2"}
        reused = _broker_call(reused_request)
        assert reused["profile_name"] == profile_name
        assert reused["definition_digest"] == definition_digest
        second_release = _broker_call(
            {
                "protocol_version": 1,
                "action": "release",
                "lease_id": reused["lease_id"],
                "definition_digest": definition_digest,
            }
        )
        assert second_release["retained"] is True
