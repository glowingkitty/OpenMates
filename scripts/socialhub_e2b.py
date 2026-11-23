#!/usr/bin/env python3
"""Run a committed SocialHub revision directly in E2B, independent of GitHub Actions."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

import e2b_dev_capacity
import heavy_remote

PARTNER_REPO = Path.home() / "projects/socialhub"
SANDBOX_ROOT = "/home/user/socialhub"


def run(repo: Path, revision: str, command: list[str], timeout: int) -> int:
    """Upload tracked files from one commit, stream the test output and return its status."""
    from e2b import CommandExitException, Sandbox, SandboxException, TimeoutException

    commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
        text=True,
    ).strip()
    archive = subprocess.check_output(["git", "-C", str(repo), "archive", "--format=tar.gz", commit])
    slot = e2b_dev_capacity.acquire("socialhub: " + commit[:12], 900, announce=heavy_remote.say)
    if slot is None:
        raise heavy_remote.RemoteUnavailable("no E2B capacity available")
    with slot:
        if exhausted := e2b_dev_capacity.budget_exhausted():
            raise heavy_remote.RemoteUnavailable(exhausted)
        sandbox = Sandbox.create(template=heavy_remote.TEMPLATE_ALIAS, timeout=timeout + 180,
                                 api_key=heavy_remote.e2b_api_key(), metadata={"purpose": "socialhub-tests"})
        started = time.monotonic()
        try:
            sandbox.files.write("/home/user/socialhub.tar.gz", archive)
            heavy_remote.checked(
                sandbox, f"mkdir -p {SANDBOX_ROOT} && tar -xzf /home/user/socialhub.tar.gz -C {SANDBOX_ROOT}",
                120, "extracting the SocialHub source",
            )
            print(f"SocialHub {commit} in Linux E2B sandbox {sandbox.sandbox_id}", flush=True)
            result = sandbox.commands.run(
                shlex.join(command), cwd=SANDBOX_ROOT, timeout=timeout, envs=heavy_remote.sandbox_env("node"),
                on_stdout=lambda data: print(data, end="", flush=True),
                on_stderr=lambda data: print(data, end="", file=sys.stderr, flush=True),
                retain_output=False,
            )
            return result.exit_code
        except CommandExitException as error:
            return error.exit_code
        except TimeoutException:
            print("SocialHub E2B run timed out", file=sys.stderr)
            return 124
        finally:
            try:
                sandbox.kill()
            except SandboxException as error:
                print(f"E2B sandbox cleanup failed and will expire automatically: {error}", file=sys.stderr)
            e2b_dev_capacity.record_spend(
                time.monotonic() - started, heavy_remote.SANDBOX_CPUS, heavy_remote.SANDBOX_MEMORY_MB,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=PARTNER_REPO)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.timeout <= 0:
        parser.error("supply a command after -- and a positive timeout")
    return run(args.repo, args.revision, command, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
