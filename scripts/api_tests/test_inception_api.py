#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Explicit live Inception smoke tests; run in the API container for Vault access."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.shared.providers.inception import InceptionClient, InceptionRequest, resolve_api_key  # noqa: E402


async def run(args):
    manager = None
    results = {}
    try:
        if not args.api_key:
            from backend.core.api.app.utils.secrets_manager import SecretsManager
            manager = SecretsManager()
            await manager.initialize()
        key = args.api_key or await resolve_api_key(manager)
        client = InceptionClient(key, timeout=30, max_retries=0)
        names = [args.test] if args.test else ["models", "completion", "stream"]
        for name in names:
            started = time.monotonic()
            try:
                if name == "models":
                    models = await client.models()
                    assert any(item.get("id") == "mercury-3" for item in models)
                else:
                    request = InceptionRequest(messages=[{"role": "user", "content": "Reply with exactly OK"}], max_completion_tokens=32, reasoning_effort="instant")
                    if name == "completion":
                        result = await client.complete(request)
                        assert result.choices and result.usage
                        assert result.choices[0].get("message", {}).get("content", "").strip() == "OK"
                    else:
                        events = [event async for event in client.stream(request)]
                        assert any(event.usage is not None for event in events)
                        content = "".join(choice.get("delta", {}).get("content") or "" for event in events for choice in event.choices)
                        assert content.strip() == "OK"
                results[name] = {"status": "pass", "duration": round(time.monotonic() - started, 3)}
            except Exception as exc:
                results[name] = {"status": "fail", "duration": round(time.monotonic() - started, 3), "error": type(exc).__name__}
            if not args.json:
                print(f"{results[name]['status'].upper()} {name} ({results[name]['duration']:.3f}s)")
        passed = sum(result["status"] == "pass" for result in results.values())
        if args.json:
            print(json.dumps({"passed": passed, "failed": len(results) - passed, "results": results}))
        else:
            print(f"Passed: {passed}/{len(results)}; failed: {len(results) - passed}")
        return 0 if passed == len(results) else 1
    finally:
        if manager is not None:
            await manager.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key")
    parser.add_argument("--test", choices=["models", "completion", "stream"])
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit structured results")
    args = parser.parse_args()
    if args.list:
        print("models: nonbilling model-list probe\ncompletion: paid minimal completion\nstream: paid usage-bearing SSE completion")
        return
    try:
        raise SystemExit(asyncio.run(run(args)))
    except Exception:
        print("FAIL Inception smoke test (details redacted)")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
