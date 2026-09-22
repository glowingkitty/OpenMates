#!/usr/bin/env python3
"""Publish one stable release only after every main artifact is available.

The workflow invoking this script is triggered by the CLI, Python SDK, and
self-host image workflows. The first invocation waits for the other workflows
for the same commit. Publication fails closed if any required workflow or
artifact disagrees with that commit.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
PRODUCT_VERSION = ROOT / "shared" / "config" / "product_version.json"
REQUIRED_WORKFLOWS = (
    "Publish CLI",
    "Publish Python SDK",
    "Publish Self-Host Images",
)
STABLE_IMAGES = (
    "openmates-api",
    "openmates-docs-worker",
    "openmates-directus",
    "openmates-cms-setup",
    "openmates-vault-setup",
    "openmates-admin-sidecar",
    "openmates-uploads",
    "openmates-upload-vault-setup",
    "openmates-preview",
    "openmates-webapp",
    "openmates-ci-schema",
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class StableReleaseError(RuntimeError):
    """Raised when stable release provenance is incomplete or inconsistent."""


@dataclass(frozen=True)
class ReleaseIdentity:
    version: str
    tag: str
    product_line: str


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def load_release_identity(path: Path = PRODUCT_VERSION) -> ReleaseIdentity:
    config = json.loads(path.read_text(encoding="utf-8"))
    cli_version = str(config.get("cli", {}).get("stableBase", "")).strip()
    python_version = str(config.get("python", {}).get("stableBase", "")).strip()
    product_line = str(config.get("userFacing", "")).strip()
    if not VERSION_RE.fullmatch(cli_version):
        raise StableReleaseError(f"invalid CLI stable version: {cli_version or 'missing'}")
    if cli_version != python_version:
        raise StableReleaseError(
            f"CLI and Python stable versions differ: {cli_version} != {python_version}"
        )
    if not re.fullmatch(r"v\d+\.\d+", product_line):
        raise StableReleaseError(f"invalid product line: {product_line or 'missing'}")
    return ReleaseIdentity(version=cli_version, tag=f"v{cli_version}", product_line=product_line)


def latest_required_workflow_states(payload: dict[str, Any], commit: str) -> dict[str, tuple[str, str]]:
    latest: dict[str, tuple[int, str, str]] = {}
    for item in payload.get("workflow_runs", []):
        if item.get("head_sha") != commit or item.get("event") != "push":
            continue
        name = str(item.get("name") or "")
        if name not in REQUIRED_WORKFLOWS:
            continue
        run_id = int(item.get("id") or 0)
        previous = latest.get(name)
        if previous is None or run_id > previous[0]:
            latest[name] = (
                run_id,
                str(item.get("status") or "missing"),
                str(item.get("conclusion") or ""),
            )
    return {name: (state[1], state[2]) for name, state in latest.items()}


def wait_for_required_workflows(repo: str, commit: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    endpoint = f"repos/{repo}/actions/runs?head_sha={commit}&event=push&per_page=100"
    while True:
        result = run(["gh", "api", endpoint])
        if result.returncode != 0:
            raise StableReleaseError(result.stderr.strip() or "could not query workflow runs")
        states = latest_required_workflow_states(json.loads(result.stdout), commit)
        failures = {
            name: conclusion
            for name, (status, conclusion) in states.items()
            if status == "completed" and conclusion != "success"
        }
        if failures:
            detail = ", ".join(f"{name}={value}" for name, value in sorted(failures.items()))
            raise StableReleaseError(f"required workflow failed for {commit}: {detail}")
        if all(states.get(name) == ("completed", "success") for name in REQUIRED_WORKFLOWS):
            return
        if time.monotonic() >= deadline:
            waiting = ", ".join(
                f"{name}={states.get(name, ('missing', ''))[0]}" for name in REQUIRED_WORKFLOWS
            )
            raise StableReleaseError(f"timed out waiting for release workflows: {waiting}")
        time.sleep(20)


def verify_npm(identity: ReleaseIdentity, commit: str) -> None:
    result = run(["npm", "view", f"openmates@{identity.version}", "gitHead", "--json"])
    if result.returncode != 0:
        raise StableReleaseError(f"npm package openmates@{identity.version} is unavailable")
    try:
        git_head = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise StableReleaseError("npm returned invalid gitHead metadata") from exc
    if git_head != commit:
        raise StableReleaseError(
            f"npm openmates@{identity.version} points to {git_head}, expected {commit}"
        )


def verify_pypi(identity: ReleaseIdentity, opener: Callable[..., Any] = urllib.request.urlopen) -> None:
    url = f"https://pypi.org/pypi/openmates/{identity.version}/json"
    try:
        with opener(url, timeout=30) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise StableReleaseError(f"PyPI package openmates=={identity.version} is unavailable") from exc
    if payload.get("info", {}).get("version") != identity.version:
        raise StableReleaseError(f"PyPI returned inconsistent metadata for {identity.version}")


def verify_versioned_images(identity: ReleaseIdentity, commit: str) -> None:
    for image in STABLE_IMAGES:
        versioned = f"ghcr.io/glowingkitty/{image}:{identity.tag}"
        immutable = f"ghcr.io/glowingkitty/{image}:sha-{commit}"
        versioned_result = run(
            ["docker", "buildx", "imagetools", "inspect", "--raw", versioned]
        )
        immutable_result = run(
            ["docker", "buildx", "imagetools", "inspect", "--raw", immutable]
        )
        if versioned_result.returncode != 0:
            raise StableReleaseError(f"versioned image is unavailable: {versioned}")
        if immutable_result.returncode != 0:
            raise StableReleaseError(f"commit image is unavailable: {immutable}")
        if versioned_result.stdout != immutable_result.stdout:
            raise StableReleaseError(
                f"versioned image does not match release commit: {versioned}"
            )


def ensure_annotated_tag(repo: str, identity: ReleaseIdentity, commit: str) -> None:
    existing = run(["gh", "api", f"repos/{repo}/git/ref/tags/{identity.tag}"])
    if existing.returncode == 0:
        try:
            target = json.loads(existing.stdout).get("object", {})
        except json.JSONDecodeError as exc:
            raise StableReleaseError(f"GitHub returned invalid metadata for {identity.tag}") from exc
        resolved = str(target.get("sha") or "")
        if target.get("type") == "tag":
            tag_object = run([
                "gh", "api", f"repos/{repo}/git/tags/{resolved}", "--jq", ".object.sha",
            ])
            if tag_object.returncode != 0:
                raise StableReleaseError(
                    tag_object.stderr.strip() or f"could not resolve {identity.tag}"
                )
            resolved = tag_object.stdout.strip()
        if resolved != commit:
            raise StableReleaseError(f"{identity.tag} does not point to {commit}")
        return
    if "HTTP 404" not in existing.stderr and "Not Found" not in existing.stderr:
        raise StableReleaseError(existing.stderr.strip() or f"could not query {identity.tag}")
    created = run([
        "gh", "api", "--method", "POST", f"repos/{repo}/git/tags",
        "-f", f"tag={identity.tag}",
        "-f", f"message=OpenMates {identity.tag}",
        "-f", f"object={commit}",
        "-f", "type=commit",
        "--jq", ".sha",
    ])
    if created.returncode != 0 or not created.stdout.strip():
        raise StableReleaseError(created.stderr.strip() or f"could not create {identity.tag}")
    ref = run(
        [
            "gh", "api", "--method", "POST", f"repos/{repo}/git/refs",
            "-f", f"ref=refs/tags/{identity.tag}",
            "-f", f"sha={created.stdout.strip()}",
        ]
    )
    if ref.returncode != 0:
        raise StableReleaseError(ref.stderr.strip() or f"could not publish {identity.tag}")


def release_notes(identity: ReleaseIdentity, commit: str) -> str:
    return (
        f"## {identity.product_line}\n\n"
        "This release is the verified stable artifact set from the OpenMates main branch. "
        "The CLI, Python SDK, and self-hosted images were published from the same commit.\n\n"
        "## Install\n\n"
        f"- CLI: `npm install -g openmates@{identity.version}`\n"
        f"- Python SDK: `pip install openmates=={identity.version}`\n"
        "- Self-hosted server: `openmates server update --channel stable`\n\n"
        "## Source\n\n"
        f"- Commit: `{commit}`\n"
    )


def publish_github_release(repo: str, identity: ReleaseIdentity, commit: str) -> None:
    ensure_annotated_tag(repo, identity, commit)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md", delete=False) as file:
        notes_path = Path(file.name)
        file.write(release_notes(identity, commit))
    try:
        existing = run([
            "gh", "release", "view", identity.tag, "--repo", repo,
            "--json", "isDraft,url",
        ])
        if existing.returncode == 0:
            metadata = json.loads(existing.stdout)
            if metadata.get("isDraft") is not True:
                print(metadata.get("url") or identity.tag)
                return
            command = [
                "gh", "release", "edit", identity.tag,
                "--repo", repo,
                "--target", commit,
                "--title", f"{identity.product_line}: verified stable artifacts",
                "--notes-file", str(notes_path),
                "--draft=false",
                "--prerelease",
            ]
        else:
            command = [
                "gh", "release", "create", identity.tag,
                "--repo", repo,
                "--verify-tag",
                "--target", commit,
                "--title", f"{identity.product_line}: verified stable artifacts",
                "--notes-file", str(notes_path),
                "--prerelease",
            ]
        result = run(command)
        if result.returncode != 0:
            raise StableReleaseError(result.stderr.strip() or f"could not publish {identity.tag}")
        print(result.stdout.strip())
    finally:
        notes_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--wait-seconds", type=int, default=2400)
    parser.add_argument("--skip-workflow-gate", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not COMMIT_RE.fullmatch(args.commit):
        print("FAIL --commit must be a full 40-character SHA", flush=True)
        return 1
    if not REPO_RE.fullmatch(args.repo):
        print("FAIL --repo must be in owner/name form", flush=True)
        return 1
    try:
        identity = load_release_identity()
        if not args.skip_workflow_gate:
            wait_for_required_workflows(args.repo, args.commit, args.wait_seconds)
        verify_npm(identity, args.commit)
        verify_pypi(identity)
        verify_versioned_images(identity, args.commit)
        if not args.apply:
            print(f"READY {identity.tag} at {args.commit}")
            return 0
        publish_github_release(args.repo, identity, args.commit)
    except StableReleaseError as exc:
        print(f"FAIL {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
