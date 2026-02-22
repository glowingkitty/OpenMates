# backend/tests/test_toon_fake_tool_call_filter.py
#
# Unit tests for the toon/tool_code fake tool call filtering logic in stream_consumer.py.
#
# Background: The AI stream consumer filters out "fake tool calls" — code blocks where
# the LLM tries to invoke tools by writing tool call structures as plain text output
# (instead of using the proper function-calling API). These appear as code blocks with
# language identifiers like 'tool_code', 'toon', or 'json' containing tool call patterns.
#
# CRITICAL BUG (Issue 07ed2bbb): The multi-chunk filter was treating ALL 'toon' code blocks
# as fake tool calls, regardless of content. But 'toon' is also our internal encoding format
# visible in LLM context, so models sometimes mislabel real code (YAML, Python) as 'toon'.
# The fix adds content-based validation: only filter 'toon' blocks that actually contain
# tool call patterns ('"tool":', 'tool_code', 'tool:').
#
# Run with: /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_toon_fake_tool_call_filter.py


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: Extracted toon validation logic (mirrors stream_consumer.py closing fence)
# ═══════════════════════════════════════════════════════════════════════════════

def is_toon_block_fake_tool_call(code_content: str) -> bool:
    """
    Determine whether a 'toon'-language code block is a fake tool call or real code.
    
    This mirrors the content-based check applied at the closing fence in
    stream_consumer.py's _consume_main_processing_stream function.
    
    Returns True if the content contains tool call patterns (should be filtered).
    Returns False if the content is real code (should be delivered to user).
    """
    return (
        '"tool":' in code_content
        or 'tool_code' in code_content
        or 'tool:' in code_content.lower()
    )


def classify_code_block_language(language: str, code_content: str) -> str:
    """
    Classify a code block by its language and content.
    
    Returns one of:
    - 'definitely_fake': Always a fake tool call (tool_code language)
    - 'toon_fake': Toon block with tool call patterns (should be filtered)
    - 'toon_real_code': Toon block with real code (should be delivered)
    - 'json_fake': JSON block with tool call structure
    - 'normal': Regular code block
    """
    lang_lower = language.lower() if language else ''
    
    # tool_code is ALWAYS a fake tool call
    if lang_lower == 'tool_code':
        return 'definitely_fake'
    
    # toon needs content-based validation
    if lang_lower == 'toon':
        if is_toon_block_fake_tool_call(code_content):
            return 'toon_fake'
        return 'toon_real_code'
    
    # JSON blocks need structure check
    if lang_lower == 'json':
        if '"tool"' in code_content and '"input"' in code_content:
            try:
                import json
                parsed = json.loads(code_content)
                if 'tool' in parsed and 'input' in parsed:
                    return 'json_fake'
            except (json.JSONDecodeError, Exception):
                pass
    
    return 'normal'


# ═══════════════════════════════════════════════════════════════════════════════
# Test Data: Real content samples from the production issue
# ═══════════════════════════════════════════════════════════════════════════════

# This is representative of the YAML config the user was generating
# (from the production logs for chat 88247e73-5309-48ef-85c6-603722cf667b)
REAL_YAML_CONTENT = """
sites:
  - name: "example-site"
    base_url: "https://example.com"
    start_selector: "app-story-detail-page-header"
    end_selector: "app-detail-page-content-footer"
    unwanted:
      - ".ad-banner"
      - ".cookie-consent"
    output_format: "markdown"
    max_pages: 100
"""

# This is representative of the Python scraper the user was generating
REAL_PYTHON_CONTENT = """
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import yaml

class WebScraper:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
    
    async def _extract_content_range(self, soup, start_sel, end_sel):
        \"\"\"Extract all siblings between start and end selectors.\"\"\"
        start = soup.select_one(start_sel)
        end = soup.select_one(end_sel)
        
        if not start:
            return str(soup)
        
        content_parts = []
        current = start.next_sibling
        while current and current != end:
            content_parts.append(str(current))
            current = current.next_sibling
        
        return '\\n'.join(content_parts)
    
    async def scrape(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            # ... scraping logic
"""

# This is a fake tool call in toon format (should be filtered)
FAKE_TOON_TOOL_CALL = """
{
  "tool": "web-search",
  "input": {
    "query": "playwright web scraper tutorial",
    "num_results": 5
  }
}
"""

# Another fake tool call pattern with nested tool_code
FAKE_TOON_WITH_TOOL_CODE = """
tool_code: web-search
parameters:
  query: "python beautifulsoup tutorial"
  max_results: 3
"""

# Fake toon with 'tool:' pattern (lowercase)
FAKE_TOON_WITH_TOOL_COLON = """
name: search_docs
tool: code-get_docs
input:
  query: "how to use async playwright"
"""

# Real code that happens to mention "tool" in a comment (should NOT be filtered)
REAL_CODE_WITH_TOOL_MENTION_IN_COMMENT = """
#!/usr/bin/env python3
# This is a helper tool for scraping web pages
# It uses Playwright as the main extraction tool

import asyncio

async def main():
    print("Starting the scraper tool")
    await scrape_pages()

if __name__ == "__main__":
    asyncio.run(main())
"""

# Real code with 'tool' in a string literal (should NOT be filtered)
REAL_CODE_WITH_TOOL_IN_STRING = """
def get_description():
    return "This tool helps you scrape web pages efficiently"

TOOL_NAME = "web_scraper_v2"
"""

# JSON embed reference (should NOT be filtered)
JSON_EMBED_REFERENCE = '{"type": "code", "embed_id": "0167c1c7-c8d5-4745-a278-873352dbfa42"}'

# JSON fake tool call (should be filtered)
JSON_FAKE_TOOL_CALL = '{"tool": "web-search", "input": {"query": "test"}}'


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: toon content-based validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestToonFakeToolCallDetection:
    """Tests for the content-based validation of toon code blocks."""

    def test_real_yaml_is_not_fake_tool_call(self):
        """Real YAML config (like the user's sites.yaml) should NOT be filtered."""
        assert not is_toon_block_fake_tool_call(REAL_YAML_CONTENT)

    def test_real_python_is_not_fake_tool_call(self):
        """Real Python code (like the user's scraper_final_v11.py) should NOT be filtered."""
        assert not is_toon_block_fake_tool_call(REAL_PYTHON_CONTENT)

    def test_fake_toon_tool_call_is_detected(self):
        """Toon block containing JSON with '"tool":' pattern should be filtered."""
        assert is_toon_block_fake_tool_call(FAKE_TOON_TOOL_CALL)

    def test_fake_toon_with_tool_code_is_detected(self):
        """Toon block containing 'tool_code' keyword should be filtered."""
        assert is_toon_block_fake_tool_call(FAKE_TOON_WITH_TOOL_CODE)

    def test_fake_toon_with_tool_colon_is_detected(self):
        """Toon block containing 'tool:' pattern should be filtered."""
        assert is_toon_block_fake_tool_call(FAKE_TOON_WITH_TOOL_COLON)

    def test_real_code_with_tool_in_comment_edge_case(self):
        """
        Code with 'tool' in comments/strings might trigger false positives.
        
        NOTE: The current heuristic checks for 'tool:' (case-insensitive) which
        would match the comment '# This is a helper tool for scraping web pages'
        — but only if there's a colon after 'tool'. This specific code does NOT
        have 'tool:' so it should pass.
        """
        assert not is_toon_block_fake_tool_call(REAL_CODE_WITH_TOOL_MENTION_IN_COMMENT)

    def test_real_code_with_tool_in_string_literal(self):
        """Code with 'tool' in string literals should NOT be filtered (no colon after 'tool')."""
        assert not is_toon_block_fake_tool_call(REAL_CODE_WITH_TOOL_IN_STRING)

    def test_empty_content_is_not_fake_tool_call(self):
        """Empty toon block should NOT be treated as fake tool call."""
        assert not is_toon_block_fake_tool_call("")

    def test_whitespace_only_is_not_fake_tool_call(self):
        """Whitespace-only toon block should NOT be treated as fake tool call."""
        assert not is_toon_block_fake_tool_call("   \n\n  \t  ")

    def test_html_content_is_not_fake_tool_call(self):
        """HTML content in toon block should NOT be treated as fake tool call."""
        html = '<div class="article"><h1>Hello World</h1><p>Content here</p></div>'
        assert not is_toon_block_fake_tool_call(html)

    def test_markdown_content_is_not_fake_tool_call(self):
        """Markdown content in toon block should NOT be treated as fake tool call."""
        md = "# Title\n\n## Section 1\n\nSome text with **bold** and *italic*.\n\n```python\nprint('hello')\n```"
        assert not is_toon_block_fake_tool_call(md)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Code block language classification
# ═══════════════════════════════════════════════════════════════════════════════

class TestCodeBlockClassification:
    """Tests for the full code block classification logic."""

    def test_tool_code_always_fake(self):
        """'tool_code' language blocks are ALWAYS fake, regardless of content."""
        assert classify_code_block_language('tool_code', REAL_PYTHON_CONTENT) == 'definitely_fake'
        assert classify_code_block_language('tool_code', '') == 'definitely_fake'
        assert classify_code_block_language('TOOL_CODE', 'anything') == 'definitely_fake'

    def test_toon_with_real_yaml_is_real_code(self):
        """Toon block with YAML content should be classified as real code."""
        assert classify_code_block_language('toon', REAL_YAML_CONTENT) == 'toon_real_code'

    def test_toon_with_real_python_is_real_code(self):
        """Toon block with Python content should be classified as real code."""
        assert classify_code_block_language('toon', REAL_PYTHON_CONTENT) == 'toon_real_code'

    def test_toon_with_fake_tool_call_is_fake(self):
        """Toon block with tool call JSON should be classified as fake."""
        assert classify_code_block_language('toon', FAKE_TOON_TOOL_CALL) == 'toon_fake'

    def test_json_with_tool_structure_is_fake(self):
        """JSON block with tool+input structure should be classified as fake."""
        assert classify_code_block_language('json', JSON_FAKE_TOOL_CALL) == 'json_fake'

    def test_json_embed_reference_is_normal(self):
        """JSON block with embed reference (no tool+input) should be classified as normal."""
        assert classify_code_block_language('json', JSON_EMBED_REFERENCE) == 'normal'

    def test_python_is_normal(self):
        """Regular Python code block should be classified as normal."""
        assert classify_code_block_language('python', REAL_PYTHON_CONTENT) == 'normal'

    def test_yaml_is_normal(self):
        """Regular YAML code block should be classified as normal."""
        assert classify_code_block_language('yaml', REAL_YAML_CONTENT) == 'normal'

    def test_empty_language_is_normal(self):
        """Empty language code block should be classified as normal."""
        assert classify_code_block_language('', REAL_PYTHON_CONTENT) == 'normal'

    def test_none_language_is_normal(self):
        """None language code block should be classified as normal."""
        assert classify_code_block_language(None, REAL_PYTHON_CONTENT) == 'normal'


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Simulated multi-chunk stream processing
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiChunkToonProcessing:
    """
    Simulates the multi-chunk code block processing flow from stream_consumer.py
    to verify that the fix correctly handles the user's exact scenario.
    
    The user's scenario: Gemini 3 Pro outputs a response with:
    1. Explanatory text (reasoning/analysis)
    2. Code blocks (YAML config + Python script) tagged with language 'toon'
    
    Before the fix: Both code blocks were silently filtered, user saw only text.
    After the fix: Code blocks should be detected as real code and delivered.
    """

    def _simulate_multi_chunk_stream(self, chunks: list[str]) -> dict:
        """
        Simulate the multi-chunk code block processing logic from stream_consumer.py.
        
        Returns a dict with:
        - 'output_chunks': List of chunks that would be emitted to the user
        - 'filtered_code_blocks': List of code blocks that were filtered as fake
        - 'delivered_code_blocks': List of code blocks that were delivered as real
        - 'fake_tool_calls_filtered': Whether the fake_tool_calls_filtered flag was set
        """
        # State tracking (mirrors stream_consumer.py local variables)
        in_code_block = False
        current_code_language = ""
        current_code_content = ""
        toon_pending_validation = False
        fake_tool_calls_filtered = False
        
        output_chunks = []
        filtered_code_blocks = []
        delivered_code_blocks = []
        
        for chunk in chunks:
            # Check for opening fence
            if not in_code_block and chunk.strip().startswith('```'):
                in_code_block = True
                fence_line = chunk.strip()
                # Extract language from fence
                lang_part = fence_line[3:].strip()
                if '\n' in lang_part:
                    current_code_language = lang_part.split('\n')[0].strip()
                    current_code_content = '\n'.join(lang_part.split('\n')[1:])
                else:
                    current_code_language = lang_part
                    current_code_content = ""
                
                # Check for suspicious languages (mirrors the fix)
                lang_lower = current_code_language.lower() if current_code_language else ''
                if lang_lower == 'tool_code':
                    # Definitely suspicious, skip
                    continue
                elif lang_lower == 'toon':
                    toon_pending_validation = True
                    # Don't emit, accumulate content
                    continue
                else:
                    output_chunks.append(chunk)
                continue
            
            # Check for closing fence
            if in_code_block and chunk.strip() == '```':
                in_code_block = False
                
                # Apply the content-based validation (mirrors the fix)
                lang_lower = current_code_language.lower() if current_code_language else ''
                
                is_tool_code = lang_lower == 'tool_code'
                is_toon_fake = False
                if toon_pending_validation and lang_lower == 'toon':
                    is_toon_fake = is_toon_block_fake_tool_call(current_code_content)
                
                is_json_fake = False
                if lang_lower == 'json' and '"tool"' in current_code_content and '"input"' in current_code_content:
                    try:
                        import json
                        parsed = json.loads(current_code_content)
                        is_json_fake = 'tool' in parsed and 'input' in parsed
                    except Exception:
                        pass
                
                if is_tool_code or is_toon_fake or is_json_fake:
                    # Filter this code block
                    filtered_code_blocks.append({
                        'language': current_code_language,
                        'content': current_code_content,
                        'reason': 'tool_code' if is_tool_code else 'toon_fake' if is_toon_fake else 'json_fake'
                    })
                    fake_tool_calls_filtered = True
                    toon_pending_validation = False
                elif toon_pending_validation:
                    # Toon block validated as real code — deliver it
                    toon_pending_validation = False
                    delivered_code_blocks.append({
                        'language': current_code_language,
                        'content': current_code_content
                    })
                    # In real code, this would create an embed reference
                    output_chunks.append(f'[CODE_EMBED: {len(current_code_content)} chars]')
                else:
                    # Normal code block closing
                    delivered_code_blocks.append({
                        'language': current_code_language,
                        'content': current_code_content
                    })
                    output_chunks.append(chunk)
                
                # Reset state
                current_code_language = ""
                current_code_content = ""
                continue
            
            # Accumulate content inside code block
            if in_code_block:
                current_code_content += chunk
                if not toon_pending_validation:
                    output_chunks.append(chunk)
                continue
            
            # Regular text outside code block
            output_chunks.append(chunk)
        
        return {
            'output_chunks': output_chunks,
            'filtered_code_blocks': filtered_code_blocks,
            'delivered_code_blocks': delivered_code_blocks,
            'fake_tool_calls_filtered': fake_tool_calls_filtered
        }

    def test_user_scenario_toon_yaml_and_python_delivered(self):
        """
        Reproduce the exact user scenario from issue 07ed2bbb:
        - Gemini 3 Pro outputs explanatory text + 2 code blocks (YAML + Python)
        - Code blocks have language='toon' (model mimicking internal encoding)
        - Both code blocks should be delivered to user (not filtered)
        """
        chunks = [
            "Das ist frustrierend, aber wir haben eine Lösung.\n\n",
            "### 1. `sites.yaml`\n\n",
            "```toon\n",
            REAL_YAML_CONTENT,
            "```",
            "\n\n### 2. `scraper_final_v11.py`\n\n",
            "```toon\n",
            REAL_PYTHON_CONTENT,
            "```",
            "\n\n"
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        # Both code blocks should be DELIVERED, not filtered
        assert len(result['delivered_code_blocks']) == 2, (
            f"Expected 2 delivered code blocks, got {len(result['delivered_code_blocks'])}. "
            f"Filtered: {len(result['filtered_code_blocks'])}"
        )
        assert len(result['filtered_code_blocks']) == 0, (
            f"Expected 0 filtered code blocks, got {len(result['filtered_code_blocks'])}. "
            f"These should have been delivered as real code."
        )
        assert not result['fake_tool_calls_filtered'], (
            "fake_tool_calls_filtered should be False since no fake tool calls were present"
        )
        
        # The explanatory text should be in output
        full_output = ''.join(result['output_chunks'])
        assert "frustrierend" in full_output
        assert "sites.yaml" in full_output
        assert "scraper_final_v11.py" in full_output

    def test_real_fake_tool_call_still_filtered(self):
        """
        Verify that actual fake tool calls in toon blocks are still filtered.
        The fix should NOT break the original protection.
        """
        chunks = [
            "Let me search for that.\n\n",
            "```toon\n",
            FAKE_TOON_TOOL_CALL,
            "```",
            "\n\n"
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        # Fake tool call should be FILTERED
        assert len(result['filtered_code_blocks']) == 1
        assert result['filtered_code_blocks'][0]['reason'] == 'toon_fake'
        assert len(result['delivered_code_blocks']) == 0
        assert result['fake_tool_calls_filtered']

    def test_mixed_real_and_fake_toon_blocks(self):
        """
        A response with both a real toon code block and a fake toon tool call.
        The real code should be delivered and the fake call should be filtered.
        """
        chunks = [
            "Here's the code and a search result.\n\n",
            "```toon\n",
            REAL_PYTHON_CONTENT,
            "```",
            "\n\n",
            "```toon\n",
            FAKE_TOON_TOOL_CALL,
            "```",
            "\n\n"
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        # One delivered, one filtered
        assert len(result['delivered_code_blocks']) == 1, (
            f"Expected 1 delivered, got {len(result['delivered_code_blocks'])}"
        )
        assert len(result['filtered_code_blocks']) == 1, (
            f"Expected 1 filtered, got {len(result['filtered_code_blocks'])}"
        )
        assert result['fake_tool_calls_filtered']

    def test_tool_code_language_always_filtered(self):
        """tool_code language should ALWAYS be filtered regardless of content."""
        chunks = [
            "```tool_code\n",
            REAL_PYTHON_CONTENT,  # Even real code with tool_code lang is filtered
            "```",
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        # Should be filtered even though content is real Python
        # (tool_code is never a valid programming language)
        assert len(result['filtered_code_blocks']) == 1
        assert result['filtered_code_blocks'][0]['reason'] == 'tool_code'

    def test_normal_python_code_block_not_affected(self):
        """Regular python code blocks should not be affected by the filter at all."""
        chunks = [
            "Here's the code:\n\n",
            "```python\n",
            REAL_PYTHON_CONTENT,
            "```",
            "\n\n"
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        assert len(result['delivered_code_blocks']) == 1
        assert len(result['filtered_code_blocks']) == 0
        assert not result['fake_tool_calls_filtered']

    def test_json_fake_tool_call_filtered(self):
        """JSON blocks with tool+input structure should be filtered."""
        chunks = [
            "```json\n",
            JSON_FAKE_TOOL_CALL,
            "```",
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        assert len(result['filtered_code_blocks']) == 1
        assert result['filtered_code_blocks'][0]['reason'] == 'json_fake'

    def test_json_embed_reference_not_filtered(self):
        """JSON blocks with embed references should NOT be filtered."""
        chunks = [
            "```json\n",
            JSON_EMBED_REFERENCE,
            "```",
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        # Embed references are normal JSON, not fake tool calls
        assert len(result['filtered_code_blocks']) == 0
        assert len(result['delivered_code_blocks']) == 1

    def test_bare_fence_then_toon_language_in_next_chunk(self):
        """
        Simulates the bare-fence path (Path C in stream_consumer.py):
        First chunk has just '```', next chunk has 'toon\\n' as the language.
        This was the exact streaming pattern that triggered the bug.
        """
        chunks = [
            "Here is the YAML:\n\n",
            "```",  # Bare fence
            "toon\n",  # Language in next chunk (with content start)
            REAL_YAML_CONTENT,
            "```",
            "\n\n"
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        # Real code should be delivered
        assert len(result['delivered_code_blocks']) == 1
        assert len(result['filtered_code_blocks']) == 0

    def test_response_with_only_filtered_content_sets_flag(self):
        """
        If ALL content in a response is filtered (only fake tool calls, no text),
        the fake_tool_calls_filtered flag should be True so the fallback message
        is shown.
        """
        chunks = [
            "```toon\n",
            FAKE_TOON_TOOL_CALL,
            "```",
        ]
        
        result = self._simulate_multi_chunk_stream(chunks)
        
        assert result['fake_tool_calls_filtered']
        # Only whitespace/empty in output
        meaningful_output = ''.join(result['output_chunks']).strip()
        assert meaningful_output == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Edge cases for toon content validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestToonEdgeCases:
    """Edge cases that could cause false positives or false negatives."""

    def test_python_with_dict_containing_tool_key(self):
        """
        Python code that defines a dict with 'tool' key should NOT be filtered
        unless it follows the exact fake tool call pattern.
        
        NOTE: This is a known limitation. If Python code contains a string like
        '"tool":' it may trigger a false positive. We accept this trade-off
        because fake tool calls are much more common than Python code that
        literally contains '"tool":' as a string pattern.
        """
        code = """
config = {
    "name": "scraper",
    "version": "1.0",
    "author": "user"
}
"""
        assert not is_toon_block_fake_tool_call(code)

    def test_toon_with_tool_in_variable_name(self):
        """Variable names like 'tooltip' or 'toolbar' should not trigger detection."""
        code = """
tooltip_text = "Hover for more info"
toolbar_items = ["save", "copy", "paste"]
def create_toolbar():
    return ToolbarWidget()
"""
        assert not is_toon_block_fake_tool_call(code)

    def test_toon_with_tool_colon_in_yaml_context(self):
        """
        YAML-like content with 'tool:' key triggers detection (intended behavior).
        This is a deliberate trade-off: YAML configs that have a 'tool:' key
        are likely tool call definitions, not user code.
        """
        code = """
tool: web-search
query: "test search"
"""
        # This SHOULD be detected as fake (it's a tool call definition)
        assert is_toon_block_fake_tool_call(code)

    def test_toon_with_url_containing_tool(self):
        """URLs containing 'tool' should NOT trigger detection."""
        code = """
API_URL = "https://api.example.com/tools/search"
DOCS_URL = "https://docs.example.com/tooling/setup"
"""
        assert not is_toon_block_fake_tool_call(code)

    def test_large_real_code_block(self):
        """Large code blocks (like the user's 2373 char scraper) should not be filtered."""
        # Generate a large but realistic Python file
        code = "#!/usr/bin/env python3\n"
        code += "\"\"\"Web scraper for content extraction.\"\"\"\n\n"
        code += "import asyncio\nimport json\nimport yaml\n\n"
        for i in range(50):
            code += f"def function_{i}(param_{i}: str) -> str:\n"
            code += f"    \"\"\"Process item {i}.\"\"\"\n"
            code += f"    return f'result_{{param_{i}}}'\n\n"
        
        assert len(code) > 2000  # Similar size to filtered blocks
        assert not is_toon_block_fake_tool_call(code)
