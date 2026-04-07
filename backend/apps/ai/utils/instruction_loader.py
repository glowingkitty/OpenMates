# backend/apps/ai/utils/instruction_loader.py
# Loads base instructions for the AI app.
#
# Architecture:
#   Plain-text prose instructions live as individual .md files under
#   backend/apps/ai/instructions/ (one file per instruction key, filename = key).
#   Structured tool schemas (JSON Schema function-calling definitions) stay in
#   base_instructions.yml and prompt_injection_detection.yml.
#
#   load_base_instructions() merges all three sources into a single dict keyed
#   by instruction name — consumers don't need to know where a given key lives.
#   See plan: /home/superdev/.claude/plans/tidy-roaming-newt.md

import logging
import os

import yaml

logger = logging.getLogger(__name__)

AI_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_INSTRUCTIONS_PATH = os.path.join(AI_APP_DIR, "base_instructions.yml")
PROMPT_INJECTION_PATH = os.path.join(AI_APP_DIR, "prompt_injection_detection.yml")
INSTRUCTIONS_MD_DIR = os.path.join(AI_APP_DIR, "instructions")


def _load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        logger.error(f"Instructions YAML NOT FOUND at {path}")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            logger.error(f"Instructions YAML at {path} is empty or malformed")
            return {}
        return data
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML from {path}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error loading {path}: {e}", exc_info=True)
        return {}


def _load_markdown_instructions(directory: str) -> dict:
    """Scan `directory` for *.md files and return {filename_stem: content}."""
    if not os.path.isdir(directory):
        logger.error(f"Instructions markdown directory NOT FOUND at {directory}")
        return {}

    result: dict = {}
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".md"):
            continue
        key = entry[:-3]
        path = os.path.join(directory, entry)
        try:
            with open(path, "r", encoding="utf-8") as f:
                result[key] = f.read()
        except Exception as e:
            logger.error(f"Failed to read instruction file {path}: {e}", exc_info=True)
    return result


def load_base_instructions() -> dict:
    """
    Load and merge all AI-app instructions into a single dict.

    Merge order (later overrides earlier on collision):
      1. base_instructions.yml          — tool schemas
      2. prompt_injection_detection.yml — injection tool + thresholds + chunking
      3. instructions/*.md              — plain-text prose (source of truth for prose)

    .md files take precedence on collision so prose is always edited in markdown.
    Returns an empty dict on any fatal load error (callers must tolerate missing keys).
    """
    merged: dict = {}

    base_yaml = _load_yaml(BASE_INSTRUCTIONS_PATH)
    merged.update(base_yaml)

    injection_yaml = _load_yaml(PROMPT_INJECTION_PATH)
    merged.update(injection_yaml)

    md_instructions = _load_markdown_instructions(INSTRUCTIONS_MD_DIR)
    # Collision detection: any md key that shadows a YAML key is logged loudly.
    collisions = set(md_instructions) & set(merged)
    if collisions:
        logger.error(
            f"Instruction key collision between YAML and .md files: {sorted(collisions)} "
            f"— .md version wins"
        )
    merged.update(md_instructions)

    logger.info(
        f"Loaded AI instructions: {len(base_yaml)} from base_instructions.yml, "
        f"{len(injection_yaml)} from prompt_injection_detection.yml, "
        f"{len(md_instructions)} from instructions/*.md "
        f"(total {len(merged)} keys)"
    )
    return merged


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    instructions = load_base_instructions()
    if instructions:
        logger.info(f"Loaded {len(instructions)} keys:")
        for key in sorted(instructions.keys()):
            value = instructions[key]
            kind = type(value).__name__
            size = len(value) if isinstance(value, str) else "-"
            logger.info(f"  {key}  [{kind}, {size} chars]")
    else:
        logger.error("Failed to load instructions.")
