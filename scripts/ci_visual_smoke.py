"""Bounded component-preview screenshot capture on the isolated GitHub runner.

Runs the candidate's original visual-smoke script, retaining both viewports.
Only public default component fixtures are supported; no account or provider
credentials are accepted. Capture receipts are explicitly not visual approval.
See docs/architecture/isolated-github-tests.md for queue and source isolation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

MAX_TARGETS = 2
TARGET = re.compile(r"http://localhost:5173/dev/preview/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\?chrome=0")
VIEWPORTS = {"laptop", "mobile"}


def validate_targets(targets):
    if not 1 <= len(targets) <= MAX_TARGETS or len(set(targets)) != len(targets):
        raise ValueError("Select one or two distinct component preview URLs")
    if any(not isinstance(url, str) or len(url) > 512 or not TARGET.fullmatch(url) for url in targets):
        raise ValueError("Only localhost:5173 bare default component previews with chrome=0 are supported")


def screenshot_records(directory, targets):
    """Validate real original-script output before binding retained image bytes."""
    validate_targets(targets)
    directory = Path(directory).resolve()
    summary = json.loads((directory / "summary.json").read_text())
    expected = {(url, viewport) for url in targets for viewport in VIEWPORTS}
    records = summary.get("records", [])
    if (summary.get("method") != "playwright" or sorted(summary.get("urls", [])) != sorted(targets)
            or set(summary.get("viewports", [])) != VIEWPORTS
            or len(records) != len(expected)
            or {(r.get("url"), r.get("viewport")) for r in records} != expected):
        raise ValueError("Incomplete visual-smoke screenshot inventory")
    images = []
    for record in records:
        # Original script writes absolute runner paths; artifacts retain basenames.
        name = Path(record["screenshot"]).name
        path = directory / name
        if path.suffix != ".png" or path.is_symlink() or not path.is_file():
            raise ValueError("Missing retained visual-smoke PNG")
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid screenshot format")
        images.append({"url": record["url"], "viewport": record["viewport"],
                       "file": name, "sha256": hashlib.sha256(data).hexdigest()})
    if len({r["file"] for r in images}) != len(images):
        raise ValueError("Screenshot filename collision")
    return summary, images


def capture(targets, web, results):
    validate_targets(targets)
    directory = Path(results) / "ci-visual-smoke"
    directory.mkdir(parents=True, exist_ok=False)
    command = ["node", str(Path(web) / "scripts/visual-smoke.mjs")]
    for url in targets:
        command += ["--url", url]
    command += ["--out", str(directory.resolve())]
    result = subprocess.run(command, cwd=web, timeout=300, check=False)
    summary, images = screenshot_records(directory, targets)
    manifest = {"review_status": "pending", "account_mode": "public_component_fixture",
                "screenshots": images,
                "summary_sha256": hashlib.sha256((directory / "summary.json").read_bytes()).hexdigest()}
    (directory / "receipt.json").write_text(json.dumps(manifest, indent=2))
    failed = result.returncode or summary.get("result") != "passed"
    return [{"spec": url, "exit_code": int(bool(failed)),
             "visual_review": "pending", "capture_receipt": "ci-visual-smoke/receipt.json"} for url in targets]


def verify_capture(directory, targets):
    summary, images = screenshot_records(directory, targets)
    manifest = json.loads((Path(directory) / "receipt.json").read_text())
    if (manifest.get("review_status") != "pending"
            or manifest.get("account_mode") != "public_component_fixture"
            or manifest.get("screenshots") != images
            or manifest.get("summary_sha256") != hashlib.sha256((Path(directory) / "summary.json").read_bytes()).hexdigest()
            or summary.get("result") != "passed"):
        raise ValueError("Visual-smoke capture receipt mismatch")
    return manifest
