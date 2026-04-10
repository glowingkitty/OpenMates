# backend/apps/ai/utils/mate_utils.py
# Utility functions for loading and handling Mate configurations.
#
# Format: each mate lives in `backend/apps/ai/mates/{category}.md` as a
# Claude Code compatible frontmatter markdown file. The frontmatter YAML block
# carries metadata (CC-compatible fields + OpenMates extensions) and the
# markdown body is the English default system prompt.
#
# This format aligns with Claude Code's subagent file format so that future
# imports of Claude Code agents into OpenMates are mostly a drop-in. The
# reserved fields `model`, `tools`, and `skills` are parsed but not yet
# enforced — they will gate model selection, app/skill access, and focus
# modes once OpenMates adds per-mate restrictions.
#
# See docs/architecture/ai/mates.md for the full schema and semantics.

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

# Marker used by Claude Code / Jekyll style frontmatter to delimit the YAML block.
FRONTMATTER_DELIMITER = "---"

# Sentinel that means "no restriction — inherit platform default".
# Used for reserved fields (model, tools, skills) that are parsed but not
# yet enforced.
INHERIT_SENTINEL = "inherit"


class MateConfig(BaseModel):
    """
    Pydantic model for a single Mate's runtime configuration.

    Loaded from a frontmatter .md file in `backend/apps/ai/mates/`.
    Downstream consumers (preprocessor, main_processor, cache, ask_skill_task)
    continue to read the same fields they always have — `id`, `name`,
    `category`, `description`, `default_system_prompt`.

    The `tools` field replaces the old `assigned_apps` field (same semantics,
    CC-compatible name). Currently `None` for all mates — reserved for future
    per-mate app/skill allowlisting.
    """

    # Extra frontmatter fields (colors, i18n keys, etc.) are silently ignored
    # — they are frontend/UI concerns not needed by the backend.
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique, stable identifier (lowercase). From frontmatter `name`.")
    name: str = Field(..., description="Human-readable display name. From frontmatter `display_name`.")
    category: str = Field(..., description="Category the Mate belongs to (e.g., 'software_development').")
    description: str = Field(..., description="A brief description of the Mate's purpose or expertise.")
    default_system_prompt: str = Field(..., description="English default system prompt. From the markdown body.")

    # Reserved fields — parsed but not yet enforced downstream.
    # When a frontmatter value is omitted or set to "inherit", these become None
    # (meaning: no restriction, inherit platform default).
    tools: Optional[List[str]] = Field(
        None,
        description=(
            "List of app or skill IDs this Mate is allowed to use. "
            "None = no restriction (inherit platform default). "
            "Replaces the legacy `assigned_apps` field."
        ),
    )
    model: Optional[str] = Field(
        None,
        description=(
            "Preferred model identifier for this Mate. "
            "None = no restriction (inherit platform default). Not yet enforced."
        ),
    )
    focus_modes: Optional[List[str]] = Field(
        None,
        description=(
            "Focus modes this Mate is allowed to use (Claude Code calls these `skills`). "
            "None = no restriction (inherit platform default). Not yet enforced."
        ),
    )


# Directory containing one .md file per mate (filename = category).
# Resolved relative to the process CWD — inside containers this is /app, which
# places the path at /app/backend/apps/ai/mates/.
DEFAULT_MATES_DIR_PATH = "backend/apps/ai/mates"


def _parse_frontmatter(content: str, source_path: str) -> Tuple[Dict[str, Any], str]:
    """
    Parse a Claude Code / Jekyll style frontmatter markdown file.

    Expected structure:
        ---
        <yaml>
        ---
        <markdown body>

    Returns (frontmatter_dict, body_string). Raises ValueError if the file
    does not have a valid frontmatter block.
    """
    # Normalize line endings so splitting is reliable across platforms.
    normalized = content.replace("\r\n", "\n").lstrip("\ufeff")

    if not normalized.startswith(FRONTMATTER_DELIMITER + "\n") and normalized.strip() != FRONTMATTER_DELIMITER:
        raise ValueError(
            f"Frontmatter file '{source_path}' must begin with a '{FRONTMATTER_DELIMITER}' line."
        )

    # Split into at most 3 parts: before first delimiter (empty), yaml, body.
    parts = normalized.split("\n" + FRONTMATTER_DELIMITER + "\n", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Frontmatter file '{source_path}' is missing a closing '{FRONTMATTER_DELIMITER}' delimiter."
        )

    yaml_block = parts[0][len(FRONTMATTER_DELIMITER) + 1:]  # strip leading "---\n"
    body = parts[1].lstrip("\n").rstrip() + "\n"

    try:
        frontmatter = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter in '{source_path}': {e}") from e

    if not isinstance(frontmatter, dict):
        raise ValueError(f"Frontmatter in '{source_path}' must be a YAML mapping, got {type(frontmatter).__name__}.")

    return frontmatter, body


def _normalize_reserved(value: Any) -> Any:
    """
    Convert the reserved "inherit" sentinel (or missing) to None.

    Accepts: None, "inherit", lists, strings. Returns None for the sentinel,
    otherwise returns the value unchanged.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == INHERIT_SENTINEL:
        return None
    return value


def _build_mate_from_file(file_path: Path) -> MateConfig:
    """
    Read a single mate .md file and build a validated MateConfig.

    Raises ValueError on parse errors and ValidationError on schema errors
    so callers can log and skip individual bad files.
    """
    with file_path.open("r", encoding="utf-8") as f:
        content = f.read()

    frontmatter, body = _parse_frontmatter(content, str(file_path))

    # Claude Code uses `name` as the stable lowercase id. OpenMates keeps a
    # separate human-readable display name in `display_name` (optional; falls
    # back to capitalizing the id).
    raw_id = frontmatter.get("name")
    if not raw_id or not isinstance(raw_id, str):
        raise ValueError(
            f"Mate file '{file_path}' is missing required frontmatter field 'name' (stable lowercase id)."
        )

    display_name = frontmatter.get("display_name") or raw_id.capitalize()

    # Reserved fields: collapse "inherit" → None so downstream code can keep
    # using "None means no restriction" semantics.
    tools = _normalize_reserved(frontmatter.get("tools"))
    model = _normalize_reserved(frontmatter.get("model"))
    focus_modes = _normalize_reserved(frontmatter.get("skills"))  # CC calls them "skills"

    mate_data: Dict[str, Any] = {
        "id": raw_id,
        "name": display_name,
        "category": frontmatter.get("category"),
        "description": frontmatter.get("description"),
        "default_system_prompt": body,
        "tools": tools,
        "model": model,
        "focus_modes": focus_modes,
    }

    return MateConfig(**mate_data)


def load_mates_config(mates_dir_path: str = DEFAULT_MATES_DIR_PATH) -> List[MateConfig]:
    """
    Load all mate configurations from the given directory.

    Walks `mates_dir_path/*.md`, parses each file, and returns the list of
    validated MateConfig objects sorted by id for deterministic ordering.
    Individual files that fail to parse or validate are logged and skipped
    so a single broken mate does not take the whole system down.

    Returns an empty list on fatal errors (missing directory, etc.).
    """
    try:
        mates_dir = Path(mates_dir_path)
        if not mates_dir.is_dir():
            logger.error(f"Mates directory not found at '{mates_dir_path}'.")
            return []

        md_files = sorted(mates_dir.glob("*.md"))
        if not md_files:
            logger.error(f"No mate .md files found in '{mates_dir_path}'.")
            return []

        mates: List[MateConfig] = []
        for md_file in md_files:
            try:
                mates.append(_build_mate_from_file(md_file))
            except (ValueError, ValidationError) as e:
                logger.error(f"Failed to load mate from '{md_file}': {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error loading mate from '{md_file}': {e}", exc_info=True)
                continue

        # Sort by id so downstream iteration order is stable regardless of
        # filesystem ordering.
        mates.sort(key=lambda m: m.id)
        logger.info(f"Successfully loaded and validated {len(mates)} mates from '{mates_dir_path}'.")
        return mates

    except Exception as e:
        logger.error(f"An unexpected error occurred while loading mates from '{mates_dir_path}': {e}", exc_info=True)
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loaded = load_mates_config()
    logger.info(f"Loaded {len(loaded)} mates:")
    for mate in loaded:
        logger.info(f"  {mate.id} ({mate.name}) — category={mate.category}")
