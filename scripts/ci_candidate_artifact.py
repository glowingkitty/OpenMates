#!/usr/bin/env python3
"""Upload private, expiring CI candidate patches through the API container."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import uuid


BUCKET_NAME = "dev-openmates-ci-candidates"
LIFECYCLE_DAYS = 2
EXPIRES_SECONDS = 48 * 60 * 60
DEFAULT_CONTAINER = "api"
CONTAINER_TMP_DIR = "/tmp/openmates-ci-candidates"
MAX_PATCH_BYTES = 100 * 1024**2

INNER_UPLOAD_CODE = r'''
import asyncio
import json
import os
from pathlib import Path
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from backend.core.api.app.utils.secrets_manager import SecretsManager

REQUEST = json.loads(os.environ["OPENMATES_CI_CANDIDATE_REQUEST"])


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
    bucket = REQUEST["bucket"]
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
            raise
        client.create_bucket(Bucket=bucket)
        time.sleep(2)
    client.put_bucket_acl(Bucket=bucket, ACL="private")
    client.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={"Rules": [{
            "ID": "ExpireCiCandidatesAfterTwoDays",
            "Status": "Enabled",
            "Filter": {"Prefix": "candidates/"},
            "Expiration": {"Days": int(REQUEST["lifecycle_days"])},
        }]},
    )
    content = Path(REQUEST["container_path"]).read_bytes()
    client.put_object(
        Bucket=bucket,
        Key=REQUEST["key"],
        Body=content,
        ContentType="application/octet-stream",
        CacheControl="private, no-store",
        ACL="private",
        Metadata={
            "purpose": "openmates-ci-candidate",
            "candidate-sha": REQUEST["source"],
            "source-sha256": REQUEST["sha256"],
        },
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": REQUEST["key"]},
        ExpiresIn=int(REQUEST["expires_in"]),
    )
    print(json.dumps({"bucket": bucket, "key": REQUEST["key"], "url": url}))


asyncio.run(main())
'''


def validate_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".your-objectstorage.com")
        or parsed.username
        or parsed.password
        or not parsed.query
        or parsed.fragment
    ):
        raise ValueError("CI candidate URL must be a presigned Hetzner HTTPS URL")
    return value


def _run(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, env=env, check=False)


def upload_patch(
    patch_path: Path,
    *,
    source: str,
    sha256: str,
    container: str = DEFAULT_CONTAINER,
    now: dt.datetime | None = None,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("CI candidate source must be a full commit SHA")
    content = patch_path.read_bytes()
    if len(content) > MAX_PATCH_BYTES:
        raise ValueError("CI candidate patch exceeds 100 MiB")
    if hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError("CI candidate patch digest changed before upload")
    instant = now or dt.datetime.now(dt.timezone.utc)
    key = f"candidates/{instant:%Y/%m/%d}/{source}/{uuid.uuid4().hex}-{sha256}.patch"
    container_path = f"{CONTAINER_TMP_DIR}/{uuid.uuid4().hex}.patch"
    request = {
        "bucket": BUCKET_NAME,
        "key": key,
        "container_path": container_path,
        "source": source,
        "sha256": sha256,
        "lifecycle_days": LIFECYCLE_DAYS,
        "expires_in": EXPIRES_SECONDS,
    }
    mkdir = _run(["docker", "exec", container, "mkdir", "-p", CONTAINER_TMP_DIR])
    if mkdir.returncode:
        raise RuntimeError(mkdir.stderr.strip() or mkdir.stdout.strip())
    copied = _run(["docker", "cp", str(patch_path), f"{container}:{container_path}"])
    if copied.returncode:
        raise RuntimeError(copied.stderr.strip() or copied.stdout.strip())
    try:
        env = {**os.environ, "OPENMATES_CI_CANDIDATE_REQUEST": json.dumps(request, sort_keys=True)}
        uploaded = _run(
            ["docker", "exec", "-e", "OPENMATES_CI_CANDIDATE_REQUEST", container, "python", "-c", INNER_UPLOAD_CODE],
            env=env,
        )
        if uploaded.returncode:
            raise RuntimeError(uploaded.stderr.strip() or uploaded.stdout.strip())
        lines = [line for line in uploaded.stdout.splitlines() if line.strip().startswith("{")]
        if not lines:
            raise RuntimeError("CI candidate upload completed without JSON output")
        result = json.loads(lines[-1])
        validate_url(result["url"])
        expires_at = instant + dt.timedelta(seconds=EXPIRES_SECONDS)
        return {**result, "expires_at": expires_at.isoformat()}
    finally:
        _run(["docker", "exec", container, "rm", "-f", container_path])
