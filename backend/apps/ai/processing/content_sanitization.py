# backend/apps/ai/processing/content_sanitization.py
#
# Content sanitization for prompt injection protection.
# Implements mandatory sanitization of external data from app skills before
# returning results to the main processing system.
#
# TWO-LAYER DEFENSE:
# 1. ASCII Smuggling Protection (character-level) - removes invisible Unicode characters
# 2. LLM-Based Detection (semantic-level) - detects malicious instructions in visible text
#
# ASCII smuggling protection runs FIRST to ensure the LLM sees clean text without
# hidden instructions embedded via invisible characters.
#
# See: docs/architecture/prompt_injection_protection.md

import logging
import yaml
import os
import re
from typing import Dict, Any, List, Optional

from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, LLMPreprocessingCallResult
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Import ASCII smuggling sanitization
# This must run BEFORE LLM-based detection to remove invisible characters
from backend.core.api.app.utils.text_sanitization import sanitize_text_for_ascii_smuggling

logger = logging.getLogger(__name__)

# Placeholder text used to replace detected prompt injection strings
# This makes it transparent that content was removed for security reasons
PROMPT_INJECTION_PLACEHOLDER = "[PROMPT INJECTION DETECTED & REMOVED]"


def _split_text_into_chunks(text: str, max_chars_per_chunk: int) -> List[str]:
    """
    Split text into chunks without breaking words.
    
    Uses efficient string methods (rfind) to find word boundaries.
    Attempts to split at word boundaries (whitespace) first, then falls back
    to character boundaries if necessary. This ensures we don't split in the
    middle of a word when chunking large text for prompt injection detection.
    
    Args:
        text: The text to split
        max_chars_per_chunk: Maximum characters per chunk
    
    Returns:
        List of text chunks
    """
    chunks = []
    current_pos = 0
    text_length = len(text)
    
    while current_pos < text_length:
        # Calculate the end position for this chunk
        chunk_end = min(current_pos + max_chars_per_chunk, text_length)
        
        # If this is the last chunk, take everything remaining
        if chunk_end >= text_length:
            chunks.append(text[current_pos:])
            break
        
        # Try to find a word boundary (whitespace) near the chunk end
        # Use rfind() for efficient backwards search (much faster than loop)
        # Search up to 10% of chunk size backwards to find a good break point
        search_back_limit = max(1, int(max_chars_per_chunk * 0.1))
        search_start = max(current_pos, chunk_end - search_back_limit)
        
        # Use rfind to efficiently find the last whitespace in the search range
        # rfind searches backwards from chunk_end, but we need to limit the search range
        # So we search in the substring from search_start to chunk_end
        search_text = text[search_start:chunk_end]
        # Find whitespace characters (space, tab, newline, etc.)
        # rfind returns the index relative to search_start, so we need to adjust
        # Try space first (most common), then other whitespace characters
        last_whitespace_in_search = search_text.rfind(' ')
        if last_whitespace_in_search == -1:
            # Try other whitespace characters
            for ws_char in ['\n', '\t', '\r']:
                pos = search_text.rfind(ws_char)
                if pos != -1 and (last_whitespace_in_search == -1 or pos > last_whitespace_in_search):
                    last_whitespace_in_search = pos
        
        # Adjust position to be relative to the full text
        if last_whitespace_in_search != -1:
            last_whitespace = search_start + last_whitespace_in_search
        else:
            last_whitespace = -1
        
        # If we found a whitespace, split there (inclusive of the whitespace)
        # Otherwise, split at the character boundary (may split a word, but better than nothing)
        if last_whitespace > current_pos:
            # Include the whitespace in the current chunk
            chunk_end = last_whitespace + 1
            chunks.append(text[current_pos:chunk_end])
            # Start next chunk after the whitespace
            current_pos = chunk_end
        else:
            # No whitespace found, split at character boundary
            # This might split a word, but it's better than not chunking at all
            chunks.append(text[current_pos:chunk_end])
            current_pos = chunk_end
    
    return chunks


def _load_content_sanitization_model() -> Optional[str]:
    """
    Load the content sanitization model ID from the AI app's app.yml.
    
    The model is configured in app.yml under:
    skills[].skill_config.default_llms.content_sanitization_model
    
    Returns:
        Model ID string, or None if not found or loading fails
    
    Raises:
        ValueError: If the model is not configured (to ensure we know about the error)
    """
    # Determine the AI app's directory
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    ai_app_dir = os.path.dirname(current_file_dir)
    app_yml_path = os.path.join(ai_app_dir, "app.yml")
    
    if not os.path.exists(app_yml_path):
        logger.error(f"AI app.yml not found at {app_yml_path}")
        return None
    
    try:
        with open(app_yml_path, 'r', encoding='utf-8') as f:
            app_config = yaml.safe_load(f)
        
        if not app_config:
            logger.error(f"AI app.yml is empty or malformed at {app_yml_path}")
            return None
        
        # Navigate to the content_sanitization_model
        # Path: skills -> find 'ask' skill -> skill_config -> default_llms -> content_sanitization_model
        skills = app_config.get("skills", [])
        for skill in skills:
            if skill.get("id", "").strip() == "ask":
                skill_config = skill.get("skill_config", {})
                default_llms = skill_config.get("default_llms", {})
                model_id = default_llms.get("content_sanitization_model")
                
                if model_id:
                    # Strip whitespace (YAML can have trailing newlines)
                    model_id = model_id.strip() if isinstance(model_id, str) else None
                    if model_id:
                        logger.debug(f"Loaded content sanitization model: {model_id}")
                        return model_id
                    else:
                        logger.error(f"Content sanitization model is empty in app.yml at {app_yml_path}")
                        return None
        
        logger.error(f"Content sanitization model not found in 'ask' skill config in app.yml at {app_yml_path}")
        return None
        
    except Exception as e:
        logger.error(f"Error loading content sanitization model from app.yml: {e}", exc_info=True)
        return None


def _load_prompt_injection_detection_config() -> Optional[Dict[str, Any]]:
    """
    Load the prompt injection detection configuration from YAML file.
    
    Returns:
        Dict containing the detection configuration, or None if loading fails
    """
    # Determine the AI app's directory
    # This file is at backend/apps/ai/processing/content_sanitization.py
    # So we need to go up to backend/apps/ai/
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    ai_app_dir = os.path.dirname(current_file_dir)
    config_path = os.path.join(ai_app_dir, "prompt_injection_detection.yml")
    
    if not os.path.exists(config_path):
        logger.error(f"Prompt injection detection config not found at {config_path}")
        return None
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        if not config:
            logger.error("Prompt injection detection config is empty or malformed")
            return None
        logger.debug(f"Successfully loaded prompt injection detection config from {config_path}")
        return config
    except Exception as e:
        logger.error(f"Error loading prompt injection detection config: {e}", exc_info=True)
        return None


async def _sanitize_text_chunk(
    chunk: str,
    chunk_index: int,
    total_chunks: int,
    task_id: str,
    detection_config: Dict[str, Any],
    block_threshold: float,
    review_threshold: float,
    secrets_manager: Optional[SecretsManager],
    cache_service: Optional[Any] = None  # CacheService type, but avoid circular import
) -> Optional[str]:
    """
    Sanitize a single text chunk by detecting and replacing prompt injection strings with a placeholder.
    
    When prompt injection strings are detected, they are replaced with '[PROMPT INJECTION DETECTED & REMOVED]'
    to make it transparent that content was removed for security reasons. This helps with debugging and
    provides visibility into what was sanitized.
    
    Args:
        chunk: The text chunk to sanitize
        chunk_index: Index of this chunk (0-based)
        total_chunks: Total number of chunks
        task_id: Task ID for logging
        detection_config: The loaded detection configuration
        block_threshold: Score threshold for blocking content
        review_threshold: Score threshold for review
        secrets_manager: Optional secrets manager for LLM calls
    
    Returns:
        Sanitized chunk with injection strings replaced by placeholder, or None if chunk should be blocked
    """
    try:
        # Get the detection tool definition and system prompt
        tool_definition = detection_config.get("prompt_injection_detection_tool")
        system_prompt = detection_config.get("prompt_injection_detection_system_prompt", "")
        
        if not tool_definition:
            logger.error(f"[{task_id}] Detection tool definition not found in config")
            return chunk  # Return as-is if config is invalid
        
        # Load content sanitization model from cache (preloaded by main API server at startup)
        # The main API server preloads this into the shared Dragonfly cache during startup.
        # Fallback to disk loading if cache is empty (e.g., cache expired or server restarted).
        model_id: Optional[str] = None
        try:
            if cache_service:
                model_id = await cache_service.get_content_sanitization_model()
                if model_id:
                    logger.debug(f"[{task_id}] Successfully loaded content_sanitization_model from cache (preloaded by main API server): {model_id}")
                else:
                    # Fallback: Cache is empty (expired or server restarted) - load from disk and re-cache
                    logger.warning(f"[{task_id}] content_sanitization_model not found in cache. Loading from disk and re-caching...")
                    model_id = _load_content_sanitization_model()
                    if model_id:
                        try:
                            await cache_service.set_content_sanitization_model(model_id)
                            logger.debug(f"[{task_id}] Re-cached content_sanitization_model after disk load: {model_id}")
                        except Exception as e:
                            logger.warning(f"[{task_id}] Failed to re-cache content_sanitization_model: {e}")
            else:
                # No cache service available, load from disk
                logger.warning(f"[{task_id}] CacheService not available. Loading content_sanitization_model from disk...")
                model_id = _load_content_sanitization_model()
        except Exception as e:
            logger.error(f"[{task_id}] Error loading content_sanitization_model: {e}", exc_info=True)
            # Fallback to disk loading
            model_id = _load_content_sanitization_model()
        
        if not model_id:
            error_msg = f"[{task_id}] Content sanitization model not configured in app.yml or cache. Cannot sanitize content."
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Prepare message history for detection
        # Include system prompt as first message if available
        message_history = []
        if system_prompt:
            message_history.append({"role": "system", "content": system_prompt})
        message_history.append({"role": "user", "content": chunk})
        
        # Log sanitization request details for debugging
        # This is critical for verifying requests are being made to OpenRouter
        logger.info(
            f"[{task_id}] CONTENT SANITIZATION REQUEST - "
            f"Chunk {chunk_index+1}/{total_chunks}, Model: {model_id}, "
            f"Content length: {len(chunk)} chars"
        )
        logger.info(
            f"[{task_id}] CONTENT SANITIZATION SYSTEM PROMPT: {system_prompt[:500]}{'...' if len(system_prompt) > 500 else ''}"
        )
        logger.info(
            f"[{task_id}] CONTENT SANITIZATION DATA (first 1000 chars): {chunk[:1000]}{'...' if len(chunk) > 1000 else ''}"
        )
        logger.debug(
            f"[{task_id}] CONTENT SANITIZATION FULL DATA: {chunk}"
        )
        
        # Call LLM for prompt injection detection
        logger.info(f"[{task_id}] Calling LLM for prompt injection detection on chunk {chunk_index+1}/{total_chunks}")
        result: LLMPreprocessingCallResult = await call_preprocessing_llm(
            task_id=f"{task_id}_chunk_{chunk_index}",
            model_id=model_id,
            message_history=message_history,
            tool_definition=tool_definition,
            secrets_manager=secrets_manager
        )
        
        # Log sanitization response
        if result.error_message:
            logger.error(
                f"[{task_id}] CONTENT SANITIZATION RESPONSE ERROR: {result.error_message}"
            )
        else:
            logger.info(
                f"[{task_id}] CONTENT SANITIZATION RESPONSE SUCCESS - "
                f"Arguments: {result.arguments if result.arguments else 'None'}"
            )
        
        # Check if call was successful (error_message is None) and has arguments
        if result.error_message or not result.arguments:
            error_msg = f"[{task_id}] Prompt injection detection failed for chunk {chunk_index+1}: {result.error_message or 'No arguments returned'}."
            
            # Add helpful hint for self-hosted users if it looks like a provider error
            if result.error_message and ("Groq" in result.error_message or "API key" in result.error_message.lower()):
                error_msg += " HINT: This usually indicates the Groq API key is missing or invalid. Groq is REQUIRED for content sanitization when using skills that fetch external data. Please check your .env file and Vault configuration."
            
            error_msg += " This is a critical security failure - cannot proceed with unsanitized external content."
            logger.error(error_msg)
            # Return None to indicate failure - caller should handle this as an error
            return None
        
        # Extract detection results
        detection_score = result.arguments.get("prompt_injection_chance", 0.0)
        injection_strings = result.arguments.get("injection_strings", [])
        
        logger.debug(
            f"[{task_id}] Chunk {chunk_index+1}/{total_chunks} detection: "
            f"score={detection_score:.1f}, strings={len(injection_strings)}"
        )
        
        # Block if score is above block threshold
        if detection_score >= block_threshold:
            logger.warning(
                f"[{task_id}] Chunk {chunk_index+1}/{total_chunks} blocked: "
                f"score {detection_score:.1f} >= block threshold {block_threshold}"
            )
            return None  # Block this chunk
        
        # Replace injection strings with placeholder if any were detected
        sanitized_chunk = chunk
        if injection_strings:
            logger.info(
                f"[{task_id}] Replacing {len(injection_strings)} injection string(s) with placeholder in chunk {chunk_index+1}/{total_chunks}"
            )
            for injection_string in injection_strings:
                # Replace exact string matches (case-sensitive) with placeholder
                # This makes it transparent that content was removed for security
                sanitized_chunk = sanitized_chunk.replace(injection_string, PROMPT_INJECTION_PLACEHOLDER)
            
            # Clean up any double placeholders that might result from overlapping or adjacent replacements
            # Replace multiple consecutive placeholders with a single one
            sanitized_chunk = re.sub(
                rf'({re.escape(PROMPT_INJECTION_PLACEHOLDER)}\s*)+',
                PROMPT_INJECTION_PLACEHOLDER,
                sanitized_chunk
            )
            
            # Clean up any excessive whitespace while preserving the placeholder
            # Replace multiple spaces/newlines with single space, but keep placeholders intact
            sanitized_chunk = re.sub(r'\s+', ' ', sanitized_chunk).strip()
        
        # Log if score is in review range
        if detection_score >= review_threshold:
            logger.info(
                f"[{task_id}] Chunk {chunk_index+1}/{total_chunks} flagged for review: "
                f"score {detection_score:.1f} (review threshold: {review_threshold})"
            )
        
        return sanitized_chunk
        
    except Exception as e:
        logger.error(
            f"[{task_id}] Error sanitizing chunk {chunk_index+1}/{total_chunks}: {e}",
            exc_info=True
        )
        # On error, return None to block (safer than allowing potentially malicious content)
        return None


async def sanitize_external_content(
    content: str,
    content_type: str = "text",
    task_id: str = "sanitization",
    secrets_manager: Optional[SecretsManager] = None,
    cache_service: Optional[Any] = None  # CacheService type, but avoid circular import
) -> str:
    """
    Sanitize external content to prevent prompt injection attacks.
    
    This function implements the mandatory sanitization process for all app skills
    that access external APIs or gather external data. See docs/architecture/apps/app_skills.md
    for detailed requirements.
    
    TWO-LAYER DEFENSE PROCESS:
    
    Layer 1 - ASCII Smuggling Protection (Character-Level):
    1. Remove invisible Unicode characters that could hide malicious instructions
    2. This includes: Unicode Tags, Variant Selectors, Zero-Width chars, BiDi controls, etc.
    3. Log security alerts if hidden content is detected
    
    Layer 2 - LLM-Based Detection (Semantic-Level):
    4. For images: Return empty string (image processing comes later)
    5. For text: Split long text into chunks of 50,000 tokens maximum
    6. Detect prompt injection attacks using LLM function call
    7. Sanitize text content by replacing detected injection strings with '[PROMPT INJECTION DETECTED & REMOVED]'
    8. Combine sanitized chunks back together
    
    Args:
        content: The content to sanitize (text or image data)
        content_type: Type of content - "text" or "image"
        task_id: Task ID for logging (default: "sanitization")
        secrets_manager: Optional secrets manager for LLM API calls
    
    Returns:
        Sanitized content (or empty string if image is rejected or text is blocked)
    """
    # Image processing comes later - reject images for now
    if content_type == "image":
        logger.debug(f"[{task_id}] Image sanitization not yet implemented, rejecting image content")
        return ""
    
    # For text content, perform sanitization
    if not isinstance(content, str):
        logger.warning(f"[{task_id}] Content is not a string, cannot sanitize")
        return str(content) if content else ""
    
    if not content.strip():
        logger.debug(f"[{task_id}] Empty content, nothing to sanitize")
        return content
    
    try:
        # =========================================================================
        # LAYER 1: ASCII SMUGGLING PROTECTION (Character-Level)
        # =========================================================================
        # Remove invisible Unicode characters BEFORE LLM-based detection.
        # External APIs could return content with hidden instructions encoded via:
        # - Unicode Tags (U+E0000-U+E007F) - maps to hidden ASCII
        # - Variant Selectors (U+FE00-U+FE0F, U+E0100-U+E01EF)
        # - Zero-Width Characters (ZWSP, ZWNJ, ZWJ, Word Joiner, BOM)
        # - Bidirectional Controls (LRO, RLO, LRE, RLE, etc.)
        # - Other invisible/formatting characters
        #
        # This ensures the LLM sees clean text without hidden instructions.
        # =========================================================================
        
        ascii_smuggling_log_prefix = f"[{task_id}][EXTERNAL] "
        content, ascii_stats = sanitize_text_for_ascii_smuggling(
            content,
            log_prefix=ascii_smuggling_log_prefix,
            include_stats=True
        )
        
        # Log security alert if hidden content was detected (potential attack from external source)
        if ascii_stats.get("hidden_ascii_detected"):
            logger.warning(
                f"[{task_id}][SECURITY ALERT] ASCII smuggling detected in EXTERNAL content! "
                f"Hidden Unicode Tags content found and removed. This may indicate a compromised external source. "
                f"Removed {ascii_stats['removed_count']} invisible characters: "
                f"Unicode Tags={ascii_stats['unicode_tags_count']}, "
                f"Zero-Width={ascii_stats['zero_width_count']}, "
                f"BiDi Controls={ascii_stats['bidi_control_count']}"
            )
        elif ascii_stats.get("removed_count", 0) > 0:
            logger.info(
                f"[{task_id}][ASCII SANITIZATION] Removed {ascii_stats['removed_count']} "
                f"invisible characters from external content before LLM detection"
            )
        
        # If content became empty after ASCII sanitization, it was likely all hidden chars
        if not content.strip():
            logger.warning(
                f"[{task_id}] External content became empty after ASCII smuggling removal. "
                f"Original may have been entirely hidden characters (attack attempt)."
            )
            return ""
        
        # =========================================================================
        # LAYER 2: LLM-BASED PROMPT INJECTION DETECTION (Semantic-Level)
        # =========================================================================
        # Now that invisible characters are removed, the LLM can analyze the
        # visible text for semantic prompt injection patterns.
        # =========================================================================
        # Load prompt injection detection configuration from cache (preloaded by main API server at startup)
        # The main API server preloads this into the shared Dragonfly cache during startup.
        # Fallback to disk loading if cache is empty (e.g., cache expired or server restarted).
        detection_config: Optional[Dict[str, Any]] = None
        try:
            if cache_service:
                detection_config = await cache_service.get_prompt_injection_detection_config()
                if detection_config:
                    logger.debug(f"[{task_id}] Successfully loaded prompt_injection_detection_config from cache (preloaded by main API server).")
                else:
                    # Fallback: Cache is empty (expired or server restarted) - load from disk and re-cache
                    logger.warning(f"[{task_id}] prompt_injection_detection_config not found in cache. Loading from disk and re-caching...")
                    detection_config = _load_prompt_injection_detection_config()
                    if detection_config:
                        try:
                            await cache_service.set_prompt_injection_detection_config(detection_config)
                            logger.debug(f"[{task_id}] Re-cached prompt_injection_detection_config after disk load.")
                        except Exception as e:
                            logger.warning(f"[{task_id}] Failed to re-cache prompt_injection_detection_config: {e}")
            else:
                # No cache service available, load from disk
                logger.warning(f"[{task_id}] CacheService not available. Loading prompt_injection_detection_config from disk...")
                detection_config = _load_prompt_injection_detection_config()
        except Exception as e:
            logger.error(f"[{task_id}] Error loading prompt_injection_detection_config: {e}", exc_info=True)
            # Fallback to disk loading
            detection_config = _load_prompt_injection_detection_config()
        
        if not detection_config:
            logger.error(f"[{task_id}] Failed to load prompt injection detection config from cache or disk, skipping sanitization")
            return content
        
        # Get configuration values
        max_tokens_per_chunk = detection_config.get("text_chunking", {}).get("max_tokens_per_chunk", 50000)
        block_threshold = detection_config.get("prompt_injection_thresholds", {}).get("block_threshold", 7.0)
        review_threshold = detection_config.get("prompt_injection_thresholds", {}).get("review_threshold", 5.0)
        
        # Estimate tokens (conservative: ~4 chars per token)
        chars_per_token = 4
        estimated_tokens = len(content) / chars_per_token
        
        # Split into chunks if needed
        max_chars_per_chunk = max_tokens_per_chunk * chars_per_token
        chunks = []
        if len(content) > max_chars_per_chunk:
            logger.info(f"[{task_id}] Content is {estimated_tokens:.0f} tokens, splitting into chunks")
            chunks = _split_text_into_chunks(content, max_chars_per_chunk)
        else:
            chunks = [content]
        
        logger.info(f"[{task_id}] Processing {len(chunks)} chunk(s) for sanitization (total content: {len(content)} chars, ~{estimated_tokens:.0f} tokens)")
        
        # Sanitize each chunk
        sanitized_chunks = []
        for i, chunk in enumerate(chunks):
            sanitized_chunk = await _sanitize_text_chunk(
                chunk=chunk,
                chunk_index=i,
                total_chunks=len(chunks),
                task_id=task_id,
                detection_config=detection_config,
                block_threshold=block_threshold,
                review_threshold=review_threshold,
                secrets_manager=secrets_manager,
                cache_service=cache_service
            )
            
            # If chunk was blocked (high risk), block entire content
            if sanitized_chunk is None:
                logger.warning(f"[{task_id}] Chunk {i+1}/{len(chunks)} was blocked due to high prompt injection risk")
                return ""  # Block entire content if any chunk is high risk
            
            sanitized_chunks.append(sanitized_chunk)
        
        # Combine sanitized chunks
        sanitized_content = "".join(sanitized_chunks)
        logger.info(f"[{task_id}] Content sanitization completed: {len(content)} -> {len(sanitized_content)} chars")
        return sanitized_content
        
    except Exception as e:
        logger.error(f"[{task_id}] Error during content sanitization: {e}", exc_info=True)
        # On error, return empty string to be safe (don't risk passing through malicious content)
        return ""

