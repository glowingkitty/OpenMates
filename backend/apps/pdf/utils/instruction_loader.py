# backend/apps/pdf/utils/instruction_loader.py
# Loads LLM prompts for the PDF app from individual .md files.
#
# Rationale:
#   Prompts used to live as hardcoded string literals inside
#   backend/apps/pdf/services/toc_detector.py, which made them awkward to edit
#   (required touching Python source). They now live under
#   backend/apps/pdf/instructions/*.md — one file per prompt, filename = key.
#   See plan: /home/superdev/.claude/plans/tidy-roaming-newt.md

import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

PDF_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTRUCTIONS_DIR = os.path.join(PDF_APP_DIR, "instructions")

_cache: Dict[str, str] = {}


def load_pdf_instructions() -> Dict[str, str]:
    """
    Load and cache all PDF-app prompts from instructions/*.md.

    Returns a dict {filename_stem: content}. Cached after first call.
    """
    if _cache:
        return _cache

    if not os.path.isdir(INSTRUCTIONS_DIR):
        logger.error(f"PDF instructions directory not found at {INSTRUCTIONS_DIR}")
        return _cache

    loaded = 0
    for entry in sorted(os.listdir(INSTRUCTIONS_DIR)):
        if not entry.endswith(".md"):
            continue
        key = entry[:-3]
        path = os.path.join(INSTRUCTIONS_DIR, entry)
        try:
            with open(path, "r", encoding="utf-8") as f:
                _cache[key] = f.read()
            loaded += 1
        except Exception as e:
            logger.error(f"Failed to read PDF instruction {path}: {e}", exc_info=True)

    logger.info(f"Loaded {loaded} PDF instruction files from {INSTRUCTIONS_DIR}")
    return _cache


def get_pdf_instruction(key: str) -> str:
    """Fetch a specific prompt by key. Raises KeyError if missing so bugs fail fast."""
    instructions = load_pdf_instructions()
    if key not in instructions:
        raise KeyError(f"PDF instruction '{key}' not found in {INSTRUCTIONS_DIR}")
    return instructions[key]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for k, v in load_pdf_instructions().items():
        logger.info(f"  {k}  [{len(v)} chars]")
