"""Camera source bytes survive normal preview generation and media encryption."""
import base64
import hashlib
import io

import pytest
from PIL import Image

from backend.upload.services.preview_generator import _process_sync, _is_safe_camera_jpeg
from backend.shared.python_utils.media_encryption import encrypt_media_variants, decrypt_media_payload


def camera_jpeg(*, size=(96, 54), progressive=False):
    image = Image.new("RGB", size)
    image.putdata([((x * 17) % 256, (x * 29) % 256, (x * 43) % 256)
                   for x in range(size[0] * size[1])])
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=63, progressive=progressive)
    raw = output.getvalue()
    # Browser canvas emits APP0/JFIF. The normal upload-privacy sanitizer drops
    # this entire segment, leaving its baseline tables/frame/scan bytes intact.
    assert raw[2:4] == b"\xff\xe0" and raw[6:11] == b"JFIF\x00"
    app0_end = 4 + int.from_bytes(raw[4:6], "big")
    return raw[:2] + raw[app0_end:]


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.parametrize("write_version", [1, 2])
def test_canonical_camera_jpeg_original_is_exact_through_real_encryption(write_version):
    source = camera_jpeg()
    result = _process_sync(source)
    assert result.original_bytes == source
    assert (result.original_width, result.original_height) == (96, 54)
    assert Image.open(io.BytesIO(result.full_webp_bytes)).format == "WEBP"
    assert (result.full_width, result.full_height) == (96, 54)
    assert (result.preview_width, result.preview_height) == (600, 400)
    # These are the same production primitives and variant inputs used by the
    # upload route's encryption step, without mocking the encryption boundary.
    variants = encrypt_media_variants({"original": result.original_bytes,
        "full": result.full_webp_bytes, "preview": result.preview_webp_bytes}, write_version=write_version)
    opened = decrypt_media_payload(encrypted_data=variants.payloads["original"],
        aes_key=base64.b64decode(variants.aes_key_b64), variant=variants.metadata["original"],
        legacy_nonce_b64=variants.legacy_nonce_b64)
    assert hashlib.sha256(opened).digest() == hashlib.sha256(source).digest()
    assert opened == source


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.parametrize("marker", [0xE0, 0xE1, 0xE2, 0xED, 0xEF, 0xFE])
def test_jpeg_metadata_cannot_enter_byte_preservation_path(marker):
    source = camera_jpeg()
    secret = b"Private GPS/camera identity and XMP owner secret"
    prefixes = {0xE0: b"JFIF\x00", 0xE1: b"Exif\x00\x00", 0xE2: b"ICC_PROFILE\x00",
                0xED: b"Photoshop 3.0\x00", 0xEF: b"Private\x00", 0xFE: b""}
    payload = prefixes[marker] + secret
    segment = bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload
    contaminated = source[:2] + segment + source[2:]
    assert not _is_safe_camera_jpeg(contaminated, 96, 54, "RGB")
    result = _process_sync(contaminated)
    assert result.original_bytes != contaminated
    assert secret not in result.original_bytes
    assert secret not in result.full_webp_bytes and secret not in result.preview_webp_bytes
    Image.open(io.BytesIO(result.original_bytes)).load()


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.parametrize("suffix", [b"Private trailing GPS secret", camera_jpeg()])
def test_jpeg_trailing_payload_is_removed_instead_of_preserved(suffix):
    source = camera_jpeg() + suffix
    assert not _is_safe_camera_jpeg(source, 96, 54, "RGB")
    result = _process_sync(source)
    assert result.original_bytes != source and result.original_bytes.endswith(b"\xff\xd9")
    assert b"Private trailing GPS secret" not in result.original_bytes
    assert result.original_bytes.count(b"\xff\xd8") == 1


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.parametrize("profile", ["progressive", "oversize", "large-dimensions"])
def test_non_camera_jpeg_profiles_keep_original_reencoding(profile):
    source = camera_jpeg(size=(1281, 4) if profile == "large-dimensions" else (96, 54),
                         progressive=profile == "progressive")
    if profile == "oversize":
        # A valid JPEG scan may have arbitrarily many quantization/Huffman table
        # repetitions. Conservative size bounds must still reject preservation.
        table_length = int.from_bytes(source[4:6], "big")
        table = source[2:4 + table_length]
        assert table[:2] == b"\xff\xdb"
        source = source[:2] + table * (256 * 1024 // len(table) + 1) + source[2:]
    result = _process_sync(source)
    assert result.original_bytes != source
    assert (result.original_width, result.original_height) == ((1281, 4) if profile == "large-dimensions" else (96, 54))
    Image.open(io.BytesIO(result.original_bytes)).load()


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.parametrize("corrupt", [lambda value: value[:-2], lambda value: value[:4] + b"\xff\xff" + value[6:]])
def test_truncated_or_malformed_jpeg_cannot_be_retained(corrupt):
    source = corrupt(camera_jpeg())
    assert not _is_safe_camera_jpeg(source, 96, 54, "RGB")
    try:
        result = _process_sync(source)
    except (ValueError, OSError, SyntaxError):
        return
    assert result.original_bytes != source


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
def test_multiscan_and_cmyk_are_not_camera_preservation_profiles():
    source = camera_jpeg()
    scan_start = source.index(b"\xff\xda")
    scan_length = int.from_bytes(source[scan_start + 2:scan_start + 4], "big")
    scan_header = source[scan_start:scan_start + 2 + scan_length]
    multiscan = source[:-2] + scan_header + source[scan_start + 2 + scan_length:]
    assert not _is_safe_camera_jpeg(multiscan, 96, 54, "RGB")
    try:
        result = _process_sync(multiscan)
    except (ValueError, OSError, SyntaxError):
        pass
    else:
        assert result.original_bytes != multiscan
    output = io.BytesIO()
    Image.new("CMYK", (96, 54)).save(output, format="JPEG")
    assert not _is_safe_camera_jpeg(output.getvalue(), 96, 54, "CMYK")
    assert _process_sync(output.getvalue()).original_bytes != output.getvalue()


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance
@pytest.mark.parametrize("image_format", ["PNG", "WEBP"])
def test_other_image_formats_keep_their_existing_variants(image_format):
    output = io.BytesIO()
    Image.new("RGB", (96, 54), "navy").save(output, format=image_format)
    source = output.getvalue()
    assert not _is_safe_camera_jpeg(source, 96, 54, "RGB")
    result = _process_sync(source)
    assert Image.open(io.BytesIO(result.original_bytes)).format == image_format
    assert (result.full_width, result.full_height) == (96, 54)
    assert (result.preview_width, result.preview_height) == (600, 400)


async def run_upload_unit(monkeypatch, source, record, *, target_env="dev", exists=True):
    """Call the production coroutine directly; only external I/O is substituted."""
    from copy import deepcopy
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from starlette.datastructures import Headers, UploadFile
    from backend.upload.routes import upload_route as route
    from backend.upload.services.preview_generator import PreviewGeneratorService

    original_record = deepcopy(record)
    objects = {}
    async def upload(**options):
        objects[options["s3_key"]] = options["content"]
        return SimpleNamespace(key=options["s3_key"], region="primary")
    s3 = SimpleNamespace(upload_file_with_region=AsyncMock(side_effect=upload),
        check_file_exists=AsyncMock(return_value=exists),
        get_base_url=Mock(side_effect=lambda target_env, region=None: f"https://{target_env}.{region or 'primary'}.test"))
    scanner = SimpleNamespace(scan=AsyncMock(return_value=SimpleNamespace(is_clean=True)))
    sightengine = SimpleNamespace(is_enabled=True, check_all=AsyncMock(return_value=(
        SimpleNamespace(is_safe=True), SimpleNamespace(ai_generated=0.0, provider="fixture", error=None))))
    request = SimpleNamespace(headers={"X-Target-Env": target_env},
        # A client may submit arbitrary extra form metadata; the actual route
        # accepts only file bytes and cannot turn this claim into stored proof.
        form=AsyncMock(return_value={"preserved_original_sha256": "0" * 64}),
        app=SimpleNamespace(state=SimpleNamespace(s3=s3, malware_scanner=scanner,
            sightengine=sightengine, preview_generator=PreviewGeneratorService())))
    monkeypatch.setattr(route, "_get_core_api_credentials", lambda request: ("https://internal.test", "service-token"))
    monkeypatch.setattr(route, "_check_duplicate_via_api", AsyncMock(return_value=record))
    monkeypatch.setattr(route, "_wrap_key_via_api", AsyncMock(return_value="vault:v1:wrapped"))
    store, cache = AsyncMock(), AsyncMock(return_value=True)
    monkeypatch.setattr(route, "_store_record_via_api", store)
    monkeypatch.setattr(route, "_cache_embed_via_api", cache)
    monkeypatch.setattr(route, "load_media_write_version", lambda: 2)
    file = UploadFile(io.BytesIO(source), filename="camera-frame.jpg", headers=Headers({
        "content-type": "image/jpeg", "preserved_original_sha256": "0" * 64}))
    response = await route.upload_file(request=request, file=file, user={"user_id": "owner-id", "vault_key_id": "owner-vault"})
    assert record == original_record  # No immutable legacy references are rewritten.
    return response, objects, store, cache, s3, scanner, request


def duplicate_record(source, *, proof=None):
    metadata = {name: {"s3_key": f"owner/hash/legacy-embed/{name}.bin", "width": 96, "height": 54,
        "size_bytes": 100, "format": "webp", "active_region": "secondary"}
        for name in ("original", "full", "preview")}
    if proof is not None:
        metadata["original"]["preserved_original_sha256"] = proof
    return {"embed_id": "legacy-embed", "content_hash": hashlib.sha256(source).hexdigest(),
        "files_metadata": metadata, "aes_key": base64.b64encode(b"k" * 32).decode(), "aes_nonce": "old-nonce",
        "vault_wrapped_aes_key": "vault:v1:old", "content_type": "image/jpeg",
        "ai_detection": {"status": "success", "ai_generated": 0.0, "provider": "fixture"}}


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("target_env", ["dev", "prod"])
@pytest.mark.parametrize("proof_status", ["legacy", "rewritten", "exact"])
async def test_actual_upload_dedup_requires_server_proof_before_any_region_reuse(monkeypatch, target_env, proof_status):
    source = camera_jpeg()
    output = io.BytesIO()
    Image.open(io.BytesIO(source)).save(output, format="JPEG", quality=98)
    assert output.getvalue() != source
    source_hash = hashlib.sha256(source).hexdigest()
    proof = None if proof_status == "legacy" else hashlib.sha256(output.getvalue()).hexdigest()
    if proof_status == "exact":
        proof = source_hash
    record = duplicate_record(source, proof=proof)
    response, objects, store, cache, s3, scanner, request = await run_upload_unit(
        monkeypatch, source, record, target_env=target_env)
    request.form.assert_not_awaited()
    if proof_status == "exact":
        assert response.deduplicated and response.embed_id == record["embed_id"]
        assert response.files["original"].preserved_original_sha256 == source_hash
        assert response.s3_base_url == f"https://{target_env}.secondary.test"
        assert len(s3.check_file_exists.await_args_list) == 3
        assert all(call.kwargs == {"target_env": target_env, "region": "secondary"}
                   for call in s3.check_file_exists.await_args_list)
        store.assert_not_awaited()
        cache.assert_not_awaited()
        scanner.scan.assert_not_awaited()
        assert not objects
    else:
        assert not response.deduplicated and response.embed_id != record["embed_id"]
        scanner.scan.assert_awaited_once_with(source)
        store.assert_awaited_once()
        saved = store.await_args.args[2]
        assert saved["embed_id"] == response.embed_id
        assert saved["files_metadata"]["original"]["preserved_original_sha256"] == source_hash
        original = response.files["original"]
        assert original.s3_key not in {item["s3_key"] for item in record["files_metadata"].values()}
        opened = decrypt_media_payload(encrypted_data=objects[original.s3_key],
            aes_key=base64.b64decode(response.aes_key), variant=original.model_dump(), legacy_nonce_b64=response.aes_nonce)
        assert opened == source
        assert hashlib.sha256(opened).hexdigest() == saved["files_metadata"]["original"]["preserved_original_sha256"]
        assert set(objects) == {variant.s3_key for variant in response.files.values()}


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
async def test_exact_dedup_proof_does_not_bypass_missing_s3_fallback(monkeypatch):
    source = camera_jpeg()
    record = duplicate_record(source, proof=hashlib.sha256(source).hexdigest())
    response, _, store, _, s3, _, _ = await run_upload_unit(monkeypatch, source, record, exists=False)
    assert not response.deduplicated and response.embed_id != record["embed_id"]
    s3.check_file_exists.assert_awaited()
    store.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
async def test_ordinary_jpeg_dedup_does_not_promote_legacy_or_client_proof(monkeypatch):
    output = io.BytesIO()
    Image.new("RGB", (96, 54)).save(output, format="JPEG")  # Contains ordinary JFIF metadata.
    source = output.getvalue()
    record = duplicate_record(source)
    response, objects, store, _, _, scanner, request = await run_upload_unit(monkeypatch, source, record)
    assert response.deduplicated and response.embed_id == record["embed_id"]
    assert response.files["original"].preserved_original_sha256 is None
    request.form.assert_not_awaited()
    store.assert_not_awaited()
    scanner.scan.assert_not_awaited()
    assert not objects
