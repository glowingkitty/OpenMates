"""Live-backend Python driver for the cross-language API-key SDK harness.

Used by frontend/apps/web_app/tests/sdk-live-work-crud.spec.ts. Reads one
bounded JSON batch of public ``openmates`` SDK operations on stdin, runs them in
order against the real isolated backend with the explicit API key from the
environment and prints one JSON result per operation. Mirrors
packages/openmates-rust/examples/sdk-live-work-conformance.rs and
sdk-live-work.mjs; never reads CLI state.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from openmates import OpenMates, OpenMatesApiError
from openmates.sdk import OpenMatesConfigError

MAX_BATCH_BYTES = 1024 * 1024


def error_class(error: Exception) -> str:
    """Same stable classes as the Rust and npm drivers."""
    if isinstance(error, OpenMatesApiError):
        status = error.status_code
        if status in (404, 410):
            return "not_found"
        if status == 401:
            return "unauthorized"
        if status == 403:
            return "forbidden"
        if status == 409:
            return "conflict"
        if status in (400, 422):
            return "invalid"
        return f"http_{status}"
    if isinstance(error, OpenMatesConfigError):
        return "invalid"
    raise error


def run(client: OpenMates, op: dict[str, Any]) -> Any:
    key = f"{op['family']}.{op['op']}"
    payload = op.get("input") or {}
    if key == "probe.chats":
        return {"count": len(client.chats.list(limit=1))}
    if key == "projects.create":
        return client.projects.create(payload, personal=True)
    if key == "projects.show":
        return client.projects.show(op["id"], personal=True)
    if key == "projects.list":
        return client.projects.list(personal=True)
    if key == "projects.update":
        return client.projects.update(op["id"], payload, personal=True)
    if key == "projects.delete":
        return client.projects.delete(op["id"], confirmed=True, personal=True)
    if key == "tasks.create":
        return client.tasks.create(payload)
    if key == "tasks.show":
        return client.tasks.show(op["id"])
    if key == "tasks.list":
        return client.tasks.list()
    if key == "tasks.update":
        return client.tasks.update(op["id"], payload)
    if key == "tasks.delete":
        return client.tasks.delete(op["id"], confirmed=True)
    if key == "plans.create":
        return client.plans.create(payload)
    if key == "plans.show":
        return client.plans.show(op["id"])
    if key == "plans.list":
        return client.plans.list()
    if key == "plans.update":
        return client.plans.update(op["id"], payload)
    if key == "plans.delete":
        return client.plans.delete(op["id"], confirmed=True)
    if key == "history.list":
        return client.history.list(object_type=payload.get("object_type"), object_id=payload.get("object_id"), limit=payload.get("limit"))
    if key == "docs.list":
        return client.docs.list()
    raise ValueError(f"unsupported live operation {key}")


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_BATCH_BYTES + 1)
    if len(raw) > MAX_BATCH_BYTES:
        raise ValueError("batch bound")
    batch = json.loads(raw)
    client = OpenMates(
        api_key=os.environ["OPENMATES_API_KEY"],
        api_url=os.environ["OPENMATES_API_URL"],
        device_id=os.environ["OPENMATES_DEVICE_ID"],
    )
    results = []
    for op in batch["operations"]:
        try:
            results.append({"ok": True, "value": run(client, op)})
        except (OpenMatesApiError, OpenMatesConfigError) as error:
            results.append({"ok": False, "error": error_class(error)})
        except (LookupError, ValueError, RuntimeError) as error:
            # Same as the npm driver: an untyped public-SDK failure is reported
            # as an error-semantics gap instead of aborting the whole batch.
            results.append({"ok": False, "error": "untyped", "detail": type(error).__name__})
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
