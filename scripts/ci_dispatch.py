"""User-facing test selection for the shared isolated GitHub CI coordinator.

Focused unit checks execute locally; daily units and all application E2E execute
on GitHub. Tasks wait on cached queue state, never acquire shared-dev/account
leases. The coordinator owns GitHub calls and source identity stays explicit.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time

try:
    from scripts.ci_coordinator import Queue, canonical_root, TERMINAL
except ModuleNotFoundError:
    from ci_coordinator import Queue, canonical_root, TERMINAL

BATCH_SIZE = 4


def ensure_coordinator(root: Path):
    unit = "openmates-ci-coordinator.service"
    state = subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit])
    if state.returncode == 0:
        return
    subprocess.run(
        [
            "systemd-run",
            "--user",
            "--collect",
            "--unit=" + unit,
            "--property=Restart=on-failure",
            "--property=RestartSec=10",
            "--property=MemoryMax=256M",
            "--working-directory=" + str(root),
            sys.executable,
            str(root / "scripts/ci_coordinator.py"),
            "serve",
        ],
        check=True,
    )


def select_specs(root: Path, args, source: str) -> list[str]:
    """Discover only files and policy from the immutable test subject."""
    payload = subprocess.check_output(
        [
            "git",
            "archive",
            source,
            "frontend/apps/web_app/tests",
            "scripts/daily_ai_test_manifest.json",
        ],
        cwd=root,
    )
    with tempfile.TemporaryDirectory(prefix="ci-selection-") as directory:
        snapshot = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            for member in archive:
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Unsafe test subject path")
                if member.isfile() and (
                    member.name.endswith(".spec.ts")
                    or member.name == "scripts/daily_ai_test_manifest.json"
                ):
                    target = snapshot / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
        return select_snapshot_specs(snapshot, args)


def select_snapshot_specs(root: Path, args) -> list[str]:
    folder = root / "frontend/apps/web_app/tests"
    if args.spec:
        names = args.spec
    else:
        from scripts import daily_ai_test_policy as policy

        manifest = policy.load_manifest(root / "scripts/daily_ai_test_manifest.json")

        names = policy.discover_specs(
            (p.name for p in folder.glob("*.spec.ts")),
            manifest=manifest,
            spec_dir=folder,
        )
        if args.daily:
            plan = policy.daily_plan(
                (p.name for p in folder.glob("*.spec.ts")),
                datetime.now(timezone.utc).date(),
                scheduled=True,
                record_mode=False,
                manifest=manifest,
            )
            names = list(dict.fromkeys([*names, *plan.selected]))
    for name in names:
        path = (folder / name).resolve()
        if (
            not path.is_relative_to(folder)
            or not path.is_file()
            or not name.endswith(".spec.ts")
        ):
            raise ValueError("Unknown E2E spec: " + name)
    return names


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--spec", action="append", default=[])
    parser.add_argument(
        "--suite",
        choices=["all", "pytest", "vitest", "playwright", "cli"],
        default="all",
    )
    parser.add_argument("--daily", action="store_true")
    parser.add_argument(
        "--session",
        default=os.environ.get("OPENMATES_SESSION_ID")
        or os.environ.get("OPENCODE_SESSION_ID"),
    )
    parser.add_argument("--expected-commit", "--commit", dest="source")
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--gate-deploy",
        action="store_true",
        help="Legacy spelling: now verifies CI source identity, never waits for Vercel",
    )
    parser.add_argument("--require-exact-commit", action="store_true")
    parser.add_argument("--no-fail-fast", action="store_true")
    parser.add_argument(
        "--proof-video-profile", choices=["web-phone", "web-laptop"], default=""
    )
    args = parser.parse_args(argv)
    root = (
        args.worktree.resolve()
        if args.worktree
        else Path(__file__).resolve().parent.parent
    )
    if (
        not args.session
        and root.name.startswith("agent-")
        and root.parent.name == ".openmates-agent-worktrees"
    ):
        args.session = root.name.removeprefix("agent-")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    canonical = canonical_root(root)
    if args.suite in ("all", "pytest", "vitest") and not args.daily and not args.spec:
        from scripts import run_tests as local_tests

        local_tests.PROJECT_ROOT = root
        local_tests.RESULTS_DIR = root / "test-results"
        checks = (
            (local_tests.run_pytest, local_tests.run_vitest)
            if args.suite == "all"
            else (
                (local_tests.run_pytest,)
                if args.suite == "pytest"
                else (local_tests.run_vitest,)
            )
        )
        units_passed = True
        for check in checks:
            result = check()
            print(json.dumps(asdict(result), default=str))
            units_passed &= result.status == "passed"
        if not units_passed:
            return 1
        if args.suite != "all":
            return 0
    readiness = canonical / "logs/ci-coordinator/cutover.json"
    ready = (
        readiness.is_file() and json.loads(readiness.read_text()).get("ready") is True
    )
    if not ready and not args.daily:
        raise RuntimeError(
            "Isolated GitHub CI migration HOLD: runner-local pilot is not verified. Shared-dev and self-hosted-runner fallback are forbidden. Local unit tests remain available."
        )
    if args.source:
        source = subprocess.check_output(
            ["git", "rev-parse", args.source + "^{commit}"], cwd=root, text=True
        ).strip()
    elif args.daily:
        subprocess.run(
            ["git", "fetch", "--no-tags", "origin", "dev"], cwd=canonical, check=True
        )
        source = subprocess.check_output(
            ["git", "rev-parse", "FETCH_HEAD"], cwd=canonical, text=True
        ).strip()
    else:
        if not args.session:
            raise ValueError(
                "A worktree run requires --session or an explicit --expected-commit"
            )
        output = subprocess.check_output(
            [
                sys.executable,
                str(canonical / "scripts/sessions.py"),
                "ci-source",
                "--session",
                args.session,
            ],
            cwd=root,
            text=True,
        )
        source = json.loads(output)["source"]
    queue = Queue(canonical / "logs/ci-coordinator/queue.sqlite3")
    owner = args.session or "daily"
    attempt = (
        str(time.time_ns())
        if args.force
        else datetime.now(timezone.utc).date().isoformat()
        if args.daily
        else ""
    )
    jobs = []
    held_specs = []
    if args.daily and args.suite in ("all", "pytest", "vitest"):
        for mode in ("pytest", "vitest") if args.suite == "all" else (args.suite,):
            jobs.append(queue.enqueue(owner, source, [], mode, attempt))
    if args.spec or args.suite in ("all", "playwright", "cli"):
        specs = select_specs(root, args, source)
        if args.suite == "cli":
            specs = [s for s in specs if s.startswith("cli-")]
        if not specs:
            raise ValueError("No E2E tests selected")
        if not ready:
            held_specs, specs = specs, []
        for index in range(0, len(specs), BATCH_SIZE):
            jobs.append(
                queue.enqueue(
                    owner,
                    source,
                    specs[index : index + BATCH_SIZE],
                    "e2e",
                    attempt,
                    args.proof_video_profile,
                )
            )
    ensure_coordinator(canonical)
    print(
        json.dumps(
            {
                "source_commit": source,
                "environment": "github-isolated",
                "jobs": [j["id"] for j in jobs],
                "held_specs": held_specs,
                "hold_reason": "Runner-local E2E cutover is not verified"
                if held_specs
                else None,
            }
        ),
        flush=True,
    )
    if args.detach:
        return 2 if held_specs else 0
    if not jobs:
        return 2
    previous = None
    while True:
        current = [queue.status(j["id"])[0] for j in jobs]
        states = [(j["id"], j["state"], j["url"]) for j in current]
        if states != previous:
            print(json.dumps(states), flush=True)
            previous = states
        if any(j["state"] == "attention" for j in current):
            print(
                "Coordinator requires remote dispatch reconciliation; no duplicate was sent.",
                file=sys.stderr,
            )
            return 2
        if all(j["state"] in TERMINAL for j in current):
            output = canonical / "test-results/ci-runs"
            output.mkdir(parents=True, exist_ok=True)
            identity = jobs[0]["id"]
            (output / (identity + ".json")).write_text(
                json.dumps(
                    {
                        "source_commit": source,
                        "environment": "github-isolated",
                        "jobs": current,
                        "held_specs": held_specs,
                    },
                    indent=2,
                )
            )
            return (
                0
                if not held_specs and all(j["state"] == "success" for j in current)
                else 1
            )
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
