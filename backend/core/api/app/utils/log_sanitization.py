# backend/core/api/app/utils/log_sanitization.py
# Utility functions for sanitizing sensitive data in logs.
# This ensures that even in development mode, we don't log actual message content,
# chat tags, summaries, or other sensitive user data.

from typing import Dict, Any, List, Optional


def sanitize_request_data_for_logging(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize request data for logging by replacing sensitive content with metadata.
    
    Instead of logging actual message content, chat tags, summaries, etc., 
    this function returns a sanitized version showing only:
    - Count of messages
    - Length per message (without content)
    - Count of tags
    - Length of summary (without content)
    
    Args:
        request_data: The original request data dictionary
        
    Returns:
        A sanitized dictionary suitable for logging
    """
    sanitized = request_data.copy()
    
    # Sanitize message_history: replace with metadata (count and lengths)
    if "message_history" in sanitized and isinstance(sanitized["message_history"], list):
        message_metadata = []
        for msg in sanitized["message_history"]:
            if isinstance(msg, dict):
                msg_meta = {
                    "role": msg.get("role", "unknown"),
                    "category": msg.get("category"),
                    "created_at": msg.get("created_at"),
                    "content_length": len(str(msg.get("content", ""))) if msg.get("content") else 0
                }
                message_metadata.append(msg_meta)
            else:
                # Handle Pydantic models or other objects
                msg_dict = msg if isinstance(msg, dict) else (msg.dict() if hasattr(msg, "dict") else {})
                msg_meta = {
                    "role": msg_dict.get("role", "unknown"),
                    "category": msg_dict.get("category"),
                    "created_at": msg_dict.get("created_at"),
                    "content_length": len(str(msg_dict.get("content", ""))) if msg_dict.get("content") else 0
                }
                message_metadata.append(msg_meta)
        
        sanitized["message_history"] = {
            "count": len(sanitized["message_history"]),
            "messages": message_metadata
        }
    
    # Sanitize chat_tags: replace with count only
    if "chat_tags" in sanitized:
        if isinstance(sanitized["chat_tags"], list):
            sanitized["chat_tags"] = {
                "count": len(sanitized["chat_tags"]),
                "tags": "[REDACTED_CONTENT]"  # Don't show actual tag content
            }
        else:
            sanitized["chat_tags"] = "[REDACTED]"
    
    # Sanitize chat_summary: replace with length only
    if "chat_summary" in sanitized:
        summary = sanitized["chat_summary"]
        if isinstance(summary, str):
            sanitized["chat_summary"] = {
                "length": len(summary),
                "content": "[REDACTED_CONTENT]"  # Don't show actual summary content
            }
        else:
            sanitized["chat_summary"] = "[REDACTED]"
    
    # Sanitize follow_up_request_suggestions: replace with count and lengths
    if "follow_up_request_suggestions" in sanitized:
        if isinstance(sanitized["follow_up_request_suggestions"], list):
            suggestions_metadata = [
                {"length": len(str(s))} for s in sanitized["follow_up_request_suggestions"]
            ]
            sanitized["follow_up_request_suggestions"] = {
                "count": len(sanitized["follow_up_request_suggestions"]),
                "suggestions": suggestions_metadata,
                "content": "[REDACTED_CONTENT]"  # Don't show actual suggestion content
            }
        else:
            sanitized["follow_up_request_suggestions"] = "[REDACTED]"
    
    # Sanitize new_chat_request_suggestions: replace with count and lengths
    if "new_chat_request_suggestions" in sanitized:
        if isinstance(sanitized["new_chat_request_suggestions"], list):
            suggestions_metadata = [
                {"length": len(str(s))} for s in sanitized["new_chat_request_suggestions"]
            ]
            sanitized["new_chat_request_suggestions"] = {
                "count": len(sanitized["new_chat_request_suggestions"]),
                "suggestions": suggestions_metadata,
                "content": "[REDACTED_CONTENT]"  # Don't show actual suggestion content
            }
        else:
            sanitized["new_chat_request_suggestions"] = "[REDACTED]"
    
    return sanitized


def sanitize_response_snippet_for_logging(response: str, max_length: int = 100) -> str:
    """
    Sanitize a response snippet for logging by showing only length and a placeholder.
    
    Args:
        response: The original response string
        max_length: Maximum length to show in the snippet (not used, kept for compatibility)
        
    Returns:
        A sanitized string showing only metadata
    """
    return f"[Response length: {len(response)} chars, content: REDACTED]"


def sanitize_preprocessing_result_for_logging(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize preprocessing result for logging.
    
    Args:
        result: The preprocessing result dictionary
        
    Returns:
        A sanitized dictionary suitable for logging
    """
    sanitized = result.copy()
    
    # Sanitize chat_summary if present
    if "chat_summary" in sanitized:
        summary = sanitized["chat_summary"]
        if isinstance(summary, str):
            sanitized["chat_summary"] = {"length": len(summary), "content": "[REDACTED_CONTENT]"}
        else:
            sanitized["chat_summary"] = "[REDACTED]"
    
    # Sanitize chat_tags if present
    if "chat_tags" in sanitized:
        if isinstance(sanitized["chat_tags"], list):
            sanitized["chat_tags"] = {"count": len(sanitized["chat_tags"]), "content": "[REDACTED_CONTENT]"}
        else:
            sanitized["chat_tags"] = "[REDACTED]"
    
    return sanitized

