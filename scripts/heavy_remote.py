#!/usr/bin/env python3
"""Run one planned heavy command in an E2B sandbox and stream its output back.

Started by `heavy_slot.py` with the E2B SDK venv (see VENV_DIR); never run
directly by agents. The sandbox comes from the TEMPLATE_ALIAS template
(`heavy_remote_template.py`): the public repository at a baseline commit with
the Rust toolchain, fetched crates, installed node packages and Playwright's
Chromium. The run uploads the files where the worktree differs from that commit
(plus any /tmp folder the plan names), runs the command, copies back the files
the command created or changed, and exits with the command's exit code. The
sandbox is killed afterwards; its estimated cost goes to the dev E2B ledger
(`e2b_dev_capacity.py`).

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
import shlex
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2b_dev_capacity  # noqa: E402 - sibling module; path set up above
import heavy_remote_plan as plan  # noqa: E402 - sibling module; path set up above

TEMPLATE_ALIAS = "openmates-heavy-remote"
SANDBOX_CPUS = 8
SANDBOX_MEMORY_MB = 8192
E2B_SDK_VERSION = "2.63.0"
VENV_DIR = Path.home() / ".cache" / "openmates" / "heavy-remote" / "venv"
EXIT_REMOTE_UNAVAILABLE = 75
STALE_BASE_DAYS = 7
PASS_THROUGH_ENV_PREFIXES = ("RUST_BACKTRACE", "RUST_LOG", "RUST_TEST_", "VITEST_", "NODE_OPTIONS")
# Browser runs against the dev stack need its URL and the dev test-account
# credentials (never production ones); OPENMATES_HEAVY_REMOTE_ENV names more.
PLAYWRIGHT_ENV_PREFIXES = ("PLAYWRIGHT_", "OPENMATES_TEST_ACCOUNT_", "OPENMATES_PERSONAL_TEST_ACOUNT_",
                           "OPENMATES_PROOF_", "E2E_")
MAX_PULL_BYTES = 1024 * 1024 * 1024
# Reads `git status --porcelain -z` on stdin; prints "D <path>" for deletions and
# "F <path>" for files written after the run marker (argv[1]).
CHANGED_FILES_SCRIPT = """
import os, sys
marker = os.path.getmtime(sys.argv[1])
for entry in sys.stdin.buffer.read().split(b"\\0"):
    entry = entry.decode(errors="surrogateescape")
    if len(entry) < 4:
        continue
    status, path = entry[:2].strip(), entry[3:]
    if status == "D":
        print("D", path)
    elif os.path.isfile(path) and os.path.getmtime(path) > marker:
        print("F", path)
"""
RUN_MARKER = "/tmp/openmates-run-start"
# Upload/download staging. Not /tmp: it is sticky, and the E2B file API cannot rewrite a file there
# that it wrote before (2026-11-14: a second proof folder failed with "permission denied").
STAGING = "/home/user/.openmates-staging"
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


def sandbox_env(kind: str) -> dict[str, str]:
    env = {"CI": "1", "PATH": SANDBOX_PATH, "CARGO_TERM_COLOR": "never",
           "CARGO_BUILD_JOBS": str(SANDBOX_CPUS)}
    prefixes = PASS_THROUGH_ENV_PREFIXES + (PLAYWRIGHT_ENV_PREFIXES if kind == "playwright" else ())
    extra = {name.strip() for name in os.environ.get("OPENMATES_HEAVY_REMOTE_ENV", "").split(",") if name.strip()}
    env.update({k: v for k, v in os.environ.items() if k.startswith(prefixes) or k in extra})
    if kind in {"vitest", "node", "playwright"}:
        env["FORCE_COLOR"] = "0"
    return env


def tar_paths(root: Path, rels: list[str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for rel in rels:
            archive.add(root / rel, arcname=rel, recursive=False)
    return buffer.getvalue()


def link_local_paths(sbx, root: Path) -> None:
    """Make the worktree's absolute path and the Playwright browser cache resolve in the sandbox."""
    browsers = Path.home() / ".cache" / "ms-playwright"
    links = [(str(root), plan.REMOTE_ROOT), (str(browsers), "/home/user/.cache/ms-playwright")]
    script = " && ".join(
        f"sudo mkdir -p {shlex.quote(os.path.dirname(local))} && sudo ln -sfn {target} {shlex.quote(local)}"
        for local, target in links if local != target)
    # Proof configs pin the dev server's browser revision (e.g. chromium-1208/chrome-linux/chrome);
    # point each revision the sandbox lacks at its installed one of the same browser.
    local_revisions = sorted(p.name for p in browsers.glob("*-*") if p.is_dir()) if browsers.is_dir() else []
    for name in local_revisions:
        kind = name.rsplit("-", 1)[0]
        script += (f" && cd /home/user/.cache/ms-playwright && {{ [ -e {name} ] || {{ "
                   f"installed=$(ls -d {kind}-[0-9]* 2>/dev/null | sort -V | tail -1); "
                   f"[ -z \"$installed\" ] || ln -s \"$installed\" {name}; }}; }}")
    script += (" && for d in /home/user/.cache/ms-playwright/chromium-*/; do "
               "[ -e \"$d/chrome-linux\" ] || [ ! -e \"$d/chrome-linux64\" ] || ln -s chrome-linux64 \"$d/chrome-linux\"; "
               "done; true")
    checked(sbx, script, 30, "linking local paths")


def upload_external(sbx, folders: tuple[str, ...]) -> None:
    for folder in folders:
        base = Path(folder)
        rels = [str(p.relative_to(base)) for p in base.rglob("*") if p.is_file() or p.is_symlink()]
        quoted = shlex.quote(folder)
        checked(sbx, f"sudo mkdir -p {quoted} && sudo chown user:user {quoted}", 30, "creating " + folder)
        if rels:
            sbx.files.write(f"{STAGING}/openmates-external.tgz", tar_paths(base, rels))
            checked(sbx, f"tar -xzf {STAGING}/openmates-external.tgz -C {quoted}", 120, "unpacking " + folder)


def pull_back(sbx, root: Path, planned_external: tuple[str, ...], cargo_build: bool) -> None:
    """Copy back what the command created or changed: repo files, /tmp folders, cargo outputs."""
    repo = plan.REMOTE_ROOT
    sbx.files.write(f"{STAGING}/openmates-changed.py", CHANGED_FILES_SCRIPT)
    listing = checked(sbx, f"cd {repo} && git status --porcelain=v1 -z --untracked-files=all --no-renames "
                           f"| python3 {STAGING}/openmates-changed.py {RUN_MARKER}", 120, "listing changed files")
    files = [line[2:] for line in listing.splitlines() if line.startswith("F ")]
    deleted = [line[2:] for line in listing.splitlines() if line.startswith("D ")]
    finds = [f"find {shlex.quote(folder)} -type f -newer {RUN_MARKER}" for folder in planned_external]
    if cargo_build:
        finds.append(f"find {repo} -path '*/node_modules' -prune -o -type d \\( -path '*/target/debug' "
                     f"-o -path '*/target/release' \\) -print 2>/dev/null | while read d; do "
                     f"find \"$d\" -maxdepth 1 -type f -newer {RUN_MARKER} ! -name '*.d'; done")
    absolute = checked(sbx, " ; ".join(finds), 120, "listing outputs").split("\n") if finds else []
    absolute = [a for a in absolute if a.strip()]
    items = [f"{repo}/{rel}" for rel in files] + absolute
    if items:
        sbx.files.write(f"{STAGING}/openmates-pull.txt", "\n".join(items))
        size = int(checked(sbx, f"cat {STAGING}/openmates-pull.txt | tr '\\n' '\\0' | du -cb --files0-from=- "
                                "| tail -1 | cut -f1", 120, "measuring outputs").strip() or 0)
        if size > MAX_PULL_BYTES:
            raise RemoteUnavailable(f"outputs to copy back are {size / 2**20:.0f} MB (limit "
                                    f"{MAX_PULL_BYTES / 2**20:.0f} MB)")
        checked(sbx, f"tar -czPf {STAGING}/openmates-pull.tgz -T {STAGING}/openmates-pull.txt", 600, "packing outputs")
        data = sbx.files.read(f"{STAGING}/openmates-pull.tgz", format="bytes")
        with tarfile.open(fileobj=io.BytesIO(bytes(data)), mode="r:gz") as archive:
            for member in archive.getmembers():
                local = local_path(member.name, root, planned_external)
                if local is None or not member.isfile():
                    continue
                local.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                local.write_bytes(source.read())
                os.chmod(local, member.mode & 0o777)
    for rel in deleted:
        target = root / rel
        if target.is_file() or target.is_symlink():
            target.unlink()
    if items or deleted:
        say(f"copied back {len(items)} changed files, removed {len(deleted)}")


def local_path(name: str, root: Path, external: tuple[str, ...]) -> Path | None:
    """Map a sandbox path from the pull archive to the local file it replaces."""
    name = "/" + name.lstrip("/")
    repo = plan.REMOTE_ROOT + "/"
    if name.startswith(repo):
        rel = Path(name[len(repo):])
        if ".." in rel.parts:
            return None
        return root / rel
    if any(name.startswith(folder.rstrip("/") + "/") for folder in external) and ".." not in Path(name).parts:
        return Path(name)
    return None


def checked(sbx, cmd: str, timeout: float, what: str) -> str:
    """Run a setup step in the sandbox; any failure is an infrastructure failure."""
    from e2b import CommandExitException

    try:
        return sbx.commands.run(cmd, timeout=timeout, envs={"PATH": SANDBOX_PATH}).stdout
    except CommandExitException as exc:
        raise RemoteUnavailable(f"{what} failed in the sandbox: {(exc.stderr or exc.stdout)[-400:]}") from exc


def prepare(sbx, root: Path, kind: str, external: tuple[str, ...]) -> dict:
    link_local_paths(sbx, root)
    upload_external(sbx, external)
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
        sbx.files.write(f"{STAGING}/openmates-sync.tgz", tar_paths(root, sync.upload))
        checked(sbx, f"tar -xzf {STAGING}/openmates-sync.tgz -C {plan.REMOTE_ROOT}", 300, "unpacking the sync")
    if sync.delete:
        sbx.files.write(f"{STAGING}/openmates-delete.txt", "\0".join(sync.delete))
        checked(sbx, f"cd {plan.REMOTE_ROOT} && xargs -0 rm -rf -- < {STAGING}/openmates-delete.txt", 60,
                "deleting removed files")
    if kind != "cargo" and sync.dependencies_changed:
        say("package manifests differ from the template; running pnpm install")
        checked(sbx, f"cd {plan.REMOTE_ROOT} && CI=1 corepack pnpm install --frozen-lockfile --prefer-offline",
                900, "pnpm install")
    checked(sbx, f"touch {RUN_MARKER} && sleep 1", 30, "marking the run start")
    return {"base": base[:12], "uploaded": len(sync.upload), "deleted": len(sync.delete)}


def run_remote(root: Path, kind: str, cwd: str, shell: str, timeout: float,
               external: tuple[str, ...] = (), cargo_build: bool = False) -> int:
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
        info = prepare(sbx, root, kind, external)
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
        pull_back(sbx, root, external, cargo_build)
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
        seconds = time.monotonic() - started
        cost = e2b_dev_capacity.record_spend(seconds, SANDBOX_CPUS, SANDBOX_MEMORY_MB)
        say(f"sandbox time {seconds:.0f}s, estimated cost ${cost:.3f}")


def _terminate(signum, _frame):
    raise SystemExit(128 + signum)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=["cargo", "vitest", "node", "playwright"])
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--shell", required=True)
    parser.add_argument("--external", action="append", default=[], help="/tmp folder to mirror")
    parser.add_argument("--cargo-build", action="store_true", help="copy target/{debug,release} outputs back")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _terminate)
    try:
        return run_remote(args.root, args.kind, args.cwd, args.shell, args.timeout,
                          tuple(args.external), args.cargo_build)
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
