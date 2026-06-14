"""Unit tests for the Apple chat parity audit.

The audit is a deterministic guardrail for native chat-window loading and visual
parity contracts. These tests use temporary source fixtures so failures prove the
audit logic, not the current repository contents.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "scripts" / "apple_chat_parity_audit.py"
spec = importlib.util.spec_from_file_location("apple_chat_parity_audit", AUDIT_PATH)
assert spec and spec.loader
apple_chat_parity_audit = importlib.util.module_from_spec(spec)
sys.modules["apple_chat_parity_audit"] = apple_chat_parity_audit
spec.loader.exec_module(apple_chat_parity_audit)


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def patch_sources(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(apple_chat_parity_audit, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(apple_chat_parity_audit, "MAIN_APP", write(tmp_path / "MainAppView.swift", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "CHAT_STORE", write(tmp_path / "ChatStore.swift", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "OFFLINE_STORE", write(tmp_path / "OfflineStore.swift", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "OFFLINE_BRIDGE", write(tmp_path / "OfflineSyncBridge.swift", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "CHAT_VIEW_MODEL", write(tmp_path / "ChatViewModel.swift", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "CHAT_VIEW", write(tmp_path / "ChatView.swift", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "EMBED_PREVIEW", write(tmp_path / "EmbedPreviewCard.swift", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "CHAT_CSS", write(tmp_path / "chat.css", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "FIELDS_CSS", write(tmp_path / "fields.css", ""))
    monkeypatch.setattr(apple_chat_parity_audit, "UNIFIED_EMBED_PREVIEW", write(tmp_path / "UnifiedEmbedPreview.svelte", ""))


def test_audit_web_to_apple_constants_passes_with_expected_contract(monkeypatch, tmp_path: Path) -> None:
    patch_sources(monkeypatch, tmp_path)
    apple_chat_parity_audit.CHAT_CSS.write_text(
        """
        border-radius: 13px;
        padding: 12px;
        filter: drop-shadow(0 4px 4px rgba(0, 0, 0, 0.25));
        background-color: var(--color-grey-blue);
        background-color: var(--color-grey-0);
        max-width: calc(100% - 100px);
        max-width: calc(100% - 20px);
        max-width: calc(100% - 70px);
        """,
        encoding="utf-8",
    )
    apple_chat_parity_audit.FIELDS_CSS.write_text(
        """
        border-radius: 24px;
        border-color: var(--color-button-primary);
        box-shadow: 0 0 0 3px rgba(255, 85, 59, 0.22);
        """,
        encoding="utf-8",
    )
    apple_chat_parity_audit.UNIFIED_EMBED_PREVIEW.write_text("Desktop: 300x200px", encoding="utf-8")
    apple_chat_parity_audit.CHAT_VIEW.write_text(
        """
        RoundedRectangle(cornerRadius: 13)
        .padding(.spacing6)
        .background(Color.greyBlue)
        .background(Color.grey0)
        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
        """,
        encoding="utf-8",
    )
    apple_chat_parity_audit.EMBED_PREVIEW.write_text(
        """
        static let compactWidth: CGFloat = 300
        static let compactHeight: CGFloat = 200
        static let cornerRadius: CGFloat = 30
        """,
        encoding="utf-8",
    )

    assert apple_chat_parity_audit.audit_web_to_apple_constants() == []


def test_audit_web_to_apple_constants_fails_on_missing_web_contract(monkeypatch, tmp_path: Path) -> None:
    patch_sources(monkeypatch, tmp_path)
    failures = apple_chat_parity_audit.audit_web_to_apple_constants()

    assert any("Web chat bubble radius" in failure for failure in failures)
    assert any("Apple embed preview width" in failure for failure in failures)


def test_audit_chat_loading_flags_full_initial_chat_arrays(monkeypatch, tmp_path: Path) -> None:
    patch_sources(monkeypatch, tmp_path)
    apple_chat_parity_audit.MAIN_APP.write_text(
        "initialMessages: isPublic ? [] : chatStore.messages(for: chatId)",
        encoding="utf-8",
    )

    failures = apple_chat_parity_audit.audit_chat_loading()

    assert any("full chatStore.messages" in failure for failure in failures)
