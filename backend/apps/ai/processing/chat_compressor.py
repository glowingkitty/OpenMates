# backend/apps/ai/processing/chat_compressor.py
# Chat compression module: summarizes older messages when chat history exceeds token budget.
#
# When the total token estimate of a chat's message history (including system prompt overhead)
# exceeds the compression threshold, older messages are summarized into a structured summary.
# The summary is stored as a system message (role="system", category="compression_summary")
# in the chat. Messages older than the summary are considered "forgotten" — not synced by
# default and removed from the AI inference cache.
#
# Architecture context: See docs/architecture/chat-compression.md for design rationale.
# Tests: None yet

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# --- Constants ---

# Token threshold at which compression is triggered. When the message history
# plus estimated system prompt overhead exceeds this, older messages are summarized.
# All models in the system have >= 128k context, so 100k leaves comfortable headroom.
DEFAULT_COMPRESSION_TRIGGER_THRESHOLD = 100_000  # tokens (estimated)

# Token budget for the "recent window" — the most recent messages kept in full
# after compression. Uses the same logic as truncation: walk backwards from newest,
# accumulating tokens, stop at this budget. Minimum: keep at least the last 6 messages.
RECENT_WINDOW_TOKEN_BUDGET = 10_000  # tokens
RECENT_WINDOW_MIN_MESSAGES = 6  # Always keep at least this many recent messages

# Target maximum tokens for the generated summary itself.
MAX_SUMMARY_TOKENS = 5_000

# Estimated token overhead for system prompt + tools (not part of message history
# but occupies context window space). Used when checking if compression is needed.
ESTIMATED_SYSTEM_PROMPT_OVERHEAD = 15_000  # tokens

# Average chars per token for estimation (matches llm_utils.py)
AVG_CHARS_PER_TOKEN = 4.0

# Redis cache key for admin compression override
ADMIN_COMPRESSION_THRESHOLD_CACHE_KEY = "admin:compression_threshold_override"

# Category marker for compression summary system messages
COMPRESSION_SUMMARY_CATEGORY = "compression_summary"

# Compression model: Gemini 3 Flash (fast, cheap, 1M context)
COMPRESSION_MODEL_ID = "gemini-3-flash-preview"
COMPRESSION_MODEL_SERVER = "google_ai_studio"  # Default server for Gemini Flash


class CompressionResult(BaseModel):
    """Result of a chat compression operation."""
    was_compressed: bool = False
    summary_content: Optional[str] = None  # The structured summary text
    compressed_message_count: int = 0  # Number of messages that were compressed
    summary_token_estimate: int = 0  # Estimated tokens in the summary
    recent_messages: Optional[List[Dict[str, Any]]] = None  # Messages kept in full
    compressed_up_to_timestamp: Optional[int] = None  # Timestamp of newest compressed message
    error: Optional[str] = None


def estimate_tokens_for_message(msg: Dict[str, Any]) -> int:
    """Estimate token count for a single message using character-based estimation.

    Matches the estimation logic in llm_utils.truncate_message_history_to_token_budget().
    """
    content = msg.get("content", "")
    tokens = 4  # Base overhead per message (role, metadata, formatting)

    if isinstance(content, str):
        tokens += len(content) / AVG_CHARS_PER_TOKEN
    elif isinstance(content, list):
        # Multimodal content (list of content parts)
        for part in content:
            if isinstance(part, dict):
                text = part.get("text", "")
                if text:
                    tokens += len(text) / AVG_CHARS_PER_TOKEN
    return int(tokens)


def estimate_total_tokens(message_history: List[Dict[str, Any]]) -> int:
    """Estimate total tokens across all messages in the history."""
    return sum(estimate_tokens_for_message(msg) for msg in message_history)


def should_compress(
    message_history: List[Dict[str, Any]],
    compression_threshold: int = DEFAULT_COMPRESSION_TRIGGER_THRESHOLD,
) -> bool:
    """Check if the message history should be compressed.

    Compression is triggered when the total estimated tokens of message history
    plus system prompt overhead exceeds the threshold.

    Args:
        message_history: List of message dicts with 'role', 'content', 'created_at'.
        compression_threshold: Token threshold (default 100k, can be overridden by admin).

    Returns:
        True if compression should be triggered.
    """
    if not message_history:
        return False

    total_tokens = estimate_total_tokens(message_history)
    total_with_overhead = total_tokens + ESTIMATED_SYSTEM_PROMPT_OVERHEAD

    logger.debug(
        f"Compression check: {len(message_history)} messages, "
        f"~{total_tokens} message tokens + ~{ESTIMATED_SYSTEM_PROMPT_OVERHEAD} overhead = "
        f"~{total_with_overhead} total vs {compression_threshold} threshold"
    )

    return total_with_overhead >= compression_threshold


def split_history_for_compression(
    message_history: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split message history into messages to compress and recent messages to keep.

    Walks backwards from the newest message, accumulating tokens until the
    RECENT_WINDOW_TOKEN_BUDGET is reached. Always keeps at least RECENT_WINDOW_MIN_MESSAGES.

    Also handles existing compression summaries: if one exists in the history, it is
    included in the messages_to_compress (so the new summary can incorporate the old one)
    and excluded from the recent window.

    Args:
        message_history: Full message history in chronological order (oldest first).

    Returns:
        Tuple of (messages_to_compress, recent_messages).
        messages_to_compress may include a previous compression summary.
    """
    if not message_history:
        return [], []

    # Walk backwards to find the split point
    accumulated_tokens = 0
    split_index = len(message_history)

    for i in range(len(message_history) - 1, -1, -1):
        msg = message_history[i]

        # Never include compression summary system messages in the recent window —
        # they belong to the "to compress" set and will be replaced by the new summary
        if (msg.get("role") == "system"
                and msg.get("category") == COMPRESSION_SUMMARY_CATEGORY):
            continue

        msg_tokens = estimate_tokens_for_message(msg)

        # Always keep at least RECENT_WINDOW_MIN_MESSAGES
        messages_in_recent = len(message_history) - i
        if messages_in_recent <= RECENT_WINDOW_MIN_MESSAGES:
            accumulated_tokens += msg_tokens
            split_index = i
            continue

        # Beyond minimum, check token budget
        if accumulated_tokens + msg_tokens > RECENT_WINDOW_TOKEN_BUDGET:
            split_index = i + 1
            break

        accumulated_tokens += msg_tokens
        split_index = i

    # Split the history
    messages_to_compress = message_history[:split_index]
    recent_messages = [
        msg for msg in message_history[split_index:]
        if not (msg.get("role") == "system"
                and msg.get("category") == COMPRESSION_SUMMARY_CATEGORY)
    ]

    logger.info(
        f"Split history: {len(messages_to_compress)} messages to compress, "
        f"{len(recent_messages)} recent messages to keep (~{accumulated_tokens} tokens)"
    )

    return messages_to_compress, recent_messages


def _find_existing_summary(messages: List[Dict[str, Any]]) -> Optional[str]:
    """Find an existing compression summary in the message list.

    Returns the content of the most recent compression_summary system message, or None.
    """
    for msg in reversed(messages):
        if (msg.get("role") == "system"
                and msg.get("category") == COMPRESSION_SUMMARY_CATEGORY):
            return msg.get("content")
    return None


def _format_relative_time(timestamp: int, now_timestamp: int) -> str:
    """Format a Unix timestamp as a relative time string."""
    diff_seconds = now_timestamp - timestamp
    if diff_seconds < 60:
        return "just now"
    elif diff_seconds < 3600:
        minutes = diff_seconds // 60
        return f"~{minutes} min ago"
    elif diff_seconds < 86400:
        hours = diff_seconds // 3600
        return f"~{hours}h ago"
    else:
        days = diff_seconds // 86400
        return f"~{days}d ago"


def _build_compression_prompt(
    messages_to_compress: List[Dict[str, Any]],
    previous_summary: Optional[str],
    now_timestamp: int,
) -> Tuple[str, List[Dict[str, str]]]:
    """Build the system prompt and message history for the compression LLM call.

    Args:
        messages_to_compress: Messages to summarize (may include old compression summary).
        previous_summary: Content of any previous compression summary found in the messages.
        now_timestamp: Current Unix timestamp for relative time calculations.

    Returns:
        Tuple of (system_prompt, formatted_messages).
    """
    system_prompt = (
        "You are a conversation compression assistant. Your task is to create a structured "
        "summary that preserves ALL essential details from the conversation history below. "
        "The summary will replace these messages in the AI's context window, so nothing "
        "important should be lost.\n\n"
        "Rules:\n"
        "- Use structured bullet points grouped by topic or phase of the conversation\n"
        "- Include relative timestamps for each phase (e.g., '~2 hours ago', '~30 min ago')\n"
        "- Preserve: key decisions made, specific code snippets or file names referenced, "
        "  technologies/tools/libraries discussed, URLs shared\n"
        "- Preserve: what embed content contained — web search results and key findings, "
        "  documents uploaded and their key content, code files processed and their purpose, "
        "  images described, maps/places looked up\n"
        "- Preserve: any user preferences, constraints, or requirements expressed\n"
        "- Preserve: errors encountered, debugging steps taken, solutions found\n"
        "- Include a 'Key Decisions' section listing decisions and their reasoning\n"
        "- Include a 'Referenced Artifacts' section listing code files, documents, "
        "  web searches, and other embeds that were used — only list what actually exists\n"
        "- Do NOT list categories of artifacts that were not present (e.g., do not write "
        "  'Documents: None uploaded' — simply omit the category)\n"
        "- Write in the same language the conversation is in\n"
        f"- Target length: concise but comprehensive (aim for under ~{MAX_SUMMARY_TOKENS} tokens)\n"
        "- Start with: '## Conversation History Summary' followed by a line stating "
        "  how many messages were compressed and the time span\n"
    )

    if previous_summary:
        system_prompt += (
            "\nA previous compression summary exists from an earlier round of compression. "
            "Incorporate its contents into your new summary, updating and consolidating as needed. "
            "Do not lose any information from the previous summary.\n\n"
            "[PREVIOUS SUMMARY]\n"
            f"{previous_summary}\n"
            "[END PREVIOUS SUMMARY]\n"
        )

    system_prompt += "\nNow summarize the following messages:"

    # Format messages for the LLM
    formatted_messages = []
    for msg in messages_to_compress:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        timestamp = msg.get("created_at", now_timestamp)

        # Skip old compression summaries — their content is in previous_summary already
        if (role == "system"
                and msg.get("category") == COMPRESSION_SUMMARY_CATEGORY):
            continue

        if not content or not isinstance(content, str):
            continue

        relative_time = _format_relative_time(timestamp, now_timestamp)
        sender = msg.get("sender_name", role)

        # Format as a single user message for the compression LLM
        formatted_messages.append({
            "role": "user",
            "content": f"[{relative_time}] [{sender}]: {content}"
        })

    return system_prompt, formatted_messages


async def compress_chat_history(
    message_history: List[Dict[str, Any]],
    task_id: str,
    secrets_manager: SecretsManager,
    compression_threshold: int = DEFAULT_COMPRESSION_TRIGGER_THRESHOLD,
) -> CompressionResult:
    """Compress older messages in a chat history into a structured summary.

    This is the main entry point for chat compression. It:
    1. Checks if compression is needed (token threshold)
    2. Splits history into messages to compress and recent messages to keep
    3. Finds any existing compression summary
    4. Calls the compression LLM (Gemini 3 Flash) to generate a new summary
    5. Returns the result with summary content and metadata

    Args:
        message_history: Full message history in chronological order (oldest first).
            Each message is a dict with 'role', 'content', 'created_at', etc.
        task_id: Task ID for logging correlation.
        secrets_manager: For LLM API key retrieval.
        compression_threshold: Token threshold override (for admin testing).

    Returns:
        CompressionResult with summary content and metadata.
    """
    log_prefix = f"[{task_id}] Compression:"

    if not should_compress(message_history, compression_threshold):
        return CompressionResult(was_compressed=False)

    compress_start = time.time()
    logger.info(
        f"{log_prefix} Compression triggered. "
        f"{len(message_history)} messages, "
        f"~{estimate_total_tokens(message_history)} estimated tokens."
    )

    # Split history
    messages_to_compress, recent_messages = split_history_for_compression(message_history)

    if not messages_to_compress:
        logger.info(f"{log_prefix} No messages to compress after split. Skipping.")
        return CompressionResult(was_compressed=False)

    # Check for existing compression summary in the messages being compressed
    previous_summary = _find_existing_summary(messages_to_compress)
    if previous_summary:
        logger.info(f"{log_prefix} Found existing compression summary to incorporate.")

    # Calculate the timestamp of the newest compressed message
    compressed_up_to_timestamp = max(
        (msg.get("created_at", 0) for msg in messages_to_compress
         if msg.get("role") != "system" or msg.get("category") != COMPRESSION_SUMMARY_CATEGORY),
        default=0
    )

    now_timestamp = int(time.time())

    # Build compression prompt
    system_prompt, formatted_messages = _build_compression_prompt(
        messages_to_compress, previous_summary, now_timestamp
    )

    if not formatted_messages:
        logger.warning(f"{log_prefix} No formattable messages to compress. Skipping.")
        return CompressionResult(was_compressed=False)

    # Call the compression LLM
    try:
        from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions

        llm_messages = [{"role": "system", "content": system_prompt}]
        llm_messages.extend(formatted_messages)

        logger.info(
            f"{log_prefix} Calling compression LLM ({COMPRESSION_MODEL_ID}) with "
            f"{len(formatted_messages)} messages to summarize."
        )

        response = await invoke_google_ai_studio_chat_completions(
            task_id=f"{task_id}_compression",
            model_id=COMPRESSION_MODEL_ID,
            messages=llm_messages,
            secrets_manager=secrets_manager,
            temperature=0.3,  # Low temperature for factual summarization
            max_tokens=MAX_SUMMARY_TOKENS * 4,  # Chars, not tokens — allow generous output
            stream=False,
        )

        if not response.success or not response.direct_message_content:
            error_msg = response.error_message or "No content returned from compression LLM"
            logger.error(f"{log_prefix} Compression LLM call failed: {error_msg}")

            # Fallback: try Cerebras with Qwen 3
            try:
                logger.info(f"{log_prefix} Attempting fallback to Cerebras Qwen 3 for compression.")
                from backend.apps.ai.llm_providers.cerebras_wrapper import invoke_cerebras_chat_completions

                response = await invoke_cerebras_chat_completions(
                    task_id=f"{task_id}_compression_fallback",
                    model_id="qwen-3-235b-a22b-instruct-2507",
                    messages=llm_messages,
                    secrets_manager=secrets_manager,
                    temperature=0.3,
                    max_tokens=MAX_SUMMARY_TOKENS * 4,
                    stream=False,
                )

                if not response.success or not response.direct_message_content:
                    fallback_error = response.error_message or "Fallback also failed"
                    logger.error(f"{log_prefix} Fallback compression also failed: {fallback_error}")
                    return CompressionResult(
                        was_compressed=False,
                        error=f"Compression failed: {error_msg}. Fallback: {fallback_error}"
                    )
            except Exception as e_fallback:
                logger.error(f"{log_prefix} Fallback compression exception: {e_fallback}", exc_info=True)
                return CompressionResult(
                    was_compressed=False,
                    error=f"Compression failed: {error_msg}. Fallback exception: {e_fallback}"
                )

        summary_content = response.direct_message_content.strip()
        summary_token_estimate = int(len(summary_content) / AVG_CHARS_PER_TOKEN)

        compress_time = time.time() - compress_start
        logger.info(
            f"{log_prefix} Compression complete in {compress_time:.2f}s. "
            f"Compressed {len(messages_to_compress)} messages into ~{summary_token_estimate} token summary. "
            f"Keeping {len(recent_messages)} recent messages."
        )

        return CompressionResult(
            was_compressed=True,
            summary_content=summary_content,
            compressed_message_count=len(messages_to_compress),
            summary_token_estimate=summary_token_estimate,
            recent_messages=[msg for msg in recent_messages],
            compressed_up_to_timestamp=compressed_up_to_timestamp,
        )

    except Exception as e:
        logger.error(f"{log_prefix} Compression failed with exception: {e}", exc_info=True)
        return CompressionResult(
            was_compressed=False,
            error=f"Compression exception: {e}"
        )


async def get_admin_compression_threshold(
    cache_service: Any,
    user_id: str,
) -> Optional[int]:
    """Check if the admin has set a custom compression threshold for testing.

    This allows admins to test compression with lower thresholds without affecting
    all users. The override is stored in Redis and applies only to admin accounts.

    Args:
        cache_service: CacheService instance for Redis access.
        user_id: User ID to check admin status for.

    Returns:
        Custom threshold in tokens, or None to use the default.
    """
    try:
        override = await cache_service.redis_client.get(
            f"{ADMIN_COMPRESSION_THRESHOLD_CACHE_KEY}:{user_id}"
        )
        if override:
            threshold = int(override)
            logger.info(
                f"Using admin compression threshold override: {threshold} tokens "
                f"for user {user_id}"
            )
            return threshold
    except Exception as e:
        logger.debug(f"Failed to check admin compression threshold: {e}")
    return None
