"""One model rework of a graphic before embroidery (assertion design-embroidery.prepare.model-rework-only-when-needed).

The fixed sandbox check names findings the deterministic rules cannot solve.
Only then, or when the request carries instructions, one rework round asks the
existing vector author for a complete corrected SVG. No requirements review
runs. A failed or invalid rework never stops the conversion: the original
graphic is converted and a note says so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence

from backend.apps.images.vector_author import (
    InvalidSvgError,
    VectorAuthorError,
    VectorUsage,
    author_svg,
    validate_svg,
)

logger = logging.getLogger(__name__)

FINDING_LABELS: dict[str, str] = {
    "gradient_or_filter": "gradients or filters",
    "live_text": "live text",
    "embedded_pixel_image": "an embedded pixel image",
    "detail_below_1mm": "details smaller than 1 mm",
    "more_than_12_colours": "more than 12 thread colours",
}

AuthorFunction = Callable[..., Awaitable[Any]]


@dataclass
class ReworkOutcome:
    """The graphic to convert and what the rework cost and changed."""

    svg: str
    reworked: bool
    usage: list[VectorUsage] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)
    model_id: str | None = None


def finding_codes(findings: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return the distinct finding codes in check order."""
    codes: list[str] = []
    for finding in findings:
        code = str(finding.get("code") or "") if isinstance(finding, Mapping) else ""
        if code and code not in codes:
            codes.append(code)
    return codes


def needs_rework(findings: Sequence[Mapping[str, Any]], instructions: str) -> bool:
    """A model is involved only for findings or for the user's design wishes."""
    return bool(finding_codes(findings)) or bool(instructions.strip())


def build_rework_prompt(*, findings: Sequence[Mapping[str, Any]], width_mm: float, instructions: str) -> str:
    """Embroidery rules for the author; the fixed system prompt stays unchanged."""
    width = f"{width_mm:g}"
    parts = [
        f"Prepare the existing SVG for machine embroidery. It will be sewn {width} mm wide.",
    ]
    problems = [
        f"- {FINDING_LABELS.get(code, code.replace('_', ' '))}: " + "; ".join(
            str(item.get("detail") or "").strip() for item in findings
            if isinstance(item, Mapping) and item.get("code") == code and str(item.get("detail") or "").strip()
        )
        for code in finding_codes(findings)
    ]
    if problems:
        parts.append("The embroidery check found these problems; solve each one:\n" + "\n".join(
            line.rstrip(": ") for line in problems
        ))
    parts.append(
        "Embroidery rules:\n"
        "- Flat solid fill colours only, at most 12 different colours in total.\n"
        "- No gradients, patterns, filters, masks, blur, shadows or partial opacity.\n"
        "- No <text> or <image> elements: draw any lettering as filled path shapes.\n"
        f"- No shape, line or gap thinner than 1 mm at {width} mm width "
        f"(1/{width} of the drawing width): enlarge, thicken or merge such details, or leave them out.\n"
        "- Keep the viewBox, the composition, the colours and every part that does not need to change exactly as they are."
    )
    if instructions.strip():
        parts.append(f"Also apply the user's design wishes: {instructions.strip()}")
    parts.append("Return the complete updated SVG document.")
    return "\n\n".join(parts)


async def rework_for_embroidery(
    *,
    svg: str,
    findings: Sequence[Mapping[str, Any]],
    width_mm: float,
    instructions: str,
    task_id: str,
    secrets_manager: Any,
    author: AuthorFunction | None = None,
) -> ReworkOutcome:
    """Run at most one rework round; without findings and instructions no model is called."""
    if not needs_rework(findings, instructions):
        return ReworkOutcome(svg=svg, reworked=False)
    write = author or author_svg
    prompt = build_rework_prompt(findings=findings, width_mm=width_mm, instructions=instructions)
    try:
        result = await write(
            task_id=task_id, prompt=prompt, source_svgs=(svg,), requirements=(),
            secrets_manager=secrets_manager, max_attempts=1,
        )
        reworked_svg = validate_svg(result.svg)
    except (VectorAuthorError, InvalidSvgError) as exc:
        logger.warning("[%s] Embroidery rework failed; converting the original graphic: %s", task_id, exc)
        return ReworkOutcome(svg=svg, reworked=False, notes=[{
            "code": "rework_failed",
            "text": "The design could not be adjusted automatically, so it was converted as it is.",
        }])
    return ReworkOutcome(
        svg=reworked_svg, reworked=True, usage=list(result.usage), model_id=result.model_id,
    )


def rework_result_notes(
    *, original_findings: Sequence[Mapping[str, Any]], remaining_findings: Sequence[Mapping[str, Any]],
    reworked: bool, instructions: str,
) -> list[dict[str, str]]:
    """Name what the rework changed and every finding that is still in the delivered design."""
    remaining = finding_codes(remaining_findings)
    notes: list[dict[str, str]] = []
    if reworked:
        solved_text = {
            "gradient_or_filter": "Gradients and filters replaced by flat colours",
            "live_text": "Text converted to stitched shapes",
            "embedded_pixel_image": "Embedded pixel image redrawn as shapes",
            "detail_below_1mm": "Small details enlarged or left out",
            "more_than_12_colours": "Colours reduced to at most 12 threads",
        }
        for code in finding_codes(original_findings):
            if code not in remaining:
                notes.append({"code": f"solved_{code}", "text": solved_text.get(code, f"Fixed {code.replace('_', ' ')}")})
        if instructions.strip():
            notes.append({"code": "instructions_applied", "text": f"Applied your wishes: {instructions.strip()}"})
    for code in remaining:
        notes.append({
            "code": f"unsolved_{code}",
            "text": f"Still contains {FINDING_LABELS.get(code, code.replace('_', ' '))}; the result may not sew cleanly there",
        })
    return notes
