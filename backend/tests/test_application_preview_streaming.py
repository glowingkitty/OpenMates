# backend/tests/test_application_preview_streaming.py
#
# Regression coverage for streamed combined application previews.
# These tests guard protocol boundaries that must remain intact until
# the stream consumer converts generated files into an application embed.

import json

import pytest

from backend.apps.ai.tasks.stream_consumer import (
    _parse_application_preview_combined_files,
    _parse_application_preview_json_bundle_files,
    _should_extract_code_file_header,
)
from backend.shared.providers.e2b_application_preview import (
    ApplicationPreviewEntrypoint,
    ApplicationPreviewFile,
    plan_application_preview_startup,
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


@pytest.mark.parametrize("bundle_format", ["application_preview", "json"])
# contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
def test_two_file_bundle_reaches_startup_with_browser_entry_files(bundle_format: str) -> None:
    package_json = json.dumps({
        "dependencies": {"svelte": "^5.55.7", "vite": "^5.4.21", "@sveltejs/vite-plugin-svelte": "^4.0.4"},
    })
    if bundle_format == "json":
        files = _parse_application_preview_json_bundle_files("json", json.dumps({
            "files": {"package.json": package_json, "src/App.svelte": "<main>Hello</main>"},
        }))
    else:
        files = _parse_application_preview_combined_files(
            bundle_format,
            f"json:package.json\n{package_json}\nsvelte:src/App.svelte\n<main>Hello</main>",
        )
    plan = plan_application_preview_startup(
        files=[ApplicationPreviewFile(path=file["filename"], content=file["content"]) for file in files],
        entrypoints=[ApplicationPreviewEntrypoint(name="frontend", command="npm run dev", port=5173)],
    )
    assert {file.path for file in plan.files} == {"package.json", "src/App.svelte", "src/main.ts", "index.html"}
