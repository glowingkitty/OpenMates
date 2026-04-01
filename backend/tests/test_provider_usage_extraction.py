# backend/tests/test_provider_usage_extraction.py
#
# Verifies that each LLM provider client extracts real token usage metadata
# from streaming responses, using the provider's native API format.
# Tiktoken estimation must only be a last-resort fallback — these tests
# ensure the primary path works for all providers.
#
# Bug history this test suite guards against:
# - Google client: async stream_iterator has no .response attribute,
#   causing silent fallback to tiktoken for ALL Google streaming calls.
#   Fixed by capturing chunk.usage_metadata during iteration.

import asyncio
from dataclasses import dataclass, field
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Provider imports (skip tests if SDK not installed) ──────────────────
try:
    from backend.apps.ai.llm_providers.google_client import (
        GoogleUsageMetadata,
        invoke_google_ai_studio_chat_completions,
    )
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

try:
    from backend.apps.ai.llm_providers.openai_client import invoke_openai_chat_completions
    from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    from backend.apps.ai.llm_providers.anthropic_direct_api import invoke_direct_api as invoke_anthropic
    from backend.apps.ai.llm_providers.anthropic_shared import AnthropicUsageMetadata
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


# ═══════════════════════════════════════════════════════════════════════
# Mock structures for Google streaming chunks
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class MockGoogleUsageMetadata:
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    total_token_count: int = 0

    def to_dict(self):
        return {
            "prompt_token_count": self.prompt_token_count,
            "candidates_token_count": self.candidates_token_count,
            "total_token_count": self.total_token_count,
        }


@dataclass
class MockGooglePart:
    text: Optional[str] = None
    thought: bool = False
    function_call: Any = None
    thought_signature: Any = None


@dataclass
class MockGoogleContent:
    parts: List[MockGooglePart] = field(default_factory=list)


@dataclass
class MockGoogleCandidate:
    content: Optional[MockGoogleContent] = None
    finish_reason: Optional[str] = None
    thought_signature: Any = None


@dataclass
class MockGoogleChunk:
    candidates: Optional[List[MockGoogleCandidate]] = None
    usage_metadata: Optional[MockGoogleUsageMetadata] = None
    prompt_feedback: Any = None

    @property
    def text(self):
        if self.candidates:
            for c in self.candidates:
                if c.content and c.content.parts:
                    texts = [p.text for p in c.content.parts if p.text and not p.thought]
                    if texts:
                        return "".join(texts)
        return None


# ═══════════════════════════════════════════════════════════════════════
# GOOGLE: Usage extraction from per-chunk metadata
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_GOOGLE, reason="google-genai not installed")
class TestGoogleUsageExtraction:

    def test_streaming_extracts_usage_from_last_chunk(self):
        """Real usage_metadata on last chunk should be yielded, not tiktoken estimate."""

        text_chunk = MockGoogleChunk(
            candidates=[MockGoogleCandidate(
                content=MockGoogleContent(parts=[MockGooglePart(text="Hello world")])
            )]
        )
        final_chunk = MockGoogleChunk(
            candidates=[MockGoogleCandidate(
                content=MockGoogleContent(parts=[MockGooglePart(text="!")]),
                finish_reason="STOP",
            )],
            usage_metadata=MockGoogleUsageMetadata(
                prompt_token_count=150,
                candidates_token_count=25,
                total_token_count=175,
            ),
        )

        # The real SDK's generate_content_stream is an async method that returns
        # an async iterator. Mock must match: awaitable that yields chunks.
        async def mock_stream(**kwargs):
            for chunk in [text_chunk, final_chunk]:
                yield chunk

        async def run():
            mock_client_instance = MagicMock()
            # generate_content_stream is awaited in the code, so wrap the async gen
            # in a coroutine that returns it
            async def awaitable_stream(**kwargs):
                return mock_stream(**kwargs)
            mock_client_instance.aio.models.generate_content_stream = awaitable_stream

            with patch("backend.apps.ai.llm_providers.google_client.genai") as mock_genai, \
                 patch("backend.apps.ai.llm_providers.google_client._get_google_ai_studio_api_key", new_callable=AsyncMock, return_value="fake-key"):
                mock_genai.Client.return_value = mock_client_instance

                result = await invoke_google_ai_studio_chat_completions(
                    task_id="test-task",
                    model_id="gemini-3-flash-preview",
                    messages=[{"role": "user", "content": "test"}],
                    stream=True,
                )

                chunks = []
                async for item in result:
                    chunks.append(item)

                usage_items = [c for c in chunks if isinstance(c, GoogleUsageMetadata)]
                text_items = [c for c in chunks if isinstance(c, str)]

                assert len(usage_items) == 1, f"Expected 1 usage metadata, got {len(usage_items)}"
                usage = usage_items[0]
                assert usage.prompt_token_count == 150
                assert usage.candidates_token_count == 25
                assert usage.total_token_count == 175
                assert "Hello world" in "".join(text_items)

        asyncio.run(run())

    def test_no_usage_falls_back_to_tiktoken(self):
        """When no usage_metadata on any chunk, tiktoken fallback should fire."""

        text_chunk = MockGoogleChunk(
            candidates=[MockGoogleCandidate(
                content=MockGoogleContent(parts=[MockGooglePart(text="Response")])
            )]
        )

        async def mock_stream(**kwargs):
            yield text_chunk

        async def run():
            mock_client_instance = MagicMock()
            async def awaitable_stream(**kwargs):
                return mock_stream(**kwargs)
            mock_client_instance.aio.models.generate_content_stream = awaitable_stream

            with patch("backend.apps.ai.llm_providers.google_client.genai") as mock_genai, \
                 patch("backend.apps.ai.llm_providers.google_client._get_google_ai_studio_api_key", new_callable=AsyncMock, return_value="fake-key"):
                mock_genai.Client.return_value = mock_client_instance

                result = await invoke_google_ai_studio_chat_completions(
                    task_id="test-task",
                    model_id="gemini-3-flash-preview",
                    messages=[{"role": "user", "content": "test"}],
                    stream=True,
                )

                chunks = []
                async for item in result:
                    chunks.append(item)

                usage_items = [c for c in chunks if isinstance(c, GoogleUsageMetadata)]
                assert len(usage_items) == 1, "Tiktoken fallback should still yield usage"
                assert usage_items[0].total_token_count > 0

        asyncio.run(run())

    def test_safety_finish_reason_detected(self):
        """SAFETY finish_reason from per-chunk data should yield a warning."""

        blocked_chunk = MockGoogleChunk(
            candidates=[MockGoogleCandidate(
                content=MockGoogleContent(parts=[MockGooglePart(text="Partial")]),
                finish_reason="SAFETY",
            )],
            usage_metadata=MockGoogleUsageMetadata(
                prompt_token_count=50, candidates_token_count=5, total_token_count=55
            ),
        )

        async def mock_stream(**kwargs):
            yield blocked_chunk

        async def run():
            mock_client_instance = MagicMock()
            async def awaitable_stream(**kwargs):
                return mock_stream(**kwargs)
            mock_client_instance.aio.models.generate_content_stream = awaitable_stream

            with patch("backend.apps.ai.llm_providers.google_client.genai") as mock_genai, \
                 patch("backend.apps.ai.llm_providers.google_client._get_google_ai_studio_api_key", new_callable=AsyncMock, return_value="fake-key"):
                mock_genai.Client.return_value = mock_client_instance

                result = await invoke_google_ai_studio_chat_completions(
                    task_id="test-task",
                    model_id="gemini-3-flash-preview",
                    messages=[{"role": "user", "content": "test"}],
                    stream=True,
                )

                chunks = []
                async for item in result:
                    chunks.append(item)

                text_chunks = [c for c in chunks if isinstance(c, str)]
                safety_msgs = [c for c in text_chunks if "safety filter" in c.lower()]
                assert len(safety_msgs) == 1, "Should yield safety filter warning"

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════
# OPENAI: Usage extraction from chunk.usage
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_OPENAI, reason="openai SDK not installed")
class TestOpenAIUsageExtraction:

    def test_streaming_extracts_usage_from_chunk(self):
        """Verify real usage from chunk.usage, not tiktoken fallback."""

        @dataclass
        class MockUsage:
            prompt_tokens: int = 100
            completion_tokens: int = 50
            total_tokens: int = 150

        @dataclass
        class MockDelta:
            content: Optional[str] = None
            tool_calls: Any = None
            role: Optional[str] = None

        @dataclass
        class MockChoice:
            delta: MockDelta = field(default_factory=MockDelta)
            finish_reason: Optional[str] = None
            index: int = 0

        @dataclass
        class MockChunk:
            choices: List[MockChoice] = field(default_factory=list)
            usage: Optional[MockUsage] = None
            model: str = "gpt-4o"

        mock_chunks = [
            MockChunk(choices=[MockChoice(delta=MockDelta(content="Hello"))]),
            MockChunk(
                choices=[MockChoice(delta=MockDelta(content=" world"), finish_reason="stop")],
                usage=MockUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            ),
        ]

        async def _chunk_gen():
            for chunk in mock_chunks:
                yield chunk

        async def mock_create(**kwargs):
            """Wraps async gen in a coroutine since the real SDK call is awaited."""
            return _chunk_gen()

        async def run():
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = mock_create

            with patch("backend.apps.ai.llm_providers.openai_client._openai_client_initialized", True), \
                 patch("backend.apps.ai.llm_providers.openai_client._openai_direct_client", mock_instance):
                result = await invoke_openai_chat_completions(
                    task_id="test-task",
                    model_id="gpt-4o",
                    messages=[{"role": "user", "content": "test"}],
                    stream=True,
                )

                items = []
                async for item in result:
                    items.append(item)

                usage_items = [i for i in items if isinstance(i, OpenAIUsageMetadata)]
                assert len(usage_items) == 1
                assert usage_items[0].input_tokens == 100
                assert usage_items[0].output_tokens == 50
                assert usage_items[0].total_tokens == 150

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════
# ANTHROPIC: Usage extraction from message_delta events
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_ANTHROPIC, reason="anthropic SDK not installed")
class TestAnthropicUsageExtraction:

    def test_streaming_extracts_usage_from_message_delta(self):
        """Verify real usage from message_delta event, not tiktoken fallback.

        The Anthropic client uses sync iteration: `for event in stream:` where
        stream = anthropic_client.messages.create(**kwargs, stream=True).
        Usage data arrives in a message_delta event with delta.usage.
        """

        @dataclass
        class MockUsage:
            input_tokens: int = 200
            output_tokens: int = 80

        @dataclass
        class MockTextDelta:
            type: str = "text_delta"
            text: str = "Hello"

        @dataclass
        class MockMessageDelta:
            type: str = "message_delta"
            stop_reason: str = "end_turn"
            usage: Optional[MockUsage] = None

        @dataclass
        class MockEvent:
            type: str = "content_block_delta"
            delta: Any = None
            index: int = 0
            content_block: Any = None
            message: Any = None

        events = [
            MockEvent(type="content_block_delta", delta=MockTextDelta()),
            MockEvent(type="message_delta", delta=MockMessageDelta(
                usage=MockUsage(input_tokens=200, output_tokens=80)
            )),
        ]

        async def run():
            # The Anthropic client uses sync iteration (for event in stream)
            mock_client = MagicMock()
            mock_client.messages.create.return_value = iter(events)

            result = await invoke_anthropic(
                task_id="test-task",
                model_id="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "test"}],
                anthropic_client=mock_client,
                stream=True,
            )

            items = []
            async for item in result:
                items.append(item)

            usage_items = [i for i in items if isinstance(i, AnthropicUsageMetadata)]
            assert len(usage_items) == 1, f"Expected 1 usage, got {len(usage_items)}: {usage_items}"
            assert usage_items[0].input_tokens == 200
            assert usage_items[0].output_tokens == 80
            assert usage_items[0].total_tokens == 280

        asyncio.run(run())
