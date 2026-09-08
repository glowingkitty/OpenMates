# Shared ownership records for asynchronous app-skill jobs.
# The dispatcher records the authenticated owner before submitting paid work.
# Polling must not depend on each provider worker returning an owner field,
# especially when Celery stores an exception instead of a result dictionary.
# Records contain only a user hash and expire after the bounded job lifetime.
# See docs/architecture/apps/images.md for generated asset delivery.

import hashlib

import redis

TASK_OWNER_PREFIX = "app-skill-task-owner:"
# Task results expire after one hour; allow a day for queueing and execution.
TASK_OWNER_TTL_SECONDS = 24 * 60 * 60
REDIS_TIMEOUT_SECONDS = 2


def _client(broker_url: str):
    return redis.Redis.from_url(
        broker_url, socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS, decode_responses=True,
    )


def record_task_owner(task_id: str, user_id: str, broker_url: str) -> None:
    """Fail before dispatch if ownership cannot be durably bound."""
    owner = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    with _client(broker_url) as client:
        if not client.set(f"{TASK_OWNER_PREFIX}{task_id}", owner, ex=TASK_OWNER_TTL_SECONDS, nx=True):
            raise RuntimeError("Task ownership record already exists")


def read_task_owner(task_id: str, broker_url: str) -> str | None:
    """An unavailable store raises; it never authorizes an unverified caller."""
    with _client(broker_url) as client:
        return client.get(f"{TASK_OWNER_PREFIX}{task_id}")
