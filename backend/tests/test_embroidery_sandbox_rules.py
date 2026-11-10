# backend/tests/test_embroidery_sandbox_rules.py
#
# Unit tests for the standard-library parts of the in-sandbox embroidery
# pipeline (backend/apps/design/embroidery_sandbox): limits and options, the
# structural SVG scan behind the rework findings, the colour-grouping sewing
# order, fabric presets and the DST read-back that every summary number comes
# from. Geometry (shapely/svgelements) runs only inside the E2B template and is
# proven by real sandbox runs (docs/plans/design-embroidery-skill/pipeline-results.md).
# Specification: feature.app-skill.design-embroidery (design-embroidery.prepare.fixed-rules,
# design-embroidery.result.complete-and-truthful, design-embroidery.convert.sandbox-inkstitch).

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.apps.design.embroidery_sandbox import UPLOADED_MODULES
from backend.apps.design.embroidery_sandbox.limits import (
    MAX_SOURCE_SVG_CHARS,
    Options,
    PipelineError,
    check_source_size,
    hoop_fit,
)
from backend.apps.design.embroidery_sandbox.ordering import OrderItem, colour_changes, plan_order
from backend.apps.design.embroidery_sandbox.presets import fill_params, running_params, satin_params
from backend.apps.design.embroidery_sandbox.stitch_report import (
    build_report,
    decode_dst,
    estimated_minutes,
    thread_metres,
    thread_minutes,
    parse_threadlist,
    stitches_json,
)
from backend.apps.design.embroidery_sandbox.svg_source import (
    findings_from_scan,
    normalise_colour,
    scan_source,
)

FIXTURES = Path(__file__).parent / "fixtures" / "embroidery"
PACKAGE = Path(__file__).resolve().parents[1] / "apps" / "design" / "embroidery_sandbox"

# Parameter names defined by Ink/Stitch v3.3.0 lib/elements (fill_stitch.py,
# satin_column.py, stroke.py, element.py) that the presets may use.
INKSTITCH_PARAMS = {
    "fill_method", "angle", "max_stitch_length_mm", "running_stitch_length_mm", "row_spacing_mm",
    "expand_mm", "fill_underlay", "fill_underlay_row_spacing_mm", "fill_underlay_inset_mm",
    "fill_underlay_angle", "satin_column", "zigzag_spacing_mm", "pull_compensation_mm",
    "center_walk_underlay", "contour_underlay", "contour_underlay_inset_mm", "zigzag_underlay",
    "split_method", "stroke_method", "bean_stitch_repeats", "trim_after",
}


# --- DST test encoder (Tajima balanced-ternary moves) -------------------------

_X = {1: (0, 0x01, 0x02), 9: (0, 0x04, 0x08), 3: (1, 0x01, 0x02), 27: (1, 0x04, 0x08), 81: (2, 0x04, 0x08)}
_Y = {1: (0, 0x80, 0x40), 9: (0, 0x20, 0x10), 3: (1, 0x80, 0x40), 27: (1, 0x20, 0x10), 81: (2, 0x20, 0x10)}


def _record(dx: int, dy: int, flags: int = 0) -> bytes:
    data = [0, 0, 0x03 | flags]
    for value, table in ((dx, _X), (dy, _Y)):
        for weight in (81, 27, 9, 3, 1):
            index, positive, negative = table[weight]
            if value > weight // 2:
                data[index] |= positive
                value -= weight
            elif value < -(weight // 2):
                data[index] |= negative
                value += weight
        assert value == 0
    return bytes(data)


def _dst(moves: list[tuple[str, int, int]]) -> bytes:
    """moves: ("s"|"j"|"c", dx, dy) in 0.1 mm with DST's +y up."""
    flags = {"s": 0x00, "j": 0x80, "c": 0xC0}
    body = b"".join(_record(dx, dy, flags[kind]) for kind, dx, dy in moves)
    return b" " * 512 + body + bytes([0x00, 0x00, 0xF3])


THREADLIST = """Design Details
==============================

Thread Order
===========================

1 Poppy #1747 - Madeira Polyneon (#d62828)
2 None #None - None (#1d4e89)

Thread Used
===========================
"""


# --- limits ------------------------------------------------------------------

# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_options_validate_ranges_and_enums() -> None:
    assert Options.from_dict({}) == Options(100.0, "none", "normal")
    assert Options.from_dict({"width_mm": 90, "hoop": "130x180", "fabric": "stretchy"}).width_mm == 90.0
    for bad in ({"width_mm": 19}, {"width_mm": 401}, {"width_mm": True}, {"hoop": "50x50"}, {"fabric": "silk"}):
        with pytest.raises(ValueError):
            Options.from_dict(bad)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
def test_border_options_are_optional_bounded_and_black_by_default() -> None:
    assert Options.from_dict({}).border_mm is None
    options = Options.from_dict({"border_mm": 3})
    assert options.border_mm == 3.0 and options.border_colour == "#000000"
    assert Options.from_dict({"border_mm": 8, "border_colour": "#1D3557"}).border_colour == "#1d3557"
    for bad in ({"border_mm": 0.9}, {"border_mm": 8.5}, {"border_mm": True}, {"border_mm": "3"},
                {"border_mm": 3, "border_colour": "navy"}):
        with pytest.raises(ValueError):
            Options.from_dict(bad)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_source_size_limit_is_unreadable_svg() -> None:
    check_source_size("x" * MAX_SOURCE_SVG_CHARS)
    with pytest.raises(PipelineError) as error:
        check_source_size("x" * (MAX_SOURCE_SVG_CHARS + 1))
    assert error.value.code == "unreadable_svg"
    with pytest.raises(ValueError):
        PipelineError("not_a_code")


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_hoop_fit_allows_rotation_and_reports_not_checked() -> None:
    assert hoop_fit(90.0, 74.0, "none") == ("not_checked", False)
    assert hoop_fit(90.0, 74.0, "130x180") == ("yes", False)
    assert hoop_fit(170.0, 120.0, "130x180") == ("yes", True)
    assert hoop_fit(150.0, 150.0, "130x180") == ("no", False)


# --- structural scan / findings ---------------------------------------------

# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_colour_normalisation() -> None:
    assert normalise_colour("#ABC") == "#aabbcc"
    assert normalise_colour("rgb(255, 0, 10)") == "#ff000a"
    assert normalise_colour("white") == "#ffffff"
    assert normalise_colour("url(#g)") is None


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_findings_fixture_reports_gradient_text_and_image() -> None:
    scan = scan_source((FIXTURES / "07_findings.svg").read_text())
    codes = [finding["code"] for finding in findings_from_scan(scan)]
    assert codes == ["gradient_or_filter", "live_text", "embedded_pixel_image"]
    # Gradient flattened to the average of its stops (#0077b6 and #52b788).
    assert scan.paint_colours["g"] == "#29979f"
    assert scan.uses_filter and scan.image_count == 1
    assert scan.text_snippets == ["OPENMATES EMBROIDERY TEST"]


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
@pytest.mark.parametrize("name", ["01_single_shape.svg", "03_stars_background.svg", "05_logo.svg"])
def test_clean_fixtures_have_no_structural_findings(name: str) -> None:
    assert findings_from_scan(scan_source((FIXTURES / name).read_text())) == []


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
@pytest.mark.parametrize("text", [
    "<html></html>",
    "<svg xmlns='http://www.w3.org/2000/svg'><path",
    "<!DOCTYPE svg [<!ENTITY a 'b'>]><svg xmlns='http://www.w3.org/2000/svg'>&a;</svg>",
])
def test_unreadable_sources_fail_explicitly(text: str) -> None:
    with pytest.raises(PipelineError) as error:
        scan_source(text)
    assert error.value.code == "unreadable_svg"


# --- sewing order ------------------------------------------------------------

# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_stars_in_six_colours_need_one_block_per_colour() -> None:
    colours = ["#e63946", "#2a9d8f", "#264653", "#f4a261", "#8338ec", "#3a86ff"]
    items = [OrderItem(i, colours[i % 6], "fill", (float(i), 0.0)) for i in range(24)]
    order = plan_order(items, {})
    sewn = [items[i].colour for i in order]
    assert colour_changes([item.colour for item in items]) == 23
    assert colour_changes(sewn) == 5
    assert plan_order(items, {}) == order  # deterministic


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_order_respects_stacking_and_defers_unfinishable_colours() -> None:
    # Logo case: navy dots are free, but navy ears/nose lie on the orange head
    # and white muzzle. Starting with navy would need a second navy block.
    items = [
        OrderItem(0, "navy", "fill", (0, 0)),     # free dot
        OrderItem(1, "orange", "fill", (5, 5)),   # head
        OrderItem(2, "white", "fill", (5, 8)),    # muzzle on head
        OrderItem(3, "navy", "fill", (5, 9)),     # nose on muzzle
        OrderItem(4, "navy", "satin", (0, 9)),    # free ring
    ]
    deps = {2: {1}, 3: {2}}
    order = plan_order(items, deps)
    assert order.index(1) < order.index(2) < order.index(3)
    assert colour_changes([items[i].colour for i in order]) == 2


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
def test_shapes_in_the_border_colour_follow_the_border_without_a_thread_change() -> None:
    items = [
        OrderItem(0, "orange", "fill", (5, 5)),   # head
        OrderItem(1, "black", "fill", (0, 0)),    # free ear
        OrderItem(2, "black", "fill", (5, 6)),    # eye on the head
    ]
    deps = {2: {0}}
    order = plan_order(items, deps, start_colour="black")
    assert order == [1, 0, 2]
    assert colour_changes(["black", *(items[i].colour for i in order)]) == 2
    assert plan_order(items, deps, start_colour="red") == plan_order(items, deps)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_lines_come_after_fills_and_cycles_are_rejected() -> None:
    items = [OrderItem(0, "red", "running", (0, 0)), OrderItem(1, "blue", "fill", (1, 1))]
    assert plan_order(items, {}) == [1, 0]
    with pytest.raises(ValueError):
        plan_order(items, {0: {1}, 1: {0}})


# --- fabric presets ------------------------------------------------------------

# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_presets_use_only_known_inkstitch_parameters() -> None:
    used: set[str] = set()
    for fabric in ("light", "normal", "stretchy"):
        used |= set(fill_params(fabric, 30.0))
        for width in (1.2, 3.0, 9.0):
            used |= set(satin_params(fabric, width))
    used |= set(running_params(0.4)) | set(running_params(0.8))
    assert used <= INKSTITCH_PARAMS


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_fabric_changes_density_and_underlay() -> None:
    light, normal, stretchy = (float(fill_params(f, 0)["row_spacing_mm"]) for f in ("light", "normal", "stretchy"))
    assert light > normal > stretchy
    assert len(fill_params("stretchy", 0)["fill_underlay_angle"].split()) == 2
    assert "pull_compensation_mm" not in fill_params("normal", 0)  # slow in Ink/Stitch; expand_mm instead
    assert satin_params("normal", 1.5)["center_walk_underlay"] == "true"
    assert satin_params("normal", 5.0)["zigzag_underlay"] == "true"
    assert satin_params("normal", 9.0)["max_stitch_length_mm"] == "7"
    assert "bean_stitch_repeats" not in running_params(0.4)
    assert running_params(0.8)["bean_stitch_repeats"] == "1"


# --- DST read-back and summary ------------------------------------------------

# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_decode_dst_blocks_jumps_and_points() -> None:
    dst = _dst([("j", 10, 0), ("s", 20, 0), ("s", 0, -20), ("j", 50, 0), ("s", 10, 0),
                ("c", 0, 0), ("j", -100, 0), ("s", 5, 5)])
    blocks = decode_dst(dst)
    assert [block.stitches for block in blocks] == [3, 1]
    assert blocks[0].points == [(30, 0), (30, 20), None, (90, 20)]
    assert blocks[0].jumps == 1
    assert blocks[1].points == [(-5, 15)]


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_build_report_numbers_describe_the_dst() -> None:
    dst = _dst([("s", 0, 0)] + [("s", 10, 0)] * 99 + [("c", 0, 0)] + [("s", 0, -10)] * 50)
    summary, stitches = build_report(dst, THREADLIST)
    assert summary["stitch_count"] == 150
    assert summary["thread_changes"] == 1
    assert summary["width_mm"] == 99.0 and summary["height_mm"] == 50.0
    assert summary["estimated_minutes"] == 2
    # 99 stitches of 1 mm plus 1 mm per stitch = 0.2 m; 49 mm + 50 mm = 0.1 m.
    assert summary["thread_length_m"] == 0.3
    assert summary["threads"] == [
        {"colour_hex": "#d62828", "name": "Poppy (Madeira Polyneon 1747)", "stitch_count": 100, "estimated_minutes": 1,
         "thread_length_m": 0.2},
        {"colour_hex": "#1d4e89", "name": "#1d4e89", "stitch_count": 50, "estimated_minutes": 1,
         "thread_length_m": 0.1},
    ]
    assert stitches["blocks"][0]["points"][0] == [0, 0]
    encoded = stitches_json(stitches)
    assert b" " not in encoded and json.loads(encoded)["width_mm"] == 99.0


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_build_report_rejects_thread_mismatch_and_empty_files() -> None:
    with pytest.raises(ValueError):
        build_report(_dst([("s", 1, 1)]), THREADLIST)
    with pytest.raises(ValueError):
        build_report(_dst([]), THREADLIST)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_estimated_minutes_formula() -> None:
    assert estimated_minutes(0, 0) == 1
    assert estimated_minutes(4800, 0) == 10
    assert estimated_minutes(4801, 2) == 13
    # The 47,067-stitch design a home machine reported as 99 minutes of sewing.
    assert estimated_minutes(47067, 0) == 99
    assert thread_metres(0, 0) == 0.1 and thread_metres(250_000, 10_000) == 35.0
    assert [thread_minutes(count) for count in (14301, 22046, 8783, 1937, 0)] == [30, 46, 19, 5, 1]
    assert parse_threadlist("no order section") == []


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_uploaded_module_list_matches_package() -> None:
    assert sorted(UPLOADED_MODULES) == sorted(path.name for path in PACKAGE.glob("*.py"))


# contract-test: supporting surface=rest_api assertions=design-embroidery.result.complete-and-truthful
def test_preview_shows_light_threads_in_their_real_colour() -> None:
    """Ink/Stitch renders cream thread yellow; the preview brings light threads back, others stay."""
    pytest.importorskip("numpy")
    image_module = pytest.importorskip("PIL.Image")
    from backend.apps.design.embroidery_sandbox.preview import is_light_thread, restore_light_threads

    assert is_light_thread("#fdf0e0") and is_light_thread("#ffffff")
    assert not is_light_thread("#c4592a") and not is_light_thread("#3a7bd5")

    dpi = 254  # one pixel per 0.1 mm
    rows = [[x, y] for y in range(0, 101, 4) for x in ((0, 100) if (y // 4) % 2 == 0 else (100, 0))]
    stitches = {"blocks": [
        {"colour_hex": "#fdf0e0", "points": rows},
        {"colour_hex": "#c4592a", "points": [[x + 150, y] for x, y in rows]},
    ]}
    render = image_module.new("RGBA", (251, 101), (0, 0, 0, 0))
    render.paste((231, 203, 112, 255), (0, 0, 101, 101))    # cream as Ink/Stitch draws it
    render.paste((181, 96, 59, 255), (150, 0, 251, 101))
    fixed = restore_light_threads(render, stitches, dpi)

    red, green, blue, alpha = fixed.getpixel((50, 50))
    assert alpha == 255 and abs(red - green) < 20 and blue > 200, (red, green, blue)
    assert blue / red == pytest.approx(0xE0 / 0xFD, abs=0.02)
    assert fixed.getpixel((200, 50)) == (181, 96, 59, 255)
    assert fixed.getpixel((125, 50))[3] == 0


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border,design-embroidery.result.complete-and-truthful
def test_transparent_preview_drops_the_page_and_keeps_the_stitches() -> None:
    """Ink/Stitch renders on an opaque fabric-coloured page; the transparent PNG keeps only the thread."""
    pytest.importorskip("numpy")
    image_module = pytest.importorskip("PIL.Image")
    import io

    from backend.apps.design.embroidery_sandbox.preview import FABRIC_RGB, to_transparent_png

    dpi = 254  # one pixel per 0.1 mm
    rows = [[x, y] for y in range(0, 101, 4) for x in ((0, 100) if (y // 4) % 2 == 0 else (100, 0))]
    stitches = {"blocks": [{"colour_hex": "#000000", "points": rows}]}
    render = image_module.new("RGBA", (201, 201), FABRIC_RGB + (255,))
    render.paste((20, 20, 20, 255), (50, 50, 151, 151))
    with image_module.open(io.BytesIO(to_transparent_png(_png(render), stitches, dpi))) as result:
        result = result.convert("RGBA")
    assert result.size == (201, 201)
    assert result.getpixel((5, 5))[3] == 0          # page: transparent
    assert result.getpixel((100, 100)) == (20, 20, 20, 255)  # thread: unchanged and opaque


def _png(image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
