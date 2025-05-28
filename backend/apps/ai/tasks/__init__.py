# backend/apps/ai/tasks/__init__.py

# This makes the 'tasks' directory a Python package.
# It also serves as a central point for Celery to discover tasks
# if Celery's autodiscover mechanism is configured to look here,
# or if tasks are explicitly imported from this package.

# Import and re-export tasks from their respective skill modules
# to make them discoverable under the `backend.apps.ai.tasks` namespace.

from .ask_skill_task import process_ai_skill_ask_task

# If you add more skill-specific task files (e.g., another_skill_task.py),
# import and re-export their task functions here as well:
# from .another_skill_task import process_another_skill_task

__all__ = [
    "process_ai_skill_ask_task",
    # "process_another_skill_task", # Add other task names here
]

# Note: Celery's task auto-discovery typically relies on finding @app.task decorators.
# By importing the task functions here, they become part of this package's namespace.
# Ensure your Celery worker's configuration (e.g., in celery_config.py or where Celery app is initialized)
# includes `backend.apps.ai.tasks` in its task auto-discovery paths if you want Celery to find them
# automatically via this __init__.py.
# For example, in your main Celery app setup:
# celery_app.autodiscover_tasks(['backend.core.api.app.tasks', 'backend.apps.ai.tasks'])
#
# Alternatively, if tasks are imported directly by the Celery worker entry point or
# another module that the worker loads, this re-export might primarily serve
# organizational purposes and cleaner import paths for other parts of your application
# that might need to send these tasks.
