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
    init() {
        FontRegistration.registerFonts()
    }

    var body: some Scene {
        WindowGroup {
#if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-layout") {
                WatchChatShellView(
                    uiTestSnapshot: Self.uiTestSnapshot,
                    selectedChatId: Self.uiTestChatId
                )
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-recording") {
                WatchChatShellView(
                    uiTestSnapshot: Self.uiTestSnapshot,
                    selectedChatId: Self.uiTestChatId,
                    showsRecordingFixture: true
                )
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-new") {
                WatchChatShellView(
                    uiTestSnapshot: Self.uiTestNewChatSnapshot,
                    selectedChatId: Self.uiTestChatId,
                    currentUsername: "Kitty"
                )
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-search") {
                WatchChatShellView(
                    uiTestSnapshot: Self.uiTestSnapshot,
                    selectedChatId: nil,
                    initialSearchText: "no matching chat"
                )
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-pair-waiting") {
                WatchPairLoginView(authStore: WatchAuthStore(), uiTestFixture: .iphoneConfirm)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-pair-cloud-short-url") {
                WatchPairLoginView(authStore: WatchAuthStore(), uiTestFixture: .cloudShortURL)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-pair-selfhost-short-url") {
                WatchPairLoginView(authStore: WatchAuthStore(), uiTestFixture: .selfHostedShortURL)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-pair-selfhost-entry") {
                WatchPairLoginView(authStore: WatchAuthStore(), uiTestFixture: .selfHostedDomainEntry)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-pair-code-entry") {
                WatchPairLoginView(authStore: WatchAuthStore(), uiTestFixture: .pairCodeEntry)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-hub-lists") {
                WatchHubUITestFixtureView()
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

    private static let uiTestNewChatSnapshot = WatchChatSnapshot(
        chats: [
            WatchChatSummary(
                id: uiTestChatId,
                title: "New chat",
                lastMessageAt: "2026-08-03T00:00:00Z",
                preview: nil,
                isPinned: false,
                encryptedTitle: nil,
                encryptedPreview: nil,
                encryptedChatKey: nil
            ),
        ],
        messagesByChatId: [:],
        savedAt: Date(timeIntervalSince1970: 0)
    )

    private static let uiTestSnapshot = WatchChatSnapshot(
        chats: [
            WatchChatSummary(
                id: uiTestChatId,
                title: "Offline Whisper iOS Integration",
                lastMessageAt: "2026-08-03T00:00:00Z",
                preview: "Draft: I think ...",
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
                            type: EmbedType.codeCode.rawValue,
                            status: "finished",
                            data: [
                                "title": AnyCodable("Write"),
                                "line_count": AnyCodable(28),
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

#if DEBUG
private struct WatchHubUITestFixtureView: View {
    @State private var openedItem: WatchItemOpenRequest?

    var body: some View {
        WatchHubView(
            currentUserId: nil,
            webSocketToken: nil,
            fixtureTasks: [
                WatchTaskListItem(
                    id: "task-one", title: "Research how expensive hoverboard motors are to carry 2-3 people safely", group: .inProgress,
                    status: "in_progress", position: 0, updatedAt: 2,
                    openRequest: WatchItemOpenRequest(kind: .task, id: "task-one")!
                ),
                WatchTaskListItem(
                    id: "task-two", title: "Ship watch app", group: .todo,
                    status: "todo", position: 0, updatedAt: 1,
                    openRequest: WatchItemOpenRequest(kind: .task, id: "task-two")!
                ),
            ],
            fixtureWorkflows: [
                WatchWorkflowListItem(
                    id: "workflow-one", title: "Weekly AI events", enabled: true,
                    updatedAt: 2, category: "general_knowledge", icon: "calendar",
                    openRequest: WatchItemOpenRequest(kind: .workflow, id: "workflow-one")!
                ),
                WatchWorkflowListItem(
                    id: "workflow-two", title: "Apartment search", enabled: true,
                    updatedAt: 1, category: "marketing_sales", icon: "search",
                    openRequest: WatchItemOpenRequest(kind: .workflow, id: "workflow-two")!
                ),
            ],
            onOpenItem: { openedItem = $0 },
            onOpenSettings: {},
            onCreate: { _ in }
        )
        .overlay(alignment: .bottom) {
            if let openedItem {
                Text("\(openedItem.kind.rawValue):\(openedItem.id)")
                    .font(.omMicro)
                    .foregroundStyle(Color.clear)
                    .accessibilityIdentifier("watch-ui-test-open-request")
            }
        }
    }
}
#endif
