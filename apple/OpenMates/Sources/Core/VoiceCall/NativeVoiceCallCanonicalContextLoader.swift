// Web source: frontend/packages/ui/src/services/voiceCallMessages.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.compressed-context, video-call.chat.fixed-binding,
// video-call.chat.memories-and-focus, video-call.chat.assistant-identity
import Foundation

/// Reads authenticated canonical pages, retaining the latest decryptable valid
/// checkpoint and every uncovered turn. An overview or a visible local page is
/// never treated as complete. All plaintext exists only in this transient value.
struct NativeVoiceCallCanonicalContextLoader: Sendable {
    typealias Request = @Sendable (NativeVoiceCallScope, String) async throws -> Data
    typealias ProjectContext = @Sendable (NativeVoiceCallScope, NativeVoiceCallJSON?) async throws -> NativeVoiceCallFrame
    let request: Request
    let decrypt: @Sendable (String, NativeVoiceCallScope) async throws -> String
    let metadata: @Sendable (NativeVoiceCallScope) async throws -> NativeVoiceCallFrame
    let isCurrent: @Sendable (NativeVoiceCallScope) async -> Bool

    /// Watch and other roots without an authorized reader retain the original
    /// fail-closed behavior for a selected Project specialist.
    var projectContext: ProjectContext? = nil
    /// Fresh Personal category availability is independent from Project authority.
    /// Supplying this reader never authorizes a selected Project specialist.
    var memoryMetadata: (@Sendable (NativeVoiceCallScope) async throws -> [String])? = nil

    private func check(_ scope: NativeVoiceCallScope) async throws {
        try Task.checkCancellation()
        guard await isCurrent(scope) else { throw NativeVoiceCallError.scopeChanged }
    }
    private func fetch(_ path: String, scope: NativeVoiceCallScope) async throws -> NativeVoiceCallFrame {
        try await check(scope)
        let data = try await request(scope, path)
        try await check(scope)
        guard data.count <= 2 * 1_024 * 1_024 + 8_192 else { throw NativeVoiceCallError.contextTooLarge }
        do { return try JSONDecoder().decode(NativeVoiceCallFrame.self, from: data) }
        catch { throw NativeVoiceCallError.contextUnavailable }
    }
    private func seconds(_ value: NativeVoiceCallJSON?) -> Int? {
        let number: Double?
        if let raw = value?.number { number = raw }
        else if let text = value?.string {
            number = Double(text) ?? (try? Date.ISO8601FormatStyle().parse(text))?.timeIntervalSince1970
                ?? (try? Date.ISO8601FormatStyle(includingFractionalSeconds: true).parse(text))?.timeIntervalSince1970
        } else { number = nil }
        guard let number, number.isFinite, number > 0, number <= 9_007_199_254_740_991 else { return nil }
        return Int(number)
    }
    func load(scope: NativeVoiceCallScope) async throws -> NativeVoiceCallContext {
        guard UUID(uuidString: scope.chatID) != nil else { throw NativeVoiceCallError.contextUnavailable }
        let path = "/v1/chats/\(scope.chatID)"
        let checkpointList = try await fetch(path + "/compression-checkpoints?limit=20", scope: scope)
        guard case .array(let listed)? = checkpointList["checkpoints"] else { throw NativeVoiceCallError.contextUnavailable }
        var checkpoints = listed.compactMap(\.object)
        guard checkpoints.count == listed.count, checkpoints.count <= 20 else { throw NativeVoiceCallError.contextUnavailable }
        if let oversized = checkpointList["oversized_checkpoint_id"]?.string {
            guard !oversized.isEmpty, !oversized.contains("/"), !oversized.contains("?"), !oversized.contains("#")
            else { throw NativeVoiceCallError.contextUnavailable }
            let exact = try await fetch(path + "/compression-checkpoints/" + oversized, scope: scope)
            guard let selected = exact["checkpoint"]?.object, selected["id"]?.string == oversized
            else { throw NativeVoiceCallError.contextUnavailable }
            checkpoints.append(selected)
        }
        guard checkpoints.allSatisfy({ $0["chat_id"]?.string == scope.chatID }) else { throw NativeVoiceCallError.contextUnavailable }
        checkpoints.sort { (seconds($0["created_at"]) ?? 0) > (seconds($1["created_at"]) ?? 0) }
        var summary: String?
        var boundary: NativeVoiceCallHistory.Boundary?
        for checkpoint in checkpoints {
            guard let ciphertext = checkpoint["encrypted_summary"]?.string,
                  let timestamp = seconds(checkpoint["compressed_up_to_timestamp"]),
                  let id = checkpoint["compressed_up_to_message_id"]?.string, !id.isEmpty,
                  (checkpoint["compressed_message_count"]?.number ?? 0) > 0 else { continue }
            do {
                let text = try await decrypt(ciphertext, scope)
                try await check(scope)
                guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { continue }
                summary = text
                let covered: Set<String>
                if case .array(let ids)? = checkpoint["covered_message_ids"] {
                    guard ids.allSatisfy({ $0.string != nil }) else { throw NativeVoiceCallError.contextUnavailable }
                    covered = Set(ids.compactMap(\.string))
                } else { covered = [] }
                boundary = .init(timestamp: timestamp, messageID: id, coveredMessageIDs: covered)
                break
            } catch let error as NativeVoiceCallError where error == .scopeChanged { throw error }
            catch { continue } // latest valid older encrypted checkpoint is allowed
        }
        guard checkpoints.isEmpty || summary != nil else { throw NativeVoiceCallError.contextUnavailable }
        guard (summary?.utf16.count ?? 0) <= 48_000 else { throw NativeVoiceCallError.contextTooLarge }
        var before: (timestamp: Int, id: String)?
        var seen = Set<String>(), scanned = 0
        var messages: [(message: NativeVoiceCallContext.Message, userID: String?)] = []
        while true {
            var query = URLComponents()
            query.path = path + "/messages/window"
            var items = [URLQueryItem(name: "direction", value: before == nil ? "latest" : "before"),
                         URLQueryItem(name: "limit", value: "20"),
                         URLQueryItem(name: "respect_compression_boundary", value: "false")]
            if let before { items += [.init(name: "before_timestamp", value: String(before.timestamp)),
                                       .init(name: "before_message_id", value: before.id)] }
            query.queryItems = items
            guard let pagePath = query.string else { throw NativeVoiceCallError.contextUnavailable }
            let page = try await fetch(pagePath, scope: scope)
            guard case .array(let rawRows)? = page["messages"], rawRows.count <= 20,
                  let hasMore = page["has_more_before"]?.bool else { throw NativeVoiceCallError.contextUnavailable }
            var rows = rawRows.compactMap(\.object)
            guard rows.count == rawRows.count else { throw NativeVoiceCallError.contextUnavailable }
            if let oversized = page["oversized_message_cursor"]?.object,
               let id = oversized["message_id"]?.string {
                guard !id.contains("/"), !id.contains("?"), !id.contains("#") else { throw NativeVoiceCallError.contextUnavailable }
                let exact = try await fetch(path + "/messages/" + id, scope: scope)
                guard let row = exact["message"]?.object, (row["message_id"]?.string ?? row["id"]?.string) == id
                else { throw NativeVoiceCallError.contextUnavailable }
                rows.append(row)
            }
            scanned += rows.count
            for row in rows {
                guard row["chat_id"]?.string == scope.chatID,
                      let id = row["client_message_id"]?.string ?? row["message_id"]?.string ?? row["id"]?.string,
                      let created = seconds(row["created_at"]), seen.insert(id).inserted
                else { throw NativeVoiceCallError.contextUnavailable }
                guard let rawRole = row["role"]?.string, let role = NativeVoiceCallTranscript.Role(rawValue: rawRole)
                else { continue } // encrypted system lifecycle rows are not model turns
                guard NativeVoiceCallHistory.isUncovered(id: id, createdAt: created,
                    callRevision: (row["queue_revision"] ?? row["revision"])?.number.flatMap {
                        $0 >= 1 && $0 <= 9_007_199_254_740_991 ? Int($0) : nil
                    }, boundary: boundary) else { continue }
                guard let ciphertext = row["encrypted_content"]?.string, !ciphertext.isEmpty
                else { throw NativeVoiceCallError.contextUnavailable }
                let text = try await decrypt(ciphertext, scope).trimmingCharacters(in: .whitespacesAndNewlines)
                try await check(scope)
                guard !text.isEmpty else { continue }
                messages.append((.init(id: id, role: role, text: text, createdAt: created), row["user_message_id"]?.string))
            }
            guard messages.count <= 30, scanned <= 120,
                  messages.reduce(summary?.utf16.count ?? 0, { $0 + $1.message.text.utf16.count }) <= 64_000
            else { throw NativeVoiceCallError.contextTooLarge }
            if !hasMore { break }
            guard !rows.isEmpty, let cursor = page["start_cursor"]?.object,
                  let timestamp = seconds(cursor["created_at"]), let id = cursor["message_id"]?.string,
                  before.map({ timestamp < $0.timestamp || (timestamp == $0.timestamp && id < $0.id) }) ?? true
            else { throw NativeVoiceCallError.contextUnavailable }
            // A corrected final call row retains its original timestamp and may
            // live on any older canonical page. Without an authoritative covered
            // revision manifest, reaching the summary boundary proves nothing
            // about those later corrections. Traverse to the actual end or fail
            // closed at the shared 120-record bound; never claim completeness
            // from a checkpoint cursor alone.
            guard scanned < 120 else { throw NativeVoiceCallError.contextTooLarge }
            before = (timestamp, id)
        }
        messages.sort { $0.message.createdAt == $1.message.createdAt ? $0.message.id < $1.message.id : $0.message.createdAt < $1.message.createdAt }
        for index in messages.indices {
            guard messages[index].message.role == .assistant, let userID = messages[index].userID,
                  let userIndex = messages.firstIndex(where: { $0.message.id == userID }), userIndex > index else { continue }
            let assistant = messages.remove(at: index)
            messages.insert(assistant, at: userIndex)
        }
        let details = try await metadata(scope)
        try await check(scope)
        guard (details["id"]?.string ?? details["chat_id"]?.string) == scope.chatID,
              details["team_id"] == nil || details["team_id"] == .null,
              details["chat_visibility"]?.string != "direct" else { throw NativeVoiceCallError.contextUnavailable }
        var focus: NativeVoiceCallJSON?
        if let encrypted = details["encrypted_active_focus_id"]?.string {
            let id = try await decrypt(encrypted, scope)
            guard let separator = id.firstIndex(of: "-"), !id.isEmpty else { throw NativeVoiceCallError.contextUnavailable }
            var fields: NativeVoiceCallFrame = ["app_id": .string(String(id[..<separator])), "focus_id": .string(id)]
            if let phase = details["encrypted_focus_phase_state"]?.string {
                let json = try await decrypt(phase, scope)
                guard let data = json.data(using: .utf8), let state = try? JSONDecoder().decode(NativeVoiceCallFrame.self, from: data)
                else { throw NativeVoiceCallError.contextUnavailable }
                fields["state"] = state[id]
            }
            try await check(scope)
            guard !id.contains("project-focus:") || projectContext != nil else { throw NativeVoiceCallError.contextUnavailable }
            focus = .object(fields)
        }
        if let encrypted = details["encrypted_category"]?.string {
            guard try await decrypt(encrypted, scope) == scope.mateCategory else { throw NativeVoiceCallError.contextUnavailable }
        }
        try await check(scope)
        var projectFields = try await projectContext?(scope, focus) ?? [:]
        if let memoryMetadata {
            let keys = try await memoryMetadata(scope)
            guard keys.count <= 10_000, Set(keys).count == keys.count,
                  keys.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 256 }) else { throw NativeVoiceCallError.contextUnavailable }
            projectFields["app_settings_memories_metadata"] = .array(keys.map { .string($0) })
        }
        try await check(scope)
        return try NativeVoiceCallContext(messages: messages.map(\.message), summary: summary,
            activeFocus: focus, projectFields: projectFields, mateCategory: scope.mateCategory, canonicalRangeComplete: true)
    }
}
