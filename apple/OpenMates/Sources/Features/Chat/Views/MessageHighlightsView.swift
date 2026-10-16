// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.inline-entity-interaction
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/HighlightCommentPopover.svelte
// Services: frontend/packages/ui/src/services/sendersMessageHighlights.ts, handlersMessageHighlights.ts
// CSS: HighlightCommentPopover.svelte, MessageSelectionToolbar.svelte
// ────────────────────────────────────────────────────────────────────
import SwiftUI
import CryptoKit

struct MessageHighlightAnchor: Codable, Equatable {
    let exact: String
    let prefix: String
    let suffix: String
    func resolve(in text: String) -> NSRange? {
        guard !exact.isEmpty else { return nil }
        let source = text as NSString
        var remaining = NSRange(location: 0, length: source.length), best: NSRange?, score = -1
        while remaining.length > 0 {
            let found = source.range(of: exact, range: remaining)
            guard found.location != NSNotFound else { break }
            let before = source.substring(to: found.location), after = source.substring(from: NSMaxRange(found))
            let weight = (!prefix.isEmpty && before.hasSuffix(prefix) ? 1 : 0) + (!suffix.isEmpty && after.hasPrefix(suffix) ? 1 : 0)
            if weight > score { best = found; score = weight }
            let end = NSMaxRange(found); remaining = NSRange(location: end, length: source.length - end)
        }
        return best
    }
}
struct MessageHighlight: Identifiable, Equatable {
    let id: String
    let chatID: String
    let messageID: String
    let authorID: String
    let anchor: MessageHighlightAnchor
    var comment: String?
    let createdAt: Int
}
struct MessageHighlightRuntimeScope: Equatable {
    let accountID: String
    let scope: UUID
    let server: ServerProfile
    let team: TeamWorkspaceSnapshot
    @MainActor static func capture(scope: UUID, server: ServerProfile, team: TeamWorkspaceSnapshot) async -> Self? {
        guard let accountID = await AuthManager.currentUserId(), scope == OfflineStore.shared.scopeGeneration,
              server == ServerProfile.current(), TeamWorkspaceContext.shared.isCurrent(team) else { return nil }
        return .init(accountID: accountID, scope: scope, server: server, team: team)
    }
    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.accountID == rhs.accountID && lhs.scope == rhs.scope && lhs.server == rhs.server
            && lhs.team.teamID == rhs.team.teamID && lhs.team.epoch == rhs.team.epoch
    }
}
enum MessageHighlightError: Error { case staleContext, missingChatKey }
struct MessageHighlightCipherRow: Codable {
    let id: String
    let chatID: String
    let messageID: String
    let authorID: String
    var encryptedPayload: String
    let createdAt: Int
    var updatedAt: Int?
    var keyVersion: Int?
    func payload(for type: String) -> [String: Any] {
        var result: [String: Any] = ["id": id, "chat_id": chatID, "message_id": messageID]
        if type == "add_message_highlight" {
            result["author_user_id"] = authorID; result["created_at"] = createdAt
            result["key_version"] = keyVersion.map { $0 as Any } ?? NSNull()
        }
        if type != "remove_message_highlight" { result["encrypted_payload"] = encryptedPayload }
        if type == "update_message_highlight" { result["updated_at"] = updatedAt ?? createdAt }
        return result
    }
}
private struct MessageHighlightPlainPayload: Codable {
    var kind = "text"
    let anchor: MessageHighlightAnchor
    var comment: String?
    let created_at: Int
    var updated_at: Int?
}

/// Decrypted selections stay in memory. Durable cache and retry rows contain
/// only the same ciphertext and opaque routing metadata as the web protocol.
@MainActor
final class HighlightsManager: ObservableObject {
    static let shared = HighlightsManager()
    @Published private(set) var highlights: [String: MessageHighlight] = [:]
    @Published private(set) var errorMessage: String?
    private struct Pending: Codable {
        let id: UUID
        let type: String
        let row: MessageHighlightCipherRow
        init(type: String, row: MessageHighlightCipherRow) { id = UUID(); self.type = type; self.row = row }
    }
    private struct Cache: Codable { var rows: [MessageHighlightCipherRow]; var pending: [Pending] }
    private var rows: [String: MessageHighlightCipherRow] = [:]
    private var pending: [Pending] = []
    private var runtime: MessageHighlightRuntimeScope?
    private var flushID: UUID?
    private let storage: UserDefaults?
    private let key: (String) -> SymmetricKey?
    private let transport: ((String, [String: Any]) async throws -> Void)?
    private let validate: (MessageHighlightRuntimeScope) async -> Bool
    init(storage: UserDefaults? = .standard,
         key: @escaping (String) -> SymmetricKey? = { ChatKeyManager.shared.key(for: $0) },
         transport: ((String, [String: Any]) async throws -> Void)? = nil, validate: @escaping (MessageHighlightRuntimeScope) async -> Bool = { captured in
             let accountID = await AuthManager.currentUserId()
             return captured.scope == OfflineStore.shared.scopeGeneration && captured.server == ServerProfile.current()
             && TeamWorkspaceContext.shared.isCurrent(captured.team) && captured.accountID == accountID
         }) {
        self.storage = storage; self.key = key; self.transport = transport; self.validate = validate
    }
    private var cacheKey: String? {
        guard let runtime else { return nil }
        let identity = runtime.accountID + "|" + runtime.server.apiBaseURL.absoluteString + "|" + (runtime.team.teamID ?? "")
        return "openmates.encryptedMessageHighlights." + SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    func reset() {
        runtime = nil; flushID = nil; highlights = [:]; rows = [:]; pending = []; errorMessage = nil
    }
    func configure(_ scope: MessageHighlightRuntimeScope?) async {
        if let scope, !(await validate(scope)) { return }
        guard runtime != scope else { await restore(); return }
        runtime = scope; flushID = nil; highlights = [:]; rows = [:]; pending = []; errorMessage = nil
        if let cacheKey, let bytes = storage?.data(forKey: cacheKey), let saved = try? JSONDecoder().decode(Cache.self, from: bytes) {
            rows = Dictionary(saved.rows.map { ($0.id, $0) }, uniquingKeysWith: { _, newer in newer }); pending = saved.pending
        }
        await restore()
    }
    func receive(type: String, fields: [String: Any], scope: UUID, server: ServerProfile, team: TeamWorkspaceSnapshot) async {
        guard let captured = await MessageHighlightRuntimeScope.capture(scope: scope, server: server, team: team) else { return }
        await configure(captured)
        await consume(type: type, fields: fields, scope: scope)
    }
    func anchors(chatID: String, messageID: String) -> [MessageHighlightAnchor] {
        highlights.values.filter { $0.chatID == chatID && $0.messageID == messageID }.map(\.anchor)
    }
    func add(chatID: String, messageID: String, anchor: MessageHighlightAnchor) async throws -> String {
        guard let captured = runtime, await validate(captured), runtime == captured,
              !anchor.exact.isEmpty, let chatKey = key(chatID) else { throw MessageHighlightError.staleContext }
        let created = Int(Date().timeIntervalSince1970), id = UUID().uuidString
        let payload = MessageHighlightPlainPayload(anchor: anchor, created_at: created)
        let bytes = try JSONEncoder().encode(payload)
        let encrypted = try await CryptoManager.shared.encryptContent(String(decoding: bytes, as: UTF8.self), key: chatKey)
        guard runtime == captured, await validate(captured), key(chatID) != nil else { throw MessageHighlightError.staleContext }
        let row = MessageHighlightCipherRow(id: id, chatID: chatID, messageID: messageID, authorID: captured.accountID, encryptedPayload: encrypted, createdAt: created)
        highlights[id] = .init(id: id, chatID: chatID, messageID: messageID, authorID: captured.accountID, anchor: anchor, createdAt: created)
        if IncognitoChatSession.isIncognitoChatId(chatID) { return id }
        rows[id] = row
        pending.append(.init(type: "add_message_highlight", row: row)); persist(); await flush()
        return id
    }
    func updateComment(id: String, comment: String) async throws {
        guard let captured = runtime, await validate(captured), runtime == captured,
              var highlight = highlights[id], highlight.authorID == captured.accountID else { throw MessageHighlightError.staleContext }
        let text = String(comment.trimmingCharacters(in: .whitespacesAndNewlines).prefix(500))
        highlight.comment = text.isEmpty ? nil : text
        if IncognitoChatSession.isIncognitoChatId(highlight.chatID) { highlights[id] = highlight; return }
        guard var row = rows[id], let chatKey = key(highlight.chatID) else { throw MessageHighlightError.missingChatKey }
        let now = Int(Date().timeIntervalSince1970)
        let payload = MessageHighlightPlainPayload(anchor: highlight.anchor, comment: highlight.comment, created_at: highlight.createdAt, updated_at: now)
        row.encryptedPayload = try await CryptoManager.shared.encryptContent(String(decoding: try JSONEncoder().encode(payload), as: UTF8.self), key: chatKey)
        row.updatedAt = now
        guard runtime == captured, await validate(captured) else { throw MessageHighlightError.staleContext }
        rows[id] = row; highlights[id] = highlight
        pending.append(.init(type: "update_message_highlight", row: row)); persist(); await flush()
    }
    func remove(id: String) async throws {
        guard let captured = runtime, await validate(captured), runtime == captured,
              let highlight = highlights[id], highlight.authorID == captured.accountID else { throw MessageHighlightError.staleContext }
        if IncognitoChatSession.isIncognitoChatId(highlight.chatID) { highlights.removeValue(forKey: id); return }
        guard let row = rows[id] else { throw MessageHighlightError.staleContext }
        rows.removeValue(forKey: id); highlights.removeValue(forKey: id)
        pending.append(.init(type: "remove_message_highlight", row: row)); persist(); await flush()
    }
    func flush() async {
        guard flushID == nil, let captured = runtime, await validate(captured), runtime == captured else { return }
        let request = UUID(); flushID = request
        defer { if flushID == request { flushID = nil } }
        while let first = pending.first {
            guard runtime == captured, await validate(captured), runtime == captured else { return }
            do {
                if let transport { try await transport(first.type, first.row.payload(for: first.type)) }
                else {
                    let socket = AppSessionCoordinator.shared.webSocketManager, generation = socket.transportGeneration
                    let responseType = ["add_message_highlight": "message_highlight_added", "update_message_highlight": "message_highlight_updated", "remove_message_highlight": "message_highlight_removed"][first.type]
                    guard let responseType else { return }
                    _ = try await socket.sendAndWait(WSOutboundMessage(type: first.type, payload: first.row.payload(for: first.type)),
                        responseTypes: [responseType], matching: { $0["id"] as? String == first.row.id }, beforeSend: { [weak self] in
                            guard let self, self.runtime == captured, await self.validate(captured), self.runtime == captured,
                                  socket.transportGeneration == generation else { throw MessageHighlightError.staleContext }
                        })
                }
            }
            catch { return } // encrypted outbox remains for the next connection.
            guard runtime == captured else { return }
            pending.removeAll { $0.id == first.id }; persist()
        }
    }
    func consume(type: String, fields: [String: Any], scope: UUID) async {
        guard let captured = runtime, captured.scope == scope, await validate(captured), runtime == captured,
              let chatID = fields["chat_id"] as? String else { return }
        if type == "chat_deleted" || type == "message_deleted" {
            let messageID = fields["message_id"] as? String
            guard type == "chat_deleted" || messageID != nil else { return }
            let ids = Set(rows.values.filter { $0.chatID == chatID && (type == "chat_deleted" || $0.messageID == messageID) }.map(\.id))
            rows = rows.filter { !ids.contains($0.key) }
            highlights = highlights.filter { $0.value.chatID != chatID || (type != "chat_deleted" && $0.value.messageID != messageID) }
            pending.removeAll { $0.row.chatID == chatID && (type == "chat_deleted" || $0.row.messageID == messageID) }
            persist(); return
        }
        guard let id = fields["id"] as? String, let messageID = fields["message_id"] as? String,
              !IncognitoChatSession.isIncognitoChatId(chatID) else { return }
        if type == "message_highlight_removed" { rows.removeValue(forKey: id); highlights.removeValue(forKey: id); pending.removeAll { $0.row.id == id }; persist(); return }
        guard ["message_highlight_added", "message_highlight_updated"].contains(type), let encrypted = fields["encrypted_payload"] as? String else { return }
        guard !pending.contains(where: { $0.row.id == id && $0.type == "remove_message_highlight" }) else { return }
        let previous = rows[id]
        guard previous == nil || (previous?.chatID == chatID && previous?.messageID == messageID) else { return }
        // An acknowledgement for an older add must not erase a comment queued
        // while that add was in flight (timestamps have one-second precision).
        if let newest = pending.last(where: { $0.row.id == id }), newest.row.encryptedPayload != encrypted { return }
        let incomingVersion = fields["updated_at"] as? Int ?? fields["created_at"] as? Int ?? 0
        guard (previous?.updatedAt ?? previous?.createdAt ?? 0) <= incomingVersion else { return }
        let row = MessageHighlightCipherRow(id: id, chatID: chatID, messageID: messageID,
            authorID: fields["author_user_id"] as? String ?? previous?.authorID ?? "",
            encryptedPayload: encrypted, createdAt: fields["created_at"] as? Int ?? previous?.createdAt ?? incomingVersion,
            updatedAt: fields["updated_at"] as? Int, keyVersion: fields["key_version"] as? Int ?? previous?.keyVersion)
        rows[id] = row; persist(); await decrypt(row, captured: captured)
    }
    func restore() async {
        guard let captured = runtime, await validate(captured), runtime == captured else { return }
        for row in rows.values { await decrypt(row, captured: captured) }
    }
    private func decrypt(_ row: MessageHighlightCipherRow, captured: MessageHighlightRuntimeScope) async {
        guard let chatKey = key(row.chatID), let plaintext = try? await CryptoManager.shared.decryptContent(base64String: row.encryptedPayload, key: chatKey),
              let payload = try? JSONDecoder().decode(MessageHighlightPlainPayload.self, from: Data(plaintext.utf8)), payload.kind == "text", !payload.anchor.exact.isEmpty,
              runtime == captured, await validate(captured), rows[row.id]?.encryptedPayload == row.encryptedPayload else { return }
        highlights[row.id] = .init(id: row.id, chatID: row.chatID, messageID: row.messageID, authorID: row.authorID,
                                  anchor: payload.anchor, comment: payload.comment, createdAt: payload.created_at)
    }
    private func persist() {
        guard let cacheKey, let bytes = try? JSONEncoder().encode(Cache(rows: Array(rows.values), pending: pending)) else { return }
        storage?.set(bytes, forKey: cacheKey)
    }
}

struct MessageHighlightCommentEditor: View {
    @Binding var comment: String
    let onSave: () -> Void
    let onCancel: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            TextField(AppStrings.localized("chats.highlight.comment_placeholder.text"), text: $comment, axis: .vertical)
                .font(.omSmall).textFieldStyle(OMTextFieldStyle()).accessibilityIdentifier("message-highlight-comment-input")
            HStack {
                Button(AppStrings.cancel, action: onCancel).buttonStyle(OMSecondaryButtonStyle())
                Button(AppStrings.save, action: onSave).buttonStyle(OMPrimaryButtonStyle()).accessibilityIdentifier("message-highlight-comment-save")
            }
        }.padding(.spacing6).background(Color.grey0).clipShape(RoundedRectangle(cornerRadius: .radius8))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("message-highlight-comment-editor")
    }
}
