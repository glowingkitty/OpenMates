"""Native reminder previews stay bounded, private, and visually identifiable."""
from io import BytesIO
import base64
from unittest.mock import Mock

import pytest
from PIL import Image

from backend.core.api.app.services import reminder_preview_renderer as renderer


def _image(data):
    return Image.open(BytesIO(data))


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.identifiable-default,notifications.reminder-email.preview-access
@pytest.mark.parametrize("icon,category", [("Train", "travel"), ("CalendarDays", "general_knowledge"), ("unknown", "unknown"), ("", "general_knowledge")])
def test_chat_metadata_icons_and_missing_names_always_render(icon, category):
    data = renderer.render_reminder_preview({"version": 1, "kind": "chat", "title": "Weekend in Berlin", "icon": icon, "category": category})
    assert _image(data).size == (600, 400)
    if icon == "Train":
        fallback = renderer.render_reminder_preview({"version": 1, "kind": "chat", "title": "Weekend in Berlin", "icon": "unknown", "category": category})
        assert data != fallback


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.preview-access
def test_all_category_fallback_icons_are_bundled():
    assets = renderer._assets()
    assert set(assets["fallbacks"].values()) <= set(assets["icons"])


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.identifiable-default,notifications.reminder-email.readable-without-images,notifications.content.privacy-boundary
@pytest.mark.parametrize("kind", ["chat", "event", "appointment"])
@pytest.mark.parametrize("darkmode", [False, True])
def test_native_preview_uses_fixed_rounded_geometry_without_network(monkeypatch, kind, darkmode):
    import urllib.request
    network = Mock(side_effect=AssertionError("Network is forbidden"))
    monkeypatch.setattr(urllib.request, "urlopen", network)
    result = renderer.render_reminder_preview({
        "version": 1, "kind": kind, "title": "Plan the Berlin trip",
        "icon": "plane", "category": "travel", "summary": "Train options and places to stay.",
        "description": "Bring your questions.", "starts_at": "2026-10-27T17:00:00Z",
        "timezone": "Europe/Berlin", "image_url": "https://invalid.example/image.png",
    }, darkmode=darkmode)
    image = _image(result)
    assert image.format == "PNG"
    assert image.size == (600, 400)
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((300, 200))[3] == 255
    assert len(result) < renderer.MAX_OUTPUT_BYTES
    if kind == "chat":
        assert image.getpixel((70, 40)) != image.getpixel((530, 40))
    else:
        assert image.getpixel((300, 360))[:3] == ((23, 23, 23) if darkmode else (255, 255, 255))
        assert image.getpixel((20, 20))[:3] != image.getpixel((300, 360))[:3]
    network.assert_not_called()


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.identifiable-default,notifications.reminder-email.readable-without-images
def test_native_preview_contains_supplied_raster_thumbnail():
    source = BytesIO()
    Image.new("RGB", (64, 64), "#00ff00").save(source, format="PNG")
    result = renderer.render_reminder_preview({"kind": "event", "title": "Community Hour", "image_base64": base64.b64encode(source.getvalue()).decode()})
    assert _image(result).getpixel((300, 60))[:3] == (0, 255, 0)


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
@pytest.mark.parametrize("context", [
    {"kind": "chat", "title": "x" * (renderer.MAX_CONTEXT_BYTES + 1)},
    {"kind": "event", "image_base64": "https://example.com/private.png"},
    {"kind": "event", "image_base64": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode()},
    {"kind": "event", "image_base64": "a" * (renderer.MAX_IMAGE_BYTES * 2)},
    {"kind": "event", "facts": [{"label": "a", "value": "b"}] * 9},
    {"kind": "event", "facts": [{"value": {"nested": "private"}}]},
])
def test_native_preview_rejects_unbounded_or_active_inputs_without_content_in_errors(context):
    with pytest.raises(ValueError) as exc:
        renderer.render_reminder_preview(context)
    assert "private" not in str(exc.value)
    assert "https://" not in str(exc.value)


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
def test_native_preview_rejects_decompression_bomb_before_loading(monkeypatch):
    source = BytesIO()
    Image.new("RGB", (64, 64), "white").save(source, format="PNG")
    monkeypatch.setattr(renderer, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ValueError, match="Invalid reminder thumbnail"):
        renderer.render_reminder_preview({"image_base64": base64.b64encode(source.getvalue()).decode()})


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.identifiable-default,notifications.reminder-email.readable-without-images
def test_date_labels_use_captured_timezone_and_end_time():
    context = {"starts_at": "2026-10-27T17:00:00Z", "ends_at": "2026-10-27T18:00:00Z", "timezone": "Europe/Berlin"}
    assert renderer.reminder_datetime_label(context) == "Tue, 27 Oct 2026 · 18:00 +0100 – 19:00 +0100"
    assert renderer.reminder_datetime_label({"starts_at": "invalid"}) == ""
    assert renderer.reminder_datetime_label(context, "xx_INVALID") == renderer.reminder_datetime_label(context)
