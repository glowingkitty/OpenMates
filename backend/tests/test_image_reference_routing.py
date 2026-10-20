"""Route opaque image refs separately from inspection, without provider calls."""
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing.preprocessor import (
    _history_has_loaded_image_blocks,
    _image_inspection_fallback_skills,
    _image_reference_consumer_skills,
)


IMAGE_EMBED = '```toon\napp_id: images\nskill_id: upload\nembed_ref: fabric.jpg\nfilename: fabric.jpg\n```'


def _request(text, *, current=False, history=None, refs=None):
    return SimpleNamespace(
        current_user_content=text, has_image_upload_embed=current,
        message_history=history or [{"role": "user", "content": text}],
        embed_file_path_index=refs or {"fabric.jpg": "private-image-id"},
    )


def _catalog():
    def tool(skill_id, field):
        return SimpleNamespace(id=skill_id, tool_schema={"type": "object", "properties": {
            "requests": {"type": "array", "items": {"type": "object", "properties": {
                field: {"type": "string"},
            }}},
        }})
    return {
        "shopping": SimpleNamespace(skills=[tool("search_products", "reference_images")]),
        "images": SimpleNamespace(skills=[tool("generate", "reference_images"), tool("search", "file_path"), tool("view", "file_path")]),
        "code": SimpleNamespace(skills=[tool("image_to_html", "source_image")]),
        "pdf": SimpleNamespace(skills=[tool("read", "file_path")]),
    }


# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
@pytest.mark.parametrize("text,skill", [
    ("Find fabrics similar to this photo", "shopping-search_products"),
    ("Make this photo brighter and explain the changes", "images-generate"),
    ("Find similar images using this photo", "images-search"),
    ("Turn this screenshot into HTML", "code-image_to_html"),
    ("Find fabrics which match this photo", "shopping-search_products"),
    ("Find similar images which use these colors", "images-search"),
    ("Use this photo to generate a variant and describe the changes", "images-generate"),
])
# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
def test_reference_consumer_does_not_get_an_automatic_viewer(text, skill):
    assert _image_inspection_fallback_skills(
        _request(text, current=True), [skill], [skill, "images-view"], _catalog(),
    ) == [skill]


# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
@pytest.mark.parametrize("text,skill", [
    ("Describe the pattern in this photo and find similar fabric", "shopping-search_products"),
    ("Inspect this photo and find similar images", "images-search"),
    ("Describe fabric.jpg and create a variant", "images-generate"),
    ("What is shown in this photo, and find similar fabric?", "shopping-search_products"),
    ("Which bar is tallest in this chart and find similar diagrams?", "images-search"),
    ("How many flowers are in this photo, and create a variant?", "images-generate"),
    ("What is shown in fabric.jpg, and find similar fabric?", "shopping-search_products"),
])
# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
def test_explicit_inspection_with_reference_consumer_keeps_both_tools(text, skill):
    assert _image_inspection_fallback_skills(
        _request(text, current=True), [skill], [skill, "images-view"], _catalog(),
    ) == ["images-view", skill]


# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
def test_photo_only_does_not_expand_a_selected_reference_consumer():
    assert _image_inspection_fallback_skills(
        _request("", current=True), ["shopping-search_products"],
        ["shopping-search_products", "images-view"], _catalog(),
    ) == ["shopping-search_products"]


# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
@pytest.mark.parametrize("text,current", [
    ("Describe this photo", True),
    ("What is this?", True),
    ("Read the chart in fabric.jpg", False),
    (IMAGE_EMBED, False),
    ("", True),
])
def test_inspection_and_photo_only_turn_keep_viewer_fallback(text, current):
    assert _image_inspection_fallback_skills(
        _request(text, current=current), [], ["images-view"], _catalog(),
    ) == ["images-view"]


# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
@pytest.mark.parametrize("text", ["Beschreibe das Bild und finde ähnliche Stoffe", "请分析这张图片", "Explique cette photo"])
def test_semantically_selected_inspection_is_preserved_in_every_language(text):
    selected = ["images-view", "shopping-search_products"]
    assert _image_inspection_fallback_skills(
        _request(text), selected, selected, _catalog(),
    ) == selected


# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
@pytest.mark.parametrize("text", ["What is the capital of Italy?", "Explain compound interest", "Thanks"])
def test_unrelated_historical_image_does_not_promote_viewer(text):
    request = _request(text, history=[{"role": "user", "content": IMAGE_EMBED}, {"role": "user", "content": text}])
    assert _image_inspection_fallback_skills(request, [], ["images-view"], _catalog()) == []


# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
def test_unavailable_viewer_is_not_invented_for_an_inspection_request():
    assert _image_inspection_fallback_skills(
        _request("Describe this photo", current=True), [], [], _catalog(),
    ) == []


# contract-test: direct surface=rest_api assertions=app-skills.images.reference-handoff
def test_reference_capability_comes_from_selected_tool_schema():
    skills = ["shopping-search_products", "images-search", "images-view", "pdf-read", "unknown-invented"]
    assert _image_reference_consumer_skills(skills, _catalog()) == {
        "shopping-search_products", "images-search",
    }


# contract-test: supporting surface=rest_api assertions=app-skills.images.reference-handoff
@pytest.mark.parametrize("value,expected", [
    ([{"role": "user", "content": IMAGE_EMBED}], False),
    ([{"role": "user", "content": [{"type": "image", "embed_id": "private-image-id"}]}], False),
    ([{"role": "tool", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,aW1hZ2U="}}]}], True),
    ([SimpleNamespace(content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,aW1hZ2U="}}])], True),
])
def test_only_loaded_pixels_trigger_image_input_safety(value, expected):
    assert _history_has_loaded_image_blocks(value) is expected
