"""The stored preview of a generated picture keeps the whole picture (no crop)."""

import io

import pytest
from PIL import Image

from backend.core.api.app.utils.image_processing import (
    PREVIEW_MAX_SIZE,
    contained_preview,
    process_image_for_storage,
    process_svg_for_storage,
)


METADATA = {
    "prompt": "framed test picture",
    "model": "test-model",
    "software": "OpenMates",
    "source": "OpenMates AI",
    "generated_at": "2026-11-10T00:00:00Z",
}


def _png(width: int, height: int) -> bytes:
    """White picture with a red frame on its outermost pixels: a crop removes the frame."""
    img = Image.new("RGB", (width, height), "white")
    for x in range(width):
        for y in (0, 1, 2, 3, height - 4, height - 3, height - 2, height - 1):
            img.putpixel((x, y), (255, 0, 0))
    for y in range(height):
        for x in (0, 1, 2, 3, width - 4, width - 3, width - 2, width - 1):
            img.putpixel((x, y), (255, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _is_red(pixel) -> bool:
    return pixel[0] > 150 and pixel[1] < 110 and pixel[2] < 110


# contract-test: direct surface=rest_api assertions=images-generate.preview.whole-picture
@pytest.mark.parametrize("size", [(1024, 1024), (2048, 1024), (1024, 2048), (1600, 1200), (3000, 500)])
def test_raster_preview_keeps_whole_picture_and_aspect_ratio(size):
    preview = Image.open(io.BytesIO(process_image_for_storage(_png(*size), metadata=METADATA)["preview_webp"])).convert("RGB")
    width, height = preview.size
    assert width <= PREVIEW_MAX_SIZE[0] and height <= PREVIEW_MAX_SIZE[1]
    assert abs(width / height - size[0] / size[1]) < 0.02
    # The frame on every edge of the source is still on every edge of the preview.
    for point in ((width // 2, 0), (width // 2, height - 1), (0, height // 2), (width - 1, height // 2)):
        assert _is_red(preview.getpixel(point)), f"edge at {point} was cropped"


# contract-test: direct surface=rest_api assertions=images-generate.preview.whole-picture
@pytest.mark.parametrize("box", [(1000, 1000), (1600, 900), (400, 1000)])
def test_svg_preview_keeps_whole_picture_and_aspect_ratio(box):
    pytest.importorskip("cairosvg")
    w, h = box
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<rect width="{w}" height="{h}" fill="#fff"/>'
        f'<rect x="10" y="10" width="{w - 20}" height="{h - 20}" fill="none" stroke="#f00" stroke-width="20"/></svg>'
    ).encode()
    preview = Image.open(io.BytesIO(process_svg_for_storage(svg, metadata=METADATA)["preview_webp"])).convert("RGB")
    width, height = preview.size
    assert width <= PREVIEW_MAX_SIZE[0] and height <= PREVIEW_MAX_SIZE[1]
    assert abs(width / height - w / h) < 0.02
    for point in ((width // 2, 2), (width // 2, height - 3), (2, height // 2), (width - 3, height // 2)):
        assert _is_red(preview.getpixel(point)), f"edge at {point} was cropped"


# contract-test: direct surface=rest_api assertions=images-generate.preview.whole-picture
def test_small_picture_is_not_enlarged():
    assert contained_preview(Image.new("RGB", (300, 200))).size == (300, 200)
