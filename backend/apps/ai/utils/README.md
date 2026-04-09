# AI App Utilities (`backend/apps/ai/utils`)

This directory contains utility modules specific to the AI application. These utilities provide helper functions and classes for common tasks within the AI app, such as:

- Interacting with Language Models (LLMs).
- Loading and processing instruction sets.
- Other AI-specific helper functionalities.

## Modules

- **[`llm_utils.py`](llm_utils.py):** Contains functions for making calls to various LLM providers, handling API requests, and processing responses. This might include utilities for both preprocessing and main processing LLM interactions.
- **[`instruction_loader.py`](instruction_loader.py):** Responsible for loading and parsing `base_instructions.yml`.
- **[`mate_utils.py`](mate_utils.py):** Loads mate configs from `backend/apps/ai/mates/*.md` (one frontmatter `.md` file per mate, Claude Code compatible format).

Refer to the individual files for more detailed documentation on their specific functionalities.