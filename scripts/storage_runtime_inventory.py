"""Inspect actual API serving processes and publish a short deployment inventory.

The server CLI runs inspection in every API container, then publishes the whole
cohort. Output contains only source and process identities, never environment
values, credentials, command lines, or user data.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stderr, redirect_stdout
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


DIAGNOSTIC_STAGES = frozenset({"compose", "inspect", "cohort", "publish", "bootstrap"})
DIAGNOSTIC_CLASSES = frozenset({"ValueError", "TypeError", "KeyError", "AttributeError", "ImportError",
    "ModuleNotFoundError", "RuntimeError", "CalledProcessError", "TimeoutExpired", "JSONDecodeError", "ConnectionError"})
DIAGNOSTIC_REASONS = frozenset({
    "api_process_inventory_unavailable", "api_worker_count_unverified", "unexpected_api_worker_process",
    "api_worker_inventory_incomplete", "api_process_inventory_ambiguous", "api_source_provenance_unavailable",
    "api_instance_identity_invalid", "api_deployment_inventory_incomplete", "api_deployment_source_mismatch",
    "api_deployment_inspection_invalid", "api_deployment_inventory_ambiguous",
    "api_deployment_publisher_source_mismatch", "api_container_inventory_unavailable",
    "api_container_identity_invalid", "api_process_inventory_exceeds_bound", "api_deployment_publish_unverified",
    "api_deployment_inventory_exceeds_bound", "runtime_inventory_unverified",
    "runtime_inventory_bootstrap_failed", "runtime_inventory_publish_failed",
    "runtime_inventory_json_invalid", "runtime_inventory_subprocess_failed",
})


class InventoryFailure(ValueError):
    """Content-free diagnostic envelope; raw subprocess/exception text stays private."""
    def __init__(self, diagnostic: dict[str, Any]):
        self.diagnostic = diagnostic
        super().__init__(diagnostic["reason"])


def failure_status(exc: Exception, *, stage: str, container_count: int | None = None) -> dict[str, Any]:
    if isinstance(exc, InventoryFailure):
        result = dict(exc.diagnostic)
    else:
        category = type(exc).__name__
        if category not in DIAGNOSTIC_CLASSES:
            category = "RuntimeError"
        message = str(exc)
        reason = message if isinstance(exc, ValueError) and message in DIAGNOSTIC_REASONS else (
            "runtime_inventory_json_invalid" if isinstance(exc, json.JSONDecodeError) else
            "runtime_inventory_subprocess_failed" if isinstance(exc, (subprocess.CalledProcessError, subprocess.TimeoutExpired)) else
            "runtime_inventory_bootstrap_failed" if stage == "bootstrap" else
            "runtime_inventory_publish_failed" if stage == "publish" else "runtime_inventory_unverified")
        result = {"status": "paused", "reason": reason,
                  "stage": stage if stage in DIAGNOSTIC_STAGES else "inspect", "error_class": category}
        if isinstance(exc, subprocess.CalledProcessError) and type(exc.returncode) is int and -255 <= exc.returncode <= 255:
            result["exit_code"] = exc.returncode
    if type(container_count) is int and 0 <= container_count <= 128:
        result["container_count"] = container_count
    return result


def reject_remote_status(value: Any, *, stage: str) -> None:
    if not isinstance(value, dict) or value.get("status") != "paused":
        return
    reason = value.get("reason")
    category = value.get("error_class")
    diagnostic = {"status": "paused", "reason": reason if isinstance(reason, str) and reason in DIAGNOSTIC_REASONS else "runtime_inventory_unverified",
                  "stage": value.get("stage") if isinstance(value.get("stage"), str) and value.get("stage") in DIAGNOSTIC_STAGES else stage,
                  "error_class": category if isinstance(category, str) and category in DIAGNOSTIC_CLASSES else "RuntimeError"}
    exit_code = value.get("exit_code")
    if type(exit_code) is int and -255 <= exit_code <= 255:
        diagnostic["exit_code"] = exit_code
    raise InventoryFailure(diagnostic)


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
    stage = "bootstrap"
    task = None
    failure = None
    try:
        from backend.core.api.app.tasks.base_task import BaseServiceTask
        from backend.core.api.app.services.storage_archive_client_compatibility import _redis
        stage = "cohort"
        inventory = validate_cohort(cohort)
        installed = os.getenv("BUILD_COMMIT_SHA") or os.getenv("OPENMATES_BUILD_SHA") or ""
        if inventory["source_commit"] != installed:
            raise ValueError("api_deployment_publisher_source_mismatch")
        stage = "bootstrap"
        task = BaseServiceTask()
        await task.initialize_core_services()
        stage = "publish"
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
    except Exception as exc:
        failure = InventoryFailure(failure_status(exc, stage=stage))
    finally:
        if task is not None:
            try:
                await task.cleanup_services()
            except Exception as exc:
                if failure is None:
                    failure = InventoryFailure(failure_status(exc, stage="publish"))
    if failure is not None:
        raise failure
    return {"status": "published", "source_commit": inventory["source_commit"], "api_processes": len(inventory["instance_ids"]), "expires_in_seconds": 180}


def refresh_host_inventory(compose_prefix: list[str]) -> dict[str, Any]:
    """Read the actual whole API cohort before replacing its shared inventory."""
    stage = "compose"
    container_count = None
    try:
        result = subprocess.run(["docker", *compose_prefix, "ps", "--all", "-q", "api"],
                                capture_output=True, text=True, timeout=15, check=True)
        containers = result.stdout.split()
        if not 1 <= len(containers) <= 128 or len(set(containers)) != len(containers):
            raise ValueError("api_container_inventory_unavailable")
        container_count = len(containers)
        cohort = []
        stage = "inspect"
        for container in containers:
            if not re.fullmatch(r"[0-9a-f]{12,64}", container):
                raise ValueError("api_container_identity_invalid")
            result = subprocess.run(["docker", "exec", container, "python", "/app/scripts/storage_runtime_inventory.py", "inspect"],
                                    capture_output=True, text=True, timeout=15, check=True)
            if len(result.stdout) > 65536:
                raise ValueError("api_process_inventory_exceeds_bound")
            inspection = json.loads(result.stdout)
            reject_remote_status(inspection, stage="inspect")
            cohort.append(inspection)
        stage = "cohort"
        validate_cohort(cohort)
        stage = "publish"
        result = subprocess.run(["docker", "exec", "-i", containers[0], "python", "/app/scripts/storage_runtime_inventory.py", "publish"],
                                input=json.dumps(cohort), capture_output=True, text=True, timeout=45, check=True)
        if len(result.stdout) > 65536:
            raise ValueError("api_deployment_inventory_exceeds_bound")
        output = json.loads(result.stdout)
        reject_remote_status(output, stage="publish")
        if not isinstance(output, dict) or output.get("status") != "published":
            raise ValueError("api_deployment_publish_unverified")
        return output
    except Exception as exc:
        raise InventoryFailure(failure_status(exc, stage=stage, container_count=container_count)) from None


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
                except Exception as exc:
                    output = failure_status(exc, stage="compose")
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
            cohort = json.loads(raw)
            # Backend imports and initialization can install stdout loggers.
            # This subprocess owns one JSON wire response; discard service
            # output without retaining private bytes or accepting log fragments.
            with open(os.devnull, "w", encoding="utf-8") as service_output:
                with redirect_stdout(service_output), redirect_stderr(service_output):
                    output = asyncio.run(publish_inventory(cohort))
    except Exception as exc:
        output = failure_status(exc, stage="publish" if args.operation == "publish" else "inspect")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
