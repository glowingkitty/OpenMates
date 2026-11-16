# contract-test-file: infrastructure
from pathlib import Path


def test_digest_does_not_call_cacheservice_initialize():
    src = Path(__file__).resolve().parents[2] / "backend/core/api/app/tasks/email_tasks/webhook_rate_limit_digest_email_task.py"
    assert "cache_service.initialize()" not in src.read_text()
