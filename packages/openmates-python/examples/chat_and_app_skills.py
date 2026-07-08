#!/usr/bin/env python3
"""OpenMates Python SDK example: chats and app skills.

Run from the repository root or installed package environment:
  OPENMATES_API_KEY=sk-api-... PYTHONPATH=packages/openmates-python python3 packages/openmates-python/examples/chat_and_app_skills.py

This uses real API requests. It lists encrypted account chats, loads the first
chat when available, and runs a deterministic math app skill.
"""

from __future__ import annotations

import json
import os

from openmates import OpenMates


client = OpenMates(
    api_key=os.getenv("OPENMATES_API_KEY"),
    api_url=os.getenv("OPENMATES_API_URL", "https://api.openmates.org"),
)

chats = client.chats.list(limit=10)
first_chat = client.chats.load(str(chats[0]["id"])) if chats and chats[0].get("id") else None
calculation = client.apps.math.calculate({"title": "SDK example calculation", "expression": "3 + 4"})

print(json.dumps({
    "chats": [
        {
            "id": chat.get("id"),
            "title": chat.get("title"),
            "category": chat.get("category"),
        }
        for chat in chats
    ],
    "loadedChat": {
        "id": first_chat.get("chat", {}).get("id"),
        "messageCount": len(first_chat.get("messages", [])),
        "embedCount": len(first_chat.get("embeds", [])),
    } if isinstance(first_chat, dict) else None,
    "calculation": calculation,
}, indent=2))
