#!/usr/bin/env python3
"""
Regression tests for product-flow user-guide documentation claims.

These source-grounding checks cover user-facing guides whose behavior spans the
Svelte app shell, chat services, local stores, settings components, and backend
routes. They intentionally avoid live browser or provider calls.

Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def read_repo(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def doc_assert(claim_id: str) -> None:
    assert claim_id


def test_chat_management_docs_are_grounded_in_chat_sources() -> None:
    doc_assert("user-guide-chats-source")
    active_chat = read_repo("frontend/packages/ui/src/components/ActiveChat.svelte")
    chat_updates = read_repo("frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts")
    chat_types = read_repo("frontend/packages/ui/src/types/chat.ts")

    assert "downloadChatAsZip" in active_chat
    assert "copyChatToClipboard" in active_chat
    assert "case 'delete'" in active_chat
    assert "case 'pin'" in active_chat
    assert "chat_pinned_updated" in chat_updates
    assert "unread_count" in chat_types


def test_drafts_hidden_incognito_docs_are_grounded_in_privacy_mode_sources() -> None:
    doc_assert("user-guide-drafts-source")
    doc_assert("user-guide-hidden-chats-source")
    doc_assert("user-guide-incognito-mode-source")
    draft_save = read_repo("frontend/packages/ui/src/services/drafts/draftSave.ts")
    hidden_service = read_repo("frontend/packages/ui/src/services/hiddenChatService.ts")
    incognito_service = read_repo("frontend/packages/ui/src/services/incognitoChatService.ts")
    usage = read_repo("backend/core/api/app/services/billing_service.py")

    assert "encrypted_draft_md" in draft_save
    assert "saveDraft" in draft_save
    assert "clearCurrentDraft" in draft_save
    assert "tryDecryptChatKey" in hidden_service
    assert "isUnlocked" in hidden_service
    assert "sessionStorage" in incognito_service
    assert "is_incognito" in incognito_service
    assert "chat_id = \"incognito\"" in usage


def test_search_and_shortcuts_docs_are_grounded_in_frontend_sources() -> None:
    doc_assert("user-guide-search-source")
    doc_assert("user-guide-keyboard-shortcuts-source")
    search = read_repo("frontend/packages/ui/src/services/searchService.ts")
    search_catalog = read_repo("frontend/packages/ui/src/services/searchSettingsCatalog.ts")
    active_chat = read_repo("frontend/packages/ui/src/components/ActiveChat.svelte")
    chats = read_repo("frontend/packages/ui/src/components/chats/Chats.svelte")

    assert "in-memory index" in search
    assert "settings" in search
    assert "appCatalog" in search
    assert "metadata index" in search
    assert "Keywords for fuzzy matching" in search_catalog
    assert "Ctrl" in chats or "metaKey" in chats or "shiftKey" in chats
    assert "downloadChatAsZip" in active_chat
    assert "copyChatToClipboard" in active_chat


def test_file_upload_docs_are_grounded_in_embed_upload_sources() -> None:
    doc_assert("user-guide-file-uploads-source")
    embed_service = read_repo("backend/core/api/app/services/embed_service.py")
    group_renderer = read_repo("frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts")
    app_skill_renderer = read_repo("frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/AppSkillUseRenderer.ts")

    assert "s3Files" in group_renderer
    assert "aesKey" in group_renderer
    assert "aesNonce" in group_renderer
    assert "aiDetection" in group_renderer
    assert "pdffullscreen" in app_skill_renderer
    assert "imagefullscreen" in app_skill_renderer
    assert "ai_detection" in embed_service


def test_notification_docs_are_grounded_in_notification_sources() -> None:
    doc_assert("user-guide-notifications-source")
    notification_store = read_repo("frontend/packages/ui/src/stores/notificationStore.ts")
    notification_component = read_repo("frontend/packages/ui/src/components/Notification.svelte")
    settings_notifications = read_repo("frontend/packages/ui/src/components/settings/SettingsNotifications.svelte")

    assert "message_completed" in notification_store or "Notification" in notification_store
    assert "close" in notification_component
    assert "push" in settings_notifications.lower()
    assert "notification" in settings_notifications.lower()


def test_daily_inspiration_demo_and_onboarding_docs_are_grounded_in_sources() -> None:
    doc_assert("user-guide-daily-inspiration-source")
    doc_assert("user-guide-demo-chats-source")
    doc_assert("user-guide-onboarding-source")
    doc_assert("user-guide-getting-started-source")
    active_chat = read_repo("frontend/packages/ui/src/components/ActiveChat.svelte")
    daily_store = read_repo("frontend/packages/ui/src/stores/dailyInspirationStore.ts")
    demos = read_repo("frontend/packages/ui/src/demo_chats/index.ts")
    app_metadata = read_repo("frontend/packages/ui/src/data/appsMetadata.ts")
    billing_utils = read_repo("backend/shared/python_utils/billing_utils.py")

    assert "DailyInspirationBanner" in active_chat
    assert "handleStartChatFromInspiration" in active_chat
    assert "content_type === 'feature'" in active_chat
    assert "markOpened" in daily_store
    assert "INTRO_CHATS" in demos
    assert "For everyone" in demos or "for_everyone" in demos
    assert "You are Suki" in app_metadata
    assert "share-usecase" in app_metadata
    assert "MINIMUM_CREDITS_CHARGED" in billing_utils


def test_docs_site_and_issue_reporting_docs_are_grounded_in_sources() -> None:
    doc_assert("user-guide-docs-web-page-source")
    doc_assert("user-guide-issue-reporting-source")
    doc_assert("user-guide-debug-tools-source")
    debug_utils = read_repo("frontend/packages/ui/src/services/debugUtils.ts")
    app = read_repo("frontend/packages/ui/src/app.ts")
    report_issue = read_repo("frontend/packages/ui/src/components/settings/SettingsReportIssue.svelte")
    docs_build = read_repo("frontend/apps/web_app/scripts/process-docs.js")

    assert "window.debugChat" in debug_utils
    assert "debugAllChats" in debug_utils
    assert "debugGetMessage" in debug_utils
    assert "debugUtils" in app
    assert "device_info" in report_issue
    assert "console_logs" in report_issue
    assert "docs-manifest" in docs_build or "search" in docs_build


def test_read_status_and_creator_docs_are_grounded_in_sources() -> None:
    doc_assert("user-guide-scroll-read-status-source")
    doc_assert("user-guide-creators-program-source")
    active_chat = read_repo("frontend/packages/ui/src/components/ActiveChat.svelte")
    chats = read_repo("frontend/packages/ui/src/components/chats/Chats.svelte")
    creators = read_repo("backend/core/api/app/routes/creators.py")

    assert "isAtBottom" in active_chat
    assert "unread_count" in active_chat
    assert "scroll" in active_chat.lower()
    assert "unread" in chats.lower()
    assert "/tip" in creators
    assert "100% of the tipped credits" in creators
    assert "hash_owner_id" in creators
    assert "Creator tips are not available in self-hosted mode" in creators
