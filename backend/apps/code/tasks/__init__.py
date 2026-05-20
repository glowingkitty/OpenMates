# backend/apps/code/tasks/__init__.py
#
# Celery task package for the Code app.
# Imported by celery_config TASK_CONFIG so app_code tasks are registered by
# workers without importing skill modules from unrelated apps.

from backend.apps.code.tasks.run_code_task import run_code_execution_task

__all__ = ["run_code_execution_task"]
