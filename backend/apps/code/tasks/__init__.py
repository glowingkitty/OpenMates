# backend/apps/code/tasks/__init__.py
#
# Celery task package for the Code app.
# Imported by celery_config TASK_CONFIG so app_code tasks are registered by
# workers without importing skill modules from unrelated apps.

try:  # pragma: no cover - local unit tests may not install Celery.
    from backend.apps.code.tasks.run_code_task import run_code_execution_task
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    run_code_execution_task = None

try:  # pragma: no cover - local unit tests may not install Celery.
    from backend.apps.code.tasks.run_application_preview_task import run_application_preview_task
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    run_application_preview_task = None

from backend.apps.code.tasks.image_to_html_task import image_to_html_task

__all__ = ["run_code_execution_task", "run_application_preview_task", "image_to_html_task"]
