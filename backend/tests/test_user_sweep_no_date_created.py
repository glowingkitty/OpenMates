"""Regression: directus_users has no date_created field (403 in prod); sweeps use signup_started_at."""
# contract-test-file: infrastructure
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "backend/core/api/app/tasks/email_tasks"


def test_sweeps_do_not_request_date_created():
    for name in ("daily_notification_dispatcher.py", "password_security_reminder_email_task.py"):
        assert "date_created" not in (ROOT / name).read_text(), name
