#!/usr/bin/env python3
"""Run a command on a committed revision of any local git repository in an E2B sandbox.

Uploads the tracked files of one commit (``git archive``) into the heavy-remote
template, inside the dev E2B capacity slot and budget, runs the command there and
exits with its status. Independent of GitHub Actions; no dev-host fallback.

Usage: python3 scripts/e2b_repo_run.py --repo PATH --sandbox-root DIR
       [--revision REV] [--timeout SECONDS] -- command...
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

import e2b_dev_capacity
import heavy_remote

ARCHIVE_PATH = "/home/user/repo-source.tar.gz"


def resolve_commit(repo: Path, revision: str) -> str:
    """The full commit id of `revision` in `repo`; fails for anything that is not a commit."""
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
        text=True,
    ).strip()


def run(repo: Path, revision: str, command: list[str], timeout: int,
        sandbox_root: str) -> int:
    """Upload tracked files from one commit, stream the command output and return its status."""
    from e2b import CommandExitException, Sandbox, SandboxException, TimeoutException

    commit = resolve_commit(repo, revision)
    archive = subprocess.check_output(["git", "-C", str(repo), "archive", "--format=tar.gz", commit])
    slot = e2b_dev_capacity.acquire("repo-tests: " + commit[:12], 900, announce=heavy_remote.say)
    if slot is None:
        raise heavy_remote.RemoteUnavailable("no E2B capacity available")
    with slot:
        if exhausted := e2b_dev_capacity.budget_exhausted():
            raise heavy_remote.RemoteUnavailable(exhausted)
        sandbox = Sandbox.create(template=heavy_remote.TEMPLATE_ALIAS, timeout=timeout + 180,
                                 api_key=heavy_remote.e2b_api_key(), metadata={"purpose": "repo-tests"})
        started = time.monotonic()
        try:
            sandbox.files.write(ARCHIVE_PATH, archive)
            root = shlex.quote(sandbox_root)
            heavy_remote.checked(
                sandbox, f"mkdir -p {root} && tar -xzf {ARCHIVE_PATH} -C {root}",
                120, "extracting the repository source",
            )
            print(f"Revision {commit} in Linux E2B sandbox {sandbox.sandbox_id}", flush=True)
            result = sandbox.commands.run(
                shlex.join(command), cwd=sandbox_root, timeout=timeout, envs=heavy_remote.sandbox_env("node"),
                on_stdout=lambda data: print(data, end="", flush=True),
                on_stderr=lambda data: print(data, end="", file=sys.stderr, flush=True),
                retain_output=False,
            )
            return result.exit_code
        except CommandExitException as error:
            return error.exit_code
        except TimeoutException:
            print("E2B repository run timed out", file=sys.stderr)
            return 124
        finally:
            try:
                sandbox.kill()
            except SandboxException as error:
                print(f"E2B sandbox cleanup failed and will expire automatically: {error}", file=sys.stderr)
            e2b_dev_capacity.record_spend(
                time.monotonic() - started, heavy_remote.SANDBOX_CPUS, heavy_remote.SANDBOX_MEMORY_MB,
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, required=True, help="local git repository to upload")
    parser.add_argument("--revision", default="HEAD", help="commit-ish to run (default: HEAD)")
    parser.add_argument("--timeout", type=int, default=1800, help="command timeout in seconds")
    parser.add_argument("--sandbox-root", required=True,
                        help="absolute directory for the source and command inside the sandbox")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    args.command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not args.command or args.timeout <= 0:
        parser.error("supply a command after -- and a positive timeout")
    if not args.sandbox_root.startswith("/"):
        parser.error("--sandbox-root must be an absolute path")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args.repo, args.revision, args.command, args.timeout, args.sandbox_root)


if __name__ == "__main__":
    sys.exit(main())
