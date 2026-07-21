#!/usr/bin/env python3
"""Dev-server REST proof for the Code image-to-HTML app skill.

This script exercises the real public app-skill route and task polling contract
against https://api.dev.openmates.org by default. It intentionally uses only the
Python standard library so it can run from the repo checkout without extra
dependencies. Set OPENMATES_API_KEY to run the provider-backed happy path.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_API_URL = "https://api.dev.openmates.org"
TASK_POLL_INTERVAL_SECONDS = 5
TASK_POLL_TIMEOUT_SECONDS = 600

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
)


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def request_json(api_url: str, method: str, path: str, api_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, exc.read().decode("utf-8", errors="replace")) from exc


def run_invalid_image_url_check(api_url: str, api_key: str) -> None:
    try:
        response = request_json(
            api_url,
            "POST",
            "/v1/apps/code/skills/image_to_html",
            api_key,
            {"requests": [{"image_url": "https://example.com/mockup.png", "mime_type": "image/png"}]},
        )
    except ApiError as exc:
        if exc.status in {400, 422, 500} and "image_url" in exc.body:
            print("PASS invalid image_url was rejected before provider execution")
            return
        raise
    if response.get("success") is False and "image_url" in str(response.get("error") or response.get("detail") or ""):
        print("PASS invalid image_url was rejected before provider execution")
        return
    raise AssertionError("image_url request unexpectedly succeeded")


def poll_task(api_url: str, api_key: str, task_id: str) -> dict[str, Any]:
    deadline = time.time() + TASK_POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        status = request_json(api_url, "GET", f"/v1/tasks/{task_id}", api_key)
        state = status.get("status")
        print(f"Task {task_id}: {state}")
        if state == "completed":
            result = status.get("result")
            if not isinstance(result, dict):
                raise AssertionError("completed task did not include an object result")
            return result
        if state == "failed":
            raise AssertionError(f"task failed: {status.get('error')}")
        time.sleep(TASK_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"task {task_id} did not complete within {TASK_POLL_TIMEOUT_SECONDS}s")


def run_happy_path(api_url: str, api_key: str, max_correction_passes: int) -> None:
    payload = {
        "requests": [
            {
                "image_base64": base64.b64encode(PNG_1X1).decode("ascii"),
                "mime_type": "image/png",
                "filename": "one-pixel.png",
                "max_correction_passes": max_correction_passes,
            }
        ]
    }
    response = request_json(api_url, "POST", "/v1/apps/code/skills/image_to_html", api_key, payload)
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    task_id = data.get("task_id")
    embed_id = data.get("embed_id")
    if not isinstance(task_id, str) or not task_id:
        raise AssertionError(f"missing task_id in response: {json.dumps(response)[:500]}")
    if not isinstance(embed_id, str) or not embed_id:
        raise AssertionError(f"missing embed_id in response: {json.dumps(response)[:500]}")
    if response.get("credits_charged") not in {0, None}:
        raise AssertionError("initial async response should not charge actual credits")
    print(f"Dispatched task_id={task_id} embed_id={embed_id}")

    result = poll_task(api_url, api_key, task_id)
    html = result.get("html")
    usage = result.get("usage")
    if not isinstance(html, str) or "<html" not in html.lower():
        raise AssertionError("task result did not include generated HTML")
    if not isinstance(usage, dict) or int(usage.get("credits_charged") or 0) <= 0:
        raise AssertionError("task result did not include positive actual usage charge metadata")
    if result.get("embed_id") != embed_id:
        raise AssertionError("task result embed_id does not match dispatch response")
    print("PASS image_to_html REST happy path completed")
    print(json.dumps({"task_id": task_id, "embed_id": embed_id, "usage": usage}, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--api-key", default=os.getenv("OPENMATES_API_KEY"))
    parser.add_argument("--max-correction-passes", type=int, default=0)
    parser.add_argument("--invalid-only", action="store_true", help="Run only the cheap image_url rejection check")
    args = parser.parse_args()

    if not args.api_key:
        print("OPENMATES_API_KEY or --api-key is required", file=sys.stderr)
        return 2
    run_invalid_image_url_check(args.api_url, args.api_key)
    if not args.invalid_only:
        run_happy_path(args.api_url, args.api_key, args.max_correction_passes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
