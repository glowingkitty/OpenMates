"""File-mapped regional storage job processor tests.

The session deploy checker maps tests by source filename, so this file keeps
direct coverage discoverable for job_processor.py while the broader replication
worker suite exercises the larger contract. No real S3 or Directus calls run.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

from io import BytesIO
import hashlib
import importlib

from backend.tests.s3_service_test_support import ensure_s3_dependencies


def _module():
    ensure_s3_dependencies()
    return importlib.import_module("backend.core.api.app.services.s3.job_processor")


class _MemoryS3Client:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects
        self.uploads: list[tuple[str, str, dict]] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        return {"ContentType": "application/octet-stream", "Metadata": {}}

    def download_fileobj(self, bucket: str, key: str, fileobj: BytesIO) -> None:
        fileobj.write(self.objects[(bucket, key)])

    def upload_fileobj(self, fileobj: BytesIO, bucket: str, key: str, *, ExtraArgs: dict) -> None:
        self.objects[(bucket, key)] = fileobj.read()
        self.uploads.append((bucket, key, ExtraArgs))

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}


class _S3Service:
    environment = "development"

    def __init__(self, source: _MemoryS3Client, target: _MemoryS3Client) -> None:
        self.region_clients = {"nbg1": source, "fsn1": target}
        self.upload_region_clients = {"fsn1": target}


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.integrity.observable-reconcilable
def test_job_processor_copies_ciphertext_to_regional_bucket_and_verifies_checksum(monkeypatch) -> None:
    module = _module()
    ciphertext = b"encrypted regional payload"
    source_bucket = "chatfiles-nbg1"
    target_bucket = "chatfiles-fsn1"
    object_key = "owner/file.enc"
    objects = {(source_bucket, object_key): ciphertext}
    source = _MemoryS3Client(objects)
    target = _MemoryS3Client(objects)
    processor = module.RegionalStorageJobProcessor(
        directus_service=object(),
        s3_service=_S3Service(source, target),
    )
    monkeypatch.setattr(module, "get_bucket_name", lambda _bucket, _environment: "chatfiles")
    monkeypatch.setattr(module, "get_bucket_config", lambda _bucket: {"access": "private"})
    monkeypatch.setattr(module, "resolve_regional_bucket_name", lambda bucket, region: f"{bucket}-{region}")

    processor._copy_immutable_object(
        {
            "active_region": "nbg1",
            "logical_bucket": "chatfiles",
            "object_key": object_key,
            "checksum": hashlib.sha256(ciphertext).hexdigest(),
        },
        "fsn1",
    )

    assert objects[(target_bucket, object_key)] == ciphertext
    assert target.uploads[0][2]["Metadata"] == {"openmates-sha256": hashlib.sha256(ciphertext).hexdigest()}
