"""Geometry rules of the in-sandbox embroidery pipeline (backend/apps/design/embroidery_sandbox).

The geometry stage needs shapely and svgelements, which live only in the E2B
template (pinned in backend/scripts/build_embroidery_template.py), not in the API
image. They are pinned in backend/requirements-dev.txt, so these tests run in the
isolated CI pytest job and fail loudly when the packages are missing. Ink/Stitch
itself is never called here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.apps.design.embroidery_sandbox import pipeline
from backend.apps.design.embroidery_sandbox.geometry import OVERLAP_MM, prepare
from backend.apps.design.embroidery_sandbox.limits import Options, PipelineError
from backend.apps.design.embroidery_sandbox.ordering import colour_changes
from backend.apps.design.embroidery_sandbox.prepared_svg import write_prepared_svg
from backend.apps.design.embroidery_sandbox.svg_source import scan_source

FIXTURES = Path(__file__).parent / "fixtures" / "embroidery"


def _prepare(name: str, width_mm: float = 100.0):
    text = (FIXTURES / f"{name}.svg").read_text(encoding="utf-8")
    return prepare(text, scan_source(text), width_mm)


def _codes(prepared) -> set[str]:
    return {note["code"] for note in prepared.notes}


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_background_is_dropped_and_colours_grouped() -> None:
    prepared = _prepare("03_stars_background")
    assert "background_removed" in _codes(prepared)
    assert prepared.technical["thread_changes_grouped"] <= prepared.technical["thread_changes_naive"]
    assert not _codes(prepared) & {"colours_grouped", "scaled"}
    assert "#fff4dc" not in {shape.colour for shape in prepared.shapes}
    assert colour_changes([shape.colour for shape in prepared.shapes]) == 7
    assert prepared.width_mm == pytest.approx(100.0, abs=1.0)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_hidden_overlaps_are_cut_down_to_the_overlap_strip() -> None:
    prepared = _prepare("02_overlapping_fills")
    assert prepared.technical["overlaps_cut"] > 0
    assert "overlaps_removed" not in _codes(prepared)
    fills = [shape for shape in prepared.shapes if shape.kind == "fill"]
    for k, lower in enumerate(fills):
        for upper in fills[k + 1:]:
            shared = lower.geom.intersection(upper.geom).area
            # Only the strip under the upper shape's edge stays doubled.
            assert shared <= upper.geom.length * OVERLAP_MM * 1.05


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_lines_split_into_satin_and_running_stitch() -> None:
    prepared = _prepare("04_lines")
    kinds = {shape.kind for shape in prepared.shapes}
    assert kinds == {"satin", "running"}
    assert all(shape.width >= 1.0 for shape in prepared.shapes if shape.kind == "satin")
    assert all(shape.width < 1.0 for shape in prepared.shapes if shape.kind == "running")
    assert "lines_running" in _codes(prepared)
    assert prepared.technical["satin_shapes"] > 0


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_background_only_graphic_has_nothing_to_sew() -> None:
    with pytest.raises(PipelineError) as raised:
        _prepare("08_background_only")
    assert raised.value.code == "nothing_to_sew"
    assert "background" in raised.value.user_message


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_prepared_svg_carries_inkstitch_version_and_palette() -> None:
    text = write_prepared_svg(_prepare("05_logo"), "normal")
    # Without the version Ink/Stitch opens its GUI update dialog and fails headless.
    assert "<inkstitch:inkstitch_svg_version>4</inkstitch:inkstitch_svg_version>" in text
    assert "Madeira Polyneon" in text
    assert 'inkstitch:satin_column="true"' in text


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fixed-rules
def test_design_too_slow_to_convert_fails_before_inkstitch(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "input.svg").write_text((FIXTURES / "06_illustration.svg").read_text(encoding="utf-8"),
                                        encoding="utf-8")

    def never_called(*_args: object) -> None:
        raise AssertionError("Ink/Stitch must not start for a design that cannot finish in time")

    monkeypatch.setattr(pipeline, "_run_inkstitch", never_called)
    options = Options.from_dict({"width_mm": 400.0, "hoop": "none", "fabric": "normal"})
    # About 134,000 estimated stitches need 191 s at the minimum rate; only 175 s of the run are left.
    with pytest.raises(PipelineError) as raised:
        pipeline.run_convert(tmp_path, options, pipeline.time.monotonic() - 420)
    assert raised.value.code == "too_many_stitches"
    assert raised.value.user_message == pipeline.TOO_SLOW_MESSAGE


# Two 30 x 40 squares 4 mm apart, a 30 x 40 square with a 10 mm wide slot and one
# with a 4 mm wide slot, in source units of 1 mm (the drawn width is 156 mm).
BORDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 156 40" width="156" height="40">'
    '<rect x="0" y="0" width="30" height="40" fill="#e8451f"/>'
    '<rect x="34" y="0" width="30" height="40" fill="#e8451f"/>'
    '<path d="M80 0H110V40H80ZM90 10V30H100V10Z" fill="#2a9d8f" fill-rule="evenodd"/>'
    '<path d="M126 0H156V40H126ZM139 15V25H143V15Z" fill="#2a9d8f" fill-rule="evenodd"/>'
    "</svg>"
)


def _bordered(border_mm: float = 3.0, colour: str = "#000000"):
    from backend.apps.design.embroidery_sandbox.border import apply_border

    return apply_border(prepare(BORDER_SVG, scan_source(BORDER_SVG), 156.0, colour), border_mm, colour)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
def test_border_is_sewn_first_and_grows_the_design_by_its_width_on_every_side() -> None:
    plain = prepare(BORDER_SVG, scan_source(BORDER_SVG), 156.0)
    bordered = _bordered(3.0, "#1d3557")
    border, *design = bordered.shapes
    assert border.colour == "#1d3557" and border.kind == "fill"
    assert len(design) == len(plain.shapes)
    assert bordered.width_mm == pytest.approx(plain.width_mm + 6.0, abs=0.05)
    assert bordered.height_mm == pytest.approx(plain.height_mm + 6.0, abs=0.05)
    assert border.geom.bounds[0] == pytest.approx(1.0, abs=0.01)  # page margin
    assert bordered.notes[-1] == {"code": "border_added", "mm": 3.0, "text": "Border of 3 mm added for sewing on"}
    assert all(note["code"] != "border_added" for note in plain.notes)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
def test_border_fills_narrow_gaps_keeps_wide_openings_and_is_not_sewn_under_the_design() -> None:
    from shapely.geometry import Point
    from shapely.ops import unary_union

    from backend.apps.design.embroidery_sandbox.border import BORDER_OVERLAP_MM

    border, *design = _bordered(3.0).shapes
    silhouette = unary_union([shape.geom for shape in design])
    x0, y0 = silhouette.bounds[:2]

    def at(x: float, y: float) -> Point:
        """A point given in source millimetres, moved to where the design now lies."""
        return Point(x0 + x, y0 + y)

    assert border.geom.contains(at(32, 20))        # 4 mm gap between the squares: filled
    assert border.geom.contains(at(141, 20))       # 4 mm slot: filled
    assert not border.geom.contains(at(95, 20))    # 10 mm slot: stays open
    assert border.geom.contains(at(91.5, 20))      # ... with a 3 mm band along its edge
    # Not under the design, only the strip under its edge.
    assert border.geom.intersection(silhouette.buffer(-BORDER_OVERLAP_MM - 0.05)).area < 0.5
    assert border.geom.intersection(silhouette).area > 0
    # Exactly 3 mm wide outside: points 2.9 mm out are border, 3.1 mm out are not.
    assert border.geom.contains(at(15, -2.9)) and not border.geom.contains(at(15, -3.1))


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
def test_border_counts_in_the_stitch_estimate() -> None:
    plain = prepare(BORDER_SVG, scan_source(BORDER_SVG), 156.0)
    bordered = _bordered(3.0)
    assert pipeline._estimate_stitches(bordered, "normal") > pipeline._estimate_stitches(plain, "normal") + 1000


# contract-test: supporting surface=rest_api assertions=design-embroidery.result.complete-and-truthful
def test_stitch_estimate_counts_outlines_so_spotted_designs_are_not_underestimated() -> None:
    # Same sewn area: one 40 x 40 square against 100 separate 4 x 4 spots (10 times the outline).
    square = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80"><rect width="40" height="40" fill="#d62828"/></svg>'
    spots = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">'
             + "".join(f'<rect x="{8 * column}" y="{8 * row}" width="4" height="4" fill="#d62828"/>'
                       for row in range(10) for column in range(10)) + "</svg>")
    compact = pipeline._estimate_stitches(prepare(square, scan_source(square), 40.0), "normal")
    spotted = pipeline._estimate_stitches(prepare(spots, scan_source(spots), 76.0), "normal")
    assert 2300 < compact < 2600        # 1,600 mm2 * 1.2 + 160 mm * 3.09
    assert spotted > compact * 2.5      # 1,600 mm2 * 1.2 + 1,600 mm * 3.09


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fill-the-hoop
def test_fit_hoop_fills_the_hoop_with_a_margin_and_keeps_the_border_width() -> None:
    from backend.apps.design.embroidery_sandbox.limits import hoop_fit, hoop_fit_width

    # Tall design 90 x 170 with a 3 mm border in the 200 x 300 hoop: the height is the limit.
    width = hoop_fit_width(90.0, 170.0, 6.0, "200x300")
    assert width * 170.0 / 90.0 + 6.0 == pytest.approx(298.0, abs=0.01)
    assert width + 6.0 < 198.0
    # Wide design: sized for the turned hoop, and the fit check then advises turning it.
    wide = hoop_fit_width(170.0, 90.0, 0.0, "200x300")
    assert wide == pytest.approx(298.0, abs=0.01)
    assert hoop_fit(wide, wide * 90.0 / 170.0, "200x300") == ("yes", True)
    # Square design: the short hoop side is the limit.
    assert hoop_fit_width(50.0, 50.0, 0.0, "100x100") == pytest.approx(98.0, abs=0.01)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fill-the-hoop
def test_fit_hoop_option_needs_a_hoop_and_sizes_the_prepared_design(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ValueError, match="fit_hoop needs a hoop"):
        Options.from_dict({"width_mm": 100.0, "fit_hoop": True})
    (tmp_path / "input.svg").write_text(BORDER_SVG, encoding="utf-8")
    seen: dict[str, float] = {}

    def stop_before_inkstitch(svg_path: Path, *_args: object) -> None:
        seen["prepared"] = 1.0
        raise PipelineError("timeout")

    sizes: list[tuple[float, float]] = []
    real_border = pipeline.apply_border

    def record_border(prepared, border_mm, colour):
        result = real_border(prepared, border_mm, colour)
        sizes.append((result.width_mm, result.height_mm))
        assert any(note["code"] == "sized_to_hoop" for note in result.notes)
        return result

    monkeypatch.setattr(pipeline, "_run_inkstitch", stop_before_inkstitch)
    monkeypatch.setattr(pipeline, "apply_border", record_border)
    options = Options.from_dict({"width_mm": 50.0, "hoop": "200x300", "fabric": "normal", "border_mm": 3.0,
                                 "fit_hoop": True})
    with pytest.raises(PipelineError):
        pipeline.run_convert(tmp_path, options, pipeline.time.monotonic())
    assert seen and sizes[0][0] == pytest.approx(298.0, abs=0.1) and sizes[0][1] < 198.0


WHISKERS = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">'
    # One element with three separate bands (drawn lines given as outlines), about 3 mm apart.
    '<path fill="#000000" d="M5 5H45V7H5Z M5 10H45V12H5Z M5 15H45V17H5Z"/>'
    '<rect fill="#000000" x="60" y="5" width="30" height="40"/></svg>'
)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.separate-shapes-not-joined
def test_separate_parts_are_trimmed_apart_and_narrow_bands_are_sewn_across() -> None:
    prepared = prepare(WHISKERS, scan_source(WHISKERS), 100.0)
    bands = [shape for shape in prepared.shapes if shape.rails is not None]
    fills = [shape for shape in prepared.shapes if shape.kind == "fill"]
    # Each band is an element of its own, so the thread can be cut between them.
    assert len(bands) == 3 and len(fills) == 1
    assert all(shape.kind == "satin" and shape.width == pytest.approx(2.0 * 100.0 / 85.0, abs=0.1) for shape in bands)
    assert all(shape.trim_after for shape in prepared.shapes[:-1])
    for shape in bands:
        left, right = (list(rail.coords) for rail in shape.rails)
        assert len(left) == len(right)
        # The bands run left to right, so every stitch lies straight up and down across them.
        assert all(abs(one[0] - other[0]) < 0.05 for one, other in zip(left, right))
    assert prepared.technical["bands_as_satin"] == 3
    svg = write_prepared_svg(prepared, "normal")
    assert svg.count('inkstitch:trim_after="true"') == 3
    assert svg.count('inkstitch:satin_column="true"') == 3


def _arc(cx: float, cy: float, inner: float, outer: float) -> str:
    """Half ring open at the bottom, drawn as a filled outline (a closed eye)."""
    return (f"M{cx - outer} {cy}A{outer} {outer} 0 0 1 {cx + outer} {cy}L{cx + inner} {cy}"
            f"A{inner} {inner} 0 0 0 {cx - inner} {cy}Z")


LINE_FACE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80">'
    f'<path fill="#d81b60" d="{_arc(25, 20, 6, 10)}"/>'
    # A nose with a stem (stays an area) and two lines hanging on it.
    '<path fill="#d81b60" d="M40 30H60L52 42V50H70V54H30V50H48V42Z"/>'
    # A ring around a spot and a wedge are not lines.
    '<path fill="#d81b60" fill-rule="evenodd" d="M80 10H100V30H80Z M84 14V26H96V14Z"/>'
    '<path fill="#d81b60" d="M0 60L35 62L0 64Z"/>'
    "</svg>"
)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.drawn-lines-as-satin
def test_drawn_lines_become_satin_columns_and_areas_rings_and_wedges_stay_fills() -> None:
    from shapely.geometry import Polygon

    prepared = prepare(LINE_FACE, scan_source(LINE_FACE), 100.0)
    bands = [shape for shape in prepared.shapes if shape.rails is not None]
    fills = [shape for shape in prepared.shapes if shape.kind == "fill"]
    # The eye arc and the two lines beside the nose stem.
    assert len(bands) == 3
    arc = min(bands, key=lambda shape: shape.geom.bounds[1])
    assert arc.width == pytest.approx(4.0, abs=0.2)
    left, right = (list(rail.coords) for rail in arc.rails)
    assert len(left) == len(right) > 20
    for k in range(5, len(left) - 5):
        # Away from its two ends every stitch lies square to the line, all the way round the arc.
        along = (left[k + 1][0] - left[k - 1][0], left[k + 1][1] - left[k - 1][1])
        across = (right[k][0] - left[k][0], right[k][1] - left[k][1])
        cosine = (along[0] * across[0] + along[1] * across[1]) / (
            (along[0] ** 2 + along[1] ** 2) ** 0.5 * (across[0] ** 2 + across[1] ** 2) ** 0.5)
        assert abs(cosine) < 0.15
    # Nose with stem, ring and wedge are still areas, and nothing of the drawing is lost.
    assert len(fills) >= 3
    assert any(shape.geom.interiors for shape in fills)
    # Arc, nose with stem and bar, ring, wedge; the fill under the columns' ends counts twice.
    drawn = 3.14159 * (10 ** 2 - 6 ** 2) / 2 + 312.0 + (400.0 - 144.0) + 70.0
    sewn = sum(shape.geom.area for shape in fills) + sum(
        Polygon(list(shape.rails[0].coords) + list(shape.rails[1].coords)[::-1]).area for shape in bands)
    assert sewn == pytest.approx(drawn, rel=0.08)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
def test_border_moves_satin_columns_together_with_the_design() -> None:
    from backend.apps.design.embroidery_sandbox.border import apply_border

    plain = prepare(WHISKERS, scan_source(WHISKERS), 100.0)
    bordered = apply_border(plain, 3.0, "#000000")
    before = next(shape for shape in plain.shapes if shape.rails is not None)
    after = next(shape for shape in bordered.shapes if shape.rails is not None)
    shift = (after.geom.coords[0][0] - before.geom.coords[0][0], after.geom.coords[0][1] - before.geom.coords[0][1])
    assert abs(shift[0]) + abs(shift[1]) > 1.0
    moved = (after.rails[0].coords[0][0] - before.rails[0].coords[0][0],
             after.rails[0].coords[0][1] - before.rails[0].coords[0][1])
    assert moved == pytest.approx(shift, abs=1e-6)

