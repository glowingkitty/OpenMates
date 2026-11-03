"""One Gemini Flash call, executed inside the `api` container (Vault holds the key).

Run as `docker exec -i api python -c <this file's text>`; reads {"prompt": str,
"json": bool} on stdin, prints the model text. Used by daily_meeting_briefing.py
to summarize Claude chats without spending the Claude subscription.
"""

import asyncio
import json
import sys
import urllib.request

from backend.core.api.app.utils.secrets_manager import SecretsManager

MODEL = "gemini-3.8-flash"


async def main() -> None:
    request = json.loads(sys.stdin.read())
    secrets = SecretsManager()
    await secrets.initialize()
    key = await secrets.get_secret("kv/data/providers/google_ai_studio", "api_key")
    body = {"contents": [{"role": "user", "parts": [{"text": request["prompt"]}]}]}
    if request.get("json"):
        body["generationConfig"] = {"responseMimeType": "application/json"}
    call = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    reply = json.loads(urllib.request.urlopen(call, timeout=300).read())
    parts = reply["candidates"][0]["content"]["parts"]
    print("".join(part.get("text", "") for part in parts if not part.get("thought")))


asyncio.run(main())
