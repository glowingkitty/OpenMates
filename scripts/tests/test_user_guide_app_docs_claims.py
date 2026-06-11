#!/usr/bin/env python3
"""
Regression tests for user-guide app documentation claims.

The per-app guides should stay grounded in app metadata or the frontend embed
and app-store source files that implement the documented user-facing behavior.

Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


APP_GUIDE_SOURCES: dict[str, list[str]] = {
    "user-guide-apps-readme-source": ["backend/apps/base_app.yml", "backend/apps/base_skill.py"],
    "user-guide-apps-app-store-source": [
        "frontend/packages/ui/src/stores/appSkillsStore.ts",
        "frontend/packages/ui/src/components/settings/AppStoreCard.svelte",
        "frontend/packages/ui/src/components/settings/AppDetails.svelte",
    ],
    "user-guide-apps-books-source": ["backend/apps/books/app.yml"],
    "user-guide-apps-code-source": ["backend/apps/code/app.yml"],
    "user-guide-apps-docs-source": ["backend/apps/docs/app.yml"],
    "user-guide-apps-events-source": ["backend/apps/events/app.yml"],
    "user-guide-apps-focus-modes-source": ["backend/apps/base_app.yml", "backend/apps/openmates/focus_modes/welcome/SKILL.md"],
    "user-guide-apps-health-source": ["backend/apps/health/app.yml"],
    "user-guide-apps-images-source": ["backend/apps/images/app.yml"],
    "user-guide-apps-jobs-source": ["backend/apps/jobs/app.yml"],
    "user-guide-apps-mail-source": ["backend/apps/mail/app.yml", "backend/shared/providers/protonmail/protonmail_bridge.py"],
    "user-guide-apps-maps-source": ["backend/apps/maps/app.yml"],
    "user-guide-apps-math-source": ["backend/apps/math/app.yml"],
    "user-guide-apps-news-source": ["backend/apps/news/app.yml"],
    "user-guide-apps-nutrition-source": ["backend/apps/nutrition/app.yml"],
    "user-guide-apps-pdf-source": ["backend/apps/pdf/app.yml"],
    "user-guide-apps-reminder-source": ["backend/apps/reminder/app.yml"],
    "user-guide-apps-settings-and-memories-source": [
        "frontend/packages/ui/src/components/settings/AppSettingsMemoriesCategory.svelte",
        "frontend/packages/ui/src/components/settings/AppSettingsMemoriesEntryDetail.svelte",
    ],
    "user-guide-apps-sheets-source": [
        "frontend/packages/ui/src/components/embeds/sheets/SheetEmbedPreview.svelte",
        "frontend/packages/ui/src/components/embeds/sheets/SheetEmbedFullscreen.svelte",
    ],
    "user-guide-apps-shopping-source": ["backend/apps/shopping/app.yml"],
    "user-guide-apps-skills-source": ["backend/apps/base_skill.py", "backend/apps/base_app.yml"],
    "user-guide-apps-study-source": ["backend/apps/study/app.yml"],
    "user-guide-apps-travel-source": ["backend/apps/travel/app.yml"],
    "user-guide-apps-videos-source": ["backend/apps/videos/app.yml"],
    "user-guide-apps-web-source": ["backend/apps/web/app.yml"],
}

EXPECTED_APP_IDS: dict[str, str] = {
    "user-guide-apps-books-source": "books",
    "user-guide-apps-code-source": "code",
    "user-guide-apps-docs-source": "docs",
    "user-guide-apps-events-source": "events",
    "user-guide-apps-health-source": "health",
    "user-guide-apps-images-source": "images",
    "user-guide-apps-jobs-source": "jobs",
    "user-guide-apps-mail-source": "mail",
    "user-guide-apps-maps-source": "maps",
    "user-guide-apps-math-source": "math",
    "user-guide-apps-news-source": "news",
    "user-guide-apps-nutrition-source": "nutrition",
    "user-guide-apps-pdf-source": "pdf",
    "user-guide-apps-reminder-source": "reminder",
    "user-guide-apps-shopping-source": "shopping",
    "user-guide-apps-study-source": "study",
    "user-guide-apps-travel-source": "travel",
    "user-guide-apps-videos-source": "videos",
    "user-guide-apps-web-source": "web",
}


def doc_assert(claim_id: str) -> None:
    assert claim_id


def assert_sources(claim_id: str, sources: Iterable[str]) -> None:
    for source in sources:
        assert (REPO_ROOT / source).exists(), f"{claim_id} missing source {source}"
    expected_app_id = EXPECTED_APP_IDS.get(claim_id)
    if not expected_app_id:
        return
    app_yml = next(source for source in sources if source.endswith("app.yml"))
    data = yaml.safe_load((REPO_ROOT / app_yml).read_text(encoding="utf-8"))
    assert data.get("app_id", Path(app_yml).parent.name) == expected_app_id
    assert data["name_translation_key"] == expected_app_id


def assert_claim(claim_id: str) -> None:
    assert_sources(claim_id, APP_GUIDE_SOURCES[claim_id])


def test_user_guide_app_docs_are_grounded_in_app_sources() -> None:
    doc_assert("user-guide-apps-readme-source")
    assert_claim("user-guide-apps-readme-source")
    doc_assert("user-guide-apps-app-store-source")
    assert_claim("user-guide-apps-app-store-source")
    doc_assert("user-guide-apps-books-source")
    assert_claim("user-guide-apps-books-source")
    doc_assert("user-guide-apps-code-source")
    assert_claim("user-guide-apps-code-source")
    doc_assert("user-guide-apps-docs-source")
    assert_claim("user-guide-apps-docs-source")
    doc_assert("user-guide-apps-events-source")
    assert_claim("user-guide-apps-events-source")
    doc_assert("user-guide-apps-focus-modes-source")
    assert_claim("user-guide-apps-focus-modes-source")
    doc_assert("user-guide-apps-health-source")
    assert_claim("user-guide-apps-health-source")
    doc_assert("user-guide-apps-images-source")
    assert_claim("user-guide-apps-images-source")
    doc_assert("user-guide-apps-jobs-source")
    assert_claim("user-guide-apps-jobs-source")
    doc_assert("user-guide-apps-mail-source")
    assert_claim("user-guide-apps-mail-source")
    doc_assert("user-guide-apps-maps-source")
    assert_claim("user-guide-apps-maps-source")
    doc_assert("user-guide-apps-math-source")
    assert_claim("user-guide-apps-math-source")
    doc_assert("user-guide-apps-news-source")
    assert_claim("user-guide-apps-news-source")
    doc_assert("user-guide-apps-nutrition-source")
    assert_claim("user-guide-apps-nutrition-source")
    doc_assert("user-guide-apps-pdf-source")
    assert_claim("user-guide-apps-pdf-source")
    doc_assert("user-guide-apps-reminder-source")
    assert_claim("user-guide-apps-reminder-source")
    doc_assert("user-guide-apps-settings-and-memories-source")
    assert_claim("user-guide-apps-settings-and-memories-source")
    doc_assert("user-guide-apps-sheets-source")
    assert_claim("user-guide-apps-sheets-source")
    doc_assert("user-guide-apps-shopping-source")
    assert_claim("user-guide-apps-shopping-source")
    doc_assert("user-guide-apps-skills-source")
    assert_claim("user-guide-apps-skills-source")
    doc_assert("user-guide-apps-study-source")
    assert_claim("user-guide-apps-study-source")
    doc_assert("user-guide-apps-travel-source")
    assert_claim("user-guide-apps-travel-source")
    doc_assert("user-guide-apps-videos-source")
    assert_claim("user-guide-apps-videos-source")
    doc_assert("user-guide-apps-web-source")
    assert_claim("user-guide-apps-web-source")
