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


def test_scaffold_promotes_app_skill_use_embeds_into_assistant_message(tmp_path: Path) -> None:
    slug = "scaffold-app-skill-use-test"
    snake = "scaffold_app_skill_use_test"
    data_path = REPO_ROOT / "frontend/packages/ui/src/demo_chats/data/example_chats" / f"{slug}.ts"
    yaml_path = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/example_chats" / f"{snake}.yml"
    registry_path = REPO_ROOT / "frontend/packages/ui/src/demo_chats/exampleChatData.ts"
    original_registry = registry_path.read_text(encoding="utf-8")
    extracted = {
        "chat_id": "chat-source",
        "title": "Recipe chat",
        "summary": "Summary",
        "icon": "utensils",
        "category": "Cooking",
        "follow_up_suggestions": [],
        "messages": [
            {
                "id": "message-1",
                "role": "user",
                "content": "Find chickpea recipes",
                "created_at": 1780000000,
            },
            {
                "id": "message-2",
                "role": "assistant",
                "content": "Here are three recipes.",
                "created_at": 1780000010,
            },
        ],
        "embeds": [
            {
                "embed_id": "nutrition-parent-embed",
                "type": "app_skill_use",
                "content": "app_id: nutrition\nskill_id: search_recipes\nstatus: finished\nembed_id: nutrition-parent-embed\nquery: chickpea dinner\nprovider: Edamam",
                "status": "finished",
                "parent_embed_id": None,
                "embed_ids": [],
            }
        ],
    }
    source = tmp_path / "chat.json"
    source.write_text(json.dumps(extracted), encoding="utf-8")

    try:
        subprocess.run(
            [
                "node",
                str(SCRIPT),
                "--from-json",
                str(source),
                "--slug",
                slug,
                "--force",
            ],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        yaml_source = yaml_path.read_text(encoding="utf-8")
        assert '{"type":"app_skill_use","embed_id":"nutrition-parent-embed"' in yaml_source
        assert yaml_source.index('{"type":"app_skill_use"') < yaml_source.index("Here are three recipes.")
        assert 'app_skill_examples: ["nutrition.search_recipes"]' in data_path.read_text(encoding="utf-8")
    finally:
        registry_path.write_text(original_registry, encoding="utf-8")
        data_path.unlink(missing_ok=True)
        yaml_path.unlink(missing_ok=True)


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


def test_example_chat_audit_uses_parent_content_registry_keys() -> None:
    audit_script = REPO_ROOT / "scripts" / "audit_example_chats.py"
    spec = importlib.util.spec_from_file_location("audit_example_chats", audit_script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    catalog = module.load_content_catalog()

    assert catalog["code.application"]["registryKey"] == "code-application"
    assert catalog["code.application"]["frontendType"] == "code-application"
    assert catalog["code.application"]["backendType"] == "application"
    assert catalog["docs.document"]["registryKey"] == "docs-doc"
