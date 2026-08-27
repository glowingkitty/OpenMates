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
DEFAULT_RUNTIME_VERIFIER = "/app/scripts/verify_storage_replication_cli_chat.py"
POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 180
REPORT_FIELDS = (
    "status",
    "variant_count",
    "verified_region_count",
    "deleted_region_count",
)


def parse_cli_json(output: str) -> dict[str, Any]:
    """Return the last complete CLI result from mixed streaming output."""
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
    for candidate in reversed(candidates):
        if candidate.get("status") == "completed" or candidate.get("chat_id"):
            return candidate
    raise RuntimeError("cli_result_invalid_json")


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
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"command_failed:{Path(command[0]).name}")
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


def _runtime_command(
    *,
    content_hash: str,
    regions: tuple[str, ...],
    expect_deleted: bool,
    timeout: int,
) -> list[str]:
    command = [
        "docker",
        "exec",
        "api",
        "python",
        os.getenv("OPENMATES_STORAGE_RUNTIME_VERIFIER", DEFAULT_RUNTIME_VERIFIER),
        "--runtime-content-hash",
        content_hash,
        "--verify-regions",
        ",".join(regions),
        "--timeout-seconds",
        str(timeout),
    ]
    if expect_deleted:
        command.append("--expect-deleted")
    return command


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
        _run(["npm", "run", "build"], cwd=CLI_DIR, timeout=300)
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
        )
        chat_id: str | None = None
        cleanup_verified = False
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
                    "--json",
                    "--response-timeout-seconds",
                    str(args.timeout_seconds),
                ),
                cwd=CLI_DIR,
                env=env,
                timeout=args.timeout_seconds + 120,
            )
            payload = parse_cli_json(f"{chat.stdout}\n{chat.stderr}")
            require_grounded_answer(payload, grounded_marker)
            chat_id = str(payload.get("chat_id") or payload.get("chatId") or "")
            if not chat_id:
                raise RuntimeError("chat_id_missing")
            replica = _run(
                _runtime_command(
                    content_hash=content_hash,
                    regions=args.regions,
                    expect_deleted=False,
                    timeout=args.timeout_seconds,
                ),
                timeout=args.timeout_seconds + 30,
            )
            replica_report = sanitize_runtime_report(json.loads(replica.stdout))
            if replica_report.get("status") != "passed":
                raise RuntimeError("regional_replica_verification_failed")
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
                )
                deleted = _run(
                    _runtime_command(
                        content_hash=content_hash,
                        regions=args.regions,
                        expect_deleted=True,
                        timeout=args.timeout_seconds,
                    ),
                    timeout=args.timeout_seconds + 30,
                )
                deletion_report = sanitize_runtime_report(json.loads(deleted.stdout))
                if deletion_report.get("status") != "passed":
                    raise RuntimeError("regional_cleanup_verification_failed")
                replica_report["deleted_region_count"] = deletion_report.get("deleted_region_count", 0)
                cleanup_verified = True
            return {
                "status": "passed",
                "scenario": args.scenario,
                "chat_completed": True,
                "image_grounded": True,
                **replica_report,
                "object_keys_in_output": False,
            }
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
                    )
                    deleted = _run(
                        _runtime_command(
                            content_hash=content_hash,
                            regions=args.regions,
                            expect_deleted=True,
                            timeout=args.timeout_seconds,
                        ),
                        timeout=args.timeout_seconds + 30,
                    )
                    cleanup_verified = json.loads(deleted.stdout).get("status") == "passed"
                except Exception as cleanup_error:
                    raise RuntimeError("mandatory_cleanup_failed") from cleanup_error
                if not cleanup_verified:
                    raise RuntimeError("mandatory_cleanup_failed")
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
                return {
                    "status": "passed",
                    "variant_count": len(variants),
                    "verified_region_count": len(args.regions),
                    "deleted_region_count": 0,
                }
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise RuntimeError("regional_replica_timeout")
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
    parser.add_argument("--expect-deleted", action="store_true")
    args = parser.parse_args()
    try:
        report = (
            asyncio.run(_runtime_verify(args))
            if args.runtime_content_hash
            else _host_verify(args)
        )
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
