"""Regression: bank_transfer_expiry_task must be in TASK_CONFIG or beat dispatches an unregistered task."""
# contract-test-file: infrastructure
from backend.core.api.app.tasks.celery_config import TASK_CONFIG


def test_bank_transfer_expiry_module_registered_on_persistence():
    assert {"name": "persistence", "module": "backend.core.api.app.tasks.bank_transfer_expiry_task"} in TASK_CONFIG
