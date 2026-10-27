// Shared request, bounded selection and reply policy; no account or storage authority.
// Web: frontend/packages/ui/src/services/voiceCallTools.ts;
// frontend/packages/ui/src/services/chatSyncServiceHandlersAppSettings.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.privacy
import Foundation

enum NativeVoiceCallMemoryPolicy {
    struct Request: Equatable, Sendable {
        let callID: String
        let requestID: String
        let functionID: String
        let keys: [String]

        init(scope: NativeVoiceCallScope, callID: String, frame: NativeVoiceCallFrame) throws {
            guard frame["type"]?.string == "voice_memory", frame["call_id"]?.string == callID,
                  let functionID = frame["function_call_id"]?.string, !functionID.isEmpty,
                  let assistantID = frame["assistant_message_id"]?.string, !assistantID.isEmpty,
                  let userID = frame["user_message_id"]?.string, !userID.isEmpty,
                  let payload = frame["payload"]?.object,
                  payload["chat_id"] == nil || payload["chat_id"]?.string == scope.chatID,
                  let requestID = payload["request_id"]?.string, !requestID.isEmpty,
                  case .array(let requested)? = payload["requested_keys"],
                  !requested.isEmpty, requested.count <= 64 else { throw NativeVoiceCallError.invalidResponse }
            self.callID = callID; self.requestID = requestID; self.functionID = functionID
            keys = try requested.map { raw in
                guard let key = raw.string, !key.isEmpty, key.utf8.count <= 256 else { throw NativeVoiceCallError.invalidResponse }
                // The pinned web replaces only the first colon before matching.
                guard let separator = key.firstIndex(of: ":") else { return key }
                return String(key[..<separator]) + "-" + String(key[key.index(after: separator)...])
            }
        }
        var requestsPersonalDocuments: Bool { keys.contains("openmates-memories") }
    }

    struct Category: Identifiable, Equatable, Sendable {
        let appID: String
        let categoryID: String
        let title: String
        var key: String { appID + "-" + categoryID }
        var id: String { appID + ":" + categoryID }
    }
    struct Choice: Identifiable, Equatable, Sendable {
        let id: String
        let category: Category
        let title: String
        let value: String
        /// Original decrypted object, including original item key and settings group.
        let content: NativeVoiceCallJSON
    }
    struct Snapshot: Equatable, Sendable {
        /// Must come from fresh owner-validated privacy preparation, never a broad catalog.
        let availableKeys: Set<String>
        let categories: [Category]
        let choices: [Choice]
        var privacyFingerprint: String? = nil

        func requested(_ request: Request) throws -> Self {
            guard !request.requestsPersonalDocuments,
                  request.keys.allSatisfy(availableKeys.contains) else { throw NativeVoiceCallError.unsupportedTransport }
            let requested = Set(request.keys)
            let categories = categories.filter { requested.contains($0.key) }
            guard Set(categories.map(\.key)) == requested,
                  Set(categories.map(\.id)).count == categories.count else { throw NativeVoiceCallError.invalidResponse }
            let choices = choices.filter { requested.contains($0.category.key) }
            guard Set(choices.map(\.id)).count == choices.count,
                  choices.allSatisfy({ choice in categories.contains(choice.category) && !choice.id.isEmpty && choice.content.object != nil })
            else { throw NativeVoiceCallError.invalidResponse }
            try validateBounds(choices.map(\.value))
            // Bound the complete object too; a small label cannot disguise a large body.
            let bytes = try choices.reduce(0) { try $0 + JSONEncoder().encode($1.content).count }
            guard bytes <= 256 * 1_024 else { throw NativeVoiceCallError.contextTooLarge }
            return Self(availableKeys: requested, categories: categories, choices: choices, privacyFingerprint: privacyFingerprint)
        }
    }

    static func validateBounds(_ values: [String]) throws {
        guard values.count <= 256, values.reduce(0, { $0 + $1.utf8.count }) <= 256 * 1_024
        else { throw NativeVoiceCallError.contextTooLarge }
    }

    static func response(_ request: Request, entries: [NativeVoiceCallJSON]) throws -> NativeVoiceCallFrame {
        let reply: NativeVoiceCallFrame = ["type": .string("voice_memory_response"),
            "call_id": .string(request.callID), "function_call_id": .string(request.functionID),
            "request_id": .string(request.requestID), "approved": .bool(!entries.isEmpty),
            "settings_memories": .array(entries)]
        _ = try NativeVoiceCallWire.encode(reply)
        return reply
    }

    static func response(_ request: Request, snapshot: Snapshot, selectedIDs: Set<String>, includeSelected: Bool) throws -> NativeVoiceCallFrame {
        let bounded = try snapshot.requested(request)
        guard selectedIDs.isSubset(of: Set(bounded.choices.map(\.id))), !includeSelected || !selectedIDs.isEmpty
        else { throw NativeVoiceCallError.invalidResponse }
        let entries: [NativeVoiceCallJSON] = includeSelected ? bounded.choices.filter { selectedIDs.contains($0.id) }.map {
            .object(["app_id": .string($0.category.appID), "item_key": .string($0.category.categoryID), "content": $0.content])
        } : []
        return try response(request, entries: entries)
    }
}
