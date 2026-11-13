# contract-test-file: tooling
"""Tests for code_map.py find: index cache, search, Jev cost cap, fallbacks and usage log.

No network and no container: Jev is replaced by fake runners. Run:
python3 -m pytest scripts/tests/test_code_locate.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import code_locate  # noqa: E402
import code_locate_jev  # noqa: E402
import code_map  # noqa: E402

FILES = {
    "backend/apps/videos/routing.py": '"""Decides whether a video is a generative clip or a composed video."""\n'
                                      "def route_video_request(prompt):\n    return 'clip'\n",
    "backend/apps/billing/invoice.py": '"""Invoice totals for credit purchases."""\ndef invoice_total(items):\n'
                                       "    return sum(items)\n",
    "frontend/packages/ui/src/services/voiceCall.ts": "// Voice call turns for the web client.\n"
                                                      "export function startVoiceCall() { return 1; }\n",
    "backend/tests/test_routing.py": "def test_route_video_request():\n    pass\n",
}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root.parent, "init", "-q", str(root))
    _git(root, "add", ".")
    _git(root, "-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "init")
    monkeypatch.setattr(code_locate, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("OPENMATES_CODE_LOCATE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OPENMATES_CODE_LOCATE_BLOCKLIST", str(tmp_path / "blocklist.txt"))
    return root


def test_tokenize_splits_identifiers_and_folds_plurals():
    assert code_locate.tokenize("startVoiceCall voice_calls the") == ["start", "voice", "call", "voice", "call"]


def test_index_skips_tests_and_reuses_cache_across_checkouts(repo, tmp_path, monkeypatch):
    rows = code_locate.load_index(repo)
    assert {r["path"] for r in rows} == {p for p in FILES if "/tests/" not in p}
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True)
    calls = []
    monkeypatch.setattr(code_locate, "analyze", lambda path: calls.append(path) or None)
    code_locate.load_index(clone)
    assert calls == [], "same blob hashes must come from the shared cache"
    (clone / "backend/apps/billing/invoice.py").write_text('"""Changed."""\n')
    code_locate.load_index(clone)
    assert [p.name for p in calls] == ["invoice.py"], "only the dirty file is re-read"


def test_search_ranks_the_named_area_first(repo):
    rows = code_locate.load_index(repo)
    ranked = code_locate.retrieve(code_locate.Retriever(rows), "videos: route a video request", 3)
    assert rows[ranked[0]]["path"] == "backend/apps/videos/routing.py"


def test_locate_uses_jev_scores_and_reports_confidence(repo):
    def fake(query, views):
        return {"scores": {v["path"]: (3.9 if "billing" in v["path"] else 0.5) for v in views},
                "input_tokens": 1000, "usd": 0.000042, "budget": {"spent_usd": 0.1, "cap_usd": 0.5}}
    result = code_locate.locate("invoice totals", repo, jev_score=fake)
    assert result["mode"] == "jev" and result["confidence"] == "high"
    assert result["files"][0]["path"] == "backend/apps/billing/invoice.py"
    assert "Confidence: high" in code_locate.format_result(result)


def test_locate_keeps_search_order_on_fallback(repo):
    result = code_locate.locate("route video request", repo, jev_score=lambda q, v: {"fallback": "daily Jev budget reached"})
    assert result["mode"] == "search" and result["reason"] == "daily Jev budget reached"
    assert result["files"][0]["path"] == "backend/apps/videos/routing.py"
    assert "local search only (daily Jev budget reached)" in code_locate.format_result(result)


def _views():
    return [{"path": "a.py", "summary": "", "symbols": [], "matching_lines": []},
            {"path": "b.py", "summary": "", "symbols": [], "matching_lines": []}]


def test_ledger_refuses_over_cap_and_resets_per_day(tmp_path):
    ledger = code_locate_jev.Ledger(tmp_path / "spend.json", 0.001)
    assert ledger.reserve(0.0006)["ok"]
    assert not ledger.reserve(0.0006)["ok"], "a second reservation would pass the cap"
    ledger.settle(0.0006, 0.0002)
    state = json.loads((tmp_path / "spend.json").read_text())
    assert state["spent_usd"] == pytest.approx(0.0002) and state["reserved_usd"] == 0 and state["skipped"] == 1
    state["day"] = "2000-01-01"
    (tmp_path / "spend.json").write_text(json.dumps(state))
    assert ledger.reserve(0.0009)["ok"], "a new UTC day starts from zero"


def test_unreadable_ledger_counts_as_cap_reached(tmp_path):
    (tmp_path / "spend.json").write_text("{broken")
    assert not code_locate_jev.Ledger(tmp_path / "spend.json", 1.0).reserve(0.0001)["ok"]


def test_score_maps_answers_and_settles_billed_tokens(repo, tmp_path):
    ledger = code_locate_jev.Ledger(tmp_path / "spend.json", 0.5)
    out = code_locate_jev.score("q", _views(), ledger=ledger, runner=lambda req, t: {
        "answers": {"c000": 3.0, "c001": 1.0}, "input_tokens": 10_000, "billed_input_tokens": 10_000})
    assert out["scores"] == {"a.py": 3.0, "b.py": 1.0}
    assert out["usd"] == pytest.approx(10_000 * code_locate_jev.PRICE_PER_TOKEN)
    assert json.loads((tmp_path / "spend.json").read_text())["spent_usd"] == pytest.approx(out["usd"])


def test_score_skips_runner_when_budget_is_spent(repo, tmp_path):
    ledger = code_locate_jev.Ledger(tmp_path / "spend.json", 0.0)
    called = []
    out = code_locate_jev.score("q", _views(), ledger=ledger, runner=lambda req, t: called.append(1))
    assert out["fallback"] == "daily Jev budget reached" and called == []


def test_score_failure_falls_back_and_charges_the_reservation(repo, tmp_path):
    ledger = code_locate_jev.Ledger(tmp_path / "spend.json", 0.5)

    def broken(req, timeout):
        raise subprocess.TimeoutExpired("docker", timeout)
    out = code_locate_jev.score("q", _views(), ledger=ledger, runner=broken)
    assert out["fallback"].startswith("Jev unavailable")
    assert json.loads((tmp_path / "spend.json").read_text())["spent_usd"] > 0, "unknown usage is charged"
    partial = code_locate_jev.score("q", _views(), ledger=ledger, runner=lambda r, t: {"answers": {"c000": 2.0}})
    assert partial["fallback"].startswith("Jev unavailable")


def test_blocklisted_word_never_reaches_jev(repo, tmp_path):
    (tmp_path / "blocklist.txt").write_text("# local\nzebrastripes\n")
    called = []
    out = code_locate_jev.score("fix the ZebraStripes search", _views(),
                                ledger=code_locate_jev.Ledger(tmp_path / "spend.json", 0.5),
                                runner=lambda req, t: called.append(1))
    assert "blocklisted" in out["fallback"] and called == []


def test_find_cli_prints_and_logs_usage(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    assert code_map.main(["find", "--no-jev", "voice", "call", "turns"]) == 0
    assert "frontend/packages/ui/src/services/voiceCall.ts" in capsys.readouterr().out
    entry = json.loads((tmp_path / "logs" / "usage.jsonl").read_text().splitlines()[-1])
    assert entry["mode"] == "search" and entry["query"] == "voice call turns"
    assert code_map.main(["find-report", "--days", "1"]) == 0
    assert "1 calls, 0 with Jev" in capsys.readouterr().out
