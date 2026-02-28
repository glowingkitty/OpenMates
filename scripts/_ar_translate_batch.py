#!/usr/bin/env python3
"""
Internal batch translation script — runs INSIDE the Docker api container.
Called by apply_ar_translations.py via docker cp + exec.

Reads /tmp/ar_input.json (list of {key, en}),
writes /tmp/ar_output.json (dict of key -> ar translation).
"""

import asyncio
import json
import sys
import logging

logging.basicConfig(level=logging.WARNING)
for noisy in ["httpx", "httpcore", "google"]:
    logging.getLogger(noisy).setLevel(logging.ERROR)

INPUT_FILE = "/tmp/ar_input.json"
OUTPUT_FILE = "/tmp/ar_output.json"
BATCH_SIZE = 30


async def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"[ar_translate] Loaded {len(items)} items", file=sys.stderr)

    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()

    all_results = {}

    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        print(f"[ar_translate] Batch {start}–{start+len(batch)-1}", file=sys.stderr)

        batch_props = {
            item["key"]: {
                "type": "string",
                "description": f"Arabic translation of: {item['en'][:80]}"
            }
            for item in batch
        }

        tool = {
            "type": "function",
            "function": {
                "name": "return_translations",
                "description": "Return Arabic (ar) translations for all provided UI strings.",
                "parameters": {
                    "type": "object",
                    "properties": batch_props,
                    "required": [item["key"] for item in batch]
                }
            }
        }

        keys_text = "\n".join(
            f'{i+1}. [{item["key"]}] {item["en"]}'
            for i, item in enumerate(batch)
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional UI translator. Translate each English UI string to Arabic (ar). "
                    "Rules:\n"
                    "- Preserve placeholders exactly: {count}, {mate_name}, {credits_amount}, etc.\n"
                    "- Keep brand names unchanged: OpenMates, Discord, GitHub, Signal, Instagram, etc.\n"
                    "- Keep technical terms unchanged: API, JWT, IBAN, JPEG, PNG, PWA.\n"
                    "- Use natural, clear Arabic suitable for a web application UI.\n"
                    "- For short labels (1-3 words), keep them concise."
                )
            },
            {
                "role": "user",
                "content": f"Translate these UI strings to Arabic:\n\n{keys_text}"
            }
        ]

        try:
            resp = await invoke_google_ai_studio_chat_completions(
                task_id=f"ar_batch_{start}",
                model_id="gemini-2.5-flash",
                messages=messages,
                secrets_manager=secrets_manager,
                tools=[tool],
                tool_choice="required",
                temperature=0.2,
                max_tokens=20000,
                stream=False
            )

            if resp.success and resp.tool_calls_made:
                for tc in resp.tool_calls_made:
                    if tc.function_name == "return_translations":
                        all_results.update(tc.function_arguments_parsed)
                        print(f"[ar_translate] Got {len(tc.function_arguments_parsed)} translations", file=sys.stderr)
            else:
                err = getattr(resp, "error_message", "no tool call")
                print(f"[ar_translate] Batch {start} failed: {err}", file=sys.stderr)

        except Exception as e:
            print(f"[ar_translate] Exception at batch {start}: {e}", file=sys.stderr)
            # Write partial results so far before dying
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)
            print(f"[ar_translate] Wrote {len(all_results)} partial results after exception", file=sys.stderr)
            raise

    await secrets_manager.aclose()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"[ar_translate] Wrote {len(all_results)} translations to {OUTPUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
