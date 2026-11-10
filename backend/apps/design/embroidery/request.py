"""Validated design.embroidery request (feature.app-skill.design-embroidery, model EmbroideryRequest).

The skill validates before dispatch and the worker validates again, so a
malformed broker payload never reaches the sandbox.
"""

from __future__ import annotations

import math
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


@dataclass(frozen=True)
class EmbroideryRequest:
    """Conversion settings; ``instructions`` is empty when the request carries none."""

    width_mm: float = DEFAULT_WIDTH_MM
    hoop: str = DEFAULT_HOOP
    fabric: str = DEFAULT_FABRIC
    instructions: str = ""


def parse_embroidery_request(
    *, width_mm: Any = None, hoop: Any = None, fabric: Any = None, instructions: Any = None,
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
    return EmbroideryRequest(width_mm=width, hoop=hoop_value, fabric=fabric_value, instructions=text)
