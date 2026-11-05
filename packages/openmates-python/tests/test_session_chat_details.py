"""Actual facade and source-derived rich vectors; synthetic native objects only."""

# contract-test-file: tooling
import asyncio
import json
from pathlib import Path
import pytest
from openmates import (
    SessionClient,
    SessionClientError,
    SessionChatDetailsRead,
    SessionChatDetailsMetadata,
    SessionChatDetailsMessage,
)

FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "packages/openmates-session-bindings/tests/fixtures/chat-details-read.json"
    ).read_text()
)


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
def test_rich_vectors_preserve_fields_followups_nulls_and_optional_omission():
    async def scenario():
        for vector in FIXTURE["vectors"]:
            calls = []

            class Output:
                def release_json(self):
                    calls.append("finish")
                    return json.dumps(vector["expected"])

                def discard(self):
                    calls.append("discard")

            class Native:
                async def chat_details_prepare(self, identity, raw):
                    calls.append([identity, json.loads(raw)])
                    return Output()

            c = SessionClient.__new__(SessionClient)
            c._essential_epoch = 0
            c._native = Native()
            options = (
                {"history": {"kind": "full"}} if "--all" in vector["flags"] else {}
            )
            result = await c.chat_details(vector["expected"]["chat"]["id"], options)
            assert result == vector["expected"] and calls == [
                [vector["expected"]["chat"]["id"], options],
                "finish",
                "discard",
            ]
            assert ("has_more_before" in result) == ("--all" not in vector["flags"])
        assert "has_more_before" in SessionChatDetailsRead.__optional_keys__
        assert "participantUserHashes" in SessionChatDetailsMetadata.__optional_keys__
        assert "activeFocusId" in SessionChatDetailsMetadata.__optional_keys__
        assert "piiMappings" in SessionChatDetailsMessage.__optional_keys__
        assert {
            "chat",
            "messages",
            "follow_up_suggestions",
        } <= SessionChatDetailsRead.__required_keys__

        def fields(rows):
            return set().union(*(row.keys() for row in rows))

        assert set(SessionChatDetailsMetadata.__annotations__) == fields(
            [v["expected"]["chat"] for v in FIXTURE["vectors"]]
        )
        assert set(SessionChatDetailsMessage.__annotations__) == fields(
            [m for v in FIXTURE["vectors"] for m in v["expected"]["messages"]]
        )
        assert set(SessionChatDetailsRead.__annotations__) == fields(
            [v["expected"] for v in FIXTURE["vectors"]]
        )

    asyncio.run(scenario())


def test_options_and_arbitrary_raw_json_pii_entries_pass_unchanged():
    async def scenario():
        for mapping in [
            None,
            False,
            42,
            "literal",
            chr(0xD83D),
            [],
            {},
            {"placeholder": "[OM_PII_X]", "original": "Synthetic Alice"},
            [
                None,
                False,
                42,
                "literal",
                [],
                {"placeholder": "[OM_PII_X]", "original": "Synthetic Alice"},
            ],
        ]:
            expected = json.loads(json.dumps(FIXTURE["vectors"][0]["expected"]))
            expected["messages"][0]["piiMappings"] = mapping
            options = {
                "history": {"kind": "latest", "limit": 7},
                "content_mode": "stored",
            }

            class Output:
                def release_json(self):
                    return json.dumps(expected)

                def discard(self):
                    pass

            class Native:
                async def chat_details_prepare(self, identity, raw):
                    assert json.loads(raw) == options
                    return Output()

            c = SessionClient.__new__(SessionClient)
            c._essential_epoch = 0
            c._native = Native()
            result = await c.chat_details(expected["chat"]["id"], options)
            assert result == expected and "piiMappings" in result["messages"][0]

    asyncio.run(scenario())


def test_queued_epoch_refusal_disposes_without_releasing():
    async def scenario():
        c = SessionClient.__new__(SessionClient)
        c._essential_epoch = 0
        calls = []

        class Output:
            def release_json(self):
                pytest.fail("stale rich output released")

            def discard(self):
                calls.append("discard")

        class Native:
            async def chat_details_prepare(self, identity, raw):
                c._essential_epoch += 1
                return Output()

        c._native = Native()
        with pytest.raises(SessionClientError) as error:
            await c.chat_details(FIXTURE["vectors"][0]["expected"]["chat"]["id"])
        assert error.value.code == "cancelled" and calls == ["discard"]

    asyncio.run(scenario())


def test_final_native_denial_is_normalized_and_discarded():
    async def scenario():
        calls = []

        class Output:
            def release_json(self):
                raise RuntimeError(
                    json.dumps({"code": "forbidden", "message": "Denied."})
                )

            def discard(self):
                calls.append("discard")

        class Native:
            async def chat_details_prepare(self, identity, raw):
                return Output()

        c = SessionClient.__new__(SessionClient)
        c._essential_epoch = 0
        c._native = Native()
        with pytest.raises(SessionClientError) as error:
            await c.chat_details(FIXTURE["vectors"][0]["expected"]["chat"]["id"])
        assert error.value.code == "forbidden" and calls == ["discard"]

    asyncio.run(scenario())


def test_host_cancellation_disposes_original_eventual_native_output():
    async def scenario():
        entered, resume, discarded = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Output:
            def release_json(self):
                pytest.fail("abandoned rich output released")

            def discard(self):
                discarded.set()

        class Native:
            async def chat_details_prepare(self, identity, raw):
                entered.set()
                await resume.wait()
                return Output()

        c = SessionClient.__new__(SessionClient)
        c._essential_epoch = 0
        c._native = Native()
        pending = asyncio.create_task(
            c.chat_details(FIXTURE["vectors"][0]["expected"]["chat"]["id"])
        )
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        resume.set()
        await asyncio.wait_for(discarded.wait(), 1)

    asyncio.run(scenario())


def test_raw_json_escaped_draft_preview_preserves_trailing_utf16_unit():
    async def scenario():
        expected = json.loads(json.dumps(FIXTURE["vectors"][0]["expected"]))
        expected["chat"]["draftPreview"] = "a" * 199 + chr(0xD83D)
        wire = json.dumps(expected, ensure_ascii=True)
        assert "\\ud83d" in wire

        class Output:
            def release_json(self):
                return wire

            def discard(self):
                pass

        class Native:
            async def chat_details_prepare(self, identity, raw):
                return Output()

        c = SessionClient.__new__(SessionClient)
        c._essential_epoch = 0
        c._native = Native()
        result = await c.chat_details(expected["chat"]["id"])
        assert result == expected and len(result["chat"]["draftPreview"]) == 200
        assert ord(result["chat"]["draftPreview"][-1]) == 0xD83D

    asyncio.run(scenario())


def test_optional_active_focus_omission_and_whitespace_are_preserved():
    async def scenario():
        for value in [None, "synthetic-focus", " "]:
            expected = json.loads(json.dumps(FIXTURE["vectors"][0]["expected"]))
            expected["chat"].pop("activeFocusId", None)
            if value is not None:
                expected["chat"]["activeFocusId"] = value

            class Output:
                def release_json(self):
                    return json.dumps(expected)

                def discard(self):
                    pass

            class Native:
                async def chat_details_prepare(self, identity, raw):
                    return Output()

            c = SessionClient.__new__(SessionClient)
            c._essential_epoch = 0
            c._native = Native()
            result = await c.chat_details(expected["chat"]["id"])
            assert result == expected
            assert ("activeFocusId" in result["chat"]) == (value is not None)

    asyncio.run(scenario())


# Shared Rust owns JS-number rounding and duplicate-key normalization. Synthetic
# native tokens prove only the unchanged facade parsing boundary here.
def test_shared_sdk_numeric_tokens_retain_infinities_negative_zero_and_decoded_keys():
    import math

    async def scenario():
        cases = [
            ("1e400", float("inf")),
            ("-1e400", -float("inf")),
            ("-0.0", -0.0),
            ("9007199254740992.0", 9007199254740992.0),
            ("1.0000000000000001e18", 1.0000000000000001e18),
            ('{"a":1,"\\u0061":2}', {"a": 2}),
            ('{"\\ud83d":"\\udfff"}', {chr(0xD83D): chr(0xDFFF)}),
        ]
        for token, mapping in cases:
            expected = json.loads(json.dumps(FIXTURE["vectors"][0]["expected"]))
            expected["messages"][0]["piiMappings"] = "SDK_NUMERIC_TOKEN"
            wire = json.dumps(expected).replace('"SDK_NUMERIC_TOKEN"', token)

            class Output:
                def release_json(self):
                    return wire

                def discard(self):
                    pass

            class Native:
                async def chat_details_prepare(self, identity, raw):
                    return Output()

            c = SessionClient.__new__(SessionClient)
            c._essential_epoch = 0
            c._native = Native()
            result = await c.chat_details(expected["chat"]["id"])
            assert result["messages"][0]["piiMappings"] == mapping
            if token == "1.0000000000000001e18":
                value = result["messages"][0]["piiMappings"]
                assert isinstance(value, float) and int(value) == 1000000000000000128
            if token == "-0.0":
                value = result["messages"][0]["piiMappings"]
                assert isinstance(value, float) and math.copysign(1, value) == -1

    asyncio.run(scenario())
