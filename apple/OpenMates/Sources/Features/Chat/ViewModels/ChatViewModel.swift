// Chat view model — manages messages, streaming, and embeds for a single chat.
// Handles the dual-channel protocol: REST POST to send, WebSocket for streaming.
// Subscribes to StreamingClient for real-time AI response chunks.

import Foundation
import SwiftUI

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var chat: Chat?
    @Published var messages: [Message] = []
    @Published var embedRecords: [String: EmbedRecord] = [:]
    @Published var isLoading = false
    @Published var isStreaming = false
    @Published var streamingContent = ""
    @Published var streamingMessageId: String?
    @Published var followUpSuggestions: [String] = []
    @Published var error: String?

    /// Number of messages to show initially and per page when scrolling up.
    private let messagesPageSize = 50
    /// All messages fetched from the server (full history).
    private var allMessages: [Message] = []
    /// Whether there are older messages above the currently visible window.
    @Published var hasOlderMessages = false
    @Published var isLoadingOlder = false

    private let api = APIClient.shared
    private var streamTask: Task<Void, Never>?
    nonisolated(unsafe) private var embedRefreshObserver: Any?

    func loadChat(id: String) async {
        isLoading = true
        error = nil

        if loadPublicChat(id: id) {
            isLoading = false
            return
        }

        do {
            var loadedChat: Chat = try await api.request(.get, path: "/v1/chats/\(id)")

            // Ensure chat key is loaded (may not be if chat was opened via deep link)
            await ensureChatKey(for: loadedChat)

            // Decrypt chat title
            if let encTitle = loadedChat.encryptedTitle,
               let decrypted = await ChatKeyManager.shared.decryptTitle(
                   for: id, encryptedTitle: encTitle
               ) {
                loadedChat.title = decrypted
            }
            chat = loadedChat

            let messagesResponse: [Message] = try await api.request(.get, path: "/v1/chats/\(id)/messages")

            // Decrypt all message content
            allMessages = await decryptMessages(messagesResponse, chatId: id)

            // Show only the most recent page initially for fast rendering
            if allMessages.count > messagesPageSize {
                messages = Array(allMessages.suffix(messagesPageSize))
                hasOlderMessages = true
            } else {
                messages = allMessages
                hasOlderMessages = false
            }

            // Load embeds for visible messages
            await loadEmbeds(for: messages.map(\.id))

            // Start listening for streaming events and embed updates
            subscribeToStream(chatId: id)
            subscribeToEmbedUpdates(chatId: id)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    // MARK: - Public bundled chats

    private func loadPublicChat(id: String) -> Bool {
        guard let publicChat = PublicChatContent.chat(for: id) else { return false }

        chat = publicChat.chat
        embedRecords = publicChat.embedRecords
        allMessages = publicChat.messages
        messages = publicChat.messages
        followUpSuggestions = publicChat.followUpSuggestions
        hasOlderMessages = false
        isLoadingOlder = false
        isStreaming = false
        streamingContent = ""
        streamingMessageId = nil
        streamTask?.cancel()
        return true
    }

    /// Ensure the chat key is available (load from master key if not cached).
    private func ensureChatKey(for chat: Chat) async {
        guard !ChatKeyManager.shared.hasKey(for: chat.id),
              let encryptedChatKey = chat.encryptedChatKey else { return }

        // Try to load master key and unwrap this chat's key
        guard let userId = await AuthManager.currentUserId(),
              let masterKey = try? await CryptoManager.shared.loadMasterKey(for: userId) else {
            return
        }

        await ChatKeyManager.shared.loadChatKey(
            chatId: chat.id,
            encryptedChatKey: encryptedChatKey,
            masterKey: masterKey
        )
    }

    /// Decrypt encrypted_content for a batch of messages using the per-chat key.
    private func decryptMessages(_ messages: [Message], chatId: String) async -> [Message] {
        var result: [Message] = []
        for var msg in messages {
            if msg.content == nil || msg.content?.isEmpty == true,
               let enc = msg.encryptedContent {
                if let decrypted = await ChatKeyManager.shared.decryptMessageContent(
                    chatId: chatId, encryptedContent: enc
                ) {
                    msg.content = decrypted
                }
            }
            result.append(msg)
        }
        return result
    }

    /// Load the next page of older messages above the current window.
    func loadOlderMessages() {
        guard hasOlderMessages, !isLoadingOlder else { return }
        isLoadingOlder = true

        let currentCount = messages.count
        let totalCount = allMessages.count
        let remaining = totalCount - currentCount

        if remaining > 0 {
            let nextPageSize = min(messagesPageSize, remaining)
            let startIndex = remaining - nextPageSize
            let olderBatch = Array(allMessages[startIndex..<remaining])
            messages.insert(contentsOf: olderBatch, at: 0)
            hasOlderMessages = startIndex > 0

            // Load embeds for newly visible messages
            Task {
                await loadEmbeds(for: olderBatch.map(\.id))
            }
        } else {
            hasOlderMessages = false
        }

        isLoadingOlder = false
    }

    // MARK: - Send message

    func sendMessage(_ content: String) async {
        guard let chatId = chat?.id else { return }

        let userMessageId = UUID().uuidString
        let userMessage = Message(
            id: userMessageId, chatId: chatId, role: .user,
            content: content, encryptedContent: nil,
            createdAt: ISO8601DateFormatter().string(from: Date()),
            updatedAt: nil, appId: nil, isStreaming: nil, embedRefs: nil
        )
        allMessages.append(userMessage)
        messages.append(userMessage)

        isStreaming = true
        streamingContent = ""

        do {
            let body: [String: Any] = [
                "chat_id": chatId,
                "message": [
                    "message_id": userMessageId,
                    "role": "user",
                    "content": content,
                    "created_at": Int(Date().timeIntervalSince1970),
                    "chat_has_title": (chat?.title != nil)
                ] as [String: Any]
            ]

            let _: Data = try await api.request(.post, path: "/v1/chat/message", body: body)
        } catch {
            self.error = error.localizedDescription
            isStreaming = false
        }
    }

    // MARK: - Stop streaming

    func stopStreaming() {
        streamTask?.cancel()
        isStreaming = false
        streamingContent = ""
        streamingMessageId = nil
    }

    // MARK: - Streaming subscription

    private func subscribeToStream(chatId: String) {
        streamTask?.cancel()
        streamTask = Task {
            let stream = await StreamingClient.shared.streamForChat(chatId)
            for await event in stream {
                guard !Task.isCancelled else { break }
                handleStreamEvent(event)
            }
        }
    }

    private func handleStreamEvent(_ event: StreamingClient.StreamEvent) {
        switch event {
        case .taskInitiated(_, _, _):
            isStreaming = true
            streamingContent = ""

        case .typingStarted(_, let messageId, _):
            streamingMessageId = messageId

        case .chunk(_, let messageId, _, let content, let isFinal):
            streamingMessageId = messageId
            streamingContent = content

            if isFinal {
                let assistantMessage = Message(
                    id: messageId, chatId: chat?.id ?? "", role: .assistant,
                    content: content, encryptedContent: nil,
                    createdAt: ISO8601DateFormatter().string(from: Date()),
                    updatedAt: nil, appId: chat?.appId, isStreaming: false, embedRefs: nil
                )
                allMessages.append(assistantMessage)
                messages.append(assistantMessage)
                isStreaming = false
                streamingContent = ""
                streamingMessageId = nil
            }

        case .thinkingChunk(_, _, _):
            break

        case .thinkingComplete(_, _):
            break

        case .messageReady(_, _):
            isStreaming = false

        case .preprocessingStep(_, _, _):
            break

        case .error(let msg):
            error = msg
            isStreaming = false
        }
    }

    // MARK: - Embed update subscription

    /// Listen for WebSocket embed updates and reload embeds for this chat.
    private func subscribeToEmbedUpdates(chatId: String) {
        embedRefreshObserver = NotificationCenter.default.addObserver(
            forName: .embedRefreshNeeded, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.chat?.id == chatId else { return }
                await self.loadEmbeds(for: self.messages.map(\.id))
            }
        }
    }

    deinit {
        if let observer = embedRefreshObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    // MARK: - Message actions

    func deleteMessage(_ messageId: String) async {
        guard let chatId = chat?.id else { return }
        do {
            let _: Data = try await api.request(
                .delete, path: "/v1/chats/\(chatId)/messages/\(messageId)"
            )
            messages.removeAll { $0.id == messageId }
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// Fork a conversation from a specific message. Returns the new chat ID
    /// so the caller can navigate to it.
    @Published var forkedChatId: String?

    func forkFromMessage(_ messageId: String) async {
        guard let chatId = chat?.id else { return }
        do {
            let response: [String: AnyCodable] = try await api.request(
                .post, path: "/v1/chats/\(chatId)/fork",
                body: ["from_message_id": messageId]
            )
            if let newChatId = response["chat_id"]?.value as? String {
                ToastManager.shared.show("Conversation forked", type: .success)
                forkedChatId = newChatId
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    // MARK: - Embed loading

    func loadEmbeds(for messageIds: [String]) async {
        guard let chatId = chat?.id else { return }
        do {
            let response: [EmbedRecord] = try await api.request(
                .get, path: "/v1/chats/\(chatId)/embeds"
            )
            for embed in response {
                embedRecords[embed.id] = embed
            }
        } catch {
            print("[Chat] Failed to load embeds: \(error)")
        }
    }

    func embeds(for message: Message) -> [EmbedRecord] {
        message.embedRefs?.compactMap { ref in
            embedRecords[ref.id]
        } ?? []
    }

    func childEmbeds(for embed: EmbedRecord) -> [EmbedRecord] {
        embed.childEmbedIds.compactMap { embedRecords[$0] }
    }

    func isStreamingMessage(_ messageId: String) -> Bool {
        streamingMessageId == messageId && isStreaming
    }

    // MARK: - Attachment upload

    func uploadAttachment(data: Data, filename: String) async {
        guard let chatId = chat?.id else { return }

        let boundary = UUID().uuidString
        var body = Data()

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n".data(using: .utf8)!)
        body.append(chatId.data(using: .utf8)!)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        do {
            let uploadURL = await APIClient.shared.baseURL
                .deletingLastPathComponent()
                .appendingPathComponent("upload/v1/files")
            var request = URLRequest(url: uploadURL)
            request.httpMethod = "POST"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.httpBody = body

            let (_, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  (200...299).contains(httpResponse.statusCode) else {
                print("[Chat] Upload failed")
                return
            }
        } catch {
            print("[Chat] Upload error: \(error)")
        }
    }

    func uploadFile(url: URL) async {
        guard let data = try? Data(contentsOf: url) else { return }
        await uploadAttachment(data: data, filename: url.lastPathComponent)
    }
}

@MainActor
private enum PublicChatContent {
    struct PublicChat {
        let chat: Chat
        let messages: [Message]
        let followUpSuggestions: [String]
        let embedRecords: [String: EmbedRecord]
    }

    static func chat(for id: String) -> PublicChat? {
        let createdAt = "2026-04-20T12:00:00Z"

        switch id {
        case "demo-for-everyone":
            return publicChat(
                id: id,
                title: AppStrings.demoForEveryoneTitle,
                appId: "ai",
                createdAt: createdAt,
                messages: [
                    assistant(id: "for-everyone-1", chatId: id, contentKey: "demo_chats.for_everyone.message", createdAt: createdAt, appId: "ai")
                ],
                followUpKeys: demoFollowUpKeys("for_everyone")
            )
        case "demo-for-developers":
            return publicChat(
                id: id,
                title: AppStrings.demoForDevelopersTitle,
                appId: "code",
                createdAt: createdAt,
                messages: [
                    assistant(id: "for-developers-1", chatId: id, contentKey: "demo_chats.for_developers.message", createdAt: createdAt, appId: "code")
                ],
                followUpKeys: demoFollowUpKeys("for_developers")
            )
        case "demo-who-develops-openmates":
            return publicChat(
                id: id,
                title: AppStrings.demoWhoDevTitle,
                appId: "ai",
                createdAt: createdAt,
                messages: [
                    assistant(id: "who-develops-openmates-1", chatId: id, contentKey: "demo_chats.who_develops_openmates.message", createdAt: createdAt, appId: "ai")
                ],
                followUpKeys: demoFollowUpKeys("who_develops_openmates")
            )
        case "announcements-introducing-openmates-v09":
            return publicChat(
                id: id,
                title: AppStrings.demoAnnouncementsV09Title,
                appId: "ai",
                createdAt: createdAt,
                messages: [
                    assistant(id: "announcements-introducing-openmates-v09-1", chatId: id, contentKey: "demo_chats.announcements_introducing_openmates_v09.message", createdAt: createdAt, appId: "ai")
                ],
                followUpKeys: []
            )
        case "legal-privacy":
            return legalChat(
                id: id,
                title: AppStrings.legalPrivacyTitle,
                content: legalPrivacyContent(),
                followUpKeys: (1...6).map { "legal.privacy.follow_up_\($0)" },
                createdAt: "2026-04-16T18:00:00Z"
            )
        case "legal-terms":
            return legalChat(
                id: id,
                title: AppStrings.legalTermsTitle,
                content: legalTermsContent(),
                followUpKeys: (1...6).map { "legal.terms.follow_up_\($0)" },
                createdAt: "2026-01-28T00:00:00Z"
            )
        case "legal-imprint":
            return legalChat(
                id: id,
                title: AppStrings.legalImprintTitle,
                content: legalImprintContent(),
                followUpKeys: (1...5).map { "legal.imprint.follow_up_\($0)" },
                createdAt: "2026-01-28T00:00:00Z"
            )
        default:
            return exampleChat(for: id, createdAt: createdAt)
        }
    }

    private static func exampleChat(for id: String, createdAt: String) -> PublicChat? {
        let specs: [String: (title: String, appId: String, messages: [MessageSpec], followUps: ClosedRange<Int>)] = [
            "example-gigantic-airplanes": (
                AppStrings.exampleGiganticAirplanesTitle,
                "ai",
                [
                    .user("example-gigantic-airplanes-user-1", "example_chats.gigantic_airplanes.user_message_1"),
                    .assistant("example-gigantic-airplanes-assistant-1", "example_chats.gigantic_airplanes.assistant_message_1"),
                    .user("example-gigantic-airplanes-user-2", "example_chats.gigantic_airplanes.user_message_2"),
                    .assistant("example-gigantic-airplanes-assistant-2", "example_chats.gigantic_airplanes.assistant_message_2")
                ],
                1...6
            ),
            "example-artemis-ii-mission": (
                AppStrings.exampleArtemisMissionTitle,
                "ai",
                [
                    .user("example-artemis-ii-mission-user-1", "example_chats.artemis_ii_mission.user_message_1"),
                    .assistant("example-artemis-ii-mission-assistant-2", "example_chats.artemis_ii_mission.assistant_message_2")
                ],
                1...4
            ),
            "example-beautiful-single-page-html": (
                AppStrings.exampleBeautifulHtmlTitle,
                "code",
                [
                    .user("example-beautiful-single-page-html-user-1", "example_chats.beautiful_single_page_html.user_message_1"),
                    .assistant("example-beautiful-single-page-html-assistant-2", "example_chats.beautiful_single_page_html.assistant_message_2")
                ],
                1...6
            ),
            "example-eu-chat-control-law": (
                AppStrings.exampleEuChatControlTitle,
                "legal",
                [
                    .user("example-eu-chat-control-law-user-1", "example_chats.eu_chat_control_law.user_message_1"),
                    .assistant("example-eu-chat-control-law-assistant-1", "example_chats.eu_chat_control_law.assistant_message_1")
                ],
                1...6
            ),
            "example-flights-berlin-bangkok": (
                AppStrings.exampleFlightsBerlinBangkokTitle,
                "travel",
                [
                    .user("example-flights-berlin-bangkok-user-1", "example_chats.flights_berlin_bangkok.user_message_1"),
                    .assistant("example-flights-berlin-bangkok-assistant-1", "example_chats.flights_berlin_bangkok.assistant_message_1")
                ],
                1...6
            ),
            "example-creativity-drawing-meetups-berlin": (
                AppStrings.exampleCreativityDrawingTitle,
                "events",
                [
                    .user("example-creativity-drawing-meetups-berlin-user-1", "example_chats.creativity_drawing_meetups_berlin.user_message_1"),
                    .assistant("example-creativity-drawing-meetups-berlin-assistant-1", "example_chats.creativity_drawing_meetups_berlin.assistant_message_1")
                ],
                1...6
            )
        ]

        guard let spec = specs[id] else { return nil }
        let messages = spec.messages.map { messageSpec in
            message(
                id: messageSpec.id,
                chatId: id,
                role: messageSpec.role,
                content: text(messageSpec.key),
                createdAt: createdAt,
                appId: messageSpec.role == .assistant ? spec.appId : nil
            )
        }
        return publicChat(
            id: id,
            title: spec.title,
            appId: spec.appId,
            createdAt: createdAt,
            messages: messages,
            followUpKeys: spec.followUps.map { "example_chats.\(exampleKey(for: id)).follow_up_\($0)" }
        )
    }

    private struct MessageSpec {
        let id: String
        let role: MessageRole
        let key: String

        static func user(_ id: String, _ key: String) -> MessageSpec {
            MessageSpec(id: id, role: .user, key: key)
        }

        static func assistant(_ id: String, _ key: String) -> MessageSpec {
            MessageSpec(id: id, role: .assistant, key: key)
        }
    }

    private static func publicChat(
        id: String,
        title: String,
        appId: String,
        createdAt: String,
        messages: [Message],
        followUpKeys: [String]
    ) -> PublicChat {
        let embedded = attachEmbeds(to: messages)

        return PublicChat(
            chat: Chat(
                id: id,
                title: title,
                lastMessageAt: createdAt,
                createdAt: createdAt,
                updatedAt: createdAt,
                isArchived: false,
                isPinned: id.hasPrefix("demo-"),
                appId: appId,
                encryptedTitle: nil,
                encryptedChatKey: nil
            ),
            messages: embedded.messages,
            followUpSuggestions: followUpKeys.map(text).filter { !$0.isEmpty && !$0.contains(".follow_up_") },
            embedRecords: embedded.records
        )
    }

    private static func legalChat(
        id: String,
        title: String,
        content: String,
        followUpKeys: [String],
        createdAt: String
    ) -> PublicChat {
        publicChat(
            id: id,
            title: title,
            appId: "ai",
            createdAt: createdAt,
            messages: [
                message(id: "\(id)-message-1", chatId: id, role: .assistant, content: content, createdAt: createdAt, appId: "ai")
            ],
            followUpKeys: followUpKeys
        )
    }

    private static func assistant(id: String, chatId: String, contentKey: String, createdAt: String, appId: String) -> Message {
        message(id: id, chatId: chatId, role: .assistant, content: text(contentKey), createdAt: createdAt, appId: appId)
    }

    private static func message(
        id: String,
        chatId: String,
        role: MessageRole,
        content: String,
        createdAt: String,
        appId: String?,
        embedRefs: [EmbedRef]? = nil
    ) -> Message {
        Message(
            id: id,
            chatId: chatId,
            role: role,
            content: sanitize(content),
            encryptedContent: nil,
            createdAt: createdAt,
            updatedAt: nil,
            appId: appId,
            isStreaming: false,
            embedRefs: embedRefs
        )
    }

    private static func attachEmbeds(to messages: [Message]) -> (messages: [Message], records: [String: EmbedRecord]) {
        var records: [String: EmbedRecord] = [:]
        let updatedMessages = messages.map { original in
            let extracted = extractEmbeds(from: original.content ?? "", fallbackAppId: original.appId)
            for record in extracted.records {
                records[record.id] = record
            }

            return Message(
                id: original.id,
                chatId: original.chatId,
                role: original.role,
                content: extracted.content,
                encryptedContent: original.encryptedContent,
                createdAt: original.createdAt,
                updatedAt: original.updatedAt,
                appId: original.appId,
                isStreaming: original.isStreaming,
                embedRefs: extracted.refs.isEmpty ? nil : extracted.refs
            )
        }
        return (updatedMessages, records)
    }

    private static func extractEmbeds(from content: String, fallbackAppId: String?) -> (content: String, refs: [EmbedRef], records: [EmbedRecord]) {
        var cleaned = content
        var refs: [EmbedRef] = []
        var records: [EmbedRecord] = []

        let jsonPattern = #"```json\s*([\s\S]*?)\s*```"#
        for match in regexMatches(jsonPattern, in: content).reversed() {
            guard let jsonRange = Range(match.range(at: 1), in: content),
                  let fullRange = Range(match.range(at: 0), in: cleaned) else { continue }

            let json = String(content[jsonRange])
            guard let data = json.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let type = object["type"] as? String,
                  let embedId = object["embed_id"] as? String else { continue }

            let record: EmbedRecord
            if type == "app_skill_use" {
                let appId = object["app_id"] as? String ?? fallbackAppId ?? "web"
                let skillId = object["skill_id"] as? String ?? "search"
                let embedType = "app:\(appId):\(skillId)"
                record = embedRecord(
                    id: embedId,
                    type: embedType,
                    appId: appId,
                    skillId: skillId,
                    data: object
                )
            } else if type == "code" {
                record = embedRecord(
                    id: embedId,
                    type: "code-code",
                    appId: "code",
                    skillId: nil,
                    data: ["code": "", "language": "html", "filename": "index.html"]
                )
            } else if type == "sheet" {
                record = embedRecord(
                    id: embedId,
                    type: "sheets-sheet",
                    appId: "sheets",
                    skillId: nil,
                    data: ["title": "Table", "rows": []]
                )
            } else {
                record = embedRecord(
                    id: embedId,
                    type: type,
                    appId: fallbackAppId,
                    skillId: nil,
                    data: object
                )
            }

            records.insert(record, at: 0)
            refs.insert(embedRef(for: record), at: 0)
            cleaned.replaceSubrange(fullRange, with: "")
        }

        let markdownEmbedPattern = #"!?\[[^\]]*\]\(embed:([^)]+)\)"#
        for match in regexMatches(markdownEmbedPattern, in: cleaned).reversed() {
            guard let refRange = Range(match.range(at: 1), in: cleaned),
                  let fullRange = Range(match.range(at: 0), in: cleaned) else { continue }

            let ref = String(cleaned[refRange])
            let record = markerEmbedRecord(ref: ref, fallbackAppId: fallbackAppId)
            records.insert(record, at: 0)
            refs.insert(embedRef(for: record), at: 0)
            cleaned.replaceSubrange(fullRange, with: "")
        }

        return (sanitize(cleaned), refs, records)
    }

    private static func markerEmbedRecord(ref: String, fallbackAppId: String?) -> EmbedRecord {
        let type = "web-website"

        let title = ref
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
        let host = ref.split(separator: "-").first.map(String.init) ?? ref
        let data: [String: Any] = [
            "title": title,
            "url": "https://\(host)",
            "description": "Referenced result from the example chat.",
            "thumbnail_url": ""
        ]

        return embedRecord(id: "static-\(ref)", type: type, appId: EmbedType(rawValue: type)?.appId ?? fallbackAppId, skillId: nil, data: data)
    }

    private static func embedRef(for record: EmbedRecord) -> EmbedRef {
        EmbedRef(id: record.id, type: record.type, status: record.status.rawValue, data: nil)
    }

    private static func embedRecord(
        id: String,
        type: String,
        appId: String?,
        skillId: String?,
        data: [String: Any]
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: .finished,
            data: .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: nil,
            appId: appId,
            skillId: skillId,
            embedIds: nil,
            createdAt: "2026-04-20T12:00:00Z"
        )
    }

    private static func regexMatches(_ pattern: String, in text: String) -> [NSTextCheckingResult] {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: []) else { return [] }
        return regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
    }

    private static func demoFollowUpKeys(_ key: String) -> [String] {
        (1...3).map { "demo_chats.\(key).follow_up_\($0)" }
    }

    private static func exampleKey(for id: String) -> String {
        switch id {
        case "example-gigantic-airplanes": return "gigantic_airplanes"
        case "example-artemis-ii-mission": return "artemis_ii_mission"
        case "example-beautiful-single-page-html": return "beautiful_single_page_html"
        case "example-eu-chat-control-law": return "eu_chat_control_law"
        case "example-flights-berlin-bangkok": return "flights_berlin_bangkok"
        case "example-creativity-drawing-meetups-berlin": return "creativity_drawing_meetups_berlin"
        default: return id
        }
    }

    private static func legalPrivacyContent() -> String {
        [
            "# \(AppStrings.legalPrivacyTitle)",
            "*\(text("legal.privacy.last_updated")): April 16, 2026*",
            section("legal.privacy.data_protection.heading", "legal.privacy.data_protection.overview"),
            text("legal.privacy.data_protection.website_vs_webapp"),
            section("legal.privacy.vercel.heading", "legal.privacy.vercel.description"),
            section("legal.privacy.webapp_services.heading", "legal.privacy.webapp_services.intro"),
            section("legal.privacy.hetzner.heading", "legal.privacy.hetzner.description"),
            section("legal.privacy.brevo.heading", "legal.privacy.brevo.description"),
            section("legal.privacy.stripe.heading", "legal.privacy.stripe.description"),
            section("legal.privacy.brave.heading", "legal.privacy.brave.description"),
            section("legal.privacy.google.heading", "legal.privacy.google.description"),
            section("legal.privacy.firecrawl.heading", "legal.privacy.firecrawl.description")
        ].joined(separator: "\n\n")
    }

    private static func legalTermsContent() -> String {
        [
            "# \(AppStrings.legalTermsTitle)",
            "*Last updated: January 28, 2026*",
            section("legal.terms.acceptance.heading", "legal.terms.acceptance.text"),
            section("legal.terms.service.heading", "legal.terms.service.text"),
            section("legal.terms.accounts.heading", "legal.terms.accounts.text"),
            section("legal.terms.credits.heading", "legal.terms.credits.text"),
            section("legal.terms.acceptable_use.heading", "legal.terms.acceptable_use.text"),
            section("legal.terms.privacy.heading", "legal.terms.privacy.text")
        ].filter { !$0.contains(".heading") && !$0.contains(".text") }.joined(separator: "\n\n")
    }

    private static func legalImprintContent() -> String {
        [
            "# \(AppStrings.legalImprintTitle)",
            "## \(text("legal.imprint.information_tmg"))",
            "OpenMates",
            "## \(text("legal.imprint.contact"))",
            "\(text("legal.imprint.email")): support@openmates.org"
        ].joined(separator: "\n\n")
    }

    private static func section(_ titleKey: String, _ bodyKey: String) -> String {
        "## \(text(titleKey))\n\n\(text(bodyKey))"
    }

    private static func text(_ key: String) -> String {
        LocalizationManager.shared.text(key)
    }

    private static func sanitize(_ content: String) -> String {
        let placeholders = [
            "[[example_chats_group]]",
            "[[dev_example_chats_group]]",
            "[[app_store_group]]",
            "[[dev_app_store_group]]",
            "[[skills_group]]",
            "[[dev_skills_group]]",
            "[[focus_modes_group]]",
            "[[dev_focus_modes_group]]",
            "[[settings_memories_group]]",
            "[[dev_settings_memories_group]]",
            "[[ai_models_group]]",
            "[[for_developers_embed]]"
        ]
        var cleaned = content
        for (index, placeholder) in placeholders.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: placeholder, with: "__OM_DEMO_PLACEHOLDER_\(index)__")
        }
        cleaned = cleaned
            .replacingOccurrences(of: #"\[\[[^\]]+\]\]"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: "\n\n\n", with: "\n\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        for (index, placeholder) in placeholders.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: "__OM_DEMO_PLACEHOLDER_\(index)__", with: placeholder)
        }
        return cleaned
    }
}
