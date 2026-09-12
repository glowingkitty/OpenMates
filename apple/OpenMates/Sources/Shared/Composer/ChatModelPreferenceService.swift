// Shared state machine for encrypted per-chat model preferences and send routing.
// Protocol: frontend/packages/ui/src/services/chatModelSelection.ts
// Routing: frontend/packages/ui/src/utils/aiModelSelection.ts
import Foundation

struct ModelPreferenceScope: Hashable, Codable, Sendable {
    let server: String
    let userID: String
    let chatID: String
}
struct EncryptedModelPreference: Equatable, Codable, Sendable {
    let ciphertext: String
    let version: Int
    // Local-only outbox marker. Never serialize this field into a WebSocket
    // preference payload. Version is provisional while this marker is present.
    var pendingExpectedVersion: Int? = nil
}
struct ModelRoutingEntry: Sendable {
    let provider: String
    let modelID: String
    let skill: String
    let servers: [String]
}
struct ModelRoutingCatalog: Sendable {
    var entries: [ModelRoutingEntry]
    var disabledModels: Set<String> = []
    var disabledServers: [String: Set<String>] = [:]
    var unhealthyServers: Set<String> = []
    func canonical(_ value: String) -> String? {
        if value == "auto" { return value }
        guard let slash = value.firstIndex(of: "/"), slash != value.startIndex else { return nil }
        let prefix = String(value[..<slash])
        let model = String(value[value.index(after: slash)...])
        return entries.first { $0.skill == "ai.ask" && $0.modelID == model &&
            ($0.provider == prefix || $0.servers.contains(prefix)) }.map { "\($0.provider)/\($0.modelID)" }
    }
    func usable(_ value: String) -> Bool {
        guard let canonical = canonical(value), canonical != "auto",
              let entry = entries.first(where: { "\($0.provider)/\($0.modelID)" == canonical && $0.skill == "ai.ask" }),
              !disabledModels.contains(entry.modelID) else { return false }
        return entry.servers.contains { !(disabledServers[entry.modelID] ?? []).contains($0) && !unhealthyServers.contains($0) }
    }
    func prefix(selection: String, text: String) -> String {
        guard !text.contains("@ai-model:"), !text.contains("@best-model:"),
              let value = canonical(selection), value != "auto", let slash = value.firstIndex(of: "/") else { return text }
        return "@ai-model:\(value[value.index(after: slash)...]):\(value[..<slash]) " + text
    }
}

// Transport implementations MUST bind to the supplied authenticated scope and
// connection generation, serialize requests per chat, and time out after 10s.
// Persistence MUST address the supplied scope, never a mutable global account.
@MainActor protocol ModelPreferenceAdapters: AnyObject {
    func withMutationLease(_ scope: ModelPreferenceScope, operation: @escaping @MainActor () async throws -> String) async throws -> String
    func encryptFormatD(_ plaintext: String, scope: ModelPreferenceScope) async throws -> String
    func decryptFormatD(_ ciphertext: String, scope: ModelPreferenceScope) async throws -> String
    func localRead(_ scope: ModelPreferenceScope) async throws -> EncryptedModelPreference?
    func localWrite(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) async throws
    func localWriteIfNewer(_ record: EncryptedModelPreference, scope: ModelPreferenceScope) async throws -> EncryptedModelPreference
    func remoteRead(_ scope: ModelPreferenceScope) async throws -> EncryptedModelPreference?
    // nil means chat_model_preference_conflict; transport errors must throw.
    func compareAndSet(_ record: EncryptedModelPreference, expected: Int, scope: ModelPreferenceScope) async throws -> EncryptedModelPreference?
}

// Test/standalone adapters can execute directly; the production adapter uses
// one app-owned lease per account/chat for the entire local-stage/CAS/ACK cycle.
extension ModelPreferenceAdapters {
    func withMutationLease(_ scope: ModelPreferenceScope, operation: @escaping @MainActor () async throws -> String) async throws -> String {
        try await operation()
    }
}

enum ModelPreferenceFailure: Error, Equatable {
    case staleContext, busy, notRestored, invalidPayload, invalidAcknowledgement, repeatedConflict, unavailable
}

@MainActor final class ChatModelPreferenceService {
    private let adapters: ModelPreferenceAdapters
    private let catalog: () -> ModelRoutingCatalog
    private let notify: (String) -> Void
    var stateDidChange: (() -> Void)?
    private var scope: ModelPreferenceScope?
    private var generation: UInt64 = 0
    private var busy = false
    private var restored = false
    private var pendingRemote: EncryptedModelPreference?
    private var drainingRemote = false
    var isReady: Bool { scope != nil && restored && !busy && pendingRemote == nil && !drainingRemote }
    private(set) var selection = "auto"
    init(adapters: ModelPreferenceAdapters, catalog: @escaping () -> ModelRoutingCatalog, notify: @escaping (String) -> Void) {
        self.adapters = adapters; self.catalog = catalog; self.notify = notify
    }
    func activate(_ scope: ModelPreferenceScope?) {
        generation &+= 1; self.scope = scope; selection = "auto"; busy = false
        restored = false; pendingRemote = nil; drainingRemote = false
        stateDidChange?()
    }
    private func check(_ scope: ModelPreferenceScope, _ generation: UInt64) throws {
        guard self.scope == scope, self.generation == generation else { throw ModelPreferenceFailure.staleContext }
    }
    private func begin() throws -> (ModelPreferenceScope, UInt64) {
        guard let scope else { throw ModelPreferenceFailure.staleContext }
        guard !busy else { throw ModelPreferenceFailure.busy }
        busy = true; return (scope, generation)
    }
    private func end(_ token: UInt64) {
        guard generation == token else { return }
        busy = false
        stateDidChange?()
        guard pendingRemote != nil, !drainingRemote else { return }
        drainingRemote = true
        Task { [weak self] in
            guard let self, self.generation == token else { return }
            defer { if self.generation == token { self.drainingRemote = false; self.stateDidChange?() } }
            while let record = self.pendingRemote, let scope = self.scope, self.generation == token {
                self.pendingRemote = nil
                do { _ = try await self.receiveRemote(record, for: scope) }
                catch {
                    guard self.generation == token else { return }
                    self.restored = false
                    self.notify("enter_message.model_selector.load_failed")
                    return
                }
            }
        }
    }
    private func decode(_ record: EncryptedModelPreference, _ scope: ModelPreferenceScope, _ token: UInt64) async throws -> String {
        guard record.version >= 0, !record.ciphertext.isEmpty,
              record.pendingExpectedVersion.map({ $0 >= 0 && $0 < Int.max && record.version == $0 + 1 }) ?? true else {
            throw ModelPreferenceFailure.invalidPayload
        }
        let plaintext = try await adapters.decryptFormatD(record.ciphertext, scope: scope)
        try check(scope, token)
        guard let data = plaintext.data(using: .utf8), let object = try JSONSerialization.jsonObject(with: data) as? [String: String] else { throw ModelPreferenceFailure.invalidPayload }
        if object["mode"] == "auto" { return "auto" }
        guard object["mode"] == "exact", let model = object["model"], !model.isEmpty else { throw ModelPreferenceFailure.invalidPayload }
        return model
    }
    private func persist(_ value: String, _ scope: ModelPreferenceScope, _ token: UInt64, synchronize: Bool = true) async throws -> String {
        let local = try await adapters.localRead(scope); try check(scope, token)
        let body = value == "auto" ? ["mode": "auto"] : ["mode": "exact", "model": value]
        let plaintext = String(decoding: try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys]), as: UTF8.self)
        let ciphertext = try await adapters.encryptFormatD(plaintext, scope: scope); try check(scope, token)
        let expected = local?.pendingExpectedVersion ?? local?.version ?? 0
        guard expected >= 0, expected < Int.max else { throw ModelPreferenceFailure.invalidPayload }
        let staged = EncryptedModelPreference(ciphertext: ciphertext, version: expected + 1, pendingExpectedVersion: expected)
        // One atomic local record contains ciphertext plus its expected remote
        // version. Reconnect can replay this intent without inventing a new CAS.
        try await adapters.localWrite(staged, scope: scope); try check(scope, token)
        selection = value
        return synchronize ? try await syncPending(staged, scope, token) : value
    }
    private func syncPending(_ staged: EncryptedModelPreference, _ scope: ModelPreferenceScope, _ token: UInt64) async throws -> String {
        guard var expected = staged.pendingExpectedVersion else { throw ModelPreferenceFailure.invalidPayload }
        var record = staged
        for attempt in 0..<2 {
            try check(scope, token)
            let accepted = try await adapters.compareAndSet(record, expected: expected, scope: scope); try check(scope, token)
            if let accepted {
                guard accepted.ciphertext == staged.ciphertext, accepted.version == expected + 1,
                      accepted.pendingExpectedVersion == nil else { throw ModelPreferenceFailure.invalidAcknowledgement }
                try await adapters.localWrite(accepted, scope: scope); try check(scope, token)
                selection = try await decode(accepted, scope, token)
                restored = true
                return selection
            }
            guard let remote = try await adapters.remoteRead(scope) else { throw ModelPreferenceFailure.repeatedConflict }
            try check(scope, token)
            // An acknowledgement can be lost after the server stored this exact
            // ciphertext. A replay conflict with the same ciphertext is success,
            // never a second preference write/version increment.
            if remote.ciphertext == staged.ciphertext && remote.version >= expected + 1 {
                try await adapters.localWrite(remote, scope: scope); try check(scope, token)
                selection = try await decode(remote, scope, token)
                restored = true
                return selection
            }
            if attempt == 1 {
                let latest = try await decode(remote, scope, token)
                try await adapters.localWrite(remote, scope: scope); try check(scope, token)
                selection = latest; restored = true
                throw ModelPreferenceFailure.repeatedConflict
            }
            guard remote.version >= 0, remote.version < Int.max else { throw ModelPreferenceFailure.invalidPayload }
            expected = remote.version
            record = EncryptedModelPreference(ciphertext: staged.ciphertext, version: expected + 1, pendingExpectedVersion: expected)
            try await adapters.localWrite(record, scope: scope); try check(scope, token)
        }
        throw ModelPreferenceFailure.repeatedConflict
    }
    // Stage a new chat's exact selection before its view is replaced. Its next
    // saved-chat host restores this encrypted outbox; navigation never waits for
    // the server to materialize the concurrently submitted first message.
    func stage(_ value: String) async throws -> String {
        guard let scope else { throw ModelPreferenceFailure.staleContext }
        let token = generation
        return try await adapters.withMutationLease(scope) { [self] in
            try check(scope, token)
            return try await stageUnlocked(value)
        }
    }
    private func stageUnlocked(_ value: String) async throws -> String {
        let (scope, token) = try begin(); defer { end(token) }
        restored = false
        guard let canonical = catalog().canonical(value), canonical == "auto" || catalog().usable(canonical) else {
            throw ModelPreferenceFailure.unavailable
        }
        return try await persist(canonical, scope, token, synchronize: false)
    }
    func select(_ value: String) async throws -> String {
        guard let scope else { throw ModelPreferenceFailure.staleContext }
        let token = generation
        return try await adapters.withMutationLease(scope) { [self] in
            try check(scope, token)
            return try await selectUnlocked(value)
        }
    }
    private func selectUnlocked(_ value: String) async throws -> String {
        let (scope, token) = try begin(); defer { end(token) }
        restored = false
        guard let canonical = catalog().canonical(value), canonical == "auto" || catalog().usable(canonical) else {
            notify("enter_message.model_selector.unavailable_reset")
            _ = try await persist("auto", scope, token)
            throw ModelPreferenceFailure.unavailable
        }
        return try await persist(canonical, scope, token)
    }
    func restore() async throws -> String {
        guard let scope else { throw ModelPreferenceFailure.staleContext }
        let token = generation
        return try await adapters.withMutationLease(scope) { [self] in
            try check(scope, token)
            return try await restoreUnlocked()
        }
    }
    private func restoreUnlocked() async throws -> String {
        let (scope, token) = try begin(); defer { end(token) }
        restored = false
        let local = try await adapters.localRead(scope); try check(scope, token)
        if let local, local.pendingExpectedVersion != nil {
            let value = try await decode(local, scope, token)
            if value != "auto", !(catalog().canonical(value).map { catalog().usable($0) } ?? false) {
                notify("enter_message.model_selector.unavailable_reset")
                return try await persist("auto", scope, token)
            }
            return try await syncPending(local, scope, token)
        }
        var remote: EncryptedModelPreference?
        do { remote = try await adapters.remoteRead(scope) } catch { try check(scope, token) }
        try check(scope, token)
        let record = (remote?.version ?? -1) > (local?.version ?? -1) ? remote : local
        guard let record else { selection = "auto"; restored = true; return selection }
        let value = try await decode(record, scope, token)
        if record == remote { try await adapters.localWrite(record, scope: scope); try check(scope, token) }
        if value == "auto" { selection = value; restored = true; return value }
        guard let canonical = catalog().canonical(value), catalog().usable(canonical) else {
            notify("enter_message.model_selector.unavailable_reset")
            return try await persist("auto", scope, token)
        }
        if canonical != value { return try await persist(canonical, scope, token) }
        selection = canonical; restored = true; return canonical
    }
    func receiveRemote(_ record: EncryptedModelPreference, for incomingScope: ModelPreferenceScope) async throws -> String {
        guard scope == incomingScope else { throw ModelPreferenceFailure.staleContext }
        guard record.version >= 0, record.pendingExpectedVersion == nil else { throw ModelPreferenceFailure.invalidPayload }
        if busy {
            if record.version >= (pendingRemote?.version ?? -1) { pendingRemote = record }
            return selection
        }
        let (scope, token) = try begin(); defer { end(token) }
        let local = try await adapters.localRead(scope); try check(scope, token)
        if let local, let expected = local.pendingExpectedVersion {
            if record.ciphertext == local.ciphertext && record.version >= expected + 1 {
                try await adapters.localWrite(record, scope: scope); try check(scope, token)
                selection = try await decode(record, scope, token); restored = true
            }
            // Preserve newer unsynced user intent if a different remote mutation
            // arrives. Reconnect/restore reconciles its exact pending CAS.
            return selection
        }
        let retained = try await adapters.localWriteIfNewer(record, scope: scope)
        try check(scope, token)
        selection = try await decode(retained, scope, token)
        restored = true
        return selection // textForSend still performs current availability recovery.
    }
    func textForSend(_ text: String) async throws -> String {
        guard !busy else { throw ModelPreferenceFailure.busy }
        guard scope != nil else { throw ModelPreferenceFailure.staleContext }
        guard isReady else { throw ModelPreferenceFailure.notRestored }
        if text.contains("@ai-model:") || text.contains("@best-model:") { return text }
        if selection != "auto" && !catalog().usable(selection) {
            notify("enter_message.model_selector.unavailable_reset")
            _ = try await select("auto") // Failure propagates; never silently send on failed recovery.
        }
        return catalog().prefix(selection: selection, text: text)
    }
}
