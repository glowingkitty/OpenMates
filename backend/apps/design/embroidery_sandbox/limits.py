"""Limits, option validation and the pipeline error type (standard library only)."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_SOURCE_SVG_CHARS = 400_000
MAX_STITCHES = 150_000
RUN_LIMIT_SECONDS = 180
MIN_WIDTH_MM = 20.0
MAX_WIDTH_MM = 400.0
MAX_COLOURS_WITHOUT_FINDING = 12
MIN_DETAIL_MM = 1.0
HOOPS_MM: dict[str, tuple[float, float]] = {
    "100x100": (100.0, 100.0),
    "130x180": (130.0, 180.0),
    "160x260": (160.0, 260.0),
    "200x300": (200.0, 300.0),
}
FABRICS = ("light", "normal", "stretchy")
# Sew-on border (design-embroidery.prepare.sew-on-border), measured at the sewn size.
MIN_BORDER_MM = 1.0
MAX_BORDER_MM = 8.0
DEFAULT_BORDER_COLOUR = "#000000"
# fit_hoop sizes the design to the hoop minus this margin on every side: the sewn
# stitches reach up to ~0.4 mm past the drawn edge (pull compensation, measured).
HOOP_FIT_MARGIN_MM = 1.0
HEX_COLOUR_RE = re.compile(r"^#[0-9a-f]{6}$")

ERROR_MESSAGES: dict[str, str] = {
    "unreadable_svg": "The graphic could not be read as an SVG vector graphic.",
    "nothing_to_sew": "Nothing to sew in this graphic.",
    "too_many_stitches": (
        "The design is too large to sew in one piece (more than 150,000 stitches). "
        "Try a smaller width."
    ),
    "timeout": "The conversion took longer than the 3 minute limit and was stopped.",
    "sandbox_failed": "The embroidery converter failed unexpectedly.",
}


class PipelineError(Exception):
    """A conversion failure with a stable code and a plain-English message."""

    def __init__(self, code: str, message: str | None = None) -> None:
        if code not in ERROR_MESSAGES:
            raise ValueError(f"unknown pipeline error code {code!r}")
        self.code = code
        self.user_message = message or ERROR_MESSAGES[code]
        super().__init__(f"{code}: {self.user_message}")


@dataclass(frozen=True)
class Options:
    """Validated conversion options (mirrors the provider's EmbroideryOptions)."""

    width_mm: float = 100.0
    hoop: str = "none"
    fabric: str = "normal"
    border_mm: float | None = None
    border_colour: str = DEFAULT_BORDER_COLOUR
    fit_hoop: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "Options":
        width = raw.get("width_mm", 100.0)
        hoop = str(raw.get("hoop", "none"))
        fabric = str(raw.get("fabric", "normal"))
        if isinstance(width, bool) or not isinstance(width, (int, float)):
            raise ValueError("width_mm must be a number")
        if not MIN_WIDTH_MM <= float(width) <= MAX_WIDTH_MM:
            raise ValueError(f"width_mm must be between {MIN_WIDTH_MM:g} and {MAX_WIDTH_MM:g}")
        if hoop != "none" and hoop not in HOOPS_MM:
            raise ValueError(f"unknown hoop {hoop!r}")
        if fabric not in FABRICS:
            raise ValueError(f"unknown fabric {fabric!r}")
        border = raw.get("border_mm")
        colour = str(raw.get("border_colour") or DEFAULT_BORDER_COLOUR).lower()
        if border is not None:
            if isinstance(border, bool) or not isinstance(border, (int, float)):
                raise ValueError("border_mm must be a number")
            if not MIN_BORDER_MM <= float(border) <= MAX_BORDER_MM:
                raise ValueError(f"border_mm must be between {MIN_BORDER_MM:g} and {MAX_BORDER_MM:g}")
            border = float(border)
        if not HEX_COLOUR_RE.match(colour):
            raise ValueError("border_colour must be a hex colour like #000000")
        fit = raw.get("fit_hoop", False)
        if not isinstance(fit, bool):
            raise ValueError("fit_hoop must be true or false")
        if fit and hoop == "none":
            raise ValueError("fit_hoop needs a hoop")
        return cls(width_mm=float(width), hoop=hoop, fabric=fabric, border_mm=border, border_colour=colour,
                   fit_hoop=fit)


def check_source_size(svg_text: str) -> None:
    """Reject sources above the Specification's character limit before parsing."""
    if len(svg_text) > MAX_SOURCE_SVG_CHARS:
        raise PipelineError(
            "unreadable_svg",
            f"The graphic is larger than {MAX_SOURCE_SVG_CHARS:,} characters and cannot be converted.",
        )


def hoop_fit(width_mm: float, height_mm: float, hoop: str) -> tuple[str, bool]:
    """Return (fits_hoop, needs_rotation). Rotation by 90 degrees is allowed."""
    if hoop == "none":
        return "not_checked", False
    hoop_w, hoop_h = HOOPS_MM[hoop]
    if width_mm <= hoop_w and height_mm <= hoop_h:
        return "yes", False
    if width_mm <= hoop_h and height_mm <= hoop_w:
        return "yes", True
    return "no", False


def hoop_fit_width(width_mm: float, height_mm: float, extra_mm: float, hoop: str) -> float:
    """Largest design width (without ``extra_mm``, the border on both sides) that fills the hoop.

    ``width_mm`` and ``height_mm`` give the design's proportions. The design may
    be turned by 90 degrees when that sews larger; the result leaves
    HOOP_FIT_MARGIN_MM free on every side and stays within the width limits.
    """
    hoop_w, hoop_h = HOOPS_MM[hoop]
    reserve = extra_mm + 2 * HOOP_FIT_MARGIN_MM
    upright = min((hoop_w - reserve) / width_mm, (hoop_h - reserve) / height_mm)
    turned = min((hoop_h - reserve) / width_mm, (hoop_w - reserve) / height_mm)
    return min(max(width_mm * max(upright, turned), MIN_WIDTH_MM), MAX_WIDTH_MM)
