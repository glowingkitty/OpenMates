"""Limits, option validation and the pipeline error type (standard library only)."""

from __future__ import annotations

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
        return cls(width_mm=float(width), hoop=hoop, fabric=fabric)


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
