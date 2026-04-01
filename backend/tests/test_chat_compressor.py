# backend/tests/test_chat_compressor.py
#
# Unit tests for the chat compression module that summarizes older messages
# when chat history exceeds the token budget.
#
# Tests cover: token estimation, compression threshold checks, history splitting,
# summary detection, relative time formatting, prompt construction, and the
# async compression entry point (with monkeypatched LLM calls).
#
# Architecture: docs/architecture/chat-compression.md
# Run: python -m pytest backend/tests/test_chat_compressor.py -v

from unittest.mock import MagicMock

import pytest

try:
    from backend.apps.ai.processing.chat_compressor import (
        estimate_tokens_for_message,
        estimate_total_tokens,
        should_compress,
        split_history_for_compression,
        _find_existing_summary,
        _format_relative_time,
        _build_compression_prompt,
        compress_chat_history,
        DEFAULT_COMPRESSION_TRIGGER_THRESHOLD,
        ESTIMATED_SYSTEM_PROMPT_OVERHEAD,
        RECENT_WINDOW_TOKEN_BUDGET,
        RECENT_WINDOW_MIN_MESSAGES,
        AVG_CHARS_PER_TOKEN,
        COMPRESSION_SUMMARY_CATEGORY,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(content: str, role: str = "user", created_at: int = 0, **extra) -> dict:
    """Create a minimal message dict for testing."""
    msg = {"role": role, "content": content, "created_at": created_at}
    msg.update(extra)
    return msg


def _compression_summary_msg(content: str = "## Summary\nOld stuff", created_at: int = 0) -> dict:
    """Create a compression_summary system message."""
    return {
        "role": "system",
        "content": content,
        "created_at": created_at,
        "category": COMPRESSION_SUMMARY_CATEGORY,
    }


def _make_history(n: int, chars_per_msg: int = 100) -> list:
    """Create a message history with n messages of roughly chars_per_msg characters."""
    history = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"Message {i}: " + "x" * (chars_per_msg - len(f"Message {i}: "))
        history.append(_msg(content, role=role, created_at=1000 + i))
    return history


# ===========================================================================
# estimate_tokens_for_message
# ===========================================================================

class TestEstimateTokensForMessage:
    def test_string_content(self):
        msg = _msg("hello world")  # 11 chars
        tokens = estimate_tokens_for_message(msg)
        # base 4 + 11/4.0 = 4 + 2.75 = 6.75 -> int(6.75) = 6
        assert tokens == int(4 + len("hello world") / AVG_CHARS_PER_TOKEN)

    def test_empty_string(self):
        msg = _msg("")
        tokens = estimate_tokens_for_message(msg)
        assert tokens == 4  # base overhead only

    def test_missing_content_key(self):
        msg = {"role": "user"}
        tokens = estimate_tokens_for_message(msg)
        assert tokens == 4  # base overhead, no content

    def test_multimodal_list_content(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image"},
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ],
        }
        tokens = estimate_tokens_for_message(msg)
        # base 4 + "Describe this image" (20 chars) / 4.0 = 4 + 5 = 9
        expected = int(4 + len("Describe this image") / AVG_CHARS_PER_TOKEN)
        assert tokens == expected

    def test_multimodal_no_text_parts(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ],
        }
        tokens = estimate_tokens_for_message(msg)
        assert tokens == 4  # only base overhead, no text

    def test_long_content(self):
        content = "a" * 40000  # 10,000 tokens
        msg = _msg(content)
        tokens = estimate_tokens_for_message(msg)
        assert tokens == int(4 + 40000 / AVG_CHARS_PER_TOKEN)


# ===========================================================================
# estimate_total_tokens
# ===========================================================================

class TestEstimateTotalTokens:
    def test_empty_history(self):
        assert estimate_total_tokens([]) == 0

    def test_single_message(self):
        history = [_msg("hello")]
        assert estimate_total_tokens(history) == estimate_tokens_for_message(history[0])

    def test_multiple_messages(self):
        history = [_msg("aaa"), _msg("bbb"), _msg("ccc")]
        total = estimate_total_tokens(history)
        individual_sum = sum(estimate_tokens_for_message(m) for m in history)
        assert total == individual_sum


# ===========================================================================
# should_compress
# ===========================================================================

class TestShouldCompress:
    def test_empty_history_returns_false(self):
        assert should_compress([]) is False

    def test_below_threshold_returns_false(self):
        # Small message: ~4 + 10/4 = ~6 tokens per message
        # 10 messages = ~60 tokens + 15k overhead = ~15060, well below 100k
        history = [_msg("short text") for _ in range(10)]
        assert should_compress(history) is False

    def test_above_threshold_returns_true(self):
        # Each message ~4 + 100000/4 = 25004 tokens
        # 4 messages = ~100016 tokens + 15k overhead = ~115016 > 100k
        big_msg = "x" * 100000
        history = [_msg(big_msg) for _ in range(4)]
        assert should_compress(history) is True

    def test_custom_threshold_lower(self):
        # With a low threshold, even small messages should trigger
        history = [_msg("hello world") for _ in range(5)]
        assert should_compress(history, compression_threshold=10) is True

    def test_custom_threshold_higher(self):
        # With a very high threshold, even big messages should not trigger
        big_msg = "x" * 100000
        history = [_msg(big_msg) for _ in range(4)]
        assert should_compress(history, compression_threshold=999_999_999) is False

    def test_overhead_is_included(self):
        """Verify that ESTIMATED_SYSTEM_PROMPT_OVERHEAD is factored into the threshold check."""
        # Create messages whose tokens alone are below threshold,
        # but tokens + overhead exceed it.
        # Target: message_tokens < threshold, but message_tokens + 15k >= threshold
        target_msg_tokens = DEFAULT_COMPRESSION_TRIGGER_THRESHOLD - ESTIMATED_SYSTEM_PROMPT_OVERHEAD
        # Each char ~0.25 tokens, so chars = tokens * 4
        chars_needed = int((target_msg_tokens - 4) * AVG_CHARS_PER_TOKEN)  # subtract base overhead
        history = [_msg("x" * chars_needed)]
        # message_tokens ~= target_msg_tokens, total_with_overhead ~= threshold
        assert should_compress(history) is True


# ===========================================================================
# split_history_for_compression
# ===========================================================================

class TestSplitHistoryForCompression:
    def test_empty_history(self):
        to_compress, recent = split_history_for_compression([])
        assert to_compress == []
        assert recent == []

    def test_keeps_minimum_recent_messages(self):
        """Must always keep at least RECENT_WINDOW_MIN_MESSAGES (6) in recent."""
        history = _make_history(20, chars_per_msg=100)
        to_compress, recent = split_history_for_compression(history)
        assert len(recent) >= RECENT_WINDOW_MIN_MESSAGES

    def test_fewer_than_min_messages_all_recent(self):
        """If history has fewer messages than the minimum, they're all in recent."""
        history = _make_history(4, chars_per_msg=100)
        to_compress, recent = split_history_for_compression(history)
        # With only 4 messages and min=6, all should be in recent
        assert len(recent) == 4
        assert len(to_compress) == 0

    def test_respects_token_budget(self):
        """Recent messages should not exceed RECENT_WINDOW_TOKEN_BUDGET."""
        # Create 30 messages with ~400 chars each (~104 tokens each)
        # 6 minimum messages = ~624 tokens (well under 10k budget)
        # Budget allows about 10000/104 ~ 96 messages, but we only have 30
        history = _make_history(30, chars_per_msg=400)
        to_compress, recent = split_history_for_compression(history)
        # With 30 * 104 = 3120 tokens in total, all fit in 10k budget
        # So most messages end up in recent
        recent_tokens = sum(estimate_tokens_for_message(m) for m in recent)
        assert recent_tokens <= RECENT_WINDOW_TOKEN_BUDGET + 500  # allow small overshoot from min messages

    def test_compression_summary_excluded_from_recent(self):
        """Existing compression summaries must land in to_compress, not recent."""
        history = _make_history(10, chars_per_msg=100)
        # Insert a compression summary in the middle
        summary = _compression_summary_msg("## Old summary", created_at=1005)
        history.insert(5, summary)
        to_compress, recent = split_history_for_compression(history)

        # The summary should NOT appear in recent
        for msg in recent:
            assert msg.get("category") != COMPRESSION_SUMMARY_CATEGORY

    def test_split_preserves_all_messages(self):
        """Every non-summary message appears in either to_compress or recent."""
        history = _make_history(15, chars_per_msg=100)
        summary = _compression_summary_msg()
        history.insert(3, summary)

        to_compress, recent = split_history_for_compression(history)
        # Count non-summary messages
        non_summary_count = sum(
            1 for m in history
            if not (m.get("role") == "system" and m.get("category") == COMPRESSION_SUMMARY_CATEGORY)
        )
        assert len(to_compress) + len(recent) >= non_summary_count - 1  # summary may be in to_compress

    def test_chronological_order_preserved(self):
        """to_compress contains older messages, recent contains newer ones."""
        history = _make_history(20, chars_per_msg=100)
        to_compress, recent = split_history_for_compression(history)
        if to_compress and recent:
            oldest_recent = min(m["created_at"] for m in recent)
            newest_compressed = max(m["created_at"] for m in to_compress)
            assert newest_compressed <= oldest_recent


# ===========================================================================
# _find_existing_summary
# ===========================================================================

class TestFindExistingSummary:
    def test_no_summary_returns_none(self):
        history = [_msg("hello"), _msg("world")]
        assert _find_existing_summary(history) is None

    def test_finds_summary(self):
        history = [
            _msg("hello"),
            _compression_summary_msg("Found this summary"),
            _msg("world"),
        ]
        assert _find_existing_summary(history) == "Found this summary"

    def test_returns_most_recent_summary(self):
        history = [
            _compression_summary_msg("Old summary", created_at=100),
            _msg("middle"),
            _compression_summary_msg("New summary", created_at=200),
        ]
        assert _find_existing_summary(history) == "New summary"

    def test_ignores_system_messages_without_category(self):
        history = [
            {"role": "system", "content": "You are a helpful assistant"},
            _msg("hello"),
        ]
        assert _find_existing_summary(history) is None

    def test_ignores_wrong_category(self):
        history = [
            {"role": "system", "content": "Not a summary", "category": "something_else"},
        ]
        assert _find_existing_summary(history) is None


# ===========================================================================
# _format_relative_time
# ===========================================================================

class TestFormatRelativeTime:
    def test_just_now(self):
        now = 1000
        assert _format_relative_time(now, now) == "just now"
        assert _format_relative_time(now - 30, now) == "just now"
        assert _format_relative_time(now - 59, now) == "just now"

    def test_minutes(self):
        now = 10000
        assert _format_relative_time(now - 60, now) == "~1 min ago"
        assert _format_relative_time(now - 120, now) == "~2 min ago"
        assert _format_relative_time(now - 3599, now) == "~59 min ago"

    def test_hours(self):
        now = 100000
        assert _format_relative_time(now - 3600, now) == "~1h ago"
        assert _format_relative_time(now - 7200, now) == "~2h ago"
        assert _format_relative_time(now - 86399, now) == "~23h ago"

    def test_days(self):
        now = 1000000
        assert _format_relative_time(now - 86400, now) == "~1d ago"
        assert _format_relative_time(now - 172800, now) == "~2d ago"

    def test_boundary_60_seconds(self):
        """Exactly 60 seconds should be '~1 min ago', not 'just now'."""
        now = 10000
        assert _format_relative_time(now - 60, now) == "~1 min ago"

    def test_boundary_3600_seconds(self):
        """Exactly 3600 seconds should be '~1h ago', not minutes."""
        now = 100000
        assert _format_relative_time(now - 3600, now) == "~1h ago"

    def test_boundary_86400_seconds(self):
        """Exactly 86400 seconds should be '~1d ago', not hours."""
        now = 1000000
        assert _format_relative_time(now - 86400, now) == "~1d ago"


# ===========================================================================
# _build_compression_prompt
# ===========================================================================

class TestBuildCompressionPrompt:
    def test_basic_prompt_construction(self):
        messages = [
            _msg("Hello, I need help", role="user", created_at=9000, sender_name="Alice"),
            _msg("Sure, how can I help?", role="assistant", created_at=9010, sender_name="Toon"),
        ]
        system_prompt, formatted = _build_compression_prompt(messages, None, 10000)

        assert "conversation compression assistant" in system_prompt.lower()
        assert len(formatted) == 2
        assert formatted[0]["role"] == "user"  # all formatted as user messages
        assert "Alice" in formatted[0]["content"]
        assert "Toon" in formatted[1]["content"]

    def test_previous_summary_included(self):
        messages = [_msg("test", created_at=9000)]
        system_prompt, _ = _build_compression_prompt(messages, "Old summary content", 10000)
        assert "Old summary content" in system_prompt
        assert "previous compression summary" in system_prompt.lower()

    def test_no_previous_summary(self):
        messages = [_msg("test", created_at=9000)]
        system_prompt, _ = _build_compression_prompt(messages, None, 10000)
        assert "PREVIOUS SUMMARY" not in system_prompt

    def test_compression_summary_messages_excluded(self):
        """Old compression summaries in the message list should be skipped."""
        messages = [
            _msg("Hello", created_at=9000),
            _compression_summary_msg("## Old Summary", created_at=9005),
            _msg("Goodbye", created_at=9010),
        ]
        _, formatted = _build_compression_prompt(messages, "## Old Summary", 10000)
        # Should have 2 messages (Hello, Goodbye), not 3
        assert len(formatted) == 2
        for fm in formatted:
            assert "Old Summary" not in fm["content"]

    def test_non_string_content_skipped(self):
        messages = [
            _msg("text msg", created_at=9000),
            {"role": "user", "content": ["image_data"], "created_at": 9005},
            {"role": "user", "content": None, "created_at": 9006},
            {"role": "user", "content": "", "created_at": 9007},
        ]
        _, formatted = _build_compression_prompt(messages, None, 10000)
        # Only "text msg" should be formatted (non-string, None, empty are skipped)
        assert len(formatted) == 1

    def test_relative_timestamps_in_messages(self):
        now = 10000
        messages = [
            _msg("Old message", created_at=now - 7200),  # 2h ago
            _msg("Recent message", created_at=now - 60),  # 1 min ago
        ]
        _, formatted = _build_compression_prompt(messages, None, now)
        assert "~2h ago" in formatted[0]["content"]
        assert "~1 min ago" in formatted[1]["content"]


# ===========================================================================
# compress_chat_history (async, requires monkeypatched LLM)
# ===========================================================================

class TestCompressChatHistory:
    @pytest.fixture
    def mock_secrets(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_below_threshold_returns_not_compressed(self, mock_secrets):
        """When history is below threshold, should return immediately without calling LLM."""
        history = [_msg("short") for _ in range(3)]
        result = await compress_chat_history(
            message_history=history,
            task_id="test-task",
            secrets_manager=mock_secrets,
        )
        assert result.was_compressed is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_success_path(self, mock_secrets, monkeypatch):
        """Primary LLM succeeds: should return compressed result with correct metadata."""
        # Create a history that exceeds threshold with custom low threshold
        history = _make_history(20, chars_per_msg=2000)

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.direct_message_content = "## Conversation History Summary\n20 messages compressed."

        async def fake_google_llm(**kwargs):
            return mock_response

        monkeypatch.setattr(
            "backend.apps.ai.processing.chat_compressor.invoke_google_ai_studio_chat_completions",
            fake_google_llm,
        )

        result = await compress_chat_history(
            message_history=history,
            task_id="test-task",
            secrets_manager=mock_secrets,
            compression_threshold=100,  # very low threshold to trigger compression
        )

        assert result.was_compressed is True
        assert "Summary" in result.summary_content
        assert result.compressed_message_count > 0
        assert result.summary_token_estimate > 0
        assert result.recent_messages is not None
        assert result.compressed_up_to_timestamp > 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(self, mock_secrets, monkeypatch):
        """Primary LLM fails, Cerebras fallback succeeds."""
        history = _make_history(20, chars_per_msg=2000)

        # Primary fails
        primary_response = MagicMock()
        primary_response.success = False
        primary_response.error_message = "Google API error"
        primary_response.direct_message_content = None

        # Fallback succeeds
        fallback_response = MagicMock()
        fallback_response.success = True
        fallback_response.direct_message_content = "## Summary from fallback"

        async def fake_google_llm(**kwargs):
            return primary_response

        async def fake_cerebras_llm(**kwargs):
            return fallback_response

        monkeypatch.setattr(
            "backend.apps.ai.processing.chat_compressor.invoke_google_ai_studio_chat_completions",
            fake_google_llm,
        )
        monkeypatch.setattr(
            "backend.apps.ai.llm_providers.cerebras_wrapper.invoke_cerebras_chat_completions",
            fake_cerebras_llm,
        )

        result = await compress_chat_history(
            message_history=history,
            task_id="test-task",
            secrets_manager=mock_secrets,
            compression_threshold=100,
        )

        assert result.was_compressed is True
        assert "fallback" in result.summary_content

    @pytest.mark.asyncio
    async def test_both_llms_fail(self, mock_secrets, monkeypatch):
        """Both primary and fallback LLM fail: should return error."""
        history = _make_history(20, chars_per_msg=2000)

        # Primary fails
        primary_response = MagicMock()
        primary_response.success = False
        primary_response.error_message = "Google API error"
        primary_response.direct_message_content = None

        # Fallback also fails
        fallback_response = MagicMock()
        fallback_response.success = False
        fallback_response.error_message = "Cerebras API error"
        fallback_response.direct_message_content = None

        async def fake_google_llm(**kwargs):
            return primary_response

        async def fake_cerebras_llm(**kwargs):
            return fallback_response

        monkeypatch.setattr(
            "backend.apps.ai.processing.chat_compressor.invoke_google_ai_studio_chat_completions",
            fake_google_llm,
        )
        monkeypatch.setattr(
            "backend.apps.ai.llm_providers.cerebras_wrapper.invoke_cerebras_chat_completions",
            fake_cerebras_llm,
        )

        result = await compress_chat_history(
            message_history=history,
            task_id="test-task",
            secrets_manager=mock_secrets,
            compression_threshold=100,
        )

        assert result.was_compressed is False
        assert result.error is not None
        assert "Google API error" in result.error
        assert "Cerebras API error" in result.error

    @pytest.mark.asyncio
    async def test_primary_raises_exception(self, mock_secrets, monkeypatch):
        """Primary LLM raises an exception: should return error without crashing."""
        history = _make_history(20, chars_per_msg=2000)

        async def fake_google_llm(**kwargs):
            raise ConnectionError("Network failure")

        monkeypatch.setattr(
            "backend.apps.ai.processing.chat_compressor.invoke_google_ai_studio_chat_completions",
            fake_google_llm,
        )

        result = await compress_chat_history(
            message_history=history,
            task_id="test-task",
            secrets_manager=mock_secrets,
            compression_threshold=100,
        )

        assert result.was_compressed is False
        assert result.error is not None
        assert "Network failure" in result.error

    @pytest.mark.asyncio
    async def test_no_formattable_messages(self, mock_secrets, monkeypatch):
        """History exceeds threshold but all messages have non-string content."""
        # Create messages with list content (multimodal) that _build_compression_prompt skips
        history = [
            {"role": "user", "content": [{"type": "image"}], "created_at": 1000 + i}
            for i in range(20)
        ]

        # Need to mock the google import since it happens inside the function
        async def fake_google_llm(**kwargs):
            raise AssertionError("Should not be called")

        monkeypatch.setattr(
            "backend.apps.ai.processing.chat_compressor.invoke_google_ai_studio_chat_completions",
            fake_google_llm,
        )

        result = await compress_chat_history(
            message_history=history,
            task_id="test-task",
            secrets_manager=mock_secrets,
            compression_threshold=10,  # very low to trigger
        )

        assert result.was_compressed is False
