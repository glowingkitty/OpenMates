// Background encrypted chat sender for OpenMates Apple surfaces.
// Used by extension-style flows that must start an assistant task without
// foreground navigation, such as the iOS share menu and notification replies.
// It mirrors ChatSendPipeline's WebSocket payloads and crypto handling while
// avoiding UI/store dependencies that are unavailable inside extensions.

import CryptoKit
import Foundation

actor BackgroundChatSender {
    struct DestinationChat: Identifiable, Decodable {
        let id: String
        var title: String?
        let lastMessageAt: String?
        let createdAt: String
        let updatedAt: String?
        let appId: String?
        let encryptedTitle: String?
        let encryptedCategory: String?
        let encryptedIcon: String?
        let encryptedChatKey: String?
        let messagesV: Int?
        let titleV: Int?

        var displayTitle: String {
            let trimmed = title?.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed?.isEmpty == false ? trimmed! : "Untitled chat"
        }

        init(
            id: String,
            title: String?,
            lastMessageAt: String?,
            createdAt: String,
            updatedAt: String?,
            appId: String?,
            encryptedTitle: String?,
            encryptedCategory: String?,
            encryptedIcon: String?,
            encryptedChatKey: String?,
            messagesV: Int?,
            titleV: Int?
        ) {
            self.id = id
            self.title = title
            self.lastMessageAt = lastMessageAt
            self.createdAt = createdAt
            self.updatedAt = updatedAt
            self.appId = appId
            self.encryptedTitle = encryptedTitle
            self.encryptedCategory = encryptedCategory
            self.encryptedIcon = encryptedIcon
            self.encryptedChatKey = encryptedChatKey
            self.messagesV = messagesV
            self.titleV = titleV
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            id = try container.decodeIfPresent(String.self, forKey: .id)
                ?? container.decode(String.self, forKey: .chatId)
            title = try container.decodeIfPresent(String.self, forKey: .title)
            lastMessageAt = Self.decodeFlexibleDateString(container, .lastMessageAt)
                ?? Self.decodeFlexibleDateString(container, .lastMessageTimestamp)
                ?? Self.decodeFlexibleDateString(container, .lastEditedOverallTimestamp)
                ?? Self.decodeFlexibleDateString(container, .updatedAt)
            createdAt = Self.decodeFlexibleDateString(container, .createdAt)
                ?? Self.decodeFlexibleDateString(container, .updatedAt)
                ?? ISO8601DateFormatter().string(from: Date())
            updatedAt = Self.decodeFlexibleDateString(container, .updatedAt)
            appId = try container.decodeIfPresent(String.self, forKey: .appId)
            encryptedTitle = try container.decodeIfPresent(String.self, forKey: .encryptedTitle)
            encryptedCategory = try container.decodeIfPresent(String.self, forKey: .encryptedCategory)
            encryptedIcon = try container.decodeIfPresent(String.self, forKey: .encryptedIcon)
            encryptedChatKey = try container.decodeIfPresent(String.self, forKey: .encryptedChatKey)
            messagesV = try container.decodeIfPresent(Int.self, forKey: .messagesV)
            titleV = try container.decodeIfPresent(Int.self, forKey: .titleV)
        }

        private static func decodeFlexibleDateString(
            _ container: KeyedDecodingContainer<CodingKeys>,
            _ key: CodingKeys
        ) -> String? {
            if let value = try? container.decodeIfPresent(String.self, forKey: key) {
                return value
            }
            if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
                return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: TimeInterval(value)))
            }
            if let value = try? container.decodeIfPresent(Double.self, forKey: key) {
                return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: value))
            }
            return nil
        }

        private enum CodingKeys: String, CodingKey {
            case id
            case chatId
            case title
            case lastMessageAt
            case lastMessageTimestamp
            case lastEditedOverallTimestamp
            case createdAt
            case updatedAt
            case appId
            case encryptedTitle
            case encryptedCategory
            case encryptedIcon
            case encryptedChatKey
            case messagesV
            case titleV
        }
    }

    struct SendRequest {
        let content: String
        let destination: DestinationChat?
    }

    struct SendResult {
        let chatId: String
        let messageId: String
    }

    private struct CachedUser: Decodable {
        let id: String
    }

    private struct SessionRequest: Encodable {
        let sessionId: String
        let deviceInfo: DeviceInfo
    }

    private struct DeviceInfo: Encodable {
        let os: String
        let deviceModel: String
        let appVersion: String
    }

    private struct SessionResponse: Decodable {
        let success: Bool
        let user: CachedUser?
        let wsToken: String?
        let needsDeviceVerification: Bool?
        let reAuthRequired: String?
        let reAuthReason: String?
    }

    private struct ChatSyncWrapper: Decodable {
        let chatDetails: DestinationChat?
    }

    private struct ChatSyncPayload: Decodable {
        let chats: [ChatSyncWrapper]?
    }

    private struct WSEnvelope<T: Decodable>: Decodable {
        let type: String
        let data: T?
        let payload: T?
    }

    private struct InboundMessage: Decodable {
        let type: String
        let data: [String: AnyCodable]?
        let payload: [String: AnyCodable]?

        func stringField(_ key: String) -> String? {
            if let value = payload?[key]?.value as? String { return value }
            if let value = data?[key]?.value as? String { return value }
            return nil
        }

        func stringArrayField(_ key: String) -> [String] {
            if let values = payload?[key]?.value as? [String] { return values }
            if let values = payload?[key]?.value as? [Any] { return values.compactMap { $0 as? String } }
            if let values = data?[key]?.value as? [String] { return values }
            if let values = data?[key]?.value as? [Any] { return values.compactMap { $0 as? String } }
            return []
        }
    }

    private struct ChatMetadata {
        let title: String?
        let iconNames: [String]
        let category: String?
        let userMessageId: String?
        let encryptedChatKey: String?
    }

    private let crypto = CryptoManager.shared
    private let decoder: JSONDecoder
    private let encoder = JSONEncoder()
    private let session: URLSession
    private var chatKeyCache: [String: SymmetricKey] = [:]

    init() {
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        session = URLSession(configuration: config)
    }

    func loadRecentChats(limit: Int = 12) async throws -> [DestinationChat] {
        let auth = try await currentAuthenticatedUser()
        let ws = try await BackgroundWebSocket.open(session: session, sessionId: nativeSessionId, token: auth.wsToken)
        defer { ws.close() }

        try await ws.send(type: "phased_sync_request", payload: [
            "phase": "all",
            "client_chat_versions": [:],
            "client_chat_ids": [],
            "client_suggestions_count": 0,
            "client_embed_ids": []
        ])

        let deadline = Date().addingTimeInterval(8)
        while Date() < deadline {
            let data = try await ws.receiveData()
            guard let envelope = try? decoder.decode(WSEnvelope<ChatSyncPayload>.self, from: data),
                  envelope.type == "phase_2_last_20_chats_ready" || envelope.type == "sync_metadata_chats_response",
                  let payload = envelope.payload ?? envelope.data else {
                continue
            }
            var chats = (payload.chats ?? []).compactMap(\.chatDetails)
            chats = try await decryptDisplayTitles(for: chats, userId: auth.userId)
            return Array(chats.prefix(limit))
        }
        return []
    }

    func send(_ request: SendRequest) async throws -> SendResult {
        let trimmed = request.content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw BackgroundChatSendError.emptyMessage }

        let auth = try await currentAuthenticatedUser()
        let now = Date()
        let createdAtUnix = Int(now.timeIntervalSince1970)
        let chatId = request.destination?.id ?? UUID().uuidString
        let messageId = "\(chatId.suffix(10))-\(UUID().uuidString)"
        let keyMaterial = try await ensureChatKey(
            chatId: chatId,
            encryptedChatKey: request.destination?.encryptedChatKey,
            userId: auth.userId
        )
        let encryptedContent = try await crypto.encryptContent(trimmed, key: keyMaterial.key)
        let nextMessagesV = max(request.destination?.messagesV ?? 0, 0) + 1

        let ws = try await BackgroundWebSocket.open(session: session, sessionId: nativeSessionId, token: auth.wsToken)
        defer { ws.close() }

        var messagePayload: [String: Any] = [
            "message_id": messageId,
            "role": "user",
            "content": trimmed,
            "created_at": createdAtUnix,
            "sender_name": "user",
            "chat_has_title": (request.destination?.titleV ?? 0) > 0
        ]
        if (request.destination?.titleV ?? 0) > 0 {
            messagePayload["current_chat_title"] = request.destination?.title
        }

        try await ws.send(type: "chat_message_added", payload: [
            "chat_id": chatId,
            "message": messagePayload,
            "encrypted_chat_key": keyMaterial.encryptedChatKey
        ])

        if let storage = try await waitForAssistantStart(ws: ws, chatId: chatId, userMessageId: messageId) {
            try await sendEncryptedUserStoragePackage(
                ws: ws,
                chatId: chatId,
                messageId: messageId,
                content: trimmed,
                encryptedContent: encryptedContent,
                createdAtUnix: createdAtUnix,
                encryptedChatKey: storage.metadata.encryptedChatKey ?? keyMaterial.encryptedChatKey,
                key: keyMaterial.key,
                taskId: storage.taskId,
                metadata: storage.metadata,
                isNewChat: request.destination == nil || (request.destination?.titleV ?? 0) == 0,
                messagesV: nextMessagesV,
                currentTitleV: request.destination?.titleV ?? 0
            )
        }

        return SendResult(chatId: chatId, messageId: messageId)
    }

    private func waitForAssistantStart(
        ws: BackgroundWebSocket,
        chatId: String,
        userMessageId: String
    ) async throws -> (taskId: String, metadata: ChatMetadata)? {
        var taskId: String?
        var metadata: ChatMetadata?
        let deadline = Date().addingTimeInterval(20)

        while Date() < deadline {
            let data = try await ws.receiveData()
            guard let inbound = try? decoder.decode(InboundMessage.self, from: data) else { continue }
            switch inbound.type {
            case "ai_task_initiated":
                if inbound.stringField("chat_id") == chatId,
                   inbound.stringField("user_message_id") == userMessageId {
                    taskId = inbound.stringField("ai_task_id") ?? inbound.stringField("task_id")
                }
            case "ai_typing_started":
                guard inbound.stringField("chat_id") == chatId else { continue }
                let candidate = ChatMetadata(
                    title: inbound.stringField("title"),
                    iconNames: inbound.stringArrayField("icon_names"),
                    category: inbound.stringField("category"),
                    userMessageId: inbound.stringField("user_message_id"),
                    encryptedChatKey: inbound.stringField("encrypted_chat_key")
                )
                if candidate.userMessageId == nil || candidate.userMessageId == userMessageId {
                    metadata = candidate
                }
            case "message_queued":
                return nil
            default:
                break
            }
            if let taskId, let metadata {
                return (taskId, metadata)
            }
        }

        return nil
    }

    private func sendEncryptedUserStoragePackage(
        ws: BackgroundWebSocket,
        chatId: String,
        messageId: String,
        content: String,
        encryptedContent: String,
        createdAtUnix: Int,
        encryptedChatKey: String,
        key: SymmetricKey,
        taskId: String,
        metadata: ChatMetadata,
        isNewChat: Bool,
        messagesV: Int,
        currentTitleV: Int
    ) async throws {
        let encryptedTitle = isNewChat ? try await encryptOptional(metadata.title, key: key) : nil
        let icon = isNewChat ? preferredIcon(from: metadata.iconNames, category: metadata.category) : nil
        let encryptedIcon = try await encryptOptional(icon, key: key)
        let encryptedChatCategory = isNewChat ? try await encryptOptional(metadata.category, key: key) : nil
        let encryptedSenderName = try await crypto.encryptContent("user", key: key)
        let encryptedUserCategory = try await encryptOptional(metadata.category, key: key)

        var payload: [String: Any] = [
            "chat_id": chatId,
            "message_id": messageId,
            "encrypted_content": encryptedContent,
            "created_at": createdAtUnix,
            "encrypted_chat_key": encryptedChatKey,
            "versions": [
                "messages_v": messagesV,
                "title_v": encryptedTitle == nil ? currentTitleV : currentTitleV + 1,
                "last_edited_overall_timestamp": createdAtUnix
            ],
            "task_id": taskId,
            "encrypted_sender_name": encryptedSenderName
        ]
        if let encryptedTitle { payload["encrypted_title"] = encryptedTitle }
        if let encryptedIcon { payload["encrypted_icon"] = encryptedIcon }
        if let encryptedChatCategory { payload["encrypted_chat_category"] = encryptedChatCategory }
        if let encryptedUserCategory { payload["encrypted_category"] = encryptedUserCategory }

        try await ws.send(type: "encrypted_chat_metadata", payload: payload)
    }

    private func decryptDisplayTitles(for chats: [DestinationChat], userId: String) async throws -> [DestinationChat] {
        guard let masterKey = try await crypto.loadMasterKey(for: userId) else {
            throw BackgroundChatSendError.missingMasterKey
        }

        var decrypted: [DestinationChat] = []
        for var chat in chats {
            if let encryptedTitle = chat.encryptedTitle,
               let encryptedChatKey = chat.encryptedChatKey,
               let chatKey = try? await crypto.unwrapChatKey(encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey),
               let title = try? await crypto.decryptContent(base64String: encryptedTitle, key: chatKey) {
                chat.title = title
            }
            decrypted.append(chat)
        }
        return decrypted
    }

    private func ensureChatKey(
        chatId: String,
        encryptedChatKey: String?,
        userId: String
    ) async throws -> (key: SymmetricKey, encryptedChatKey: String) {
        guard let masterKey = try await crypto.loadMasterKey(for: userId) else {
            throw BackgroundChatSendError.missingMasterKey
        }
        if let key = chatKeyCache[chatId] {
            let encrypted: String
            if let encryptedChatKey {
                encrypted = encryptedChatKey
            } else {
                encrypted = try await crypto.wrapChatKey(key, masterKey: masterKey)
            }
            return (key, encrypted)
        }
        if let encryptedChatKey {
            let key = try await crypto.unwrapChatKey(encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey)
            chatKeyCache[chatId] = key
            return (key, encryptedChatKey)
        }
        let key = await crypto.generateChatKey()
        chatKeyCache[chatId] = key
        return (key, try await crypto.wrapChatKey(key, masterKey: masterKey))
    }

    private func encryptOptional(_ value: String?, key: SymmetricKey) async throws -> String? {
        guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return try await crypto.encryptContent(value, key: key)
    }

    private func preferredIcon(from iconNames: [String], category: String?) -> String {
        iconNames.first ?? categoryIconFallback(category)
    }

    private func categoryIconFallback(_ category: String?) -> String {
        switch category {
        case "web": return "search"
        case "travel": return "plane"
        case "videos": return "video"
        case "nutrition": return "utensils"
        case "code": return "code"
        default: return "sparkles"
        }
    }

    private func currentAuthenticatedUser() async throws -> (userId: String, wsToken: String?) {
        let response: SessionResponse = try await apiRequest(
            .post,
            path: "/v1/auth/session",
            body: SessionRequest(sessionId: nativeSessionId, deviceInfo: makeDeviceInfo())
        )
        guard response.success, response.needsDeviceVerification != true, let user = response.user else {
            if response.reAuthRequired != nil || response.reAuthReason != nil {
                throw BackgroundChatSendError.notAuthenticated
            }
            throw BackgroundChatSendError.notAuthenticated
        }
        guard (try? await crypto.loadMasterKey(for: user.id)) != nil else {
            throw BackgroundChatSendError.missingMasterKey
        }
        return (user.id, response.wsToken)
    }

    private var nativeSessionId: String {
        let key = "openmates.apple.auth.session_id"
        if let existing = OpenMatesSharedEnvironment.defaults.string(forKey: key) {
            return existing
        }
        if let existing = UserDefaults.standard.string(forKey: key) {
            OpenMatesSharedEnvironment.defaults.set(existing, forKey: key)
            return existing
        }
        let newValue = UUID().uuidString
        OpenMatesSharedEnvironment.defaults.set(newValue, forKey: key)
        UserDefaults.standard.set(newValue, forKey: key)
        return newValue
    }

    private func apiRequest<T: Decodable, Body: Encodable>(
        _ method: BackgroundHTTPMethod,
        path: String,
        body: Body
    ) async throws -> T {
        var request = buildRequest(method, path: path)
        request.httpBody = try encoder.encode(body)
        return try await execute(request)
    }

    private func buildRequest(_ method: BackgroundHTTPMethod, path: String) -> URLRequest {
        let normalizedPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        let pathAndQuery = normalizedPath.split(separator: "?", maxSplits: 1).map(String.init)
        var url = ServerConfiguration.current.apiBaseURL.appendingPathComponent(pathAndQuery[0])
        if pathAndQuery.count == 2, var components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            components.percentEncodedQuery = pathAndQuery[1]
            url = components.url ?? url
        }

        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(ServerConfiguration.current.webAppURL.absoluteString, forHTTPHeaderField: "Origin")
        request.setValue("OpenMates-Apple/\(appVersion)", forHTTPHeaderField: "User-Agent")
        request.setValue(platformIdentifier, forHTTPHeaderField: "X-OpenMates-Client")
        request.setValue(Bundle.main.bundleIdentifier ?? "org.openmates.app", forHTTPHeaderField: "X-OpenMates-Bundle-ID")
        return request
    }

    private func execute<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw BackgroundChatSendError.network
        }
        guard (200...299).contains(httpResponse.statusCode) else {
            if httpResponse.statusCode == 401 { throw BackgroundChatSendError.notAuthenticated }
            throw BackgroundChatSendError.server(httpResponse.statusCode)
        }
        return try decoder.decode(T.self, from: data)
    }

    private func makeDeviceInfo() -> DeviceInfo {
        #if os(iOS)
        let os = "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        let model = "iOS Extension"
        #elseif os(macOS)
        let os = "macOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        let model = "macOS Extension"
        #else
        let os = "Apple \(ProcessInfo.processInfo.operatingSystemVersionString)"
        let model = "Apple Extension"
        #endif
        return DeviceInfo(os: os, deviceModel: model, appVersion: appVersion)
    }

    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
    }

    private var platformIdentifier: String {
        #if os(iOS)
        return "ios-share-extension"
        #elseif os(macOS)
        return "macos-share-extension"
        #else
        return "apple-extension"
        #endif
    }
}

private final class BackgroundWebSocket: @unchecked Sendable {
    private let task: URLSessionWebSocketTask
    private let encoder = JSONEncoder()

    private init(task: URLSessionWebSocketTask) {
        self.task = task
    }

    static func open(session: URLSession, sessionId: String, token: String?) async throws -> BackgroundWebSocket {
        guard var components = URLComponents(url: ServerConfiguration.current.apiBaseURL, resolvingAgainstBaseURL: false) else {
            throw BackgroundChatSendError.network
        }
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        components.path = "/v1/ws"
        var queryItems = [URLQueryItem(name: "sessionId", value: sessionId)]
        if let token, !token.isEmpty {
            queryItems.append(URLQueryItem(name: "token", value: token))
        }
        components.queryItems = queryItems
        guard let url = components.url else { throw BackgroundChatSendError.network }

        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        request.setValue(ServerConfiguration.current.webAppURL.absoluteString, forHTTPHeaderField: "Origin")
        request.setValue("OpenMates-Apple/\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0")", forHTTPHeaderField: "User-Agent")
        request.setValue(Bundle.main.bundleIdentifier ?? "org.openmates.app", forHTTPHeaderField: "X-OpenMates-Bundle-ID")

        let task = session.webSocketTask(with: request)
        task.resume()
        let ws = BackgroundWebSocket(task: task)
        try await ws.waitForOpenSocket()
        return ws
    }

    func send(type: String, payload: [String: Any]) async throws {
        let outbound = BackgroundWSOutboundMessage(type: type, payload: payload)
        let data = try encoder.encode(outbound)
        guard let text = String(data: data, encoding: .utf8) else {
            throw BackgroundChatSendError.encoding
        }
        try await task.send(.string(text))
    }

    func receiveData() async throws -> Data {
        let message = try await task.receive()
        switch message {
        case .string(let text):
            guard let data = text.data(using: .utf8) else { throw BackgroundChatSendError.encoding }
            return data
        case .data(let data):
            return data
        @unknown default:
            throw BackgroundChatSendError.network
        }
    }

    func close() {
        task.cancel(with: .normalClosure, reason: nil)
    }

    private func waitForOpenSocket() async throws {
        try await Task.sleep(for: .milliseconds(650))
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            task.sendPing { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            }
        }
    }
}

private struct BackgroundWSOutboundMessage: Encodable {
    let type: String
    let payload: [String: AnyCodable]

    init(type: String, payload: [String: Any]) {
        self.type = type
        self.payload = payload.mapValues { AnyCodable($0) }
    }
}

enum BackgroundChatSendError: LocalizedError {
    case emptyMessage
    case notAuthenticated
    case missingMasterKey
    case network
    case encoding
    case server(Int)

    var errorDescription: String? {
        switch self {
        case .emptyMessage:
            return "Nothing to send."
        case .notAuthenticated:
            return "Open OpenMates and sign in first."
        case .missingMasterKey:
            return "Open OpenMates and sign in again to unlock encryption on this device."
        case .network:
            return "OpenMates could not connect. Please try again."
        case .encoding:
            return "OpenMates could not prepare the message."
        case .server(let status):
            return "OpenMates server error (\(status))."
        }
    }
}

private enum BackgroundHTTPMethod: String {
    case get = "GET"
    case post = "POST"
}
