#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the release intelligence changelog generator.

The fixtures are synthetic git-change records, not real product history. They
cover the deterministic contracts that must hold before any LLM prose or
newsletter automation is allowed to consume release artifacts.
"""

from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

_release_intelligence = importlib.import_module("release_intelligence")
CommitChange = _release_intelligence.CommitChange
build_monthly_artifact = _release_intelligence.build_monthly_artifact
build_monthly_llm_source = _release_intelligence.build_monthly_llm_source
build_daily_artifact = _release_intelligence.build_daily_artifact
build_daily_llm_source = _release_intelligence.build_daily_llm_source
build_weekly_discord_payload = _release_intelligence.build_weekly_discord_payload
build_weekly_artifact = _release_intelligence.build_weekly_artifact
build_weekly_llm_source = _release_intelligence.build_weekly_llm_source
dump_yaml = _release_intelligence.dump_yaml
load_daily_artifacts = _release_intelligence.load_daily_artifacts
load_weekly_artifacts = _release_intelligence.load_weekly_artifacts
llm_system_prompt = _release_intelligence.llm_system_prompt
normalize_summary = _release_intelligence.normalize_summary
newsletter_include_commits_from_source = _release_intelligence.newsletter_include_commits_from_source


def test_daily_artifact_groups_changes_and_gates_newsletter_readiness() -> None:
    commits = [
        CommitChange(
            sha="1111111111111111111111111111111111111111",
            short_sha="1111111",
            authored_at="2026-07-08T08:00:00+00:00",
            subject="feat(images): add transparent background exports",
            body="",
            changed_paths=["backend/apps/images/skills/generate.py", "frontend/packages/ui/src/components/embeds/ImageEmbed.svelte"],
            in_main=True,
            in_dev=True,
        ),
        CommitChange(
            sha="2222222222222222222222222222222222222222",
            short_sha="2222222",
            authored_at="2026-07-08T09:00:00+00:00",
            subject="fix(chat): repair duplicate message display",
            body="",
            changed_paths=["frontend/packages/ui/src/services/chatSyncService.ts"],
            in_main=False,
            in_dev=True,
        ),
        CommitChange(
            sha="3333333333333333333333333333333333333333",
            short_sha="3333333",
            authored_at="2026-07-08T10:00:00+00:00",
            subject="docs: clarify self-host setup",
            body="",
            changed_paths=["docs/self-hosting/setup.md"],
            in_main=True,
            in_dev=True,
        ),
    ]

    artifact = build_daily_artifact(
        commits=commits,
        report_date=date(2026, 7, 8),
        since="24 hours ago",
        from_ref=None,
        to_ref="HEAD",
        assume_released=False,
    )

    assert artifact["summary"]["total_commits"] == 3
    assert artifact["summary"]["newsletter_ready_items"] == 1
    assert artifact["summary"]["dev_only_items"] == 1

    feature = artifact["sections"]["features"][0]
    assert feature["newsletter_ready"] is True
    assert feature["release_status"] == "released_main"
    assert feature["user_facing"] is True

    fix = artifact["sections"]["bug_fixes"][0]
    assert fix["newsletter_ready"] is False
    assert fix["release_status"] == "dev_only"
    assert artifact["unreleased_progress"]["dev_only"][0]["commits"] == ["2222222"]

    docs = artifact["sections"]["docs"][0]
    assert docs["user_facing"] is False


def test_assume_released_is_explicit_override_for_smoke_runs() -> None:
    commits = [
        CommitChange(
            sha="4444444444444444444444444444444444444444",
            short_sha="4444444",
            authored_at="2026-07-08T11:00:00+00:00",
            subject="improve(files): make PDF previews clearer",
            body="",
            changed_paths=["frontend/packages/ui/src/components/embeds/PdfEmbed.svelte"],
            in_main=False,
            in_dev=True,
        )
    ]

    artifact = build_daily_artifact(
        commits=commits,
        report_date=date(2026, 7, 8),
        since="24 hours ago",
        from_ref=None,
        to_ref="HEAD",
        assume_released=True,
    )

    item = artifact["sections"]["improvements"][0]
    assert item["newsletter_ready"] is True
    assert item["release_status"] == "released_override"
    assert artifact["marketing_candidates"]["newsletter"][0]["commits"] == ["4444444"]


def test_disabled_related_features_are_not_newsletter_ready_even_on_main() -> None:
    commits = [
        CommitChange(
            sha="5555555555555555555555555555555555555555",
            short_sha="5555555",
            authored_at="2026-07-08T12:00:00+00:00",
            subject="feat(watch): add reliable Apple Watch pairing",
            body="",
            changed_paths=["apple/OpenMatesWatch/Sources/WatchPairLoginView.swift"],
            in_main=True,
            in_dev=True,
        )
    ]

    artifact = build_daily_artifact(
        commits=commits,
        report_date=date(2026, 7, 8),
        since="24 hours ago",
        from_ref=None,
        to_ref="HEAD",
        assume_released=False,
    )

    item = artifact["sections"]["features"][0]
    assert item["release_status"] == "released_main"
    assert item["communication_status"] == "unreleased_feature"
    assert item["newsletter_ready"] is False
    assert item["related_features"] == [
        {
            "id": "platform:apple-watch",
            "kind": "platform",
            "default_enabled": False,
            "effective_enabled": False,
            "override": None,
            "parent_id": None,
            "source": "platform",
        }
    ]
    assert artifact["summary"]["newsletter_ready_items"] == 0
    assert artifact["marketing_candidates"]["newsletter"] == []
    assert artifact["marketing_candidates"]["social_or_video"][0]["communication_status"] == "unreleased_feature"


def test_disabled_ios_and_macos_features_are_not_newsletter_ready_even_on_main() -> None:
    commits = [
        CommitChange(
            sha="6666666666666666666666666666666666666666",
            short_sha="6666666",
            authored_at="2026-07-08T13:00:00+00:00",
            subject="feat(apple): add native composer parity",
            body="",
            changed_paths=["apple/OpenMates/Sources/Features/Chat/NativeComposerView.swift"],
            in_main=True,
            in_dev=True,
        )
    ]

    artifact = build_daily_artifact(
        commits=commits,
        report_date=date(2026, 7, 8),
        since="24 hours ago",
        from_ref=None,
        to_ref="HEAD",
        assume_released=False,
    )

    item = artifact["sections"]["features"][0]
    assert item["release_status"] == "released_main"
    assert item["communication_status"] == "unreleased_feature"
    assert item["newsletter_ready"] is False
    assert [feature["id"] for feature in item["related_features"]] == ["platform:ios", "platform:macos"]
    assert all(feature["effective_enabled"] is False for feature in item["related_features"])
    assert artifact["marketing_candidates"]["newsletter"] == []


def test_disabled_workflow_features_are_not_newsletter_ready_even_on_main() -> None:
    commits = [
        CommitChange(
            sha="7777777777777777777777777777777777777777",
            short_sha="7777777",
            authored_at="2026-07-08T14:00:00+00:00",
            subject="feat(workflows): add input sessions",
            body="",
            changed_paths=["backend/core/api/app/routes/workflows.py"],
            in_main=True,
            in_dev=True,
        )
    ]

    artifact = build_daily_artifact(
        commits=commits,
        report_date=date(2026, 7, 8),
        since="24 hours ago",
        from_ref=None,
        to_ref="HEAD",
        assume_released=False,
    )

    item = artifact["sections"]["features"][0]
    assert item["communication_status"] == "unreleased_feature"
    assert item["newsletter_ready"] is False
    assert [feature["id"] for feature in item["related_features"]] == ["app:workflows", "platform:workflows"]
    assert artifact["marketing_candidates"]["newsletter"] == []


def test_daily_llm_source_includes_disabled_feature_context() -> None:
    artifact = build_daily_artifact(
        commits=[],
        report_date=date(2026, 7, 8),
        since="24 hours ago",
        from_ref=None,
        to_ref="HEAD",
        assume_released=False,
    )

    source = build_daily_llm_source(artifact)
    disabled_ids = {feature["id"] for feature in source["feature_availability"]["disabled_features"]}

    assert {"platform:workflows", "platform:projects", "platform:tasks", "platform:plans", "platform:teams"} <= disabled_ids
    assert {"platform:ios", "platform:macos", "platform:apple-watch"} <= disabled_ids


def test_llm_prompt_requires_neutral_authorship_and_disabled_feature_exclusions() -> None:
    prompt = llm_system_prompt("weekly")

    assert 'Do not write "the team", "we", "our team"' in prompt
    assert "feature_availability.disabled_features" in prompt
    assert "Workflows, projects, tasks, plans, teams, iOS, macOS, and Apple Watch are unreleased" in prompt
    assert "For weekly summaries, be more extensive" in prompt


def test_yaml_output_round_trips_required_top_level_fields() -> None:
    artifact = build_daily_artifact(
        commits=[],
        report_date=date(2026, 7, 8),
        since="24 hours ago",
        from_ref=None,
        to_ref="HEAD",
        assume_released=False,
    )

    rendered = dump_yaml(artifact)
    parsed = yaml.safe_load(rendered)

    assert parsed["schema_version"] == 1
    assert parsed["cadence"] == "daily"
    assert parsed["date"] == "2026-07-08"
    assert parsed["sections"]["features"] == []
    assert parsed["sources"]["commits"] == []


def write_daily_artifact(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def minimal_daily(day: str, items: list[dict]) -> dict:
    sections = {section: [] for section in ["features", "bug_fixes", "improvements", "docs", "tests", "infrastructure", "internal", "other"]}
    for item in items:
        sections[item["section"]].append(item)
    return {
        "schema_version": 1,
        "cadence": "daily",
        "date": day,
        "generated_at": f"{day}T08:00:00+00:00",
        "summary": {
            "total_commits": len(items),
            "newsletter_ready_items": sum(1 for item in items if item.get("newsletter_ready")),
            "dev_only_items": sum(1 for item in items if item.get("release_status") == "dev_only"),
        },
        "sections": sections,
        "unreleased_progress": {
            "dev_only": [],
            "unknown_release_status": [],
            "feature_metadata_changed": [],
        },
        "marketing_candidates": {"newsletter": [], "social_or_video": []},
        "sources": {"commits": []},
    }


def test_weekly_rollup_groups_daily_items_and_preserves_dates(tmp_path: Path) -> None:
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    write_daily_artifact(
        daily_dir / "2026-07-06.yml",
        minimal_daily(
            "2026-07-06",
            [
                {
                    "title": "fix: restore anonymous chat after reload",
                    "section": "bug_fixes",
                    "commits": ["aaaaaaa"],
                    "changed_paths": ["frontend/packages/ui/src/components/ActiveChat.svelte"],
                    "release_status": "released_main",
                    "newsletter_ready": True,
                    "user_facing": True,
                }
            ],
        ),
    )
    write_daily_artifact(
        daily_dir / "2026-07-07.yml",
        minimal_daily(
            "2026-07-07",
            [
                {
                    "title": "fix: sync restored chat history on mount",
                    "section": "bug_fixes",
                    "commits": ["bbbbbbb"],
                    "changed_paths": ["frontend/packages/ui/src/components/ChatHistory.svelte"],
                    "release_status": "released_main",
                    "newsletter_ready": True,
                    "user_facing": True,
                },
                {
                    "title": "feat: link package listings from settings footer",
                    "section": "features",
                    "commits": ["ccccccc"],
                    "changed_paths": ["frontend/packages/ui/src/components/settings/SettingsFooter.svelte"],
                    "release_status": "dev_only",
                    "newsletter_ready": False,
                    "user_facing": True,
                },
            ],
        ),
    )

    daily_artifacts = load_daily_artifacts(daily_dir, date(2026, 7, 6), date(2026, 7, 12))
    weekly = build_weekly_artifact(
        daily_artifacts=daily_artifacts,
        week_start=date(2026, 7, 6),
        week_end=date(2026, 7, 12),
    )

    assert weekly["summary"]["daily_files"] == 2
    assert weekly["summary"]["newsletter_ready_items"] == 2
    assert weekly["summary"]["dev_only_items"] == 1

    chat_theme = next(theme for theme in weekly["themes"] if theme["theme"] == "chat")
    assert chat_theme["item_count"] == 2
    assert chat_theme["source_items"][0]["date"] == "2026-07-06"
    assert chat_theme["source_items"][1]["date"] == "2026-07-07"

    unreleased = weekly["unreleased_progress"]["dev_only"][0]
    assert unreleased["date"] == "2026-07-07"
    assert unreleased["title"] == "feat: link package listings from settings footer"


def test_weekly_yaml_output_round_trips(tmp_path: Path) -> None:
    weekly = build_weekly_artifact(
        daily_artifacts=[],
        week_start=date(2026, 7, 6),
        week_end=date(2026, 7, 12),
    )

    parsed = yaml.safe_load(dump_yaml(weekly))

    assert parsed["schema_version"] == 1
    assert parsed["cadence"] == "weekly"
    assert parsed["week_start"] == "2026-07-06"
    assert parsed["week_end"] == "2026-07-12"


def test_monthly_rollup_reads_weekly_artifacts_and_preserves_weeks(tmp_path: Path) -> None:
    weekly_dir = tmp_path / "weekly"
    weekly_dir.mkdir()
    weekly_payload = {
        "schema_version": 1,
        "cadence": "weekly",
        "week_start": "2026-07-06",
        "week_end": "2026-07-12",
        "summary": {"total_items": 1, "newsletter_ready_items": 1, "dev_only_items": 0},
        "feature_availability": {"disabled_features": [{"id": "platform:ios", "kind": "platform"}]},
        "themes": [
            {
                "theme": "cli_sdk",
                "source_items": [
                    {
                        "date": "2026-07-07",
                        "title": "feat: add CLI self-update commands",
                        "section": "features",
                        "commits": ["abc1234"],
                        "changed_paths": ["frontend/packages/openmates-cli/src/selfUpdate.ts"],
                        "release_status": "released_main",
                        "newsletter_ready": True,
                        "user_facing": True,
                    }
                ],
            }
        ],
        "marketing_candidates": {"newsletter": [{"date": "2026-07-07", "title": "feat: add CLI self-update commands", "commits": ["abc1234"]}], "social_or_video": []},
        "unreleased_progress": {"dev_only": [], "unknown_release_status": []},
        "llm_summary": {"overview": "CLI self-update shipped."},
    }
    write_daily_artifact(weekly_dir / "2026-W28.yml", weekly_payload)

    weekly_artifacts = load_weekly_artifacts(weekly_dir, date(2026, 7, 1), date(2026, 7, 31))
    monthly = build_monthly_artifact(
        weekly_artifacts=weekly_artifacts,
        month_start=date(2026, 7, 1),
        month_end=date(2026, 7, 31),
    )
    source = build_monthly_llm_source(monthly, weekly_artifacts)

    assert monthly["schema_version"] == 1
    assert monthly["cadence"] == "monthly"
    assert monthly["summary"]["weekly_files"] == 1
    assert monthly["marketing_candidates"]["newsletter"][0]["commits"] == ["abc1234"]
    assert source["weekly_summaries"][0]["week_start"] == "2026-07-06"
    assert source["weekly_summaries"][0]["llm_summary"]["overview"] == "CLI self-update shipped."


def test_weekly_discord_payload_includes_include_and_exclude_items() -> None:
    artifact = {
        "week_start": "2026-07-06",
        "week_end": "2026-07-12",
        "summary": {"total_items": 12, "newsletter_ready_items": 3, "dev_only_items": 2},
        "llm_summary": {
            "overview": "OpenMates improved CLI updates.",
            "newsletter_recommendation": {
                "include": [{"text": "CLI self-update", "evidence": {"commits": ["abc1234"]}}],
                "exclude": [{"text": "Apple Watch", "evidence": {"commits": ["def5678"]}}],
            },
            "validation_warnings": [],
        },
    }

    payload = build_weekly_discord_payload(artifact)
    description = payload["embeds"][0]["description"]

    assert "Weekly release intelligence" in payload["embeds"][0]["title"]
    assert "CLI self-update" in description
    assert "Apple Watch" in description


def test_release_intelligence_cron_wrapper_documents_all_modes() -> None:
    wrapper = (ROOT / "scripts" / "release-intelligence-cron.sh").read_text(encoding="utf-8")

    assert "run_daily" in wrapper
    assert "run_weekly" in wrapper
    assert "--discord" in wrapper
    assert "run_monthly" in wrapper


def test_llm_summary_normalization_keeps_only_known_commit_evidence() -> None:
    raw = {
        "overview": "A clear release summary.",
        "released_changes": [
            {
                "text": "CLI self-update is now easier to use.",
                "evidence": {"commits": ["abc1234", "not-real"]},
                "release_status": "released_main",
            }
        ],
        "bug_fixes": [],
        "unreleased_progress": [
            {
                "text": "Settings footer links are still dev-only.",
                "evidence": {"commits": ["def5678"]},
                "release_status": "dev_only",
            }
        ],
        "internal_progress": [],
        "newsletter_recommendation": {
            "include": [
                {
                    "text": "Mention CLI self-update.",
                    "evidence": {"commits": ["abc1234"]},
                    "reason": "Released and user-facing.",
                }
            ],
            "exclude": [
                {
                    "text": "Do not mention footer links yet.",
                    "evidence": {"commits": ["def5678"]},
                    "reason": "Dev-only.",
                }
            ],
            "rationale": "One released item is safe to mention.",
        },
        "social_video_recommendations": [
            {
                "idea": "Show CLI self-update in 20 seconds.",
                "priority": "medium",
                "reason": "Concrete workflow.",
                "evidence": {"commits": ["abc1234"]},
            },
            {
                "idea": "Unsupported idea.",
                "priority": "low",
                "reason": "No known evidence.",
                "evidence": {"commits": ["unknown"]},
            },
        ],
        "quality_notes": ["Review before sending."],
    }

    normalized = normalize_summary(raw, {"abc1234", "def5678"})

    assert normalized["released_changes"][0]["evidence"]["commits"] == ["abc1234"]
    assert normalized["unreleased_progress"][0]["release_status"] == "dev_only"
    assert normalized["social_video_recommendations"][1]["evidence"]["commits"] == []
    assert normalized["validation_warnings"]


def test_newsletter_include_evidence_is_limited_to_newsletter_ready_commits() -> None:
    raw = {
        "overview": "A clear release summary.",
        "released_changes": [],
        "bug_fixes": [],
        "unreleased_progress": [],
        "internal_progress": [],
        "newsletter_recommendation": {
            "include": [
                {
                    "text": "Mention workflow input sessions.",
                    "evidence": {"commits": ["disabled1"]},
                    "reason": "Should be blocked.",
                }
            ],
            "exclude": [],
            "rationale": "Only ready commits are allowed.",
        },
        "social_video_recommendations": [],
        "quality_notes": [],
    }

    normalized = normalize_summary(raw, {"disabled1", "ready1"}, newsletter_include_commits={"ready1"})

    assert normalized["newsletter_recommendation"]["include"] == []
    assert normalized["validation_warnings"] == []


def test_weekly_llm_source_includes_dated_daily_summaries() -> None:
    daily = minimal_daily(
        "2026-07-07",
        [
            {
                "title": "feat: add CLI self-update commands",
                "section": "features",
                "commits": ["abc1234"],
                "changed_paths": ["frontend/packages/openmates-cli/src/selfUpdate.ts"],
                "release_status": "released_main",
                "newsletter_ready": True,
                "user_facing": True,
            }
        ],
    )
    daily["llm_summary"] = {"overview": "CLI self-update shipped."}
    weekly = build_weekly_artifact(
        daily_artifacts=[daily],
        week_start=date(2026, 7, 6),
        week_end=date(2026, 7, 12),
    )

    source = build_weekly_llm_source(weekly, [daily])

    assert source["daily_summaries"][0]["date"] == "2026-07-07"
    assert source["daily_summaries"][0]["llm_summary"]["overview"] == "CLI self-update shipped."
    assert source["marketing_candidates"]["newsletter"][0]["commits"] == ["abc1234"]


def test_newsletter_include_commits_from_weekly_source_uses_daily_candidates() -> None:
    daily = minimal_daily(
        "2026-07-07",
        [
            {
                "title": "feat: add CLI self-update commands",
                "section": "features",
                "commits": ["abc1234"],
                "changed_paths": ["frontend/packages/openmates-cli/src/selfUpdate.ts"],
                "release_status": "released_main",
                "newsletter_ready": True,
                "user_facing": True,
            }
        ],
    )
    weekly = build_weekly_artifact(
        daily_artifacts=[daily],
        week_start=date(2026, 7, 6),
        week_end=date(2026, 7, 12),
    )
    source = build_weekly_llm_source(weekly, [daily])

    assert newsletter_include_commits_from_source(source) == {"abc1234"}


def test_collect_commits_keeps_date_bounds_with_from_ref(monkeypatch) -> None:
    logged_commands = []

    def fake_git_output(command, check=True):
        if command[0] == "log":
            logged_commands.append(command)
        return ""

    monkeypatch.setattr(_release_intelligence, "git_output", fake_git_output)

    commits = _release_intelligence.collect_commits(
        since="2026-04-13T12:11:31+00:00",
        until="2026-04-13T23:59:59+00:00",
        from_ref="v0.9.0-alpha",
        to_ref="origin/main",
        main_ref="origin/main",
        dev_ref="origin/dev",
    )

    assert commits == []
    assert logged_commands == [
        [
            "log",
            "--format=%x1e%H%x1f%h%x1f%aI%x1f%s%x1f%b",
            "--since=2026-04-13T12:11:31+00:00",
            "--until=2026-04-13T23:59:59+00:00",
            "v0.9.0-alpha..origin/main",
        ]
    ]
