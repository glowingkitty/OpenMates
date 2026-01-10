# backend/apps/code/skills/get_docs_skill.py
#
# Get Docs skill implementation.
# Fetches up-to-date documentation for libraries/frameworks using Context7 API
# with intelligent library selection via LLM.
#
# Flow:
# 1. If library looks like ID (e.g., "/sveltejs/svelte"), try direct fetch first
# 2. If not ID or direct fetch fails: Context7 search (library → results)
# 3. LLM selection (results + question → library_id) - only if >1 result
# 4. Context7 docs (library_id + question → documentation)
# 5. ASCII smuggling protection (no LLM sanitization - Context7 is trusted)
#
# PERFORMANCE NOTES (measured via test_context7_api.py):
# - Context7 search returns max 5 libraries (~50ms)
# - LLM library selection: ~400-500 input tokens, ~100ms with fast models
# - Context7 /context API: varies by library, typically 1-3k tokens (~200ms)
# - Total typical latency: 300-500ms (dominated by API calls, not LLM)
#
# CONTEXT7 API BEHAVIOR:
# - /libs/search returns max 5 library matches (not configurable)
# - /context returns ONE markdown document with relevant snippets (not multiple)
#
# See docs/architecture/apps/code.md for full specification.

import logging
import os
import json
import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from celery import Celery

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
# Note: LLM-based sanitize_external_content is NOT used for Context7 docs (trusted source)
# We only use ASCII smuggling protection which is imported inline where needed

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================

class GetDocsRequest(BaseModel):
    """
    Request model for get_docs skill.
    
    This model defines the parameters for fetching library documentation.
    Used by FastAPI to generate correct OpenAPI schema for the API docs.
    """
    library: str = Field(
        ...,
        description="Library name to search for (e.g., 'svelte', 'react', 'fastapi')."
    )
    question: str = Field(
        ...,
        description="Natural language question about the documentation needed (e.g., 'How to use useState hook?', 'How to setup routing?')."
    )


class GetDocsResponse(BaseModel):
    """Response model for get_docs skill."""
    library: Optional[Dict[str, Any]] = Field(
        None,
        description="Selected library info (id, title, description)"
    )
    documentation: Optional[str] = Field(
        None,
        description="Retrieved documentation content (markdown)"
    )
    word_count: int = Field(
        default=0,
        description="Word count of the documentation content"
    )
    source: str = Field(
        default="context7",
        description="Source of documentation (context7, openmates, web_search)"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if retrieval failed"
    )


def _calculate_word_count(text: Optional[str]) -> int:
    """
    Calculate word count from text.
    
    Uses simple whitespace splitting to count words.
    This is the same algorithm used by word processors.
    
    Args:
        text: The text to count words in
        
    Returns:
        Number of words in the text
    """
    if not text:
        return 0
    # Split on whitespace and filter empty strings
    words = text.strip().split()
    return len(words)


# =============================================================================
# Context7 API Client (inline for simplicity)
# =============================================================================

class Context7Client:
    """
    Minimal Context7 API client for the get_docs skill.
    Based on official API: https://context7.com/docs/api-guide
    """
    
    BASE_URL = "https://context7.com/api/v2"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "OpenMates-GetDocs/1.0"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    async def search_libraries(
        self,
        library_name: str,
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for libraries by name.
        
        API: GET /api/v2/libs/search
        """
        import aiohttp
        
        params = {"libraryName": library_name}
        if query:
            params["query"] = query
        
        url = f"{self.BASE_URL}/libs/search"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("results", [])
                elif response.status == 429:
                    logger.warning("Context7 rate limit hit")
                    return []
                else:
                    logger.error(f"Context7 search failed: {response.status}")
                    return []
    
    async def get_context(
        self,
        library_id: str,
        query: str
    ) -> Optional[str]:
        """
        Get documentation context for a library.
        
        API: GET /api/v2/context
        """
        import aiohttp
        
        params = {
            "libraryId": library_id,
            "query": query
        }
        
        url = f"{self.BASE_URL}/context"
        
        logger.info(f"Context7 get_context: library_id={library_id}, query={query[:50]}..., url={url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                # Log response status and headers for debugging
                content_type = response.headers.get("Content-Type", "")
                logger.info(f"Context7 get_context response: status={response.status}, content_type={content_type}, url={response.url}")
                
                # Read response body - always read as text first, then parse if needed
                # This ensures we can always log the raw response for debugging
                response_text = None
                response_body = None
                try:
                    response_text = await response.text()
                    logger.info(f"Context7 get_context: Response text length={len(response_text) if response_text else 0}")
                    
                    # Try to parse as JSON if content type indicates JSON or if text looks like JSON
                    if "application/json" in content_type or (response_text and (response_text.strip().startswith("{") or response_text.strip().startswith("["))):
                        try:
                            response_body = json.loads(response_text)
                            logger.debug(f"Context7 get_context: Parsed response as JSON, type={type(response_body)}")
                        except json.JSONDecodeError as json_err:
                            # Not valid JSON, use as text
                            logger.debug(f"Context7 get_context: Failed to parse as JSON (using as text): {json_err}")
                            response_body = response_text
                    else:
                        # Use as text
                        response_body = response_text
                        
                except Exception as e:
                    logger.error(f"Context7 get_context: Failed to read response body: {e}", exc_info=True)
                    return None
                
                if response.status == 200:
                    # API returns text/markdown or JSON
                    content = None
                    
                    if isinstance(response_body, str):
                        content = response_body.strip() if response_body else None
                    elif isinstance(response_body, dict):
                        # Try common response fields (in order of preference)
                        content = (
                            response_body.get("content") or
                            response_body.get("context") or
                            response_body.get("data") or
                            response_body.get("documentation") or
                            response_body.get("text") or
                            None
                        )
                        # If we found content, ensure it's a string and not empty
                        if content is not None:
                            if isinstance(content, str):
                                content = content.strip()
                                # Convert empty string to None
                                if len(content) == 0:
                                    content = None
                            else:
                                # If it's not a string, try to convert
                                content_str = str(content).strip()
                                # If the string representation is just braces or empty, it's useless
                                if content_str in ["{}", "[]", ""] or len(content_str) < 10:
                                    content = None
                                else:
                                    content = content_str
                        # If no content found in dict, log what we got
                        if content is None:
                            logger.debug(
                                f"Context7 get_context: No content in dict response for library_id={library_id}, "
                                f"dict_keys={list(response_body.keys())}, dict_preview={str(response_body)[:300]}"
                            )
                    elif response_body is not None:
                        # Try to convert to string for other types (list, etc.)
                        content_str = str(response_body).strip()
                        # If it's just braces/brackets, it's useless
                        if content_str not in ["{}", "[]", "None", ""] and len(content_str) >= 10:
                            content = content_str
                    
                    # Final check: if content is empty or None, log and return None
                    if not content or len(content.strip()) == 0:
                        logger.warning(
                            f"Context7 get_context: Received empty or invalid content for library_id={library_id}, "
                            f"query={query[:50]}..., response_status={response.status}, "
                            f"response_body_type={type(response_body)}, "
                            f"response_body_keys={list(response_body.keys()) if isinstance(response_body, dict) else 'N/A'}, "
                            f"response_body_preview={str(response_body)[:500] if response_body else 'None'}"
                        )
                        return None
                    
                    logger.info(f"Context7 get_context: Retrieved {len(content)} chars for library_id={library_id}")
                    return content
                    
                elif response.status == 404:
                    logger.warning(
                        f"Context7 library not found: library_id={library_id}, "
                        f"query={query[:50]}..., response_body={str(response_body)[:500] if response_body else 'None'}"
                    )
                    return None
                elif response.status == 401:
                    logger.error(
                        f"Context7 authentication failed: library_id={library_id}, "
                        f"query={query[:50]}..., response_body={str(response_body)[:500] if response_body else 'None'}. "
                        f"Check if API key is valid and has access to this library."
                    )
                    return None
                elif response.status == 429:
                    logger.warning(
                        f"Context7 rate limit exceeded: library_id={library_id}, "
                        f"query={query[:50]}..., response_body={str(response_body)[:500] if response_body else 'None'}"
                    )
                    return None
                else:
                    logger.error(
                        f"Context7 get_context failed: status={response.status}, "
                        f"library_id={library_id}, query={query[:50]}..., "
                        f"response_body={str(response_body)[:1000] if response_body else 'None'}"
                    )
                    return None


# =============================================================================
# LLM Library Selection
# =============================================================================

# System prompt for library selection (simple classification task)
# IMPORTANT: Keep this prompt simple and direct - when tool_choice="required", the model MUST call the function
# Complex prompts with multiple instructions can confuse models into trying to generate text instead
LIBRARY_SELECTION_SYSTEM_PROMPT = """Select the most relevant library from the provided options.

Match the library to the user's question based on:
1. Library name/title similarity
2. Description relevance  
3. Higher benchmark scores are preferred

You MUST call the select_library function with one library_id from the provided options."""

# Function calling tool definition for all providers (Groq, Cerebras, Mistral)
# All providers use OpenAI-compatible function calling
LIBRARY_SELECTION_TOOL = {
    "type": "function",
    "function": {
        "name": "select_library",
        "description": "Select the most relevant library ID from the search results",
        "parameters": {
            "type": "object",
            "properties": {
                "library_id": {
                    "type": "string",
                    "description": "The selected library ID (e.g. '/sveltejs/svelte')"
                }
            },
            "required": ["library_id"]
        }
    }
}


async def select_library_with_llm(
    libraries: List[Dict[str, Any]],
    question: str,
    secrets_manager: SecretsManager
) -> Optional[str]:
    """
    Use LLM to select the best library from search results.
    
    All providers use function calling (tool use) for reliable structured responses.
    Groq, Cerebras, and Mistral all support OpenAI-compatible function calling.
    
    Fallback chain:
    1. Primary: openai/gpt-oss-20b via Groq (with function calling)
    2. Fallback 1: gpt-oss-120b via Cerebras (with function calling)
    3. Fallback 2: mistral-small-latest via Mistral (with function calling)
    4. Fallback 3: First search result (no LLM)
    
    Returns the selected library_id or None if selection fails.
    """
    if not libraries:
        return None
    
    # If only one result, skip LLM selection
    if len(libraries) == 1:
        return libraries[0].get("id")
    
    # Prepare library options for LLM (minimal data to reduce injection risk)
    # Truncate descriptions to 100 chars max
    library_options = []
    valid_ids = set()
    for lib in libraries[:10]:  # Max 10 options
        lib_id = lib.get("id", "")
        valid_ids.add(lib_id)
        library_options.append({
            "id": lib_id,
            "title": lib.get("title", "")[:50],
            "description": (lib.get("description") or "")[:100],
            "benchmark": lib.get("benchmarkScore", 0)
        })
    
    task_id = f"lib_select_{int(time.time())}"
    
    # Build messages for all providers (all use function calling)
    # IMPORTANT: Keep user message concise - verbose instructions can cause models to generate text instead of calling function
    # With tool_choice="required", the model MUST call the function, so we keep the prompt minimal
    messages = [
        {"role": "system", "content": LIBRARY_SELECTION_SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {question}\n\nLibraries:\n{json.dumps(library_options, indent=2)}\n\nSelect the best matching library."}
    ]
    
    # Tool definition for function calling (used by all providers)
    tools = [LIBRARY_SELECTION_TOOL]
    
    # Import LLM clients
    from backend.apps.ai.llm_providers.groq_client import invoke_groq_chat_completions
    from backend.apps.ai.llm_providers.cerebras_wrapper import invoke_cerebras_chat_completions
    from backend.apps.ai.llm_providers.mistral_client import invoke_mistral_chat_completions
    
    # Try Groq gpt-oss-20b with function calling (primary)
    # Use tool_choice="required" since we have exactly one tool - this ensures the function is always called
    try:
        logger.info(f"[{task_id}] Trying Groq openai/gpt-oss-20b with function calling (required)")
        result = await invoke_groq_chat_completions(
            task_id=task_id,
            model_id="openai/gpt-oss-20b",
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0,
            max_tokens=500,  # Increased from 100 - function calls need more tokens, even with tool_choice="required"
            tools=tools,
            tool_choice="required"  # Force function calling - more reliable with single tool
        )
        
        selected_id = _extract_library_id_from_response(result, valid_ids, task_id, "Groq")
        if selected_id:
            logger.info(f"[{task_id}] Library selected via Groq: {selected_id}")
            return selected_id
        else:
            logger.warning(f"[{task_id}] Groq returned no valid library_id. Response: success={result.success}, tool_calls={len(result.tool_calls_made) if result.tool_calls_made else 0}, error={result.error_message if not result.success else None}")
            
    except Exception as e:
        logger.warning(f"[{task_id}] Groq selection failed: {e}", exc_info=True)
    
    # Try Cerebras gpt-oss-120b with function calling (fallback 1)
    try:
        logger.info(f"[{task_id}] Trying Cerebras gpt-oss-120b with function calling (required)")
        result = await invoke_cerebras_chat_completions(
            task_id=task_id,
            model_id="gpt-oss-120b",
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0,
            max_tokens=500,  # Increased from 100 - function calls need more tokens
            tools=tools,
            tool_choice="required"  # Force function calling - more reliable with single tool
        )
        
        selected_id = _extract_library_id_from_response(result, valid_ids, task_id, "Cerebras")
        if selected_id:
            logger.info(f"[{task_id}] Library selected via Cerebras: {selected_id}")
            return selected_id
        else:
            logger.warning(f"[{task_id}] Cerebras returned no valid library_id. Response: success={result.success}, tool_calls={len(result.tool_calls_made) if result.tool_calls_made else 0}, error={result.error_message if not result.success else None}")
            
    except Exception as e:
        logger.warning(f"[{task_id}] Cerebras selection failed: {e}", exc_info=True)
    
    # Try Mistral mistral-small-latest with function calling (fallback 2)
    try:
        logger.info(f"[{task_id}] Trying Mistral mistral-small-latest with function calling (required)")
        result = await invoke_mistral_chat_completions(
            task_id=task_id,
            model_id="mistral-small-latest",
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0,
            max_tokens=500,  # Increased from 100 - function calls need more tokens
            tools=tools,
            tool_choice="required"  # Force function calling - more reliable with single tool
        )
        
        selected_id = _extract_library_id_from_response(result, valid_ids, task_id, "Mistral")
        if selected_id:
            logger.info(f"[{task_id}] Library selected via Mistral: {selected_id}")
            return selected_id
        else:
            logger.warning(f"[{task_id}] Mistral returned no valid library_id. Response: success={result.success}, tool_calls={len(result.tool_calls_made) if result.tool_calls_made else 0}, error={result.error_message if not result.success else None}")
            
    except Exception as e:
        logger.warning(f"[{task_id}] Mistral selection failed: {e}", exc_info=True)
    
    # All providers failed - return first result as fallback
    logger.warning(f"[{task_id}] All LLM providers failed, using first search result as fallback")
    return libraries[0].get("id") if libraries else None


def _extract_library_id_from_response(result, valid_ids: set, task_id: str = "", provider: str = "") -> Optional[str]:
    """
    Extract library_id from LLM response.
    
    Handles function calling (tool use) responses from all providers:
    1. Tool calls (function calling) - primary method for all providers
    2. Plain text with library ID pattern - fallback
    
    All providers (Groq, Cerebras, Mistral) use OpenAI-compatible function calling,
    so tool_calls_made should contain the parsed function call.
    
    Args:
        result: UnifiedOpenAIResponse from LLM call
        valid_ids: Set of valid library IDs to choose from
        task_id: Task ID for logging context
        provider: Provider name for logging context
    
    Returns:
        Selected library_id or None if extraction failed
    """
    import re
    
    log_prefix = f"[{task_id}][{provider}]" if task_id and provider else ""
    
    # Check if response was successful
    if not result.success:
        logger.warning(f"{log_prefix} LLM response unsuccessful: {result.error_message}")
        return None
    
    # Extract from tool calls (function calling) - primary method
    # All providers (Groq, Cerebras, Mistral) use OpenAI-compatible format
    if result.tool_calls_made:
        for tool_call in result.tool_calls_made:
            if tool_call.function_name == "select_library":
                # Try function_arguments_parsed first (OpenAI/Groq/Cerebras format)
                args = getattr(tool_call, 'function_arguments_parsed', None)
                # Fallback to function_arguments if it exists (some formats)
                if args is None:
                    args = getattr(tool_call, 'function_arguments', None)
                
                # Check for parsing errors
                if hasattr(tool_call, 'parsing_error') and tool_call.parsing_error:
                    logger.warning(f"{log_prefix} JSON parsing error in tool call: {tool_call.parsing_error}")
                    # Try to extract from raw arguments string as fallback
                    if hasattr(tool_call, 'function_arguments_raw'):
                        try:
                            args = json.loads(tool_call.function_arguments_raw)
                        except json.JSONDecodeError:
                            pass
                
                if isinstance(args, dict):
                    lib_id = args.get("library_id")
                    if lib_id and lib_id in valid_ids:
                        logger.debug(f"{log_prefix} Extracted library_id from tool call: {lib_id}")
                        return lib_id
                    elif lib_id:
                        logger.warning(f"{log_prefix} LLM returned invalid ID '{lib_id}', not in valid set. Valid IDs: {list(valid_ids)[:5]}...")
                    else:
                        logger.warning(f"{log_prefix} Tool call missing 'library_id' parameter. Args: {args}")
                else:
                    logger.warning(f"{log_prefix} Tool call arguments not a dict. Type: {type(args)}, Value: {args}")
            else:
                logger.warning(f"{log_prefix} Unexpected function name in tool call: {tool_call.function_name} (expected 'select_library')")
    else:
        logger.warning(f"{log_prefix} No tool calls in response (tool_choice='required' should have forced a tool call)")
    
    # Fallback: Try to extract from direct_message_content (shouldn't happen with tool use + tool_choice="required")
    content = result.direct_message_content or ""
    if content:
        logger.debug(f"{log_prefix} No tool calls found, trying to extract from message content (length: {len(content)})")
        # Try to parse as JSON first (in case model returns JSON instead of tool call)
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                lib_id = parsed.get("library_id")
                if lib_id and lib_id in valid_ids:
                    logger.debug(f"{log_prefix} Extracted library_id from JSON content: {lib_id}")
                    return lib_id
                elif lib_id:
                    logger.warning(f"{log_prefix} JSON library_id '{lib_id}' not in valid set: {list(valid_ids)[:5]}...")
        except json.JSONDecodeError:
            # Not JSON, try regex extraction
            pass
        
        # Fallback: Look for library ID pattern in text (e.g., /sveltejs/svelte)
        match = re.search(r'(/[\w-]+/[\w.-]+)', content)
        if match:
            lib_id = match.group(1)
            if lib_id in valid_ids:
                logger.debug(f"{log_prefix} Extracted library_id from text pattern: {lib_id}")
                return lib_id
            else:
                logger.warning(f"{log_prefix} Extracted ID '{lib_id}' not in valid set: {list(valid_ids)[:5]}...")
    
    return None


# =============================================================================
# Main Skill Class
# =============================================================================

class GetDocsSkill(BaseSkill):
    """
    Get Docs skill that fetches library documentation using Context7 API.
    
    This skill:
    1. Searches Context7 for matching libraries
    2. Uses LLM to select the best library match
    3. Retrieves documentation context
    4. Sanitizes output for prompt injection protection
    
    ARCHITECTURE: Direct async execution (not Celery)
    - Fast operation (~2-5 seconds total)
    - I/O-bound (network calls)
    - Non-blocking async/await
    """
    
    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer: Optional[Celery] = None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer
        )
        
        self.context7_client: Optional[Context7Client] = None
    
    async def _get_context7_client(self, secrets_manager: SecretsManager) -> Context7Client:
        """Get or create Context7 client with API key."""
        if self.context7_client is None:
            # Context7 API key from Vault
            api_key = await secrets_manager.get_secret(
                secret_path="kv/data/providers/context7",
                secret_key="api_key"
            )
            self.context7_client = Context7Client(api_key=api_key)
        return self.context7_client
    
    async def execute(
        self,
        library: str,
        question: str,
        secrets_manager: Optional[SecretsManager] = None
    ) -> GetDocsResponse:
        """
        Execute get_docs skill.
        
        Args:
            library: Library name to search for (e.g., "svelte", "react")
            question: Natural language question about documentation needed
            secrets_manager: SecretsManager instance
        
        Returns:
            GetDocsResponse with documentation or error
        """
        # Validate inputs
        if not library or not library.strip():
            return GetDocsResponse(error="Missing 'library' parameter")
        if not question or not question.strip():
            return GetDocsResponse(error="Missing 'question' parameter")
        
        library = library.strip()
        question = question.strip()
        
        # Get or create SecretsManager using BaseSkill helper method
        # This properly initializes the SecretsManager with Vault token
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="GetDocsSkill",
            error_response_factory=lambda msg: GetDocsResponse(error=msg),
            logger=logger
        )
        if error_response:
            return error_response
        
        task_id = f"get_docs_{library}_{int(time.time())}"
        logger.info(f"[{task_id}] Starting get_docs: library='{library}', question='{question[:50]}...'")
        
        # Timing measurements for performance analysis
        timing = {"start": time.time()}
        
        try:
            # Special case: OpenMates API documentation
            if library.lower() in ["openmates", "openmates api", "openmates-api"]:
                return await self._get_openmates_docs(question)
            
            client = await self._get_context7_client(secrets_manager)
            selected_id = None
            selected_lib = None
            
            # OPTIMIZATION: If library looks like a Context7 ID (e.g., "/sveltejs/svelte"),
            # try direct fetch first to skip search + LLM selection entirely.
            # This saves ~200-300ms when the user provides an exact library ID.
            if library.startswith("/") and library.count("/") >= 2:
                logger.info(f"[{task_id}] Library looks like ID, trying direct fetch: {library}")
                timing["direct_fetch_start"] = time.time()
                
                # Try to get docs directly with the provided ID
                documentation = await client.get_context(library, question)
                timing["direct_fetch_end"] = time.time()
                timing["direct_fetch_ms"] = int((timing["direct_fetch_end"] - timing["direct_fetch_start"]) * 1000)
                
                if documentation:
                    logger.info(f"[{task_id}][PERF] Direct fetch succeeded in {timing['direct_fetch_ms']}ms")
                    selected_id = library
                    
                    # Do a quick search to get library metadata (title, description)
                    # This adds ~50ms but ensures we have complete metadata
                    timing["metadata_search_start"] = time.time()
                    # Extract library name from ID for search (e.g., "/stripe/stripe-js" -> "stripe-js")
                    lib_name_for_search = library.split("/")[-1]
                    metadata_results = await client.search_libraries(lib_name_for_search)
                    timing["metadata_search_end"] = time.time()
                    timing["metadata_search_ms"] = int((timing["metadata_search_end"] - timing["metadata_search_start"]) * 1000)
                    
                    # Find matching library in search results for full metadata
                    selected_lib = next(
                        (lib for lib in metadata_results if lib.get("id") == library),
                        {"id": library, "title": lib_name_for_search}  # Fallback if not found
                    )
                    logger.info(f"[{task_id}][PERF] Metadata search completed in {timing['metadata_search_ms']}ms, found description: {bool(selected_lib.get('description'))}")
                    # Skip to documentation processing (after the search/select block)
                else:
                    logger.info(f"[{task_id}] Direct fetch failed, falling back to search")
            
            # If we don't have docs yet (either not an ID, or direct fetch failed), do search
            if selected_id is None:
                # Step 1: Search Context7 for libraries
                timing["search_start"] = time.time()
                logger.info(f"[{task_id}] Searching Context7 for '{library}'...")
                libraries = await client.search_libraries(library, query=question)
                timing["search_end"] = time.time()
                timing["search_ms"] = int((timing["search_end"] - timing["search_start"]) * 1000)
                
                if not libraries:
                    logger.warning(f"[{task_id}] No libraries found for '{library}'")
                    return GetDocsResponse(
                        error=f"No documentation found for '{library}'. Try a different library name.",
                        source="context7"
                    )
                
                logger.info(f"[{task_id}][PERF] Search returned {len(libraries)} libraries in {timing['search_ms']}ms")
                
                # Step 2: Select best library using LLM (only if multiple results)
                timing["llm_start"] = time.time()
                logger.info(f"[{task_id}] Selecting best library with LLM...")
                selected_id = await select_library_with_llm(
                    libraries=libraries,
                    question=question,
                    secrets_manager=secrets_manager
                )
                timing["llm_end"] = time.time()
                timing["llm_ms"] = int((timing["llm_end"] - timing["llm_start"]) * 1000)
                
                if not selected_id:
                    return GetDocsResponse(
                        error="Failed to select library from search results",
                        source="context7"
                    )
                
                # Find selected library info
                selected_lib = next(
                    (lib for lib in libraries if lib.get("id") == selected_id),
                    {"id": selected_id, "title": library}
                )
                
                logger.info(f"[{task_id}][PERF] LLM selection chose '{selected_id}' in {timing['llm_ms']}ms")
                
                # Step 3: Get documentation from Context7
                timing["docs_start"] = time.time()
                logger.info(f"[{task_id}] Fetching documentation...")
                documentation = await client.get_context(selected_id, question)
                timing["docs_end"] = time.time()
                timing["docs_ms"] = int((timing["docs_end"] - timing["docs_start"]) * 1000)
                logger.info(f"[{task_id}][PERF] Documentation fetch completed in {timing['docs_ms']}ms")
            
            if not documentation:
                return GetDocsResponse(
                    library={
                        "id": selected_id,
                        "title": selected_lib.get("title", ""),
                        "description": selected_lib.get("description", "")
                    },
                    error=f"No documentation content found for '{selected_id}'",
                    source="context7"
                )
            
            # ARCHITECTURE DECISION: Skip LLM-based sanitization for Context7 documentation
            # ================================================================================
            # Context7 is a TRUSTED SOURCE - it provides curated, official library documentation
            # from GitHub repos and official docs sites. This is NOT user-generated content.
            # 
            # Reasons to skip LLM sanitization:
            # 1. Context7 documentation is curated from official sources (GitHub, official docs)
            # 2. LLM-based sanitization adds latency (~1-2 seconds) and cost
            # 3. The Groq safeguard model has reliability issues with function calling
            # 4. Documentation from official sources is extremely unlikely to contain prompt injection
            # 5. ASCII smuggling protection (Layer 1) still runs to remove invisible characters
            #
            # We still apply ASCII smuggling protection (character-level sanitization) as a
            # lightweight security measure that doesn't require LLM calls.
            # ================================================================================
            
            logger.info(f"[{task_id}] Applying ASCII smuggling protection to documentation ({len(documentation)} chars)...")
            
            # Import ASCII smuggling sanitization for character-level protection
            from backend.core.api.app.utils.text_sanitization import sanitize_text_for_ascii_smuggling
            
            # Apply ASCII smuggling protection (removes invisible Unicode characters)
            # This is a fast, deterministic operation that doesn't require LLM calls
            ascii_smuggling_log_prefix = f"[{task_id}][CONTEXT7] "
            sanitized_docs, ascii_stats = sanitize_text_for_ascii_smuggling(
                documentation,
                log_prefix=ascii_smuggling_log_prefix,
                include_stats=True
            )
            
            # Log security alert if hidden content was detected
            if ascii_stats.get("hidden_ascii_detected"):
                logger.warning(
                    f"[{task_id}][SECURITY ALERT] ASCII smuggling detected in Context7 documentation! "
                    f"Hidden Unicode Tags content found and removed. "
                    f"Removed {ascii_stats['removed_count']} invisible characters."
                )
            elif ascii_stats.get("removed_count", 0) > 0:
                logger.info(
                    f"[{task_id}][ASCII SANITIZATION] Removed {ascii_stats['removed_count']} "
                    f"invisible characters from Context7 documentation"
                )
            
            # If content became empty after ASCII sanitization, it was likely all hidden chars
            if not sanitized_docs.strip():
                logger.warning(
                    f"[{task_id}] Context7 documentation became empty after ASCII smuggling removal. "
                    f"Original may have been entirely hidden characters (attack attempt)."
                )
                return GetDocsResponse(
                    library={
                        "id": selected_id,
                        "title": selected_lib.get("title", ""),
                        "description": selected_lib.get("description", "")
                    },
                    error="Documentation content was invalid (contained only invisible characters)",
                    source="context7"
                )
            
            # Log total timing breakdown
            timing["total_ms"] = int((time.time() - timing["start"]) * 1000)
            timing_summary = f"total={timing['total_ms']}ms"
            if "direct_fetch_ms" in timing:
                timing_summary += f", direct_fetch={timing['direct_fetch_ms']}ms"
            if "metadata_search_ms" in timing:
                timing_summary += f", metadata_search={timing['metadata_search_ms']}ms"
            if "search_ms" in timing:
                timing_summary += f", search={timing['search_ms']}ms"
            if "llm_ms" in timing:
                timing_summary += f", llm_select={timing['llm_ms']}ms"
            if "docs_ms" in timing:
                timing_summary += f", docs_fetch={timing['docs_ms']}ms"
            
            # Calculate word count for the documentation
            doc_word_count = _calculate_word_count(sanitized_docs)
            
            logger.info(f"[{task_id}][PERF] Success: {len(sanitized_docs)} chars, {doc_word_count} words | {timing_summary}")
            
            return GetDocsResponse(
                library={
                    "id": selected_id,
                    "title": selected_lib.get("title", ""),
                    "description": selected_lib.get("description", "")
                },
                documentation=sanitized_docs,
                word_count=doc_word_count,
                source="context7"
            )
            
        except Exception as e:
            logger.error(f"[{task_id}] Error: {e}", exc_info=True)
            return GetDocsResponse(error=f"Failed to get documentation: {str(e)}")
    
    async def _get_openmates_docs(self, question: str) -> GetDocsResponse:
        """
        Get OpenMates API documentation directly from local files.
        Bypasses Context7 for internal API documentation.
        """
        try:
            # Try to read openapi.json
            openapi_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "docs", "openapi.json"
            )
            
            if os.path.exists(openapi_path):
                with open(openapi_path, 'r', encoding='utf-8') as f:
                    openapi_spec = json.load(f)
                
                # Return relevant portion based on question
                # For now, return the full spec (could be optimized)
                docs_content = json.dumps(openapi_spec, indent=2)
                return GetDocsResponse(
                    library={
                        "id": "openmates",
                        "title": "OpenMates API",
                        "description": "OpenMates internal API documentation"
                    },
                    documentation=docs_content,
                    word_count=_calculate_word_count(docs_content),
                    source="openmates"
                )
            else:
                return GetDocsResponse(
                    error="OpenMates API documentation not found",
                    source="openmates"
                )
                
        except Exception as e:
            logger.error(f"Error reading OpenMates docs: {e}")
            return GetDocsResponse(
                error=f"Failed to read OpenMates documentation: {str(e)}",
                source="openmates"
            )
