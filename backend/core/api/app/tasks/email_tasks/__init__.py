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
from . import recovery_account_email_task  # Import account recovery email task
from . import newsletter_email_task  # Import newsletter email task
from . import issue_report_email_task  # Import issue report email task
from . import community_share_email_task  # Import community share notification task
from . import mailjet_contact_cleanup_task  # Import Mailjet contact cleanup task
from . import support_contribution_email_task  # Import supporter contribution receipt task
from . import account_created_email_task  # Import account created confirmation task
from . import reminder_notification_email_task  # Import reminder notification task
from . import usecase_submitted_email_task  # Import use-case submission admin notification task
from . import password_security_reminder_email_task  # Import periodic password-security reminder task
from . import daily_notification_dispatcher  # Import unified daily notification dispatcher
from . import test_notification_email_task  # Import E2E test failure notification task
from . import test_run_summary_email_task  # Import daily test run summary email task
from . import test_run_started_email_task  # Import test run started notification task

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
    'recovery_account_email_task',
    'newsletter_email_task',
    'issue_report_email_task',
    'community_share_email_task',
    'mailjet_contact_cleanup_task',
    'support_contribution_email_task',
    'account_created_email_task',
    'reminder_notification_email_task',
    'usecase_submitted_email_task',
    'password_security_reminder_email_task',
    'daily_notification_dispatcher',
    'test_notification_email_task',
    'test_run_summary_email_task',
    'test_run_started_email_task',
]
