"""Fabric presets mapped to Ink/Stitch 3.3.0 element parameters (standard library only).

Attribute names are Ink/Stitch's ``inkstitch:`` parameters from
``lib/elements/fill_stitch.py``, ``satin_column.py`` and ``stroke.py`` at v3.3.0.
Light fabric gets less density and lighter underlay so it does not pucker,
stretchy fabric gets denser stitching, crossed fill underlay and more pull
compensation so the stitches do not pull gaps open.

Fills compensate pull with ``expand_mm`` (a geometric grow of the shape), not
with the fill's ``pull_compensation_mm``: measured on E2B, fill pull
compensation made one 100 mm heart take 43 s instead of 5 s to stitch.
"""

from __future__ import annotations

SATIN_MIN_WIDTH_MM = 1.0
BEAN_MIN_WIDTH_MM = 0.6
SATIN_SPLIT_LENGTH_MM = 7.0

_FILL = {
    "light": {"row_spacing_mm": "0.35", "expand_mm": "0.1", "fill_underlay": "true",
              "fill_underlay_row_spacing_mm": "1.4", "fill_underlay_inset_mm": "0.4"},
    "normal": {"row_spacing_mm": "0.30", "expand_mm": "0.2", "fill_underlay": "true",
               "fill_underlay_row_spacing_mm": "1.2", "fill_underlay_inset_mm": "0.3"},
    "stretchy": {"row_spacing_mm": "0.27", "expand_mm": "0.3", "fill_underlay": "true",
                 "fill_underlay_row_spacing_mm": "1.0", "fill_underlay_inset_mm": "0.3"},
}
_SATIN = {
    "light": {"zigzag_spacing_mm": "0.45", "pull_compensation_mm": "0.15"},
    "normal": {"zigzag_spacing_mm": "0.40", "pull_compensation_mm": "0.25"},
    "stretchy": {"zigzag_spacing_mm": "0.36", "pull_compensation_mm": "0.35"},
}
NOTE_TEXT = {
    "light": "Light fabric: lighter density and underlay",
    "normal": "Normal fabric: standard density and underlay",
    "stretchy": "Stretchy fabric: denser stitching, crossed underlay and extra pull compensation",
}


def fill_params(fabric: str, angle_deg: float) -> dict[str, str]:
    """Tatami fill parameters; the underlay runs across the top stitches."""
    params = {"fill_method": "tatami_fill", "angle": f"{angle_deg:g}", "max_stitch_length_mm": "3.5",
              "running_stitch_length_mm": "2.5", **_FILL[fabric]}
    if fabric == "stretchy":
        params["fill_underlay_angle"] = f"{angle_deg + 45:g} {angle_deg - 45:g}"
    else:
        params["fill_underlay_angle"] = f"{angle_deg + 90:g}"
    return params


def satin_params(fabric: str, width_mm: float) -> dict[str, str]:
    """Satin column parameters; underlay grows with the column width."""
    params = {"satin_column": "true", **_SATIN[fabric]}
    if width_mm < 2.0:
        params["center_walk_underlay"] = "true"
    else:
        params["contour_underlay"] = "true"
        params["contour_underlay_inset_mm"] = "0.3"
        if width_mm >= 4.0 or fabric == "stretchy":
            params["zigzag_underlay"] = "true"
    if width_mm > SATIN_SPLIT_LENGTH_MM:
        params["split_method"] = "default"
        params["max_stitch_length_mm"] = f"{SATIN_SPLIT_LENGTH_MM:g}"
    return params


def running_params(width_mm: float) -> dict[str, str]:
    """Running stitch; lines from 0.6 mm get a triple (bean) stitch to stay visible."""
    params = {"stroke_method": "running_stitch", "running_stitch_length_mm": "2.0"}
    if width_mm >= BEAN_MIN_WIDTH_MM:
        params["bean_stitch_repeats"] = "1"
    return params
