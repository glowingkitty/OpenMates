"""Regression tests for example-chat scaffold tooling.

The scaffold command converts CLI-generated shared chats into frontend example
chat files. It must reject or normalize human category labels before they reach
the web app, because chat gradients only accept canonical category IDs.
"""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
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


def test_scaffold_normalizes_home_category_label(tmp_path: Path) -> None:
    extracted = {
        "chat_id": "chat-source",
        "title": "Apartment search chat",
        "summary": "Summary",
        "icon": "home",
        "category": "Home",
        "follow_up_suggestions": [],
        "messages": [
            {
                "id": "message-1",
                "role": "user",
                "content": "Find apartments in Berlin",
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
            "home-category-normalization-test",
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "category: general_knowledge" in result.stdout


def test_current_example_chats_pass_audit(tmp_path: Path) -> None:
    audit_script = REPO_ROOT / "scripts" / "audit_example_chats.py"
    spec = importlib.util.spec_from_file_location("audit_example_chats", audit_script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not module.REGISTRY_PATH.exists():
        registry_path = tmp_path / "embedRegistry.generated.ts"
        registry_path.write_text("", encoding="utf-8")
        module.REGISTRY_PATH = registry_path

    assert module.audit() == []
