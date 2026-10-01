// In-memory, unauthenticated encrypted shared-chat recipient foundation.
// Web: frontend/apps/web_app/src/routes/share/chat/[chatId]/+page.svelte
//      frontend/apps/web_app/src/routes/share/chat/shareChatEmbedUtils.ts
// API: backend/core/api/app/routes/share.py (public ciphertext endpoints)
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open, chat-share-settings.readonly-viewer-controls

import Combine
import CryptoKit
import Foundation

struct SharedChatRecipientContext {
    let originalURL: URL
    let resolvedURL: URL
    let chatKey: SymmetricKey
    var chat: Chat
    var messages: [Message]
    var embeds: [String: EmbedRecord]
    // Preserve opaque manifests for scoped highlights, checkpoints, code outputs,
    // application handoff and project/task rendering without installing owner state.
    let encryptedManifest: Data
    let targetMessageID: String?
    let sharePII: Bool
    let shareHighlights: Bool
    var hasMoreBefore: Bool
    var nextBeforeTimestamp: Int?
    var nextBeforeMessageID: String?
}

@MainActor
protocol SharedChatRecipientTransport {
    func get(_ url: URL) async throws -> Data
}

/// Dedicated ephemeral client: no auth, cookie storage, disk cache or external redirects.
final class SharedChatRecipientURLTransport: NSObject, SharedChatRecipientTransport, URLSessionTaskDelegate {
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.urlCredentialStorage = nil
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest = 30
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    @MainActor func get(_ url: URL) async throws -> Data {
        guard Self.allowed(url) else { throw SharedChatRecipientError.invalidLink }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard let response = response as? HTTPURLResponse,
              let finalURL = response.url, Self.allowed(finalURL), finalURL.host == url.host else {
            throw SharedChatRecipientError.network
        }
        switch response.statusCode {
        case 200...299: break
        case 404: throw url.path.contains("/short-url/") ? SharedChatRecipientError.shortLinkUnavailable : .unavailable
        case 429: throw url.path.contains("/short-url/") ? SharedChatRecipientError.shortLinkDisabled : .network
        default: throw SharedChatRecipientError.network
        }
        guard data.count <= 16 * 1024 * 1024 else { throw SharedChatRecipientError.invalidResponse }
        return data
    }

    nonisolated private static func allowed(_ url: URL) -> Bool {
        url.scheme == "https" && url.user == nil && url.password == nil && url.port == nil && url.fragment == nil &&
            ["api.openmates.org", "api.dev.openmates.org"].contains(url.host?.lowercased() ?? "") &&
            url.path.hasPrefix("/v1/share/")
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                               willPerformHTTPRedirection response: HTTPURLResponse,
                               newRequest request: URLRequest,
                               completionHandler: @escaping (URLRequest?) -> Void) {
        // Share API routes are canonical; refusing redirects also prevents leaking
        // recipient identifiers to a redirect target or attaching ambient auth.
        completionHandler(nil)
    }
}

@MainActor
final class SharedChatRecipientModel: ObservableObject {
    enum State { case idle, loading, passwordRequired, ready, failed(SharedChatRecipientError) }
    @Published private(set) var state: State = .idle
    @Published private(set) var context: SharedChatRecipientContext?
    @Published private(set) var isLoadingEarlier = false
    private let service: SharedChatRecipientService
    private var generation = UUID()
    private var loadingTask: Task<Void, Never>?
    var presentationScopeID: String { generation.uuidString }

    init(service: SharedChatRecipientService? = nil) { self.service = service ?? SharedChatRecipientService() }

    #if DEBUG
    convenience init(previewState: State, previewContext: SharedChatRecipientContext? = nil) {
        self.init()
        state = previewState
        context = previewContext
    }
    #endif

    /// Pass passwords directly into this operation; the model never retains them.
    @discardableResult func open(_ url: URL, password: String? = nil) -> Task<Void, Never> {
        cancel()
        let scope = generation
        state = .loading
        let service = service
        let task = Task { @MainActor [weak self] in
            do {
                let loaded = try await service.load(url, password: password)
                guard let self, self.generation == scope, !Task.isCancelled else { return }
                self.context = loaded
                self.state = .ready
            } catch is CancellationError {
                // A cancelled/replaced scope must never publish plaintext.
            } catch {
                guard let self, self.generation == scope, !Task.isCancelled else { return }
                let failure = error as? SharedChatRecipientError ?? .network
                self.state = failure == .passwordRequired ? .passwordRequired : .failed(failure)
            }
        }
        loadingTask = task
        return task
    }

    func cancel() {
        generation = UUID()
        loadingTask?.cancel()
        loadingTask = nil
        context = nil
        state = .idle
        isLoadingEarlier = false
    }

    @discardableResult func loadEarlier() -> Task<Void, Never>? {
        guard let current = context, current.hasMoreBefore, !isLoadingEarlier else { return nil }
        let scope = generation
        isLoadingEarlier = true
        let service = service
        let task = Task { @MainActor [weak self] in
            do {
                let updated = try await service.loadEarlier(current)
                guard let self, self.generation == scope, !Task.isCancelled else { return }
                self.context = updated
                self.isLoadingEarlier = false
            } catch {
                guard let self, self.generation == scope, !Task.isCancelled else { return }
                self.isLoadingEarlier = false
                self.state = .failed(error as? SharedChatRecipientError ?? .network)
            }
        }
        loadingTask = task
        return task
    }
}

@MainActor
struct SharedChatRecipientService {
    private let transport: any SharedChatRecipientTransport
    private let now: () -> Int
    init(transport: (any SharedChatRecipientTransport)? = nil,
         now: @escaping () -> Int = { Int(Date().timeIntervalSince1970) }) {
        self.transport = transport ?? SharedChatRecipientURLTransport()
        self.now = now
    }

    func load(_ originalURL: URL, password: String? = nil) async throws -> SharedChatRecipientContext {
        var link = try SharedChatRecipientLink.parse(originalURL)
        if case let .short(token, key) = link.target {
            let response = try object(await transport.get(link.apiBaseURL.appendingPathComponent("v1/share/short-url/\(token)")))
            try Task.checkCancellation()
            guard let encrypted = response["encrypted_url"] as? String else { throw SharedChatRecipientError.invalidResponse }
            let resolved: URL
            do { resolved = try await ShareLinkCrypto.decryptShortURL(encrypted, token: token, shortKey: key) }
            catch { throw SharedChatRecipientError.invalidLink }
            let target = try SharedChatRecipientLink.parse(resolved)
            guard target.apiBaseURL == link.apiBaseURL, case .chat = target.target else {
                throw SharedChatRecipientError.invalidLink
            }
            link = target
        }
        try Task.checkCancellation()
        guard case let .chat(id, blob, targetMessageID) = link.target else { throw SharedChatRecipientError.invalidLink }
        let serverTime: Int
        do {
            let response = try object(await transport.get(link.apiBaseURL.appendingPathComponent("v1/share/time")))
            serverTime = (response["timestamp"] as? Int) ?? (response["server_time"] as? Int) ?? now()
        } catch is CancellationError { throw CancellationError() }
        catch { serverTime = now() }
        try Task.checkCancellation()
        let key = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: serverTime, password: password)
        try Task.checkCancellation()
        let base = link.apiBaseURL.appendingPathComponent("v1/share/chat/\(id)")
        var manifest: [String: Any]
        var window: [String: Any]
        do {
            manifest = try object(await transport.get(base.appendingPathComponent("manifest")))
            window = try object(await transport.get(messagesURL(base: base, target: targetMessageID)))
        } catch is CancellationError { throw CancellationError() }
        catch {
            try Task.checkCancellation()
            let legacy = try object(await transport.get(base))
            manifest = legacy
            window = legacy
        }
        try Task.checkCancellation()
        guard (manifest["chat_id"] as? String ?? id) == id else { throw SharedChatRecipientError.unavailable }
        let rawMessages = try messageObjects(window["messages"])
        // Authenticate exactly the first content/title/summary candidate used by web.
        guard let validation = rawMessages.compactMap({ $0["encrypted_content"] as? String }).first(where: { !$0.isEmpty })
                ?? (manifest["encrypted_title"] as? String)
                ?? (manifest["encrypted_chat_summary"] as? String),
              (try? await CryptoManager.shared.decryptContent(base64String: validation, key: key)) != nil else {
            throw SharedChatRecipientError.unavailable
        }
        let chat = try await hydrateChat(manifest, id: id, key: key)
        let messages = try await hydrateMessages(rawMessages, id: id, key: key)
        let embeds = try await hydrateEmbeds(manifest, id: id, key: key)
        try Task.checkCancellation()
        let inline = PublicChatContent.attachEmbeds(to: messages)
        var context = SharedChatRecipientContext(originalURL: originalURL, resolvedURL: link.url, chatKey: key, chat: chat,
                     messages: inline.messages, embeds: PublicChatContent.mergingHydratedRecords(existing: embeds, inline: inline.records),
                     encryptedManifest: try JSONSerialization.data(withJSONObject: manifest), targetMessageID: targetMessageID,
                     sharePII: manifest["share_pii"] as? Bool ?? false, shareHighlights: manifest["share_highlights"] as? Bool ?? true,
                     hasMoreBefore: window["has_more"] as? Bool ?? false,
                     nextBeforeTimestamp: window["next_before_timestamp"] as? Int,
                     nextBeforeMessageID: window["next_before_message_id"] as? String)
        // Same bounded four-page interactive response context expansion as web.
        for _ in 0..<4 {
            guard hasMissingQuestion(context.messages), context.hasMoreBefore, context.nextBeforeTimestamp != nil else { break }
            do { context = try await loadEarlier(context) }
            catch is CancellationError { throw CancellationError() }
            catch { break }
        }
        return context
    }

    func loadEarlier(_ context: SharedChatRecipientContext) async throws -> SharedChatRecipientContext {
        guard context.hasMoreBefore, let timestamp = context.nextBeforeTimestamp else { return context }
        let link = try SharedChatRecipientLink.parse(context.resolvedURL)
        let base = link.apiBaseURL.appendingPathComponent("v1/share/chat/\(context.chat.id)")
        var url = URLComponents(url: messagesURL(base: base, target: nil), resolvingAgainstBaseURL: false)!
        url.queryItems?.append(.init(name: "before_timestamp", value: String(timestamp)))
        if let messageID = context.nextBeforeMessageID { url.queryItems?.append(.init(name: "before_message_id", value: messageID)) }
        let window = try object(await transport.get(url.url!))
        try Task.checkCancellation()
        guard (window["chat_id"] as? String ?? context.chat.id) == context.chat.id else { throw SharedChatRecipientError.unavailable }
        let messages = try await hydrateMessages(messageObjects(window["messages"]), id: context.chat.id, key: context.chatKey)
        var updated = context
        var seen = Set<String>()
        let merged = (messages + context.messages).filter { seen.insert($0.id).inserted }.sorted {
            $0.createdAt == $1.createdAt ? $0.id < $1.id : $0.createdAt < $1.createdAt
        }
        let inline = PublicChatContent.attachEmbeds(to: merged)
        updated.messages = inline.messages
        updated.embeds = PublicChatContent.mergingHydratedRecords(existing: context.embeds, inline: inline.records)
        updated.hasMoreBefore = !messages.isEmpty && (window["has_more"] as? Bool ?? false)
        updated.nextBeforeTimestamp = window["next_before_timestamp"] as? Int
        updated.nextBeforeMessageID = window["next_before_message_id"] as? String
        // Refuse a non-advancing cursor so malformed responses cannot loop forever.
        if updated.nextBeforeTimestamp == context.nextBeforeTimestamp && updated.nextBeforeMessageID == context.nextBeforeMessageID {
            updated.hasMoreBefore = false
        }
        try Task.checkCancellation()
        return updated
    }

    private func hasMissingQuestion(_ messages: [Message]) -> Bool {
        func ids(_ content: String, kind: String) -> Set<String> {
            guard let pattern = try? NSRegularExpression(pattern: "```\(kind)\\s*([\\s\\S]*?)\\s*```") else { return [] }
            let text = content as NSString
            return Set(pattern.matches(in: content, range: NSRange(location: 0, length: text.length)).compactMap {
                let body = text.substring(with: $0.range(at: 1))
                guard let row = try? object(Data(body.utf8)), let id = row["id"] as? String,
                      !id.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
                return id
            })
        }
        var seen = Set<String>(), missing = Set<String>()
        for message in messages.sorted(by: { $0.createdAt == $1.createdAt ? $0.id < $1.id : $0.createdAt < $1.createdAt }) {
            if message.role == .assistant {
                let questions = ids(message.content ?? "", kind: "interactive_question")
                seen.formUnion(questions)
                missing.subtract(questions)
            } else if message.role == .user {
                missing.formUnion(ids(message.content ?? "", kind: "interactive_response").subtracting(seen))
            }
        }
        return !missing.isEmpty
    }

    private func hydrateChat(_ payload: [String: Any], id: String, key: SymmetricKey) async throws -> Chat {
        func field(_ name: String) async -> String? {
            guard let encrypted = payload[name] as? String, !encrypted.isEmpty else { return nil }
            return try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
        }
        return await Chat(id: id, title: field("encrypted_title"), lastMessageAt: nil,
                         createdAt: ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: Double(now()))),
                         updatedAt: nil, isArchived: false, isPinned: false, appId: nil,
                         category: field("encrypted_category"), icon: field("encrypted_icon"), chatSummary: field("encrypted_chat_summary"),
                         encryptedTitle: payload["encrypted_title"] as? String,
                         encryptedFollowUpRequestSuggestions: payload["encrypted_follow_up_request_suggestions"] as? String,
                         encryptedChatKey: nil)
    }

    private func hydrateMessages(_ rows: [[String: Any]], id: String, key: SymmetricKey) async throws -> [Message] {
        var result: [Message] = []
        var seen = Set<String>()
        for row in rows {
            try Task.checkCancellation()
            // Web share windows use the client identity before wire/database IDs.
            // Normalize both aliases because Message's decoder prefers `id`.
            guard let messageID = ["client_message_id", "message_id", "id"]
                .compactMap({ row[$0] as? String }).first(where: { !$0.isEmpty }),
                  seen.insert(messageID).inserted else { continue }
            var safe = row
            safe["chat_id"] = id
            safe["chatId"] = id
            safe["id"] = messageID
            safe["message_id"] = messageID
            safe["role"] = ["assistant", "system"].contains(row["role"] as? String ?? "") ? row["role"] : "user"
            // Plaintext supplied alongside ciphertext is untrusted and cannot bypass authentication.
            for name in ["content", "sender_name", "senderName", "model_name", "modelName", "category",
                         "pii_mappings", "piiMappings", "renderDocument", "thinking_content", "thinkingContent"] { safe.removeValue(forKey: name) }
            var message = try JSONDecoder().decode(Message.self, from: JSONSerialization.data(withJSONObject: safe))
            func field(_ name: String) async -> String? {
                guard let encrypted = row[name] as? String, !encrypted.isEmpty else { return nil }
                return try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
            }
            message.content = await field("encrypted_content")
            message.senderName = await field("encrypted_sender_name")
            message.modelName = await field("encrypted_model_name")
            message.category = await field("encrypted_category")
            message.thinkingContent = await field("encrypted_thinking_content")
            if let pii = await field("encrypted_pii_mappings"), let bytes = pii.data(using: .utf8) {
                message.piiMappings = try? JSONDecoder().decode([PIIMapping].self, from: bytes)
            }
            result.append(message)
        }
        return result
    }

    private func hydrateEmbeds(_ manifest: [String: Any], id: String, key: SymmetricKey) async throws -> [String: EmbedRecord] {
        let rows = manifest["embeds"] as? [[String: Any]] ?? []
        let wrappers = manifest["embed_keys"] as? [[String: Any]] ?? []
        func hash(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
        var keys: [String: SymmetricKey] = [:]
        var records: [String: EmbedRecord] = [:]
        for row in rows {
            try Task.checkCancellation()
            guard let embedID = row["embed_id"] as? String, records[embedID] == nil else { continue }
            var safe = row
            safe.removeValue(forKey: "content")
            safe.removeValue(forKey: "data")
            // Share manifests send legacy pipe-delimited strings as well as
            // arrays. Normalize to the array accepted by EmbedRecord's decoder.
            if let rawChildren = row["embed_ids"] ?? row["embedIds"] {
                let children = (rawChildren as? String).map { $0.components(separatedBy: "|") }
                    ?? (rawChildren as? [Any])?.compactMap { $0 as? String } ?? []
                safe["embed_ids"] = children.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
                safe.removeValue(forKey: "embedIds")
            }
            let record = try JSONDecoder().decode(EmbedRecord.self, from: JSONSerialization.data(withJSONObject: safe))
            records[embedID] = record
            for wrapper in wrappers where wrapper["key_type"] as? String == "chat" && wrapper["hashed_chat_id"] as? String == hash(id) && wrapper["hashed_embed_id"] as? String == hash(embedID) {
                if let encrypted = wrapper["encrypted_embed_key"] as? String,
                   let raw = try? await CryptoManager.shared.decryptBlob(base64String: encrypted, key: key), raw.count == 32 {
                    keys[embedID] = SymmetricKey(data: raw)
                    break
                }
            }
        }
        // Direct wrappers win. Legacy children reuse their parent's key, including
        // payloads declaring embed_ids without parent_embed_id on child rows.
        var parents: [String: String] = [:]
        for record in records.values {
            if let parent = record.parentEmbedId { parents[record.id] = parent }
            for child in record.childEmbedIds where parents[child] == nil { parents[child] = record.id }
        }
        for _ in 0..<records.count {
            var changed = false
            for (child, parent) in parents where keys[child] == nil {
                if let inherited = keys[parent] { keys[child] = inherited; changed = true }
            }
            if !changed { break }
        }
        for (embedID, record) in records {
            try Task.checkCancellation()
            guard let embedKey = keys[embedID] else { continue }
            let content: String?
            if let encrypted = record.encryptedContent { content = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: embedKey) }
            else { content = nil }
            let type: String?
            if let encrypted = record.encryptedType { type = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: embedKey) }
            else { type = nil }
            records[embedID] = record.decryptedCopy(content: content, type: type)
        }
        return records
    }

    private func object(_ data: Data) throws -> [String: Any] {
        guard data.count <= 16 * 1024 * 1024, let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw SharedChatRecipientError.invalidResponse
        }
        return object
    }

    private func messageObjects(_ value: Any?) throws -> [[String: Any]] {
        guard let values = value as? [Any] else { return [] }
        return try values.map { value in
            if let string = value as? String { return try object(Data(string.utf8)) }
            guard let row = value as? [String: Any] else { throw SharedChatRecipientError.invalidResponse }
            return row
        }
    }

    private func messagesURL(base: URL, target: String?) -> URL {
        var url = URLComponents(url: base.appendingPathComponent("messages"), resolvingAgainstBaseURL: false)!
        url.queryItems = [URLQueryItem(name: "limit", value: "30")]
        if let target { url.queryItems?.append(.init(name: "target_message_id", value: target)) }
        return url.url!
    }
}
