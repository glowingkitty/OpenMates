# backend/shared/python_utils/focus_mode_skill_loader.py
#
# Parser for SKILL.md-format focus mode files.
#
# See docs/architecture/apps/focus-modes.md for the full format spec.
#
# This module parses a SKILL.md file (YAML frontmatter + markdown body)
# into a dict shaped for AppFocusDefinition in
# backend/shared/python_schemas/app_metadata_schemas.py. Downstream code
# consumes the resulting dict without needing to know the source format.
#
# In Phase 1 of the migration (prototype), the loader is used only by a
# startup-time parity validator that checks SKILL.md-derived data against
# the legacy app.yml entry for the same focus mode. In Phase 2, the loader
# becomes the primary source and app.yml `focuses:` entries are removed.

import hashlib
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# Heading → body-section key mapping. Case-insensitive match on the H2
# heading text. Anything not in this map is ignored (treated as authoring
# notes) so the format degrades gracefully.
_BODY_SECTION_HEADINGS = {
    "process": "process",
    "how to use": "how_to_use",
    "system prompt": "system_prompt",
}


class SkillMdParseError(ValueError):
    """Raised when a SKILL.md file cannot be parsed into a valid focus dict."""


def parse_skill_md(file_path: str) -> Dict[str, Any]:
    """
    Parse a single SKILL.md file into a raw dict.

    Returns a dict with both frontmatter fields and body-derived fields
    merged at the top level. Does NOT validate against AppFocusDefinition
    — call load_focus_mode_from_skill_md for that.

    Raises SkillMdParseError on any structural problem (missing frontmatter,
    bad YAML, missing required section, …). Never returns partial data.
    """
    if not os.path.exists(file_path):
        raise SkillMdParseError(f"SKILL.md not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()

    frontmatter, body = _split_frontmatter_and_body(raw, file_path)
    body_sections = _parse_body_sections(body)

    merged: Dict[str, Any] = dict(frontmatter)

    # Process bullets: from `## Process` section
    if "process" in body_sections:
        merged["process"] = _parse_bullet_list(body_sections["process"])

    # How-to-use examples: from `## How to use` section
    if "how_to_use" in body_sections:
        merged["how_to_use"] = _parse_bullet_list(body_sections["how_to_use"])

    # System prompt: from `## System prompt` section (full text, trimmed)
    if "system_prompt" in body_sections:
        merged["system_prompt"] = body_sections["system_prompt"].strip()

    return merged


def load_focus_mode_from_skill_md(file_path: str, app_id: str) -> Dict[str, Any]:
    """
    Parse a SKILL.md file into a dict shaped for AppFocusDefinition.

    Derives translation keys from (app_id, focus id) using the legacy
    convention so the frontend build script and runtime consumers see an
    identical shape — no frontend changes are required in Phase 1.

    Raises SkillMdParseError on any structural problem.
    """
    raw = parse_skill_md(file_path)

    focus_id = raw.get("id")
    if not focus_id or not isinstance(focus_id, str):
        raise SkillMdParseError(
            f"{file_path}: frontmatter must contain a non-empty 'id' field"
        )

    yaml_app_id = raw.get("app")
    if yaml_app_id and yaml_app_id != app_id:
        raise SkillMdParseError(
            f"{file_path}: frontmatter 'app' ({yaml_app_id!r}) does not match "
            f"containing directory app ({app_id!r})"
        )

    # Translation keys follow the legacy convention so the existing
    # frontend i18n resolution path keeps working unchanged.
    name_translation_key = f"{app_id}.{focus_id}"
    description_translation_key = f"{app_id}.{focus_id}.description"
    process_translation_key = f"focus_modes.{app_id}_{focus_id}.process"
    systemprompt_translation_key = f"focus_modes.{app_id}_{focus_id}.systemprompt"

    result: Dict[str, Any] = {
        "id": focus_id,
        "name_translation_key": name_translation_key,
        "description_translation_key": description_translation_key,
        "process_translation_key": process_translation_key,
        "systemprompt_translation_key": systemprompt_translation_key,
    }

    # Pass-through fields that map 1:1 from frontmatter to AppFocusDefinition.
    _copy_if_present(raw, result, "stage")
    _copy_if_present(raw, result, "icon", dest_key="icon_image")
    _copy_if_present(raw, result, "preprocessor-hint", dest_key="preprocessor_hint")
    _copy_if_present(raw, result, "allowed-models", dest_key="allowed_models")
    _copy_if_present(raw, result, "recommended-model", dest_key="recommended_model")
    _copy_if_present(raw, result, "allowed-apps", dest_key="allowed_apps")
    _copy_if_present(raw, result, "allowed-skills", dest_key="allowed_skills")
    _copy_if_present(raw, result, "denied-skills", dest_key="denied_skills")

    # Body-derived fields.
    _copy_if_present(raw, result, "system_prompt")
    _copy_if_present(raw, result, "process")
    _copy_if_present(raw, result, "how_to_use")

    return result


def compute_canonical_source_hash(file_path: str) -> str:
    """
    Compute the SHA-256 hash of a canonical SKILL.md's frontmatter +
    structural body (excluding localized string fields and metadata).

    Used by the parity lint to detect stale translations: if a localized
    SKILL.<lang>.md's `source_hash` doesn't match the current canonical
    hash, its `verified_by_human` flag is auto-flipped to false.

    In Phase 1 this is computed but not yet enforced.
    """
    raw = parse_skill_md(file_path)

    # Fields excluded from the hash because they differ legitimately
    # across languages (translated strings + file-level metadata).
    EXCLUDE = {
        "name",
        "description",
        "preprocessor-hint",  # English-only, identical across locales
        "lang",
        "verified_by_human",
        "source_hash",
        "process",
        "how_to_use",
        "system_prompt",
    }

    structural = {k: v for k, v in raw.items() if k not in EXCLUDE}
    canonical = yaml.safe_dump(structural, sort_keys=True, allow_unicode=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_parity_against_legacy(
    skill_md_dict: Dict[str, Any],
    legacy_focus_dict: Dict[str, Any],
    focus_id: str,
) -> List[str]:
    """
    Compare a SKILL.md-derived focus dict to the legacy app.yml focus entry.

    Returns a list of human-readable drift messages. Empty list = parity.
    Only compares fields both sources populate; never flags SKILL.md-only
    fields (gating, how_to_use) as drift.

    Normalizes whitespace on long text fields (preprocessor_hint,
    system_prompt) since YAML block scalars and markdown bodies handle
    line wrapping differently.
    """
    drift: List[str] = []

    def _norm_text(s: Any) -> Optional[str]:
        if not isinstance(s, str):
            return None
        return re.sub(r"\s+", " ", s).strip() or None

    # Direct string comparisons.
    for field in ("id", "stage", "icon_image"):
        new = skill_md_dict.get(field)
        old = legacy_focus_dict.get(field)
        if new is not None and old is not None and new != old:
            drift.append(f"{focus_id}: {field} differs (SKILL.md={new!r}, app.yml={old!r})")

    # Whitespace-normalized text comparisons.
    for field in ("preprocessor_hint",):
        new_norm = _norm_text(skill_md_dict.get(field))
        old_norm = _norm_text(legacy_focus_dict.get(field))
        if new_norm and old_norm and new_norm != old_norm:
            drift.append(
                f"{focus_id}: {field} differs after whitespace normalization"
            )

    return drift


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_frontmatter_and_body(raw: str, file_path: str) -> Tuple[Dict[str, Any], str]:
    """Split `---\nfrontmatter\n---\nbody` into (dict, body)."""
    if not raw.startswith("---"):
        raise SkillMdParseError(
            f"{file_path}: SKILL.md must start with '---' YAML frontmatter delimiter"
        )

    # Find the closing delimiter. Use a regex that matches '---' on its own line.
    match = re.search(r"^---\s*$", raw, re.MULTILINE)
    if not match:
        raise SkillMdParseError(
            f"{file_path}: could not find opening '---' frontmatter delimiter"
        )
    start_end = match.end()

    end_match = re.search(r"^---\s*$", raw[start_end:], re.MULTILINE)
    if not end_match:
        raise SkillMdParseError(
            f"{file_path}: could not find closing '---' frontmatter delimiter"
        )

    frontmatter_text = raw[start_end : start_end + end_match.start()]
    body_text = raw[start_end + end_match.end() :]

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as e:
        raise SkillMdParseError(f"{file_path}: YAML frontmatter parse error: {e}") from e

    if not isinstance(frontmatter, dict):
        raise SkillMdParseError(
            f"{file_path}: frontmatter must be a YAML mapping, got {type(frontmatter).__name__}"
        )

    return frontmatter, body_text


def _parse_body_sections(body: str) -> Dict[str, str]:
    """
    Split the markdown body into sections keyed by H2 heading.

    H1 headings are ignored (treated as presentational titles).
    Anything before the first H2 is discarded.
    """
    sections: Dict[str, str] = {}
    current_key: Optional[str] = None
    current_lines: List[str] = []

    for line in body.splitlines():
        h2_match = re.match(r"^##\s+(.+?)\s*$", line)
        if h2_match:
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            heading = h2_match.group(1).strip().lower()
            current_key = _BODY_SECTION_HEADINGS.get(heading)
            current_lines = []
            continue

        if current_key is not None:
            current_lines.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def _parse_bullet_list(section_text: str) -> List[str]:
    """Extract `- bullet` lines from a section into a list of strings."""
    bullets: List[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
        elif stripped.startswith("-\t"):
            bullets.append(stripped[2:].strip())
    return bullets


def _copy_if_present(
    src: Dict[str, Any],
    dst: Dict[str, Any],
    src_key: str,
    dest_key: Optional[str] = None,
) -> None:
    """Copy src[src_key] to dst[dest_key or src_key] only when present and not None."""
    if src_key not in src:
        return
    value = src[src_key]
    if value is None:
        return
    dst[dest_key or src_key] = value
