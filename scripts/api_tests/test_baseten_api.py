#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Non-billable Baseten credential/catalog readiness check (API container/Vault)."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.shared.providers.baseten import BasetenClient, resolve_api_key  # noqa: E402

MODEL_ID = "deepseek-ai/DeepSeek-V4.1-Flash-1017"


async def run(args):
    manager = None
    try:
        if not args.api_key:
            from backend.core.api.app.utils.secrets_manager import SecretsManager

            manager = SecretsManager()
            await manager.initialize()
        key = args.api_key or await resolve_api_key(manager)
        models = await BasetenClient(key, timeout=20, max_retries=0).models()
        available = any(row.get("id") == MODEL_ID for row in models)
        result = {
            "status": "pass" if available else "fail",
            "test": "models",
            "credential_configured": True,
            "model_available": available,
            "inference_requests": 0,
        }
    except Exception as exc:
        result = {
            "status": "fail",
            "test": "models",
            "error": type(exc).__name__,
            "inference_requests": 0,
        }
    finally:
        if manager is not None:
            await manager.aclose()
    if args.json:
        print(json.dumps(result))
    else:
        print(
            f"{result['status'].upper()} Baseten catalog readiness; inference requests: 0"
        )
    return 0 if result["status"] == "pass" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-key", help="Prefer Vault/environment; never commit credentials"
    )
    parser.add_argument("--test", choices=["models"], default="models")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.list:
        print("models: non-billable credential and pinned-model catalog readiness")
        return
    logging.disable(logging.CRITICAL)
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
