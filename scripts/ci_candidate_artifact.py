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
MAX_PATCH_BYTES = 100 * 1024**2

INNER_UPLOAD_CODE = r'''
import asyncio
import hashlib
import json
import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from backend.core.api.app.utils.secrets_manager import SecretsManager

REQUEST = json.loads(os.environ["OPENMATES_CI_CANDIDATE_REQUEST"])


async def main():
    content = sys.stdin.buffer.read(REQUEST["size"] + 1)
    if len(content) != REQUEST["size"] or hashlib.sha256(content).hexdigest() != REQUEST["sha256"]:
        raise RuntimeError("CI candidate stream differs from the verified patch")
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
    created = False
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
            raise
        client.create_bucket(Bucket=bucket)
        created = True
        time.sleep(2)
    # Hetzner creates buckets private by default. Verify privacy without
    # requiring permission to rewrite the bucket ACL for every candidate.
    acl = client.get_bucket_acl(Bucket=bucket)
    owner = acl["Owner"]["ID"]
    if not acl["Grants"] or any(
        grant["Grantee"].get("Type") != "CanonicalUser" or grant["Grantee"].get("ID") != owner
        for grant in acl["Grants"]
    ):
        raise RuntimeError("CI candidate bucket ACL must grant access only to its owner")
    try:
        client.get_bucket_policy(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchBucketPolicy":
            raise
    else:
        raise RuntimeError("CI candidate bucket must not have a bucket policy")
    expiry_rule = {
        "ID": "ExpireCiCandidatesAfterTwoDays",
        "Status": "Enabled",
        "Filter": {"Prefix": "candidates/"},
        "Expiration": {"Days": int(REQUEST["lifecycle_days"])},
    }
    if created:
        client.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules": [expiry_rule]})
    rules = client.get_bucket_lifecycle_configuration(Bucket=bucket)["Rules"]
    if expiry_rule not in rules:
        raise RuntimeError("CI candidate bucket must have the enabled two-day expiry rule")
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


def _run(command: list[str], *, env: dict[str, str], input_bytes: bytes) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, input=input_bytes, capture_output=True, env=env, check=False)
    return subprocess.CompletedProcess(
        result.args, result.returncode,
        result.stdout.decode(errors="replace"), result.stderr.decode(errors="replace"),
    )


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
    request = {
        "bucket": BUCKET_NAME,
        "key": key,
        "size": len(content),
        "source": source,
        "sha256": sha256,
        "lifecycle_days": LIFECYCLE_DAYS,
        "expires_in": EXPIRES_SECONDS,
    }
    env = {**os.environ, "OPENMATES_CI_CANDIDATE_REQUEST": json.dumps(request, sort_keys=True)}
    uploaded = _run(
        ["docker", "exec", "-i", "-e", "OPENMATES_CI_CANDIDATE_REQUEST", container, "python", "-c", INNER_UPLOAD_CODE],
        env=env,
        input_bytes=content,
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
