#!/usr/bin/env python3
"""
Safety-contract tests for deterministic stale-code detection.

The detector favors precision over recall: only narrow, analyzer-approved edits
may be deletion-ready. Dynamic framework contracts, public APIs, compatibility
code, generated files, and ambiguous symbols must be suppressed or review-only.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "find_dead_code.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_find_dead_code", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def items_for(report, *, code: str | None = None, subcategory: str | None = None):
    return [
        item
        for item in report.items
        if (code is None or item.code == code)
        and (subcategory is None or item.subcategory == subcategory)
    ]


def test_python_safe_import_is_deletion_ready_but_patch_alias_is_review_only(tmp_path: Path) -> None:
    module = load_module()
    write(tmp_path / "backend" / "safe.py", "from pathlib import PurePath\n")
    write(
        tmp_path / "backend" / "test_patch.py",
        "from unittest.mock import patch\n"
        "def exercise():\n"
        "    with patch('pkg.value') as mock_value:\n"
        "        return 1\n",
    )

    report = module.scan_repository(tmp_path, categories={"python"})

    safe = items_for(report, subcategory="unused_import")
    assert any(item.classification == "deletion_ready" for item in safe)
    alias = items_for(report, code="mock_value")
    assert len(alias) == 1
    assert alias[0].classification == "review_only"
    assert "binding" in " ".join(alias[0].evidence).lower()


def test_python_ruff_imports_in_protected_paths_or_external_modules_are_not_deletion_ready(tmp_path: Path) -> None:
    module = load_module()
    write(tmp_path / "backend" / "tests" / "test_unused.py", "from pathlib import PurePath\n")
    write(tmp_path / "backend" / "migrations" / "001_seed.py", "from pathlib import PurePath\n")
    write(tmp_path / "backend" / "alembic" / "versions" / "001_seed.py", "from pathlib import PurePath\n")
    write(tmp_path / "backend" / "fixtures" / "sample.py", "from pathlib import PurePath\n")
    write(tmp_path / "backend" / "routes" / "health.py", "from pathlib import PurePath\n")
    write(tmp_path / "backend" / "plugin.py", "from custom_plugin import register\n")

    report = module.scan_repository(tmp_path, categories={"python"})

    for path_fragment in ("/tests/", "/migrations/", "/alembic/", "/fixtures/", "/routes/"):
        protected = [item for item in report.items if path_fragment in f"/{item.file}"]
        assert protected
        assert all(item.classification != "deletion_ready" for item in protected)
    external = [item for item in report.items if item.code == "custom_plugin.register"]
    assert external[0].classification != "deletion_ready"
    assert any("side effect" in reason.lower() for reason in external[0].suppression_reasons)


def test_python_unused_functions_and_classes_are_review_only(tmp_path: Path) -> None:
    module = load_module()
    write(
        tmp_path / "backend" / "symbols.py",
        "def _abandoned_helper():\n"
        "    return 1\n\n"
        "class _AbandonedThing:\n"
        "    pass\n",
    )

    report = module.scan_repository(tmp_path, categories={"python"})

    assert items_for(report, code="_abandoned_helper")[0].classification == "review_only"
    assert items_for(report, code="_AbandonedThing")[0].classification == "review_only"


def test_python_public_test_and_script_entrypoints_are_not_reported_as_stale(tmp_path: Path) -> None:
    module = load_module()
    write(tmp_path / "backend" / "module.py", "def public_entrypoint():\n    return 1\n")
    write(tmp_path / "backend" / "tests" / "test_flow.py", "def test_public_flow():\n    assert True\n")
    write(tmp_path / "backend" / "scripts" / "runner.py", "def main():\n    return 0\n")

    report = module.scan_repository(tmp_path, categories={"python"})

    assert not items_for(report, code="public_entrypoint")
    assert not items_for(report, code="test_public_flow")
    assert not items_for(report, code="main")


def test_python_dynamic_and_public_contracts_are_not_deletion_ready(tmp_path: Path) -> None:
    module = load_module()
    write(
        tmp_path / "backend" / "contracts.py",
        "__all__ = ['PublicThing']\n\n"
        "@router.get('/health')\n"
        "def health_check():\n"
        "    return {}\n\n"
        "class PublicThing:\n"
        "    pass\n\n"
        "def compatibility_shim():\n"
        "    \"\"\"Kept for backward compatibility.\"\"\"\n"
        "    return None\n",
    )

    report = module.scan_repository(tmp_path, categories={"python"})

    assert not any(
        item.classification == "deletion_ready"
        for name in ("health_check", "PublicThing", "compatibility_shim")
        for item in items_for(report, code=name)
    )


def test_svelte_glob_and_metadata_components_are_suppressed(tmp_path: Path) -> None:
    module = load_module()
    component = write(
        tmp_path / "frontend" / "packages" / "ui" / "src" / "components" / "embeds" / "code" / "CodeDocsEmbedFullscreen.svelte",
        "<p>docs</p>\n",
    )
    write(
        tmp_path / "frontend" / "packages" / "ui" / "src" / "services" / "resolver.ts",
        "const modules = import.meta.glob('../components/embeds/**/*EmbedFullscreen.svelte');\n",
    )
    write(
        tmp_path / "backend" / "apps" / "code" / "app.yml",
        "embeds:\n  docs:\n    fullscreen_component: code/CodeDocsEmbedFullscreen.svelte\n",
    )

    classification, reasons = module.classify_svelte_file(tmp_path, component)

    assert classification == "suppressed"
    assert any("import.meta.glob" in reason for reason in reasons)
    assert any("metadata" in reason for reason in reasons)


def test_orphan_svelte_component_is_review_only_and_route_is_suppressed(tmp_path: Path) -> None:
    module = load_module()
    orphan = write(
        tmp_path / "frontend" / "packages" / "ui" / "src" / "components" / "OrphanPanel.svelte",
        "<p>orphan</p>\n",
    )
    route = write(
        tmp_path / "frontend" / "apps" / "web_app" / "src" / "routes" / "+page.svelte",
        "<p>route</p>\n",
    )

    assert module.classify_svelte_file(tmp_path, orphan)[0] == "review_only"
    assert module.classify_svelte_file(tmp_path, route)[0] == "suppressed"


def test_typescript_unused_export_is_review_only_and_compatibility_is_suppressed(tmp_path: Path) -> None:
    module = load_module()
    write(
        tmp_path / "frontend" / "packages" / "ui" / "src" / "private.ts",
        "export function orphanExport() { return 1; }\n"
        "/** Kept for backward compatibility. */\n"
        "export function legacyExport() { return 2; }\n",
    )

    report = module.scan_repository(tmp_path, categories={"typescript"})

    assert items_for(report, code="orphanExport")[0].classification == "review_only"
    assert items_for(report, code="legacyExport")[0].classification == "suppressed"


def test_css_dynamic_class_families_are_suppressed_and_other_css_is_review_only(tmp_path: Path) -> None:
    module = load_module()
    css = write(
        tmp_path / "frontend" / "packages" / "ui" / "src" / "styles" / "icons.css",
        ".app-math { color: red; }\n"
        ".provider-openai { color: blue; }\n"
        ".old-static-rule { color: green; }\n",
    )
    write(
        tmp_path / "frontend" / "packages" / "ui" / "src" / "Icon.svelte",
        '<span class="app-{appId} provider-{providerId}"></span>\n',
    )

    report = module.scan_repository(tmp_path, categories={"css"})

    assert items_for(report, code=".app-math")[0].classification == "suppressed"
    assert items_for(report, code=".provider-openai")[0].classification == "suppressed"
    assert items_for(report, code=".old-static-rule")[0].classification == "review_only"
    assert css.exists()


def test_current_repository_dynamic_regressions_are_not_deletion_ready() -> None:
    module = load_module()
    calendar = ROOT / "frontend/packages/ui/src/components/embeds/calendar/CalendarActionEmbedFullscreen.svelte"
    docs = ROOT / "frontend/packages/ui/src/components/embeds/code/CodeGetDocsEmbedFullscreen.svelte"

    for path in (calendar, docs):
        classification, reasons = module.classify_svelte_file(ROOT, path)
        assert classification == "suppressed"
        assert any("import.meta.glob" in reason or "metadata" in reason for reason in reasons)

    classification, reasons = module.classify_css_class(ROOT, "provider-openai")
    assert classification == "suppressed"
    assert any("dynamic" in reason.lower() for reason in reasons)


def test_fingerprint_is_deterministic_and_changes_with_location() -> None:
    module = load_module()
    first = module.stable_fingerprint("python", "unused_function", "backend/a.py", 10, "unused")
    repeated = module.stable_fingerprint("python", "unused_function", "backend/a.py", 10, "unused")
    moved = module.stable_fingerprint("python", "unused_function", "backend/a.py", 11, "unused")

    assert first == repeated
    assert first != moved
    assert len(first) == 64


def test_report_order_is_deterministic(tmp_path: Path) -> None:
    module = load_module()
    write(tmp_path / "backend" / "z.py", "from pathlib import PurePath\n")
    write(tmp_path / "backend" / "a.py", "from pathlib import PurePosixPath\n")

    first = module.scan_repository(tmp_path, categories={"python"}).to_dict()
    second = module.scan_repository(tmp_path, categories={"python"}).to_dict()

    assert first == second
    assert [item["file"] for item in first["items"]] == sorted(item["file"] for item in first["items"])


def test_missing_required_analyzer_fails_closed(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    write(tmp_path / "backend" / "safe.py", "from pathlib import PurePath\n")
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    report = module.scan_repository(tmp_path, categories={"python"})

    assert report.status == "error"
    assert report.items == []
    assert "ruff" in report.errors[0].lower()
