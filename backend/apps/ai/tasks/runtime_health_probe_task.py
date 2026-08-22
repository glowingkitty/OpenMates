# backend/apps/ai/tasks/runtime_health_probe_task.py
#
# Provider-free Celery probe for the host runtime verifier.
# It proves that the app_ai queue can execute and return a synthetic result
# without entering model selection, inference, persistence, or user-data paths.
# Spec: docs/specs/post-update-runtime-health-alerting/spec.yml.

import os
import time
from typing import Any, Dict

import redis

from backend.core.api.app.tasks.celery_config import app


@app.task(name="runtime_health.worker_probe")
def runtime_health_worker_probe(probe_id: str) -> Dict[str, Any]:
    return {"probe_id": probe_id, "completed_at": int(time.time())}


@app.task(name="runtime_health.chat_plumbing_probe")
def runtime_health_chat_plumbing_probe(probe_id: str) -> Dict[str, Any]:
    """Prove app_ai execution plus ephemeral Redis persistence and cleanup."""
    raw_url = os.getenv("DRAGONFLY_URL", "cache:6379")
    redis_url = raw_url if "://" in raw_url else f"redis://{raw_url}"
    client = redis.Redis.from_url(
        redis_url,
        password=os.getenv("DRAGONFLY_PASSWORD"),
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    key = f"runtime_health:chat_plumbing:{probe_id}"
    try:
        client.set(key, probe_id, ex=30)
        if client.get(key) != probe_id:
            raise RuntimeError("chat_plumbing_probe_mismatch")
    finally:
        client.delete(key)
        client.close()
    return {
        "probe_id": probe_id,
        "transport": "redis",
        "cleanup_status": "completed",
        "completed_at": int(time.time()),
    }
