// Watch chat runtime and offline cache.
// Provides the portable data layer for the standalone watchOS chat shell while
// staying small enough to unit test from the existing Apple unit-test target.
// The runtime fetches recent chats/messages directly from the backend, unwraps
// per-chat keys from the Watch-local master key, and keeps a local JSON snapshot
// for offline startup. This layer never logs plaintext.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.browse-search-open, apple-watch.chats.new-text-reply

import CryptoKit
import Foundation
import SwiftUI

enum WatchUIContract {
    static let pairLoginIdentifiers = [
        "watch-pair-login",
        "watch-pair-confirm-iphone-title",
        "watch-pair-confirm-iphone-description",
        "watch-pair-manual-fallback",
        "watch-pair-login-without-iphone-button",
        "watch-pair-token",
        "watch-pair-url",
        "watch-pair-waiting-label",
        "watch-pair-pin-input",
        "watch-pair-refresh-button",
        "watch-pair-self-host-button",
        "watch-pair-self-host-input",
        "watch-pair-self-host-connect-button",
        "watch-pair-self-host-cancel-button",
        "watch-pair-self-host-error",
        "watch-pair-use-production-button",
    ]

    static let chatFlowIdentifiers = [
        "watch-chat-shell",
        "watch-chat-list",
        "watch-chat-search-button",
        "watch-chat-search-input",
        "watch-chat-settings-button",
        "watch-chat-row-<id>",
        "watch-chat-thread",
        "watch-message-input",
        "watch-message-send",
        "watch-new-chat-button",
        "watch-audio-record-button",
        "watch-audio-send-button",
    ]

    static let audioComposerIdentifiers = [
        "watch-audio-record-button",
        "watch-audio-stop-button",
        "watch-audio-recording-screen",
        "watch-audio-recording-duration",
        "watch-audio-cancel-button",
        "watch-audio-transcribing",
        "watch-audio-send-button",
        "watch-audio-error",
    ]

    static let embedPreviewIdentifiers = [
        "watch-embed-preview",
        "watch-embed-continuation",
        "watch-embed-open-device",
        "watch-embed-qr-payload",
        "watch-embed-notification-request",
    ]

    static let forbiddenProductChrome = [
        "List",
        "Form",
        "NavigationStack",
        "TabView",
        "navigationTitle",
        "toolbar",
    ]

    static let designEvidence = [
        "Dark Watch shell uses Color.grey100, Color.grey90, Color.grey0, Color.buttonPrimary, and generated spacing/typography tokens.",
        "Chat and embed surfaces use ScrollView/LazyVStack/custom buttons instead of List, Form, default navigation chrome, or stock product controls.",
        "Embed previews preserve OpenMates app/embed semantics through WatchEmbedPreviewModel and route detail actions to continuation metadata instead of rich fullscreen Watch consumption.",
        "Audio recording uploads and transcribes on the server, then sends one encrypted audio-recording embed turn.",
    ]
}

struct WatchChatSummary: Codable, Equatable, Identifiable, Sendable {
    let id: String
    var title: String?
    var lastMessageAt: String?
    var preview: String?
    var isPinned: Bool
    var encryptedTitle: String?
    var encryptedPreview: String?
    var encryptedChatKey: String?
    var messagesV: Int = 0
    var titleV: Int = 0
    var metadataV: Int = 0

    init(id: String, title: String?, lastMessageAt: String?, preview: String?, isPinned: Bool,
         encryptedTitle: String?, encryptedPreview: String?, encryptedChatKey: String?,
         messagesV: Int = 0, titleV: Int = 0, metadataV: Int = 0) {
        self.id = id; self.title = title; self.lastMessageAt = lastMessageAt
        self.preview = preview; self.isPinned = isPinned; self.encryptedTitle = encryptedTitle
        self.encryptedPreview = encryptedPreview; self.encryptedChatKey = encryptedChatKey
        self.messagesV = messagesV; self.titleV = titleV; self.metadataV = metadataV
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, lastMessageAt, preview, isPinned, encryptedTitle, encryptedPreview,
             encryptedChatKey, messagesV, titleV, metadataV
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(id: try c.decode(String.self, forKey: .id),
                  title: try c.decodeIfPresent(String.self, forKey: .title),
                  lastMessageAt: try c.decodeIfPresent(String.self, forKey: .lastMessageAt),
                  preview: try c.decodeIfPresent(String.self, forKey: .preview),
                  isPinned: try c.decode(Bool.self, forKey: .isPinned),
                  encryptedTitle: try c.decodeIfPresent(String.self, forKey: .encryptedTitle),
                  encryptedPreview: try c.decodeIfPresent(String.self, forKey: .encryptedPreview),
                  encryptedChatKey: try c.decodeIfPresent(String.self, forKey: .encryptedChatKey),
                  messagesV: try c.decodeIfPresent(Int.self, forKey: .messagesV) ?? 0,
                  titleV: try c.decodeIfPresent(Int.self, forKey: .titleV) ?? 0,
                  metadataV: try c.decodeIfPresent(Int.self, forKey: .metadataV) ?? 0)
    }
}

struct WatchChatMessage: Codable, Equatable, Identifiable, Sendable {
    enum Role: String, Codable, Sendable {
        case user
        case assistant
        case system
    }

    let id: String
    let chatId: String
    let role: Role
    var content: String?
    var encryptedContent: String?
    var embedRefs: [WatchEmbedRef]? = nil
    let createdAt: String
    var isPending: Bool
}

struct WatchEmbedRef: Codable, Equatable, Identifiable, @unchecked Sendable {
    let id: String
    let type: String
    let status: String?
    let data: [String: AnyCodable]?
}

struct WatchPendingTextSend: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let chatId: String
    let messageId: String
    let encryptedContent: String
    let encryptedChatKey: String
    let createdAt: String
    var preflightJSON: Data = Data()
    var inferenceJSON: Data = Data()

    init(id: String, chatId: String, messageId: String, encryptedContent: String,
         encryptedChatKey: String, createdAt: String, preflightJSON: Data = Data(),
         inferenceJSON: Data = Data()) {
        self.id = id; self.chatId = chatId; self.messageId = messageId
        self.encryptedContent = encryptedContent; self.encryptedChatKey = encryptedChatKey
        self.createdAt = createdAt; self.preflightJSON = preflightJSON
        self.inferenceJSON = inferenceJSON
    }

    private enum CodingKeys: String, CodingKey {
        case id, chatId, messageId, encryptedContent, encryptedChatKey,
             createdAt, preflightJSON, inferenceJSON
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(id: try c.decode(String.self, forKey: .id),
                  chatId: try c.decode(String.self, forKey: .chatId),
                  messageId: try c.decode(String.self, forKey: .messageId),
                  encryptedContent: try c.decode(String.self, forKey: .encryptedContent),
                  encryptedChatKey: try c.decode(String.self, forKey: .encryptedChatKey),
                  createdAt: try c.decode(String.self, forKey: .createdAt),
                  preflightJSON: try c.decodeIfPresent(Data.self, forKey: .preflightJSON) ?? Data(),
                  inferenceJSON: try c.decodeIfPresent(Data.self, forKey: .inferenceJSON) ?? Data())
    }
}

struct WatchUploadedFileVariant: Codable, Equatable, Sendable {
    let s3Key: String
    let sizeBytes: Int?
    let width: Int?
    let height: Int?
    let format: String?
}

struct WatchUploadedAudio: Codable, Equatable, Sendable {
    let embedId: String
    let filename: String
    let contentType: String
    let contentHash: String?
    let files: [String: WatchUploadedFileVariant]
    let s3BaseUrl: String
    let aesKey: String
    let aesNonce: String
    let vaultWrappedAesKey: String
}

struct WatchTranscriptionWaveform: Decodable, Equatable, Sendable {
    let version: Int
    let kind: String
    let samples: [Int]
    let durationSeconds: TimeInterval?

    var contentObject: [String: Any] {
        var value: [String: Any] = ["version": version, "kind": kind, "samples": samples]
        if let durationSeconds { value["duration_seconds"] = durationSeconds }
        return value
    }
}

struct WatchTranscriptionMetadata: Decodable, Equatable, Sendable {
    let title: String?
    let transcript: String?
    let transcriptOriginal: String?
    let transcriptCorrected: String?
    let useCorrected: Bool?
    let model: String?
    let correctionModel: String?
    let waveform: WatchTranscriptionWaveform?

    var displayTranscript: String? {
        if useCorrected == true, let transcriptCorrected, !transcriptCorrected.isEmpty {
            return transcriptCorrected
        }
        return transcript
    }
}

struct WatchPendingAudioEmbed: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let filename: String
    let transcript: String?
    let duration: TimeInterval
    let content: String

    var markdownReference: String {
        "```json\n{\"type\": \"audio-recording\", \"embed_id\": \"\(id)\"}\n```"
    }

    static func from(upload: WatchUploadedAudio, transcription: WatchTranscriptionMetadata?, duration: TimeInterval) -> WatchPendingAudioEmbed {
        let contentObject = audioContentObject(upload: upload, transcription: transcription, duration: duration)
        return WatchPendingAudioEmbed(
            id: upload.embedId,
            filename: upload.filename,
            transcript: transcription?.displayTranscript,
            duration: duration,
            content: jsonString(contentObject)
        )
    }

    private static func audioContentObject(
        upload: WatchUploadedAudio,
        transcription: WatchTranscriptionMetadata?,
        duration: TimeInterval
    ) -> [String: Any] {
        var object: [String: Any] = [
            "app_id": "audio",
            "type": "audio-recording",
            "status": "finished",
            "filename": upload.filename,
            "s3_base_url": upload.s3BaseUrl,
            "files": upload.files.mapValues { variant in
                var item: [String: Any] = ["s3_key": variant.s3Key]
                if let sizeBytes = variant.sizeBytes { item["size_bytes"] = sizeBytes }
                if let width = variant.width { item["width"] = width }
                if let height = variant.height { item["height"] = height }
                if let format = variant.format { item["format"] = format }
                return item
            },
            "aes_key": upload.aesKey,
            "aes_nonce": upload.aesNonce,
            "vault_wrapped_aes_key": upload.vaultWrappedAesKey,
            "skill_id": "transcribe",
            "duration": duration,
        ]
        if let contentHash = upload.contentHash { object["content_hash"] = contentHash }
        if let transcription {
            if let title = transcription.title { object["title"] = title }
            if let transcript = transcription.transcript { object["transcript"] = transcript }
            if let display = transcription.displayTranscript { object["transcription"] = display }
            if let original = transcription.transcriptOriginal { object["transcript_original"] = original }
            if let corrected = transcription.transcriptCorrected { object["transcript_corrected"] = corrected }
            if let useCorrected = transcription.useCorrected { object["use_corrected"] = useCorrected }
            if let model = transcription.model { object["model"] = model }
            if let correctionModel = transcription.correctionModel { object["correction_model"] = correctionModel }
            if let waveform = transcription.waveform { object["waveform"] = waveform.contentObject }
        }
        return object
    }

    private static func jsonString(_ object: [String: Any]) -> String {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
              let string = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return string
    }
}

struct WatchChatSnapshot: Codable, Equatable, Sendable {
    var chats: [WatchChatSummary]
    var messagesByChatId: [String: [WatchChatMessage]]
    var pendingTextSends: [WatchPendingTextSend]
    var pendingAudioEmbeds: [WatchPendingAudioEmbed]
    var savedAt: Date

    static let empty = WatchChatSnapshot(
        chats: [],
        messagesByChatId: [:],
        pendingTextSends: [],
        pendingAudioEmbeds: [],
        savedAt: .distantPast
    )

    init(
        chats: [WatchChatSummary],
        messagesByChatId: [String: [WatchChatMessage]],
        pendingTextSends: [WatchPendingTextSend] = [],
        pendingAudioEmbeds: [WatchPendingAudioEmbed] = [],
        savedAt: Date
    ) {
        self.chats = chats
        self.messagesByChatId = messagesByChatId
        self.pendingTextSends = pendingTextSends
        self.pendingAudioEmbeds = pendingAudioEmbeds
        self.savedAt = savedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        chats = try container.decode([WatchChatSummary].self, forKey: .chats)
        messagesByChatId = try container.decode([String: [WatchChatMessage]].self, forKey: .messagesByChatId)
        pendingTextSends = try container.decodeIfPresent([WatchPendingTextSend].self, forKey: .pendingTextSends) ?? []
        pendingAudioEmbeds = try container.decodeIfPresent([WatchPendingAudioEmbed].self, forKey: .pendingAudioEmbeds) ?? []
        savedAt = try container.decode(Date.self, forKey: .savedAt)
    }
}

struct WatchSyncSession: Equatable, Sendable {
    let sessionId: String
    let token: String?
}

struct WatchSyncClientState: Equatable, Sendable {
    let clientChatVersions: [String: [String: Int]]
    let clientChatIds: [String]
    let clientSuggestionsCount: Int
    let clientEmbedIds: [String]
}

// Mirrors ChatKeyWrapperRecord selection for the Watch target, which does not
// compile ChatKeyManager.swift.
struct WatchChatKeyWrapperRecord: Decodable, Sendable {
    let id: String?
    let hashedChatId: String
    let keyType: String
    let encryptedChatKey: String
    let wrapperVersion: Int?
    let createdAt: String?

    static func orderedMasterWrappers(_ wrappers: [Self], for chatId: String) -> [Self] {
        let hash = hashedChatId(for: chatId)
        return wrappers
            .filter { $0.keyType == "master" && $0.hashedChatId == hash && !$0.encryptedChatKey.isEmpty }
            .sorted {
                ($0.wrapperVersion ?? 0, $0.createdAt ?? "", $0.id ?? "") >
                    ($1.wrapperVersion ?? 0, $1.createdAt ?? "", $1.id ?? "")
            }
    }

    static func hashedChatId(for chatId: String) -> String {
        SHA256.hash(data: Data(chatId.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

struct WatchRemoteChat: Sendable {
    let id: String
    let title: String?
    let lastMessageAt: String?
    let updatedAt: String?
    let chatSummary: String?
    let isPinned: Bool
    let encryptedTitle: String?
    let encryptedChatSummary: String?
    let encryptedChatKey: String?
    var chatKeyWrappers: [WatchChatKeyWrapperRecord] = []
    var messagesV: Int = 0
    var titleV: Int = 0
    var metadataV: Int = 0
}

struct WatchRemoteMessage: Equatable, Sendable {
    let id: String
    let chatId: String
    let role: WatchChatMessage.Role
    let content: String?
    let encryptedContent: String?
    let embedRefs: [WatchEmbedRef]?
    let createdAt: String

    init(
        id: String,
        chatId: String,
        role: WatchChatMessage.Role,
        content: String?,
        encryptedContent: String?,
        embedRefs: [WatchEmbedRef]? = nil,
        createdAt: String
    ) {
        self.id = id
        self.chatId = chatId
        self.role = role
        self.content = content
        self.encryptedContent = encryptedContent
        self.embedRefs = embedRefs
        self.createdAt = createdAt
    }
}

protocol WatchChatAPI: Sendable {
    func fetchRecentChats(limit: Int, offset: Int) async throws -> [WatchRemoteChat]
    func fetchMessages(chatId: String) async throws -> [WatchRemoteMessage]
    func fetchMessagesVersion(chatId: String) async throws -> Int?
    func uploadAudioRecording(data: Data, filename: String, chatId: String) async throws -> WatchUploadedAudio
    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String) async throws -> WatchTranscriptionMetadata?
}

@MainActor
protocol WatchChatSyncSocket: AnyObject {
    func connect(session: WatchSyncSession, syncState: WatchSyncClientState)
    func disconnect()
    func sendTurn(_ pending: WatchPendingTextSend) async throws
    func setChangeHandler(_ handler: (@MainActor () -> Void)?)
}

@MainActor
protocol WatchChatCrypto: AnyObject {
    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary?
    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage
    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String
    func createChat() async throws -> WatchChatSummary
    func recoveryPublicKey(for chat: WatchChatSummary) async throws -> String
    func encryptedAudioEmbed(_ embed: WatchPendingAudioEmbed, chat: WatchChatSummary, messageId: String) async throws -> [[String: Any]]
}

actor WatchChatOfflineCache {
    private let fileURL: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(directory: URL? = nil) {
        self.fileURL = (directory ?? WatchChatOfflineCache.defaultDirectory())
            .appendingPathComponent("watch-chat-snapshot.json")
        self.encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    func loadSnapshot() -> WatchChatSnapshot {
        guard let data = try? Data(contentsOf: fileURL),
              let snapshot = try? decoder.decode(WatchChatSnapshot.self, from: data) else {
            return .empty
        }
        return snapshot
    }

    func saveSnapshot(_ snapshot: WatchChatSnapshot) throws {
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let data = try encoder.encode(snapshot)
        try data.write(to: fileURL, options: [.atomic, .completeFileProtection])
    }

    func removeSnapshot() throws {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        try FileManager.default.removeItem(at: fileURL)
    }

    static func defaultDirectory() -> URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OpenMatesWatch", isDirectory: true)
    }
}

@MainActor
final class WatchChatRuntime: ObservableObject {
    @Published private(set) var chats: [WatchChatSummary] = []
    @Published private(set) var messagesByChatId: [String: [WatchChatMessage]] = [:]
    @Published var selectedChatId: String?
    @Published private(set) var isSyncing = false
    @Published private(set) var isOffline = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var pendingAudioEmbeds: [WatchPendingAudioEmbed] = []
    @Published private(set) var unavailableChatCount = 0

    private let api: any WatchChatAPI
    private let cache: WatchChatOfflineCache
    private let crypto: any WatchChatCrypto
    private let syncSocket: (any WatchChatSyncSocket)?
    private let syncSession: WatchSyncSession?
    private var isSending = false
    private var pendingTextSends: [WatchPendingTextSend] = []
    private static let incognitoChatIdPrefix = "incognito-"
    // The chat endpoint caps each request at 100. Fetch every page so local
    // search can find older encrypted titles after client-side decryption.
    private static let chatFetchLimit = 100
    private static let fetchRetryAttempts = 4
    private static let fetchRetryDelayNanoseconds: UInt64 = 750_000_000

    init(
        currentUserId: String? = nil,
        api: any WatchChatAPI = APIClient.shared,
        cache: WatchChatOfflineCache = WatchChatOfflineCache(),
        crypto: (any WatchChatCrypto)? = nil,
        syncSocket: (any WatchChatSyncSocket)? = WatchRealtimeSyncSocket(),
        syncSession: WatchSyncSession? = nil
    ) {
        self.api = api
        self.cache = cache
        self.crypto = crypto ?? WatchChatCryptoService(currentUserId: currentUserId)
        self.syncSocket = syncSocket
        self.syncSession = syncSession
    }

#if DEBUG
    init(uiTestSnapshot snapshot: WatchChatSnapshot, selectedChatId: String?) {
        self.api = APIClient.shared
        self.cache = WatchChatOfflineCache()
        self.crypto = WatchChatCryptoService(currentUserId: nil)
        self.syncSocket = nil
        self.syncSession = nil
        self.chats = snapshot.chats
        self.messagesByChatId = snapshot.messagesByChatId
        self.pendingTextSends = snapshot.pendingTextSends
        self.pendingAudioEmbeds = snapshot.pendingAudioEmbeds
        self.selectedChatId = selectedChatId
    }
#endif

    var selectedChat: WatchChatSummary? {
        guard let selectedChatId else { return nil }
        return chats.first { $0.id == selectedChatId }
    }

    var selectedMessages: [WatchChatMessage] {
        guard let selectedChatId else { return [] }
        return messagesByChatId[selectedChatId] ?? []
    }

    func loadCachedSnapshot() async {
        apply(await cache.loadSnapshot())
    }

    func refresh() async {
        isSyncing = true
        errorMessage = nil
        if chats.isEmpty {
            await loadCachedSnapshot()
        }

        var failurePhase = "fetch"
        do {
            var fetchedChats: [WatchRemoteChat] = []
            while true {
                let offset = fetchedChats.count
                let page = try await fetchWithRetry {
                    try await api.fetchRecentChats(limit: Self.chatFetchLimit, offset: offset)
                }
                fetchedChats.append(contentsOf: page)
                if page.count < Self.chatFetchLimit { break }
            }
            let remote = Self.sortedChats(await decryptChats(fetchedChats))
            unavailableChatCount = fetchedChats.count - remote.count
            NativeDiagnostics.event("refresh", category: "watch_chat", counts: [
                "fetched": fetchedChats.count, "decrypted": remote.count,
                "unavailable_key": unavailableChatCount,
            ])
            if unavailableChatCount > 0 {
                NativeDiagnostics.event("decrypt_key_unavailable", category: "watch_chat", level: .warning,
                                        counts: ["count": unavailableChatCount])
            }
            let remoteIds = Set(remote.map(\.id))
            let pendingChatIds = Set(pendingTextSends.map(\.chatId))
            let localRetained = chats.filter { chat in
                !remoteIds.contains(chat.id) && (
                    pendingChatIds.contains(chat.id)
                    || (chat.messagesV == 0 && messagesByChatId[chat.id] != nil)
                )
            }
            chats = Self.sortedChats(remote + localRetained)
            isOffline = false
            await replayPendingTextSends()
            failurePhase = "persist"
            try await persistSnapshot()
        } catch {
            NativeDiagnostics.failure("\(failurePhase)_failed", category: "watch_chat", level: .warning, error: error)
            unavailableChatCount = 0
            isOffline = true
            errorMessage = error.localizedDescription
            if chats.isEmpty {
                await loadCachedSnapshot()
            }
        }
        isSyncing = false
    }

    func startRealtimeSync() async {
        guard let syncSocket, let syncSession else { return }
        syncSocket.setChangeHandler { [weak self] in
            guard let self else { return }
            Task { await self.refreshSelectedChat() }
        }
        syncSocket.connect(session: syncSession, syncState: makeSyncClientState())
    }

    func openChat(_ chat: WatchChatSummary) async {
        selectedChatId = chat.id
        if messagesByChatId[chat.id] == nil {
            let snapshot = await cache.loadSnapshot()
            messagesByChatId[chat.id] = snapshot.messagesByChatId[chat.id]
        }
        if chat.messagesV == 0 && messagesByChatId[chat.id] == [] { return }

        do {
            let messages = try await fetchWithRetry {
                try await api.fetchMessages(chatId: chat.id)
            }
            messagesByChatId[chat.id] = Self.sortedMessages(await decryptMessages(messages))
            let authoritativeVersion = try? await api.fetchMessagesVersion(chatId: chat.id)
            if let index = chats.firstIndex(where: { $0.id == chat.id }) {
                chats[index].messagesV = max(chats[index].messagesV, authoritativeVersion ?? messages.count)
            }
            isOffline = false
            errorMessage = nil
            try await persistSnapshot()
        } catch {
            isOffline = true
            errorMessage = error.localizedDescription
        }
    }

    func createNewChat() async {
        do {
            let chat = try await crypto.createChat()
            chats.insert(chat, at: 0)
            messagesByChatId[chat.id] = []
            selectedChatId = chat.id
            errorMessage = nil
            try await persistSnapshot()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @discardableResult
    func sendText(_ content: String) async -> Bool {
        guard let chat = selectedChat else {
            errorMessage = WatchChatRuntimeError.noSelectedChat.localizedDescription
            return false
        }
        return await send(content: content, chat: chat, embed: nil)
    }

    @discardableResult
    func sendAudioRecording(data: Data, filename: String, duration: TimeInterval) async -> Bool {
        guard let chat = selectedChat else {
            errorMessage = WatchChatRuntimeError.noSelectedChat.localizedDescription
            return false
        }
        guard !data.isEmpty, duration > 0 else {
            errorMessage = WatchChatRuntimeError.invalidRecording.localizedDescription
            return false
        }
        do {
            let upload = try await api.uploadAudioRecording(data: data, filename: filename, chatId: chat.id)
            let transcription = try await api.transcribeAudioRecording(upload, chatId: chat.id)
            let embed = WatchPendingAudioEmbed.from(upload: upload, transcription: transcription, duration: duration)
            return await send(content: embed.markdownReference, chat: chat, embed: embed)
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    private func send(content: String, chat: WatchChatSummary, embed: WatchPendingAudioEmbed?) async -> Bool {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = WatchChatRuntimeError.noSelectedChat.localizedDescription
            return false
        }
        guard let encryptedChatKey = chat.encryptedChatKey else {
            errorMessage = WatchChatRuntimeError.missingChatKey.localizedDescription
            return false
        }
        guard !isSending, pendingTextSends.isEmpty else {
            errorMessage = WatchChatRuntimeError.sendInProgress.localizedDescription
            return false
        }
        isSending = true
        defer { isSending = false }
        var queued = false
        do {
            guard let syncSocket, syncSession != nil else { throw WatchChatRuntimeError.socketUnavailable }
            let now = Date()
            let createdAt = ISO8601DateFormatter().string(from: now)
            let createdAtUnix = Int(now.timeIntervalSince1970)
            let messageId = UUID().uuidString.lowercased()
            let turnId = UUID().uuidString.lowercased()
            let encryptedContent = try await crypto.encryptText(trimmed, for: chat)
            let recoveryPublicKey = try await crypto.recoveryPublicKey(for: chat)
            let existing = messagesByChatId[chat.id] ?? []
            let expectedVersion = max(chat.messagesV, existing.filter { !$0.isPending }.count)
            let titleVersion = max(chat.titleV, chat.title?.isEmpty == false ? 1 : 0)
            let metadataVersion = max(chat.metadataV, titleVersion)
            var message: [String: Any] = [
                "message_id": messageId, "role": "user", "content": trimmed,
                "created_at": createdAtUnix, "sender_name": "user",
                "chat_has_title": titleVersion > 0, "current_chat_title_v": titleVersion,
                "current_chat_metadata_v": metadataVersion
            ]
            if titleVersion > 0, let title = chat.title { message["current_chat_title"] = title }
            var inference: [String: Any] = [
                "chat_id": chat.id, "message": message,
                "encrypted_chat_key": encryptedChatKey, "broadcast": false,
                "turn_id": turnId, "recovery_public_key": recoveryPublicKey,
                "chat_key_version": 1
            ]
            let history = try Self.historyPayload(existing + [WatchChatMessage(
                id: messageId, chatId: chat.id, role: .user, content: trimmed,
                encryptedContent: encryptedContent, embedRefs: nil,
                createdAt: createdAt, isPending: true
            )])
            if !existing.isEmpty { inference["message_history"] = history }
            if let embed {
                inference["embeds"] = [[
                    "embed_id": embed.id, "type": "audio-recording", "status": "finished",
                    "content": embed.content, "createdAt": createdAtUnix, "updatedAt": createdAtUnix,
                    "text_preview": embed.transcript ?? embed.filename
                ]]
                inference["encrypted_embeds"] = try await crypto.encryptedAudioEmbed(embed, chat: chat, messageId: messageId)
            }
            let encryptedUserMessage: [String: Any] = [
                "client_message_id": messageId, "chat_id": chat.id,
                "encrypted_content": encryptedContent, "role": "user",
                "created_at": createdAtUnix, "updated_at": createdAtUnix
            ]
            var preflight: [String: Any] = [
                "protocol_version": 1, "chat_id": chat.id, "turn_id": turnId,
                "message_id": messageId, "chat_key_version": 1,
                "encrypted_chat_key": encryptedChatKey,
                "recovery_public_key": recoveryPublicKey,
                "expected_messages_v": expectedVersion,
                "encrypted_user_message": encryptedUserMessage,
                "inference_request": inference
            ]
            if expectedVersion == 0 && titleVersion == 0 {
                let encryptedTitle: String
                if let existingTitle = chat.encryptedTitle { encryptedTitle = existingTitle }
                else { encryptedTitle = try await crypto.encryptText("", for: chat) }
                preflight["encrypted_chat_metadata"] = [
                    "encrypted_title": encryptedTitle,
                    "encrypted_chat_key": encryptedChatKey,
                    "created_at": createdAtUnix, "updated_at": createdAtUnix
                ]
            }
            let pending = WatchPendingTextSend(
                id: turnId, chatId: chat.id, messageId: messageId,
                encryptedContent: encryptedContent, encryptedChatKey: encryptedChatKey,
                createdAt: createdAt,
                preflightJSON: try JSONSerialization.data(withJSONObject: preflight),
                inferenceJSON: try JSONSerialization.data(withJSONObject: inference)
            )
            var local = messagesByChatId[chat.id] ?? []
            local.append(WatchChatMessage(
                id: messageId, chatId: chat.id, role: .user, content: trimmed,
                encryptedContent: encryptedContent,
                embedRefs: embed.map { [WatchEmbedRef(id: $0.id, type: "audio-recording", status: "finished", data: nil)] },
                createdAt: createdAt, isPending: true
            ))
            messagesByChatId[chat.id] = Self.sortedMessages(local)
            pendingTextSends.append(pending)
            queued = true
            try await persistSnapshot()
            syncSocket.connect(session: syncSession!, syncState: makeSyncClientState())
            try await syncSocket.sendTurn(pending)
            pendingTextSends.removeAll { $0.id == turnId }
            markPendingMessageSent(messageId: messageId, chatId: chat.id)
            errorMessage = nil
            try await persistSnapshot()
            await refreshSelectedChat()
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(3))
                await self?.refreshSelectedChat()
            }
            return true
        } catch {
            errorMessage = error.localizedDescription
            try? await persistSnapshot()
            return queued
        }
    }

    private static func historyPayload(_ messages: [WatchChatMessage]) throws -> [[String: Any]] {
        var history: [[String: Any]] = []
        var seen = Set<String>()
        for message in messages.sorted(by: { $0.createdAt < $1.createdAt }) {
            guard message.role != .system, seen.insert(message.id).inserted else { continue }
            guard let content = message.content, !content.isEmpty else {
                throw WatchChatRuntimeError.historyUnavailable
            }
            history.append([
                "message_id": message.id, "chat_id": message.chatId,
                "role": message.role.rawValue, "content": content,
                "sender_name": message.role == .user ? "User" : "Assistant",
                "created_at": Int((ISO8601DateFormatter().date(from: message.createdAt) ?? Date()).timeIntervalSince1970)
            ])
        }
        return history
    }

    private func refreshSelectedChat() async {
        guard let chat = selectedChat else { return }
        do {
            let remote = try await api.fetchMessages(chatId: chat.id)
            let decrypted = Self.sortedMessages(await decryptMessages(remote))
            let remoteIds = Set(decrypted.map(\.id))
            let localOnly = (messagesByChatId[chat.id] ?? []).filter { !remoteIds.contains($0.id) }
            messagesByChatId[chat.id] = Self.sortedMessages(decrypted + localOnly)
            let authoritativeVersion = try? await api.fetchMessagesVersion(chatId: chat.id)
            if let index = chats.firstIndex(where: { $0.id == chat.id }) {
                chats[index].messagesV = max(chats[index].messagesV, authoritativeVersion ?? remote.count)
            }
            try await persistSnapshot()
        } catch {
            // An unsaved local chat may not exist on the server until its first turn.
        }
    }

    private func apply(_ snapshot: WatchChatSnapshot) {
        chats = Self.sortedChats(snapshot.chats)
        messagesByChatId = snapshot.messagesByChatId.mapValues(Self.sortedMessages)
        pendingTextSends = snapshot.pendingTextSends
        pendingAudioEmbeds = []
    }

    private func persistSnapshot() async throws {
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: chats,
                messagesByChatId: messagesByChatId,
                pendingTextSends: pendingTextSends,
                pendingAudioEmbeds: [],
                savedAt: Date()
            )
        )
    }

    private func fetchWithRetry<T>(_ operation: () async throws -> T) async throws -> T {
        var lastError: Error?
        for attempt in 1...Self.fetchRetryAttempts {
            do {
                return try await operation()
            } catch {
                lastError = error
                guard attempt < Self.fetchRetryAttempts,
                      Self.shouldRetryFetchError(error),
                      !Task.isCancelled else {
                    throw error
                }
                try await Task.sleep(nanoseconds: Self.fetchRetryDelayNanoseconds)
            }
        }
        throw lastError ?? URLError(.unknown)
    }

    private static func shouldRetryFetchError(_ error: Error) -> Bool {
        guard let urlError = error as? URLError else { return false }
        switch urlError.code {
        case .networkConnectionLost, .timedOut, .cannotConnectToHost, .notConnectedToInternet:
            return true
        default:
            return false
        }
    }

    private func decryptChats(_ remoteChats: [WatchRemoteChat]) async -> [WatchChatSummary] {
        var result: [WatchChatSummary] = []
        result.reserveCapacity(remoteChats.count)
        for chat in remoteChats {
            if let decrypted = await crypto.decryptChat(chat) {
                result.append(decrypted)
            }
        }
        return result
    }

    private func decryptMessages(_ remoteMessages: [WatchRemoteMessage]) async -> [WatchChatMessage] {
        var result: [WatchChatMessage] = []
        result.reserveCapacity(remoteMessages.count)
        for message in remoteMessages {
            result.append(await crypto.decryptMessage(message))
        }
        return result
    }

    private func replayPendingTextSends() async {
        guard let syncSocket, let syncSession, !pendingTextSends.isEmpty, !isSending else { return }
        isSending = true
        defer { isSending = false }
        syncSocket.connect(session: syncSession, syncState: makeSyncClientState())
        for pending in pendingTextSends where !pending.preflightJSON.isEmpty {
            do {
                try await syncSocket.sendTurn(pending)
                pendingTextSends.removeAll { $0.id == pending.id }
                markPendingMessageSent(messageId: pending.messageId, chatId: pending.chatId)
            } catch {
                errorMessage = error.localizedDescription
                break
            }
        }
        try? await persistSnapshot()
    }

    private func makeSyncClientState() -> WatchSyncClientState {
        let syncableChats = chats.filter { !$0.id.hasPrefix(Self.incognitoChatIdPrefix) }
        return WatchSyncClientState(
            clientChatVersions: [:],
            clientChatIds: syncableChats.map(\.id),
            clientSuggestionsCount: 0,
            clientEmbedIds: []
        )
    }

    private func markPendingMessageSent(messageId: String, chatId: String) {
        guard var messages = messagesByChatId[chatId],
              let index = messages.firstIndex(where: { $0.id == messageId }) else { return }
        messages[index].isPending = false
        messagesByChatId[chatId] = messages
    }

    private static func sortedChats(_ chats: [WatchChatSummary]) -> [WatchChatSummary] {
        chats.sorted { lhs, rhs in
            if lhs.isPinned != rhs.isPinned { return lhs.isPinned && !rhs.isPinned }
            return (lhs.lastMessageAt ?? "") > (rhs.lastMessageAt ?? "")
        }
    }

    private static func sortedMessages(_ messages: [WatchChatMessage]) -> [WatchChatMessage] {
        messages.sorted { $0.createdAt < $1.createdAt }
    }
}

extension APIClient: WatchChatAPI {
    func fetchRecentChats(limit: Int, offset: Int) async throws -> [WatchRemoteChat] {
        let response: WatchChatListEnvelope = try await request(.get, path: "/v1/chats?limit=\(limit)&offset=\(offset)")
        return response.chats.map(WatchRemoteChat.init(dto:))
    }

    func fetchMessages(chatId: String) async throws -> [WatchRemoteMessage] {
        let response: [WatchChatMessageDTO] = try await request(.get, path: "/v1/chats/\(chatId)/messages")
        return response.map(WatchRemoteMessage.init(dto:))
    }

    func fetchMessagesVersion(chatId: String) async throws -> Int? {
        let response: WatchChatVersionEnvelope = try await request(
            .get, path: "/v1/chats/\(chatId)/messages/window?limit=1"
        )
        return response.messagesV ?? response.serverMessageCount
    }

    func uploadAudioRecording(data: Data, filename: String, chatId: String) async throws -> WatchUploadedAudio {
        let responseData = try await uploadFile(
            data: data, filename: filename, contentType: "audio/mp4", chatId: chatId
        )
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(WatchUploadedAudio.self, from: responseData)
    }

    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String) async throws -> WatchTranscriptionMetadata? {
        let s3Key = upload.files["original"]?.s3Key ?? upload.files.values.first?.s3Key
        guard let s3Key else { throw WatchChatRuntimeError.audioUploadFailed }
        let embedId = UUID().uuidString
        let request: [String: Any] = [
            "requests": [[
                "id": embedId,
                "embed_id": upload.embedId,
                "s3_key": s3Key,
                "s3_base_url": upload.s3BaseUrl,
                "aes_key": upload.aesKey,
                "aes_nonce": upload.aesNonce,
                "vault_wrapped_aes_key": upload.vaultWrappedAesKey,
                "filename": upload.filename,
                "mime_type": upload.contentType,
                "chat_id": chatId,
            ]]
        ]
        let response: WatchTranscribeSkillResponse = try await self.request(
            .post,
            path: "apps/audio/skills/transcribe",
            body: request
        )
        return response.data.results.first?.results.first
    }
}

#if !os(watchOS)
extension WebSocketManager: WatchChatSyncSocket {
    func sendTurn(_ pending: WatchPendingTextSend) async throws {
        throw WatchChatRuntimeError.socketUnavailable
    }

    func setChangeHandler(_ handler: (@MainActor () -> Void)?) {}

    func connect(session: WatchSyncSession, syncState: WatchSyncClientState) {
        connect(
            sessionId: session.sessionId,
            token: session.token,
            syncState: SyncClientState(
                clientChatVersions: syncState.clientChatVersions,
                clientChatIds: syncState.clientChatIds,
                clientSuggestionsCount: syncState.clientSuggestionsCount,
                clientEmbedIds: syncState.clientEmbedIds
            )
        )
    }
}
#endif

@MainActor
private final class WatchRealtimeSyncSocket: WatchChatSyncSocket {
    private var webSocketTask: URLSessionWebSocketTask?
    private var isConnecting = false
    private var isReady = false
    private var changeHandler: (@MainActor () -> Void)?
    private var inbox: [(type: String, payload: [String: Any])] = []
    private var receiveTask: Task<Void, Never>?
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        return URLSession(configuration: config)
    }()

    func setChangeHandler(_ handler: (@MainActor () -> Void)?) { changeHandler = handler }

    func connect(session syncSession: WatchSyncSession, syncState: WatchSyncClientState) {
        guard webSocketTask == nil, !isConnecting else { return }
        isConnecting = true
        isReady = false
        Task {
            defer { self.isConnecting = false }
            let baseURL = await APIClient.shared.baseURL
            let origin = await APIClient.shared.webAppURL.absoluteString
            guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return }
            components.scheme = components.scheme == "https" ? "wss" : "ws"
            components.path = "/v1/ws"
            var queryItems = [URLQueryItem(name: "sessionId", value: syncSession.sessionId)]
            if let token = syncSession.token, !token.isEmpty {
                queryItems.append(URLQueryItem(name: "token", value: token))
            }
            components.queryItems = queryItems
            guard let url = components.url else { return }
            var request = URLRequest(url: url)
            request.timeoutInterval = 30
            request.setValue(origin, forHTTPHeaderField: "Origin")
            APIClient.nativeClientHeaders.forEach { request.setValue($1, forHTTPHeaderField: $0) }
            let task = self.session.webSocketTask(with: request)
            self.webSocketTask = task
            task.resume()
            self.receiveTask = Task { await self.receiveLoop(task) }
            try? await Task.sleep(for: .milliseconds(250))
            let sync = WatchWSOutboundMessage(type: "phased_sync_request", payload: [
                "phase": "all", "client_chat_versions": syncState.clientChatVersions,
                "client_chat_ids": syncState.clientChatIds,
                "client_suggestions_count": syncState.clientSuggestionsCount,
                "client_embed_ids": syncState.clientEmbedIds
            ])
            do {
                try await self.send(sync, on: task)
                self.isReady = true
            } catch {
                self.disconnect()
            }
        }
    }

    func disconnect() {
        receiveTask?.cancel()
        receiveTask = nil
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        isReady = false
        inbox.removeAll()
    }

    func sendTurn(_ pending: WatchPendingTextSend) async throws {
        guard !pending.preflightJSON.isEmpty, !pending.inferenceJSON.isEmpty else {
            throw WatchChatRuntimeError.invalidPendingTurn
        }
        let preflight = try JSONSerialization.jsonObject(with: pending.preflightJSON) as? [String: Any]
        let inference = try JSONSerialization.jsonObject(with: pending.inferenceJSON) as? [String: Any]
        guard let preflight, let inference,
              preflight["inference_request"] != nil,
              let turnId = preflight["turn_id"] as? String,
              turnId == pending.id else { throw WatchChatRuntimeError.invalidPendingTurn }
        let task = try await connectedTask()
        try await send(WatchWSOutboundMessage(type: "chat_turn_preflight", payload: preflight), on: task)
        let ack = try await waitForEvent(type: "chat_turn_preflight_ack", turnId: turnId)
        guard let state = ack["state"] as? String,
              let preflightId = ack["preflight_id"] as? String, !preflightId.isEmpty else {
            throw WatchChatRuntimeError.preflightRejected
        }
        if state == "ENQUEUED" || state == "RUNNING" || state == "TERMINAL" { return }
        guard state == "PREPARED" || state == "LEGACY" else { throw WatchChatRuntimeError.preflightRejected }
        var commit = inference
        commit["protocol_version"] = 1
        commit["preflight_id"] = preflightId
        try await send(WatchWSOutboundMessage(type: "chat_message_added", payload: commit), on: task)
        let receipt = try await waitForEvent(type: "ai_task_initiated", turnId: turnId, messageId: pending.messageId)
        if receipt["code"] as? String != nil { throw WatchChatRuntimeError.inferenceRejected }
    }

    private func connectedTask() async throws -> URLSessionWebSocketTask {
        for _ in 0..<50 {
            if let webSocketTask, isReady { return webSocketTask }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw WatchChatRuntimeError.socketUnavailable
    }

    private func send(_ message: WatchWSOutboundMessage, on task: URLSessionWebSocketTask) async throws {
        let data = try JSONEncoder().encode(message)
        guard let json = String(data: data, encoding: .utf8) else { throw WatchChatRuntimeError.socketUnavailable }
        try await task.send(.string(json))
    }

    private func receiveLoop(_ task: URLSessionWebSocketTask) async {
        while !Task.isCancelled {
            do {
                let value = try await task.receive()
                let data: Data
                switch value {
                case .string(let text): data = Data(text.utf8)
                case .data(let bytes): data = bytes
                @unknown default: continue
                }
                guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let type = object["type"] as? String else { continue }
                let payload = object["payload"] as? [String: Any] ?? [:]
                inbox.append((type, payload))
                if inbox.count > 100 { inbox.removeFirst(inbox.count - 100) }
                if ["new_chat_message", "chat_message_added", "chat_message_confirmed", "ai_response_storage_confirmed", "phased_sync_complete"].contains(type) {
                    changeHandler?()
                }
            } catch {
                if webSocketTask === task {
                    webSocketTask = nil
                    isReady = false
                }
                return
            }
        }
    }

    private func waitForEvent(type: String, turnId: String, messageId: String? = nil) async throws -> [String: Any] {
        for _ in 0..<200 {
            if let index = inbox.firstIndex(where: { event in
                guard event.type == type || event.type == "error" else { return false }
                if event.payload["turn_id"] as? String == turnId { return true }
                if let messageId,
                   (event.payload["user_message_id"] ?? event.payload["message_id"]) as? String == messageId { return true }
                return false
            }) {
                let event = inbox.remove(at: index)
                if event.type == "error" { throw WatchChatRuntimeError.preflightRejected }
                return event.payload
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw WatchChatRuntimeError.socketUnavailable
    }
}

private struct WatchWSOutboundMessage: Encodable {
    let type: String
    let payload: [String: AnyCodable]

    init(type: String, payload: [String: Any]) {
        self.type = type
        self.payload = payload.mapValues { AnyCodable($0) }
    }
}

@MainActor
private final class WatchChatCryptoService: WatchChatCrypto {
    private let currentUserId: String?
    private var chatKeys: [String: SymmetricKey] = [:]

    init(currentUserId: String?) {
        self.currentUserId = currentUserId
    }

    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary? {
        guard let resolved = await loadChatKey(chatId: chat.id, wrappers: chat.chatKeyWrappers,
                                               encryptedChatKey: chat.encryptedChatKey) else {
            return nil
        }
        let key = resolved.key
        let title = await decrypt(chat.encryptedTitle, key: key) ?? chat.title
        let preview = await decrypt(chat.encryptedChatSummary, key: key) ?? chat.chatSummary
        return WatchChatSummary(
            id: chat.id, title: title,
            lastMessageAt: chat.lastMessageAt ?? chat.updatedAt,
            preview: preview, isPinned: chat.isPinned,
            encryptedTitle: chat.encryptedTitle,
            encryptedPreview: chat.encryptedChatSummary,
            encryptedChatKey: resolved.outboundWrapped,
            messagesV: chat.messagesV, titleV: chat.titleV, metadataV: chat.metadataV
        )
    }

    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage {
        let key = chatKeys[message.chatId]
        let content = await decrypt(message.encryptedContent, key: key) ?? message.content
        let embedRefs = message.embedRefs ?? WatchMessageContentSanitizer.inlineEmbedRefs(content: content)
        return WatchChatMessage(
            id: message.id,
            chatId: message.chatId,
            role: message.role,
            content: content,
            encryptedContent: message.encryptedContent,
            embedRefs: embedRefs.isEmpty ? nil : embedRefs,
            createdAt: message.createdAt,
            isPending: false
        )
    }

    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String {
        guard let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        return try await CryptoManager.shared.encryptContent(text, key: key)
    }

    func createChat() async throws -> WatchChatSummary {
        guard let currentUserId,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUserId) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        let id = UUID().uuidString.lowercased()
        let key = await CryptoManager.shared.generateChatKey()
        let wrapped = try await CryptoManager.shared.wrapChatKey(key, masterKey: masterKey)
        let encryptedTitle = try await CryptoManager.shared.encryptContent("", key: key)
        chatKeys[id] = key
        return WatchChatSummary(id: id, title: nil, lastMessageAt: nil, preview: nil,
                                isPinned: false, encryptedTitle: encryptedTitle,
                                encryptedPreview: nil, encryptedChatKey: wrapped)
    }

    func recoveryPublicKey(for chat: WatchChatSummary) async throws -> String {
        guard let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        return try await CryptoManager.shared.deriveRecoveryKeyPair(
            chatKey: key, chatId: chat.id, keyVersion: 1
        ).publicKey
    }

    func encryptedAudioEmbed(_ embed: WatchPendingAudioEmbed, chat: WatchChatSummary, messageId: String) async throws -> [[String: Any]] {
        guard let currentUserId,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUserId),
              let chatKey = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        let embedKey = ComposerEmbedCrypto.deriveKey(chatKey: chatKey, embedId: embed.id)
        let hashedChatId = Self.hash(chat.id)
        let hashedUserId = Self.hash(currentUserId)
        let hashedEmbedId = Self.hash(embed.id)
        let now = Int(Date().timeIntervalSince1970)
        return [[
            "embed_id": embed.id,
            "encrypted_type": try ComposerEmbedCrypto.encryptContent("audio-recording", using: embedKey),
            "encrypted_content": try ComposerEmbedCrypto.encryptContent(embed.content, using: embedKey),
            "encrypted_text_preview": try ComposerEmbedCrypto.encryptContent(embed.transcript ?? embed.filename, using: embedKey),
            "status": "finished", "hashed_chat_id": hashedChatId,
            "hashed_message_id": Self.hash(messageId), "hashed_user_id": hashedUserId,
            "created_at": now, "updated_at": now,
            "embed_keys": [
                ["hashed_embed_id": hashedEmbedId, "key_type": "master", "hashed_chat_id": NSNull(),
                 "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: masterKey),
                 "hashed_user_id": hashedUserId, "created_at": now] as [String: Any],
                ["hashed_embed_id": hashedEmbedId, "key_type": "chat", "hashed_chat_id": hashedChatId,
                 "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: chatKey),
                 "hashed_user_id": hashedUserId, "created_at": now] as [String: Any]
            ]
        ]]
    }

    private static func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func chatKey(chatId: String, encryptedChatKey: String?) async -> SymmetricKey? {
        if let key = chatKeys[chatId] { return key }
        guard let currentUserId,
              let encryptedChatKey,
              let masterKey = try? await CryptoManager.shared.loadMasterKey(for: currentUserId),
              let chatKey = try? await CryptoManager.shared.unwrapChatKey(
                encryptedChatKeyBase64: encryptedChatKey,
                masterKey: masterKey
              ) else { return nil }
        chatKeys[chatId] = chatKey
        return chatKey
    }

    private func loadChatKey(chatId: String, wrappers: [WatchChatKeyWrapperRecord],
                             encryptedChatKey: String?) async -> WatchChatKeyResolver.Resolved? {
        guard let currentUserId,
              let masterKey = try? await CryptoManager.shared.loadMasterKey(for: currentUserId) else { return nil }
        guard let resolved = await WatchChatKeyResolver.resolve(
            chatId: chatId, wrappers: wrappers, encryptedChatKey: encryptedChatKey,
            masterKey: masterKey
        ) else { return nil }
        chatKeys[chatId] = resolved.key
        return resolved
    }

    private func decrypt(_ encrypted: String?, key: SymmetricKey?) async -> String? {
        guard let encrypted, let key else { return nil }
        return try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
    }
}

enum WatchChatKeyResolver {
    struct Resolved {
        let key: SymmetricKey
        let wrapped: String
        let outboundWrapped: String?
    }

    static func resolve(chatId: String, wrappers: [WatchChatKeyWrapperRecord],
                        encryptedChatKey: String?, masterKey: SymmetricKey) async -> Resolved? {
        let candidates = WatchChatKeyWrapperRecord.orderedMasterWrappers(wrappers, for: chatId)
            .map(\.encryptedChatKey) + (encryptedChatKey.map { [$0] } ?? [])
        for wrapped in candidates {
            if let key = try? await CryptoManager.shared.unwrapChatKey(
                encryptedChatKeyBase64: wrapped, masterKey: masterKey
            ) {
                // Existing-chat writes must send the exact immutable row value.
                // A different wrapper can decrypt content, but cannot replace it.
                var outboundWrapped: String?
                if let encryptedChatKey,
                   let rowKey = try? await CryptoManager.shared.unwrapChatKey(
                    encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey
                   ), rowKey.withUnsafeBytes({ Data($0) }) == key.withUnsafeBytes({ Data($0) }) {
                    outboundWrapped = encryptedChatKey
                }
                return Resolved(key: key, wrapped: wrapped, outboundWrapped: outboundWrapped)
            }
        }
        return nil
    }
}

enum WatchChatRuntimeError: LocalizedError {
    case missingChatKey
    case audioUploadFailed
    case noSelectedChat
    case invalidRecording
    case sendInProgress
    case socketUnavailable
    case invalidPendingTurn
    case preflightRejected
    case inferenceRejected
    case historyUnavailable

    var errorDescription: String? {
        switch self {
        case .missingChatKey:
            return "Missing local chat key"
        case .audioUploadFailed: return "Audio upload failed"
        case .noSelectedChat: return "Open or create a chat first"
        case .invalidRecording: return "Recording is empty"
        case .sendInProgress: return "A message is already sending"
        case .socketUnavailable: return "Chat connection is unavailable"
        case .invalidPendingTurn: return "Pending message cannot be sent"
        case .preflightRejected: return "Message could not be saved"
        case .inferenceRejected: return "Message could not start a reply"
        case .historyUnavailable: return "Chat history could not be read"
        }
    }
}

private struct WatchTranscribeSkillResponse: Decodable {
    struct ResponseData: Decodable {
        struct ResultGroup: Decodable {
            let results: [WatchTranscriptionMetadata]
        }

        let results: [ResultGroup]
    }

    let data: ResponseData
}

private struct WatchChatVersionEnvelope: Decodable {
    let messagesV: Int?
    let serverMessageCount: Int?
}

struct WatchChatListEnvelope: Decodable {
    let chats: [WatchChatDTO]
}

struct WatchChatDTO: Decodable {
    let id: String
    let title: String?
    let lastMessageAt: String?
    let updatedAt: String?
    let chatSummary: String?
    let isPinned: Bool?
    let encryptedTitle: String?
    let encryptedChatSummary: String?
    let encryptedChatKey: String?
    let chatKeyWrappers: [WatchChatKeyWrapperRecord]
    let messagesV: Int
    let titleV: Int
    let metadataV: Int

    private enum CodingKeys: String, CodingKey {
        case id
        case chatId = "chat_id"
        case title
        case lastMessageAt
        case lastMessageAtSnake = "last_message_at"
        case updatedAt
        case updatedAtSnake = "updated_at"
        case chatSummary
        case chatSummarySnake = "chat_summary"
        case isPinned
        case isPinnedSnake = "is_pinned"
        case pinned
        case encryptedTitle
        case encryptedTitleSnake = "encrypted_title"
        case encryptedChatSummary
        case encryptedChatSummarySnake = "encrypted_chat_summary"
        case encryptedChatKey
        case encryptedChatKeySnake = "encrypted_chat_key"
        case chatKeyWrappers
        case chatKeyWrappersSnake = "chat_key_wrappers"
        case messagesV, titleV, metadataV
        case messagesVSnake = "messages_v"
        case titleVSnake = "title_v"
        case metadataVSnake = "metadata_v"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .chatId)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        lastMessageAt = try container.decodeIfPresent(String.self, forKey: .lastMessageAt)
            ?? container.decodeIfPresent(String.self, forKey: .lastMessageAtSnake)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
            ?? container.decodeIfPresent(String.self, forKey: .updatedAtSnake)
        chatSummary = try container.decodeIfPresent(String.self, forKey: .chatSummary)
            ?? container.decodeIfPresent(String.self, forKey: .chatSummarySnake)
        isPinned = try container.decodeIfPresent(Bool.self, forKey: .isPinned)
            ?? container.decodeIfPresent(Bool.self, forKey: .isPinnedSnake)
            ?? container.decodeIfPresent(Bool.self, forKey: .pinned)
        encryptedTitle = try container.decodeIfPresent(String.self, forKey: .encryptedTitle)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedTitleSnake)
        encryptedChatSummary = try container.decodeIfPresent(String.self, forKey: .encryptedChatSummary)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedChatSummarySnake)
        encryptedChatKey = try container.decodeIfPresent(String.self, forKey: .encryptedChatKey)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedChatKeySnake)
        chatKeyWrappers = try container.decodeIfPresent([WatchChatKeyWrapperRecord].self, forKey: .chatKeyWrappers)
            ?? container.decodeIfPresent([WatchChatKeyWrapperRecord].self, forKey: .chatKeyWrappersSnake) ?? []
        messagesV = try container.decodeIfPresent(Int.self, forKey: .messagesV)
            ?? container.decodeIfPresent(Int.self, forKey: .messagesVSnake) ?? 0
        titleV = try container.decodeIfPresent(Int.self, forKey: .titleV)
            ?? container.decodeIfPresent(Int.self, forKey: .titleVSnake) ?? 0
        metadataV = try container.decodeIfPresent(Int.self, forKey: .metadataV)
            ?? container.decodeIfPresent(Int.self, forKey: .metadataVSnake) ?? titleV
    }
}

private struct WatchChatMessageDTO: Decodable {
    let id: String
    let chatId: String
    let role: WatchChatMessage.Role
    let content: String?
    let encryptedContent: String?
    let embedRefs: [WatchEmbedRef]?
    let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case messageId = "message_id"
        case chatId
        case chatIdSnake = "chat_id"
        case role
        case content
        case encryptedContent
        case encryptedContentSnake = "encrypted_content"
        case embedRefs
        case embedRefsSnake = "embed_refs"
        case createdAt
        case createdAtSnake = "created_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .messageId)
        chatId = try container.decodeIfPresent(String.self, forKey: .chatId)
            ?? container.decode(String.self, forKey: .chatIdSnake)
        role = try container.decode(WatchChatMessage.Role.self, forKey: .role)
        content = try container.decodeIfPresent(String.self, forKey: .content)
        encryptedContent = try container.decodeIfPresent(String.self, forKey: .encryptedContent)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedContentSnake)
        embedRefs = try container.decodeIfPresent([WatchEmbedRef].self, forKey: .embedRefs)
            ?? container.decodeIfPresent([WatchEmbedRef].self, forKey: .embedRefsSnake)
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
            ?? container.decodeIfPresent(String.self, forKey: .createdAtSnake)
            ?? ""
    }
}

extension WatchRemoteChat {
    init(dto: WatchChatDTO) {
        self.init(
            id: dto.id,
            title: dto.title,
            lastMessageAt: dto.lastMessageAt ?? dto.updatedAt,
            updatedAt: dto.updatedAt,
            chatSummary: dto.chatSummary,
            isPinned: dto.isPinned == true,
            encryptedTitle: dto.encryptedTitle,
            encryptedChatSummary: dto.encryptedChatSummary,
            encryptedChatKey: dto.encryptedChatKey,
            chatKeyWrappers: dto.chatKeyWrappers,
            messagesV: dto.messagesV, titleV: dto.titleV, metadataV: dto.metadataV
        )
    }
}

private extension WatchRemoteMessage {
    init(dto: WatchChatMessageDTO) {
        self.init(
            id: dto.id,
            chatId: dto.chatId,
            role: dto.role,
            content: dto.content,
            encryptedContent: dto.encryptedContent,
            embedRefs: dto.embedRefs,
            createdAt: dto.createdAt,
        )
    }
}
