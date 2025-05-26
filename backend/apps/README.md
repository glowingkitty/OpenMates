# Backend Apps (`backend/apps/`)

This directory houses specialized applications that extend the core OpenMates backend functionality. These apps are designed to be utilized by "Mates" (AI personas) and are orchestrated, in part, by the central AI App. Each subdirectory within `backend/apps/` typically represents a distinct, independently deployable application (e.g., `ai_app`, `web_app`, `health_app`), each with its own internal API.

## Core Concepts

*   **`BaseApp` ([`base_app.py`](base_app.py)):** A foundational class that all specific applications should inherit from. It provides common functionalities such as:
    *   Loading and validating the application's `app.yml` configuration file.
    *   Initializing a FastAPI instance for the app's internal API.
    *   Providing a `/metadata` endpoint for service discovery, exposing the app's skills, focuses, and memory definitions.
    *   Helper methods for interacting with other core services (e.g., requesting credit charges from the main API).

*   **`BaseSkill` ([`base_skill.py`](base_skill.py)):** A base class for all skills defined within applications. Skills are discrete units of functionality. `BaseSkill` aims to provide:
    *   Common structure for skill identification and metadata.
    *   Handling for operational stages (e.g., `development`, `production`).
    *   Mechanisms for specifying underlying AI models (`full_model_reference`).
    *   Integration points for billing and asynchronous task management (e.g., Celery).

*   **`app.yml`:** Each application is expected to have an `app.yml` file in its root directory. This YAML file defines the application's metadata, its skills, focus modes, and memory field structures. The schema for `app.yml` is validated by `BaseApp`.

## Application Structure (General Guideline)

A typical application within `backend/apps/` might have a structure like:

```
backend/apps/
├── my_app_name/
│   ├── app.yml                 # App configuration (skills, focuses, memory)
│   ├── app.py                  # Initializes and runs the FastAPI app (e.g., using BaseApp)
│   ├── Dockerfile              # Dockerfile for building the app's container
│   ├── skills/                 # Directory for skill implementations
│   │   ├── __init__.py
│   │   └── my_skill.py         # Implementation of a specific skill inheriting from BaseSkill
│   ├── focuses/                # (Optional) Logic related to focus modes if complex
│   │   └── ...
│   ├── models/                 # (Optional) Pydantic models specific to the app
│   │   └── ...
│   └── services/               # (Optional) Services specific to this app's domain
│       └── ...
├── base_app.py                 # Base class for all apps
├── base_skill.py               # Base class for all skills
└── README.md                   # This file
```

## Interaction with Core API

Applications run as separate services (typically Docker containers) and expose an internal FastAPI. The main `api` service ([`backend/core/api/main.py`](../core/api/main.py)) discovers these apps and routes external requests to them. Apps can also make authenticated internal API calls back to the main `api` service for core functionalities like user credit management.