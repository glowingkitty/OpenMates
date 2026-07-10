#!/usr/bin/env python3
"""
Validate and render OpenMates' tag-backed milestone release catalog.

The catalog records only immutable source commits and externally verifiable
distribution artifacts. It intentionally does not rebuild historical binaries
or publish a GitHub Release without an existing annotated tag.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "docs" / "releases" / "milestones.yml"
TAG_PATTERN = re.compile(r"^v\d+\.\d+\.0-alpha$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
UNAVAILABLE = "unavailable"


class ReleaseCatalogError(ValueError):
    """Raised when release provenance is incomplete or inconsistent."""


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseCatalogError(f"catalog does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise ReleaseCatalogError(f"catalog is not valid YAML: {path}") from exc
    if not isinstance(loaded, dict):
        raise ReleaseCatalogError("catalog must be a mapping")
    return loaded


def _required_string(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ReleaseCatalogError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_artifact(name: str, artifact: Any) -> None:
    if not isinstance(artifact, dict):
        raise ReleaseCatalogError(f"{name} artifact must be a mapping")
    if artifact.get("status") == UNAVAILABLE:
        if set(artifact) != {"status"}:
            raise ReleaseCatalogError(f"{name} unavailable artifact cannot include install metadata")
        return
    if name in {"npm", "pypi"}:
        _required_string(artifact, "version")
        if name == "npm":
            git_head = _required_string(artifact, "git_head")
            if not COMMIT_PATTERN.fullmatch(git_head):
                raise ReleaseCatalogError("npm git_head must be an immutable 40-character SHA")
        return
    if name == "ghcr":
        _required_string(artifact, "tag")
        digest = _required_string(artifact, "digest")
        if not DIGEST_PATTERN.fullmatch(digest):
            raise ReleaseCatalogError("ghcr digest must be an immutable sha256 digest")
        revision = _required_string(artifact, "revision")
        if not COMMIT_PATTERN.fullmatch(revision):
            raise ReleaseCatalogError("ghcr revision must be an immutable 40-character SHA")
        return
    raise ReleaseCatalogError(f"unsupported artifact: {name}")


def validate_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    if catalog.get("schema_version") != 1:
        raise ReleaseCatalogError("catalog schema_version must be 1")
    milestones = catalog.get("milestones")
    if not isinstance(milestones, list) or not milestones:
        raise ReleaseCatalogError("catalog milestones must be a non-empty list")

    tags: set[str] = set()
    validated: list[dict[str, Any]] = []
    for milestone in milestones:
        if not isinstance(milestone, dict):
            raise ReleaseCatalogError("each milestone must be a mapping")
        tag = _required_string(milestone, "tag")
        if not TAG_PATTERN.fullmatch(tag):
            raise ReleaseCatalogError(f"tag must use the milestone alpha convention: {tag}")
        if tag in tags:
            raise ReleaseCatalogError(f"duplicate milestone tag: {tag}")
        tags.add(tag)

        commit = _required_string(milestone, "commit")
        if not COMMIT_PATTERN.fullmatch(commit):
            raise ReleaseCatalogError(f"commit must be an immutable 40-character SHA: {commit}")
        _required_string(milestone, "title")
        _required_string(milestone, "original_release_window")
        if milestone.get("prerelease") is not True:
            raise ReleaseCatalogError(f"{tag} must be a prerelease")
        if milestone.get("historical_backfill") is not True:
            raise ReleaseCatalogError(f"{tag} must declare historical_backfill")

        artifacts = milestone.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ReleaseCatalogError(f"{tag} artifacts must be a mapping")
        for name in ("npm", "pypi", "ghcr"):
            if name not in artifacts:
                raise ReleaseCatalogError(f"{tag} must declare {name} artifact availability")
            _validate_artifact(name, artifacts[name])
        npm = artifacts["npm"]
        if "git_head" in npm and npm["git_head"] != commit:
            raise ReleaseCatalogError(f"{tag} npm git_head must match the milestone commit")
        ghcr = artifacts["ghcr"]
        if "revision" in ghcr and ghcr["revision"] != commit:
            raise ReleaseCatalogError(f"{tag} GHCR revision must match the milestone commit")
        validated.append(milestone)
    return validated


def render_release_notes(milestone: dict[str, Any], overview: str) -> str:
    artifacts = milestone["artifacts"]
    lines = [
        "> Historical backfill: reconstructed from immutable git and registry records.",
        f"> Original release window: {milestone['original_release_window']}. GitHub publication occurs after maintainer review.",
        "",
        overview.strip(),
        "",
        "## Source",
        f"- Commit: `{milestone['commit']}`",
        f"- GitHub provides source `.zip` and `.tar.gz` downloads for tag `{milestone['tag']}`.",
        "",
        "## Available Installations",
    ]
    npm = artifacts["npm"]
    lines.append(
        f"- npm: `npm install -g openmates@{npm['version']}`"
        if "version" in npm
        else "- npm: unavailable for this historical milestone."
    )
    pypi = artifacts["pypi"]
    lines.append(
        f"- PyPI: `pip install openmates=={pypi['version']}`"
        if "version" in pypi
        else "- PyPI: unavailable for this historical milestone."
    )
    ghcr = artifacts["ghcr"]
    lines.append(
        f"- Self-hosted images: `ghcr.io/glowingkitty/openmates-api:{ghcr['tag']}` (`{ghcr['digest']}`)."
        if "tag" in ghcr
        else "- Self-hosted images: unavailable for this historical milestone."
    )
    return "\n".join(lines) + "\n"


def build_draft_command(milestone: dict[str, Any], notes_path: Path) -> list[str]:
    return [
        "gh",
        "release",
        "create",
        milestone["tag"],
        "--verify-tag",
        "--target",
        milestone["commit"],
        "--title",
        milestone["title"],
        "--notes-file",
        str(notes_path),
        "--draft",
        "--prerelease",
    ]


def build_update_command(milestone: dict[str, Any], notes_path: Path) -> list[str]:
    return [
        "gh",
        "release",
        "edit",
        milestone["tag"],
        "--verify-tag",
        "--target",
        milestone["commit"],
        "--title",
        milestone["title"],
        "--notes-file",
        str(notes_path),
        "--draft",
        "--prerelease",
    ]


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)


def annotated_tag_commit(tag: str) -> str:
    tag_type = run(["git", "cat-file", "-t", tag])
    if tag_type.returncode != 0 or tag_type.stdout.strip() != "tag":
        raise ReleaseCatalogError(f"{tag} must exist as an annotated tag")
    target = run(["git", "rev-list", "-n", "1", tag])
    if target.returncode != 0:
        raise ReleaseCatalogError(f"could not resolve tag target: {tag}")
    return target.stdout.strip()


def audit_milestone(milestone: dict[str, Any]) -> None:
    tag = milestone["tag"]
    target = annotated_tag_commit(tag)
    if target != milestone["commit"]:
        raise ReleaseCatalogError(f"{tag} resolves to {target}, not catalog commit {milestone['commit']}")
    audit_artifacts(milestone)


def audit_artifacts(milestone: dict[str, Any]) -> None:
    artifacts = milestone["artifacts"]
    npm = artifacts["npm"]
    if "version" in npm:
        result = run(["npm", "view", f"openmates@{npm['version']}", "gitHead", "--json"])
        if result.returncode != 0:
            raise ReleaseCatalogError(f"could not query npm package {npm['version']}")
        try:
            git_head = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ReleaseCatalogError(f"npm returned invalid gitHead metadata for {npm['version']}") from exc
        if git_head != npm["git_head"]:
            raise ReleaseCatalogError(f"npm package {npm['version']} does not match its catalog git_head")

    pypi = artifacts["pypi"]
    if "version" in pypi:
        result = run([sys.executable, "-m", "pip", "index", "versions", "openmates"])
        versions_match = re.search(r"Available versions:\s*(.+)", result.stdout)
        versions = {version.strip() for version in versions_match.group(1).split(",")} if versions_match else set()
        if result.returncode != 0 or pypi["version"] not in versions:
            raise ReleaseCatalogError(f"PyPI package openmates=={pypi['version']} is unavailable")

    ghcr = artifacts["ghcr"]
    if "tag" in ghcr:
        image = f"ghcr.io/glowingkitty/openmates-api:{ghcr['tag']}"
        result = run(["docker", "buildx", "imagetools", "inspect", image])
        if result.returncode != 0 or ghcr["digest"] not in result.stdout:
            raise ReleaseCatalogError(f"GHCR image digest does not verify for {image}")
        pulled_image = f"{image}@{ghcr['digest']}"
        pull = run(["docker", "pull", pulled_image])
        if pull.returncode != 0:
            raise ReleaseCatalogError(f"could not pull GHCR image digest for {image}")
        revision = run(
            [
                "docker",
                "image",
                "inspect",
                pulled_image,
                "--format",
                "{{ index .Config.Labels \"org.opencontainers.image.revision\" }}",
            ]
        )
        if revision.returncode != 0 or revision.stdout.strip() != ghcr["revision"]:
            raise ReleaseCatalogError(f"GHCR image revision does not verify for {image}")


def create_tag(milestone: dict[str, Any], *, push: bool) -> None:
    tag = milestone["tag"]
    existing = run(["git", "rev-parse", "--verify", "--quiet", tag])
    if existing.returncode == 0:
        audit_milestone(milestone)
        return
    created = run(
        [
            "git",
            "tag",
            "-a",
            tag,
            milestone["commit"],
            "-m",
            f"OpenMates {tag} historical milestone",
        ]
    )
    if created.returncode != 0:
        raise ReleaseCatalogError(created.stderr.strip() or f"could not create tag: {tag}")
    if push:
        pushed = run(["git", "push", "origin", tag])
        if pushed.returncode != 0:
            raise ReleaseCatalogError(pushed.stderr.strip() or f"could not push tag: {tag}")


def create_draft(milestone: dict[str, Any], *, apply: bool) -> None:
    audit_milestone(milestone)
    notes = render_release_notes(milestone, milestone["overview"])
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md", delete=False) as file:
        notes_path = Path(file.name)
        file.write(notes)
    try:
        existing = run(["gh", "release", "view", milestone["tag"], "--json", "isDraft"])
        if existing.returncode == 0:
            try:
                existing_release = json.loads(existing.stdout)
            except json.JSONDecodeError as exc:
                raise ReleaseCatalogError(f"GitHub returned invalid release metadata for {milestone['tag']}") from exc
            if existing_release.get("isDraft") is not True:
                raise ReleaseCatalogError(f"refusing to modify published release: {milestone['tag']}")
            command = build_update_command(milestone, notes_path)
        else:
            command = build_draft_command(milestone, notes_path)
        if not apply:
            print(" ".join(command))
            return
        result = run(command)
        if result.returncode != 0:
            raise ReleaseCatalogError(result.stderr.strip() or f"could not create draft: {milestone['tag']}")
        print(result.stdout.strip())
    finally:
        notes_path.unlink(missing_ok=True)


def select_milestones(milestones: list[dict[str, Any]], tag: str | None) -> list[dict[str, Any]]:
    if tag is None:
        return milestones
    selected = [milestone for milestone in milestones if milestone["tag"] == tag]
    if not selected:
        raise ReleaseCatalogError(f"unknown milestone tag: {tag}")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and draft tag-backed milestone releases.")
    parser.add_argument("command", choices=("audit", "create-tags", "draft", "render"))
    parser.add_argument("--tag", help="Operate on one catalog milestone tag")
    parser.add_argument("--push", action="store_true", help="Push newly created annotated tags to origin")
    parser.add_argument("--apply", action="store_true", help="Create GitHub Release drafts instead of printing commands")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    milestones = select_milestones(validate_catalog(load_catalog()), args.tag)
    try:
        if args.command == "audit":
            for milestone in milestones:
                audit_milestone(milestone)
                print(f"PASS {milestone['tag']}")
        elif args.command == "create-tags":
            for milestone in milestones:
                create_tag(milestone, push=args.push)
                print(f"READY {milestone['tag']}")
        elif args.command == "draft":
            for milestone in milestones:
                create_draft(milestone, apply=args.apply)
        else:
            for milestone in milestones:
                print(render_release_notes(milestone, milestone["overview"]), end="")
    except ReleaseCatalogError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
