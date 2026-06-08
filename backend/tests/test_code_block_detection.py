# backend/tests/test_code_block_detection.py
#
# Unit tests for the code block detection logic in stream_consumer.py.
#
# Guards against false-positive code block detection when the AI model
# outputs markdown code fences as *examples* or *inline references*
# (e.g., "use ```json blocks") rather than actual code blocks.
#
# Bug: Issue 6a948813 — Gemini model wrote a template teaching markdown
# usage, and the stream consumer incorrectly treated the example code
# fence as a real code block, creating a broken embed with 13 chars.

import pytest

try:
    from backend.apps.ai.tasks.stream_consumer import (
        _build_application_manifest_from_code_embeds,
        _extract_code_embed_ids_from_response,
        _extract_application_preview_files_from_markdown_code_block,
        _parse_application_preview_combined_files,
        _parse_application_preview_json_bundle_files,
        _strip_code_file_header_from_content,
        _should_process_chunk_as_code_block,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# Fix 1: Inline code fence detection (context-aware)
# When ``` appears mid-line (after prose text on the same line), it's an
# inline example, not a real code block.
# ---------------------------------------------------------------------------


class TestInlineCodeFenceDetection:
    """Test that code fences preceded by text on the same line are skipped."""

    def test_inline_fence_after_prose(self):
        """Bug scenario: 'use ```json blocks' should NOT be a code block."""
        chunk = "```json\n{ \"key\": \"value\" }\n```"
        aggregated = "Gib Terminal-Befehle immer in entsprechenden Markdown-Codeblöcken (z.B. "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False, "Inline fence after prose should not be treated as code block"

    def test_inline_fence_with_parenthetical(self):
        """'(e.g. ```python)' should NOT be a code block."""
        chunk = "```python\nprint('hello')\n```"
        aggregated = "You can use code blocks (e.g. "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False

    def test_inline_fence_after_colon(self):
        """'like this: ```bash' mid-line should NOT be a code block."""
        chunk = "```bash\nls -la\n```"
        aggregated = "Format your commands like this: "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False

    def test_inline_fence_inside_list_item(self):
        """Fence inside a list item text should NOT be a code block."""
        chunk = "```yaml\nkey: value\n```"
        aggregated = "- Use YAML config files (e.g. "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False


# ---------------------------------------------------------------------------
# Fix 1: Real code fences (should still be detected)
# ---------------------------------------------------------------------------


class TestRealCodeFenceDetection:
    """Test that legitimate code blocks at line start are still detected."""

    def test_fence_at_line_start(self):
        """Standard code block at start of line should be detected."""
        chunk = "```python\ndef hello():\n    print('world')\n```"
        aggregated = "Here is the code:\n"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True


    def test_fence_at_start_of_response(self):
        """Code block as first content should be detected."""
        chunk = "```javascript\nconsole.log('hello')\n```"
        aggregated = ""
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True

    def test_fence_after_newline(self):
        """Code block after a blank line should be detected."""
        chunk = "```json\n{\"key\": \"value\"}\n```"
        aggregated = "Here is the config:\n\n"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True

    def test_fence_inside_blockquote(self):
        """Code block inside a blockquote (> ```python) is valid."""
        chunk = "```python\nprint('hello')\n```"
        aggregated = "> "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True

    def test_fence_inside_nested_blockquote(self):
        """Code block inside nested blockquote (>> ```python) is valid."""
        chunk = "```yaml\nkey: value\n```"
        aggregated = ">> "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True

    def test_fence_after_blockquote_newline(self):
        """Code block on new line inside blockquote is valid."""
        chunk = "```bash\necho hello\n```"
        aggregated = "> Some text\n> \n> "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True

    def test_fence_with_indentation(self):
        """Indented code block should still be detected."""
        chunk = "  ```python\ndef hello():\n    pass\n```"
        aggregated = "Example:\n"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True

    def test_already_in_code_block(self):
        """If already inside a code block, should return False (not a new opening)."""
        chunk = "```python\nmore code\n```"
        aggregated = "```python\ndef hello():\n"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=True)
        assert result is False


class TestGeneratedApplicationManifestDetection:
    """Test conservative grouping of generated code files into an app manifest."""

    def test_requires_package_manifest_and_source_file(self):
        result = _build_application_manifest_from_code_embeds([
            {"embed_id": "file-app", "filename": "src/App.svelte", "language": "svelte"},
        ])

        assert result is None

    def test_builds_svelte_node_application_manifest(self):
        result = _build_application_manifest_from_code_embeds([
            {"embed_id": "file-package", "filename": "./package.json", "language": "json"},
            {"embed_id": "file-app", "filename": "src/App.svelte", "language": "svelte"},
            {"embed_id": "file-main", "filename": "src/main.ts", "language": "typescript"},
        ])

        assert result == {
            "name": "Generated application",
            "framework": "svelte",
            "runtime": "node",
            "file_refs": [
                {"path": "package.json", "embed_id": "file-package", "role": "dependency_manifest"},
                {"path": "src/App.svelte", "embed_id": "file-app", "role": "source"},
                {"path": "src/main.ts", "embed_id": "file-main", "role": "source"},
            ],
            "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
            "main_file": "src/main.ts",
        }

    def test_parses_combined_application_preview_block(self):
        result = _parse_application_preview_combined_files(
            "application_preview",
            """json:package.json
{"scripts":{"dev":"vite"},"dependencies":{"@sveltejs/vite-plugin-svelte":"latest","vite":"latest","svelte":"latest"}}
typescript:src/main.ts
import App from './App.svelte';

new App({ target: document.getElementById('app') });
svelte:src/App.svelte
<script lang="ts">
  let recipes = ['Pasta'];
</script>

<main>{recipes[0]}</main>
""",
        )

        assert result == [
            {
                "language": "json",
                "filename": "package.json",
                "content": '{"scripts":{"dev":"vite"},"dependencies":{"@sveltejs/vite-plugin-svelte":"latest","vite":"latest","svelte":"latest"}}',
            },
            {
                "language": "typescript",
                "filename": "src/main.ts",
                "content": "import App from './App.svelte';\n\nnew App({ target: document.getElementById('app') });",
            },
            {
                "language": "svelte",
                "filename": "src/App.svelte",
                "content": '<script lang="ts">\n  let recipes = [\'Pasta\'];\n</script>\n\n<main>{recipes[0]}</main>',
            },
        ]

    def test_ignores_combined_preview_without_app_manifest(self):
        result = _parse_application_preview_combined_files(
            "application_preview",
            """typescript:src/main.ts
console.log('hello');
""",
        )

        assert result == []

    def test_ignores_combined_preview_when_language_is_regular_code(self):
        result = _parse_application_preview_combined_files(
            "typescript",
            """json:package.json
{"scripts":{"dev":"vite"}}
typescript:src/main.ts
console.log('hello');
""",
        )

        assert result == []

    def test_extracts_code_embed_ids_from_response_json_refs(self):
        result = _extract_code_embed_ids_from_response(
            'Intro\n```json\n{"type":"code","embed_id":"file-app"}\n```\n'
            '```json\n{"type":"application","embed_id":"app-parent"}\n```\n'
            '```json\n{"type":"code","embed_id":"file-package"}\n```\n'
        )

        assert result == ["file-app", "file-package"]

    def test_strips_code_file_header_from_content(self):
        code, language, filename = _strip_code_file_header_from_content(
            "svelte:src/App.svelte\n<script>let count = 1;</script>"
        )

        assert language == "svelte"
        assert filename == "src/App.svelte"
        assert code == "<script>let count = 1;</script>"

    def test_parses_json_files_bundle_as_application_preview_files(self):
        result = _parse_application_preview_json_bundle_files(
            "json",
            """{
  "files": {
    "package.json": { "content": "{\\\"scripts\\\":{\\\"dev\\\":\\\"vite\\\"}}" },
    "src/App.svelte": { "content": "<main>Hello</main>" },
    "src/main.ts": { "content": "import App from './App.svelte';" }
  }
}""",
        )

        assert result == [
            {
                "language": "json",
                "filename": "package.json",
                "content": '{"scripts":{"dev":"vite"}}',
            },
            {
                "language": "svelte",
                "filename": "src/App.svelte",
                "content": "<main>Hello</main>",
            },
            {
                "language": "typescript",
                "filename": "src/main.ts",
                "content": "import App from './App.svelte';",
            },
        ]

    def test_extracts_application_files_from_raw_markdown_json_fence(self):
        files, cleaned = _extract_application_preview_files_from_markdown_code_block(
            "Intro\n```json\n"
            '{"files":{"package.json":{"content":"{}"},"src/App.svelte":{"content":"<main />"}}}'
            "\n```\nOutro"
        )

        assert files == [
            {"language": "json", "filename": "package.json", "content": "{}"},
            {"language": "svelte", "filename": "src/App.svelte", "content": "<main />"},
        ]
        assert cleaned == "Intro\n\nOutro"


# ---------------------------------------------------------------------------
# Fix 1: Embed reference skip (existing behavior — must not regress)
# ---------------------------------------------------------------------------


class TestEmbedReferenceSkip:
    """Existing embed references in JSON blocks should always be skipped."""

    def test_json_embed_reference(self):
        """JSON block with embed_id should be skipped."""
        chunk = '```json\n{"type": "code", "embed_id": "abc-123"}\n```'
        aggregated = "Here is the result:\n"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False

    def test_json_embed_ids_reference(self):
        """JSON block with embed_ids should be skipped."""
        chunk = '```json\n{"type": "table", "embed_ids": ["a", "b"]}\n```'
        aggregated = "The data:\n"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False


# ---------------------------------------------------------------------------
# Fix 1: Edge cases
# ---------------------------------------------------------------------------


class TestCodeFenceEdgeCases:
    """Edge cases for code fence detection."""

    def test_fence_after_only_whitespace_on_line(self):
        """Whitespace-only prefix before ``` should be treated as real code block."""
        chunk = "```python\ncode\n```"
        aggregated = "Text\n   "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True

    def test_inline_fence_in_blockquote_with_text(self):
        """Inline fence inside blockquote text should be skipped."""
        chunk = "```json\n{}\n```"
        aggregated = "> Use markdown blocks like "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False

    def test_chunk_without_fence(self):
        """Non-fence chunk should return False."""
        chunk = "Just some text"
        aggregated = "Previous text\n"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False

    def test_chunk_has_newline_before_fence(self):
        """Chunk with newline before ``` — fence is on its own line, should be detected.

        This covers the case where the LLM streams "Here is the code:" in one
        chunk and "\\n\\n```python\\ncode\\n```" in the next. The ``` is on its
        own line within the chunk, so it's a real code block even though the
        aggregated response ends with prose text.
        """
        chunk = "\n\n```python\nprint('hello')\n```"
        aggregated = "Here is the solution:"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True, "Chunk with newline before ``` should be treated as real code block"

    def test_chunk_has_single_newline_before_fence(self):
        """Single newline before ``` in chunk is still a real code block."""
        chunk = "\n```bash\nls -la\n```"
        aggregated = "Run this command:"
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is True

    def test_chunk_no_newline_before_fence_inline(self):
        """No newline before ``` in chunk AND prose in aggregated → inline, skip."""
        chunk = "```json\n{}\n```"
        aggregated = "Use this format: "
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False

    def test_inline_fence_exact_production_case(self):
        """Exact reproduction of the production bug from issue 6a948813.

        The Gemini model wrote a blockquote template teaching markdown usage:
        > Gib Terminal-Befehle immer in entsprechenden Markdown-Codeblöcken (z.B. ```json
        The system incorrectly treated this as a real code block.
        """
        chunk = "```json\n"
        aggregated = (
            "> **4. Antwortformat & Kommunikationsstil:**\n"
            "> - Gib Terminal-Befehle immer in entsprechenden "
            "Markdown-Codeblöcken (z.B. "
        )
        result = _should_process_chunk_as_code_block(chunk, aggregated, in_code_block=False)
        assert result is False, "Production bug: inline fence in blockquote list should not be a code block"


# ---------------------------------------------------------------------------
# Fix 2: Minimum content length threshold for code embeds
# ---------------------------------------------------------------------------


class TestMinimumCodeBlockLength:
    """Test that tiny code blocks are not converted to embeds."""

    def test_short_code_block_below_threshold(self):
        """Code block with <20 chars should not become an embed."""
        from backend.apps.ai.tasks.stream_consumer import _is_code_block_too_short_for_embed
        assert _is_code_block_too_short_for_embed("x = 1") is True

    def test_empty_code_block(self):
        """Empty code block should not become an embed."""
        from backend.apps.ai.tasks.stream_consumer import _is_code_block_too_short_for_embed
        assert _is_code_block_too_short_for_embed("") is True

    def test_whitespace_only_code_block(self):
        """Whitespace-only code block should not become an embed."""
        from backend.apps.ai.tasks.stream_consumer import _is_code_block_too_short_for_embed
        assert _is_code_block_too_short_for_embed("   \n\n  ") is True

    def test_real_code_block_above_threshold(self):
        """Code block with >=20 chars should become an embed."""
        from backend.apps.ai.tasks.stream_consumer import _is_code_block_too_short_for_embed
        code = "def hello_world():\n    print('Hello, World!')"
        assert _is_code_block_too_short_for_embed(code) is False

    def test_exactly_at_threshold(self):
        """Code block with exactly 20 chars should become an embed."""
        from backend.apps.ai.tasks.stream_consumer import _is_code_block_too_short_for_embed
        code = "x" * 20
        assert _is_code_block_too_short_for_embed(code) is False

    def test_13_chars_production_bug(self):
        """13 chars was the exact size of the broken embed from issue 6a948813."""
        from backend.apps.ai.tasks.stream_consumer import _is_code_block_too_short_for_embed
        code = "{ \"key\": \"v\" }"  # ~13 chars
        assert _is_code_block_too_short_for_embed(code) is True
