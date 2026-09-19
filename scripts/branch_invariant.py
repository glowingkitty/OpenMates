#!/usr/bin/env python3
"""Audit, archive, and safely enforce OpenMates' dev/main-only branch invariant."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess

import yaml


ALLOWED = {"dev", "main"}
SHA = re.compile(r"[0-9a-f]{40}")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def local_heads(root: Path) -> dict[str, str]:
    output = git(root, "for-each-ref", "--format=%(refname:strip=2) %(objectname)", "refs/heads")
    return dict(line.split(" ", 1) for line in output.splitlines() if line)


def remote_heads(root: Path) -> dict[str, str]:
    output = git(root, "ls-remote", "--heads", "origin")
    result = {}
    for line in output.splitlines():
        sha, ref = line.split("\t", 1)
        result[ref.removeprefix("refs/heads/")] = sha
    return result


def checked_out_heads(root: Path) -> dict[str, str]:
    output = git(root, "worktree", "list", "--porcelain")
    current_path = ""
    result = {}
    for line in [*output.splitlines(), ""]:
        if line.startswith("worktree "):
            current_path = line.removeprefix("worktree ")
        elif line.startswith("branch refs/heads/"):
            result[line.removeprefix("branch refs/heads/")] = current_path
    return result


def code_violations(root: Path) -> list[str]:
    violations = []
    source = (root / "scripts/ci_source.py").read_text()
    workflow = (root / ".github/workflows/advance-dev-version.yml").read_text()
    dependabot = yaml.safe_load((root / ".github/dependabot.yml").read_text())
    if "refs/heads/codex/ci" in source or re.search(r"git\([^\n]+[\"']push[\"']", source):
        violations.append("scripts/ci_source.py can publish a Git branch")
    if "gh pr create" in workflow or "automation/advance-dev" in workflow or 'HEAD:"$branch"' in workflow:
        violations.append("advance-dev-version.yml can create an intermediate branch")
    if "git push origin HEAD:dev" not in workflow:
        violations.append("advance-dev-version.yml does not target dev directly")
    if "ssh-key: ${{ secrets.VERSION_BUMP_DEPLOY_KEY }}" not in workflow:
        violations.append("advance-dev-version.yml lacks its dedicated protected-dev credential")
    if "secrets.GITHUB_TOKEN" in workflow:
        violations.append("advance-dev-version.yml uses the ordinary Actions token for protected-dev writes")
    if any(entry.get("open-pull-requests-limit") != 0 for entry in dependabot.get("updates", [])):
        violations.append("Dependabot version updates can create pull-request branches")
    return violations


def audit(root: Path, *, include_remote: bool = True) -> dict:
    local = local_heads(root)
    remote = remote_heads(root) if include_remote else {}
    return {
        "ok": set(local) <= ALLOWED and (not include_remote or set(remote) <= ALLOWED) and not code_violations(root),
        "allowed": sorted(ALLOWED),
        "local": local,
        "remote": remote,
        "extra_local": {name: sha for name, sha in local.items() if name not in ALLOWED},
        "extra_remote": {name: sha for name, sha in remote.items() if name not in ALLOWED},
        "code_violations": code_violations(root),
    }


def archive(root: Path, destination: Path) -> dict:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    subprocess.run(
        ["git", "fetch", "--no-tags", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"],
        cwd=root,
        check=True,
    )
    local = local_heads(root)
    remote = remote_heads(root)
    refs = [f"refs/heads/{name}" for name in sorted(local)]
    refs.extend(f"refs/remotes/origin/{name}" for name in sorted(remote))
    bundle = destination / "all-branches.bundle"
    subprocess.run(["git", "bundle", "create", str(bundle), *refs], cwd=root, check=True)
    verification = subprocess.run(
        ["git", "bundle", "verify", str(bundle)], cwd=root, text=True, capture_output=True, check=True
    )
    manifest = {
        "schema": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repository": git(root, "remote", "get-url", "origin"),
        "bundle": str(bundle),
        "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "bundle_verification": verification.stderr.strip() or verification.stdout.strip(),
        "local_heads": local,
        "remote_heads": remote,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_path.chmod(0o600)
    bundle.chmod(0o600)
    return {**manifest, "manifest": str(manifest_path)}


def cleanup(root: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    bundle = Path(manifest["bundle"])
    if not bundle.is_file() or hashlib.sha256(bundle.read_bytes()).hexdigest() != manifest["bundle_sha256"]:
        raise RuntimeError("Branch backup bundle is missing or does not match its manifest")
    subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=root, check=True, capture_output=True)
    current_local = local_heads(root)
    current_remote = remote_heads(root)
    expected_local = manifest["local_heads"]
    expected_remote = manifest["remote_heads"]
    extra_local = {name: sha for name, sha in current_local.items() if name not in ALLOWED}
    extra_remote = {name: sha for name, sha in current_remote.items() if name not in ALLOWED}
    if extra_local != {name: sha for name, sha in expected_local.items() if name not in ALLOWED}:
        raise RuntimeError("Local branch inventory changed after archival")
    expected_extra_remote = {name: sha for name, sha in expected_remote.items() if name not in ALLOWED}
    changed_remote = {
        name: sha
        for name, sha in extra_remote.items()
        if expected_extra_remote.get(name) != sha
    }
    if changed_remote:
        raise RuntimeError("Remote branch inventory changed after archival")
    already_absent_remote = sorted(set(expected_extra_remote) - set(extra_remote))
    occupied = {name: path for name, path in checked_out_heads(root).items() if name in extra_local}
    if occupied:
        raise RuntimeError("Extra branches remain checked out: " + json.dumps(occupied, sort_keys=True))
    if extra_remote:
        command = ["git", "push", "--atomic", "origin"]
        for name, sha in sorted(extra_remote.items()):
            command.extend([f"--force-with-lease=refs/heads/{name}:{sha}", f":refs/heads/{name}"])
        subprocess.run(command, cwd=root, check=True)
    for name, sha in sorted(extra_local.items()):
        subprocess.run(
            ["git", "update-ref", "-d", f"refs/heads/{name}", sha], cwd=root, check=True
        )
    final = audit(root)
    if not final["ok"]:
        raise RuntimeError("Two-branch invariant is still violated: " + json.dumps(final, sort_keys=True))
    return {
        "deleted_local": sorted(extra_local),
        "deleted_remote": sorted(extra_remote),
        "already_absent_remote": already_absent_remote,
        "final": final,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    sub = parser.add_subparsers(dest="action", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--local-only", action="store_true")
    archive_parser = sub.add_parser("archive")
    archive_parser.add_argument("--destination", type=Path, required=True)
    cleanup_parser = sub.add_parser("cleanup")
    cleanup_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.action == "audit":
        result = audit(root, include_remote=not args.local_only)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.action == "archive":
        print(json.dumps(archive(root, args.destination), indent=2, sort_keys=True))
        return 0
    print(json.dumps(cleanup(root, args.manifest), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
