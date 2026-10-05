# contract-test-file: tooling
"""Check public synthetic lesson chips with real Jev inference.

Runs inside the api container with Vault-backed provider credentials.
Uses no account, chat history, learner data or saved memories.
Exercises a new arithmetic task after a solved task and a science check.
Prints only safe counts and whether answer-bearing chips were withheld.
Usage: docker exec api python /app/backend/scripts/test_learning_followups_real.py
"""

import asyncio
import json

from backend.apps.ai.processing.learning_followups import filter_learning_followups
from backend.core.api.app.utils.secrets_manager import SecretsManager


async def main():
    secrets = SecretsManager()
    await secrets.initialize()
    results = []
    try:
        cases = [
            (
                "arithmetic",
                "Your previous 7/10 is correct. Now try 1/4 + 2/5. What do you think?",
                [
                    "Calculate the decimal value of thirteen twentieths using division",
                    "Give me a small hint",
                ],
            ),
            (
                "science",
                "A water plant releases oxygen bubbles under a lamp. What happens to bubble production when the lamp is turned off, and why?",
                [
                    "Explain how oxygen is released during photosynthesis",
                    "Let me explain my prediction first",
                ],
            ),
        ]
        for name, assistant, candidates in cases:
            safe = await filter_learning_followups(
                candidates,
                assistant_response=assistant,
                user_message="Give me a fresh unsolved check.",
                message_history=[],
                teaching_context={"focus": {"phase_id": "independent_check"}},
                secrets_manager=secrets,
                model_id="typesafe/jev-1.13",
            )
            results.append(
                {
                    "case": name,
                    "safe_count": len(safe),
                    "spoiler_withheld": candidates[0] not in safe,
                }
            )
    finally:
        await secrets.aclose()
    passed = all(r["spoiler_withheld"] for r in results) and any(
        r["safe_count"] > 0 for r in results
    )
    print(json.dumps({"passed": passed, "results": results}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
