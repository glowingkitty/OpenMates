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
    with pytest.raises(PipelineError) as raised:
        pipeline.run_convert(tmp_path, options, pipeline.time.monotonic())
    assert raised.value.code == "too_many_stitches"
    assert raised.value.user_message == pipeline.TOO_SLOW_MESSAGE
