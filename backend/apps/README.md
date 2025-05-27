# Backend Applications (`backend/apps`)

This directory contains the individual, self-contained applications that form part of the OpenMates backend. Each subdirectory represents a distinct application (e.g., `ai`, `travel`, `health`).

The framework is designed for a streamlined, convention-over-configuration approach. To create a new application, developers will:
1.  Create a new directory (e.g., `backend/apps/travel/`).
2.  Define the application's capabilities in an `app.yml` file within that directory (e.g., `backend/apps/travel/app.yml`).
3.  Implement the Python classes for any skills defined in the `app.yml` (e.g., in `backend/apps/travel/skills/`).
4.  Add a service definition to `backend/core/docker-compose.yml` using the unified `Dockerfile.base`.

The combination of `app.yml`, skill implementation files, and the Docker setup (using `Dockerfile.base` and `base_main.py`) is sufficient to run an application.

## Core Components for Each App

1.  **`app.yml` (Required):**
    *   The manifest file for the application, located in the app's root directory (e.g., `backend/apps/travel/app.yml`).
    *   Defines metadata (name, description, icon), skills, focuses, and memory fields.
    *   This file is crucial for service discovery and dynamic route generation by `BaseApp`.

2.  **Skill Implementations (Required for apps with skills):**
    *   Python files containing the logic for each skill defined in `app.yml`.
    *   Example: `backend/apps/ai/skills/ask_skill.py` implements the `AskSkill` class.
    *   Skills should inherit from `BaseSkill` (defined in `backend/apps/base_skill.py`).

3.  **App-Specific Code (Optional):**
    *   Any other Python modules specific to the app's functionality (e.g., utilities, processing logic for skills), placed within the app's directory (e.g., `backend/apps/travel/utils.py`).

## Running Applications: Unified Approach

Applications are run as Docker containers using a **unified base Dockerfile** and a **generic application runner**.

### 1. Unified Base Dockerfile (`backend/apps/Dockerfile.base`)

A single, common Dockerfile is used to build all applications.
*   It handles setting up the Python environment, installing common dependencies, and copying shared framework code (`base_app.py`, `base_skill.py`, shared schemas).
*   It uses a build argument (`APP_NAME`) to identify and copy the specific application's code (e.g., from `backend/apps/travel/` into `/app/travel/` in the container).
*   It is configured to use `base_main.py` as the entry point for Uvicorn.

### 2. Generic Application Runner (`backend/apps/base_main.py`)

This script is the standard entry point for all applications built with `Dockerfile.base`.
*   It reads environment variables (`APP_NAME`, `APP_INTERNAL_PORT`) to determine the application's specific directory (e.g., `/app/travel` for `APP_NAME=travel`) and the port it should listen on.
*   It directly instantiates `BaseApp` from `backend/apps/base_app.py`, configuring it with the determined `app_dir` and `app_port`.
*   The `BaseApp` instance then loads the app's `app.yml`, registers default routes (like `/metadata`, `/health`), and dynamically creates API endpoints for all skills defined in the `app.yml`.

### 3. Docker Compose Configuration

To add a new app (e.g., "travel") using this unified approach:

In `backend/core/docker-compose.yml`:
```yaml
services:
  app-travel:
    container_name: app-travel
    build:
      context: ../../  # Relative to docker-compose.yml, points to project root
      dockerfile: backend/apps/Dockerfile.base # Path to the base Dockerfile
      args:
        APP_NAME: travel # Critical: This tells the base Dockerfile which app to build
    env_file: ../../.env
    environment:
      APP_NAME: "travel" # Used by base_main.py
      # Define a unique port for your app, e.g., TRAVEL_APP_INTERNAL_PORT
      # The base_main.py will look for <APP_NAME_UPPERCASE>_APP_INTERNAL_PORT
      TRAVEL_APP_INTERNAL_PORT: "800X" 
      # Add other necessary environment variables for your app
    volumes:
      # Mount app-specific code for hot-reloading during development
      - ../../backend/apps/travel:/app/travel
      # Common mounts (already included by Dockerfile.base COPY, but good for dev hot-reload)
      - ../../backend/apps:/app/apps 
      - ../../backend/shared/python_schemas:/app/backend_shared/python_schemas
    restart: unless-stopped
    networks:
      - openmates
    # depends_on: [...] # Add dependencies as needed
```

## Shared Framework Components

*   **`base_app.py`:** Provides `BaseApp`, handling `app.yml` loading, validation, dynamic skill route registration, Celery producer, default API endpoints (`/metadata`, `/health`), and the FastAPI instance.
*   **`base_skill.py`:** Provides `BaseSkill` for all skill implementations.
*   **`base_main.py`:** The standard Uvicorn entry point for all apps.
*   **`Dockerfile.base`:** The unified Dockerfile for building all app images.
*   **`backend_shared/python_schemas/`:** Contains shared Pydantic models.