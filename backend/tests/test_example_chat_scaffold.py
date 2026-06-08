"""Regression tests for example-chat scaffold tooling.

The scaffold command converts CLI-generated shared chats into frontend example
chat files. It must reject or normalize human category labels before they reach
the web app, because chat gradients only accept canonical category IDs.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "create-example-chat-from-share.mjs"


def test_scaffold_normalizes_human_category_label(tmp_path: Path) -> None:
    extracted = {
        "chat_id": "chat-source",
        "title": "Research chat",
        "summary": "Summary",
        "icon": "globe",
        "category": "Research",
        "follow_up_suggestions": [],
        "messages": [
            {
                "id": "message-1",
                "role": "user",
                "content": "Read https://example.com",
                "created_at": 1780000000,
            }
        ],
        "embeds": [],
    }
    source = tmp_path / "chat.json"
    source.write_text(json.dumps(extracted), encoding="utf-8")

    result = subprocess.run(
        [
            "node",
            str(SCRIPT),
            "--from-json",
            str(source),
            "--slug",
            "category-normalization-test",
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "category: general_knowledge" in result.stdout
