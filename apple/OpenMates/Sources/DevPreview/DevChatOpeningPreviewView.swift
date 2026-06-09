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
    @StateObject private var chatStore = ChatStore()
    @StateObject private var uiTestRecorder = VoiceRecorder()
    @State private var seeded = false

    private var initialWindow: [Message] {
        chatStore.initialMessageWindow(for: fixture.chat.id)
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            VStack(spacing: 0) {
                header

                if seeded {
                    ChatView(
                        chatId: fixture.chat.id,
                        initialChat: fixture.chat,
                        initialMessages: initialWindow,
                        initialEmbeds: [],
                        chatStore: chatStore
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
        }
        .background(Color.grey0.ignoresSafeArea())
        .accessibilityIdentifier("dev-chat-opening-preview")
        .onAppear(perform: seedIfNeeded)
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

    private func seedIfNeeded() {
        guard !seeded else { return }
        chatStore.performWithoutPersistence {
            chatStore.upsertChat(fixture.chat)
            chatStore.setMessages(for: fixture.chat.id, messages: fixture.messages)
        }
        seeded = true
    }

    private var isUITestRecordingOverlayForced: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-force-recording-overlay")
            || ProcessInfo.processInfo.environment["UI_TEST_FORCE_RECORDING_OVERLAY"] == "1"
    }
}

private struct DevChatOpeningFixture {
    let chat: Chat
    let messages: [Message]

    static func make(messageCount: Int = 250) -> DevChatOpeningFixture {
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

    private static func timestamp(for index: Int) -> String {
        let minute = index / 60
        let second = index % 60
        return String(format: "2026-01-01T00:%02d:%02dZ", minute, second)
    }
}
#endif
