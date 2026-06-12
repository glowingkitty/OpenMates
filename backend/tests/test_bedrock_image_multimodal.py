# backend/tests/test_bedrock_image_multimodal.py
#
# Purpose: regression coverage for image tool results sent to AWS Bedrock Converse.
# The images.view skill must preserve the real MIME type, and Bedrock conversion
# must pass raw bytes to boto3 rather than a base64 string.
# Architecture: backend/apps/images/skills/view_skill.py and
# backend/apps/ai/llm_providers/bedrock_shared.py.

import base64

import pytest

from backend.shared.python_utils.image_mime import detect_image_mime_type

try:
    from backend.apps.ai.llm_providers.bedrock_shared import convert_messages_to_converse_format
except ImportError:
    convert_messages_to_converse_format = None  # type: ignore[assignment]


def test_detect_image_mime_type_uses_jpeg_magic_bytes() -> None:
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"jpeg payload"

    assert detect_image_mime_type(jpeg_bytes, "uploaded.webp") == "image/jpeg"


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
