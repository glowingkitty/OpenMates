// Debug-only seeded large chat preview for native chat-opening tests.
// Builds a deterministic in-memory chat with a bounded initial window so XCUITest
// can verify ChatView opens the latest turn without loading the full history.
// This file is compiled in Debug builds only and is never exposed in production.
// It mirrors the web chat-flow surface used by frontend chat-flow specs.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatHistory.svelte
//          frontend/packages/ui/src/components/ChatMessage.svelte
// CSS:     frontend/packages/ui/src/styles/chat.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import SwiftUI

struct DevChatOpeningPreviewView: View {
    private let fixture = DevChatOpeningFixture.make()
    private let forceRecordingOverlay: Bool
    @StateObject private var chatStore = ChatStore()
    @StateObject private var uiTestRecorder = VoiceRecorder()
    @State private var seeded = false
    @State private var reportIssuePrefill: ReportIssuePrefill?

    init(forceRecordingOverlay: Bool = false) {
        self.forceRecordingOverlay = forceRecordingOverlay
    }

    private var initialWindow: [Message] {
        chatStore.initialMessageWindow(for: fixture.chat.id)
    }

    var body: some View {
        Group {
            if isUITestPIIComposerBannerFixtureEnabled {
                DevPIIComposerBannerFixtureView()
            } else if isUITestPIIVisibilityFixtureEnabled {
                DevPIIVisibilityFixtureView()
            } else {
                chatOpeningPreview
            }
        }
        .background(Color.grey0.ignoresSafeArea())
        .accessibilityIdentifier("dev-chat-opening-preview")
        .onAppear(perform: seedIfNeeded)
    }

    private var chatOpeningPreview: some View {
        ZStack(alignment: .bottom) {
            VStack(spacing: 0) {
                if !isUITestVisualSnapshotEnabled {
                    header
                }

                if isUITestResponsiveMetricsEnabled && !isUITestVisualSnapshotEnabled {
                    responsiveMetricsProbe
                }

                if isUITestHeaderContractEnabled && !isUITestVisualSnapshotEnabled {
                    headerContractProbe
                }

                if seeded {
                    ChatView(
                        chatId: fixture.chat.id,
                        bannerState: reportFormBannerState,
                        initialChat: fixture.chat,
                        initialMessages: initialWindow,
                        initialEmbeds: [],
                        chatStore: chatStore,
                        onReportIssue: { reportIssuePrefill = $0 }
                    )
                } else {
                    ProgressView()
                        .tint(.fontSecondary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color.grey20)
                }
            }

            if isUITestRecordingOverlayForced {
                ComposerRecordingOverlay(
                    recorder: uiTestRecorder,
                    dragOffsetX: 0,
                    onStop: { _ in },
                    onCancel: {}
                )
                .frame(maxWidth: 1000)
                .frame(height: 400)
                .padding(.horizontal, .spacing4)
                .padding(.bottom, .spacing3)
            }

            if let reportIssuePrefill {
                ReportIssueView(prefill: reportIssuePrefill)
                    .frame(maxWidth: 360)
                    .frame(maxHeight: .infinity)
                    .background(Color.grey20)
                    .clipShape(RoundedRectangle(cornerRadius: .radius7))
                    .shadow(color: .black.opacity(0.25), radius: 12, x: 0, y: 0)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing8)
                    .accessibilityIdentifier("dev-report-issue-overlay")
            }
        }
    }

    private var header: some View {
        HStack(spacing: .spacing4) {
            VStack(alignment: .leading, spacing: .spacing1) {
                Text("Native Chat Opening Preview")
                    .font(.omH4)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                Text("initial-window-count=\(initialWindow.count); total-message-count=\(fixture.messages.count)")
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("chat-opening-initial-window-count")
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing4)
        .background(Color.grey10)
    }

    private var responsiveMetricsProbe: some View {
        GeometryReader { proxy in
            let metrics = responsiveMetricsLabel(width: proxy.size.width)
            Text(metrics)
                .font(.omMicro)
                .foregroundStyle(Color.fontTertiary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, .spacing5)
                .accessibilityIdentifier("chat-responsive-metrics")
                .accessibilityLabel(metrics)
        }
        .frame(height: 18)
        .background(Color.grey0)
    }

    private var headerContractProbe: some View {
        let iconVisible = fixture.chat.category != nil || fixture.chat.appId != nil
        let contract = "chat-header-title=\(fixture.chat.displayTitle); chat-header-icon=\(iconVisible)"
        return Text(contract)
            .font(.omMicro)
            .foregroundStyle(Color.fontTertiary)
            .lineLimit(1)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, .spacing5)
            .accessibilityIdentifier("chat-header-contract")
            .accessibilityLabel(contract)
    }

    private func seedIfNeeded() {
        guard !seeded else { return }
        chatStore.performWithoutPersistence {
            chatStore.upsertChat(fixture.chat)
            chatStore.setMessages(for: fixture.chat.id, messages: fixture.messages)
        }
        seeded = true
    }

    private var isUITestRecordingOverlayForced: Bool {
        forceRecordingOverlay
            || ProcessInfo.processInfo.arguments.contains("--ui-test-force-recording-overlay")
            || ProcessInfo.processInfo.environment["UI_TEST_FORCE_RECORDING_OVERLAY"] == "1"
    }

    private var isUITestResponsiveMetricsEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-responsive-metrics")
            || ProcessInfo.processInfo.environment["UI_TEST_RESPONSIVE_METRICS"] == "1"
    }

    private var isUITestHeaderContractEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-header-contract")
            || ProcessInfo.processInfo.environment["UI_TEST_HEADER_CONTRACT"] == "1"
    }

    private var isUITestVisualSnapshotEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-visual-snapshot")
            || ProcessInfo.processInfo.environment["UI_TEST_VISUAL_SNAPSHOT"] == "1"
    }

    private var isUITestPIIComposerBannerFixtureEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-pii-composer-banner-fixture")
            || ProcessInfo.processInfo.environment["UI_TEST_PII_COMPOSER_BANNER_FIXTURE"] == "1"
    }

    private var isUITestPIIVisibilityFixtureEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-pii-visibility-fixture")
            || ProcessInfo.processInfo.environment["UI_TEST_PII_VISIBILITY_FIXTURE"] == "1"
    }

    private var isUITestChatReportFormEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-chat-report-form")
            || ProcessInfo.processInfo.environment["UI_TEST_CHAT_REPORT_FORM"] == "1"
    }

    private var reportFormBannerState: ChatBannerState? {
        guard isUITestChatReportFormEnabled else { return nil }
        return .loaded(
            title: fixture.chat.displayTitle,
            appId: fixture.chat.category ?? "ai",
            summary: fixture.chat.chatSummary
        )
    }

    private func responsiveMetricsLabel(width: CGFloat) -> String {
        let assistantStackedBreakpoint: CGFloat = 500
        let inlineNewChatCompactBreakpoint: CGFloat = 550
        let roundedWidth = Int(width.rounded())
        let assistantStacked = width <= assistantStackedBreakpoint
        let inlineNewChatCompact = width <= inlineNewChatCompactBreakpoint
        let sizeClass = width <= inlineNewChatCompactBreakpoint ? "compact" : "regular"
        return "chat-width=\(roundedWidth); assistant-stacked=\(assistantStacked); inline-new-chat-compact=\(inlineNewChatCompact); size-class=\(sizeClass)"
    }
}

private struct DevPIIComposerBannerFixtureView: View {
    @State private var matches: [PIIMatch] = [
        PIIMatch(
            id: "EMAIL:alice@example.com",
            type: .email,
            value: "alice@example.com",
            range: NSRange(location: 6, length: 17),
            placeholder: "[EMAIL_1_com]"
        ),
        PIIMatch(
            id: "PHONE:+49 170 1234567",
            type: .phone,
            value: "+49 170 1234567",
            range: NSRange(location: 33, length: 16),
            placeholder: "[PHONE_1_567]"
        )
    ]

    var body: some View {
        VStack(spacing: .spacing4) {
            Text("Native Chat Opening Preview")
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)

            Text("PII Composer Banner Fixture")
                .font(.omMicro)
                .foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("pii-composer-banner-fixture")

            PIIWarningBanner(matches: matches) {
                matches = []
            }

            PIIHighlightStrip(matches: matches) { match in
                matches.removeAll { $0.id == match.id }
            }

            Spacer()
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Color.grey20)
    }
}

private struct DevPIIVisibilityFixtureView: View {
    private let hiddenContent = "Please email [EMAIL_1_com] the update."
    private let mappings = [
        PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL")
    ]
    @State private var isRevealed = false

    private var displayedContent: String {
        guard isRevealed else { return hiddenContent }
        return PIIDetector.restorePII(in: hiddenContent, mappings: mappings)
    }

    private var toggleLabel: String {
        isRevealed ? AppStrings.piiHide : AppStrings.piiShow
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(spacing: .spacing3) {
                Text("Native Chat Opening Preview")
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.fontPrimary)

                Spacer(minLength: 0)

                Button {
                    isRevealed.toggle()
                } label: {
                    HStack(spacing: .spacing2) {
                        Icon(isRevealed ? "hidden" : "visible", size: 18)
                            .foregroundStyle(LinearGradient.primary)
                        Text(toggleLabel)
                            .font(.omXs.weight(.semibold))
                            .foregroundStyle(Color.fontPrimary)
                    }
                    .padding(.horizontal, .spacing3)
                    .frame(height: 44)
                    .background(Color.grey0.opacity(0.92))
                    .clipShape(Capsule())
                    .shadow(color: .black.opacity(0.18), radius: 12, x: 0, y: 4)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(toggleLabel)
                .accessibilityIdentifier("chat-pii-toggle")
                .accessibilityAddTraits(.isButton)
            }

            Text(displayedContent)
                .font(.omP)
                .foregroundStyle(Color.fontPrimary)
                .accessibilityIdentifier("pii-visibility-fixture-message")

            Spacer()
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.grey20)
    }
}

private struct DevChatOpeningFixture {
    let chat: Chat
    let messages: [Message]

    static func make(messageCount: Int = 250) -> DevChatOpeningFixture {
        if ProcessInfo.processInfo.arguments.contains("--ui-test-pii-visibility-fixture") {
            return piiVisibilityFixture()
        }

        let chatId = "dev-chat-opening-large"
        let messages = (1...messageCount).map { index in
            let id = "seeded-message-\(index)"
            let role: MessageRole = index.isMultiple(of: 2) ? .assistant : .user
            let label = index == messageCount
                ? "Latest assistant response visible after bounded open"
                : "Seeded \(role.rawValue) message \(index)"
            return Message(
                id: id,
                chatId: chatId,
                role: role,
                content: label,
                encryptedContent: nil,
                createdAt: timestamp(for: index),
                updatedAt: nil,
                appId: nil,
                isStreaming: false,
                embedRefs: nil
            )
        }

        let chat = Chat(
            id: chatId,
            title: "Seeded Large Chat",
            lastMessageAt: timestamp(for: messageCount),
            createdAt: timestamp(for: 1),
            updatedAt: timestamp(for: messageCount),
            isArchived: false,
            isPinned: false,
            appId: nil,
            category: "ai",
            icon: "ai",
            chatSummary: "Deterministic large chat for native opening tests.",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: messageCount,
            lastVisibleMessageId: messages.last?.id
        )
        return DevChatOpeningFixture(chat: chat, messages: messages)
    }

    private static func piiVisibilityFixture() -> DevChatOpeningFixture {
        let chatId = "dev-chat-pii-visibility"
        let mappings = [
            PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL")
        ]
        let messages = [
            Message(
                id: "pii-user-1",
                chatId: chatId,
                role: .user,
                content: "Please email [EMAIL_1_com] the update.",
                encryptedContent: nil,
                createdAt: timestamp(for: 1),
                updatedAt: nil,
                appId: nil,
                isStreaming: false,
                embedRefs: nil,
                piiMappings: mappings,
                encryptedPIIMappings: "encrypted-test-mappings"
            ),
            Message(
                id: "pii-assistant-1",
                chatId: chatId,
                role: .assistant,
                content: "I will draft a note for [EMAIL_1_com].",
                encryptedContent: nil,
                createdAt: timestamp(for: 2),
                updatedAt: nil,
                appId: "ai",
                isStreaming: false,
                embedRefs: nil
            )
        ]

        let chat = Chat(
            id: chatId,
            title: "Seeded PII Chat",
            lastMessageAt: timestamp(for: 2),
            createdAt: timestamp(for: 1),
            updatedAt: timestamp(for: 2),
            isArchived: false,
            isPinned: false,
            appId: nil,
            category: "ai",
            icon: "ai",
            chatSummary: "Deterministic PII reveal fixture for native UI tests.",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: messages.count,
            lastVisibleMessageId: messages.last?.id
        )
        return DevChatOpeningFixture(chat: chat, messages: messages)
    }

    private static func timestamp(for index: Int) -> String {
        let minute = index / 60
        let second = index % 60
        return String(format: "2026-01-01T00:%02d:%02dZ", minute, second)
    }
}
#endif
