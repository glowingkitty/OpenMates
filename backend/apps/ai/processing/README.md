# AI App Processing Modules

This directory contains modules responsible for the core logic of processing AI requests within the AI App. It separates distinct stages of request handling for clarity and maintainability.

## Modules

-   **[`preprocessor.py`](backend/apps/ai/processing/preprocessor.py):** Handles the initial preprocessing stage of an AI skill request. This includes:
    -   Loading and applying safety instructions.
    -   Interacting with a cost-effective LLM to analyze the request (e.g., for harmful content, category, complexity, memory loading needs, and embedded preview requirements).
    -   Performing initial checks like credit availability.
    -   Identifying relevant embedded preview types (code, math, music, etc.) needed for response formatting.
-   **[`main_processor.py`](backend/apps/ai/processing/main_processor.py):** Handles the main processing stage after preprocessing. This includes:
    -   Loading any required application-specific user memories.
    -   Assembling the full system prompt for the main LLM (incorporating base ethics, Mate defaults, focus prompts, etc.).
    -   Interacting with the selected main LLM to generate a response.
    -   Handling streaming responses, token counting, and credit consumption for the main LLM interaction.
-   **Other potential modules:** As the system evolves, other specialized processing utilities might be added here (e.g., for specific types of content generation, advanced memory integration, etc.).

The Celery tasks defined in [`backend/apps/ai/tasks.py`](backend/apps/ai/tasks.py) will typically orchestrate calls to functions within these modules.