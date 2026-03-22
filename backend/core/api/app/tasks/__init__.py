# backend/core/api/app/tasks/__init__.py
#
# Import all task modules to ensure they are discovered by Celery when this
# package is loaded. Each import triggers the @app.task decorator to register
# tasks with the Celery application.
#
# The explicit `import X as X` re-export syntax is required to satisfy the
# linter (ruff F401: imported-but-unused) because these modules are imported
# solely for their side effects (task registration), not for direct use here.

from .email_tasks import verification_email_task as verification_email_task
from .email_tasks import new_device_email_task as new_device_email_task
from .email_tasks import backup_code_email_task as backup_code_email_task
from .email_tasks import purchase_confirmation_email_task as purchase_confirmation_email_task
from .email_tasks import credit_note_email_task as credit_note_email_task
from .email_tasks import milestone_checker_task as milestone_checker_task
from .email_tasks import signup_milestone_email_task as signup_milestone_email_task
from .email_tasks import recovery_key_email_task as recovery_key_email_task
from .email_tasks import recovery_account_email_task as recovery_account_email_task
from .email_tasks import newsletter_email_task as newsletter_email_task
from .email_tasks import community_share_email_task as community_share_email_task
from .email_tasks import usecase_submitted_email_task as usecase_submitted_email_task
from . import user_metrics as user_metrics
from . import user_cache_tasks as user_cache_tasks
