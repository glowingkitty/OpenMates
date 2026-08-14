"""
Packaged command for generating and delivering an operational monitoring report.

The host CLI invokes this inside the API container so Directus, Prometheus,
Vault-backed email, and environment configuration stay on the private network.
Output is one JSON object with redacted delivery receipts.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from backend.core.api.app.tasks.operational_monitoring_tasks import generate_and_deliver_operational_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=["development", "production", "self_host"])
    parser.add_argument("--channels", default="email,discord")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    channels = {item.strip() for item in args.channels.split(",") if item.strip()}
    invalid = channels - {"email", "discord"}
    if invalid:
        parser.error(f"unsupported channels: {', '.join(sorted(invalid))}")
    result = asyncio.run(generate_and_deliver_operational_report(
        environment=args.environment,
        channels=channels,
        test=args.test,
    ))
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["delivery_state"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
