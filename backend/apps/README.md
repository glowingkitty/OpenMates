# Backend Applications (`backend/apps`)

This directory contains the individual, self-contained applications that form part of the OpenMates backend. Each subdirectory represents a distinct application (e.g., `ai`, `travel`, `health`).

## How to add a new app

The framework uses convention-over-configuration. To add a new app:

1.  Create a directory: `backend/apps/<name>/` (e.g. `backend/apps/travel/`).
2.  Define the app manifest in `backend/apps/<name>/app.yml`.
3.  Implement skill classes in `backend/apps/<name>/skills/`.
4.  Restart the `api` container (and any worker containers that need the app).

That's it. **No `docker-compose.yml` edits.** The api gateway filesystem-scans `backend/apps/*/app.yml` at startup, parses each, and registers the app + its skill classes via `importlib` in an in-process `SkillRegistry`. REST routes (`POST /v1/apps/<id>/skills/<skill_id>`) are auto-registered. Celery workers do the same at `worker_process_init` time and dispatch to the same registry.

## Architecture (OPE-342 — in-process plugins)

Until OPE-342, every app folder had a corresponding `app-<name>` Uvicorn container in `docker-compose.yml`. They burned ~2.6 GiB of idle RAM, added ~10 ms per skill call (HTTP serialization), and silently broke whenever the compose entry was forgotten. They provided none of their claimed benefits — every container shipped the same `requirements.txt`, had no per-app state, and a skill exception was already caught per-request regardless of process boundary.

The current model:

- **Discovery:** `backend/core/api/main.py:discover_apps()` → `backend/core/api/app/services/skill_registry.py:build_skill_registry()` filesystem-scans, applies stage filtering, instantiates a `BaseApp(register_http_routes=False)` per app. Each `BaseApp` resolves skill `class_path` strings via `importlib` at construction time.
- **REST dispatch:** `backend/core/api/app/routes/apps_api.py:call_app_skill()` calls `SkillRegistry.dispatch_skill()` directly — no HTTP, no JSON serialization.
- **Worker dispatch:** `backend/apps/ai/processing/skill_executor.py:execute_skill()` calls the same registry. Workers build their own `SkillRegistry` instance in `init_worker_process()` (`backend/core/api/app/tasks/celery_config.py`).
- **Failure mode:** A skill whose `class_path` import fails is logged ERROR (in `BaseApp._resolve_skill_classes`) and becomes unavailable (REST returns 404, AI preprocessor doesn't see it as a tool). The rest of the app — and the rest of the api — keeps working.

The only containers in `backend/core/docker-compose.yml` that still run app code are the Celery workers, which earn their RAM with real queue workloads:

- `app-ai-worker` — runs the AI processing pipeline (`apps.ai.tasks.*`)
- `app-images-worker` — image generation queue
- `app-pdf-worker` — PDF rendering queue
- `task-worker` — infrastructure tasks (email, persistence, push)
- `task-scheduler` — Celery beat

## Core Components for Each App

1.  **`app.yml` (Required):**
    - The manifest file at `backend/apps/<name>/app.yml`.
    - Defines metadata (name, description, icon), skills, focuses, and memory fields.
    - Validated as `AppYAML` (`backend/shared/python_schemas/app_metadata_schemas.py`).
    - Read by `BaseApp` at startup.

2.  **Skill Implementations (Required for apps with skills):**
    - Python modules under `backend/apps/<name>/skills/`.
    - Each skill class subclasses `BaseSkill` (`backend/apps/base_skill.py`) and implements `async def execute(...)`.
    - Referenced from `app.yml` via `class_path` (e.g. `backend.apps.travel.skills.search.SearchSkill`).
    - Skills must NOT import from other skills. Shared logic goes in `BaseSkill` or `backend/shared/`.

3.  **App-Specific Code (Optional):**
    - Any utility modules, providers, processing logic specific to the app.
    - Live under `backend/apps/<name>/`.

## Shared Framework Components

- **`base_app.py`** — `BaseApp` class. Loads `app.yml`, resolves skill `class_path` references via `importlib`, holds the per-app Celery producer, and provides the `dispatch_skill(skill_id, request_body)` entry point used by the in-process registry. Also retains a legacy FastAPI route registration path (`register_http_routes=True`) which is no longer used by any container after OPE-342.
- **`base_skill.py`** — `BaseSkill` base class for all skill implementations.
- **`backend/shared/python_schemas/`** — shared Pydantic models including `AppYAML`.
