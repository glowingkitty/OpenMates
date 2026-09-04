#!/usr/bin/env python3
"""Send labeled dev runtime-health tests through each configured CLI channel.

Email and Discord reuse existing dev operations settings without printing their
destinations. Generic webhook delivery uses a temporary loopback HTTP receiver,
enabled only by the CLI's explicit development-fixture guard, and validates the
timestamp/event signature over the exact received bytes.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "frontend" / "packages" / "openmates-cli" / "dist" / "cli.js"


class SignedWebhookReceiver(BaseHTTPRequestHandler):
    secret = ""
    received: dict[str, Any] | None = None

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        timestamp = self.headers.get("X-OpenMates-Timestamp", "")
        event_id = self.headers.get("X-OpenMates-Event-Id", "")
        expected = "sha256=" + hmac.new(self.secret.encode(), f"{timestamp}.{event_id}.".encode() + body, sha256).hexdigest()
        signature_valid = hmac.compare_digest(expected, self.headers.get("X-OpenMates-Signature", ""))
        payload = json.loads(body)
        type(self).received = {
            "signature_valid": signature_valid,
            "event_id_present": bool(event_id),
            "timestamp_present": bool(timestamp),
            "kind": payload.get("kind"),
        }
        self.send_response(204 if signature_valid else 401)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run_cli(
    channel: str,
    extra_env: dict[str, str] | None = None,
    event_kind: str = "delivery_test",
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(extra_env or {})
    result = subprocess.run(
        [
            "node",
            str(CLI_PATH),
            "server",
            "notifications",
            "test",
            "--channel",
            channel,
            "--event-kind",
            event_kind,
            "--json",
            "--path",
            ".",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=45,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{channel} notification command returned invalid JSON") from exc
    if result.returncode != 0:
        raise RuntimeError(f"{channel} notification test failed")
    return payload


def test_webhook(event_kind: str = "delivery_test") -> dict[str, Any]:
    secret = secrets.token_urlsafe(32)
    SignedWebhookReceiver.secret = secret
    SignedWebhookReceiver.received = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), SignedWebhookReceiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        cli = run_cli(
            "webhook",
            {
                "SERVER_ENVIRONMENT": "development",
                "OPENMATES_RUNTIME_HEALTH_ALLOW_LOCAL_WEBHOOK_FIXTURE": "true",
                "OPENMATES_RUNTIME_HEALTH_WEBHOOK_URL": f"http://127.0.0.1:{port}/runtime-health",
                "OPENMATES_RUNTIME_HEALTH_WEBHOOK_SECRET": secret,
            },
            event_kind,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    received = SignedWebhookReceiver.received
    passed = bool(received and received["signature_valid"] and received["event_id_present"] and received["timestamp_present"] and received["kind"] == event_kind)
    return {"status": "passed" if passed else "failed", "cli": cli, "received": received}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["dev"], required=True)
    parser.add_argument("--channels", default="email,discord,webhook")
    parser.add_argument("--event-kind", choices=["delivery_test", "incident", "critical", "recovery"], default="delivery_test")
    args = parser.parse_args()
    channels = [channel.strip() for channel in args.channels.split(",") if channel.strip()]
    results: dict[str, Any] = {}
    for channel in channels:
        results[channel] = test_webhook(args.event_kind) if channel == "webhook" else run_cli(channel, event_kind=args.event_kind)
    passed = True
    for result in results.values():
        if result.get("status") == "passed":
            continue
        deliveries = result.get("deliveries", [])
        passed = passed and result.get("configured") is True and bool(deliveries)
        passed = passed and all(delivery.get("status") == "delivered" for delivery in deliveries)
    print(json.dumps({"status": "passed" if passed else "failed", "channels": results}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
