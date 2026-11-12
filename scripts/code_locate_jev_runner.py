"""Runs inside the api container: one Jev scoring request from stdin, result line on stdout.

Purpose: code_locate_jev.py pipes this file to `docker exec -i api python -c`, because the
TypeSafe key lives in Vault there. The key is fetched by JevDecisionClient and never printed.
Input JSON: {"state", "questions", "timeout"}. Output: one line
"CODE_LOCATE_RESULT {answers: {id: score}, input_tokens, billed_input_tokens}" or {"error"}.
Only the direct TypeSafe provider is used (no fallback provider with a different tariff).
"""

import asyncio
import json
import sys


async def main() -> dict:
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.providers.typesafe import DecisionProviderError, JevDecisionClient

    request = json.load(sys.stdin)
    accounting: list = []
    manager = SecretsManager()
    try:
        try:
            await manager.initialize()
        except (OSError, ValueError, RuntimeError):
            pass  # the client falls back to the environment key, as the product does
        client = JevDecisionClient(secrets_manager=manager, provider="typesafe",
                                   timeout_seconds=float(request.get("timeout", 10)), accounting=accounting)
        try:
            response = await client.evaluate(state=request["state"], questions=request["questions"])
            out = {"answers": {key: answer.score for key, answer in response.answers.items()},
                   "input_tokens": response.usage.input_tokens}
        except DecisionProviderError as exc:
            out = {"error": type(exc).__name__}
    finally:
        await manager.aclose()
    out["billed_input_tokens"] = sum(row.get("input_tokens") or 0 for row in accounting)
    return out


print("CODE_LOCATE_RESULT " + json.dumps(asyncio.run(main())))
