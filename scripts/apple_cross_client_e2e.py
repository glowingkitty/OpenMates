#!/usr/bin/env python3
"""Run credential-free cross-client chat E2E stages with opaque manifests.

The caller configures each stage command. This runner only passes a fresh run ID
and temporary artifact directory, validates stage manifests, and removes those
artifacts on completion or failure. It never reads, logs, or stores credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import subprocess
import tempfile
from pathlib import Path


STAGES = ("web-producer", "cli-producer", "apple", "web-consumer", "cli-consumer")
REQUIRED_MANIFESTS = {
    "web-producer": ("web-producer",), "cli-producer": ("cli-producer",),
    "apple": ("apple-consumer", "apple-producer"), "web-consumer": ("web-consumer",),
    "cli-consumer": ("cli-consumer",),
}


class ControlPlaneError(RuntimeError):
    """A stage did not create a valid opaque run manifest."""


def manifest_path(directory: Path, run_id: str, name: str) -> Path:
    return directory / f"apple-cross-client-{run_id}-{name}.json"


def validate_manifest(directory: Path, run_id: str, name: str) -> None:
    try:
        manifest = json.loads(manifest_path(directory, run_id, name).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ControlPlaneError(f"missing or invalid {name} manifest") from error
    if manifest.get("schema_version") != 1 or manifest.get("run_id") != run_id:
        raise ControlPlaneError(f"{name} manifest has an invalid schema or run ID")
    if not isinstance(manifest.get("chat_id"), str) and name not in {"apple-consumer"}:
        raise ControlPlaneError(f"{name} manifest has no opaque chat ID")


def run_stage(command: str, environment: dict[str, str]) -> None:
    result = subprocess.run(shlex.split(command), env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise ControlPlaneError("configured cross-client stage failed")


def run(stages: dict[str, str]) -> str:
    missing = [stage for stage in STAGES if stage not in stages]
    if missing:
        raise ControlPlaneError("missing configured cross-client stage")
    run_id = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="openmates-apple-cross-client-") as raw_directory:
        directory = Path(raw_directory)
        environment = {**os.environ, "APPLE_CROSS_CLIENT_RUN_ID": run_id, "APPLE_CROSS_CLIENT_ARTIFACT_DIR": str(directory)}
        for stage in STAGES:
            run_stage(stages[stage], environment)
            for manifest_name in REQUIRED_MANIFESTS[stage]:
                validate_manifest(directory, run_id, manifest_name)
    return run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="append", default=[], metavar="NAME=COMMAND")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stages = dict(item.split("=", 1) for item in args.stage if "=" in item)
    try:
        print(json.dumps({"run_id": run(stages)}))
    except ControlPlaneError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
