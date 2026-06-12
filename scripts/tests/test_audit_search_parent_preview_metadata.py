"""Tests for the search/result-list parent preview metadata audit.

The audit keeps new composite result-list embed types from being added without a
parent-level preview metadata contract. Fixture app.yml files cover the failing,
covered, and explicitly exempted paths without touching production app metadata.
"""

from __future__ import annotations

from pathlib import Path

from scripts.audit_search_parent_preview_metadata import audit_app_files


def write_app(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_has_children_result_list_without_contract_is_reported(tmp_path: Path) -> None:
    app_path = write_app(
        tmp_path / "backend/apps/new_search/app.yml",
        """
embed_types:
  - id: search
    category: app-skill-use
    skill_id: search
    has_children: true
    preview_component: new/NewSearchEmbedPreview.svelte
    child_preview_component: new/NewResultEmbedPreview.svelte
""",
    )

    issues = audit_app_files([app_path], covered=set(), exemptions={})

    assert len(issues) == 1
    assert "new_search:search" in issues[0].format(Path.cwd())
    assert "parent preview metadata" in issues[0].message


def test_has_children_result_list_with_contract_passes(tmp_path: Path) -> None:
    app_path = write_app(
        tmp_path / "backend/apps/new_search/app.yml",
        """
embed_types:
  - id: search
    category: app-skill-use
    skill_id: search
    has_children: true
    preview_component: new/NewSearchEmbedPreview.svelte
    child_preview_component: new/NewResultEmbedPreview.svelte
""",
    )

    issues = audit_app_files([app_path], covered={"new_search:search"}, exemptions={})

    assert issues == []


def test_explicit_non_result_list_exemption_passes(tmp_path: Path) -> None:
    app_path = write_app(
        tmp_path / "backend/apps/code/app.yml",
        """
embed_types:
  - id: application
    category: app-skill-use
    skill_id: create_application
    has_children: true
    preview_component: code/ApplicationEmbedPreview.svelte
    child_preview_component: code/CodeEmbedPreview.svelte
""",
    )

    issues = audit_app_files(
        [app_path],
        covered=set(),
        exemptions={"code:create_application": "Application parents use manifest refs, not result-list previews."},
    )

    assert issues == []


def test_empty_exemption_reason_is_reported(tmp_path: Path) -> None:
    app_path = write_app(
        tmp_path / "backend/apps/code/app.yml",
        """
embed_types:
  - id: application
    category: app-skill-use
    skill_id: create_application
    has_children: true
    preview_component: code/ApplicationEmbedPreview.svelte
    child_preview_component: code/CodeEmbedPreview.svelte
""",
    )

    issues = audit_app_files([app_path], covered=set(), exemptions={"code:create_application": ""})

    assert len(issues) == 1
    assert "exemption reason" in issues[0].message
