"""Bounded, dated model knowledge for conversations about AI models."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Mapping, Sequence

MODEL_FAMILIES = ("llm", "image", "video", "audio")
MAX_MODELS_PER_PROVIDER = 3
MAX_MODELS_PER_FAMILY = 18
MAX_RELEASE_AGE_DAYS = 365


def _family(model: Mapping[str, Any]) -> str | None:
    skill = model.get("for_app_skill")
    if skill == "ai.ask":
        return "llm"
    if isinstance(skill, str):
        for prefix, family in (("images.", "image"), ("videos.", "video"), ("audio.", "audio")):
            if skill.startswith(prefix):
                return family
    return None


def build_ai_model_catalogue_context(
    provider_configs: Mapping[str, Mapping[str, Any]],
    topics: Sequence[str],
    *,
    today: date | None = None,
) -> str:
    """Summarize the newest dated entries per provider without claiming global coverage."""
    selected = [family for family in MODEL_FAMILIES if family in topics]
    if not selected:
        return ""
    today = today or date.today()
    grouped: dict[str, dict[str, list[tuple[date | None, str, str]]]] = defaultdict(lambda: defaultdict(list))
    for provider_id, provider in provider_configs.items():
        provider_name = provider.get("name") or provider_id
        for model in provider.get("models") or []:
            if not isinstance(model, dict):
                continue
            family = _family(model)
            if family not in selected or not model.get("name"):
                continue
            raw_date = model.get("release_date")
            try:
                released = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
            except ValueError:
                released = None
            if released and released > today:
                continue
            if released and (today - released).days > MAX_RELEASE_AGE_DAYS:
                continue
            description = " ".join(str(model.get("description") or "").split())[:160]
            details = f"{provider_name} — {model['name']}"
            core = []
            if model.get("capability_level") in {"low", "medium", "high", "max"}:
                core.append(f"capability {model['capability_level']}")
            if model.get("reasoning") is True:
                core.append("reasoning")
            for label, key in (("input", "input_types"), ("output", "output_types")):
                modalities = model.get(key)
                if isinstance(modalities, list) and modalities:
                    core.append(f"{label} {', '.join(str(value) for value in modalities[:5])}")
            if core:
                details += f" ({'; '.join(core)})"
            if description:
                details += f": {description}"
            grouped[family][str(provider_id)].append((released, str(model["name"]), details))

    lines = [
        "AI model catalogue snapshot (OpenMates-supported models only; not an exhaustive market list):"
    ]
    for family in selected:
        candidates: list[tuple[date | None, str, str]] = []
        for provider_models in grouped[family].values():
            provider_models.sort(key=lambda item: (item[0] or date.min, item[1]), reverse=True)
            candidates.extend(provider_models[:MAX_MODELS_PER_PROVIDER])
        candidates.sort(key=lambda item: (item[0] or date.min, item[1]), reverse=True)
        lines.append(f"{family.upper()} models:")
        for released, _, details in candidates[:MAX_MODELS_PER_FAMILY]:
            lines.append(f"- {released.isoformat() if released else 'release date unrecorded'}: {details}")
        if not candidates:
            lines.append("- No dated/current entries available in the local catalogue.")
    lines.append(
        "Use these dates as a recency anchor. Prefer current relevant models in comparisons; "
        "discuss older models when the user explicitly requests them or historical context needs them. "
        "Treat entries without a release date as available options with unknown recency. "
        "Do not present this catalogue as a complete list of worldwide releases. "
        "Subscription prices, included usage, rate limits, and recent announcements are NOT in this catalogue. "
        "For those changing facts, use an available web search and cite current primary sources; "
        "if verification is unavailable, state the uncertainty and do not invent exact quotas."
    )
    return "\n".join(lines)
