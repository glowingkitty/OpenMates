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
    from scripts.ci_coordinator import Queue, canonical_root, enqueue_submission, TERMINAL
    from scripts.ci_candidate import load as load_candidate
    from scripts.ci_pytest_targets import validate_pytest_targets
except ModuleNotFoundError:
    from ci_coordinator import Queue, canonical_root, enqueue_submission, TERMINAL
    from ci_candidate import load as load_candidate
    from ci_pytest_targets import validate_pytest_targets

NON_E2E_BATCH_SIZE = 4


def spec_source(root: Path, source: str, spec: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{source}:frontend/apps/web_app/tests/{spec}"],
        cwd=root,
        text=True,
    )


def ensure_coordinator(root: Path):
    """Observe the installed service using the linger bus, including from cron."""
    try:
        from scripts.ci_coordinator_service import UNIT_NAME, manager
    except ModuleNotFoundError:
        from ci_coordinator_service import UNIT_NAME, manager
    return manager("is-active", "--quiet", UNIT_NAME).returncode == 0


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
            (p.relative_to(folder).as_posix() for p in folder.rglob("*.spec.ts")),
            manifest=manifest,
            spec_dir=folder,
        )
        if args.daily:
            plan = policy.daily_plan(
                (p.relative_to(folder).as_posix() for p in folder.rglob("*.spec.ts")),
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


def write_daily_manifest(
    canonical: Path, source: str, attempt: str, args, jobs: list[dict],
    selected_specs: list[str], held_specs: list[str], held_reasons: dict,
    *, selection_error: str = "",
) -> Path:
    """Keep a source-bound daily inventory, including failed selection."""
    import hashlib

    manifest_dir = canonical / "test-results/daily-runs"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_id = hashlib.sha256(
        json.dumps([source, attempt, args.suite, args.spec], sort_keys=True).encode()
    ).hexdigest()
    path = manifest_dir / (manifest_id + ".json")
    if path.exists():
        return path
    data = {
        "created": time.time(), "run_date": datetime.now(timezone.utc).date().isoformat(),
        "source_commit": source, "suite": args.suite,
        "jobs": [job["id"] for job in jobs],
        "selected_specs": selected_specs, "held_specs": held_specs,
        "held_reasons": held_reasons,
        "status": "blocked" if selection_error else "queued",
        "selection_error": selection_error,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)
    return path


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--spec", action="append", default=[])
    parser.add_argument(
        "--test-target",
        action="append",
        default=[],
        help="Exact repository-relative pytest file or node ID; repeatable",
    )
    parser.add_argument(
        "--suite",
        choices=["all", "pytest", "vitest", "playwright", "cli"],
        default="all",
    )
    parser.add_argument("--daily", action="store_true")
    parser.add_argument(
        "--session",
        default=os.environ.get("OPENMATES_SESSION_ID"),
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
    if args.test_target and args.suite != "pytest":
        raise ValueError("--test-target requires --suite pytest")
    pytest_targets = validate_pytest_targets(args.test_target)
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
    if (
        args.suite in ("all", "pytest", "vitest")
        and not args.daily
        and not args.spec
        and not pytest_targets
    ):
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
    candidate = {}
    if args.source:
        source = subprocess.check_output(
            ["git", "rev-parse", args.source + "^{commit}"], cwd=root, text=True
        ).strip()
        candidate = load_candidate(root, source, require_fresh=True)
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
        published = json.loads(output)
        source = published["source"]
        candidate = {} if published.get("unchanged") else load_candidate(
            root, source, required=True, require_fresh=True
        )
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
    held_reasons = {}
    selected_specs = []
    # Validate scheduled browser selection before queuing units. Previously a
    # newly unclassified AI spec left two orphan unit jobs and no daily record.
    if args.spec or args.suite in ("all", "playwright", "cli"):
        try:
            selected_specs = select_specs(root, args, source)
        except Exception as exc:
            if args.daily:
                write_daily_manifest(
                    canonical, source, attempt, args, [], [], [], {},
                    selection_error=f"{type(exc).__name__}: {exc}",
                )
            raise
    if pytest_targets:
        # The runner validates existence against the immutable candidate before
        # invoking pytest; the queue retains these exact node IDs unchanged.
        jobs.append(
            queue.enqueue(
                owner, source, pytest_targets, "pytest", attempt, candidate=candidate
            )
        )
    if args.daily and args.suite in ("all", "pytest", "vitest"):
        for mode in ("pytest", "vitest") if args.suite == "all" else (args.suite,):
            jobs.append(queue.enqueue(owner, source, [], mode, attempt, candidate=candidate))
    if args.spec or args.suite in ("all", "playwright", "cli"):
        specs = selected_specs
        if args.suite == "cli":
            specs = [s for s in specs if s.startswith("cli-")]
        if not specs:
            raise ValueError("No E2E tests selected")
        if not ready:
            held_specs, specs = specs, []
        else:
            from scripts.ci_coverage import partition
            specs, held_reasons = partition(specs)
            held_specs = list(held_reasons)
        from scripts.ci_coverage import execution_mode, runtime_batches
        modes = {
            spec: execution_mode(spec, spec_source(root, source, spec))
            for spec in specs
        }
        for mode in ("component", "e2e", "artifact", "selfhost"):
            selected = [spec for spec in specs if modes[spec] == mode]
            batches = (
                [[spec] for spec in selected]
                if mode in ("component", "e2e")
                else runtime_batches(selected, NON_E2E_BATCH_SIZE)
            )
            for batch in batches:
                if mode == "e2e":
                    jobs.extend(
                        enqueue_submission(
                            queue,
                            owner,
                            source,
                            batch,
                            mode,
                            attempt,
                            args.proof_video_profile,
                            candidate,
                            source_root=canonical,
                            prepared_builds=True,
                        )
                    )
                else:
                    jobs.append(queue.enqueue(
                        owner, source, batch, mode,
                        attempt, args.proof_video_profile, candidate,
                    ))
    if args.daily:
        write_daily_manifest(
            canonical, source, attempt, args, jobs, selected_specs,
            held_specs, held_reasons,
        )
    if not ensure_coordinator(canonical):
        if args.daily:
            daily_manifest_path = write_daily_manifest(
                canonical, source, attempt, args, jobs, selected_specs,
                held_specs, held_reasons,
            )
            data = json.loads(daily_manifest_path.read_text())
            data.update(
                status="blocked",
                coordinator_error="Persistent coordinator unavailable; queued jobs preserved",
            )
            temporary = daily_manifest_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n")
            temporary.replace(daily_manifest_path)
        print("Persistent CI coordinator unavailable; queued jobs preserved", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "source_commit": source,
                "environment": "github-isolated",
                "jobs": [j["id"] for j in jobs],
                "held_specs": held_specs,
                "held_reasons": held_reasons,
                "hold_reason": ("Some runtime coverage is not migrated" if ready else "Runner-local E2E cutover is not verified")
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
