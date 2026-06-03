#!/usr/bin/env python3
"""
Prepare or launch a user-guide freshness review for changed linked specs.

This is the second layer of test-backed user-guide freshness. It finds user
guides whose `tested_by` specs changed, gathers structured evidence, and either
prints a dry-run review package or spawns an OpenCode session to decide whether
the natural-language guide needs an update.

Validator: scripts/docs_guide_verify.py
Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from docs_guide_verify import REPO_ROOT, USER_GUIDE_ROOT, GuideMetadata, parse_guide


TMP_DIR = REPO_ROOT / "scripts" / ".tmp" / "docs-guide-review"
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(frozen=True)
class AffectedGuide:
    guide: GuideMetadata
    changed_specs: tuple[str, ...]


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def changed_files_since(since: str) -> set[str]:
    output = run_git(["diff", "--name-only", since, "--"])
    return {line.strip() for line in output.splitlines() if line.strip()}


def collect_linked_guides() -> list[GuideMetadata]:
    guides: list[GuideMetadata] = []
    for path in sorted(USER_GUIDE_ROOT.rglob("*.md")):
        metadata = parse_guide(path)
        if metadata.tested_by:
            guides.append(metadata)
    return guides


def find_affected_guides(changed_paths: set[str], specs: set[str]) -> list[AffectedGuide]:
    targets = changed_paths | specs
    affected: list[AffectedGuide] = []
    for guide in collect_linked_guides():
        changed_specs = tuple(
            entry.spec for entry in guide.tested_by if entry.spec in targets
        )
        if changed_specs:
            affected.append(AffectedGuide(guide=guide, changed_specs=changed_specs))
    return affected


def file_diff(path: str, since: str) -> str:
    try:
        return run_git(["diff", since, "--", path])
    except subprocess.CalledProcessError as exc:
        return f"[diff unavailable for {path}: {exc}]"


def read_file(path: str) -> str:
    full_path = REPO_ROOT / path
    if not full_path.exists():
        return f"[missing file: {path}]"
    return full_path.read_text(encoding="utf-8", errors="replace")


def read_env_file() -> dict[str, str]:
    env_path = REPO_ROOT / ".env"
    env_vars: dict[str, str] = {}
    if not env_path.is_file():
        return env_vars
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env_vars[key.strip()] = value.strip().strip("'\"")
    return env_vars


def get_env(key: str, dot_env: dict[str, str], default: str = "") -> str:
    return os.environ.get(key) or dot_env.get(key) or default


def build_prompt(
    affected: list[AffectedGuide], since: str, changed_paths: set[str], result_path: Path
) -> str:
    today = dt.date.today().isoformat()
    payload = {
        "review_date": today,
        "since": since,
        "changed_paths": sorted(changed_paths),
        "affected_guides": [
            {
                "guide": str(item.guide.path.relative_to(REPO_ROOT)),
                "changed_specs": list(item.changed_specs),
                "tested_by": [entry.__dict__ for entry in item.guide.tested_by],
            }
            for item in affected
        ],
    }

    sections: list[str] = [
        "You are reviewing whether OpenMates user-guide docs need updates after linked Playwright specs changed.",
        "",
        "Rules:",
        "- Read the guide text and linked spec diffs before editing.",
        "- Update natural-language user-guide docs only if user-visible behavior, steps, labels, screenshots, or expected outcomes changed.",
        "- Do not update docs for test-only refactors, helper cleanup, mock fixture changes that do not alter the user flow, or selector-only changes.",
        "- If docs do not need changes, report that clearly and do not edit files.",
        "- If docs need changes, edit only the affected docs under docs/user-guide/ unless a linked index needs a cross-link update.",
        "- After any doc edit, run: python3 scripts/docs_guide_verify.py --guide <changed-guide> for every changed guide.",
        "- If docs changed, admin notification is mandatory: include the changed guide path, linked spec, commit SHA once deployed, and a short explanation for Discord and email review.",
        "- Preserve the existing user-guide tone: plain language, no engineering jargon.",
        f"- Before finishing, write a machine-readable result JSON to `{result_path.relative_to(REPO_ROOT)}`.",
        "- The result JSON must have: docs_updated (boolean), changed_files (array), reason (string), notification_required (boolean), notification_summary (string).",
        "",
        "Structured review payload:",
        "```json",
        json.dumps(payload, indent=2),
        "```",
        "",
    ]

    for item in affected:
        guide_path = str(item.guide.path.relative_to(REPO_ROOT))
        sections.extend([
            f"## Guide: {guide_path}",
            "",
            "Current guide content:",
            "```markdown",
            read_file(guide_path),
            "```",
            "",
        ])
        for spec in item.changed_specs:
            sections.extend([
                f"### Changed spec: {spec}",
                "",
                "Spec diff:",
                "```diff",
                file_diff(spec, since),
                "```",
                "",
                "Current spec content:",
                "```ts",
                read_file(spec),
                "```",
                "",
            ])

    sections.extend([
        "Final response required:",
        "- State whether docs needed updates.",
        "- If updated, list files changed and the exact user-visible behavior that changed.",
        "- If not updated, explain why the spec change did not affect the guide.",
        f"- Confirm that you wrote `{result_path.relative_to(REPO_ROOT)}`.",
    ])
    return "\n".join(sections)


def make_run_paths(result_file: str | None) -> tuple[Path, Path]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    prompt_path = TMP_DIR / f"review-{timestamp}.md"
    result_path = (REPO_ROOT / result_file).resolve() if result_file else TMP_DIR / f"result-{timestamp}.json"
    return prompt_path, result_path


def write_prompt(prompt: str, prompt_path: Path) -> Path:
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def spawn_review(prompt_path: Path) -> None:
    name = "docs-guide-review"
    subprocess.run(
        [
            "python3",
            "scripts/sessions.py",
            "spawn-chat",
            "--prompt-file",
            str(prompt_path.relative_to(REPO_ROOT)),
            "--name",
            name,
            "--mode",
            "execute",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def run_direct_review(prompt_path: Path) -> None:
    message = (
        "Review the attached user-guide freshness prompt. Follow the prompt exactly, "
        "including writing the required result JSON file."
    )
    subprocess.run(
        [
            "opencode",
            "run",
            message,
            "--file",
            str(prompt_path),
            "--title",
            "docs guide review",
            "--dangerously-skip-permissions",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def validate_result_file(result_path: Path) -> dict[str, object]:
    if not result_path.exists():
        raise FileNotFoundError(f"Review result file was not written: {result_path}")
    data = json.loads(result_path.read_text(encoding="utf-8"))
    required = {
        "docs_updated": bool,
        "changed_files": list,
        "reason": str,
        "notification_required": bool,
        "notification_summary": str,
    }
    for key, expected_type in required.items():
        if key not in data:
            raise ValueError(f"Review result missing required key: {key}")
        if not isinstance(data[key], expected_type):
            raise TypeError(f"Review result key {key} must be {expected_type.__name__}")
    return data


def build_notification_text(result: dict[str, object], commit_sha: str) -> tuple[str, str]:
    changed_files = [str(path) for path in result.get("changed_files", [])]
    subject = f"[OpenMates] User guide docs updated ({commit_sha[:12]})"
    lines = [
        "User-guide docs were updated after a linked spec review.",
        "",
        f"Commit: {commit_sha}",
        "Changed files:",
        *(f"- {path}" for path in changed_files),
        "",
        "Reason:",
        str(result.get("reason") or "not provided"),
        "",
        "Notification summary:",
        str(result.get("notification_summary") or "not provided"),
    ]
    return subject, "\n".join(lines)


def post_discord_notification(result: dict[str, object], commit_sha: str, dry_run: bool) -> bool:
    dot_env = read_env_file()
    url = get_env("DISCORD_WEBHOOK_DOCS", dot_env) or get_env("DISCORD_WEBHOOK_DEV_NIGHTLY", dot_env)
    subject, text = build_notification_text(result, commit_sha)
    payload = {
        "username": "OpenMates Docs Review",
        "avatar_url": "https://openmates.org/favicon.png",
        "embeds": [
            {
                "title": subject,
                "description": text[:4000],
                "color": 0x3B82F6,
                "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            }
        ],
    }
    if dry_run:
        print("Dry-run Discord notification payload:")
        print(json.dumps(payload, indent=2))
        return True
    if not url:
        print("DISCORD_WEBHOOK_DOCS and DISCORD_WEBHOOK_DEV_NIGHTLY not set; skipping Discord.")
        return False

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "OpenMates-DocsGuideReview/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        print("Discord docs notification sent.")
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"Discord docs notification failed: HTTP {exc.code}: {body}")
    except Exception as exc:
        print(f"Discord docs notification failed: {exc}")
    return False


def send_email_notification(result: dict[str, object], commit_sha: str, dry_run: bool) -> bool:
    dot_env = read_env_file()
    admin_email = get_env("ADMIN_NOTIFY_EMAIL", dot_env)
    brevo_api_key = get_env("BREVO_API_KEY", dot_env)
    internal_token = get_env("INTERNAL_API_SHARED_TOKEN", dot_env)
    internal_api_url = get_env("INTERNAL_API_URL", dot_env, "http://localhost:8000").rstrip("/")
    subject, text = build_notification_text(result, commit_sha)
    payload = {
        "sender": {"name": "OpenMates", "email": "noreply@openmates.org"},
        "to": [{"email": admin_email or "<ADMIN_NOTIFY_EMAIL>"}],
        "subject": subject,
        "textContent": text,
        "headers": {
            "Precedence": "bulk",
            "Auto-Submitted": "auto-generated",
        },
    }
    if dry_run:
        print("Dry-run email notification payload:")
        redacted = {**payload, "to": [{"email": "<ADMIN_NOTIFY_EMAIL>"}]}
        print(json.dumps(redacted, indent=2))
        return True
    if not admin_email:
        print("ADMIN_NOTIFY_EMAIL not set; skipping email.")
        return False
    if not brevo_api_key and internal_token:
        return send_internal_email_notification(
            admin_email=admin_email,
            internal_api_url=internal_api_url,
            internal_token=internal_token,
            subject=subject,
            text=text,
            result=result,
            commit_sha=commit_sha,
        )
    if not brevo_api_key:
        print("BREVO_API_KEY and INTERNAL_API_SHARED_TOKEN not set; skipping email.")
        return False

    request = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"accept": "application/json", "api-key": brevo_api_key, "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        print(f"Email docs notification sent to {admin_email}.")
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"Email docs notification failed: HTTP {exc.code}: {body}")
    except Exception as exc:
        print(f"Email docs notification failed: {exc}")
    return False


def send_internal_email_notification(
    *,
    admin_email: str,
    internal_api_url: str,
    internal_token: str,
    subject: str,
    text: str,
    result: dict[str, object],
    commit_sha: str,
) -> bool:
    changed_files = [str(path) for path in result.get("changed_files", [])]
    payload = {
        "recipient_email": admin_email,
        "environment": "development",
        "run_id": f"docs-guide-review-{commit_sha[:12]}",
        "git_sha": commit_sha,
        "git_branch": run_git(["branch", "--show-current"]) or "dev",
        "duration_seconds": 0,
        "total": len(changed_files) or 1,
        "passed": len(changed_files) or 1,
        "failed": 0,
        "skipped": 0,
        "not_started": 0,
        "suites": [
            {
                "name": "docs-guide-review",
                "total": len(changed_files) or 1,
                "passed": len(changed_files) or 1,
                "failed": 0,
                "dispatch_error": 0,
                "not_started": 0,
                "status": "passed",
            }
        ],
        "failed_tests": [],
        "all_tests": [
            {"suite": "docs-guide-review", "name": path, "status": "passed", "duration_seconds": 0}
            for path in changed_files
        ],
        "subject_override": subject,
        "opencode_chat_url": text[:1000],
    }
    request = urllib.request.Request(
        f"{internal_api_url}/internal/dispatch-test-summary-email",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Internal-Service-Token": internal_token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        print(f"Internal API docs notification email dispatched to {admin_email}.")
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"Internal API docs notification email failed: HTTP {exc.code}: {body}")
    except Exception as exc:
        print(f"Internal API docs notification email failed: {exc}")
    return False


def notify_admin(result: dict[str, object], commit_sha: str, dry_run: bool = False) -> int:
    if not result.get("notification_required"):
        print("Review result does not require admin notification.")
        return 0
    discord_sent = post_discord_notification(result, commit_sha, dry_run)
    email_sent = send_email_notification(result, commit_sha, dry_run)
    if discord_sent and email_sent:
        return 0
    print("Docs notification did not reach both required channels.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="HEAD~1", help="Git ref to diff against.")
    parser.add_argument(
        "--spec",
        action="append",
        default=[],
        help="Explicit linked spec path to review. May be repeated.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run an OpenCode review. Dry-run is the default.",
    )
    parser.add_argument(
        "--execute-mode",
        choices=("spawn", "direct"),
        default="spawn",
        help="Execution backend. spawn opens a Zellij session; direct waits for opencode run.",
    )
    parser.add_argument(
        "--result-file",
        help="Path where the reviewer must write result JSON. Defaults to scripts/.tmp/docs-guide-review/.",
    )
    parser.add_argument(
        "--notify-admin",
        action="store_true",
        help="Notify admin after a direct review writes a result that requires notification.",
    )
    parser.add_argument(
        "--notify-result",
        help="Validate an existing result JSON and send its admin notification.",
    )
    parser.add_argument(
        "--commit-sha",
        help="Deployed commit SHA to include in admin notifications. Defaults to HEAD.",
    )
    parser.add_argument(
        "--dry-run-notify",
        action="store_true",
        help="Print Discord and email notification payloads without sending them.",
    )
    args = parser.parse_args()

    commit_sha = args.commit_sha or run_git(["rev-parse", "HEAD"])
    if args.notify_result:
        result = validate_result_file((REPO_ROOT / args.notify_result).resolve())
        return notify_admin(result, commit_sha, args.dry_run_notify)

    changed_paths = changed_files_since(args.since)
    affected = find_affected_guides(changed_paths, set(args.spec))
    if not affected:
        print("No linked user guides affected by changed specs.")
        return 0

    prompt_path, result_path = make_run_paths(args.result_file)
    prompt = build_prompt(affected, args.since, changed_paths, result_path)
    prompt_path = write_prompt(prompt, prompt_path)

    print(f"Affected guides: {len(affected)}")
    for item in affected:
        guide_path = item.guide.path.relative_to(REPO_ROOT)
        print(f"- {guide_path}: {', '.join(item.changed_specs)}")
    print(f"Review prompt written to: {prompt_path.relative_to(REPO_ROOT)}")

    notification_payload = {
        "event": "docs_guide_review_prepared",
        "affected_guides": [str(item.guide.path.relative_to(REPO_ROOT)) for item in affected],
        "linked_specs": sorted({spec for item in affected for spec in item.changed_specs}),
        "prompt_file": str(prompt_path.relative_to(REPO_ROOT)),
        "result_file": str(result_path.relative_to(REPO_ROOT)),
    }
    print("Admin notification payload for any resulting docs change:")
    print(json.dumps(notification_payload, indent=2))

    if args.execute:
        if args.execute_mode == "direct":
            run_direct_review(prompt_path)
            result = validate_result_file(result_path)
            print("OpenCode direct review completed with result:")
            print(json.dumps(result, indent=2))
            if args.notify_admin:
                return notify_admin(result, commit_sha, args.dry_run_notify)
        else:
            spawn_review(prompt_path)
            print("Spawned OpenCode docs guide review session.")
            print(f"Expected result file: {result_path.relative_to(REPO_ROOT)}")
    else:
        print("Dry-run only. Re-run with --execute to spawn the review session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
