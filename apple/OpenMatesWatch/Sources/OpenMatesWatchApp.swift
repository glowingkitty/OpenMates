// OpenMates Watch app entry point.
// Defines the independent watchOS application scene for the standalone Watch
// client. The target intentionally starts with only app plumbing; pair login,
// chat sync, audio input, and embed previews are added by later spec tasks.
// Keep this file free of business logic so shared runtime can remain testable.
// User-visible copy belongs in localized view layers, never in the app entry.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Header.svelte
// CSS:     frontend/packages/ui/src/styles/header.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

@main
struct OpenMatesWatchApp: App {
    var body: some Scene {
        WindowGroup {
#if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-layout") {
                WatchChatShellView(
                    uiTestSnapshot: Self.uiTestSnapshot,
                    selectedChatId: Self.uiTestChatId
                )
            } else {
                WatchRootView()
            }
#else
            WatchRootView()
#endif
        }
    }

#if DEBUG
    private static let uiTestChatId = "watch-ui-test-chat"

    private static let uiTestSnapshot = WatchChatSnapshot(
        chats: [
            WatchChatSummary(
                id: uiTestChatId,
                title: "Watch layout",
                lastMessageAt: "2026-08-03T00:00:00Z",
                preview: "Embed preview",
                isPinned: false,
                encryptedTitle: nil,
                encryptedPreview: nil,
                encryptedChatKey: nil
            ),
        ],
        messagesByChatId: [
            uiTestChatId: [
                WatchChatMessage(
                    id: "watch-ui-test-message",
                    chatId: uiTestChatId,
                    role: .assistant,
                    content: nil,
                    encryptedContent: nil,
                    embedRefs: [
                        WatchEmbedRef(
                            id: "watch-ui-test-embed",
                            type: EmbedType.webWebsite.rawValue,
                            status: "finished",
                            data: [
                                "title": AnyCodable("OpenMates Watch preview"),
                                "url": AnyCodable("https://openmates.org"),
                            ]
                        ),
                    ],
                    createdAt: "2026-08-03T00:00:00Z",
                    isPending: false
                ),
            ],
        ],
        savedAt: Date(timeIntervalSince1970: 0)
    )
#endif
}
