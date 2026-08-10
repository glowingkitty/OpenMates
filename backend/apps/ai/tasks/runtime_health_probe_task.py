# backend/apps/ai/tasks/runtime_health_probe_task.py
#
# Provider-free Celery probe for the host runtime verifier.
# It proves that the app_ai queue can execute and return a synthetic result
# without entering model selection, inference, persistence, or user-data paths.
# Spec: docs/specs/post-update-runtime-health-alerting/spec.yml.

import time
from typing import Any, Dict

from backend.core.api.app.tasks.celery_config import app


@app.task(name="runtime_health.worker_probe")
def runtime_health_worker_probe(probe_id: str) -> Dict[str, Any]:
    return {"probe_id": probe_id, "completed_at": int(time.time())}
