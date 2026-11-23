"""Strict docx_model fence parsing: no raw-JSON fallback paragraph."""

import json

import pytest

from backend.apps.ai.tasks.stream_consumer import _extract_document_title_and_filename

MODEL = {
    "title": "Heating Failure",
    "filename": "Letter.docx",
    "blocks": [{"type": "paragraph", "runs": [{"text": "Dear Mr. Example"}]}],
}


# contract-test: supporting surface=rest_api assertions=doc-editor.preview.structured-model
def test_valid_fence_yields_model():
    title, filename, model = _extract_document_title_and_filename("docx_model", json.dumps(MODEL))
    assert (title, filename, model) == ("Heating Failure", "Letter.docx", MODEL)


# contract-test: supporting surface=rest_api assertions=doc-editor.preview.structured-model
def test_double_encoded_json_string_is_unwrapped():
    _, _, model = _extract_document_title_and_filename("docx_model", json.dumps(json.dumps(MODEL)))
    assert model == MODEL


# contract-test: supporting surface=rest_api assertions=doc-editor.preview.structured-model
@pytest.mark.parametrize("content", ['{"title": "x", "blocks": [', '{"title": "x"}', '[1]', '{"blocks": ["text"]}'])
def test_invalid_model_raises_instead_of_raw_json_paragraph(content):
    with pytest.raises(ValueError):
        _extract_document_title_and_filename("docx_model", content)
