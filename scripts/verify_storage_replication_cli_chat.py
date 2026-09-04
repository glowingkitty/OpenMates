#!/usr/bin/env python3
"""Verify a real CLI image chat and its encrypted regional S3 replicas.

Host mode builds and runs the real OpenMates CLI against dev with an isolated
test-account session. Runtime mode executes inside the API container, resolves
the unique test upload through Directus, and compares ciphertext bytes against
the durable replication checksum without emitting object keys or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend/packages/openmates-cli"
CLI_DIST = CLI_DIR / "dist/cli.js"
LOGIN_HELPER = ROOT / "scripts/openmates_cli_test_account.mjs"
POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 180
ORPHAN_UPLOAD_CLEANUP_TIMEOUT_SECONDS = 60
REPORT_FIELDS = (
    "status",
    "variant_count",
    "verified_region_count",
    "deleted_region_count",
)
SAFE_RUNTIME_FAILURE_CLASSES = {
    "cli_build_failed",
    "cli_chat_create_failed",
    "cli_chat_preflight_rejected",
    "cli_chat_response_timeout",
    "cli_chat_delete_failed",
    "cli_file_upload_failed",
    "cli_login_failed",
    "cli_mention_resolution_failed",
    "cli_signup_required",
    "orphan_upload_cleanup_timeout",
    "orphan_upload_record_delete_failed",
    "regional_ciphertext_checksum_mismatch",
    "regional_cleanup_timeout",
    "regional_replica_timeout",
    "runtime_output_invalid_json",
    "upload_record_not_found",
    "upload_variants_missing",
}


def parse_json_objects(output: str) -> list[dict[str, Any]]:
    """Return complete JSON objects embedded in mixed command output."""
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    return candidates


def parse_cli_json(output: str) -> dict[str, Any]:
    """Return the last complete CLI result from mixed streaming output."""
    candidates = parse_json_objects(output)
    for candidate in reversed(candidates):
        if candidate.get("status") == "completed" or candidate.get("chat_id"):
            return candidate
    raise RuntimeError("cli_result_invalid_json")


def parse_runtime_report(output: str) -> dict[str, Any]:
    """Return the last sanitized runtime report from mixed runtime output."""
    for candidate in reversed(parse_json_objects(output)):
        if "status" in candidate or "failure_class" in candidate:
            return candidate
    raise RuntimeError("runtime_output_invalid_json")


def classify_cli_failure(output: str, default: str) -> str:
    """Map mixed CLI output to a safe non-secret failure class."""
    lowered = output.casefold()
    if "upload failed:" in lowered:
        return "cli_file_upload_failed"
    if "response timed out" in lowered or "timed out waiting" in lowered:
        return "cli_chat_response_timeout"
    if "encrypted chat preflight was rejected" in lowered:
        return "cli_chat_preflight_rejected"
    if "unknown mention" in lowered:
        return "cli_mention_resolution_failed"
    if "file uploads require signup" in lowered or "signup_required" in lowered:
        return "cli_signup_required"
    return default


def require_grounded_answer(payload: dict[str, Any], marker: str) -> None:
    """Require the deterministic image-grounding marker from the assistant."""
    answer = str(payload.get("assistant") or "")
    if marker.casefold() not in answer.casefold():
        raise RuntimeError("image_grounding_failed")


def sanitize_runtime_report(report: dict[str, Any]) -> dict[str, Any]:
    """Retain only aggregate evidence approved for command output."""
    return {field: report[field] for field in REPORT_FIELDS if field in report}


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    input_text: str | None = None,
    failure_class: str | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        input=input_text,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        default_failure = failure_class or f"command_failed:{Path(command[0]).name}"
        raise RuntimeError(classify_cli_failure(f"{completed.stdout}\n{completed.stderr}", default_failure))
    return completed


def _unique_image(directory: Path) -> tuple[Path, str, str]:
    marker = f"OM-{uuid.uuid4().hex[:10].upper()}"
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="600">'
        '<rect width="1200" height="600" fill="#10243e"/>'
        '<text x="600" y="300" text-anchor="middle" dominant-baseline="middle" '
        'font-family="monospace" font-size="96" font-weight="700" fill="#f4d35e">'
        f'{marker}</text></svg>'
    ).encode()
    path = directory / "regional-image-test.svg"
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest(), marker


def _proof_slug(content_hash: str) -> str:
    return f"regional-storage-{content_hash[:16]}"


def build_host_report(scenario: str, replica_report: dict[str, Any]) -> dict[str, Any]:
    return {
        **replica_report,
        "status": "passed",
        "scenario": scenario,
        "chat_completed": True,
        "image_grounded": True,
        "object_keys_in_output": False,
    }


def _runtime_command(
    *,
    content_hash: str,
    regions: tuple[str, ...],
    expect_deleted: bool,
    timeout: int,
    wait_for_cleanup: bool = False,
) -> list[str]:
    runtime_verifier = os.getenv("OPENMATES_STORAGE_RUNTIME_VERIFIER")
    command = ["docker", "exec"]
    if not runtime_verifier:
        command.append("-i")
    command.extend([
        "api",
        "python",
        runtime_verifier or "-",
        "--runtime-content-hash",
        content_hash,
        "--verify-regions",
        ",".join(regions),
        "--timeout-seconds",
        str(timeout),
    ])
    if expect_deleted:
        command.append("--expect-deleted")
    if wait_for_cleanup:
        command.append("--wait-for-cleanup")
    return command


def _runtime_upload_cleanup_command(
    *,
    content_hash: str,
    regions: tuple[str, ...],
    timeout: int,
) -> list[str]:
    runtime_verifier = os.getenv("OPENMATES_STORAGE_RUNTIME_VERIFIER")
    command = ["docker", "exec"]
    if not runtime_verifier:
        command.append("-i")
    command.extend([
        "api",
        "python",
        runtime_verifier or "-",
        "--runtime-cleanup-content-hash",
        content_hash,
        "--verify-regions",
        ",".join(regions),
        "--timeout-seconds",
        str(timeout),
    ])
    return command


def _run_runtime(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    source = None if os.getenv("OPENMATES_STORAGE_RUNTIME_VERIFIER") else Path(__file__).read_text(encoding="utf-8")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=dict(os.environ),
        text=True,
        capture_output=True,
        input=source,
        check=False,
        timeout=timeout,
    )
    if completed.returncode == 0:
        return completed
    try:
        failure_class = str(json.loads(completed.stdout.strip()).get("failure_class") or "")
    except (json.JSONDecodeError, AttributeError):
        failure_class = ""
    safe_failure = failure_class if failure_class in SAFE_RUNTIME_FAILURE_CLASSES else "runtime_verification_failed"
    raise RuntimeError(safe_failure)


def _run_runtime_upload_cleanup(command: list[str], *, timeout: int) -> dict[str, Any]:
    completed = _run_runtime(command, timeout=timeout)
    report = parse_runtime_report(f"{completed.stdout}\n{completed.stderr}")
    if report.get("status") not in {"passed", "not_found"}:
        failure = str(report.get("failure_class") or "orphan_upload_cleanup_timeout")
        raise RuntimeError(failure if failure in SAFE_RUNTIME_FAILURE_CLASSES else "runtime_verification_failed")
    return report


def _start_runtime_cleanup_session(
    command: list[str],
) -> tuple[subprocess.Popen[str], dict[str, Any]]:
    source = None if os.getenv("OPENMATES_STORAGE_RUNTIME_VERIFIER") else Path(__file__).read_text(encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=dict(os.environ),
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdin is not None:
        process.stdin.write(source or "")
        process.stdin.close()
        process.stdin = None
    if process.stdout is None:
        _stop_runtime_process(process)
        raise RuntimeError("runtime_verification_failed")
    while True:
        ready_line = process.stdout.readline()
        if not ready_line:
            _stop_runtime_process(process)
            raise RuntimeError("runtime_output_invalid_json")
        try:
            ready = parse_runtime_report(ready_line)
        except RuntimeError:
            continue
        break
    if ready.get("status") != "replicas_ready":
        _stop_runtime_process(process)
        failure = str(ready.get("failure_class") or "")
        raise RuntimeError(failure if failure in SAFE_RUNTIME_FAILURE_CLASSES else "runtime_verification_failed")
    return process, sanitize_runtime_report(ready)


def _stop_runtime_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        process.wait()
        return
    process.terminate()
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()


def _finish_runtime_cleanup_session(
    process: subprocess.Popen[str],
    *,
    timeout: int,
) -> dict[str, Any]:
    try:
        remaining_output, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_runtime_process(process)
        raise RuntimeError("regional_cleanup_timeout")
    report = parse_runtime_report(remaining_output)
    if process.returncode != 0:
        failure = str(report.get("failure_class") or "")
        raise RuntimeError(failure if failure in SAFE_RUNTIME_FAILURE_CLASSES else "runtime_verification_failed")
    return sanitize_runtime_report(report)


def _cli_command(*args: str) -> list[str]:
    executable = os.getenv("OPENMATES_CLI")
    if executable:
        return [executable, *args]
    return ["node", str(CLI_DIST), *args]


def _host_verify(args: argparse.Namespace) -> dict[str, Any]:
    if args.scenario != "image-question":
        raise RuntimeError("unsupported_scenario")
    if not args.cleanup:
        raise RuntimeError("cleanup_is_required")
    if os.getenv("OPENMATES_CLI_SKIP_BUILD") != "1":
        _run(["npm", "run", "build"], cwd=CLI_DIR, timeout=300, failure_class="cli_build_failed")
    with tempfile.TemporaryDirectory(prefix="openmates-regional-cli-") as temporary:
        home = Path(temporary)
        (home / "backend").symlink_to(ROOT / "backend", target_is_directory=True)
        image_path, content_hash, grounded_marker = _unique_image(home)
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["OPENMATES_CLI_DEVICE_IDENTITY"] = f"cli:regional-storage:{content_hash[:12]}"
        _run(
            [
                "node",
                str(LOGIN_HELPER),
                "login",
                "--slot",
                "auto",
                "--api-url",
                args.api_url,
            ],
            env=env,
            failure_class="cli_login_failed",
        )
        chat_id: str | None = None
        cleanup_verified = False
        runtime_process: subprocess.Popen[str] | None = None
        try:
            prompt = (
                f"Inspect @{image_path} and reply with exactly the large token visible in the image."
            )
            chat = _run(
                _cli_command(
                    "--api-url",
                    args.api_url,
                    "chats",
                    "new",
                    prompt,
                    "--slug",
                    _proof_slug(content_hash),
                    "--json",
                    "--response-timeout-seconds",
                    str(args.timeout_seconds),
                ),
                cwd=CLI_DIR,
                env=env,
                timeout=args.timeout_seconds + 120,
                failure_class="cli_chat_create_failed",
            )
            payload = parse_cli_json(f"{chat.stdout}\n{chat.stderr}")
            require_grounded_answer(payload, grounded_marker)
            chat_id = str(payload.get("chat_id") or payload.get("chatId") or "")
            if not chat_id:
                raise RuntimeError("chat_id_missing")
            runtime_process, replica_report = _start_runtime_cleanup_session(
                _runtime_command(
                    content_hash=content_hash,
                    regions=args.regions,
                    expect_deleted=False,
                    timeout=args.timeout_seconds,
                    wait_for_cleanup=True,
                )
            )
            if args.cleanup:
                _run(
                    _cli_command(
                        "--api-url",
                        args.api_url,
                        "chats",
                        "delete",
                        chat_id,
                        "--yes",
                        "--json",
                    ),
                    cwd=CLI_DIR,
                    env=env,
                    failure_class="cli_chat_delete_failed",
                )
                deletion_report = _finish_runtime_cleanup_session(
                    runtime_process,
                    timeout=args.timeout_seconds + 30,
                )
                if deletion_report.get("status") != "passed":
                    raise RuntimeError("regional_cleanup_verification_failed")
                replica_report["deleted_region_count"] = deletion_report.get("deleted_region_count", 0)
                cleanup_verified = True
            return build_host_report(args.scenario, replica_report)
        finally:
            if chat_id and not cleanup_verified:
                try:
                    _run(
                        _cli_command(
                            "--api-url",
                            args.api_url,
                            "chats",
                            "delete",
                            chat_id,
                            "--yes",
                            "--json",
                        ),
                        cwd=CLI_DIR,
                        env=env,
                        failure_class="cli_chat_delete_failed",
                    )
                    if runtime_process is not None:
                        deletion_report = _finish_runtime_cleanup_session(
                            runtime_process,
                            timeout=args.timeout_seconds + 30,
                        )
                        cleanup_verified = deletion_report.get("status") == "passed"
                except Exception as cleanup_error:
                    if runtime_process is not None:
                        _stop_runtime_process(runtime_process)
                    safe_failure = str(cleanup_error)
                    if safe_failure not in SAFE_RUNTIME_FAILURE_CLASSES:
                        safe_failure = "runtime_verification_failed"
                    raise RuntimeError(f"mandatory_cleanup_failed:{safe_failure}") from cleanup_error
                if not cleanup_verified:
                    raise RuntimeError("mandatory_cleanup_failed")
            if not chat_id:
                try:
                    _run_runtime_upload_cleanup(
                        _runtime_upload_cleanup_command(
                            content_hash=content_hash,
                            regions=args.regions,
                            timeout=ORPHAN_UPLOAD_CLEANUP_TIMEOUT_SECONDS,
                        ),
                        timeout=ORPHAN_UPLOAD_CLEANUP_TIMEOUT_SECONDS + 30,
                    )
                except Exception as cleanup_error:
                    safe_failure = str(cleanup_error)
                    if safe_failure not in SAFE_RUNTIME_FAILURE_CLASSES:
                        safe_failure = "runtime_verification_failed"
                    raise RuntimeError(f"mandatory_cleanup_failed:{safe_failure}") from cleanup_error
            subprocess.run(
                _cli_command("--api-url", args.api_url, "logout", "--yes"),
                cwd=CLI_DIR,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )


def _stream_checksum(body: Any) -> str:
    digest = hashlib.sha256()
    try:
        while chunk := body.read(1024 * 1024):
            digest.update(chunk)
    finally:
        body.close()
    return digest.hexdigest()


async def _load_runtime_services() -> tuple[Any, Any, Any]:
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.s3.service import S3UploadService
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets = SecretsManager()
    await secrets.initialize()
    directus = DirectusService()
    s3 = S3UploadService(secrets_manager=secrets, directus_service=directus)
    await s3.initialize(configure_buckets=False)
    return secrets, directus, s3


async def _runtime_verify(args: argparse.Namespace) -> dict[str, Any]:
    from botocore.exceptions import ClientError

    from backend.core.api.app.services.s3.config import get_bucket_name
    from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name

    secrets, directus, s3 = await _load_runtime_services()
    try:
        deadline = time.monotonic() + args.timeout_seconds
        upload: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            rows = await directus.get_items(
                "upload_files",
                params={
                    "filter": {"content_hash": {"_eq": args.runtime_content_hash}},
                    "fields": "id,files_metadata",
                    "sort": "-created_at",
                    "limit": 1,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            if rows:
                upload = dict(rows[0])
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        if upload is None:
            raise RuntimeError("upload_record_not_found")
        variants = [
            variant
            for variant in dict(upload.get("files_metadata") or {}).values()
            if isinstance(variant, dict) and variant.get("s3_key")
        ]
        if not variants:
            raise RuntimeError("upload_variants_missing")

        if args.expect_deleted:
            deadline = time.monotonic() + args.timeout_seconds
            while time.monotonic() < deadline:
                deleted = 0
                completed_tombstones = 0
                for variant in variants:
                    key = str(variant["s3_key"])
                    tombstones = await directus.get_items(
                        "storage_deletion_tombstones",
                        params={
                            "filter": {
                                "logical_bucket": {"_eq": "chatfiles"},
                                "object_key": {"_eq": key},
                                "state": {"_eq": "completed"},
                            },
                            "fields": "id,state",
                            "limit": 1,
                        },
                        no_cache=True,
                        admin_required=True,
                        raise_on_error=True,
                    )
                    if tombstones:
                        completed_tombstones += 1
                    for region in args.regions:
                        bucket = resolve_regional_bucket_name(
                            get_bucket_name("chatfiles", s3.environment), region
                        )
                        try:
                            await asyncio.to_thread(
                                s3.region_clients[region].head_object,
                                Bucket=bucket,
                                Key=key,
                            )
                        except ClientError as exc:
                            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                                deleted += 1
                                continue
                            raise
                expected = len(variants) * len(args.regions)
                if deleted == expected and completed_tombstones == len(variants):
                    return {
                        "status": "passed",
                        "variant_count": len(variants),
                        "verified_region_count": 0,
                        "deleted_region_count": len(args.regions),
                    }
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            raise RuntimeError("regional_cleanup_timeout")

        while time.monotonic() < deadline:
            verified = 0
            retry = False
            for variant in variants:
                key = str(variant["s3_key"])
                jobs = await directus.get_items(
                    "storage_replication_jobs",
                    params={
                        "filter": {"logical_bucket": {"_eq": "chatfiles"}, "object_key": {"_eq": key}},
                        "fields": "checksum,generation,state",
                        "sort": "-generation",
                        "limit": 1,
                    },
                    no_cache=True,
                    admin_required=True,
                    raise_on_error=True,
                )
                if not jobs:
                    retry = True
                    break
                expected_checksum = str(jobs[0]["checksum"]).removeprefix("sha256:")
                for region in args.regions:
                    bucket = resolve_regional_bucket_name(
                        get_bucket_name("chatfiles", s3.environment), region
                    )
                    try:
                        response = await asyncio.to_thread(
                            s3.region_clients[region].get_object,
                            Bucket=bucket,
                            Key=key,
                        )
                        checksum = await asyncio.to_thread(_stream_checksum, response["Body"])
                    except ClientError as exc:
                        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                            retry = True
                            break
                        raise
                    if checksum != expected_checksum:
                        raise RuntimeError("regional_ciphertext_checksum_mismatch")
                    verified += 1
                if retry:
                    break
            if not retry and verified == len(variants) * len(args.regions):
                replica_report = {
                    "status": "passed",
                    "variant_count": len(variants),
                    "verified_region_count": len(args.regions),
                    "deleted_region_count": 0,
                }
                if not args.wait_for_cleanup:
                    return replica_report
                print(json.dumps({**replica_report, "status": "replicas_ready"}, separators=(",", ":")), flush=True)
                args.expect_deleted = True
                deadline = time.monotonic() + args.timeout_seconds
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        else:
            raise RuntimeError("regional_replica_timeout")

        while time.monotonic() < deadline:
            deleted = 0
            completed_tombstones = 0
            for variant in variants:
                key = str(variant["s3_key"])
                tombstones = await directus.get_items(
                    "storage_deletion_tombstones",
                    params={
                        "filter": {
                            "logical_bucket": {"_eq": "chatfiles"},
                            "object_key": {"_eq": key},
                            "state": {"_eq": "completed"},
                        },
                        "fields": "id,state",
                        "limit": 1,
                    },
                    no_cache=True,
                    admin_required=True,
                    raise_on_error=True,
                )
                if tombstones:
                    completed_tombstones += 1
                for region in args.regions:
                    bucket = resolve_regional_bucket_name(
                        get_bucket_name("chatfiles", s3.environment), region
                    )
                    try:
                        await asyncio.to_thread(
                            s3.region_clients[region].head_object,
                            Bucket=bucket,
                            Key=key,
                        )
                    except ClientError as exc:
                        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                            deleted += 1
                            continue
                        raise
            expected = len(variants) * len(args.regions)
            if deleted == expected and completed_tombstones == len(variants):
                return {
                    "status": "passed",
                    "variant_count": len(variants),
                    "verified_region_count": 0,
                    "deleted_region_count": len(args.regions),
                }
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise RuntimeError("regional_cleanup_timeout")
    finally:
        await directus.close()
        await secrets.aclose()


async def _runtime_cleanup_upload_by_hash(args: argparse.Namespace) -> dict[str, Any]:
    from botocore.exceptions import ClientError

    from backend.core.api.app.services.s3.config import get_bucket_name
    from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name

    secrets, directus, s3 = await _load_runtime_services()
    try:
        deadline = time.monotonic() + args.timeout_seconds
        upload: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            rows = await directus.get_items(
                "upload_files",
                params={
                    "filter": {"content_hash": {"_eq": args.runtime_cleanup_content_hash}},
                    "fields": "id,files_metadata,file_size_bytes",
                    "sort": "-created_at",
                    "limit": 1,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            if rows:
                upload = dict(rows[0])
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        if upload is None:
            return {
                "status": "not_found",
                "upload_record_found": False,
                "object_keys_in_output": False,
            }

        variants = [
            variant
            for variant in dict(upload.get("files_metadata") or {}).values()
            if isinstance(variant, dict) and variant.get("s3_key")
        ]
        tombstones = await directus.embed._persist_upload_tombstones([upload])
        directus_id = str(upload.get("id") or "")
        if directus_id:
            deleted = await directus.delete_item("upload_files", directus_id, admin_required=True)
            if not deleted:
                raise RuntimeError("orphan_upload_record_delete_failed")
        await directus.embed._activate_s3_tombstones(tombstones)

        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() < deadline:
            deleted_count = 0
            completed_tombstones = 0
            for variant in variants:
                key = str(variant["s3_key"])
                tombstone_rows = await directus.get_items(
                    "storage_deletion_tombstones",
                    params={
                        "filter": {
                            "logical_bucket": {"_eq": "chatfiles"},
                            "object_key": {"_eq": key},
                            "state": {"_eq": "completed"},
                        },
                        "fields": "id,state",
                        "limit": 1,
                    },
                    no_cache=True,
                    admin_required=True,
                    raise_on_error=True,
                )
                if tombstone_rows:
                    completed_tombstones += 1
                for region in args.regions:
                    bucket = resolve_regional_bucket_name(
                        get_bucket_name("chatfiles", s3.environment), region
                    )
                    try:
                        await asyncio.to_thread(
                            s3.region_clients[region].head_object,
                            Bucket=bucket,
                            Key=key,
                        )
                    except ClientError as exc:
                        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                            deleted_count += 1
                            continue
                        raise
            if not variants or (
                deleted_count == len(variants) * len(args.regions)
                and completed_tombstones == len(variants)
            ):
                return {
                    "status": "passed",
                    "upload_record_found": True,
                    "variant_count": len(variants),
                    "deleted_region_count": len(args.regions),
                    "object_keys_in_output": False,
                }
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise RuntimeError("orphan_upload_cleanup_timeout")
    finally:
        await directus.close()
        await secrets.aclose()


async def _runtime_cleanup_aggregate(minutes: int) -> dict[str, Any]:
    """Return recent deletion health without object identities or storage names."""
    secrets, directus, _s3 = await _load_runtime_services()
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        rows = await directus.get_items(
            "storage_deletion_tombstones",
            params={
                "filter": {"created_at": {"_gte": since}},
                "fields": "state,purge_states,attempts,last_error_code",
                "sort": "-created_at",
                "limit": 100,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        uploads = await directus.get_items(
            "upload_files",
            params={
                "fields": "embed_id,created_at",
                "sort": "-created_at",
                "limit": 20,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        upload_embed_ids = {
            str(upload.get("embed_id")) for upload in uploads or [] if upload.get("embed_id")
        }
        embeds = []
        legacy_upload_matches = []
        structured_upload_matches = []
        if upload_embed_ids:
            embeds = await directus.get_items(
                "embeds",
                params={
                    "filter": {"embed_id": {"_in": sorted(upload_embed_ids)}},
                    "fields": "embed_id,is_private,is_shared,hashed_chat_id",
                    "limit": 100,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            legacy_upload_matches = await directus.get_items(
                "upload_files",
                params={
                    "filter[embed_id][_in]": ",".join(sorted(upload_embed_ids)),
                    "fields": "id",
                    "limit": 100,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            structured_upload_matches = await directus.get_items(
                "upload_files",
                params={
                    "filter": {"embed_id": {"_in": sorted(upload_embed_ids)}},
                    "fields": "id",
                    "limit": 100,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
        matched_embed_ids = {
            str(embed.get("embed_id")) for embed in embeds or [] if embed.get("embed_id")
        }
        privacy_states: Counter[str] = Counter(
            f"private={embed.get('is_private')}:shared={embed.get('is_shared')}"
            for embed in embeds or []
        )
        now_timestamp = int(datetime.now(timezone.utc).timestamp())
        latest_upload_states = [
            {
                "age_seconds": max(0, now_timestamp - int(upload.get("created_at") or now_timestamp)),
                "embed_present": str(upload.get("embed_id")) in matched_embed_ids,
            }
            for upload in (uploads or [])[:5]
        ]
        states: Counter[str] = Counter()
        errors: Counter[str] = Counter()
        region_states: Counter[str] = Counter()
        max_attempts = 0
        for row in rows or []:
            states[str(row.get("state") or "unknown")] += 1
            error_code = str(row.get("last_error_code") or "")
            if error_code:
                errors[error_code] += 1
            max_attempts = max(max_attempts, int(row.get("attempts") or 0))
            for generation_states in dict(row.get("purge_states") or {}).values():
                for region, state in dict(generation_states or {}).items():
                    region_states[f"{region}:{state}"] += 1
        return {
            "status": "passed",
            "window_minutes": minutes,
            "tombstone_count": len(rows or []),
            "state_counts": dict(sorted(states.items())),
            "region_state_counts": dict(sorted(region_states.items())),
            "error_code_counts": dict(sorted(errors.items())),
            "max_attempts": max_attempts,
            "sampled_upload_count": len(uploads or []),
            "matched_embed_count": len(matched_embed_ids),
            "unmatched_upload_count": len(upload_embed_ids - matched_embed_ids),
            "embed_privacy_state_counts": dict(sorted(privacy_states.items())),
            "latest_upload_states": latest_upload_states,
            "legacy_filter_match_count": len(legacy_upload_matches or []),
            "structured_filter_match_count": len(structured_upload_matches or []),
            "object_keys_in_output": False,
        }
    finally:
        await directus.close()
        await secrets.aclose()


def _parse_regions(value: str) -> tuple[str, ...]:
    regions = tuple(part.strip() for part in value.split(",") if part.strip())
    if not regions or any(region not in {"nbg1", "fsn1", "hel1"} for region in regions):
        raise argparse.ArgumentTypeError("regions must be a non-empty subset of nbg1,fsn1,hel1")
    return regions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("dev",), default="dev")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--scenario", default="image-question")
    parser.add_argument("--verify-regions", dest="regions", type=_parse_regions, default=("nbg1", "fsn1", "hel1"))
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--runtime-content-hash")
    parser.add_argument("--runtime-cleanup-content-hash")
    parser.add_argument("--wait-for-cleanup", action="store_true")
    parser.add_argument("--runtime-cleanup-aggregate-minutes", type=int)
    parser.add_argument("--expect-deleted", action="store_true")
    args = parser.parse_args()
    try:
        if args.runtime_cleanup_content_hash:
            report = asyncio.run(_runtime_cleanup_upload_by_hash(args))
        elif args.runtime_cleanup_aggregate_minutes:
            report = asyncio.run(_runtime_cleanup_aggregate(args.runtime_cleanup_aggregate_minutes))
        elif args.runtime_content_hash:
            report = asyncio.run(_runtime_verify(args))
        else:
            report = _host_verify(args)
    except Exception as exc:
        report = {
            "status": "failed",
            "failure_class": str(exc),
            "object_keys_in_output": False,
        }
        print(json.dumps(report, separators=(",", ":")))
        return 1
    print(json.dumps(report, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
