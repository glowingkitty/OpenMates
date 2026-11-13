# backend/tests/test_loose_application_files.py
"""Unfenced app file sections after a combined preview block become app files."""
from backend.apps.ai.tasks.loose_application_files import split_loose_application_files
from backend.apps.ai.tasks.stream_consumer import _parse_generated_app_file_header

APP_REF = '```json\n{"type": "application", "embed_id": "app-1"}\n```'
CODE_REF = '```json\n{"type": "code", "embed_id": "code-1"}\n```'


# contract-test: supporting surface=rest_api assertions=projects.files.application-single-source
def test_unfenced_script_sources_after_the_application_become_files() -> None:
    text = (
        f"I built a recipe keeper.\n\n{APP_REF}\n\n\n\n"
        "javascript:src/main.jsx\nimport App from './App.jsx';\nrender(App);\n\n"
        "javascript:src/App.jsx\nexport default function App() {\n  return null;\n}\n"
        f"{CODE_REF}\n"
    )
    files, remaining = split_loose_application_files(text, _parse_generated_app_file_header)

    assert [(f["filename"], f["language"]) for f in files] == [("src/main.jsx", "javascript"), ("src/App.jsx", "javascript")]
    assert files[0]["content"] == "import App from './App.jsx';\nrender(App);"
    assert files[1]["content"].endswith("return null;\n}")
    assert remaining == f"I built a recipe keeper.\n\n{APP_REF}\n\n{CODE_REF}"


# contract-test: supporting surface=rest_api assertions=projects.files.application-single-source
def test_fenced_file_headers_and_plain_text_stay_untouched() -> None:
    text = "Run it with:\n```\njavascript:src/main.jsx\nconsole.log(1)\n```\nsee notes: below"
    assert split_loose_application_files(text, _parse_generated_app_file_header) == ([], text)


# contract-test: supporting surface=rest_api assertions=projects.files.application-single-source
def test_header_without_content_is_kept_as_text() -> None:
    text = f"{APP_REF}\njavascript:src/main.jsx\n"
    files, remaining = split_loose_application_files(text, _parse_generated_app_file_header)
    assert files == [] and remaining == text
