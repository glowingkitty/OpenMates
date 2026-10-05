"""Inspect actual API serving processes and publish a short deployment inventory.

The server CLI runs inspection in every API container, then publishes the whole
cohort. Output contains only source and process identities, never environment
values, credentials, command lines, or user data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid
from typing import Any

INVENTORY_KEY = "storage:archive_client_guard:deployment:v1"
INSPECTION_SCHEMA = "agentic-storage-api-process-inventory-v1"
SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
INSTANCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def serving_process_ids(processes: dict[int, dict[str, Any]]) -> list[int]:
    roots = []
    for pid, process in processes.items():
        argv = process["argv"]
        if ("backend.core.api.main:app" in argv
                and any(Path(arg).name == "uvicorn" for arg in argv)):
            roots.append(pid)
    if not roots:
        raise ValueError("api_process_inventory_unavailable")
    ids = []
    for pid in roots:
        process = processes[pid]
        argv = process["argv"]
        raw_workers = process.get("web_concurrency", "1") or "1"
        for index, arg in enumerate(argv):
            if arg == "--workers":
                raw_workers = argv[index + 1] if index + 1 < len(argv) else ""
            elif arg.startswith("--workers="):
                raw_workers = arg.partition("=")[2]
        if not str(raw_workers).isdecimal() or not 1 <= int(raw_workers) <= 128:
            raise ValueError("api_worker_count_unverified")
        workers = int(raw_workers)
        children = [child_pid for child_pid, child in processes.items()
                    if child["parent"] == pid and any("spawn_main" in arg for arg in child["argv"])
                    and "--multiprocessing-fork" in child["argv"]]
        if workers == 1:
            if children:
                raise ValueError("unexpected_api_worker_process")
            ids.append(pid)
        elif len(children) != workers:
            raise ValueError("api_worker_inventory_incomplete")
        else:
            ids.extend(children)
    if not 1 <= len(ids) <= 128 or len(set(ids)) != len(ids):
        raise ValueError("api_process_inventory_ambiguous")
    return sorted(ids)


def inspect_api_processes(*, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    source = os.getenv("BUILD_COMMIT_SHA") or os.getenv("OPENMATES_BUILD_SHA") or ""
    if not SOURCE_RE.fullmatch(source):
        raise ValueError("api_source_provenance_unavailable")
    processes = {}
    for directory in proc_root.iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            argv = directory.joinpath("cmdline").read_bytes().decode().rstrip("\0").split("\0")
            parent = next(int(line.partition(":")[2].strip()) for line in directory.joinpath("status").read_text().splitlines() if line.startswith("PPid:"))
            # Inspect only the worker-count setting. Never return process env.
            web = next((entry.partition("=")[2] for entry in directory.joinpath("environ").read_bytes().decode().split("\0") if entry.startswith("WEB_CONCURRENCY=")), "1")
        except (OSError, UnicodeError, StopIteration, ValueError):
            continue
        processes[int(directory.name)] = {"argv": argv, "parent": parent, "web_concurrency": web}
    ids = serving_process_ids(processes)
    hostname = socket.gethostname()
    instance_ids = [f"{hostname}:{pid}" for pid in ids]
    if any(not INSTANCE_RE.fullmatch(instance) for instance in instance_ids):
        raise ValueError("api_instance_identity_invalid")
    return {"schema": INSPECTION_SCHEMA, "source_commit": source, "instance_ids": instance_ids}


def validate_cohort(cohort: Any, *, now: int | None = None) -> dict[str, Any]:
    if not isinstance(cohort, list) or not 1 <= len(cohort) <= 128:
        raise ValueError("api_deployment_inventory_incomplete")
    sources = {row.get("source_commit") for row in cohort if isinstance(row, dict)}
    if len(sources) != 1 or not SOURCE_RE.fullmatch(next(iter(sources), "")):
        raise ValueError("api_deployment_source_mismatch")
    ids = []
    for row in cohort:
        if (not isinstance(row, dict) or set(row) != {"schema", "source_commit", "instance_ids"}
                or row.get("schema") != INSPECTION_SCHEMA
                or not isinstance(row.get("instance_ids"), list) or not row["instance_ids"]):
            raise ValueError("api_deployment_inspection_invalid")
        ids.extend(row["instance_ids"])
    if (not 1 <= len(ids) <= 128 or any(not isinstance(item, str) or not INSTANCE_RE.fullmatch(item) for item in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("api_deployment_inventory_ambiguous")
    current = int(time.time()) if now is None else now
    return {"inventory_id": str(uuid.uuid4()), "source_commit": next(iter(sources)), "instance_ids": sorted(ids),
            "observed_at": current, "expires_at": current + 180}


async def publish_inventory(cohort: Any) -> dict[str, Any]:
    from backend.core.api.app.tasks.base_task import BaseServiceTask
    from backend.core.api.app.services.storage_archive_client_compatibility import _redis
    inventory = validate_cohort(cohort)
    installed = os.getenv("BUILD_COMMIT_SHA") or os.getenv("OPENMATES_BUILD_SHA") or ""
    if inventory["source_commit"] != installed:
        raise ValueError("api_deployment_publisher_source_mismatch")
    task = BaseServiceTask()
    try:
        await task.initialize_core_services()
        client = await _redis(task.directus_service)
        existing_raw = await client.get(INVENTORY_KEY)
        try:
            existing = json.loads(existing_raw) if existing_raw else {}
            existing_id = str(uuid.UUID(existing.get("inventory_id", ""), version=4))
            if (existing_id == existing.get("inventory_id")
                    and existing.get("source_commit") == inventory["source_commit"]
                    and existing.get("instance_ids") == inventory["instance_ids"]
                    and type(existing.get("expires_at")) is int
                    and existing["expires_at"] > inventory["observed_at"]):
                inventory["inventory_id"] = existing_id
        except (ValueError, TypeError, AttributeError):
            pass
        await client.set(INVENTORY_KEY, json.dumps(inventory, sort_keys=True, separators=(",", ":")), ex=180)
    finally:
        await task.cleanup_services()
    return {"status": "published", "source_commit": inventory["source_commit"], "api_processes": len(inventory["instance_ids"]), "expires_in_seconds": 180}


def refresh_host_inventory(compose_prefix: list[str]) -> dict[str, Any]:
    """Read the actual whole API cohort before replacing its shared inventory."""
    result = subprocess.run(["docker", *compose_prefix, "ps", "--all", "-q", "api"],
                            capture_output=True, text=True, timeout=15, check=True)
    containers = result.stdout.split()
    if not 1 <= len(containers) <= 128 or len(set(containers)) != len(containers):
        raise ValueError("api_container_inventory_unavailable")
    cohort = []
    for container in containers:
        if not re.fullmatch(r"[0-9a-f]{12,64}", container):
            raise ValueError("api_container_identity_invalid")
        result = subprocess.run(["docker", "exec", container, "python", "/app/scripts/storage_runtime_inventory.py", "inspect"],
                                capture_output=True, text=True, timeout=15, check=True)
        if len(result.stdout) > 65536:
            raise ValueError("api_process_inventory_exceeds_bound")
        cohort.append(json.loads(result.stdout))
    validate_cohort(cohort)
    result = subprocess.run(["docker", "exec", "-i", containers[0], "python", "/app/scripts/storage_runtime_inventory.py", "publish"],
                            input=json.dumps(cohort), capture_output=True, text=True, timeout=45, check=True)
    output = json.loads(result.stdout)
    if not isinstance(output, dict) or output.get("status") != "published":
        raise ValueError("api_deployment_publish_unverified")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "publish", "refresh"))
    parser.add_argument("--compose-file", type=Path)
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == "refresh":
            if args.compose_file is None:
                parser.error("refresh requires --compose-file")
            while True:
                try:
                    output = refresh_host_inventory(["compose", "-f", str(args.compose_file)])
                except Exception:
                    output = {"status": "paused", "reason": "runtime_inventory_unverified"}
                if not args.loop:
                    break
                print(json.dumps(output, sort_keys=True), flush=True)
                time.sleep(60)
        elif args.operation == "inspect":
            output = inspect_api_processes()
        else:
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise ValueError("api_deployment_inventory_exceeds_bound")
            output = asyncio.run(publish_inventory(json.loads(raw)))
    except Exception:
        output = {"status": "paused", "reason": "runtime_inventory_unverified"}
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
