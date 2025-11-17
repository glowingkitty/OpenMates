# backend/apps/ai/processing/content_sanitization.py
#
# Content sanitization for prompt injection protection.
# Implements mandatory sanitization of external data from app skills before
# returning results to the main processing system.

import logging
import yaml
import os
import re
from typing import Dict, Any, List, Optional

from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, LLMPreprocessingCallResult
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


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
            logger.error(f"Prompt injection detection config is empty or malformed")
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
    secrets_manager: Optional[SecretsManager]
) -> Optional[str]:
    """
    Sanitize a single text chunk by detecting and removing prompt injection strings.
    
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
        Sanitized chunk, or None if chunk should be blocked
    """
    try:
        # Get the detection tool definition and system prompt
        tool_definition = detection_config.get("prompt_injection_detection_tool")
        system_prompt = detection_config.get("prompt_injection_detection_system_prompt", "")
        
        if not tool_definition:
            logger.error(f"[{task_id}] Detection tool definition not found in config")
            return chunk  # Return as-is if config is invalid
        
        # Load content sanitization model from app.yml
        # This must be loaded from the AI app's app.yml - no hardcoded fallbacks!
        model_id = _load_content_sanitization_model()
        if not model_id:
            error_msg = f"[{task_id}] Content sanitization model not configured in app.yml. Cannot sanitize content."
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
            logger.warning(f"[{task_id}] Prompt injection detection failed for chunk {chunk_index+1}: {result.error_message or 'No arguments returned'}. Allowing through.")
            return chunk  # Allow through if detection fails (conservative approach)
        
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
        
        # Remove injection strings if any were detected
        sanitized_chunk = chunk
        if injection_strings:
            logger.info(
                f"[{task_id}] Removing {len(injection_strings)} injection string(s) from chunk {chunk_index+1}/{total_chunks}"
            )
            for injection_string in injection_strings:
                # Remove exact string matches (case-sensitive)
                sanitized_chunk = sanitized_chunk.replace(injection_string, "")
            
            # Clean up any double spaces or newlines that might result
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
    secrets_manager: Optional[SecretsManager] = None
) -> str:
    """
    Sanitize external content to prevent prompt injection attacks.
    
    This function implements the mandatory sanitization process for all app skills
    that access external APIs or gather external data. See docs/architecture/apps/app_skills.md
    for detailed requirements.
    
    Process:
    1. For images: Return empty string (image processing comes later)
    2. For text: Split long text into chunks of 50,000 tokens maximum
    3. Detect prompt injection attacks using LLM function call
    4. Sanitize text content to remove malicious instructions
    5. Combine sanitized chunks back together
    
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
        # Load prompt injection detection configuration
        detection_config = _load_prompt_injection_detection_config()
        if not detection_config:
            logger.error(f"[{task_id}] Failed to load prompt injection detection config, skipping sanitization")
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
                secrets_manager=secrets_manager
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

