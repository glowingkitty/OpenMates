#!/usr/bin/env python3
"""Run one planned heavy command in an E2B sandbox and stream its output back.

Started by `heavy_slot.py` with the E2B SDK venv (see VENV_DIR); never run
directly by agents. The sandbox comes from the TEMPLATE_ALIAS template
(`heavy_remote_template.py`): the public repository at a baseline commit with
the Rust toolchain, fetched crates and installed node packages. The run uploads
the files where the worktree differs from that commit, runs the command, and
exits with the command's exit code. The sandbox is killed afterwards.

Exit EXIT_REMOTE_UNAVAILABLE means the remote run could not be completed for an
infrastructure reason (no key, no sandbox, lost connection); heavy_slot then
says so and runs the command locally instead.

The E2B key is read from Vault through the `api` container for every run and is
kept only in this process.
"""

from __future__ import annotations

import argparse
import io
import os
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heavy_remote_plan as plan  # noqa: E402 - sibling module; path set up above

TEMPLATE_ALIAS = "openmates-heavy-remote"
SANDBOX_CPUS = 8
SANDBOX_MEMORY_MB = 8192
E2B_SDK_VERSION = "2.63.0"
VENV_DIR = Path.home() / ".cache" / "openmates" / "heavy-remote" / "venv"
EXIT_REMOTE_UNAVAILABLE = 75
STALE_BASE_DAYS = 7
PASS_THROUGH_ENV_PREFIXES = ("RUST_BACKTRACE", "RUST_LOG", "RUST_TEST_", "VITEST_")
SANDBOX_PATH = "/home/user/.cargo/bin:/home/user/.local/bin:/usr/local/bin:/usr/bin:/bin"
KEY_SNIPPET = """
import asyncio
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
async def main():
    manager = SecretsManager()
    await manager.initialize()
    try:
        print(await get_e2b_api_key_async(manager))
    finally:
        await manager.aclose()
asyncio.run(main())
"""


class RemoteUnavailable(RuntimeError):
    """The remote run failed for an infrastructure reason, not the command's."""


def say(message: str) -> None:
    print(f"heavy_slot[e2b]: {message}", file=sys.stderr, flush=True)


def e2b_api_key() -> str:
    """Fetch the E2B key from Vault via the api container (never printed)."""
    if os.environ.get("E2B_API_KEY"):
        return os.environ["E2B_API_KEY"]
    try:
        result = subprocess.run(["docker", "exec", "-i", "api", "python", "-"], input=KEY_SNIPPET,
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RemoteUnavailable(f"could not reach the api container for the E2B key: {exc}") from exc
    key = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if result.returncode != 0 or not key:
        raise RemoteUnavailable("the api container returned no E2B key")
    return key


def sync_archive(root: Path, sync: plan.SyncPlan) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for rel in sync.upload:
            archive.add(root / rel, arcname=rel, recursive=False)
    return buffer.getvalue()


def sandbox_env(kind: str) -> dict[str, str]:
    env = {"CI": "1", "PATH": SANDBOX_PATH, "CARGO_TERM_COLOR": "never",
           "CARGO_BUILD_JOBS": str(SANDBOX_CPUS)}
    env.update({k: v for k, v in os.environ.items() if k.startswith(PASS_THROUGH_ENV_PREFIXES)})
    if kind == "vitest":
        env["FORCE_COLOR"] = "0"
    return env


def checked(sbx, cmd: str, timeout: float, what: str) -> str:
    """Run a setup step in the sandbox; any failure is an infrastructure failure."""
    from e2b import CommandExitException

    try:
        return sbx.commands.run(cmd, timeout=timeout, envs={"PATH": SANDBOX_PATH}).stdout
    except CommandExitException as exc:
        raise RemoteUnavailable(f"{what} failed in the sandbox: {(exc.stderr or exc.stdout)[-400:]}") from exc


def prepare(sbx, root: Path, kind: str) -> dict:
    base = checked(sbx, f"git -C {plan.REMOTE_ROOT} rev-parse HEAD", 30, "reading the baseline").strip()
    if not plan.has_commit(root, base):
        raise RemoteUnavailable(f"baseline {base[:10]} is not in this worktree's history")
    age_days = (time.time() - int(subprocess.run(
        ["git", "-C", str(root), "show", "-s", "--format=%ct", base],
        capture_output=True, text=True, check=True).stdout.strip())) / 86400
    if age_days > STALE_BASE_DAYS:
        say(f"template baseline is {age_days:.0f} days old; refresh with "
            "python3 scripts/heavy_slot.py remote-template")
    sync = plan.sync_plan(root, base)
    for rel in sync.skipped_large:
        say(f"not uploaded (over {plan.MAX_SYNC_FILE_BYTES // 2**20} MB): {rel}")
    if sync.upload:
        sbx.files.write("/tmp/openmates-sync.tgz", sync_archive(root, sync))
        checked(sbx, f"tar -xzf /tmp/openmates-sync.tgz -C {plan.REMOTE_ROOT}", 300, "unpacking the sync")
    if sync.delete:
        sbx.files.write("/tmp/openmates-delete.txt", "\0".join(sync.delete))
        checked(sbx, f"cd {plan.REMOTE_ROOT} && xargs -0 rm -rf -- < /tmp/openmates-delete.txt", 60,
                "deleting removed files")
    if kind == "vitest" and sync.dependencies_changed:
        say("package manifests differ from the template; running pnpm install")
        checked(sbx, f"cd {plan.REMOTE_ROOT} && CI=1 corepack pnpm install --frozen-lockfile --prefer-offline",
                900, "pnpm install")
    return {"base": base[:12], "uploaded": len(sync.upload), "deleted": len(sync.delete)}


def run_remote(root: Path, kind: str, cwd: str, shell: str, timeout: float) -> int:
    from e2b import CommandExitException, Sandbox, SandboxException, TimeoutException

    started = time.monotonic()
    key = e2b_api_key()
    try:
        sbx = Sandbox.create(template=TEMPLATE_ALIAS, timeout=int(timeout) + 600, api_key=key,
                             metadata={"purpose": "heavy-slot", "session": os.environ.get("CLAUDE_CODE_SESSION_ID", "")[:60]})
    except SandboxException as exc:
        raise RemoteUnavailable(f"sandbox creation failed: {exc}") from exc
    command_started = False
    try:
        info = prepare(sbx, root, kind)
        say(f"running in E2B ({SANDBOX_CPUS} CPUs, {SANDBOX_MEMORY_MB // 1024} GB; baseline {info['base']}, "
            f"{info['uploaded']} files uploaded, {info['deleted']} deleted; "
            f"setup {time.monotonic() - started:.0f}s)")
        command_started = True
        try:
            result = sbx.commands.run(
                shell, cwd=cwd, envs=sandbox_env(kind), timeout=timeout,
                on_stdout=lambda data: (sys.stdout.write(data), sys.stdout.flush()),
                on_stderr=lambda data: (sys.stderr.write(data), sys.stderr.flush()),
                retain_output=False)
            code = result.exit_code
        except CommandExitException as exc:
            code = exc.exit_code
        except TimeoutException:
            say(f"command timed out after {timeout:.0f}s")
            code = 124
        say(f"exit {code} after {time.monotonic() - started:.0f}s")
        return code
    except (SandboxException, OSError) as exc:
        where = "during the command (output above may be partial)" if command_started else "during setup"
        raise RemoteUnavailable(f"lost the sandbox {where}: {exc}") from exc
    finally:
        try:
            sbx.kill()
        except SandboxException as exc:
            say(f"could not kill sandbox {sbx.sandbox_id} (it expires on its own): {exc}")


def _terminate(signum, _frame):
    raise SystemExit(128 + signum)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=["cargo", "vitest"])
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--shell", required=True)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _terminate)
    try:
        return run_remote(args.root, args.kind, args.cwd, args.shell, args.timeout)
    except RemoteUnavailable as exc:
        say(f"remote run unavailable: {exc}")
        return EXIT_REMOTE_UNAVAILABLE
    # Process boundary: the command's own result only ever arrives as an exit
    # code, so any exception here is an infrastructure failure. The E2B SDK's
    # exceptions (AuthenticationException, RateLimitException, ...) share no
    # common base, so they cannot be listed reliably.
    except Exception as exc:  # noqa: BLE001 - reported, then heavy_slot falls back locally
        say(f"remote run unavailable: {type(exc).__name__}: {str(exc)[:300]}")
        return EXIT_REMOTE_UNAVAILABLE


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
