# backend/core/api/app/tasks/__init__.py

# Import tasks to ensure they are discovered by Celery
from .email_tasks import verification_email_task
from .email_tasks import new_device_email_task
from .email_tasks import backup_code_email_task
from .email_tasks import purchase_confirmation_email_task
# Keep import for any other existing task files if necessary
from . import user_metrics # This one stays as it wasn't moved

# You might not need to explicitly import the tasks themselves,
# just importing the modules where the @app.task decorator is used
# is often sufficient for Celery's discovery mechanism.

# Optionally, you could define __all__ if you want to control what's imported
# when using 'from app.tasks import *', but it's not strictly necessary for discovery.
# __all__ = [
#     'verification_email_task',
#     'new_device_email_task',
#     'backup_code_email_task',
#     'purchase_confirmation_email_task',
#     'user_metrics',
# ]