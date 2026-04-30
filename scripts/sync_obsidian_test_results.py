#!/usr/bin/env python3
"""
Synchronizes the latest OpenMates test results into the local Obsidian vault.

The vault stores durable markdown summaries and only the latest screenshots.
Failed-run videos are copied into the vault so they can be played directly.
The script is idempotent: rerunning it for the same test-results/last-run.json
does not increment history counters twice.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = Path("/home/superdev/vaults/memory")
RESULTS_DIR = PROJECT_ROOT / "test-results"
SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"
TESTS_DIR = Path("OpenMates/Tests")
SPECS_DIR = TESTS_DIR / "Specs"
ASSETS_CURRENT_DIR = TESTS_DIR / "assets/current"
HISTORY_PATH = Path(".obsidian-auto/test-results-history.json")
OVERVIEW_PATH = TESTS_DIR / "Test runs.md"
FAILING_STATUSES = {"failed", "timeout", "timedOut", "dispatch_error", "result_unknown"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync OpenMates test results into Obsidian.")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def yaml_quote(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def frontmatter(props: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in props.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            if value:
                lines.extend(f"  - {yaml_quote(item)}" for item in value)
            else:
                lines.append("  []")
        else:
            lines.append(f"{key}: {yaml_quote(value)}")
    lines.append("---")
    return "\n".join(lines)


def discover_specs() -> list[str]:
    return sorted(path.name for path in SPEC_DIR.glob("*.spec.ts") if path.name != "create-test-account.spec.ts")


def spec_slug(spec: str) -> str:
    return spec.replace(".spec.ts", "").replace(".test.ts", "").replace("/", "-")


def markdown_note_link(slug: str, label: str) -> str:
    return f"[{label}](Specs/{slug}.md)"


def vault_video_names(vault: Path, slug: str) -> list[str]:
    video_dir = vault / ASSETS_CURRENT_DIR / slug
    if not video_dir.is_dir():
        return []
    return sorted(
        item.name for item in video_dir.iterdir()
        if item.suffix.lower() in {".webm", ".mp4"}
    )


def collect_playwright_tests(last_run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    playwright = last_run.get("suites", {}).get("playwright", {})
    tests = playwright.get("tests", []) if isinstance(playwright, dict) else []
    by_spec: dict[str, dict[str, Any]] = {}
    for test in tests:
        if not isinstance(test, dict):
            continue
        spec = test.get("file") or test.get("name")
        if not spec:
            continue
        by_spec[str(spec)] = test
    return by_spec


def is_failure(status: str) -> bool:
    return status in FAILING_STATUSES


def update_history(
    history: dict[str, Any],
    all_specs: list[str],
    tests_by_spec: dict[str, dict[str, Any]],
    run_id: str,
    run_time: str,
) -> dict[str, Any]:
    specs_state = history.setdefault("specs", {})
    history["last_synced_run_id"] = run_id
    history["last_synced_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for spec in all_specs:
        state = specs_state.setdefault(
            spec,
            {
                "total_runs": 0,
                "total_failures": 0,
                "consecutive_failures": 0,
                "last_status": "not_run",
                "first_failed_at": None,
                "last_failed_at": None,
                "last_run": None,
                "last_counted_run_id": None,
            },
        )
        test = tests_by_spec.get(spec)
        if not test:
            continue

        status = str(test.get("status", "unknown"))
        already_counted = state.get("last_counted_run_id") == run_id
        state["last_status"] = status
        state["last_run"] = run_time
        state["last_counted_run_id"] = run_id
        for key in ("github_run_url", "video_artifact_name", "video_paths", "local_video_paths"):
            if test.get(key):
                state[key] = test[key]

        if already_counted:
            continue

        state["total_runs"] = int(state.get("total_runs", 0)) + 1
        if is_failure(status):
            state["total_failures"] = int(state.get("total_failures", 0)) + 1
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
            state["first_failed_at"] = state.get("first_failed_at") or run_time
            state["last_failed_at"] = run_time
        else:
            state["consecutive_failures"] = 0

    return history


def reset_current_assets(vault: Path, results_dir: Path) -> None:
    """Copy screenshots into the vault, replacing only specs that have new screenshots.

    Specs not present in the current run keep their previous screenshots so that
    the vault always has at least one screenshot per test, not just those from the
    most recent batch.
    """
    dest_root = vault / ASSETS_CURRENT_DIR
    dest_root.mkdir(parents=True, exist_ok=True)

    source_root = results_dir / "screenshots/current"
    if not source_root.is_dir():
        return

    for spec_dir in source_root.iterdir():
        if not spec_dir.is_dir():
            continue
        new_images = [
            item for item in spec_dir.iterdir()
            if item.suffix.lower() in {".png", ".webp"}
        ]
        if not new_images:
            continue
        dest_dir = dest_root / spec_dir.name
        # Only wipe existing screenshots for this spec once fresh ones are available.
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        for item in new_images:
            shutil.copy2(item, dest_dir / item.name)


def copy_current_videos(vault: Path, results_dir: Path) -> None:
    """Copy locally persisted failed-run videos into the vault.

    Only videos from failed runs are persisted by run_tests.py. Successful-run
    videos stay in GitHub Actions artifacts to avoid unbounded vault growth.
    """
    source_root = results_dir / "videos/current"
    if not source_root.is_dir():
        return

    dest_root = vault / ASSETS_CURRENT_DIR
    dest_root.mkdir(parents=True, exist_ok=True)
    for spec_dir in source_root.iterdir():
        if not spec_dir.is_dir():
            continue
        videos = [item for item in spec_dir.iterdir() if item.suffix.lower() in {".webm", ".mp4"}]
        if not videos:
            continue
        dest_dir = dest_root / spec_dir.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        for old_video in dest_dir.iterdir():
            if old_video.suffix.lower() in {".webm", ".mp4"}:
                old_video.unlink()
        for video in videos:
            shutil.copy2(video, dest_dir / video.name)


def load_report(results_dir: Path, spec: str, status: str) -> str:
    slug = spec_slug(spec)
    report_dir = "failed" if is_failure(status) else "success"
    path = results_dir / "reports" / report_dir / f"{slug}.md"
    if not path.is_file():
        return "*No detailed markdown report was generated for this test in the latest run.*\n"
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("../../screenshots/current/", "../assets/current/")


def write_spec_note(
    vault: Path,
    results_dir: Path,
    spec: str,
    test: dict[str, Any] | None,
    state: dict[str, Any],
    run_id: str,
    run_time: str,
) -> None:
    slug = spec_slug(spec)
    status = str((test or {}).get("status") or state.get("last_status") or "not_run")
    github_run_url = (test or {}).get("github_run_url")
    artifact_name = (test or {}).get("video_artifact_name")
    video_paths = (test or {}).get("video_paths") or []
    local_video_paths = (test or {}).get("local_video_paths") or []
    local_video_names = [Path(path).name for path in local_video_paths]
    if not local_video_names and is_failure(status):
        local_video_names = vault_video_names(vault, slug)
    screenshot_paths = (test or {}).get("screenshot_paths") or []

    props = {
        "type": "e2e-test",
        "project": "OpenMates",
        "spec": spec,
        "last_status": status,
        "last_run": state.get("last_run"),
        "last_synced_run_id": run_id,
        "github_run_url": github_run_url,
        "artifact_name": artifact_name,
        "video_available": bool(video_paths or local_video_names),
        "local_video_available": bool(local_video_names),
        "total_runs": int(state.get("total_runs", 0)),
        "total_failures": int(state.get("total_failures", 0)),
        "consecutive_failures": int(state.get("consecutive_failures", 0)),
        "first_failed_at": state.get("first_failed_at"),
        "last_failed_at": state.get("last_failed_at"),
        "tags": ["openmates", "e2e-test"],
    }

    lines = [frontmatter(props), "", f"# {spec}", ""]
    lines.extend([
        f"**Latest status:** `{status}`",
        f"**Latest run:** {state.get('last_run') or run_time}",
        f"**Failure history:** {state.get('total_failures', 0)} failures / {state.get('total_runs', 0)} runs",
        f"**Consecutive failures:** {state.get('consecutive_failures', 0)}",
        "",
    ])

    if github_run_url or artifact_name or video_paths or local_video_names:
        lines.append("")
        lines.append("## Video / GitHub Run")
        lines.append("")
        if local_video_names:
            lines.append("Failed-run videos copied into this vault:")
            for video_name in local_video_names:
                rel_video_path = f"../assets/current/{slug}/{video_name}"
                lines.append(f"- [Open video]({rel_video_path})")
                lines.append(f"<video controls src=\"{rel_video_path}\"></video>")
            lines.append("")
        if github_run_url:
            lines.append(f"[View on GitHub Actions]({github_run_url})")
        if artifact_name:
            lines.append(f"Artifact: `{artifact_name}` — download from the GitHub run link above.")
        if video_paths:
            lines.append("")
            lines.append("Video paths inside the artifact:")
            for video_path in video_paths:
                lines.append(f"- `{video_path}`")
    if screenshot_paths:
        lines.append("")
        lines.append("## Current Screenshots")
        lines.append("")
        lines.append("Screenshots below are from the most recent synced run only.")

    lines.extend(["", "## Latest Run Report", ""])
    if test:
        lines.append(load_report(results_dir, spec, status))
    else:
        lines.append("*This spec was not part of the latest run.*\n")

    note_path = vault / SPECS_DIR / f"{slug}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def status_icon(status: str) -> str:
    if status == "passed":
        return "✅"
    if is_failure(status):
        return "❌"
    if status in {"skipped", "not_run"}:
        return "⏭️"
    return "❔"


def write_overview(
    vault: Path,
    all_specs: list[str],
    tests_by_spec: dict[str, dict[str, Any]],
    history: dict[str, Any],
    last_run: dict[str, Any],
) -> None:
    run_id = str(last_run.get("run_id", "unknown"))
    summary = last_run.get("summary", {})
    run_time = run_id
    props = {
        "type": "test-dashboard",
        "project": "OpenMates",
        "last_run": run_time,
        "total": summary.get("total", 0),
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "skipped": summary.get("skipped", 0),
        "not_started": summary.get("not_started", 0),
        "tags": ["openmates", "test-dashboard"],
    }

    lines = [frontmatter(props), "", "# OpenMates Test Runs", ""]
    lines.append("> Generated from `test-results/last-run.json`. Obsidian keeps latest screenshots plus failed-run videos; successful-run videos stay in GitHub Actions artifacts.")
    lines.append("")
    lines.append("## Latest Summary")
    lines.append("")
    lines.append(f"- Run: `{run_id}`")
    lines.append(f"- Total: `{summary.get('total', 0)}`")
    lines.append(f"- Passed: `{summary.get('passed', 0)}`")
    lines.append(f"- Failed: `{summary.get('failed', 0)}`")
    lines.append(f"- Skipped/not started: `{summary.get('skipped', 0)}` / `{summary.get('not_started', 0)}`")
    lines.append("")

    specs_state = history.get("specs", {})
    lines.append("## All Specs")
    lines.append("")
    lines.append("| Status | Spec | Last run | Failures | Consecutive | GitHub run | Video |")
    lines.append("| --- | --- | --- | ---: | ---: | --- | --- |")

    for spec in all_specs:
        test = tests_by_spec.get(spec) or {}
        state = specs_state.get(spec, {})
        status = str(test.get("status") or state.get("last_status") or "not_run")
        slug = spec_slug(spec)
        note = markdown_note_link(slug, spec)
        github_run_url = test.get("github_run_url") or state.get("github_run_url")
        run_link = f"[run]({github_run_url})" if github_run_url else ""
        local_video_names = [Path(path).name for path in test.get("local_video_paths") or state.get("local_video_paths") or []]
        if not local_video_names and is_failure(status):
            local_video_names = vault_video_names(vault, slug)
        if local_video_names:
            video_links = []
            for index, video_name in enumerate(local_video_names, start=1):
                video_links.append(f"[video {index}](assets/current/{slug}/{video_name})")
            video_text = ", ".join(video_links)
        else:
            video_text = "artifact" if test.get("video_paths") or state.get("video_paths") else ""
        lines.append(
            f"| {status_icon(status)} `{status}` | {note} | {state.get('last_run') or ''} | "
            f"{state.get('total_failures', 0)} | {state.get('consecutive_failures', 0)} | {run_link} | {video_text} |"
        )

    overview_path = vault / OVERVIEW_PATH
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    vault = args.vault.expanduser().resolve()
    results_dir = args.results_dir.expanduser().resolve()
    last_run_path = results_dir / "last-run.json"

    if not vault.exists():
        print(f"Obsidian vault not found, skipping: {vault}")
        return 0
    if not last_run_path.is_file():
        print(f"No last-run.json found, skipping: {last_run_path}")
        return 0

    last_run = load_json(last_run_path, {})
    run_id = str(last_run.get("run_id") or datetime.now(timezone.utc).isoformat(timespec="seconds"))
    run_time = run_id
    all_specs = discover_specs()
    tests_by_spec = collect_playwright_tests(last_run)
    history_abs = vault / HISTORY_PATH
    history = load_json(history_abs, {"specs": {}})
    history = update_history(history, all_specs, tests_by_spec, run_id, run_time)

    if args.dry_run:
        print(f"Would sync {len(all_specs)} spec notes into {vault / TESTS_DIR}")
        return 0

    reset_current_assets(vault, results_dir)
    copy_current_videos(vault, results_dir)
    for spec in all_specs:
        write_spec_note(
            vault,
            results_dir,
            spec,
            tests_by_spec.get(spec),
            history.get("specs", {}).get(spec, {}),
            run_id,
            run_time,
        )
    write_overview(vault, all_specs, tests_by_spec, history, last_run)
    write_json(history_abs, history)
    print(f"Synced {len(all_specs)} OpenMates test notes into {vault / TESTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
