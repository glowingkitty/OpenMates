# contract-test-file: tooling
"""Tests for scripts/feature_overview.py (unified feature overview and its drift check)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import feature_overview as fo  # noqa: E402 - needs the sys.path entry above

SURFACES_OK = {"web": "implemented", "apple": "unverified", "cli": "not_planned", "tui": "not_planned",
               "rest_api": "implemented", "sdk_npm": "not_planned", "sdk_pypi": "not_planned"}
WEB_SPEC = "frontend/apps/web_app/tests/chat-flow.spec.ts"


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Minimal repository: one Specification, one app, one product feature, tests and config."""
    shutil.copytree(REPO / "backend/core/api/app/services", tmp_path / "backend/core/api/app/services",
                    ignore=lambda _d, names: [n for n in names if n != "feature_availability_service.py"])
    for package in ("backend", "backend/core", "backend/core/api", "backend/core/api/app", "backend/core/api/app/services"):
        (tmp_path / package / "__init__.py").touch()
    _write(tmp_path / "specifications/features/chats/specification.yml",
           {"id": "feature.chats", "status": "draft", "title": "Chats", "summary": "Chats sync. More."})
    _write(tmp_path / "backend/apps/weather/app.yml", {"name_translation_key": "apps.weather", "skills": []})
    _write(tmp_path / "frontend/packages/ui/src/i18n/sources/apps.yml", {"weather": {"en": "Weather"}})
    _write(tmp_path / "frontend/packages/ui/src/data/product_features.yml", {"features": [{"id": "trusted-quotes"}]})
    _write(tmp_path / "backend/config/backend_config.yml", {"feature_overrides": {"disabled": ["app:weather"]}})
    _write(tmp_path / "backend/config/backend_config.dev.yml", {"feature_overrides": {}})
    _write(tmp_path / "frontend/apps/web_app/tests/chat-flow.spec.ts", "// test\n")
    _write(tmp_path / "frontend/apps/web_app/tests/skill-weather-forecast.spec.ts", "// test\n")
    _write(tmp_path / "specifications/generated/assertion-index.yml", {"assertions": {
        "chats.send.a": {"specification": "feature.chats@1", "direct_tests": [
            {"path": WEB_SPEC, "name": "sends a message", "surface": "gui.web"},
            {"path": "backend/tests/test_chats.py", "name": "test_send", "surface": "rest_api"},
        ], "supporting_tests": []},
        "chats.sync.b": {"specification": "feature.chats@1", "direct_tests": [
            {"path": WEB_SPEC, "name": "${device} syncs", "surface": "gui.web"},
        ], "supporting_tests": []}}})
    _write(tmp_path / "specifications/generated/registry.yml", {"assertions": {
        "chats.send.a": {"specification_id": "feature.chats", "required_applies_to": ["gui.web", "rest_api", "gui.apple"]},
        "chats.sync.b": {"specification_id": "feature.chats", "required_applies_to": ["gui.web", "gui.apple"]},
    }})
    _write(tmp_path / "specifications/test-results.yml", {"schema_version": 1, "as_of": "2026-11-13", "tests": {
        WEB_SPEC: {"result": "passed", "date": "2026-11-13", "commit": "abc", "job": "j1"},
    }})
    _write(tmp_path / "specifications/features.yml", {"schema_version": 1, "features": [
        {"id": "chats", "name": "Chats", "kind": "core", "description": "Chats sync.",
         "specifications": ["feature.chats"], "product_features": ["trusted-quotes"], "release": "v0.5.0-alpha",
         "surfaces": dict(SURFACES_OK),
         "subfeatures": [{"id": "sending", "name": "Sending", "assertions": ["chats.send.*"]}]},
        {"id": "weather", "name": "Weather", "kind": "app", "description": "Forecasts.", "specifications": [],
         "apps": ["weather"], "release": "unreleased", "surfaces": dict(SURFACES_OK, rest_api="unverified"),
         "key_tests": {"web": ["frontend/apps/web_app/tests/skill-weather-forecast.spec.ts"]}},
    ]})
    sys.modules.pop("backend.core.api.app.services.feature_availability_service", None)
    for name in [m for m in sys.modules if m == "backend" or m.startswith("backend.")]:
        sys.modules.pop(name)
    sys.path.insert(0, str(tmp_path))
    fo.spec_tests.cache_clear()
    yield tmp_path
    sys.path.remove(str(tmp_path))
    for name in [m for m in sys.modules if m == "backend" or m.startswith("backend.")]:
        sys.modules.pop(name)
    fo.spec_tests.cache_clear()


def _edit_manual(repo: Path, change) -> None:
    path = repo / "specifications/features.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data["features"])
    _write(path, data)
    fo.spec_tests.cache_clear()


def _view(repo: Path) -> dict:
    fo.write_outputs(repo)
    return yaml.safe_load((repo / fo.GENERATED_YML).read_text(encoding="utf-8"))


def _set_result(repo: Path, path: str, **data) -> None:
    snapshot = yaml.safe_load((repo / "specifications/test-results.yml").read_text(encoding="utf-8"))
    snapshot["tests"][path] = {"date": "2026-11-14", "commit": "def", "job": "j2", **data}
    _write(repo / "specifications/test-results.yml", snapshot)


def test_valid_overview_generates_view_and_passes_check(repo: Path) -> None:
    assert fo.validate(repo) == []
    assert set(fo.write_outputs(repo)) == set(fo.GENERATED_PATHS)
    assert fo.drift(repo) == []
    view = _view(repo)
    chats, weather = view["features"]
    assert view["results_as_of"] == "2026-11-13"
    assert chats["surfaces"]["web"]["e2e_tests"] == [WEB_SPEC]
    assert chats["surfaces"]["rest_api"]["key_unit_tests"] == ["backend/tests/test_chats.py"]
    assert chats["flags"] == {"ids": [], "dev": "no_flag", "prod": "no_flag"}
    assert weather["flags"] == {"ids": ["app:weather"], "dev": "enabled", "prod": "disabled"}
    assert "| [Chats](#chats) | **live** 2/2" in (repo / fo.GENERATED_MD).read_text(encoding="utf-8")


def test_cells_derive_from_assertions_tests_and_results(repo: Path) -> None:
    chats = _view(repo)["features"][0]
    web, rest, apple = (chats["surfaces"][s] for s in ("web", "rest_api", "apple"))
    assert web["status"] == "live" and web["source"] == "tests" and web["assertions"]["passing"] == 2
    assert rest["status"] == "not_run" and rest["assertions"] == {"passing": 0, "failing": 0, "not_run": 1, "missing": 0, "counted": 1}
    # Required on Apple but no Apple test: the cell keeps the human intent and counts the gap.
    assert apple["status"] == "unverified" and apple["source"] == "intent" and apple["assertions"]["missing"] == 2
    assert chats["subfeatures"][0]["assertion_ids"] == ["chats.send.a"]
    assert chats["subfeatures"][0]["surfaces"]["web"]["status"] == "live"


def test_failed_case_fails_only_its_declared_assertion(repo: Path) -> None:
    _set_result(repo, WEB_SPEC, result="failed", failed=["phone syncs"])
    web = _view(repo)["features"][0]["surfaces"]["web"]
    assert web["status"] == "failing" and web["assertions"]["passing"] == 1 and web["assertions"]["failing"] == 1
    assert web["failing_tests"] == [f"{WEB_SPEC} › ${{device}} syncs"]
    _set_result(repo, WEB_SPEC, result="failed", failed=["an unrelated case"])
    assert _view(repo)["features"][0]["surfaces"]["web"]["status"] == "live"


def test_gaps_lists_failing_before_missing(repo: Path) -> None:
    _set_result(repo, WEB_SPEC, result="failed", failed=["sends a message"])
    view = _view(repo)
    rows = fo.gaps(view, "web", fo.KINDS)
    assert [(r["name"], r["status"]) for r in rows][:2] == [("Chats", "failing"), ("Chats › Sending", "failing")]
    apple = fo.gaps(view, "apple", fo.KINDS)
    assert {r["name"] for r in apple} >= {"Chats", "Chats › Sending"}
    assert "Gaps on apple" in fo.render_gaps(apple, "apple", view["results_as_of"])


def test_stale_generated_view_is_reported(repo: Path) -> None:
    fo.write_outputs(repo)
    _edit_manual(repo, lambda features: features[0].update(description="Changed."))
    assert fo.drift(repo) and "stale" in fo.drift(repo)[0]


def test_specification_and_app_without_entry_fail(repo: Path) -> None:
    _write(repo / "specifications/features/tasks/specification.yml", {"id": "feature.tasks", "status": "draft"})
    _write(repo / "backend/apps/maps/app.yml", {})
    errors = fo.validate(repo)
    assert any("'feature.tasks' has no entry" in e for e in errors)
    assert any("app 'maps' has no entry" in e for e in errors)


def test_missing_references_fail(repo: Path) -> None:
    def change(features):
        features[0]["specifications"].append("feature.nope")
        features[1]["key_tests"]["web"].append("frontend/apps/web_app/tests/gone.spec.ts")
        features[1]["flags"] = ["platform:nope"]
    _edit_manual(repo, change)
    errors = "\n".join(fo.validate(repo))
    assert "'feature.nope' does not exist" in errors
    assert "gone.spec.ts' does not exist" in errors
    assert "'platform:nope' is not defined" in errors


def test_derived_values_and_bad_subfeatures_are_rejected(repo: Path) -> None:
    def change(features):
        features[0]["surfaces"]["cli"] = "tested"
        features[0]["subfeatures"].append({"id": "nope", "name": "Nope", "assertions": ["chats.unknown.*"]})
    _edit_manual(repo, change)
    errors = "\n".join(fo.validate(repo))
    assert "cli status 'tested'" in errors and "derived from tests" in errors
    assert "'chats.unknown.*' matches no assertion" in errors


def test_unlinked_product_feature_and_bad_values_fail(repo: Path) -> None:
    def change(features):
        features[0]["product_features"] = []
        features[0]["release"] = "soon"
        features[0]["surfaces"]["web"] = "done"
        del features[0]["surfaces"]["tui"]
    _edit_manual(repo, change)
    errors = "\n".join(fo.validate(repo))
    assert "'trusted-quotes'" in errors and "not linked" in errors
    assert "release must be" in errors
    assert "web status 'done'" in errors
    assert "surface 'tui' is missing" in errors


def test_classify_test_paths() -> None:
    assert fo.classify_test("frontend/apps/web_app/tests/cli-tui-startup.spec.ts", "cli") == ("tui", "e2e")
    assert fo.classify_test("frontend/apps/web_app/tests/cli-images.spec.ts", "gui.web") == ("cli", "e2e")
    assert fo.classify_test("frontend/apps/web_app/tests/chat.spec.ts", "gui.web") == ("web", "e2e")
    assert fo.classify_test("apple/OpenMatesUITests/ChatFlowUITests.swift", "gui.apple") == ("apple", "e2e")
    assert fo.classify_test("apple/OpenMatesWatchUITests/WatchChatLayoutUITests.swift", "gui.apple") == ("watchos", "e2e")
    assert fo.classify_test("apple/OpenMatesTests/WatchChatRuntimeTests.swift", "gui.apple") == ("watchos", "unit")
    assert fo.classify_test("packages/openmates-python/tests/test_x.py", "sdks.pip") == ("sdk_pypi", "unit")
    assert fo.classify_test("scripts/tests/test_x.py", "tooling") is None


def test_suggest_stub_uses_evidence(repo: Path) -> None:
    stub = fo.suggest_entry(repo, "feature.chats")
    assert stub["surfaces"]["web"] == "implemented"
    assert stub["surfaces"]["rest_api"] == "implemented"
    assert fo.suggest_entry(repo, "app:weather")["name"] == "Weather"


def test_repository_feature_overview_is_valid() -> None:
    fo.spec_tests.cache_clear()
    assert fo.validate(REPO) == []


def test_refresh_results_reads_validated_receipts(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    import json
    import sqlite3

    import feature_overview_results as results

    stores = tmp_path_factory.mktemp("stores")
    _write(repo / "apple/OpenMatesTests/ChatTests.swift", "final class ChatTests: XCTestCase {}\n")
    _write(repo / "backend/tests/test_chats.py", "def test_send(): pass\n")
    (stores / "logs/ci-coordinator").mkdir(parents=True)
    jobs = [
        ("e2e1", "c" * 40, "1", "e2e", "failure", 1_795_000_000),
        ("py1", "d" * 40, "2", "pytest", "failure", 1_795_000_100),
        ("ap1", "e" * 40, "3", "apple-unit", "failure", 1_795_000_200),
        ("bad1", "f" * 40, "4", "e2e", "success", 1_795_000_300),  # receipt for another commit: ignored
    ]
    with sqlite3.connect(stores / "logs/ci-coordinator/queue.sqlite3") as db:
        db.execute("CREATE TABLE jobs (id TEXT, source TEXT, run_id TEXT, mode TEXT, state TEXT, created REAL)")
        db.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)", jobs)
    reports = {
        "e2e1": [{"spec": "chat-flow.spec.ts", "exit_code": 1, "coverage_scope": "full-spec",
                  "stats": {"expected": 1, "unexpected": 1, "skipped": 0, "flaky": 0}}],
        "py1": [{"suite": "pytest", "exit_code": 1, "selection_mode": "focused", "selected_tests": ["backend/tests/test_chats.py"],
                 "failed_tests": ["tests/test_chats.py::test_send[x]"]}],
        "ap1": [], "bad1": [{"spec": "chat-flow.spec.ts", "exit_code": 0, "coverage_scope": "full-spec",
                             "stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}}],
    }
    for job_id, source, run_id, *_ in jobs:
        receipt = {"id": job_id, "source_commit": source if job_id != "bad1" else "0" * 40, "run_id": run_id,
                   "report": {"results": reports[job_id]}}
        _write(stores / f"test-results/ci-runs/{job_id}/receipt.json", json.dumps(receipt))
    _write(stores / "test-results/ci-runs/e2e1/subject/test-results/ci-spec-0.json", json.dumps({"suites": [{"specs": [
        {"file": "chat-flow.spec.ts", "title": "phone syncs", "tests": [{"results": [{"status": "failed"}]}]},
        {"file": "chat-flow.spec.ts", "title": "sends a message", "tests": [{"results": [{"status": "passed"}]}]},
    ]}]}))
    _write(stores / "test-results/ci-runs/ap1/apple-unit/rows/xcodebuild-test-openmatestests.log",
           "Test Case '-[OpenMatesTests.ChatTests testA]' passed (0.1 seconds).\n"
           "Test Case '-[OpenMatesTests.ChatTests testB]' failed (0.1 seconds).\n")
    counts = results.refresh(repo, stores)
    tests = results.load_snapshot(repo)["tests"]
    assert tests[WEB_SPEC]["result"] == "failed" and tests[WEB_SPEC]["failed"] == ["phone syncs"]
    assert tests[WEB_SPEC]["commit"] == "c" * 10
    assert tests["backend/tests/test_chats.py"] == {"result": "failed", "date": "2026-11-18", "commit": "d" * 10,
                                                   "job": "py1", "failed": ["test_send"]}
    assert tests["apple/OpenMatesTests/ChatTests.swift"]["failed"] == ["testB"]
    assert counts["failed"] == 3
