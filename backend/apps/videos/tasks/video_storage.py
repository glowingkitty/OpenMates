"""Encrypted storage of a videos.generate result and the files kept with it.

One AES key per stored version encrypts every object it uploads with the
nonce-prefixed media format (``encrypt_media_variants``): the MP4
(``original``), its thumbnail (``thumbnail``) and, as ``extra`` objects, the
files a later change of the video needs (a generated clip, copies of the input
pictures). The key is wrapped with the owner's Vault key; the wrapped key and
each object's encryption marker are what the kept record
(``video_kept.py``) and the generated-asset index hold, so the server can read
the files again for the owner only.

The chat child lists only ``original`` and ``thumbnail``. The generated-asset
index lists every uploaded object, so the account's storage counts all of them,
and every object key is in the embed's file index so it is deleted with the
embed. An upload that fails part-way removes what it already uploaded.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

CHATFILES = "chatfiles"
PUBLIC_VARIANTS = ("original", "thumbnail")


@dataclass(frozen=True)
class StoredObject:
    """One encrypted object the server can read again for its owner."""

    s3_key: str
    variant: dict[str, Any]  # encryption marker (and nonce of legacy objects)
    vault_wrapped_aes_key: str
    size_bytes: int

    def to_json(self) -> dict[str, Any]:
        return {"s3_key": self.s3_key, "variant": dict(self.variant),
                "vault_wrapped_aes_key": self.vault_wrapped_aes_key, "size_bytes": self.size_bytes}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "StoredObject":
        key, variant, wrapped = data.get("s3_key"), data.get("variant"), data.get("vault_wrapped_aes_key")
        size = data.get("size_bytes")
        if (not isinstance(key, str) or not key or not isinstance(variant, Mapping) or not isinstance(wrapped, str)
                or not wrapped or not isinstance(size, int)):
            raise ValueError("stored object reference is incomplete")
        return cls(s3_key=key, variant=dict(variant), vault_wrapped_aes_key=wrapped, size_bytes=size)


@dataclass(frozen=True)
class StoredVideo:
    files_metadata: dict[str, dict[str, Any]]  # original + thumbnail, as the chat child lists them
    extra_metadata: dict[str, dict[str, Any]]  # objects kept for later changes (clip, input copies)
    aes_key_b64: str
    nonce_b64: str
    vault_wrapped_aes_key: str
    s3_base_url: str
    uploaded_keys: tuple[str, ...] = field(default_factory=tuple)

    def object(self, name: str) -> StoredObject:
        meta = self.files_metadata.get(name) or self.extra_metadata.get(name)
        if meta is None:
            raise KeyError(name)
        variant = {key: meta[key] for key in ("encryption", "aes_nonce") if meta.get(key)}
        return StoredObject(s3_key=meta["s3_key"], variant=variant, vault_wrapped_aes_key=self.vault_wrapped_aes_key,
                            size_bytes=int(meta["size_bytes"]))

    def file_keys(self) -> list[dict[str, str]]:
        return [{"bucket": CHATFILES, "key": key} for key in self.uploaded_keys]

    @property
    def size_bytes(self) -> int:
        return sum(int(meta.get("size_bytes") or 0) for meta in (*self.files_metadata.values(),
                                                                 *self.extra_metadata.values()))


async def upload_video_files(
    task: Any, *, s3_service: Any, bucket_name: str, user_id: str, mp4: bytes, thumbnail: bytes,
    thumbnail_format: str, vault_key_id: str, label: str, extra: Optional[Mapping[str, tuple[bytes, str, str]]] = None,
) -> StoredVideo:
    """Encrypt and upload the video, its thumbnail and ``extra`` objects (name → bytes, extension, mime type)."""
    from backend.shared.python_utils.media_encryption import encrypt_media_variants, load_media_write_version

    plain: dict[str, tuple[bytes, str, str]] = {
        "original": (mp4, "mp4", "video/mp4"),
        "thumbnail": (thumbnail, thumbnail_format, f"image/{'jpeg' if thumbnail_format == 'jpg' else thumbnail_format}"),
        **dict(extra or {}),
    }
    encrypted = encrypt_media_variants({name: item[0] for name, item in plain.items()},
                                       write_version=load_media_write_version())
    wrapped_key, _ = await task._encryption_service.encrypt_with_user_key(encrypted.aes_key_b64, vault_key_id)
    if not wrapped_key:
        raise RuntimeError("Failed to wrap the AES key of the video with Vault")
    prefix = f"{user_id}/{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{label}"
    public: dict[str, dict[str, Any]] = {}
    kept: dict[str, dict[str, Any]] = {}
    uploaded: list[str] = []
    try:
        for name, (content, extension, mime_type) in plain.items():
            file_key = f"{prefix}_{name}.{extension}"
            await s3_service.upload_file(CHATFILES, file_key, encrypted.payloads[name], "application/octet-stream")
            uploaded.append(file_key)
            meta = {"s3_key": file_key, "size_bytes": len(content), "format": extension, "mime_type": mime_type,
                    **encrypted.metadata[name]}
            if encrypted.legacy_nonce_b64 and not encrypted.metadata[name]:
                meta["aes_nonce"] = encrypted.legacy_nonce_b64
            (public if name in PUBLIC_VARIANTS else kept)[name] = meta
    except BaseException:
        for file_key in uploaded:
            await s3_service.delete_file(CHATFILES, file_key)
        raise
    return StoredVideo(files_metadata=public, extra_metadata=kept, aes_key_b64=encrypted.aes_key_b64,
                       nonce_b64=encrypted.legacy_nonce_b64 or "", vault_wrapped_aes_key=wrapped_key,
                       s3_base_url=f"https://{bucket_name}.{s3_service.base_domain}", uploaded_keys=tuple(uploaded))


async def delete_video_files(s3_service: Any, stored: StoredVideo) -> None:
    for file_key in stored.uploaded_keys:
        await s3_service.delete_file(CHATFILES, file_key)


async def index_video(
    task: Any, stored: StoredVideo, *, user_id: str, embed_id: str, mp4: bytes, provenance: Mapping[str, Any],
    log_prefix: str, existing_record_id: Optional[str] = None, retained_size_bytes: int = 0,
) -> bool:
    """Index the version in the owner's generated-asset index (a revision re-points the existing row)."""
    from backend.shared.python_utils.generated_assets import index_generated_asset

    return await index_generated_asset(
        task, user_id=user_id, embed_id=embed_id, media_type="video",
        files_metadata={**stored.files_metadata, **stored.extra_metadata}, s3_base_url=stored.s3_base_url,
        aes_key_b64=stored.aes_key_b64, nonce_b64=stored.nonce_b64,
        vault_wrapped_aes_key=stored.vault_wrapped_aes_key, created_at=int(datetime.now(timezone.utc).timestamp()),
        content_hash_source=mp4, original_filename=f"openmates_video_{embed_id[:8]}.mp4", content_type="video/mp4",
        log_prefix=log_prefix, provenance_metadata=dict(provenance), existing_record_id=existing_record_id,
        retained_size_bytes=retained_size_bytes,
    )


async def read_stored_object(task: Any, *, s3_service: Any, bucket_name: str, stored: StoredObject,
                             vault_key_id: str) -> Optional[bytes]:
    """Decrypt one kept object for its owner; ``None`` when the object is gone."""
    import base64
    import binascii

    from backend.shared.python_utils.media_encryption import decrypt_media_payload

    aes_key_b64 = await task._encryption_service.decrypt_with_user_key(stored.vault_wrapped_aes_key, vault_key_id)
    try:
        aes_key = base64.b64decode(aes_key_b64 or "", validate=True)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise RuntimeError("A kept video file has an unreadable key") from exc
    encrypted = await s3_service.get_file(bucket_name=bucket_name, object_key=stored.s3_key)
    if not encrypted:
        return None
    return decrypt_media_payload(encrypted_data=encrypted, aes_key=aes_key, variant=stored.variant,
                                 legacy_nonce_b64=stored.variant.get("aes_nonce"))


async def cache_embed_file_keys(task: Any, *, embed_id: str, keys: list[dict[str, str]], ttl_seconds: int = 3600
                                ) -> None:
    """Leave the files of a first version for ``store_embed`` (embed deletion removes every one of them)."""
    import json

    client = await task._cache_service.client
    if not client:
        raise RuntimeError("File index cache is unavailable for a generated video")
    await client.set(f"embed:{embed_id}:s3_file_keys", json.dumps(keys), ex=ttl_seconds)
