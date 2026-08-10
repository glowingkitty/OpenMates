# backend/shared/python_utils/image_generation_defaults.py
#
# Resolve the configured images.generate default model from canonical app and
# provider metadata. Other apps reuse this instead of duplicating image-model
# choices or pricing assumptions.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMAGES_APP_METADATA = REPOSITORY_ROOT / "backend" / "apps" / "images" / "app.yml"
PROVIDERS_ROOT = REPOSITORY_ROOT / "backend" / "providers"


@dataclass(frozen=True)
class ImageGenerationDefault:
    """The configured images.generate model and per-image credit price."""

    model_reference: str
    credits: int


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Unable to load configured image generation metadata: {path.name}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Configured image generation metadata must be a mapping: {path.name}")
    return parsed


def resolve_images_generate_default() -> ImageGenerationDefault:
    """Read the current images.generate default model and provider credit price."""
    app_metadata = _load_yaml(IMAGES_APP_METADATA)
    skill = next(
        (
            candidate
            for candidate in app_metadata.get("skills") or []
            if isinstance(candidate, dict) and candidate.get("id") == "generate"
        ),
        None,
    )
    model_reference = str((skill or {}).get("full_model_reference") or "")
    provider_id, separator, model_id = model_reference.partition("/")
    if not skill or not separator or not provider_id or not model_id:
        raise ValueError("images.generate must define a provider/model default")

    provider_metadata = _load_yaml(PROVIDERS_ROOT / f"{provider_id}.yml")
    model = next(
        (
            candidate
            for candidate in provider_metadata.get("models") or []
            if isinstance(candidate, dict) and candidate.get("id") == model_id
        ),
        None,
    )
    pricing = (model or {}).get("pricing") or {}
    per_unit = pricing.get("per_unit") if isinstance(pricing, dict) else None
    try:
        credits = int((per_unit or {}).get("credits"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Configured image model has no per-unit credit price: {model_reference}") from exc
    if credits <= 0:
        raise ValueError(f"Configured image model has an invalid credit price: {model_reference}")
    return ImageGenerationDefault(model_reference=model_reference, credits=credits)
