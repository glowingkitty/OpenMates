// Watch authority is injected; app AuthManager, Team and OfflineStore are not used.
// Web: frontend/packages/ui/src/services/voiceCallTools.ts;
// frontend/packages/ui/src/components/AppSettingsMemoriesPermissionDialog.svelte
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.privacy
import Combine
import CryptoKit
import Foundation

@MainActor
final class WatchVoiceCallMemoryPermission: ObservableObject {
    typealias Validation = @MainActor @Sendable () async throws -> Void
    struct Dependencies {
        /// A real loader must use verified Watch HTTP, this exact request context,
        /// the account master key and current hide-personal-data metadata policy.
        /// Catalog discovery alone cannot grant access or substitute for privacy.
        var load: @MainActor @Sendable (NativeVoiceCallScope, WatchChatRequestContext, [String]) async throws -> NativeVoiceCallMemoryPolicy.Snapshot
        var now: @MainActor @Sendable () -> Date = { Date() }
        var lifetime: TimeInterval = 120
        static var live: Self {
            Self(load: { scope, context, keys in
                try await WatchVoiceCallMemoryLoader.live.load(scope: scope, context: context, keys: keys)
            })
        }
    }
    struct Prompt: Identifiable {
        let id: UUID
        let scope: NativeVoiceCallScope
        let request: NativeVoiceCallMemoryPolicy.Request
        let snapshot: NativeVoiceCallMemoryPolicy.Snapshot
        let expiresAt: Date
        var selectedIDs: Set<String> = []
        var deciding = false
        var categories: [NativeVoiceCallMemoryPolicy.Category] { snapshot.categories }
        var choices: [NativeVoiceCallMemoryPolicy.Choice] { snapshot.choices }
    }
    @Published private(set) var prompt: Prompt?
    private let dependencies: Dependencies
    private var operationID: UUID?
    private var continuation: CheckedContinuation<NativeVoiceCallArtifactDisposition, any Error>?
    private var validation: Validation?
    private var approvalValidation: Validation?
    private var expiry: Task<Void, Never>?
    private var decisionTask: Task<Void, Never>?

    init(dependencies: Dependencies = .live) { self.dependencies = dependencies }

    func invalidate() {
        operationID = nil; prompt = nil; validation = nil; approvalValidation = nil
        expiry?.cancel(); expiry = nil
        decisionTask?.cancel(); decisionTask = nil
        let waiting = continuation; continuation = nil
        waiting?.resume(throwing: CancellationError())
    }

    func request(scope: NativeVoiceCallScope, callID: String, frame: NativeVoiceCallFrame,
                 context: WatchChatRequestContext, validate: @escaping Validation) async throws -> NativeVoiceCallArtifactDisposition {
        guard operationID == nil else { throw NativeVoiceCallError.invalidState }
        let request = try NativeVoiceCallMemoryPolicy.Request(scope: scope, callID: callID, frame: frame)
        try context.check()
        guard context.accountID == scope.accountID, context.profile.id == scope.profileID else { throw NativeVoiceCallError.scopeChanged }
        let id = UUID(); operationID = id
        defer { if operationID == id { invalidate() } }
        return try await withTaskCancellationHandler {
            try await validate(); try check(id)
            // Personal documents require a separate genuine loader, never Project focus suggestions.
            guard !request.requestsPersonalDocuments else { return .unsupported }
            let snapshot: NativeVoiceCallMemoryPolicy.Snapshot
            do { snapshot = try await dependencies.load(scope, context, request.keys).requested(request) }
            catch NativeVoiceCallError.unsupportedTransport {
                try context.check(); try await validate(); try check(id)
                return .unsupported
            }
            try context.check(); try await validate(); try check(id)
            validation = {
                try context.check()
                try await validate()
                try context.check()
            }
            let load = dependencies.load
            approvalValidation = {
                try context.check(); try await validate()
                let fresh = try await load(scope, context, request.keys).requested(request)
                try context.check(); try await validate()
                guard fresh == snapshot else { throw NativeVoiceCallError.scopeChanged }
            }
            return try await withCheckedThrowingContinuation { waiting in
                guard operationID == id, !Task.isCancelled else { waiting.resume(throwing: CancellationError()); return }
                continuation = waiting
                let lifetime = max(0, min(dependencies.lifetime, 120))
                prompt = Prompt(id: id, scope: scope, request: request, snapshot: snapshot,
                    expiresAt: dependencies.now().addingTimeInterval(lifetime))
                expiry = Task { [weak self] in
                    do { try await Task.sleep(for: .seconds(lifetime)) } catch { return }
                    if self?.operationID == id { self?.invalidate() }
                }
            }
        } onCancel: { [weak self] in
            Task { @MainActor in if self?.operationID == id { self?.invalidate() } }
        }
    }

    private func check(_ id: UUID) throws {
        try Task.checkCancellation()
        guard operationID == id else { throw CancellationError() }
        if let prompt, dependencies.now() >= prompt.expiresAt { throw CancellationError() }
    }
    func setSelected(_ selected: Bool, choiceID: String, promptID: UUID) {
        guard var current = prompt, current.id == promptID, !current.deciding,
              dependencies.now() < current.expiresAt, current.choices.contains(where: { $0.id == choiceID }) else { return }
        if selected { current.selectedIDs.insert(choiceID) } else { current.selectedIDs.remove(choiceID) }
        prompt = current
    }
    func decide(promptID: UUID, includeSelected: Bool) async {
        guard var current = prompt, current.id == promptID, !current.deciding, let validate = validation,
              !includeSelected || !current.selectedIDs.isEmpty else { return }
        current.deciding = true; prompt = current
        let task = Task { [weak self] in
            guard let self else { return }
            await finishDecision(current, validate: validate, includeSelected: includeSelected)
        }
        decisionTask = task
        await task.value
        if operationID == promptID { decisionTask = nil }
    }
    private func finishDecision(_ current: Prompt, validate: Validation, includeSelected: Bool) async {
        let promptID = current.id
        do {
            try await validate(); try check(promptID)
            if includeSelected {
                guard let approvalValidation else { throw CancellationError() }
                try await approvalValidation(); try check(promptID)
            }
            let reply = try NativeVoiceCallMemoryPolicy.response(current.request, snapshot: current.snapshot,
                selectedIDs: current.selectedIDs, includeSelected: includeSelected)
            try check(promptID)
            let waiting = continuation; continuation = nil
            prompt = nil; validation = nil; approvalValidation = nil; expiry?.cancel(); expiry = nil; decisionTask = nil
            waiting?.resume(returning: .response(reply))
        } catch {
            // A cancelled refresh may ignore cancellation until its transport
            // returns. Its old operation cannot tear down a replacement prompt.
            if operationID == promptID { invalidate() }
        }
    }
}

/// The first-party session snapshot is a complete current Personal directory,
/// including encrypted account settings and hide-personal-data policy rows.
/// Public app metadata supplies labels/schema only, never availability authority.
/// Contract: deployed preparedPrivacyForSend.ts fullSnapshot/compilePersonalPrivacy/
/// personalPrivacyMetadataKeys and auth_session.py include_personal_memories.
@MainActor
struct WatchVoiceCallMemoryLoader {
    typealias Policy = NativeVoiceCallMemoryPolicy
    struct Dependencies {
        var request: @MainActor @Sendable (HTTPMethod, String, Data?, WatchChatRequestContext) async throws -> Data
        var masterKey: @MainActor @Sendable (String) async throws -> SymmetricKey?
        var decrypt: @MainActor @Sendable (String, SymmetricKey) async throws -> String
        var sessionID: @MainActor @Sendable () -> String
        var localize: @MainActor @Sendable (String) -> String
    }
    let dependencies: Dependencies
    static var live: Self {
        Self(dependencies: .init(request: { method, path, body, context in
            if method == .get, path == "/v1/apps/metadata?include_unavailable=true", body == nil {
                return try await publicCatalog(context: context)
            }
            guard method == .post, path == "/v1/auth/session" else { throw NativeVoiceCallError.unsupportedTransport }
            guard let accountID = context.accountID else { throw NativeVoiceCallError.scopeChanged }
            return try await APIClient.shared.requestForVerifiedWatchSession(method, path: path,
                serverProfile: context.profile, body: body.map { JSONRawBody(data: $0) },
                headers: ["Cache-Control": "no-cache", "Pragma": "no-cache"],
                verifyResponse: { response, bytes in
                    guard path == "/v1/auth/session", (200...299).contains(response.statusCode) else { return }
                    _ = try Self.sessionSnapshot(bytes, accountID: accountID)
                }, validate: { try context.check() })
        }, masterKey: { try await CryptoManager.shared.loadMasterKey(for: $0) },
            decrypt: { try await CryptoManager.shared.decryptContent(base64String: $0, key: $1) },
            sessionID: { WatchCompatibleSession.nativeSessionId }, localize: { key in
                #if os(watchOS)
                WatchLocalization.text(key)
                #else
                AppStrings.localized(key)
                #endif
            }))
    }

    private final class PublicLabelsNoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
        nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
            willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
            completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }
    }
    private static func publicCatalog(context: WatchChatRequestContext) async throws -> Data {
        try context.check()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil; configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil; configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 15
        let session = URLSession(configuration: configuration, delegate: PublicLabelsNoRedirect(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var components = URLComponents(url: context.profile.apiBaseURL.appendingPathComponent("v1/apps/metadata"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "include_unavailable", value: "true")]
        guard let url = components?.url else { throw NativeVoiceCallError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpShouldHandleCookies = false
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (bytes, response) = try await session.bytes(for: request)
        try context.check()
        guard let response = response as? HTTPURLResponse, (200...299).contains(response.statusCode),
              response.expectedContentLength <= 2 * 1_024 * 1_024 else { throw NativeVoiceCallError.invalidResponse }
        var data = Data()
        for try await byte in bytes {
            guard data.count < 2 * 1_024 * 1_024 else { throw NativeVoiceCallError.contextTooLarge }
            if data.count % 16_384 == 0 { try context.check() }
            data.append(byte)
        }
        try context.check()
        return data
    }

    private struct Row {
        let id: String
        let appID: String
        let categoryID: String
        let itemKey: String
        let fields: NativeVoiceCallFrame
        var metadataKey: String { appID + "-" + categoryID }
    }
    private struct Prepared {
        let keys: Set<String>
        let rows: [Row]
        let fingerprint: String
    }
    private static func sessionSnapshot(_ data: Data, accountID: String) throws -> NativeVoiceCallFrame {
        guard data.count <= 8 * 1_024 * 1_024,
              let result = try? JSONDecoder().decode(NativeVoiceCallFrame.self, from: data),
              result["success"]?.bool == true, result["user"]?.object?["id"]?.string == accountID,
              result["re_auth_required"] == nil || result["re_auth_required"] == .null,
              result["needs_device_verification"]?.bool != true else { throw NativeVoiceCallError.scopeChanged }
        guard let snapshot = result["personal_memories"]?.object else { throw NativeVoiceCallError.unsupportedTransport }
        guard snapshot["encrypted_settings"] == .null || snapshot["encrypted_settings"]?.string != nil,
              case .array(let rows)? = snapshot["memories"], rows.count <= 10_000,
              rows.allSatisfy({ $0.object != nil }) else { throw NativeVoiceCallError.invalidResponse }
        return snapshot
    }
    private func prepare(context: WatchChatRequestContext) async throws -> Prepared {
        try context.check()
        guard let accountID = context.accountID, !accountID.isEmpty,
              let key = try await dependencies.masterKey(accountID) else { throw NativeVoiceCallError.contextUnavailable }
        try context.check()
        let sessionID = dependencies.sessionID()
        let body = try JSONEncoder().encode(["session_id": NativeVoiceCallJSON.string(sessionID), "include_personal_memories": .bool(true)])
        let data = try await dependencies.request(.post, "/v1/auth/session", body, context)
        try context.check()
        guard dependencies.sessionID() == sessionID else { throw NativeVoiceCallError.scopeChanged }
        let snapshot = try Self.sessionSnapshot(data, accountID: accountID)
        var totalBytes = 0
        func object(_ ciphertext: String) async throws -> NativeVoiceCallFrame {
            try context.check()
            let plaintext = try await dependencies.decrypt(ciphertext, key)
            try context.check()
            guard dependencies.sessionID() == sessionID else { throw NativeVoiceCallError.scopeChanged }
            totalBytes += plaintext.utf8.count
            guard totalBytes <= 8 * 1_024 * 1_024,
                  let object = try? JSONDecoder().decode(NativeVoiceCallFrame.self, from: Data(plaintext.utf8))
            else { throw NativeVoiceCallError.contextTooLarge }
            return object
        }
        let settings: NativeVoiceCallFrame
        if let ciphertext = snapshot["encrypted_settings"]?.string { settings = try await object(ciphertext) }
        else { settings = [:] }
        guard case .array(let encryptedRows)? = snapshot["memories"] else { throw NativeVoiceCallError.invalidResponse }
        var rows: [Row] = [], ids = Set<String>(), preferenceFound = false
        for raw in encryptedRows {
            guard let row = raw.object, let id = row["id"]?.string, !id.isEmpty, ids.insert(id).inserted,
                  let app = row["app_id"]?.string, !app.isEmpty,
                  let type = row["item_type"]?.string, !type.isEmpty,
                  let itemKey = row["item_key"]?.string, !itemKey.isEmpty,
                  let ciphertext = row["encrypted_item_json"]?.string, !ciphertext.isEmpty,
                  row["team_id"] == nil || row["team_id"] == .null,
                  row["hashed_team_id"] == nil || row["hashed_team_id"] == .null
            else { throw NativeVoiceCallError.invalidResponse }
            let fields = try await object(ciphertext)
            // Validate the current policy alongside the directory; no missing or
            // unreadable privacy row may be dropped to manufacture partial discovery.
            if app == "privacy", type == "pii_detection_settings" {
                guard !preferenceFound, fields["masterEnabled"] == nil || fields["masterEnabled"]?.bool != nil,
                      fields["categories"] == nil || fields["categories"]?.object?.values.allSatisfy({ $0.bool != nil }) == true
                else { throw NativeVoiceCallError.invalidResponse }
                preferenceFound = true
            }
            if app == "privacy", type == "personal_data_entry", fields["enabled"]?.bool != false {
                guard fields["textToHide"]?.string != nil, fields["replaceWith"]?.string != nil else { throw NativeVoiceCallError.invalidResponse }
            }
            rows.append(Row(id: id, appID: app, categoryID: app == "travel" && type == "interests" ? "preferred_activities" : type,
                itemKey: itemKey, fields: fields))
        }
        try context.check()
        guard dependencies.sessionID() == sessionID else { throw NativeVoiceCallError.scopeChanged }
        var keys = Set(rows.map(\.metadataKey))
        if ["memory_documents", "rule_documents"].contains(where: { field in
            if case .array(let values)? = settings[field] { return !values.isEmpty }; return false
        }) { keys.insert("openmates-memories") }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let fingerprintSource: NativeVoiceCallJSON = .object(["settings": .object(settings), "memories": .array(rows.sorted { $0.id < $1.id }.map {
            .object(["id": .string($0.id), "app_id": .string($0.appID), "item_type": .string($0.categoryID),
                "item_key": .string($0.itemKey), "data": .object($0.fields)])
        })])
        let fingerprint = SHA256.hash(data: try encoder.encode(fingerprintSource)).map { String(format: "%02x", $0) }.joined()
        return Prepared(keys: keys, rows: rows, fingerprint: fingerprint)
    }

    func availableMetadata(context: WatchChatRequestContext) async throws -> [String] {
        (try await prepare(context: context)).keys.sorted()
    }

    func load(scope: NativeVoiceCallScope, context: WatchChatRequestContext, keys: [String]) async throws -> Policy.Snapshot {
        try context.check()
        guard context.accountID == scope.accountID, context.profile.id == scope.profileID else { throw NativeVoiceCallError.scopeChanged }
        let prepared = try await prepare(context: context)
        let requested = Set(keys)
        guard !requested.contains("openmates-memories"), requested.isSubset(of: prepared.keys) else { throw NativeVoiceCallError.unsupportedTransport }
        let data = try await dependencies.request(.get, "/v1/apps/metadata?include_unavailable=true", nil, context)
        try context.check()
        guard data.count <= 2 * 1_024 * 1_024,
              let catalog = try? JSONDecoder().decode(NativeVoiceCallFrame.self, from: data), let apps = catalog["apps"]?.object
        else { throw NativeVoiceCallError.invalidResponse }
        var categories: [Policy.Category] = [], choices: [Policy.Choice] = []
        func name(_ fields: NativeVoiceCallFrame, fallback: String) -> String {
            fields["name_translation_key"]?.string.map(dependencies.localize) ?? fields["name"]?.string ?? fallback
        }
        for appID in apps.keys.sorted() {
            guard let app = apps[appID]?.object, case .array(let rawCategories)? = app["settings_and_memories"] else { continue }
            for raw in rawCategories {
                guard let fields = raw.object, let categoryID = fields["id"]?.string, requested.contains(appID + "-" + categoryID) else { continue }
                let category = Policy.Category(appID: appID, categoryID: categoryID,
                    title: name(app, fallback: appID) + " / " + name(fields, fallback: categoryID))
                categories.append(category)
                let properties = fields["schema_definition"]?.object?["properties"]?.object ?? [:]
                let titleField = properties.keys.sorted().first { properties[$0]?.object?["is_title"]?.bool == true }
                    ?? ["name", "title", "label"].first { properties[$0] != nil }
                for row in prepared.rows where row.appID == appID && row.categoryID == categoryID {
                    var content = row.fields
                    content["_original_item_key"] = content["_original_item_key"] ?? .string(row.itemKey)
                    content["settings_group"] = .string(categoryID)
                    let title = titleField.flatMap { content[$0]?.string } ?? content["_original_item_key"]?.string ?? row.itemKey
                    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
                    let value = String(decoding: try encoder.encode(NativeVoiceCallJSON.object(content)), as: UTF8.self)
                    choices.append(Policy.Choice(id: category.id + ":" + row.id, category: category, title: title, value: value, content: .object(content)))
                }
            }
        }
        try context.check()
        return Policy.Snapshot(availableKeys: prepared.keys, categories: categories, choices: choices, privacyFingerprint: prepared.fingerprint)
    }
}
