// Watch chat list, transcript, and composer shell.
// Provides the dark Watch-native chat surface for the standalone watchOS client
// without using stock List/Form/navigation chrome. Runtime state is supplied by
// WatchChatRuntime so this file stays visual and platform-specific.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatHistory.svelte
//          frontend/packages/ui/src/components/ChatMessage.svelte
//          frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/styles/chat.css
//          frontend/packages/ui/src/styles/fields.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import AVFoundation
import SwiftUI

@MainActor
private final class WatchAudioRecorder: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var duration: TimeInterval = 0
    @Published var errorMessage: String?

    private var audioRecorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var timer: Timer?

    func requestPermission() async -> Bool {
        await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
    }

    func startRecording() async {
        errorMessage = nil
        guard await requestPermission() else {
            errorMessage = WatchStrings.microphoneBlocked
            return
        }

        do {
            try AVAudioSession.sharedInstance().setCategory(.playAndRecord, mode: .default)
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            errorMessage = error.localizedDescription
            return
        }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("watch-recording-\(Int(Date().timeIntervalSince1970)).m4a")
        recordingURL = url
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44_100.0,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]

        do {
            audioRecorder = try AVAudioRecorder(url: url, settings: settings)
            audioRecorder?.record()
            isRecording = true
            duration = 0
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.duration += 0.1 }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func stopRecording() -> URL? {
        guard isRecording else { return nil }
        audioRecorder?.stop()
        timer?.invalidate()
        timer = nil
        isRecording = false
        return recordingURL
    }
}

struct WatchChatShellView: View {
    @StateObject private var runtime: WatchChatRuntime
    @StateObject private var phoneBridge = WatchPhoneLoginBridge()

    init(currentUserId: String?, webSocketToken: String?) {
        _runtime = StateObject(wrappedValue: WatchChatRuntime(
            currentUserId: currentUserId,
            syncSession: WatchSyncSession(
                sessionId: WatchCompatibleSession.nativeSessionId,
                token: webSocketToken
            )
        ))
    }

    var body: some View {
        TabView(selection: Binding(
            get: { runtime.selectedChatId == nil ? "list" : "thread" },
            set: { if $0 == "list" { runtime.selectedChatId = nil } }
        )) {
            WatchChatListView(runtime: runtime)
                .tag("list")

            WatchChatThreadView(runtime: runtime)
                .environmentObject(phoneBridge)
                .tag("thread")
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        .task {
            phoneBridge.start { _ in }
            await runtime.loadCachedSnapshot()
            await runtime.startRealtimeSync()
            await runtime.refresh()
        }
        .accessibilityIdentifier("watch-chat-shell")
    }
}

private struct WatchChatListView: View {
    @ObservedObject var runtime: WatchChatRuntime

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .spacing3) {
                WatchChatHeader(title: WatchStrings.newChat, isSyncing: runtime.isSyncing)

                if runtime.isOffline {
                    WatchStatusPill(text: WatchStrings.offlineBanner)
                }

                if runtime.chats.isEmpty && !runtime.isSyncing {
                    Text(WatchStrings.noChats)
                        .font(.omSmall)
                        .foregroundStyle(Color.grey0.opacity(0.76))
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.vertical, .spacing8)
                        .accessibilityIdentifier("watch-chat-empty")
                }

                ForEach(runtime.chats) { chat in
                    Button {
                        Task { await runtime.openChat(chat) }
                    } label: {
                        WatchChatRow(chat: chat)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("watch-chat-row-\(chat.id)")
                }
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing5)
        }
        .background(Color.grey100)
        .accessibilityIdentifier("watch-chat-list")
    }
}

private struct WatchChatThreadView: View {
    @ObservedObject var runtime: WatchChatRuntime
    @EnvironmentObject private var phoneBridge: WatchPhoneLoginBridge
    @StateObject private var audioRecorder = WatchAudioRecorder()
    @State private var draft = ""
    @State private var isPreparingAudio = false

    var body: some View {
        VStack(spacing: .spacing3) {
            HStack(spacing: .spacing2) {
                Button {
                    runtime.selectedChatId = nil
                } label: {
                    Text("‹")
                        .font(.omH2)
                        .foregroundStyle(Color.grey0)
                        .frame(width: .iconSizeMd, height: .iconSizeMd)
                        .background(Color.grey90, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(WatchStrings.back)
                .accessibilityIdentifier("watch-chat-back")

                Text(runtime.selectedChat?.title ?? WatchStrings.untitledChat)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey0)
                    .lineLimit(1)

                Spacer(minLength: 0)
            }
            .padding(.horizontal, .spacing4)
            .padding(.top, .spacing4)

            ScrollView {
                LazyVStack(spacing: .spacing3) {
                    ForEach(runtime.selectedMessages) { message in
                        WatchMessageBubble(message: message) { model in
                            sendEmbedOpenNotification(model)
                        }
                    }
                }
                .padding(.horizontal, .spacing4)
                .padding(.vertical, .spacing2)
            }

            HStack(spacing: .spacing2) {
                Button {
                    Task { await toggleAudioRecording() }
                } label: {
                    Text(audioRecorder.isRecording ? "■" : "●")
                        .font(.omMicro)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.grey0)
                        .frame(width: .iconSizeMd, height: .iconSizeMd)
                        .background(audioRecorder.isRecording ? Color.error : Color.grey90, in: Circle())
                        .overlay(Circle().stroke(Color.grey70, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .disabled(isPreparingAudio)
                .accessibilityIdentifier(audioRecorder.isRecording ? "watch-audio-stop-button" : "watch-audio-record-button")

                TextField(WatchStrings.messagePlaceholder, text: $draft)
                    .font(.omXs)
                    .foregroundStyle(Color.grey0)
                    .tint(Color.buttonPrimary)
                    .padding(.horizontal, .spacing3)
                    .padding(.vertical, .spacing2)
                    .background(Color.grey90, in: Capsule())
                    .overlay(Capsule().stroke(Color.grey70, lineWidth: 1))
                    .accessibilityIdentifier("watch-message-input")

                Button {
                    let text = draft
                    draft = ""
                    Task { await runtime.queueLocalText(text) }
                } label: {
                    Text(WatchStrings.send)
                        .font(.omMicro)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, .spacing3)
                        .padding(.vertical, .spacing2)
                        .background(Color.buttonPrimary, in: Capsule())
                }
                .buttonStyle(.plain)
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .opacity(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.45 : 1)
                .accessibilityIdentifier("watch-message-send")
            }
            .padding(.horizontal, .spacing4)

            if isPreparingAudio {
                WatchStatusPill(text: WatchStrings.transcribing)
                    .padding(.horizontal, .spacing4)
                    .accessibilityIdentifier("watch-audio-transcribing")
            }

            if let errorMessage = audioRecorder.errorMessage ?? runtime.errorMessage, !errorMessage.isEmpty {
                WatchStatusPill(text: errorMessage)
                    .padding(.horizontal, .spacing4)
                    .accessibilityIdentifier("watch-audio-error")
            }

            ForEach(runtime.pendingAudioEmbeds) { embed in
                WatchPendingAudioEmbedView(embed: embed)
                    .padding(.horizontal, .spacing4)
            }

            if audioRecorder.isRecording {
                Text(WatchStrings.recordingDuration(seconds: audioRecorder.duration))
                    .font(.omMicro)
                    .foregroundStyle(Color.grey30)
                    .accessibilityIdentifier("watch-audio-recording-duration")
            }
        }
        .padding(.bottom, .spacing4)
        .background(Color.grey100)
        .accessibilityIdentifier("watch-chat-thread")
    }

    private func toggleAudioRecording() async {
        if audioRecorder.isRecording {
            guard let url = audioRecorder.stopRecording(),
                  let data = try? Data(contentsOf: url) else { return }
            isPreparingAudio = true
            _ = await runtime.prepareAudioRecording(
                data: data,
                filename: url.lastPathComponent,
                duration: audioRecorder.duration
            )
            isPreparingAudio = false
        } else {
            await audioRecorder.startRecording()
        }
    }

    private func sendEmbedOpenNotification(_ model: WatchEmbedPreviewModel) {
        guard let request = WatchEmbedOpenRequest(
            chatId: model.continuation.chatId ?? runtime.selectedChatId,
            embedId: model.id
        ) else { return }
        phoneBridge.sendEmbedOpenRequest(request)
    }
}

private struct WatchPendingAudioEmbedView: View {
    let embed: WatchPendingAudioEmbed

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(WatchStrings.voiceRecording)
                .font(.omMicro)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey30)
            Text(embed.transcript ?? embed.filename)
                .font(.omXs)
                .foregroundStyle(Color.grey0)
                .lineLimit(2)
        }
        .padding(.horizontal, .spacing3)
        .padding(.vertical, .spacing2)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey90, in: RoundedRectangle(cornerRadius: .radius6, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: .radius6, style: .continuous)
                .stroke(Color.buttonPrimary.opacity(0.55), lineWidth: 1)
        )
        .accessibilityIdentifier("watch-pending-audio-embed")
    }
}

private struct WatchChatHeader: View {
    let title: String
    let isSyncing: Bool

    var body: some View {
        HStack(spacing: .spacing3) {
            Circle()
                .fill(LinearGradient.primary)
                .frame(width: .iconSizeLg, height: .iconSizeLg)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey0)
                Text(isSyncing ? WatchStrings.syncing : WatchStrings.loadingChats)
                    .font(.omMicro)
                    .foregroundStyle(Color.grey30)
            }
        }
    }
}

private struct WatchChatRow: View {
    let chat: WatchChatSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            HStack(spacing: .spacing2) {
                Text(chat.title ?? WatchStrings.untitledChat)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey0)
                    .lineLimit(1)
                if chat.isPinned {
                    Circle()
                        .fill(Color.buttonPrimary)
                        .frame(width: 5, height: 5)
                        .accessibilityHidden(true)
                }
            }
            Text(chat.preview ?? WatchStrings.clientEncrypted)
                .font(.omMicro)
                .foregroundStyle(Color.grey30)
                .lineLimit(2)
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey90, in: RoundedRectangle(cornerRadius: .radius6, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: .radius6, style: .continuous)
                .stroke(Color.grey80, lineWidth: 1)
        )
    }
}

private struct WatchMessageBubble: View {
    let message: WatchChatMessage
    let onOpenEmbed: (WatchEmbedPreviewModel) -> Void

    private var isUser: Bool { message.role == .user }
    private var embedRecords: [EmbedRecord] { message.watchEmbedRecords }
    private var embedLookup: [String: EmbedRecord] {
        EmbedRecord.dictionaryById(embedRecords, context: "watchMessageBubble") { _ in }
    }
    private var embedPreviews: [WatchEmbedPreviewModel] {
        embedRecords.map {
            WatchEmbedPreviewMapper.makeModel(
                for: $0,
                chatId: message.chatId,
                allEmbedRecords: embedLookup
            )
        }
    }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: .spacing5) }
            VStack(alignment: .leading, spacing: .spacing2) {
                if let displayContent = message.watchDisplayContent {
                    Text(displayContent)
                        .font(.omXs)
                        .foregroundStyle(isUser ? Color.grey100 : Color.fontPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                } else if embedPreviews.isEmpty {
                    Text(WatchStrings.clientEncrypted)
                        .font(.omXs)
                        .foregroundStyle(isUser ? Color.grey100 : Color.fontPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                ForEach(embedPreviews) { preview in
                    WatchEmbedPreviewCard(model: preview) {
                        onOpenEmbed(preview)
                    }
                }

                if message.isPending {
                    Text(WatchStrings.pendingSend)
                        .font(.omMicro)
                        .foregroundStyle(isUser ? Color.grey80 : Color.grey40)
                }
            }
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .background(isUser ? Color.greyBlue : Color.grey0, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
            if !isUser { Spacer(minLength: .spacing5) }
        }
    }
}

private struct WatchEmbedPreviewCard: View {
    let model: WatchEmbedPreviewModel
    let onOpen: () -> Void

    var body: some View {
        Button(action: onOpen) {
            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: .spacing2) {
                    HStack(alignment: .top, spacing: .spacing2) {
                        AppIconView(appId: model.appId, size: 28)
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(model.typeLabel)
                                .font(.omMicro)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.fontSecondary)
                                .lineLimit(1)
                            Text(model.title)
                                .font(.omXs)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.fontPrimary)
                                .lineLimit(2)
                        }
                    }

                    if let subtitle = model.subtitle ?? model.detail {
                        Text(subtitle)
                            .font(.omMicro)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(2)
                    }

                    Spacer(minLength: 0)
                }
                .padding(.spacing3)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

                HStack(spacing: .spacing2) {
                    statusDot
                    Text(WatchStrings.embedTapToShowDetails)
                        .font(.omMicro)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontButton)
                        .lineLimit(1)
                }
                .padding(.horizontal, .spacing3)
                .padding(.vertical, .spacing2)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.buttonPrimary)
            }
            .frame(width: WatchEmbedPreviewModel.cardWidth, height: WatchEmbedPreviewModel.cardHeight)
            .background(Color.grey25)
            .clipShape(RoundedRectangle(cornerRadius: .radius6, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: .radius6, style: .continuous)
                    .stroke(model.state == .error ? Color.error : Color.grey30, lineWidth: 1)
            )
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("watch-embed-preview")
            .accessibilityLabel(model.title)
            .accessibilityValue(model.typeLabel)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("watch-embed-notification-request")
    }

    private var statusDot: some View {
        Circle()
            .fill(statusColor)
            .frame(width: 6, height: 6)
            .accessibilityHidden(true)
    }

    private var statusColor: Color {
        switch model.state {
        case .ready: return Color.grey0
        case .processing: return Color.warning
        case .error: return Color.error
        }
    }
}

private struct WatchStatusPill: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.omMicro)
            .foregroundStyle(Color.grey0)
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey90, in: Capsule())
            .overlay(Capsule().stroke(Color.buttonPrimary.opacity(0.55), lineWidth: 1))
    }
}
