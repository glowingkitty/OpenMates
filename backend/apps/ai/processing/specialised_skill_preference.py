"""Specialised app skills before general web search, per request.

Owner rule (2026-11-20, TASK-2134): a specialised app skill that fits the
request is always preferred; general web search is only the fallback when no
app skill fits. The general skill-usage instruction states this once for every
request, but the answer model still picked ``web-search`` when stage two offered
it next to a fitting specialised skill (for example the largest open source
conference question with ``events-search`` and ``web-search`` scored 0.96 and
0.97). This module names the specialised skills of the current request so the
answer model calls them first and keeps web search as the fallback.
"""

from __future__ import annotations

from collections.abc import Iterable

# Broad retrieval skills that a specialised skill should come before.
GENERAL_WEB_SKILLS: frozenset[str] = frozenset({"web-search", "web-browse"})
# Apps whose skills are general retrieval or media enrichment, never "specialised".
GENERAL_APPS: frozenset[str] = frozenset({"web", "news", "images", "videos", "ai", "openmates"})


def specialised_first_instruction(
    stage_two_skills: Iterable[str],
    offered_skills: Iterable[str],
    *,
    explicit_request: bool,
) -> str | None:
    """Return a per-request instruction, or ``None`` when no preference applies.

    ``stage_two_skills`` are the skills the preprocessor selected as relevant
    (before always-included and companion skills are merged); ``offered_skills``
    are the skills finally offered to the answer model. The instruction applies
    only when general web search is offered next to at least one specialised
    skill that stage two selected, and never to an explicit skill request,
    which has its own mandatory instruction.
    """
    if explicit_request:
        return None
    offered = set(offered_skills)
    general = sorted(GENERAL_WEB_SKILLS & offered)
    if not general:
        return None
    specialised = sorted(
        skill for skill in set(stage_two_skills) & offered
        if skill.split("-", 1)[0] not in GENERAL_APPS
    )
    if not specialised:
        return None
    names = ", ".join(f"`{skill}`" for skill in specialised)
    fallback = " or ".join(f"`{skill}`" for skill in general)
    return (
        "**Specialised skills first for this request**\n\n"
        f"This request was matched to the specialised skill(s) {names}. Where one of them covers "
        f"what the user asks, call it first instead of {fallback}. Use {fallback} only for parts "
        "no specialised skill covers, or as a fallback when the specialised skill returns "
        "nothing useful."
    )
