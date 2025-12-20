# backend/core/api/app/tasks/email_tasks/__init__.py
#
# This makes the 'email_tasks' directory a Python package.
# It imports all email task modules to ensure tasks are discovered by Celery
# when the package is imported by celery_config.py

# Import all email task modules to ensure tasks are registered with Celery
from . import verification_email_task
from . import new_device_email_task
from . import backup_code_email_task
from . import purchase_confirmation_email_task
from . import credit_note_email_task
from . import milestone_checker_task
from . import signup_milestone_email_task
from . import recovery_key_email_task
from . import newsletter_email_task  # Import newsletter email task

# Note: When celery_config.py imports 'backend.core.api.app.tasks.email_tasks',
# this __init__.py will execute and import all the task modules, which causes
# the @app.task decorators to run and register the tasks with Celery.

__all__ = [
    'verification_email_task',
    'new_device_email_task',
    'backup_code_email_task',
    'purchase_confirmation_email_task',
    'credit_note_email_task',
    'milestone_checker_task',
    'signup_milestone_email_task',
    'recovery_key_email_task',
    'newsletter_email_task',
]

