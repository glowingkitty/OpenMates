// Current Personal privacy is decrypted locally before every saved-turn admission.
// Web: frontend/packages/ui/src/services/preparedPrivacyForSend.ts
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.privacy-context, message-input.send.ownership
import Foundation
import CryptoKit

struct NativeCompiledPersonalPrivacy: Equatable, Sendable {
    let settings: PIIPrivacySettings
    let metadataKeys: [String]

    /// The injected decryptor uses the current owner's master key. Invalid or
    /// missing ciphertext fails closed; unrelated Memory bodies are not selected.
    @MainActor static func compile(_ snapshot: [String: Any], decrypt: (String) async throws -> String) async throws -> Self {
        guard let memories = snapshot["memories"] as? [[String: Any]], memories.count <= 10_000,
              snapshot["encrypted_settings"] is NSNull || snapshot["encrypted_settings"] is String else {
            throw NativePersonalPrivacyError.invalidSnapshot
        }
        func object(_ ciphertext: String) async throws -> [String: Any] {
            let text = try await decrypt(ciphertext)
            guard text.utf8.count <= 2 * 1024 * 1024, let data = text.data(using: .utf8),
                  let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw NativePersonalPrivacyError.invalidSnapshot }
            return value
        }
        let accountSettings: [String: Any]
        if let encrypted = snapshot["encrypted_settings"] as? String { accountSettings = try await object(encrypted) }
        else { accountSettings = [:] }
        var enabled = true, disabled = Set<String>(), entries: [PersonalDataForDetection] = [], keys = Set<String>()
        var ids = Set<String>(), preferenceFound = false
        for row in memories {
            guard let id = row["id"] as? String, !id.isEmpty, ids.insert(id).inserted,
                  let app = row["app_id"] as? String, let type = row["item_type"] as? String,
                  let ciphertext = row["encrypted_item_json"] as? String, !ciphertext.isEmpty else { throw NativePersonalPrivacyError.invalidSnapshot }
            keys.insert("\(app)-\(type)")
            // The web compiler verifies every row; no unreadable row silently
            // turns a partial encrypted snapshot into complete discovery.
            let body = try await object(ciphertext)
            guard app == "privacy" else { continue }
            if type == "pii_detection_settings" {
                guard !preferenceFound else { throw NativePersonalPrivacyError.invalidSnapshot }
                preferenceFound = true
                enabled = body["masterEnabled"] as? Bool != false
                if let categories = body["categories"] as? [String: Bool] { disabled = Set(categories.filter { !$0.value }.map(\.key)) }
                else if body["categories"] != nil { throw NativePersonalPrivacyError.invalidSnapshot }
            } else if type == "personal_data_entry", body["enabled"] as? Bool != false {
                guard let text = body["textToHide"] as? String, let replacement = body["replaceWith"] as? String else { throw NativePersonalPrivacyError.invalidSnapshot }
                let address = (body["addressLines"] as? [String: Any] ?? [:]).values.compactMap { $0 as? String }
                entries.append(PersonalDataForDetection(id: id, textToHide: text.trimmingCharacters(in: .whitespacesAndNewlines), replaceWith: replacement,
                    additionalTexts: address.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }))
            }
        }
        if ["memory_documents", "rule_documents"].contains(where: { (accountSettings[$0] as? [Any])?.isEmpty == false }) {
            keys.insert("openmates-memories")
        }
        return Self(settings: PIIPrivacySettings(masterEnabled: enabled, disabledCategories: disabled,
            personalDataEntries: entries.sorted { $0.id < $1.id }), metadataKeys: keys.sorted())
    }
}

enum NativePersonalPrivacyError: Error, Equatable {
    case invalidSnapshot, staleScope, policyNotPersisted, changedAfterPreparation, unsupportedReceipt
}

/// Explicit per-turn exclusions survive a transport retry within their original
/// account/key/Team owner, but never authorize another workspace or later turn.
struct NativePersonalPrivacyExclusionIntent {
    let scope: ChatPreparationScope
    let originals: Set<String>
    let recordedAt: Date
    func values(for current: ChatPreparationScope, now: Date) -> Set<String> {
        guard scope.account == current.account, scope.server == current.server,
              scope.keyGeneration == current.keyGeneration, scope.teamID == current.teamID,
              scope.teamEpoch == current.teamEpoch, now.timeIntervalSince(recordedAt) >= 0,
              now.timeIntervalSince(recordedAt) < 7_200 else { return [] }
        return originals
    }
}

@MainActor
final class NativePersonalPrivacyRuntime {
    static let shared = NativePersonalPrivacyRuntime()
    struct Receipt {
        let turnID: String
        let scope: ChatPreparationScope
        let generation: String?
        let receiptID: String?
        let privacy: NativeCompiledPersonalPrivacy
        let mutation: UInt64
        let checkedAt: Date
    }
    private struct Cache {
        var generation: ChatPreparedPrivacyGeneration
        let privacy: NativeCompiledPersonalPrivacy
    }
    private var cache: Cache?
    private var receipts: [String: Receipt] = [:]
    private var preparing: ChatPreparationScope?
    private var exclusionsByTurn: [String: NativePersonalPrivacyExclusionIntent] = [:]

    static func scope(socket: WebSocketManager) -> ChatPreparationScope {
        let team = TeamWorkspaceContext.shared.snapshot
        return ChatPreparationScope(account: OfflineStore.shared.scopeGeneration, server: ServerProfile.current().apiBaseURL.absoluteString,
            keyGeneration: ChatKeyManager.shared.cacheGeneration, teamID: team.teamID, teamEpoch: team.epoch,
            socketGeneration: socket.transportGeneration)
    }
    static func require(_ scope: ChatPreparationScope, socket: WebSocketManager) throws {
        guard socket.isConnected, Self.scope(socket: socket) == scope else { throw NativePersonalPrivacyError.staleScope }
        try Task.checkCancellation()
    }
    func invalidate() { cache = nil; receipts.removeAll(); exclusionsByTurn.removeAll() }
    func transportDidChange(socket: WebSocketManager) {
        cache = nil; receipts.removeAll()
        let owner = Self.scope(socket: socket), now = Date()
        exclusionsByTurn = exclusionsByTurn.filter { !$0.value.values(for: owner, now: now).isEmpty }
    }

    /// No current text or inference is passed to focus preparation.
    func warm(socket: WebSocketManager) async {
        let owner = Self.scope(socket: socket)
        guard preparing != owner else { return }
        preparing = owner
        defer { if preparing == owner { preparing = nil } }
        do {
            guard let result = try await socket.preparePersonalPrivacyContext() else { return }
            try Self.require(owner, socket: socket)
            let mutation = PIIPrivacySettingsStore.shared.privacyMutationRevision
            let compiled = try await compile(result, scope: owner, socket: socket)
            try Self.require(owner, socket: socket)
            guard mutation == PIIPrivacySettingsStore.shared.privacyMutationRevision,
                  let generation = result["privacy_generation"] as? String, !generation.isEmpty else { return }
            cache = Cache(generation: ChatPreparedPrivacyGeneration(scope: owner, generation: generation,
                mutationRevision: mutation, touchedAt: Date()), privacy: compiled)
        } catch { if Self.scope(socket: socket) == owner { cache = nil } }
    }

    func fresh(turnID: String, socket: WebSocketManager) async throws -> Receipt {
        let owner = Self.scope(socket: socket)
        try await PIIPrivacySettingsStore.shared.waitForPrivacyMutations()
        try Self.require(owner, socket: socket)
        let mutation = PIIPrivacySettingsStore.shared.privacyMutationRevision
        let known = cache.flatMap { cached -> String? in
            guard cached.generation.scope == owner, cached.generation.mutationRevision == mutation,
                  Date().timeIntervalSince(cached.generation.touchedAt) < 7_200 else { return nil }
            return cached.generation.generation
        }
        let result: [String: Any]
        if let response = try await socket.personalPrivacySnapshotForSend(turnID: turnID, knownGeneration: known) { result = response }
        else { result = try await fullSnapshot(turnID: turnID, scope: owner, socket: socket) }
        try Self.require(owner, socket: socket)
        let generation = result["privacy_generation"] as? String
        let compiled: NativeCompiledPersonalPrivacy
        if result["unchanged"] as? Bool == true {
            guard var cached = cache, result["personal_memories"] == nil,
                  cached.generation.validateReuse(scope: owner, freshGeneration: generation, mutationRevision: mutation, now: Date()) else {
                throw NativePersonalPrivacyError.invalidSnapshot
            }
            compiled = cached.privacy; cache = cached
        } else {
            compiled = try await compile(result, scope: owner, socket: socket)
        }
        try Self.require(owner, socket: socket)
        try PIIPrivacySettingsStore.shared.reconcilePrivacyPersistence(with: compiled.settings, expectedRevision: mutation)
        if let generation, !generation.isEmpty {
            cache = Cache(generation: ChatPreparedPrivacyGeneration(scope: owner, generation: generation,
                mutationRevision: mutation, touchedAt: Date()), privacy: compiled)
        } else { cache = nil }
        guard result["turn_id"] as? String == turnID else { throw NativePersonalPrivacyError.unsupportedReceipt }
        let receiptID = result["receipt_id"] as? String
        if result["legacy_full_snapshot"] as? Bool != true, receiptID?.isEmpty != false { throw NativePersonalPrivacyError.unsupportedReceipt }
        let receipt = Receipt(turnID: turnID, scope: owner, generation: generation, receiptID: receiptID,
            privacy: compiled, mutation: mutation, checkedAt: Date())
        receipts = receipts.filter { $0.value.scope == owner && Date().timeIntervalSince($0.value.checkedAt) < 25 }
        receipts[turnID] = receipt
        return receipt
    }
    /// Revision requests need fresh Personal privacy but do not consume a chat
    /// admission receipt. Use the complete authenticated session fallback.
    func freshForQueuedRevision(requestID: String, socket: WebSocketManager) async throws -> Receipt {
        let owner = Self.scope(socket: socket)
        try await PIIPrivacySettingsStore.shared.waitForPrivacyMutations()
        let mutation = PIIPrivacySettingsStore.shared.privacyMutationRevision
        let result = try await fullSnapshot(turnID: requestID, scope: owner, socket: socket)
        let privacy = try await compile(result, scope: owner, socket: socket)
        try Self.require(owner, socket: socket)
        try PIIPrivacySettingsStore.shared.reconcilePrivacyPersistence(with: privacy.settings, expectedRevision: mutation)
        let receipt = Receipt(turnID: requestID, scope: owner, generation: nil, receiptID: nil,
            privacy: privacy, mutation: mutation, checkedAt: Date())
        receipts[requestID] = receipt
        return receipt
    }

    private struct FullSnapshotRequest: Encodable, Sendable {
        let sessionId: String
        let includePersonalMemories = true
    }
    /// Capability fallback always obtains a complete first-party session batch.
    /// Existing verified transport checks authority before cookie publication.
    private func fullSnapshot(turnID: String, scope: ChatPreparationScope, socket: WebSocketManager) async throws -> [String: Any] {
        let snapshotLease = try await ChatSavedSendAdmissionGate.shared.acquire(.init(scope: scope, chatID: "privacy-session-snapshot"))
        defer { snapshotLease.release() }
        try Self.require(scope, socket: socket)
        guard let accountID = await AuthManager.currentUserId() else { throw NativePersonalPrivacyError.staleScope }
        let profile = ServerProfile.current(), sessionID = AuthManager.nativeSessionId
        let bytes = try await APIClient.shared.requestForVerifiedWatchSession(.post, path: "/v1/auth/session", serverProfile: profile,
            body: FullSnapshotRequest(sessionId: sessionID), verifyResponse: { response, data in
                guard (200...299).contains(response.statusCode),
                      let result = try JSONSerialization.jsonObject(with: data) as? [String: Any], result["success"] as? Bool == true,
                      (result["user"] as? [String: Any])?["id"] as? String == accountID,
                      result["re_auth_required"] == nil || result["re_auth_required"] is NSNull,
                      result["needs_device_verification"] as? Bool != true else { throw NativePersonalPrivacyError.staleScope }
            }, validate: {
                try Self.require(scope, socket: socket)
                guard AuthManager.nativeSessionId == sessionID else { throw NativePersonalPrivacyError.staleScope }
            })
        try Self.require(scope, socket: socket)
        guard let result = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              let snapshot = result["personal_memories"] as? [String: Any] else { throw NativePersonalPrivacyError.invalidSnapshot }
        return ["turn_id": turnID, "unchanged": false, "legacy_full_snapshot": true, "personal_memories": snapshot]
    }

    private func compile(_ result: [String: Any], scope: ChatPreparationScope, socket: WebSocketManager) async throws -> NativeCompiledPersonalPrivacy {
        guard let snapshot = result["personal_memories"] as? [String: Any], let owner = await AuthManager.currentUserId(),
              let key = try await CryptoManager.shared.loadMasterKey(for: owner) else { throw NativePersonalPrivacyError.invalidSnapshot }
        try Self.require(scope, socket: socket)
        let compiled = try await NativeCompiledPersonalPrivacy.compile(snapshot) { ciphertext in
            try Self.require(scope, socket: socket)
            let text = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
            try Self.require(scope, socket: socket)
            return text
        }
        try Self.require(scope, socket: socket)
        return compiled
    }

    /// Protect only validated protocol reference fields and respect explicit
    /// user exclusions; generated prose never determines privacy categories.
    func filter(_ text: String, receipt: Receipt, socket: WebSocketManager,
                existingMappings: [PIIMapping], excludedOriginals: Set<String> = []) throws -> (content: String, mappings: [PIIMapping]) {
        try Self.require(receipt.scope, socket: socket)
        guard receipt.mutation == PIIPrivacySettingsStore.shared.privacyMutationRevision else { throw NativePersonalPrivacyError.staleScope }
        let result = try NativePersonalPrivacyFilter.apply(text, settings: receipt.privacy.settings,
            existingMappings: existingMappings, excludedOriginals: excludedOriginals)
        exclusionsByTurn[receipt.turnID] = NativePersonalPrivacyExclusionIntent(scope: receipt.scope, originals: excludedOriginals, recordedAt: Date())
        return result
    }

    func verifyQueuedRevision(_ request: ChatQueuedRevisionRequest, fallbackContent: String,
                              mappings: [PIIMapping], socket: WebSocketManager) async throws {
        var receipt = receipts[request.clientRequestID]
        if receipt?.scope != Self.scope(socket: socket) || receipt?.mutation != PIIPrivacySettingsStore.shared.privacyMutationRevision
            || Date().timeIntervalSince(receipt?.checkedAt ?? .distantPast) >= 25 {
            receipt = try await freshForQueuedRevision(requestID: request.clientRequestID, socket: socket)
        }
        guard let receipt else { throw NativePersonalPrivacyError.staleScope }
        let payload = try request.payload(), content = payload["content"] as? String ?? fallbackContent
        let checked = try filter(content, receipt: receipt, socket: socket, existingMappings: mappings,
            excludedOriginals: exclusionsByTurn[request.clientRequestID]?.values(for: receipt.scope, now: Date()) ?? [])
        guard checked.content == content else { throw NativePersonalPrivacyError.changedAfterPreparation }
    }

    func requireReceiptCurrent(turnID: String, socket: WebSocketManager) throws {
        guard let receipt = receipts[turnID] else { throw NativePersonalPrivacyError.staleScope }
        try Self.require(receipt.scope, socket: socket)
        guard receipt.mutation == PIIPrivacySettingsStore.shared.privacyMutationRevision,
              Date().timeIntervalSince(receipt.checkedAt) < 25 else { throw NativePersonalPrivacyError.staleScope }
    }

    /// Add the one-use proof to the transport wrapper only. Reconnect gets a new
    /// receipt for the original immutable turn; ciphertext and digest stay exact.
    func attach(to preflight: [String: Any], outbound: [String: Any], turnID: String,
                socket: WebSocketManager, excludedOriginals: Set<String> = []) async throws -> [String: Any] {
        var receipt = receipts[turnID]
        if receipt?.scope != Self.scope(socket: socket) || receipt?.mutation != PIIPrivacySettingsStore.shared.privacyMutationRevision
            || Date().timeIntervalSince(receipt?.checkedAt ?? .distantPast) >= 25 {
            receipt = try await fresh(turnID: turnID, socket: socket)
        }
        guard let receipt, let message = outbound["message"] as? [String: Any], let content = message["content"] as? String else {
            throw NativePersonalPrivacyError.invalidSnapshot
        }
        let filtered = try filter(content, receipt: receipt, socket: socket, existingMappings: [],
            excludedOriginals: exclusionsByTurn[turnID]?.values(for: receipt.scope, now: Date()) ?? excludedOriginals)
        guard filtered.content == content else { throw NativePersonalPrivacyError.changedAfterPreparation }
        var frame = preflight
        if let receiptID = receipt.receiptID {
            frame["privacy_receipt_id"] = receiptID
            frame["privacy_generation"] = receipt.generation.map { $0 as Any } ?? NSNull()
        }
        return frame
    }
}

enum NativePersonalPrivacyFilter {
    static func apply(_ text: String, settings: PIIPrivacySettings, existingMappings: [PIIMapping],
                      excludedOriginals: Set<String> = []) throws -> (content: String, mappings: [PIIMapping]) {
        let referenceRanges = Self.protectedReferenceRanges(in: text)
        var occupied: [String: String] = [:]
        for mapping in existingMappings {
            if let old = occupied[mapping.placeholder], old != mapping.original { throw NativePersonalPrivacyError.invalidSnapshot }
            occupied[mapping.placeholder] = mapping.original
        }
        var detected: [PIIMatch] = []
        for match in PIIDetector.detect(in: text, options: settings.detectionOptions) {
            guard !excludedOriginals.contains(match.value),
                  !referenceRanges.contains(where: { NSIntersectionRange($0, match.range).length > 0 }) else { continue }
            var replacement = match.placeholder, index = 2
            while let old = occupied[replacement], old != match.value {
                let next = match.placeholder.replacingOccurrences(of: "_\\d+(?=[_\\]])", with: "_\(index)", options: .regularExpression)
                guard next != match.placeholder else { throw NativePersonalPrivacyError.invalidSnapshot }
                replacement = next; index += 1
            }
            occupied[replacement] = match.value
            detected.append(PIIMatch(id: match.id, type: match.type, value: match.value, range: match.range, placeholder: replacement))
        }
        let result = PIIDetector.redactionResult(in: text, matches: detected, options: settings.detectionOptions)
        return (result.redactedText, PIIDetector.mergePIIMappings(existingMappings + result.mappings))
    }

    private static func protectedReferenceRanges(in text: String) -> [NSRange] {
        guard let blocks = try? NSRegularExpression(pattern: #"```json\n([\s\S]*?)\n```"#),
              let fields = try? NSRegularExpression(pattern: #""(?:embed_id|embed_ids)"\s*:\s*("(?:\\.|[^"\\])*"|\[[\s\S]*?\])"#),
              let strings = try? NSRegularExpression(pattern: #""([a-fA-F0-9-]{36})""#) else { return [] }
        let source = text as NSString
        var ranges: [NSRange] = []
        for block in blocks.matches(in: text, range: NSRange(location: 0, length: source.length)) {
            let jsonRange = block.range(at: 1), json = source.substring(with: jsonRange)
            guard let data = json.data(using: .utf8), (try? JSONSerialization.jsonObject(with: data)) != nil else { continue }
            let value = json as NSString
            for field in fields.matches(in: json, range: NSRange(location: 0, length: value.length)) {
                let bodyRange = field.range(at: 1), body = value.substring(with: bodyRange)
                for string in strings.matches(in: body, range: NSRange(location: 0, length: (body as NSString).length)) {
                    let identity = (body as NSString).substring(with: string.range(at: 1))
                    guard UUID(uuidString: identity) != nil else { continue }
                    ranges.append(NSRange(location: jsonRange.location + bodyRange.location + string.range(at: 1).location, length: string.range(at: 1).length))
                }
            }
        }
        return ranges
    }

}
