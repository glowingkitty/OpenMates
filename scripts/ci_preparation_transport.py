#!/usr/bin/env python3
"""Private, expiring object transport for reusable CI preparation bytes.

Coordinator-side functions persist owner-only presigned tickets. Runner-side
commands read a ticket only from the workflow event, mask every URL before use,
and stream a fixed allowlist without putting presigned URLs in argv or receipts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping
import urllib.parse
import uuid

try:
    from scripts.ci_candidate_artifact import (
        BUCKET_NAME,
        DEFAULT_CONTAINER,
        EXPIRES_SECONDS,
    )
except ModuleNotFoundError:  # Direct execution puts scripts/ on sys.path.
    from ci_candidate_artifact import (  # type: ignore
        BUCKET_NAME,
        DEFAULT_CONTAINER,
        EXPIRES_SECONDS,
    )


FORMAT_VERSION = 1
TICKET_DIR = Path("logs/ci-coordinator/preparations")
OBJECT_PREFIX = "candidates/preparations"
MANIFEST_PATH = "manifest.json"
ALLOWED_PATHS = (
    MANIFEST_PATH,
    "web.tar.gz",
    "translations.tar.gz",
    "cli.tar.gz",
    "images/api.tar",
    "images/cms.tar",
    "images/setup.tar",
    "images/schema.tar",
    "images/upload.tar",
)
MAX_MANIFEST_BYTES = 1024**2
MAX_OBJECT_BYTES = 4 * 1024**3
MAX_TOTAL_BYTES = 9 * 1024**3
CHUNK_BYTES = 1024**2
HTTP_TIMEOUT_SECONDS = 120
PRESIGN_TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 64 * 1024


class PreparationTransportError(RuntimeError):
    """A bounded error that never includes a presigned URL or response body."""


INNER_PRESIGN_CODE = r'''
import asyncio
import json
import os

import boto3
from botocore.config import Config

from backend.core.api.app.utils.secrets_manager import SecretsManager

REQUEST = json.loads(os.environ["OPENMATES_CI_PREPARATION_REQUEST"])


async def main():
    manager = SecretsManager()
    await manager.initialize()
    access_key = await manager.get_secret(secret_path="kv/data/providers/hetzner", secret_key="s3_access_key")
    secret_key = await manager.get_secret(secret_path="kv/data/providers/hetzner", secret_key="s3_secret_key")
    region = await manager.get_secret(secret_path="kv/data/providers/hetzner", secret_key="s3_region_name") or "nbg1"
    if not access_key or not secret_key:
        raise RuntimeError("Hetzner S3 credentials are unavailable in Vault")
    client = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=f"https://{region}.your-objectstorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    client.head_bucket(Bucket=REQUEST["bucket"])
    result = {}
    for relative, key in REQUEST["objects"].items():
        put_url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": REQUEST["bucket"],
                "Key": key,
                "ContentType": "application/octet-stream",
                "ACL": "private",
            },
            ExpiresIn=REQUEST["expires_in"],
        )
        get_url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": REQUEST["bucket"], "Key": key},
            ExpiresIn=REQUEST["expires_in"],
        )
        result[relative] = {"put_url": put_url, "get_url": get_url}
    print(json.dumps(result, sort_keys=True))


asyncio.run(main())
'''


def _utc_now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Preparation transport time must include a timezone")
    return value.astimezone(dt.timezone.utc)


def _validate_identity(producer_id: str, source: str, preparation_key: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", producer_id):
        raise ValueError("Preparation producer must have a full job ID")
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("Preparation source must be a full commit SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", preparation_key):
        raise ValueError("Preparation key must be a full SHA-256")


def _ticket_paths(root: Path, producer_id: str) -> tuple[Path, Path]:
    directory = root.resolve() / TICKET_DIR
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory / f"{producer_id}.json", directory / f"{producer_id}.lock"


class _TicketLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.fchmod(descriptor, 0o600)
        self.handle = os.fdopen(descriptor, "a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self.handle

    def __exit__(self, exc_type, exc, traceback):
        assert self.handle is not None
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def _parse_expiry(value: object) -> dt.datetime:
    try:
        expiry = dt.datetime.fromisoformat(str(value))
    except ValueError:
        raise PreparationTransportError("Preparation transport ticket is invalid") from None
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        raise PreparationTransportError("Preparation transport ticket is invalid")
    return expiry.astimezone(dt.timezone.utc)


def _validate_url(value: object, *, expected_path: str | None = None) -> str:
    if not isinstance(value, str):
        raise PreparationTransportError("Preparation transport URL is invalid")
    if re.search(r"[\x00-\x20\x7f]", value):
        raise PreparationTransportError("Preparation transport URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise PreparationTransportError("Preparation transport URL is invalid") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".your-objectstorage.com")
        or port not in (None, 443)
        or parsed.username
        or parsed.password
        or not parsed.query
        or parsed.fragment
        or (
            parsed.path != expected_path
            if expected_path is not None
            else not parsed.path.startswith(f"/{BUCKET_NAME}/")
        )
    ):
        raise PreparationTransportError("Preparation transport URL is invalid")
    return value


def _object_key(
    source: str, preparation_key: str, producer_id: str, relative: str
) -> str:
    return f"{OBJECT_PREFIX}/{source}/{preparation_key}/{producer_id}/{relative}"


def _object_url_path(
    source: str, preparation_key: str, producer_id: str, relative: str
) -> str:
    return f"/{BUCKET_NAME}/{_object_key(source, preparation_key, producer_id, relative)}"


def _validate_ticket(
    ticket: Mapping[str, Any],
    *,
    producer_id: str,
    source: str,
    preparation_key: str,
    now: dt.datetime,
) -> dict[str, Any]:
    if (
        ticket.get("format_version") != FORMAT_VERSION
        or ticket.get("producer_id") != producer_id
        or ticket.get("source") != source
        or ticket.get("preparation_key") != preparation_key
        or ticket.get("bucket") != BUCKET_NAME
        or _parse_expiry(ticket.get("expires_at")) <= now
    ):
        raise PreparationTransportError("Preparation transport ticket is unavailable")
    objects = ticket.get("objects")
    if not isinstance(objects, dict) or set(objects) != set(ALLOWED_PATHS):
        raise PreparationTransportError("Preparation transport ticket is invalid")
    for relative, record in objects.items():
        if not isinstance(record, dict):
            raise PreparationTransportError("Preparation transport ticket is invalid")
        expected_key = _object_key(source, preparation_key, producer_id, relative)
        if record.get("object_key") != expected_key:
            raise PreparationTransportError("Preparation transport ticket is invalid")
        expected_path = _object_url_path(
            source, preparation_key, producer_id, relative
        )
        _validate_url(record.get("put_url"), expected_path=expected_path)
        _validate_url(record.get("get_url"), expected_path=expected_path)
    return dict(ticket)


def _read_ticket(path: Path) -> dict[str, Any]:
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PreparationTransportError("Preparation transport ticket is unavailable")
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raise PreparationTransportError("Preparation transport ticket is unavailable") from None
    if not isinstance(value, dict):
        raise PreparationTransportError("Preparation transport ticket is unavailable")
    return value


def _write_ticket(path: Path, ticket: Mapping[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(ticket, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _presign_objects(
    objects: Mapping[str, str],
    expires_seconds: int,
    *,
    container: str = DEFAULT_CONTAINER,
) -> dict[str, dict[str, str]]:
    request = {
        "bucket": BUCKET_NAME,
        "expires_in": expires_seconds,
        "objects": dict(objects),
    }
    environment = {
        **os.environ,
        "OPENMATES_CI_PREPARATION_REQUEST": json.dumps(
            request, sort_keys=True, separators=(",", ":")
        ),
    }
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                "OPENMATES_CI_PREPARATION_REQUEST",
                container,
                "python",
                "-c",
                INNER_PRESIGN_CODE,
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
            timeout=PRESIGN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise PreparationTransportError(
            "Failed to create preparation transport ticket"
        ) from None
    if result.returncode:
        raise PreparationTransportError("Failed to create preparation transport ticket")
    try:
        lines = [line for line in result.stdout.splitlines() if line.strip().startswith("{")]
        value = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        raise PreparationTransportError(
            "Failed to create preparation transport ticket"
        ) from None
    if not isinstance(value, dict) or set(value) != set(objects):
        raise PreparationTransportError("Failed to create preparation transport ticket")
    validated = {}
    for relative, record in value.items():
        if not isinstance(record, dict):
            raise PreparationTransportError("Failed to create preparation transport ticket")
        expected_path = f"/{BUCKET_NAME}/{objects[relative]}"
        validated[relative] = {
            "put_url": _validate_url(
                record.get("put_url"), expected_path=expected_path
            ),
            "get_url": _validate_url(
                record.get("get_url"), expected_path=expected_path
            ),
        }
    return validated


def get_or_create_ticket(
    root: Path,
    producer_id: str,
    source: str,
    preparation_key: str,
    *,
    now: dt.datetime | None = None,
    presign: Callable[[Mapping[str, str], int], Mapping[str, Mapping[str, str]]]
    | None = None,
) -> dict[str, Any]:
    """Return one durable producer-owned ticket, refreshing only after expiry."""

    _validate_identity(producer_id, source, preparation_key)
    instant = _utc_now(now)
    ticket_path, lock_path = _ticket_paths(root, producer_id)
    with _TicketLock(lock_path):
        if ticket_path.is_file():
            try:
                return _validate_ticket(
                    _read_ticket(ticket_path),
                    producer_id=producer_id,
                    source=source,
                    preparation_key=preparation_key,
                    now=instant,
                )
            except PreparationTransportError:
                # Identity mismatches never refresh an owner's ticket. Only an
                # expired, otherwise matching ticket can be renewed.
                existing = _read_ticket(ticket_path)
                expiry = _parse_expiry(existing.get("expires_at"))
                if expiry > instant or expiry == dt.datetime.min.replace(
                    tzinfo=dt.timezone.utc
                ):
                    raise
                _validate_ticket(
                    existing,
                    producer_id=producer_id,
                    source=source,
                    preparation_key=preparation_key,
                    now=expiry - dt.timedelta(microseconds=1),
                )
        prefix = f"{OBJECT_PREFIX}/{source}/{preparation_key}/{producer_id}"
        object_keys = {path: f"{prefix}/{path}" for path in ALLOWED_PATHS}
        signer = presign or _presign_objects
        try:
            signed = signer(object_keys, EXPIRES_SECONDS)
        except PreparationTransportError:
            raise
        except Exception:
            raise PreparationTransportError(
                "Failed to create preparation transport ticket"
            ) from None
        if not isinstance(signed, Mapping) or set(signed) != set(ALLOWED_PATHS):
            raise PreparationTransportError("Failed to create preparation transport ticket")
        created = instant
        expiry = created + dt.timedelta(seconds=EXPIRES_SECONDS)
        objects = {}
        for relative, object_key in object_keys.items():
            record = signed[relative]
            if not isinstance(record, Mapping):
                raise PreparationTransportError("Failed to create preparation transport ticket")
            expected_path = f"/{BUCKET_NAME}/{object_key}"
            objects[relative] = {
                "object_key": object_key,
                "put_url": _validate_url(
                    record.get("put_url"), expected_path=expected_path
                ),
                "get_url": _validate_url(
                    record.get("get_url"), expected_path=expected_path
                ),
            }
        ticket = {
            "format_version": FORMAT_VERSION,
            "producer_id": producer_id,
            "source": source,
            "preparation_key": preparation_key,
            "bucket": BUCKET_NAME,
            "created_at": created.isoformat(),
            "expires_at": expiry.isoformat(),
            "objects": objects,
        }
        _write_ticket(ticket_path, ticket)
        return ticket


def _dispatch_view(ticket: Mapping[str, Any], *, producer: bool) -> dict[str, Any]:
    objects = {}
    for relative in ALLOWED_PATHS:
        record = ticket["objects"][relative]
        objects[relative] = {"get_url": record["get_url"]}
        if producer:
            objects[relative]["put_url"] = record["put_url"]
    return {
        "format_version": FORMAT_VERSION,
        "producer_id": ticket["producer_id"],
        "source": ticket["source"],
        "preparation_key": ticket["preparation_key"],
        "expires_at": ticket["expires_at"],
        "objects": objects,
    }


def dispatch_ticket(
    root: Path,
    job: Mapping[str, Any],
    *,
    now: dt.datetime | None = None,
    presign: Callable[[Mapping[str, str], int], Mapping[str, Mapping[str, str]]]
    | None = None,
) -> str:
    """Return the exact workflow input without logging or persisting receipts."""

    values = dict(job)
    source = str(values.get("source", ""))
    preparation_key = str(values.get("preparation_key", ""))
    is_producer = values.get("mode") == "prepare"
    producer_id = str(values.get("id") if is_producer else values.get("preparation_id", ""))
    _validate_identity(producer_id, source, preparation_key)
    instant = _utc_now(now)
    if is_producer:
        ticket = get_or_create_ticket(
            root,
            producer_id,
            source,
            preparation_key,
            now=instant,
            presign=presign,
        )
    else:
        ticket_path, lock_path = _ticket_paths(root, producer_id)
        with _TicketLock(lock_path):
            ticket = _validate_ticket(
                _read_ticket(ticket_path),
                producer_id=producer_id,
                source=source,
                preparation_key=preparation_key,
                now=instant,
            )
    return json.dumps(
        _dispatch_view(ticket, producer=is_producer),
        sort_keys=True,
        separators=(",", ":"),
    )


def _mask_and_validate_urls(
    ticket: Mapping[str, Any], mask: Callable[[str], None]
) -> dict[str, Any]:
    if ticket.get("format_version") != FORMAT_VERSION:
        raise PreparationTransportError("Preparation transport input is invalid")
    objects = ticket.get("objects")
    if not isinstance(objects, dict) or set(objects) != set(ALLOWED_PATHS):
        raise PreparationTransportError("Preparation transport input is invalid")
    source = ticket.get("source")
    preparation_key = ticket.get("preparation_key")
    producer_id = ticket.get("producer_id")
    if (
        not isinstance(source, str)
        or not re.fullmatch(r"[0-9a-f]{40}", source)
        or not isinstance(preparation_key, str)
        or not re.fullmatch(r"[0-9a-f]{64}", preparation_key)
        or not isinstance(producer_id, str)
        or not re.fullmatch(r"[0-9a-f]{64}", producer_id)
    ):
        raise PreparationTransportError("Preparation transport input is invalid")
    for relative, record in objects.items():
        if not isinstance(record, dict):
            raise PreparationTransportError("Preparation transport input is invalid")
        expected_path = _object_url_path(
            source, preparation_key, producer_id, relative
        )
        for name in ("put_url", "get_url"):
            value = record.get(name)
            if value is not None:
                _validate_url(value, expected_path=expected_path)
                # GitHub processes this workflow command before subsequent logs.
                mask(f"::add-mask::{value}")
    return dict(ticket)


def event_ticket(
    *,
    event_path: Path | None = None,
    environment: Mapping[str, str] | None = None,
    mask: Callable[[str], None] = print,
    now: dt.datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    env = os.environ if environment is None else environment
    path = event_path or Path(str(env.get("GITHUB_EVENT_PATH", "")))
    try:
        if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError
        event = json.loads(path.read_text())
        inputs = event["inputs"]
        raw = inputs["preparation_transport"]
        if not isinstance(raw, str) or len(raw.encode()) > MAX_MANIFEST_BYTES:
            raise ValueError
        ticket = json.loads(raw)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise PreparationTransportError("Preparation transport input is invalid") from None
    if not isinstance(inputs, dict) or not isinstance(ticket, dict):
        raise PreparationTransportError("Preparation transport input is invalid")
    ticket = _mask_and_validate_urls(ticket, mask)
    source = str(env.get("BUILD_COMMIT_SHA") or inputs.get("source_commit", ""))
    key = str(inputs.get("preparation_key", ""))
    if ticket.get("source") != source or ticket.get("preparation_key") != key:
        raise PreparationTransportError("Preparation transport identity mismatch")
    if _parse_expiry(ticket.get("expires_at")) <= _utc_now(now):
        raise PreparationTransportError("Preparation transport ticket expired")
    return ticket, inputs


def validate_event_role(
    ticket: Mapping[str, Any], inputs: Mapping[str, Any], *, command: str
) -> str:
    """Fail closed when a workflow receives capabilities for the wrong role."""

    mode = inputs.get("mode")
    producer = mode == "prepare"
    if not producer and mode not in {"e2e", "visual-smoke"}:
        raise PreparationTransportError("Preparation transport role is invalid")
    if command == "upload" and not producer:
        raise PreparationTransportError("Preparation transport role is invalid")
    if command == "download" and producer:
        raise PreparationTransportError("Preparation transport role is invalid")

    producer_id = ticket.get("producer_id")
    if not isinstance(producer_id, str) or not re.fullmatch(r"[0-9a-f]{64}", producer_id):
        raise PreparationTransportError("Preparation transport role is invalid")
    objects = ticket.get("objects")
    if not isinstance(objects, dict):
        raise PreparationTransportError("Preparation transport role is invalid")
    records = [record for record in objects.values() if isinstance(record, dict)]
    has_put = ["put_url" in record for record in records]
    has_get = ["get_url" in record for record in records]
    correct_capabilities = all(has_put) if producer else not any(has_put)
    expected_fields = {"get_url", "put_url"} if producer else {"get_url"}
    if (
        len(records) != len(ALLOWED_PATHS)
        or any(set(record) != expected_fields for record in records)
        or not all(has_get)
        or not correct_capabilities
    ):
        raise PreparationTransportError("Preparation transport role is invalid")
    return "producer" if producer else "consumer"


def _safe_relative(value: object) -> str:
    if not isinstance(value, str):
        raise PreparationTransportError("Preparation manifest path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value not in ALLOWED_PATHS:
        raise PreparationTransportError("Preparation manifest path is invalid")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_references(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PreparationTransportError("Preparation manifest is invalid")
    candidates = []
    for value in artifacts.values():
        if not isinstance(value, dict):
            raise PreparationTransportError("Preparation manifest is invalid")
        candidates.append(value)
    runtime = manifest.get("runtime_images")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("images"), list):
        raise PreparationTransportError("Preparation manifest is invalid")
    for value in runtime["images"]:
        if not isinstance(value, dict):
            raise PreparationTransportError("Preparation manifest is invalid")
        if value.get("archive_path"):
            candidates.append(
                {
                    "path": value.get("archive_path"),
                    "sha256": value.get("archive_sha256"),
                    "size": value.get("archive_size"),
                }
            )
    total = 0
    for value in candidates:
        relative = _safe_relative(value.get("path"))
        digest = value.get("sha256")
        size = value.get("size")
        if (
            relative == MANIFEST_PATH
            or relative in references
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(size, int)
            or size < 1
            or size > MAX_OBJECT_BYTES
        ):
            raise PreparationTransportError("Preparation manifest is invalid")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise PreparationTransportError("Preparation manifest exceeds transport limits")
        references[relative] = {"sha256": digest, "size": size}
    if not {"web.tar.gz", "translations.tar.gz"}.issubset(references):
        raise PreparationTransportError("Preparation manifest is incomplete")
    return references


def _load_manifest(
    path: Path,
    *,
    source: str,
    preparation_key: str,
    producer_run_id: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise PreparationTransportError("Preparation manifest is unavailable")
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raise PreparationTransportError("Preparation manifest is invalid") from None
    if (
        not isinstance(manifest, dict)
        or manifest.get("source_commit") != source
        or manifest.get("preparation_key") != preparation_key
        or str(manifest.get("producer_run_id", "")) != str(producer_run_id)
    ):
        raise PreparationTransportError("Preparation manifest identity mismatch")
    return manifest, _manifest_references(manifest)


def _connection_target(parsed: urllib.parse.SplitResult) -> str:
    return urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))


def _bounded_response(response: http.client.HTTPResponse) -> None:
    remaining = MAX_RESPONSE_BYTES + 1
    while remaining > 0:
        chunk = response.read(min(CHUNK_BYTES, remaining))
        if not chunk:
            break
        remaining -= len(chunk)


def put_file(
    url: str,
    path: Path,
    size: int,
    *,
    connection_factory: Callable[..., Any] = http.client.HTTPSConnection,
) -> None:
    value = _validate_url(url)
    parsed = urllib.parse.urlsplit(value)
    connection = connection_factory(
        parsed.hostname, parsed.port or 443, timeout=HTTP_TIMEOUT_SECONDS
    )
    try:
        connection.putrequest("PUT", _connection_target(parsed))
        connection.putheader("Content-Length", str(size))
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("x-amz-acl", "private")
        connection.endheaders()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
                connection.send(chunk)
        response = connection.getresponse()
        _bounded_response(response)
        if not 200 <= response.status < 300:
            raise PreparationTransportError("Preparation object upload was rejected")
    except PreparationTransportError:
        raise
    except Exception:
        raise PreparationTransportError("Preparation object upload failed") from None
    finally:
        connection.close()


def get_file(
    url: str,
    path: Path,
    max_bytes: int,
    *,
    expected_size: int | None = None,
    connection_factory: Callable[..., Any] = http.client.HTTPSConnection,
) -> int:
    value = _validate_url(url)
    parsed = urllib.parse.urlsplit(value)
    connection = connection_factory(
        parsed.hostname, parsed.port or 443, timeout=HTTP_TIMEOUT_SECONDS
    )
    try:
        connection.request("GET", _connection_target(parsed))
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            _bounded_response(response)
            raise PreparationTransportError("Preparation object download was rejected")
        header = response.getheader("Content-Length")
        if header:
            try:
                declared = int(header)
            except ValueError:
                raise PreparationTransportError(
                    "Preparation object has an invalid size"
                ) from None
            if declared > max_bytes or (
                expected_size is not None and declared != expected_size
            ):
                raise PreparationTransportError("Preparation object size mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        total = 0
        try:
            with os.fdopen(descriptor, "wb") as handle:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise PreparationTransportError(
                            "Preparation object exceeds transport limit"
                        )
                    handle.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if expected_size is not None and total != expected_size:
            path.unlink(missing_ok=True)
            raise PreparationTransportError("Preparation object size mismatch")
        return total
    except PreparationTransportError:
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise PreparationTransportError("Preparation object download failed") from None
    finally:
        connection.close()


def _ticket_url(ticket: Mapping[str, Any], relative: str, method: str) -> str:
    try:
        source = ticket["source"]
        preparation_key = ticket["preparation_key"]
        producer_id = ticket["producer_id"]
        return _validate_url(
            ticket["objects"][relative][method],
            expected_path=_object_url_path(
                source, preparation_key, producer_id, relative
            ),
        )
    except (KeyError, TypeError):
        raise PreparationTransportError("Preparation transport input is incomplete") from None


def upload_directory(
    directory: Path,
    ticket: Mapping[str, Any],
    *,
    source: str,
    preparation_key: str,
    producer_run_id: str,
    put: Callable[[str, Path, int], None] = put_file,
) -> dict[str, Any]:
    manifest_path = directory / MANIFEST_PATH
    _, references = _load_manifest(
        manifest_path,
        source=source,
        preparation_key=preparation_key,
        producer_run_id=producer_run_id,
    )
    actual_files = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise PreparationTransportError("Preparation directory contains a symlink")
        if path.is_file():
            actual_files.add(path.relative_to(directory).as_posix())
    if actual_files != set(references) | {MANIFEST_PATH}:
        raise PreparationTransportError("Preparation directory contains unexpected files")
    for relative, identity in references.items():
        path = directory / relative
        if (
            not path.is_file()
            or path.stat().st_size != identity["size"]
            or _sha256(path) != identity["sha256"]
        ):
            raise PreparationTransportError("Preparation object identity mismatch")
    for relative in sorted(references):
        put(_ticket_url(ticket, relative, "put_url"), directory / relative, references[relative]["size"])
    # Atomic publication boundary: consumers fetch this object before any bytes.
    put(
        _ticket_url(ticket, MANIFEST_PATH, "put_url"),
        manifest_path,
        manifest_path.stat().st_size,
    )
    return {
        "uploaded": len(references) + 1,
        "source_commit": source,
        "preparation_key": preparation_key,
        "producer_run_id": str(producer_run_id),
    }


def download_directory(
    directory: Path,
    ticket: Mapping[str, Any],
    *,
    source: str,
    preparation_key: str,
    prepared_run_id: str,
    get: Callable[[str, Path, int], int] = get_file,
) -> dict[str, Any]:
    if directory.is_symlink():
        raise PreparationTransportError(
            "Preparation destination contains a symlink"
        )
    directory = directory.resolve()
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="ci-preparation-", dir=directory.parent))
    try:
        manifest_path = temporary / MANIFEST_PATH
        get(
            _ticket_url(ticket, MANIFEST_PATH, "get_url"),
            manifest_path,
            MAX_MANIFEST_BYTES,
        )
        _, references = _load_manifest(
            manifest_path,
            source=source,
            preparation_key=preparation_key,
            producer_run_id=prepared_run_id,
        )
        for relative in sorted(references):
            identity = references[relative]
            target = temporary / relative
            get(
                _ticket_url(ticket, relative, "get_url"),
                target,
                min(MAX_OBJECT_BYTES, identity["size"]),
                expected_size=identity["size"],
            )
            if _sha256(target) != identity["sha256"]:
                raise PreparationTransportError("Preparation object digest mismatch")
        directory.mkdir(parents=True, exist_ok=True)
        for relative in ALLOWED_PATHS:
            existing = directory / relative
            if existing.is_symlink():
                raise PreparationTransportError(
                    "Preparation destination contains a symlink"
                )
            if existing.is_file():
                existing.unlink()
        for relative in sorted(references):
            source_path = temporary / relative
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source_path.replace(target)
        manifest_path.replace(directory / MANIFEST_PATH)
        return {
            "downloaded": len(references) + 1,
            "source_commit": source,
            "preparation_key": preparation_key,
            "producer_run_id": str(prepared_run_id),
        }
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    for name in ("upload", "download"):
        command = subparsers.add_parser(name)
        command.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise PreparationTransportError(
            "Preparation byte transfer is restricted to GitHub Actions"
        )
    ticket, inputs = event_ticket()
    source = str(os.environ.get("BUILD_COMMIT_SHA") or inputs.get("source_commit", ""))
    preparation_key = str(inputs.get("preparation_key", ""))
    role = validate_event_role(ticket, inputs, command=args.command)
    if args.command == "validate":
        result = {"role": role, "validated": True}
    elif args.command == "upload":
        if inputs.get("mode") != "prepare" or not os.environ.get("GITHUB_RUN_ID"):
            raise PreparationTransportError("Preparation producer identity is missing")
        result = upload_directory(
            args.directory.resolve(),
            ticket,
            source=source,
            preparation_key=preparation_key,
            producer_run_id=os.environ["GITHUB_RUN_ID"],
        )
    else:
        prepared_run_id = str(inputs.get("prepared_run_id", ""))
        if not prepared_run_id:
            raise PreparationTransportError("Preparation consumer identity is missing")
        result = download_directory(
            args.directory.resolve(),
            ticket,
            source=source,
            preparation_key=preparation_key,
            prepared_run_id=prepared_run_id,
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def entrypoint() -> int:
    """Keep capability-bearing input and exception causes out of CI logs."""

    try:
        return main()
    except Exception:
        print("Preparation transport failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
