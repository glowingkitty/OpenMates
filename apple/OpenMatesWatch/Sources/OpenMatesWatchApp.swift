// OpenMates Watch app entry point.
// Defines the independent watchOS application scene for the standalone Watch
// client. The target intentionally starts with only app plumbing; pair login,
// chat sync, audio input, and embed previews are added by later spec tasks.
// Keep this file free of business logic so shared runtime can remain testable.
// User-visible copy belongs in localized view layers, never in the app entry.
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.registration.lifecycle
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.tasks.edit-private, apple-watch.workflows.compact-editor

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
#if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-reset-zoom") {
            UserDefaults.standard.removeObject(forKey: "watch.transcript.zoom")
        }
#endif
        FontRegistration.registerFonts()
        WatchPushNotificationManager.shared.configureForLaunch()
    }

    var body: some Scene {
        WindowGroup {
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-workflow-save-failure") {
                WatchWorkflowUITestFixtureView(failFirstSave: true)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-workflow-retry") {
                WatchWorkflowUITestFixtureView(failFirstRead: true)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-workflow-empty") {
                WatchWorkflowUITestFixtureView(empty: true)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-workflow-detail") {
                WatchWorkflowUITestFixtureView()
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-task-edit-failure") {
                WatchTaskEditingUITestFixtureView(failsSave: true)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-task-edit-workflow") {
                WatchTaskEditingUITestFixtureView(workflowProjection: true)
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-task-edit") {
                WatchTaskEditingUITestFixtureView()
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-crown-binding") {
                WatchCrownBindingDiagnosticView()
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-native-crown") {
                WatchNativeCrownDiagnosticView()
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-message-window") {
                WatchMessageWindowUITestView()
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-list-metadata") {
                WatchChatListMetadataUITestView()
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-share") {
                WatchChatShareUITestView()
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
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-offline-cohort") {
                WatchOfflineCohortUITestView()
            } else if ProcessInfo.processInfo.arguments.contains("--watch-whisper-lab-fixture") {
                WatchWhisperLabView()
            } else if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-chat-mobile-preview") {
                WatchChatShellView(uiTestSnapshot: Self.uiTestMobilePreviewSnapshot, selectedChatId: Self.uiTestChatId)
                    .environment(\.dynamicTypeSize, ProcessInfo.processInfo.arguments.contains("--ui-test-watch-large-text") ? .accessibility3 : .large)
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

    /// Local payloads exercise the production mobile composition without
    /// granting fixture launches account, network or persistence access.
    private static var uiTestMobilePreviewSnapshot: WatchChatSnapshot {
        let args = ProcessInfo.processInfo.arguments
        let family = args.firstIndex(of: "--ui-test-watch-embed-family")
            .flatMap { args.indices.contains($0 + 1) ? args[$0 + 1] : nil } ?? "spreadsheet"
        let type: EmbedType
        switch family {
        case "website": type = .webWebsite
        case "webVideo": type = .videosVideo
        case "image": type = .image
        case "audioRecording": type = .recording
        case "code": type = .codeCode
        case "pdf": type = .pdf
        case "mapPlace": type = .mapsPlace
        case "searchResults": type = .eventsSearch
        case "travelStay": type = .travelStay
        case "travelConnection": type = .travelConnection
        case "shoppingProduct": type = .shoppingProduct
        case "weather": type = .weatherForecast
        case "reminder": type = .reminderSet
        case "event": type = .eventsEvent
        case "document": type = .docsDoc
        case "mindmap": type = .mindmapsMindmap
        case "audio": type = .audioSpeak
        case "application": type = .mailEmail
        default: type = .sheetsSheet
        }
        let data: [String: AnyCodable] = [
            "title": AnyCodable("devices.xls"), "query": AnyCodable("Public device comparison"),
            "table": AnyCodable("| Device | Type |\n| --- | --- |\n| Nexus Fold X | Phone |\n| Lumina Watch Pro | Watch |\n| AuraBook Air | Laptop |"),
            "row_count": AnyCodable(29), "col_count": AnyCodable(2),
            "code": AnyCodable("let device = \"Watch\"\nlet readable = true"),
            "summary": AnyCodable("A compact public device comparison."),
            "filename": AnyCodable("devices.xls"), "line_count": AnyCodable(2),
            "location_latitude": AnyCodable(52.52), "location_longitude": AnyCodable(13.405),
            "thumbnail_base64": AnyCodable(family == "image" ? "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGPwL73xHwAFTwKctQraKwAAAABJRU5ErkJggg==" : ""),
        ]
        let missing = args.contains("--ui-test-watch-preview-missing-payload")
        let id = "watch-mobile-preview"
        let grouped = args.contains("--ui-test-watch-preview-group")
        var refs = [WatchEmbedRef(id: id, type: type.rawValue, status: "finished", data: missing ? nil : data)]
        if grouped { refs.append(WatchEmbedRef(id: "watch-second-preview", type: type.rawValue,
            status: "finished", data: ["title": AnyCodable("second.xls"), "table": data["table"]!])) }
        let content = grouped ? "Before the previews\n\n[!](embed:\(id))\n\n[!](embed:watch-second-preview)\n\nAfter the previews" : "Hello Watch\n\n[!](embed:\(id))"
        let message = WatchChatMessage(id: "watch-mobile-message", chatId: uiTestChatId,
            role: .assistant, content: content, encryptedContent: nil,
            embedRefs: refs,
            createdAt: "2026-10-03T12:00:00Z", isPending: false)
        return WatchChatSnapshot(chats: [WatchChatSummary(id: uiTestChatId, title: "Mobile previews",
            lastMessageAt: nil, preview: nil, isPinned: false, encryptedTitle: nil,
            encryptedPreview: nil, encryptedChatKey: nil)],
            messagesByChatId: [uiTestChatId: [message]], savedAt: .distantPast)
    }

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
/// Tooling only: separates Crown event delivery from automatic ScrollView focus.
private struct WatchCrownBindingDiagnosticView: View {
    @State private var rotation = 0.0
    @State private var eventCount = 0
    @FocusState private var crownFocused: Bool

    var body: some View {
        VStack(spacing: .spacing3) {
            Text(crownFocused ? "true" : "false")
                .accessibilityIdentifier("watch-crown-binding-focus")
            Text(String(eventCount))
                .accessibilityIdentifier("watch-crown-binding-events")
            Text(String(format: "%.4f", rotation))
                .accessibilityIdentifier("watch-crown-binding-rotation")
        }
        .font(.omSmall)
        .foregroundStyle(Color.grey0)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey100)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-crown-binding-control")
        .focusable()
        .focused($crownFocused)
        .digitalCrownRotation($rotation)
        .onChange(of: rotation) { _, _ in eventCount += 1 }
        .task { crownFocused = true }
    }
}
#endif

#if DEBUG
private struct WatchHubUITestFixtureView: View {
    @State private var openedItem: WatchItemOpenRequest?
    @StateObject private var chatRuntime = WatchChatRuntime(uiTestSnapshot: .empty, selectedChatId: nil)

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
            chatRuntime: chatRuntime,
            currentUserId: WatchWorkflowDetailFixtures.accountID,
            currentAccountID: { WatchWorkflowDetailFixtures.accountID },
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
            workflowDetailService: WatchWorkflowDetailFixtures.service(),
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
