# backend/tests/test_bedrock_image_multimodal.py
# contract-test-file: infrastructure
#
# Purpose: regression coverage for image tool results sent to AWS Bedrock Converse.
# The images.view skill must preserve the real MIME type, and Bedrock conversion
# must pass raw bytes to boto3 rather than a base64 string.
# Architecture: backend/apps/images/skills/view_skill.py and
# backend/apps/ai/llm_providers/bedrock_shared.py.

import base64
import json
import sys
import types

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.apps.images.skills.view_skill import ViewSkill
from backend.shared.python_utils.image_mime import detect_image_mime_type
from backend.shared.python_utils.media_encryption import MEDIA_ENCRYPTION_V2

try:
    from backend.apps.ai.llm_providers.bedrock_shared import (
        convert_messages_to_converse_format,
        convert_tool_choice_to_converse_format,
    )
except ImportError:
    convert_messages_to_converse_format = None  # type: ignore[assignment]
    convert_tool_choice_to_converse_format = None  # type: ignore[assignment]


def test_detect_image_mime_type_uses_jpeg_magic_bytes() -> None:
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"jpeg payload"

    assert detect_image_mime_type(jpeg_bytes, "uploaded.webp") == "image/jpeg"


def _view_skill() -> ViewSkill:
    return ViewSkill(
        app=object(),
        app_id="images",
        skill_id="view",
        skill_name="View image",
        skill_description="Load an uploaded image",
    )


class _FakeRedis:
    def __init__(self, value: str) -> None:
        self.value = value
        self.closed = False

    async def get(self, key: str) -> str:
        assert key == "embed:embed-1"
        return self.value

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_image_view_lookup_accepts_upload_cache_record_without_encrypted_content(monkeypatch) -> None:
    upload_record = {
        "embed_id": "embed-1",
        "vault_wrapped_aes_key": "wrapped-aes-key",
        "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
    }
    redis = _FakeRedis(json.dumps(upload_record))
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")
    redis_asyncio_module.from_url = lambda *args, **kwargs: redis
    redis_module.asyncio = redis_asyncio_module
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_asyncio_module)

    content = await _view_skill()._lookup_embed_content("embed-1", "vault-key-1")

    assert content == upload_record
    assert redis.closed is True


@pytest.mark.asyncio
async def test_image_view_decrypts_nonce_prefixed_media_without_top_level_nonce(monkeypatch) -> None:
    skill = _view_skill()
    nonce = b"\x33" * 12
    aes_key = b"\x11" * 32
    image_bytes = b"\x89PNG\r\n\x1a\nchair-image"
    encrypted = nonce + AESGCM(aes_key).encrypt(nonce, image_bytes, None)

    async def fake_lookup(embed_id: str, vault_key_id: str) -> dict[str, object]:
        assert embed_id == "embed-1"
        assert vault_key_id == "vault-key-1"
        return {
            "filename": "chair.png",
            "vault_wrapped_aes_key": "wrapped-aes-key",
            "files": {
                "original": {
                    "s3_key": "inputs/chair.png",
                    "format": "png",
                    "encryption": MEDIA_ENCRYPTION_V2,
                }
            },
        }

    async def fake_unwrap(wrapped_key: str, vault_key_id: str) -> bytes:
        assert wrapped_key == "wrapped-aes-key"
        assert vault_key_id == "vault-key-1"
        return aes_key

    async def fake_download(_s3_base_url: str, s3_key: str) -> bytes:
        assert s3_key == "inputs/chair.png"
        return encrypted

    monkeypatch.setattr(skill, "_lookup_embed_content", fake_lookup)
    monkeypatch.setattr(skill, "_unwrap_aes_key", fake_unwrap)
    monkeypatch.setattr(skill, "_download_from_s3", fake_download)

    result = await skill.execute(
        "chair.png",
        user_vault_key_id="vault-key-1",
        file_path_index={"chair.png": "embed-1"},
    )

    assert result[0] == {"type": "text", "text": "Image: chair.png"}
    assert result[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    )


def test_bedrock_image_conversion_decodes_data_url_to_raw_bytes() -> None:
    if convert_messages_to_converse_format is None:
        pytest.skip("Bedrock dependencies not installed locally (botocore)")

    image_bytes = b"\xff\xd8\xff\xe0jpeg payload"
    data_url = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('ascii')}"

    _system, messages = convert_messages_to_converse_format([
        {
            "role": "tool",
            "tool_call_id": "tool-1",
            "content": [
                {"type": "text", "text": "Image: uploaded.jpg"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ])

    image = messages[0]["content"][0]["toolResult"]["content"][1]["image"]
    assert image["format"] == "jpeg"
    assert image["source"]["bytes"] == image_bytes


def test_bedrock_groups_parallel_image_results_in_the_next_user_turn() -> None:
    if convert_messages_to_converse_format is None:
        pytest.skip("Bedrock dependencies not installed locally (botocore)")

    image_bytes = b"\x89PNG\r\n\x1a\nimage"
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    calls = [
        {"id": tool_id, "function": {"name": "images_view", "arguments": "{}"}}
        for tool_id in ("image-1", "image-2")
    ]
    history = [{"role": "user", "content": "Compare these images"},
               {"role": "assistant", "tool_calls": calls}]
    history.extend({"role": "tool", "tool_call_id": call["id"], "content": [
        {"type": "text", "text": call["id"]},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]} for call in calls)
    history.extend([{"role": "assistant", "content": "Comparison"},
                    {"role": "user", "content": "Thanks"}])

    _, messages = convert_messages_to_converse_format(history)

    assert [message["role"] for message in messages] == [
        "user", "assistant", "user", "assistant", "user"
    ]
    results = [block["toolResult"] for block in messages[2]["content"]]
    assert [result["toolUseId"] for result in results] == ["image-1", "image-2"]
    assert all(result["content"][1]["image"]["source"]["bytes"] == image_bytes for result in results)


def test_bedrock_named_openai_tool_choice_uses_converse_tool_name() -> None:
    if convert_tool_choice_to_converse_format is None:
        pytest.skip("Bedrock dependencies not installed locally (botocore)")

    tool_choice = {"type": "function", "function": {"name": "get_weather"}}

    assert convert_tool_choice_to_converse_format(tool_choice, has_tools=True) == {"tool": {"name": "get_weather"}}
