# AI App LLM Providers (`backend/apps/ai/llm_providers`)

This directory contains modules for interacting with specific Large Language Model (LLM) providers. Each file in this directory should encapsulate the logic required to communicate with a particular provider's API, handle authentication, make requests, and process responses.

## Purpose

The goal is to abstract the provider-specific details away from the core AI application logic (e.g., skills, processing steps). This allows for:

-   **Modularity:** Easily add, update, or replace LLM providers without significantly altering the main AI app flow.
-   **Maintainability:** Provider-specific code is isolated, making it easier to manage.
-   **Flexibility:** The AI app can choose which provider and model to use based on configuration, task complexity, user preferences, or other criteria.

## Modules

Examples of modules that might reside here:

-   **[`mistral_client.py`](mistral_client.py):** For interacting with Mistral AI models.
-   `google_client.py`: For interacting with Google's Gemini models via Vertex AI or other APIs.
-   `openai_client.py`: For interacting with OpenAI models.
-   `anthropic_client.py`: For interacting with Anthropic's Claude models.

Each client module should ideally:

-   Handle API key management (likely by fetching secrets via the core `SecretsManager`).
-   Provide functions to invoke specific models for tasks like text generation, tool/function calling, etc.
-   Manage provider-specific request/response formats and error handling.
-   Be callable from higher-level utilities (e.g., in `backend/apps/ai/utils/llm_utils.py`) which then orchestrate calls to these clients.