# backend/tests/test_import_live_mock_cache.py
# contract-test-file: infrastructure
#
# Validates transactional candidate-cache promotion used by live-mock recording.
# Every selected group must validate before canonical fixtures are replaced.
# Promotion stages copies and retains rollback backups until replacements succeed.

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_import_script():
    script = Path(__file__).resolve().parents[2] / "scripts" / "import_live_mock_cache.py"
    spec = importlib.util.spec_from_file_location("import_live_mock_cache", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_cache_file(root: Path, group: str, name: str, body: str) -> None:
    path = root / group / "llm__test-model" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fingerprint": name,
                "category": "llm/test-model",
                "group_id": group,
                "request": {"model": "test-model"},
                "response": {"body": body},
            }
        ),
        encoding="utf-8",
    )


# contract-test: direct surface=cli assertions=daily-ai-tests.cache.manual-transactional-promotion
def test_validation_failure_leaves_all_canonical_groups_untouched(tmp_path, monkeypatch) -> None:
    module = _load_import_script()
    source_root = tmp_path / "candidate"
    canonical_root = tmp_path / "canonical"
    monkeypatch.setattr(module, "CACHE_ROOT", canonical_root)
    _write_cache_file(canonical_root, "valid", "old", "canonical")
    _write_cache_file(source_root, "valid", "new", "candidate")
    invalid_path = source_root / "invalid" / "llm__test-model" / "broken.json"
    invalid_path.parent.mkdir(parents=True)
    invalid_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit, match="Invalid JSON"):
        module._validate_groups(source_root, ["valid", "invalid"])

    assert (canonical_root / "valid" / "llm__test-model" / "old.json").exists()
    assert not (canonical_root / "valid" / "llm__test-model" / "new.json").exists()


# contract-test: direct surface=cli assertions=daily-ai-tests.cache.manual-transactional-promotion
def test_promotion_replaces_group_only_after_staging_candidate(tmp_path, monkeypatch) -> None:
    module = _load_import_script()
    source_root = tmp_path / "candidate"
    canonical_root = tmp_path / "canonical"
    monkeypatch.setattr(module, "CACHE_ROOT", canonical_root)
    _write_cache_file(canonical_root, "search", "old", "canonical")
    _write_cache_file(source_root, "search", "new", "candidate")

    module._promote_groups(module._validate_groups(source_root, ["search"]))

    promoted = canonical_root / "search" / "llm__test-model"
    assert not (promoted / "old.json").exists()
    assert json.loads((promoted / "new.json").read_text(encoding="utf-8"))["response"]["body"] == "candidate"
    assert not list(canonical_root.glob(".search.*"))


# contract-test: direct surface=cli assertions=daily-ai-tests.cache.manual-transactional-promotion
def test_main_refuses_promotion_without_both_pass_receipts(tmp_path, monkeypatch) -> None:
    module = _load_import_script()
    source_root = tmp_path / "candidate"
    canonical_root = tmp_path / "canonical"
    monkeypatch.setattr(module, "CACHE_ROOT", canonical_root)
    _write_cache_file(source_root, "search", "new", "candidate")
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_live_mock_cache.py", str(source_root), "--group", "search"],
    )

    with pytest.raises(SystemExit, match="requires --passed-real-run"):
        module.main()
    assert not (canonical_root / "search").exists()
