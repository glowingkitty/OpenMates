// OpenMates Watch app entry point.
// Defines the independent watchOS application scene for the standalone Watch
// client. The target intentionally starts with only app plumbing; pair login,
// chat sync, audio input, and embed previews are added by later spec tasks.
// Keep this file free of business logic so shared runtime can remain testable.
// User-visible copy belongs in localized view layers, never in the app entry.
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.registration.lifecycle

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Header.svelte
// CSS:     frontend/packages/ui/src/styles/header.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import WatchKit

@main
struct OpenMatesWatchApp: App {
    @WKApplicationDelegateAdaptor(WatchPushAppDelegate.self) private var pushDelegate
    init() {
        FontRegistration.registerFonts()
        WatchPushNotificationManager.shared.configureForLaunch()
    }

    var body: some Scene {
        WindowGroup {
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-native-crown") {
                WatchNativeCrownDiagnosticView()
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-layout") {
                WatchChatShellView(
                    uiTestSnapshot: Self.uiTestSnapshot,
                    selectedChatId: Self.uiTestChatId
                )
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-notification-route") {
                WatchChatShellView(uiTestSnapshot: Self.uiTestSnapshot, selectedChatId: nil,
                                   fixtureNotificationChatID: Self.uiTestChatId)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-notification-missing") {
                WatchChatShellView(uiTestSnapshot: Self.uiTestSnapshot, selectedChatId: nil,
                                   fixtureNotificationChatID: "missing-notification-chat")
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-remote-draft") {
                WatchChatShellView(uiTestSnapshot: .empty, selectedChatId: nil, remoteDraftFixture: true)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-markdown") {
                WatchChatShellView(uiTestSnapshot: Self.uiTestMarkdownSnapshot, selectedChatId: Self.uiTestChatId)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-draft") {
                WatchChatShellView(uiTestSnapshot: Self.uiTestNewChatSnapshot, selectedChatId: Self.uiTestChatId,
                    initialDraft: "Berlin meetup draft", currentUsername: "Kitty")
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
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-pair-initiation-failed") {
                WatchPairLoginView(authStore: WatchAuthStore(), uiTestFixture: .initiationFailed)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-pair-selfhost-initiation-failed") {
                WatchPairLoginView(authStore: WatchAuthStore(), uiTestFixture: .selfHostedInitiationFailed)
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

    private static let uiTestMarkdownSnapshot = WatchChatSnapshot(
        chats: [WatchChatSummary(id: uiTestChatId, title: "Public Berlin events", lastMessageAt: "2026-09-30T12:00:00Z",
            preview: nil, isPinned: false, encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil)],
        messagesByChatId: [uiTestChatId: [WatchChatMessage(id: "watch-markdown-fixture", chatId: uiTestChatId,
            role: .assistant, content: "## Berlin **Meetup**\n\n- **Bring** a demo\n- Meet *developers*\n\n> Public event\n\n```swift\nlet city = \"Berlin\"\n```",
            encryptedContent: nil, embedRefs: [WatchEmbedRef(id: "watch-events-fixture", type: EmbedType.eventsSearch.rawValue,
                status: "finished", data: ["query": AnyCodable("Berlin meetups"), "result_count": AnyCodable(3)])],
            createdAt: "2026-09-30T12:00:00Z", isPending: false)]], savedAt: .distantPast)

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

    private static var tasks: [WatchTaskListItem] {
        var items = (0..<12).map { index in
            WatchTaskListItem(id: "backlog-\(index)", title: "Backlog task \(index + 1)",
                group: .backlog, status: "backlog", position: index, updatedAt: 1,
                openRequest: WatchItemOpenRequest(kind: .task, id: "backlog-\(index)")!)
        }
        items += [
            WatchTaskListItem(id: "task-two", title: "Ship watch app", group: .todo,
                status: "todo", position: 0, updatedAt: 1,
                openRequest: WatchItemOpenRequest(kind: .task, id: "task-two")!),
            WatchTaskListItem(id: "task-one", title: "Research hoverboard motors", group: .inProgress,
                status: "in_progress", position: 0, updatedAt: 2,
                openRequest: WatchItemOpenRequest(kind: .task, id: "task-one")!,
                description: "Compare motors that safely carry two people.",
                latestInstruction: "Check torque and battery capacity before choosing parts.",
                activitySummary: "Compared three motors. Next: verify supplier specifications."),
            WatchTaskListItem(id: "task-blocked", title: "Waiting for approval", group: .blocked,
                status: "blocked", position: 0, updatedAt: 1,
                openRequest: WatchItemOpenRequest(kind: .task, id: "task-blocked")!,
                blockedReason: "Confirm the parts budget."),
            WatchTaskListItem(id: "task-done", title: "Completed research", group: .done,
                status: "done", position: 0, updatedAt: 1,
                openRequest: WatchItemOpenRequest(kind: .task, id: "task-done")!),
        ]
        return items
    }

    var body: some View {
        WatchHubView(
            currentUserId: nil,
            webSocketToken: nil,
            fixtureTasks: Self.tasks,
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
