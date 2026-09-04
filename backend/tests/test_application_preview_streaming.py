# backend/tests/test_application_preview_streaming.py
#
# Regression coverage for streamed combined application previews.
# These tests guard protocol boundaries that must remain intact until
# the stream consumer converts generated files into an application embed.

import pytest

from backend.apps.ai.tasks.stream_consumer import (
    _parse_application_preview_combined_files,
    _should_extract_code_file_header,
)


@pytest.mark.parametrize(
    "outer_language",
    [
        "application_preview",
        "application-preview",
        "app_preview",
        "generated_application",
        "generated-application",
        " Application_Preview ",
    ],
)
# contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
def test_combined_application_preview_preserves_first_file_header(
    outer_language: str,
) -> None:
    content = """json:package.json
{"scripts":{"dev":"vite"}}
svelte:src/App.svelte
<main>Hello</main>
"""

    assert _should_extract_code_file_header(outer_language, None) is False
    assert [
        file["filename"]
        for file in _parse_application_preview_combined_files(outer_language, content)
    ] == ["package.json", "src/App.svelte"]


# contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
def test_regular_code_fence_can_extract_missing_filename() -> None:
    assert _should_extract_code_file_header("typescript", None) is True
