"""Plan or apply a strictly scoped newsletter-image publication.

No general S3 service/reconciliation is used. Credentials remain publisher-only;
the complete authored manifest is validated before any provider side effects.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET

from botocore.exceptions import ClientError
import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.shared.python_utils.newsletter_assets import (
    ASSET_MAP_PATH, CI_S3_ENDPOINT, NEWSLETTER_S3_BUCKETS,
    NEWSLETTER_S3_PREFIX, NEWSLETTER_S3_REGION, REPO_ROOT, newsletter_isolated_s3,
    newsletter_public_policy, newsletter_s3_endpoint, newsletter_s3_url, validate_asset_manifest,
)

STATIC_DIR = Path("frontend/apps/website/static/newsletter-assets")
PRIVATE_PROBE_KEY = "newsletter-publication-probes/access-boundary.bin"
PRIVATE_PROBE_BYTES = b"OpenMates newsletter access-boundary probe\n"
CONTENT_TYPES = {"jpg": "image/jpeg", "svg": "image/svg+xml"}


def selected_bucket(environment: str) -> str:
    if environment not in NEWSLETTER_S3_BUCKETS:
        raise ValueError("Newsletter publication requires an exact development or production target")
    return NEWSLETTER_S3_BUCKETS[environment]


def _safe_local_path(root: Path, relative: Path) -> Path:
    path = root / relative
    for parent in [path, *path.parents]:
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise ValueError("Newsletter publication input must not contain symlinks")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Newsletter publication input is missing or outside the staged root")
    return path


def validate_image_bytes(filename: str, data: bytes, asset: dict) -> str:
    if len(data) != asset["size_bytes"] or hashlib.sha256(data).hexdigest() != filename.split(".", 1)[0]:
        raise ValueError("Newsletter image bytes do not match the immutable manifest identity")
    content_type = CONTENT_TYPES[filename.rsplit(".", 1)[1]]
    if content_type == "image/jpeg":
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG" or image.width > 1200 or image.height > 10000:
                raise ValueError("Newsletter JPEG content or dimensions are invalid")
            if asset.get("width", image.width) != image.width or asset.get("height", image.height) != image.height:
                raise ValueError("Newsletter image dimensions differ from the manifest")
            image.verify()
    else:
        if any(marker in data.upper() for marker in (b"<!DOCTYPE", b"<!ENTITY", b"<?XML-STYLESHEET")):
            raise ValueError("Newsletter SVG declarations are not allowed")
        root = ET.fromstring(data)
        if root.tag.split("}")[-1] != "svg":
            raise ValueError("Newsletter SVG root is invalid")
        for element in root.iter():
            if element.tag.split("}")[-1].lower() in {"script", "foreignobject", "style", "animate", "animatetransform", "animatemotion", "set"}:
                raise ValueError("Active newsletter SVG content is not allowed")
            for attribute, value in element.attrib.items():
                name = attribute.split("}")[-1].lower()
                if name.startswith("on") or (name == "href" and not value.startswith("#")) or "url(" in value.lower():
                    raise ValueError("Newsletter SVG external or active references are not allowed")
    return content_type


def validated_local_assets(repo_root: Path) -> tuple[dict, dict[str, dict]]:
    root = Path(repo_root).absolute()
    map_path = _safe_local_path(root, ASSET_MAP_PATH)
    if map_path.stat().st_size > 1024 * 1024:
        raise ValueError("Newsletter publication manifest exceeds its input bound")
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    validate_asset_manifest(payload)
    objects = {}
    for asset in payload["assets"].values():
        filename = asset["filename"]
        if filename in objects:
            continue
        path = _safe_local_path(root, STATIC_DIR / filename)
        if path.stat().st_size != asset["size_bytes"]:
            raise ValueError("Newsletter publication file size differs from manifest")
        data = path.read_bytes()
        content_type = validate_image_bytes(filename, data, asset)
        objects[filename] = {"data": data, "size": len(data), "content_type": content_type,
                             "sha256": hashlib.sha256(data).hexdigest()}
    return payload, objects


def validate_policy(policy: dict, bucket: str) -> None:
    expected = newsletter_public_policy(bucket)
    actual = deepcopy(policy)
    statements = actual.get("Statement") if isinstance(actual, dict) else None
    if not isinstance(statements, list) or len(statements) != 1:
        raise ValueError("Existing newsletter bucket policy is unexpected")
    statement = statements[0]
    if not isinstance(statement, dict):
        raise ValueError("Existing newsletter bucket policy is unexpected")
    # Accept only equivalent provider serialization of our exact single grant.
    for field in ("Action", "Resource"):
        if isinstance(statement.get(field), list) and len(statement[field]) == 1:
            statement[field] = statement[field][0]
    if statement.get("Principal") in ({"AWS": "*"}, {"AWS": ["*"]}):
        statement["Principal"] = "*"
    if actual != expected:
        raise ValueError("Existing newsletter bucket policy is unexpected")


def _error_status(error: ClientError) -> tuple[str, int | None]:
    return str(error.response.get("Error", {}).get("Code", "")), error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")


def _private_acl(client, bucket: str, key: str | None = None) -> None:
    acl = client.get_object_acl(Bucket=bucket, Key=key) if key else client.get_bucket_acl(Bucket=bucket)
    owner = acl.get("Owner", {}).get("ID")
    grants = acl.get("Grants")
    if (not owner or not isinstance(grants, list) or not grants
            or any(grant.get("Permission") != "FULL_CONTROL"
                   or grant.get("Grantee", {}).get("Type") != "CanonicalUser"
                   or grant.get("Grantee", {}).get("ID") != owner for grant in grants)):
        raise ValueError("Newsletter bucket has unexpected ACL grants")


def _bucket_objects(client, bucket: str, objects: dict) -> set[str]:
    expected = {NEWSLETTER_S3_PREFIX + filename: image["size"] for filename, image in objects.items()}
    expected[PRIVATE_PROBE_KEY] = len(PRIVATE_PROBE_BYTES)
    response = client.list_objects_v2(Bucket=bucket, MaxKeys=len(expected) + 1)
    if response.get("IsTruncated"):
        raise ValueError("Newsletter bucket contains unexpected additional objects")
    seen = set()
    for item in response.get("Contents", []):
        key = item.get("Key")
        if key not in expected or key in seen or item.get("Size") != expected[key]:
            raise ValueError("Newsletter bucket contains unexpected content")
        seen.add(key)
    return seen


def _verify_object(client, bucket: str, key: str, image: dict) -> None:
    _private_acl(client, bucket, key)
    head = client.head_object(Bucket=bucket, Key=key)
    if (head.get("ContentLength") != image["size"] or head.get("ContentType") != image["content_type"]
            or head.get("Metadata", {}).get("sha256") != image["sha256"]):
        raise ValueError("Existing newsletter object metadata differs from its declared identity")
    response = client.get_object(Bucket=bucket, Key=key)
    stream = response["Body"]
    try:
        data = stream.read(image["size"] + 1)
    finally:
        stream.close()
    if len(data) != image["size"] or hashlib.sha256(data).hexdigest() != image["sha256"]:
        raise ValueError("Existing newsletter object content differs from its declared identity")


def _put_missing_object(client, bucket: str, key: str, image: dict) -> None:
    try:
        client.put_object(
            Bucket=bucket, Key=key, Body=image["data"], ContentType=image["content_type"],
            CacheControl="public, max-age=31536000, immutable" if key.startswith(NEWSLETTER_S3_PREFIX) else "no-store",
            Metadata={"sha256": image["sha256"]}, ACL="private", IfNoneMatch="*",
        )
    except ClientError as error:
        code, status = _error_status(error)
        if code not in {"PreconditionFailed", "ConditionalRequestConflict"} and status not in {409, 412}:
            raise
        # A concurrent publication may have created the exact same object.
        # Never retry with an unconditional overwrite.
    _verify_object(client, bucket, key, image)


def _public_url(bucket: str, key: str) -> str:
    if newsletter_isolated_s3():
        return f"{CI_S3_ENDPOINT}/{bucket}/{key}"
    return f"https://{bucket}.nbg1.your-objectstorage.com/{key}"


def verify_public_boundary(public, bucket: str, objects: dict) -> None:
    for filename, image in objects.items():
        with public.stream("GET", newsletter_s3_url(bucket, filename)) as response:
            if (response.status_code != 200
                    or response.headers.get("content-type", "").split(";", 1)[0].strip() != image["content_type"]):
                raise ValueError("Newsletter public image is unavailable or differs from the manifest")
            digest, size = hashlib.sha256(), 0
            for chunk in response.iter_bytes(chunk_size=65536):
                size += len(chunk)
                if size > image["size"]:
                    raise ValueError("Newsletter public image exceeds the manifest byte bound")
                digest.update(chunk)
            if size != image["size"] or digest.hexdigest() != image["sha256"]:
                raise ValueError("Newsletter public image is unavailable or differs from the manifest")
    if public.get(_public_url(bucket, "") + "?list-type=2").status_code != 403:
        raise ValueError("Newsletter bucket anonymously exposes object listing")
    if public.get(_public_url(bucket, PRIVATE_PROBE_KEY)).status_code != 403:
        raise ValueError("Newsletter bucket exposes the private publication probe")
    # A new probe key avoids ever attempting to overwrite a declared image.
    write_name = hashlib.sha256(b"OpenMates anonymous write denial probe").hexdigest() + ".jpg"
    write_url = _public_url(bucket, NEWSLETTER_S3_PREFIX + write_name)
    if public.put(write_url, content=b"denial probe").status_code != 403:
        raise ValueError("Newsletter bucket did not reject anonymous writes")


def publish_to_s3(payload: dict, objects: dict, *, environment: str, client, public,
                  apply: bool = False, audit: dict | None = None) -> tuple[dict, dict | None]:
    """Every SDK operation names only the selected dedicated bucket explicitly."""
    bucket = selected_bucket(environment)
    asset_hash = validate_asset_manifest(payload)
    declared = {asset["filename"] for asset in payload["assets"].values()}
    if set(objects) != declared:
        raise ValueError("Newsletter publication must provide every declared image and no extras")
    for filename, image in objects.items():
        asset = next(asset for asset in payload["assets"].values() if asset["filename"] == filename)
        content_type = validate_image_bytes(filename, image["data"], asset)
        if image != {"data": image["data"], "size": len(image["data"]), "content_type": content_type,
                     "sha256": hashlib.sha256(image["data"]).hexdigest()}:
            raise ValueError("Newsletter publication object inventory is invalid")
    endpoint = newsletter_s3_endpoint()  # Fail before SDK calls on an unauthorized override.
    if client.meta.endpoint_url != endpoint or client.meta.region_name != NEWSLETTER_S3_REGION:
        raise ValueError("Newsletter SDK client is outside the selected endpoint/region")
    receipt = audit if audit is not None else {}
    receipt.update({"schema_version": 1, "environment": environment, "bucket": bucket, "region": NEWSLETTER_S3_REGION,
               "prefix": NEWSLETTER_S3_PREFIX, "asset_manifest_sha256": asset_hash,
               "object_count": len(objects), "apply": apply, "created_bucket": False,
               "uploaded": 0, "existing": 0, "status": "planned", "phase": "bucket-admission"})
    try:
        client.head_bucket(Bucket=bucket)
        exists = True
    except ClientError as error:
        code, status = _error_status(error)
        if code not in {"NoSuchBucket", "404"} and status != 404:
            raise
        exists = False
    if not exists:
        if not apply:
            receipt["would_create_bucket"] = True
            return receipt, None
        # Creation-only: never adopt or change an existing empty/private bucket.
        client.create_bucket(Bucket=bucket, ACL="private", CreateBucketConfiguration={"LocationConstraint": NEWSLETTER_S3_REGION})
        receipt["created_bucket"] = True
        if client.list_objects_v2(Bucket=bucket, MaxKeys=1).get("Contents"):
            raise ValueError("New newsletter bucket is not empty")
        try:
            client.get_bucket_policy(Bucket=bucket)
        except ClientError as error:
            if _error_status(error)[0] != "NoSuchBucketPolicy":
                raise
        else:
            raise ValueError("New newsletter bucket already has an unexpected policy")
        client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(newsletter_public_policy(bucket), sort_keys=True))
    policy = client.get_bucket_policy(Bucket=bucket)
    validate_policy(json.loads(policy["Policy"]), bucket)
    _private_acl(client, bucket)
    existing = _bucket_objects(client, bucket, objects)
    receipt["phase"] = "existing-object-verification"
    probe = {"data": PRIVATE_PROBE_BYTES, "size": len(PRIVATE_PROBE_BYTES), "content_type": "application/octet-stream",
             "sha256": hashlib.sha256(PRIVATE_PROBE_BYTES).hexdigest()}
    # Audit every existing declared object before any new writes.
    for filename, image in objects.items():
        if NEWSLETTER_S3_PREFIX + filename in existing:
            _verify_object(client, bucket, NEWSLETTER_S3_PREFIX + filename, image)
            receipt["existing"] += 1
    if PRIVATE_PROBE_KEY in existing:
        _verify_object(client, bucket, PRIVATE_PROBE_KEY, probe)
    if not apply:
        receipt["missing_objects"] = len(objects) - receipt["existing"]
        return receipt, None
    receipt["phase"] = "immutable-uploads"
    for filename, image in objects.items():
        key = NEWSLETTER_S3_PREFIX + filename
        if key not in existing:
            _put_missing_object(client, bucket, key, image)
            receipt["uploaded"] += 1
    if PRIVATE_PROBE_KEY not in existing:
        _put_missing_object(client, bucket, PRIVATE_PROBE_KEY, probe)
    receipt["phase"] = "public-boundary-verification"
    verify_public_boundary(public, bucket, objects)
    # Detect unexpected concurrent writes, including a failed denial probe.
    _bucket_objects(client, bucket, objects)
    validate_policy(json.loads(client.get_bucket_policy(Bucket=bucket)["Policy"]), bucket)
    _private_acl(client, bucket)
    ready = deepcopy(payload)
    ready.setdefault("s3_publications", {})[environment] = {
        "bucket": bucket, "region": NEWSLETTER_S3_REGION, "prefix": NEWSLETTER_S3_PREFIX,
        "asset_manifest_sha256": asset_hash, "object_count": len(objects),
        "verified_filenames": sorted(objects), "verified_public": True,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    ready["delivery_transport"] = "s3"
    receipt.update(status="verified", phase="complete", anonymous_get=True, anonymous_list_denied=True,
                   private_prefix_denied=True, anonymous_write_denied=True)
    return receipt, ready


def atomic_json(path: Path, payload: dict) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Newsletter publication output must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".newsletter-publication-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=tuple(NEWSLETTER_S3_BUCKETS), required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)  # Vault/provider details never enter operator output.
    if args.receipt.exists() or any(path.is_symlink() for path in (args.receipt, *args.receipt.parents)):
        raise ValueError("Newsletter publication requires a new private receipt path without symlinks")
    payload, objects = validated_local_assets(args.repo_root)
    endpoint = newsletter_s3_endpoint()
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    import boto3
    from botocore.config import Config

    secrets = SecretsManager()
    receipt = {"schema_version": 1, "status": "failed", "bucket": selected_bucket(args.environment)}
    try:
        await secrets.initialize()
        access = await secrets.get_secret(secret_path="kv/data/providers/hetzner", secret_key="s3_access_key")
        secret = await secrets.get_secret(secret_path="kv/data/providers/hetzner", secret_key="s3_secret_key")
        if not access or not secret:
            raise RuntimeError("Newsletter publisher credentials are unavailable")
        client = boto3.client("s3", endpoint_url=endpoint, region_name=NEWSLETTER_S3_REGION,
                              aws_access_key_id=access, aws_secret_access_key=secret,
                              config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                            connect_timeout=10, read_timeout=20, retries={"max_attempts": 0}))
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as public:
                receipt, ready = publish_to_s3(payload, objects, environment=args.environment, client=client,
                                              public=public, apply=args.apply, audit=receipt)
            if ready is not None:
                atomic_json(args.repo_root / ASSET_MAP_PATH, ready)
        finally:
            client.close()
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__)
        if isinstance(error, ClientError):
            receipt["provider_error_code"] = _error_status(error)[0]
        elif isinstance(error, (ValueError, RuntimeError)):
            receipt["reason"] = str(error)
        raise RuntimeError("Newsletter publication failed; inspect the private receipt") from None
    finally:
        atomic_json(args.receipt, receipt)
        await secrets.aclose()
    print(json.dumps({"status": receipt["status"], "bucket": receipt["bucket"], "objects": len(objects)}))
    return 0


if __name__ == "__main__":
    asyncio.run(main())
