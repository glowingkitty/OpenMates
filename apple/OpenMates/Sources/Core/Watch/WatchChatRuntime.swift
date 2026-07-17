// Watch chat runtime and offline cache.
// Provides the portable data layer for the standalone watchOS chat shell while
// staying small enough to unit test from the existing Apple unit-test target.
// The runtime fetches recent chats/messages directly from the backend, unwraps
// per-chat keys from the Watch-local master key, and keeps a local JSON snapshot
// for offline startup. This layer never logs plaintext.

import CryptoKit
import Foundation
import SwiftUI

enum WatchUIContract {
    static let pairLoginIdentifiers = [
        "watch-pair-login",
        "watch-pair-confirm-iphone-title",
        "watch-pair-confirm-iphone-description",
        "watch-pair-manual-fallback",
        "watch-pair-token",
        "watch-pair-url",
        "watch-pair-show-qr-button",
        "watch-pair-qr-code",
        "watch-pair-qr-fullscreen",
        "watch-pair-qr-close-button",
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
        "watch-chat-thread",
        "watch-message-input",
        "watch-message-send",
        "watch-audio-record-button",
        "watch-pending-audio-embed",
    ]

    static let audioComposerIdentifiers = [
        "watch-audio-record-button",
        "watch-audio-stop-button",
        "watch-audio-transcribing",
        "watch-pending-audio-embed",
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
        "navigationTitle",
        "toolbar",
    ]

    static let designEvidence = [
        "Dark Watch shell uses Color.grey100, Color.grey90, Color.grey0, Color.buttonPrimary, and generated spacing/typography tokens.",
        "Chat and embed surfaces use ScrollView/LazyVStack/custom buttons instead of List, Form, default navigation chrome, or stock product controls.",
        "Embed previews preserve OpenMates app/embed semantics through WatchEmbedPreviewModel and route detail actions to continuation metadata instead of rich fullscreen Watch consumption.",
        "Audio composer mirrors iOS behavior by creating a pending audio-recording embed and requiring explicit manual send.",
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

struct WatchPendingAudioEmbed: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let filename: String
    let transcript: String?
    let duration: TimeInterval
    let content: String

    var markdownReference: String {
        "```json\n{\"type\": \"audio-recording\", \"embed_id\": \"\(id)\"}\n```"
    }

    static func from(upload: WatchUploadedAudio, transcript: String?, duration: TimeInterval) -> WatchPendingAudioEmbed {
        let contentObject = audioContentObject(upload: upload, transcript: transcript, duration: duration)
        return WatchPendingAudioEmbed(
            id: upload.embedId,
            filename: upload.filename,
            transcript: transcript,
            duration: duration,
            content: jsonString(contentObject)
        )
    }

    private static func audioContentObject(
        upload: WatchUploadedAudio,
        transcript: String?,
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
        if let transcript { object["transcript"] = transcript }
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

struct WatchRemoteChat: Equatable, Sendable {
    let id: String
    let title: String?
    let lastMessageAt: String?
    let updatedAt: String?
    let chatSummary: String?
    let isPinned: Bool
    let encryptedTitle: String?
    let encryptedChatSummary: String?
    let encryptedChatKey: String?
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
    func fetchRecentChats(limit: Int) async throws -> [WatchRemoteChat]
    func fetchMessages(chatId: String) async throws -> [WatchRemoteMessage]
    func sendPendingText(_ pending: WatchPendingTextSend) async throws
    func uploadAudioRecording(data: Data, filename: String, chatId: String) async throws -> WatchUploadedAudio
    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String) async throws -> String?
}

@MainActor
protocol WatchChatSyncSocket: AnyObject {
    func connect(session: WatchSyncSession, syncState: WatchSyncClientState)
    func disconnect()
}

@MainActor
protocol WatchChatCrypto: AnyObject {
    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary?
    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage
    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String
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
        try data.write(to: fileURL, options: [.atomic])
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

    private let api: any WatchChatAPI
    private let cache: WatchChatOfflineCache
    private let crypto: any WatchChatCrypto
    private let syncSocket: (any WatchChatSyncSocket)?
    private let syncSession: WatchSyncSession?
    private var pendingTextSends: [WatchPendingTextSend] = []
    private static let incognitoChatIdPrefix = "incognito-"
    private static let recentChatLimit = 20
    private static let hiddenCandidateFetchLimit = 40
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

        do {
            let fetchedChats = try await fetchWithRetry {
                try await api.fetchRecentChats(limit: Self.hiddenCandidateFetchLimit)
            }
            chats = Array(Self.sortedChats(await decryptChats(fetchedChats)).prefix(Self.recentChatLimit))
            if selectedChatId == nil {
                selectedChatId = chats.first?.id
            }
            isOffline = false
            await replayPendingTextSends()
            try await persistSnapshot()
        } catch {
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
        syncSocket.connect(session: syncSession, syncState: makeSyncClientState())
    }

    func openChat(_ chat: WatchChatSummary) async {
        selectedChatId = chat.id
        if messagesByChatId[chat.id] == nil {
            await loadCachedSnapshot()
        }

        do {
            let messages = try await fetchWithRetry {
                try await api.fetchMessages(chatId: chat.id)
            }
            messagesByChatId[chat.id] = Self.sortedMessages(await decryptMessages(messages))
            isOffline = false
            errorMessage = nil
            try await persistSnapshot()
        } catch {
            isOffline = true
            errorMessage = error.localizedDescription
        }
    }

    func queueLocalText(_ content: String) async {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              let selectedChatId,
              let chat = selectedChat,
              let encryptedChatKey = chat.encryptedChatKey else { return }
        let createdAt = ISO8601DateFormatter().string(from: Date())
        let messageId = "watch-\(selectedChatId.suffix(10))-\(UUID().uuidString)"
        let encryptedContent: String
        do {
            encryptedContent = try await crypto.encryptText(trimmed, for: chat)
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        let pending = WatchChatMessage(
            id: messageId,
            chatId: selectedChatId,
            role: .user,
            content: trimmed,
            encryptedContent: encryptedContent,
            embedRefs: nil,
            createdAt: createdAt,
            isPending: true
        )
        let pendingSend = WatchPendingTextSend(
            id: UUID().uuidString,
            chatId: selectedChatId,
            messageId: messageId,
            encryptedContent: encryptedContent,
            encryptedChatKey: encryptedChatKey,
            createdAt: createdAt
        )
        var messages = messagesByChatId[selectedChatId] ?? []
        messages.append(pending)
        messagesByChatId[selectedChatId] = Self.sortedMessages(messages)
        pendingTextSends.append(pendingSend)
        try? await persistSnapshot()
        await replayPendingTextSends()
        try? await persistSnapshot()
    }

    func prepareAudioRecording(data: Data, filename: String, duration: TimeInterval) async -> String? {
        guard let selectedChatId else { return nil }
        do {
            let upload = try await api.uploadAudioRecording(
                data: data,
                filename: filename,
                chatId: selectedChatId
            )
            let transcript = try await api.transcribeAudioRecording(upload, chatId: selectedChatId)
            let pendingEmbed = WatchPendingAudioEmbed.from(
                upload: upload,
                transcript: transcript,
                duration: duration
            )
            pendingAudioEmbeds.removeAll { $0.id == pendingEmbed.id }
            pendingAudioEmbeds.append(pendingEmbed)
            errorMessage = nil
            try? await persistSnapshot()
            return transcript
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    private func apply(_ snapshot: WatchChatSnapshot) {
        chats = Self.sortedChats(snapshot.chats)
        messagesByChatId = snapshot.messagesByChatId.mapValues(Self.sortedMessages)
        pendingTextSends = snapshot.pendingTextSends
        pendingAudioEmbeds = snapshot.pendingAudioEmbeds
        if selectedChatId == nil {
            selectedChatId = chats.first?.id
        }
    }

    private func persistSnapshot() async throws {
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: chats,
                messagesByChatId: messagesByChatId,
                pendingTextSends: pendingTextSends,
                pendingAudioEmbeds: pendingAudioEmbeds,
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
        guard !pendingTextSends.isEmpty else { return }
        var remaining: [WatchPendingTextSend] = []
        for pending in pendingTextSends {
            do {
                try await api.sendPendingText(pending)
                markPendingMessageSent(messageId: pending.messageId, chatId: pending.chatId)
            } catch {
                remaining.append(pending)
            }
        }
        pendingTextSends = remaining
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
    func fetchRecentChats(limit: Int) async throws -> [WatchRemoteChat] {
        let response: WatchChatListEnvelope = try await request(.get, path: "/v1/chats?limit=\(limit)")
        return response.chats.map(WatchRemoteChat.init(dto:))
    }

    func fetchMessages(chatId: String) async throws -> [WatchRemoteMessage] {
        let response: [WatchChatMessageDTO] = try await request(.get, path: "/v1/chats/\(chatId)/messages")
        return response.map(WatchRemoteMessage.init(dto:))
    }

    func sendPendingText(_ pending: WatchPendingTextSend) async throws {
        let createdAtUnix = Int((ISO8601DateFormatter().date(from: pending.createdAt) ?? Date()).timeIntervalSince1970)
        let payload: [String: Any] = [
            "chat_id": pending.chatId,
            "message_id": pending.messageId,
            "encrypted_content": pending.encryptedContent,
            "created_at": createdAtUnix,
            "encrypted_chat_key": pending.encryptedChatKey,
            "versions": ["last_edited_overall_timestamp": createdAtUnix]
        ]
        let _: Data = try await request(.post, path: "/v1/chats/\(pending.chatId)/messages", body: payload)
    }

    func uploadAudioRecording(data: Data, filename: String, chatId: String) async throws -> WatchUploadedAudio {
        let boundary = UUID().uuidString
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/mp4\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n".data(using: .utf8)!)
        body.append(chatId.data(using: .utf8)!)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        let uploadURL = await uploadBaseURL.appendingPathComponent("v1/upload/file")
        var request = URLRequest(url: uploadURL)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let (responseData, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw WatchChatRuntimeError.audioUploadFailed
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(WatchUploadedAudio.self, from: responseData)
    }

    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String) async throws -> String? {
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
        return response.data.results.first?.results.first?.transcript
    }
}

#if !os(watchOS)
extension WebSocketManager: WatchChatSyncSocket {
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
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        return URLSession(configuration: config)
    }()

    func connect(session syncSession: WatchSyncSession, syncState: WatchSyncClientState) {
        disconnect()
        Task { @MainActor in
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
            APIClient.nativeClientHeaders.forEach { key, value in
                request.setValue(value, forHTTPHeaderField: key)
            }

            let task = session.webSocketTask(with: request)
            webSocketTask = task
            task.resume()
            try? await Task.sleep(for: .milliseconds(250))
            try? await sendPhasedSync(syncState)
        }
    }

    func disconnect() {
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
    }

    private func sendPhasedSync(_ syncState: WatchSyncClientState) async throws {
        guard let webSocketTask else { return }
        let message = WatchWSOutboundMessage(
            type: "phased_sync_request",
            payload: [
                "phase": "all",
                "client_chat_versions": syncState.clientChatVersions,
                "client_chat_ids": syncState.clientChatIds,
                "client_suggestions_count": syncState.clientSuggestionsCount,
                "client_embed_ids": syncState.clientEmbedIds,
            ]
        )
        let data = try JSONEncoder().encode(message)
        guard let json = String(data: data, encoding: .utf8) else { return }
        try await webSocketTask.send(.string(json))
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
        guard let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else {
            return nil
        }
        let title = await decrypt(chat.encryptedTitle, key: key) ?? chat.title
        let preview = await decrypt(chat.encryptedChatSummary, key: key) ?? chat.chatSummary
        return WatchChatSummary(
            id: chat.id,
            title: title,
            lastMessageAt: chat.lastMessageAt ?? chat.updatedAt,
            preview: preview,
            isPinned: chat.isPinned,
            encryptedTitle: chat.encryptedTitle,
            encryptedPreview: chat.encryptedChatSummary,
            encryptedChatKey: chat.encryptedChatKey
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

    private func decrypt(_ encrypted: String?, key: SymmetricKey?) async -> String? {
        guard let encrypted, let key else { return nil }
        return try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
    }
}

enum WatchChatRuntimeError: LocalizedError {
    case missingChatKey
    case audioUploadFailed

    var errorDescription: String? {
        switch self {
        case .missingChatKey:
            return "Missing local chat key"
        case .audioUploadFailed:
            return "Audio upload failed"
        }
    }
}

private struct WatchTranscribeSkillResponse: Decodable {
    struct ResponseData: Decodable {
        struct ResultGroup: Decodable {
            struct Result: Decodable {
                let transcript: String?
            }

            let results: [Result]
        }

        let results: [ResultGroup]
    }

    let data: ResponseData
}

private struct WatchChatListEnvelope: Decodable {
    let chats: [WatchChatDTO]
}

private struct WatchChatDTO: Decodable {
    let id: String
    let title: String?
    let lastMessageAt: String?
    let updatedAt: String?
    let chatSummary: String?
    let isPinned: Bool?
    let encryptedTitle: String?
    let encryptedChatSummary: String?
    let encryptedChatKey: String?

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

private extension WatchRemoteChat {
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
            encryptedChatKey: dto.encryptedChatKey
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
