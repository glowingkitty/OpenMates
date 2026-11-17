# contract-test-file: tooling
"""Hourly disk size log (scripts/host_disk_usage.py): categories, nesting, growth, budgets."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_disk_usage as usage  # noqa: E402 - repo-local module, path set just above

GB = usage.GB


def _tree(tmp_path: Path) -> tuple[Path, dict[str, int]]:
    sizes = {"wt/agent-a": 10, "wt/agent-a/target": 7, "wt/agent-b": 3, "cache/openmates-rust-x": 4}
    for name in sizes:
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return tmp_path, {str(tmp_path / name): size * GB for name, size in sizes.items()}


def test_nested_paths_of_an_earlier_category_are_subtracted(tmp_path):
    root, sizes = _tree(tmp_path)
    cats = (usage.Category("rust", "", (f"{root}/wt/*/target", f"{root}/cache/openmates-rust-*"), 25 * GB),
            usage.Category("worktrees", "", (f"{root}/wt/*",), 15 * GB))
    measured = usage.measure_paths(cats, du=lambda path: sizes[path])
    assert measured["rust"]["bytes"] == 11 * GB
    assert measured["worktrees"]["bytes"] == 6 * GB  # 10 - 7 for agent-a, plus 3
    assert measured["rust"]["largest"][0] == [f"{root}/wt/agent-a/target", 7 * GB]


def test_excluded_paths_and_paths_inside_another_match_are_not_counted_twice(tmp_path):
    root, sizes = _tree(tmp_path)
    cats = (usage.Category("all", "", (f"{root}/wt/*", f"{root}/wt/*/target", f"{root}/cache/*"), None,
                           exclude=(f"{root}/cache/openmates-rust-x",)),)
    measured = usage.measure_paths(cats, du=lambda path: sizes[path])
    assert measured["all"]["bytes"] == 13 * GB


def test_parse_size_reads_docker_and_journal_units():
    assert usage.parse_size("9.493GB") == 9_493_000_000
    assert usage.parse_size("367.5MB") == 367_500_000
    assert usage.parse_size("0B") == 0
    assert usage.parse_size("797.9M") == int(797.9 * 1024**2)


def test_growth_compares_with_the_record_closest_to_24_hours_earlier():
    records = [{"ts": 0, "categories": {"rust": 10}}, {"ts": 80000, "categories": {"rust": 15}},
               {"ts": 86400 + 3600, "categories": {"rust": 30, "new": 2}}]
    assert usage.growth(records) == {"rust": 20, "new": 2}
    assert usage.growth(records[:1]) == {}


def test_append_keeps_the_retention_window(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "RETENTION_HOURS", 3)
    for index in range(5):
        usage.append(tmp_path, {"ts": index, "categories": {}})
    assert [row["ts"] for row in usage.history(tmp_path)] == [2, 3, 4]


def test_growth_summary_names_growers_and_categories_over_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "caps", lambda projects: {"rust": 25 * GB, "worktrees": 15 * GB})
    rows = [{"ts": 0, "categories": {"rust": 20 * GB, "worktrees": 16 * GB, "other": 5 * GB}},
            {"ts": 86400, "categories": {"rust": 26 * GB, "worktrees": 16 * GB, "other": 6 * GB}}]
    (tmp_path / "usage.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    text = usage.growth_summary(tmp_path, tmp_path)
    assert text.startswith("largest growers in 24 h: rust +6.0 GB (26.0 GB, cap 25 GB), other +1.0 GB (6.0 GB)")
    assert text.endswith("over budget: rust 26.0/25 GB, worktrees 16.0/15 GB")
    assert usage.growth_summary(tmp_path / "missing", tmp_path) == ""


def test_approved_caps_are_the_owner_decision():
    caps = usage.caps(Path("/nonexistent/projects"))
    assert caps == {"rust": 25 * GB, "ci_artifacts": 10 * GB, "scratchpads": 6 * GB, "worktrees": 15 * GB,
                    "docker_images": 20 * GB, "docker_logs": 1 * GB, "journal": 1 * GB}
