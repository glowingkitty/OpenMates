"""Verify Gemini tool continuation serialization with the pinned SDK, without AI."""
# contract-test-file: infrastructure
import base64
import json
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web
from google import genai
from google.oauth2.credentials import Credentials
from google.genai import types

from backend.apps.ai.llm_providers import google_client


SIGNATURE = b"private-thought-signature"


def _tool_messages(image_counts, *, name="images-view"):
    calls = []
    results = []
    for call_index, image_count in enumerate(image_counts):
        call_id = f"opaque_call_{call_index}"
        calls.append({
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": '{"id":"example"}'},
            "thought_signature": base64.b64encode(SIGNATURE).decode() if call_index == 0 else None,
        })
        blocks = [{"type": "text", "text": json.dumps({"image_count": image_count})}]
        for image_index in range(image_count):
            image_bytes = f"image bytes {call_index}:{image_index}".encode()
            blocks.extend([
                {"type": "text", "text": f"Image {image_index + 1}: embed {call_index}:{image_index}"},
                {"type": "image_url", "image_url": {
                    "url": "data:image/webp;base64," + base64.b64encode(image_bytes).decode(),
                    "detail": "original",
                }},
            ])
        # Omit name: arbitrary provider IDs cannot be used to infer tool names.
        results.append({"role": "tool", "tool_call_id": call_id, "content": blocks})
    return [
        {"role": "user", "content": "Describe the requested images."},
        {"role": "assistant", "content": "", "tool_calls": calls},
        *results,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["studio", "vertex"])
@pytest.mark.parametrize("model_id,name,image_counts", [
    ("gemini-3.8-flash", "images-view", [1]),
    ("gemini-3.8-flash", "pdf-view", [3]),
    ("gemini-4-argon", "images-view", [1, 2]),
])
async def test_sdk_wire_nests_and_associates_every_tool_image(
    provider, model_id, name, image_counts,
):
    """Inspect actual SDK HTTP JSON, including call IDs, nested blobs and signatures."""
    captured = []

    async def respond(request):
        captured.append(await request.json())
        return web.json_response({"candidates": [{"content": {
            "role": "model", "parts": [{"text": "ready"}],
        }, "finishReason": "STOP"}]})

    application = web.Application()
    application.router.add_post("/{path:.*}", respond)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = genai.Client(
        **({"api_key": "unit-test-key"} if provider == "studio" else {
            "vertexai": True, "project": "unit-project", "location": "global",
            "credentials": Credentials(token="unit-test-token"),
        }),
        http_options=types.HttpOptions(base_url=f"http://127.0.0.1:{port}"),
    )
    messages = _tool_messages(image_counts, name=name)
    _, contents = google_client._prepare_messages_and_system_prompt(messages, model_id)
    try:
        response = await client.aio.models.generate_content(model=model_id, contents=contents)
        assert response.text == "ready"
    finally:
        await client.aio.aclose()
        client.close()
        await runner.cleanup()

    assert len(captured) == 1
    # The pinned SDK leaves nested function-response fields in proto snake_case.
    # ProtoJSON accepts those names as well as lowerCamelCase. Normalize names
    # only, preserving the captured HTTP values for all payload assertions.
    aliases = {"function_call": "functionCall", "function_response": "functionResponse",
               "inline_data": "inlineData", "thought_signature": "thoughtSignature",
               "mime_type": "mimeType", "display_name": "displayName"}

    def normalize_names(value):
        if isinstance(value, list):
            return [normalize_names(item) for item in value]
        if isinstance(value, dict):
            return {aliases.get(key, key): normalize_names(item) for key, item in value.items()}
        return value

    wire = normalize_names(captured[0]["contents"])
    calls = wire[1]["parts"]
    responses = wire[2]["parts"]
    assert len(responses) == len(image_counts)
    assert wire[2]["role"] == "user"
    assert calls[0]["thoughtSignature"] == base64.b64encode(SIGNATURE).decode()
    assert all("thoughtSignature" not in part for part in calls[1:])
    assert "private-thought-signature" not in json.dumps(responses)
    for call_index, image_count in enumerate(image_counts):
        call = calls[call_index]["functionCall"]
        assert call["id"] == f"opaque_call_{call_index}"
        assert call["name"] == name
        assert set(responses[call_index]) == {"functionResponse"}
        result = responses[call_index]["functionResponse"]
        assert result["id"] == call["id"]
        assert result["name"] == call["name"]
        assert len(result["parts"]) == image_count
        content = result["response"]["content"]
        assert content[0] == {"type": "text", "text": json.dumps({"image_count": image_count})}
        display_names = []
        for image_index, part in enumerate(result["parts"]):
            assert set(part) == {"inlineData"}
            blob = part["inlineData"]
            assert blob["mimeType"] == "image/webp"
            assert base64.b64decode(blob["data"]) == f"image bytes {call_index}:{image_index}".encode()
            assert content[image_index * 2 + 1]["text"] == (
                f"Image {image_index + 1}: embed {call_index}:{image_index}"
            )
            assert content[image_index * 2 + 2] == {
                "type": "image", "image": {"$ref": blob["displayName"]},
            }
            display_names.append(blob["displayName"])
        assert len(set(display_names)) == image_count


@pytest.mark.parametrize("model_id", ["gemini-2.5-flash", "qwen/qwen3-235b-maas"])
def test_older_models_keep_sibling_images_and_unchanged_user_image_input(model_id):
    messages = _tool_messages([1])
    messages[0]["content"] = messages[2]["content"]
    _, history = google_client._prepare_messages_and_system_prompt(messages, model_id)
    response_parts = history[2].parts
    assert response_parts[0].function_response.id == "opaque_call_0"
    assert response_parts[0].function_response.name == "images-view"
    assert response_parts[0].function_response.response == {"status": "ok", "type": "multimodal"}
    assert response_parts[0].function_response.parts is None
    assert response_parts[-1].inline_data.data == b"image bytes 0:0"
    assert history[0].parts[-1].inline_data.data == b"image bytes 0:0"
    assert history[1].parts[0].thought_signature == SIGNATURE


@pytest.mark.parametrize("payload,expected", [
    ('{"result":{"count":2}}', {"result": {"count": 2}}),
    ("count: 2", {"result": "count: 2"}),
    ({"error": "unavailable"}, {"error": "unavailable"}),
])
def test_non_image_tool_payload_is_unchanged_alongside_image_response(payload, expected):
    messages = _tool_messages([1])
    messages[1]["tool_calls"].append({
        "id": "opaque_plain", "function": {"name": "web-search", "arguments": "{}"},
    })
    messages.append({"role": "tool", "tool_call_id": "opaque_plain", "content": payload})
    _, history = google_client._prepare_messages_and_system_prompt(messages, "gemini-3.8-flash")
    assert len(history) == 3
    assert len(history[-1].parts) == 2
    response = history[-1].parts[1].function_response
    assert response.name == "web-search"
    assert response.id == "opaque_plain"
    assert response.response == expected
    assert response.parts is None


@pytest.mark.parametrize("streamed", [True, False])
def test_provider_call_id_and_signature_round_trip_without_logging_them(streamed, caplog, monkeypatch):
    call = types.FunctionCall(id="provider-issued-id", name="images-view", args={"id": "example"})
    monkeypatch.setattr(google_client.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(google_client.logger, "propagate", False)
    with caplog.at_level(logging.DEBUG, logger=google_client.__name__):
        if streamed:
            parsed = google_client._parse_streamed_google_tool_call(
                call, function_call_thought_signature=SIGNATURE,
                candidate_thought_signature=None, signature_provider_id="google_ai_studio",
            )
        else:
            response = types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(role="model", parts=[types.Part(
                    function_call=call, thought_signature=SIGNATURE,
                )]),
            )])
            parsed, = google_client._parse_non_streamed_google_tool_calls(response, "google_ai_studio")
        assert parsed.tool_call_id == "provider-issued-id"
        assert parsed.provider_transport_state == {
            google_client.GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY: "google_ai_studio",
        }
        messages = _tool_messages([1])
        messages[1]["tool_calls"][0].update({
            "id": parsed.tool_call_id, "thought_signature": parsed.thought_signature,
        })
        messages[2]["tool_call_id"] = parsed.tool_call_id
        _, history = google_client._prepare_messages_and_system_prompt(messages, "gemini-3.8-flash")
    assert history[1].parts[0].function_call.id == "provider-issued-id"
    assert history[1].parts[0].thought_signature == SIGNATURE
    assert history[2].parts[0].function_response.id == "provider-issued-id"
    assert "Prepared multimodal tool response" in caplog.text
    assert SIGNATURE.decode() not in caplog.text
    assert parsed.thought_signature not in caplog.text
    assert parsed.thought_signature not in json.dumps(history[2].model_dump(mode="json"))


def test_legacy_idless_call_gets_a_consistent_identifier():
    parsed = google_client._parse_streamed_google_tool_call(
        SimpleNamespace(name="images-view", args={}),
        candidate_thought_signature=None, signature_provider_id="google",
    )
    assert parsed.tool_call_id.startswith("images-view-")
    messages = _tool_messages([1])
    messages[1]["tool_calls"][0]["id"] = parsed.tool_call_id
    messages[2]["tool_call_id"] = parsed.tool_call_id
    _, history = google_client._prepare_messages_and_system_prompt(messages, "gemini-3.8-flash")
    assert history[1].parts[0].function_call.id == history[2].parts[0].function_response.id


@pytest.mark.parametrize("url", ["https://private.invalid/image?token=secret", "data:image/png;base64,%%%"])
def test_invalid_tool_image_raises_without_logging_private_payload(url, caplog):
    messages = _tool_messages([1])
    messages[2]["content"][-1]["image_url"]["url"] = url
    with caplog.at_level(logging.DEBUG, logger=google_client.__name__):
        with pytest.raises(ValueError):
            google_client._prepare_messages_and_system_prompt(messages, "gemini-3.8-flash")
    assert url not in caplog.text
