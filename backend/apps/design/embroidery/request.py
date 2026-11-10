"""Validated design.embroidery request (feature.app-skill.design-embroidery, model EmbroideryRequest).

The skill validates before dispatch and the worker validates again, so a
malformed broker payload never reaches the sandbox.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

HOOPS: tuple[str, ...] = ("100x100", "130x180", "160x260", "200x300", "none")
FABRICS: tuple[str, ...] = ("light", "normal", "stretchy")
MIN_WIDTH_MM = 20.0
MAX_WIDTH_MM = 400.0
DEFAULT_WIDTH_MM = 100.0
DEFAULT_HOOP = "none"
DEFAULT_FABRIC = "normal"
MAX_INSTRUCTIONS_CHARS = 500
MIN_BORDER_MM = 1.0
MAX_BORDER_MM = 8.0
DEFAULT_BORDER_COLOUR = "#000000"
_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class EmbroideryRequest:
    """Conversion settings; ``instructions`` is empty when the request carries none.

    ``border_mm`` is None when no sew-on border is wanted; ``border_colour`` only
    applies together with it. With ``fit_hoop`` the design (border included) is
    sized to fill the chosen hoop and ``width_mm`` is not used.
    """

    width_mm: float = DEFAULT_WIDTH_MM
    hoop: str = DEFAULT_HOOP
    fabric: str = DEFAULT_FABRIC
    instructions: str = ""
    border_mm: float | None = None
    border_colour: str = DEFAULT_BORDER_COLOUR
    fit_hoop: bool = False


def _border(border_mm: Any, border_colour: Any) -> tuple[float | None, str]:
    """Validate the optional sew-on border; the colour defaults to black."""
    message = f"border_mm must be a number of millimetres between {MIN_BORDER_MM:g} and {MAX_BORDER_MM:g}"
    if border_colour in (None, ""):
        colour = DEFAULT_BORDER_COLOUR
    elif isinstance(border_colour, str) and _HEX_COLOUR.match(border_colour.strip()):
        colour = border_colour.strip().lower()
    else:
        raise ValueError("border_colour must be a hex colour like #000000")
    if border_mm is None or border_mm == "":
        return None, colour
    if isinstance(border_mm, bool) or not isinstance(border_mm, (int, float, str)):
        raise ValueError(message)
    try:
        width = float(border_mm)
    except ValueError as exc:
        raise ValueError(message) from exc
    if not math.isfinite(width) or not MIN_BORDER_MM <= width <= MAX_BORDER_MM:
        raise ValueError(message)
    return width, colour


def parse_embroidery_request(
    *, width_mm: Any = None, hoop: Any = None, fabric: Any = None, instructions: Any = None,
    border_mm: Any = None, border_colour: Any = None, fit_hoop: Any = None,
) -> EmbroideryRequest:
    """Apply defaults and bounds; raise ``ValueError`` with an assistant-readable reason."""
    if width_mm is None:
        width = DEFAULT_WIDTH_MM
    else:
        if isinstance(width_mm, bool) or not isinstance(width_mm, (int, float, str)):
            raise ValueError("width_mm must be a number of millimetres between 20 and 400")
        try:
            width = float(width_mm)
        except ValueError as exc:
            raise ValueError("width_mm must be a number of millimetres between 20 and 400") from exc
        if not math.isfinite(width) or not MIN_WIDTH_MM <= width <= MAX_WIDTH_MM:
            raise ValueError("width_mm must be between 20 and 400 millimetres")
    hoop_value = DEFAULT_HOOP if hoop in (None, "") else str(hoop)
    if hoop_value not in HOOPS:
        raise ValueError(f"hoop must be one of: {', '.join(HOOPS)}")
    fabric_value = DEFAULT_FABRIC if fabric in (None, "") else str(fabric)
    if fabric_value not in FABRICS:
        raise ValueError(f"fabric must be one of: {', '.join(FABRICS)}")
    if instructions is not None and not isinstance(instructions, str):
        raise ValueError("instructions must be text")
    text = " ".join((instructions or "").split())
    if len(text) > MAX_INSTRUCTIONS_CHARS:
        raise ValueError(f"instructions must be at most {MAX_INSTRUCTIONS_CHARS} characters")
    border, colour = _border(border_mm, border_colour)
    if fit_hoop not in (None, True, False):
        raise ValueError("fit_hoop must be true or false")
    if fit_hoop and hoop_value == "none":
        raise ValueError("fit_hoop needs a hoop: set hoop to the user's hoop size")
    return EmbroideryRequest(width_mm=width, hoop=hoop_value, fabric=fabric_value, instructions=text,
                             border_mm=border, border_colour=colour, fit_hoop=bool(fit_hoop))
