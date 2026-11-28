"""Authorize a protected CI subject and materialize trusted tooling without checkout filters."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SHA = re.compile(r"[0-9a-f]{40}")


def authorize(source: str, approved: str, ref: str, workflow_sha: str) -> None:
    """The protected dev commit is already reviewed. For isolated changes, a
    maintainer appends the reviewed ci-source SHA to the target environment's
    SCOPED_INFERENCE_REVIEWED_SOURCES JSON list from the development host.
    The dispatched job has read-only access to that list.
    """
    if ref != "refs/heads/dev" or not SHA.fullmatch(source) or not SHA.fullmatch(workflow_sha):
        raise ValueError("Invalid scoped CI source or branch")
    if source == workflow_sha:
        return
    entries = json.loads(approved or "[]")
    if (not isinstance(entries, list) or not 1 <= len(entries) <= 128
            or not all(isinstance(item, str) and SHA.fullmatch(item) for item in entries)
            or source not in entries):
        raise ValueError("Source has no protected environment approval")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["/usr/bin/git", "--no-replace-objects", "-C", str(repo), *args],
        env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
        stderr=subprocess.DEVNULL,
    )


def materialize(repo: Path, expected: str, temp: Path) -> Path:
    if not SHA.fullmatch(expected) or git(repo, "rev-parse", "HEAD").decode().strip() != expected:
        raise ValueError("Unexpected trusted workflow commit")
    root = Path(tempfile.mkdtemp(prefix="scoped-ci-tooling-", dir=temp))
    # Helpers, the allowlisted test manifest, and the workflow configuration all
    # originate in the executing Git commit. No worktree files or Python caches
    # enter the credentialed process.
    entries = git(repo, "ls-tree", "-rz", expected, "--", "scripts", ".github/workflows").split(b"\0")
    objects = []
    for entry in filter(None, entries):
        metadata, name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = Path(os.fsdecode(name))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid trusted tooling path")
        if mode not in {"100644", "100755"} or kind != "blob":
            if path.suffix == ".py":
                raise ValueError("Python tooling must be a regular Git blob")
            continue
        if not SHA.fullmatch(oid):
            raise ValueError("Invalid trusted tooling blob")
        objects.append((oid, root / path, mode))
    request = "".join(oid + "\n" for oid, _, _ in objects).encode("ascii")
    process = subprocess.run(
        ["/usr/bin/git", "--no-replace-objects", "-C", str(repo), "cat-file", "--batch"],
        input=request, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
        env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )
    from io import BytesIO
    data = BytesIO(process.stdout)
    for oid, path, mode in objects:
        actual, kind, length = data.readline().decode("ascii").split()
        size = int(length)
        if actual != oid or kind != "blob" or not 0 <= size <= 64 * 1024 * 1024:
            raise ValueError("Unexpected trusted tooling object")
        content = data.read(size)
        if (len(content) != size or data.read(1) != b"\n"
                or hashlib.sha1(b"blob " + str(size).encode() + b"\0" + content).hexdigest() != oid):
            raise ValueError("Trusted tooling content mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(content)
        path.chmod(0o700 if mode == "100755" else 0o600)
    if data.read() or not (root / "scripts/ci_environment.py").is_file():
        raise ValueError("Incomplete trusted CI tooling")
    return root


if __name__ == "__main__":
    authorize(os.environ["SCOPED_SUBJECT"], os.environ["SCOPED_APPROVED_SOURCES"],
              os.environ["GITHUB_REF"], os.environ["GITHUB_SHA"])
    if sys.argv[1:] == ["materialize"]:
        root = materialize(Path.cwd(), os.environ["GITHUB_SHA"], Path(os.environ["RUNNER_TEMP"]))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"root={root}\n")
    elif sys.argv[1:] != ["authorize"]:
        raise SystemExit("Unknown scoped CI operation")
