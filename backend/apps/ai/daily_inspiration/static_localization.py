"""Resolve generated static copy without frontend files or translation services.

The JSON is built from the shared i18n YAML source by
``scripts/build_daily_inspiration_fallback.py`` and ships with the backend.
"""
import json
from pathlib import Path


STATIC_LOCALIZATIONS: dict[str, dict[str, dict[str, str]]] = json.loads(
    Path(__file__).with_name("static_localizations.json").read_text(encoding="utf-8")
)


def localized_static_copy(card: str, language: str) -> tuple[str, dict[str, str]]:
    """Return truthful base-language metadata and all visible fields.

    Accept common language-region forms (including underscore separators).
    Unsupported locales use English copy and are explicitly marked English.
    """
    locale = language.strip().lower().replace("_", "-").split("-")[0]
    if locale not in STATIC_LOCALIZATIONS:
        locale = "en"
    return locale, STATIC_LOCALIZATIONS[locale][card].copy()
