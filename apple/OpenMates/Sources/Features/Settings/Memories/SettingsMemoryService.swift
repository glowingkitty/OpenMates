// Web source: frontend/packages/ui/src/stores/appSettingsMemoriesStore.ts
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.surface.semantic-parity
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.memories.upcoming, apple-live-activities.lifecycle.isolation
// Plaintext lives only in memory; API records contain ciphertext and hashed keys.

import Combine
import CryptoKit
import Foundation

struct SettingsEncryptedMemoryResponse: Decodable { let memories: [SettingsEncryptedMemoryRecord] }
struct SettingsEncryptedMemoryRecord: Codable {
    let id: String
    let appId: String
    let itemKey: String
    let itemType: String
    let encryptedItemJson: String
    let encryptedAppKey: String
    let createdAt: Int
    let updatedAt: Int
    let itemVersion: Int
    enum CodingKeys: String, CodingKey {
        case id
        case appId = "app_id", itemKey = "item_key", itemType = "item_type"
        case encryptedItemJson = "encrypted_item_json", encryptedAppKey = "encrypted_app_key"
        case createdAt = "created_at", updatedAt = "updated_at", itemVersion = "item_version"
    }
}

struct SettingsMemoryContext {
    let accountID: String?
    let server: ServerProfile
    let scope: UUID
    let team: APIRequestTeamContext
    @MainActor
    func check(environment: TeamWorkspaceEnvironment, teamContext: () -> APIRequestTeamContext) async throws {
        try Task.checkCancellation()
        let currentAccount = await environment.currentAccountID()
        let currentTeam = teamContext()
        guard accountID == currentAccount, server == environment.serverProfile(), scope == environment.scopeGeneration(),
              team.epoch == currentTeam.epoch, team.teamID == currentTeam.teamID else { throw CancellationError() }
    }
}

@MainActor
final class SettingsMemoryService: ObservableObject {
    enum LoadState: Equatable {
        case loading, loaded, empty, missingKey, pending, conflict, error(String)
    }
    typealias Transport = @MainActor (HTTPMethod, String, Data?, SettingsMemoryContext) async throws -> Data
    typealias KeyLoader = @MainActor (String) async throws -> SymmetricKey?
    typealias LiveActivitySnapshot = @MainActor (SettingsMemoryLiveActivitySnapshot) -> Void
    @Published private(set) var state: LoadState = .loading
    @Published private(set) var categories: [SettingsMemoryCategory] = [] { didSet { updateSections() } }
    @Published private(set) var entries: [SettingsMemoryEntry] = [] { didSet { updateSections() } }
    @Published private(set) var isAuthenticated = false { didSet { updateSections() } }
    @Published private(set) var sections: [SettingsMemoryAppSection] = []
    private func updateSections() { sections = SettingsMemoryCatalog.sections(categories: categories, entries: entries, authenticated: isAuthenticated) }
    private let transport: Transport
    private let keyLoader: KeyLoader
    private let environment: TeamWorkspaceEnvironment
    private let teamContext: () -> APIRequestTeamContext
    private let liveActivitySnapshot: LiveActivitySnapshot
    private var context: SettingsMemoryContext?
    private var generation = UUID()
    private var recordsByID: [String: SettingsEncryptedMemoryRecord] = [:]
    private var syncObserver: AnyCancellable?
    private var active = false
    #if DEBUG
    private var usesEditorFixture = false
    #endif

    init(transport: Transport? = nil, keyLoader: KeyLoader? = nil,
         environment: TeamWorkspaceEnvironment = .live,
         teamContext: @escaping () -> APIRequestTeamContext = {
            .init(epoch: TeamWorkspaceContext.shared.contextEpoch, teamID: TeamWorkspaceContext.shared.teamID)
         }, observesSync: Bool = true,
         liveActivitySnapshot: @escaping LiveActivitySnapshot = { UpcomingMemoryLiveActivityBridge.shared.accept($0) }) {
        self.liveActivitySnapshot = liveActivitySnapshot
        self.environment = environment; self.teamContext = teamContext
        self.transport = transport ?? { method, path, data, context in
            if let data {
                return try await APIClient.shared.request(method, path: path, serverProfile: context.server,
                    body: JSONRawBody(data: data), expectedAccountID: context.accountID,
                    expectedScope: context.accountID == nil ? nil : context.scope,
                    expectedTeamContext: context.accountID == nil ? nil : context.team)
            }
            return try await APIClient.shared.request(method, path: path, serverProfile: context.server,
                expectedAccountID: context.accountID,
                expectedScope: context.accountID == nil ? nil : context.scope,
                expectedTeamContext: context.accountID == nil ? nil : context.team)
        }
        self.keyLoader = keyLoader ?? { try await CryptoManager.shared.loadMasterKey(for: $0) }
        if observesSync {
            syncObserver = NotificationCenter.default.publisher(for: .wsSyncEvent).sink { [weak self] _ in
                Task { @MainActor in if self?.active == true { await self?.load() } }
            }
        }
    }
    func cancel() {
        generation = UUID(); context = nil; active = false
        entries = []; recordsByID = [:]; isAuthenticated = false
    }
    private func check(_ context: SettingsMemoryContext, token: UUID) async throws {
        try await context.check(environment: environment, teamContext: teamContext)
        guard generation == token, active else { throw CancellationError() }
    }
    func load() async {
        cancel(); active = true; state = .loading
        let token = generation
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-memory-fixture") || ProcessInfo.processInfo.arguments.contains("--ui-test-memory-editor-fixture") {
            usesEditorFixture = ProcessInfo.processInfo.arguments.contains("--ui-test-memory-editor-fixture")
            categories = usesEditorFixture ? [Self.fixtureCategory] : [Self.fixtureCategory, Self.fixtureSiblingCategory]; isAuthenticated = usesEditorFixture
            entries = usesEditorFixture ? [] : categories.flatMap(\.examples); state = .loaded; return
        }
        #endif
        let pinned = SettingsMemoryContext(accountID: await environment.currentAccountID(), server: environment.serverProfile(),
            scope: environment.scopeGeneration(), team: teamContext())
        context = pinned
        do {
            let data = try await transport(.get, "/v1/apps/metadata?include_unavailable=true", nil, pinned)
            try await check(pinned, token: token)
            categories = try Self.decodeCatalog(data)
            guard let account = pinned.accountID else {
                entries = categories.flatMap(\.examples); state = entries.isEmpty ? .empty : .loaded; return
            }
            isAuthenticated = true
            guard let key = try await keyLoader(account) else { try await check(pinned, token: token); state = .missingKey; return }
            try await check(pinned, token: token)
            let snapshotRevision = SettingsMemoryLiveActivitySnapshot.nextRevision()
            let responseData = try await transport(.get, "/v1/sdk/memories", nil, pinned)
            try await check(pinned, token: token)
            let response = try JSONDecoder().decode(SettingsEncryptedMemoryResponse.self, from: responseData)
            var decoded: [SettingsMemoryEntry] = [], records: [String: SettingsEncryptedMemoryRecord] = [:]
            for record in response.memories {
                let category = SettingsMemoryCatalog.categoryID(appID: record.appId, itemType: record.itemType)
                guard categories.contains(where: { $0.appId == record.appId && $0.categoryId == category }) else { continue }
                let plaintext = try await CryptoManager.shared.decryptContent(base64String: record.encryptedItemJson, key: key)
                try await check(pinned, token: token)
                let fields = try Self.decodePayload(plaintext, fallbackKey: record.itemKey)
                decoded.append(.init(id: record.id, appId: record.appId, categoryId: category, key: fields.key,
                    value: try SettingsMemoryValue.object(fields.value).json(), createdAt: record.createdAt,
                    updatedAt: record.updatedAt, version: record.itemVersion, isExample: false, fields: fields.value))
                records[record.id] = record
            }
            try await check(pinned, token: token)
            entries = decoded.sorted { $0.updatedAt > $1.updatedAt }; recordsByID = records
            state = entries.isEmpty ? .empty : .loaded
            publishLiveActivitySnapshot(context: pinned, revision: snapshotRevision)
        } catch {
            guard generation == token else { return }
            if error is CancellationError { cancel(); return }
            do { try await check(pinned, token: token) } catch { cancel(); return }
            state = .error(AppStrings.error)
            NativeDiagnostics.warning("Memory load failed errorType=\(type(of: error))", category: "settings_memories")
        }
    }
    func entries(in category: SettingsMemoryCategory) -> [SettingsMemoryEntry] {
        entries.filter { $0.appId == category.appId && $0.categoryId == category.categoryId }
    }
    func save(entry: SettingsMemoryEntry?, category: SettingsMemoryCategory, key: String, value: String) async -> Bool {
        guard let parsed = try? SettingsMemoryValue.parse(value), let object = parsed.object else {
            return await save(entry: entry, category: category, key: key, fields: ["value": .string(value)])
        }
        return await save(entry: entry, category: category, key: key, fields: object)
    }
    func save(entry: SettingsMemoryEntry?, category: SettingsMemoryCategory, key: String, fields: [String: SettingsMemoryValue]) async -> Bool {
        guard isAuthenticated, entry?.isExample != true, state != .pending,
              entry == nil || (entry?.appId == category.appId && entry?.categoryId == category.categoryId),
              categories.contains(where: { $0.id == category.id }), !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        let token = generation, now = Int(Date().timeIntervalSince1970)
        let draft = SettingsMemoryEntry(id: entry?.id ?? UUID().uuidString, appId: category.appId, categoryId: category.categoryId,
            key: key, value: (try? SettingsMemoryValue.object(fields).json()) ?? "", createdAt: entry?.createdAt ?? now,
            updatedAt: now, version: (entry?.version ?? 0) + 1, isExample: false, fields: fields)
        #if DEBUG
        if usesEditorFixture { entries.removeAll { $0.id == draft.id }; entries.insert(draft, at: 0); state = .loaded; return true }
        #endif
        guard let context, let account = context.accountID,
              entry == nil || recordsByID[entry!.id] != nil else { return false }
        state = .pending
        do {
            try await check(context, token: token)
            guard let masterKey = try await keyLoader(account) else { throw SettingsMemoryServiceError.missingKey }
            try await check(context, token: token)
            var payload = fields; payload["_original_item_key"] = .string(key); payload["settings_group"] = .string(category.categoryId)
            let encrypted = try await CryptoManager.shared.encryptWithMasterKey(try SettingsMemoryValue.object(payload).json(), masterKey: masterKey)
            try await check(context, token: token)
            let existing = entry.flatMap { recordsByID[$0.id] }
            let record = SettingsEncryptedMemoryRecord(id: draft.id, appId: category.appId,
                itemKey: existing?.itemKey ?? Self.hash("\(category.appId)-\(key)-\(UUID().uuidString)"), itemType: category.categoryId,
                encryptedItemJson: encrypted, encryptedAppKey: existing?.encryptedAppKey ?? "", createdAt: draft.createdAt,
                updatedAt: now, itemVersion: draft.version)
            let recordData = try JSONEncoder().encode(record)
            let object = try JSONSerialization.jsonObject(with: recordData)
            let requestData = try JSONSerialization.data(withJSONObject: ["entry": object])
            _ = try await transport(.post, "/v1/sdk/memories", requestData, context)
            try await check(context, token: token)
            recordsByID[record.id] = record; entries.removeAll { $0.id == draft.id }; entries.insert(draft, at: 0); state = .loaded
            publishLiveActivitySnapshot(context: context, revision: SettingsMemoryLiveActivitySnapshot.nextRevision(), change: .upsert(draft))
            return true
        } catch { await handle(error, token: token, context: context); return false }
    }
    @discardableResult
    func delete(_ entry: SettingsMemoryEntry) async -> Bool {
        guard isAuthenticated, !entry.isExample, state != .pending else { return false }
        #if DEBUG
        if usesEditorFixture { entries.removeAll { $0.id == entry.id }; state = entries.isEmpty ? .empty : .loaded; return true }
        #endif
        guard let context, recordsByID[entry.id] != nil else { return false }
        let token = generation; state = .pending
        do {
            try await check(context, token: token)
            let id = entry.id.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? entry.id
            _ = try await transport(.delete, "/v1/sdk/memories/\(id)", nil, context)
            try await check(context, token: token)
            recordsByID[entry.id] = nil; entries.removeAll { $0.id == entry.id }; state = entries.isEmpty ? .empty : .loaded
            publishLiveActivitySnapshot(context: context, revision: SettingsMemoryLiveActivitySnapshot.nextRevision(), change: .removed(entry.id))
            return true
        } catch { await handle(error, token: token, context: context); return false }
    }
    private func handle(_ error: Error, token: UUID, context: SettingsMemoryContext) async {
        guard generation == token else { return }
        if error is CancellationError { cancel(); return }
        do { try await check(context, token: token) } catch { if generation == token { cancel() }; return }
        state = error.localizedDescription.contains("409") ? .conflict : .error(AppStrings.error)
        NativeDiagnostics.warning("Memory mutation failed errorType=\(type(of: error))", category: "settings_memories")
    }
    private func publishLiveActivitySnapshot(context: SettingsMemoryContext, revision: UInt64,
                                            change: SettingsMemoryLiveActivitySnapshot.Change = .full) {
        guard isAuthenticated, let scope = UpcomingMemorySnapshotScope(context) else { return }
        liveActivitySnapshot(.init(scope: scope, entries: entries, revision: revision, change: change))
    }
    static func decodePayload(_ plaintext: String, fallbackKey: String) throws -> (key: String, value: [String: SettingsMemoryValue]) {
        guard var fields = try SettingsMemoryValue.parse(plaintext).object else { throw SettingsMemoryServiceError.invalidPayload }
        let key = fields.removeValue(forKey: "_original_item_key")?.string ?? fallbackKey
        fields.removeValue(forKey: "settings_group")
        return (key, fields)
    }
    static func decodeCatalog(_ data: Data) throws -> [SettingsMemoryCategory] {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any], let apps = root["apps"] as? [String: [String: Any]] else { throw SettingsMemoryServiceError.invalidPayload }
        var orderReader = SettingsMemoryMetadataOrder(data: data)
        let order = orderReader.read()
        return (order["apps"] ?? apps.keys.sorted()).flatMap { appID -> [SettingsMemoryCategory] in
            guard appID != "ai", let app = apps[appID], let categories = app["settings_and_memories"] as? [[String: Any]] else { return [] }
            @MainActor func translated(_ key: String, fallback: String, source: [String: Any]) -> String {
                if let translation = source[key] as? String { return AppStrings.localized(translation) }
                return source["name"] as? String ?? fallback
            }
            let appName = translated("name_translation_key", fallback: appID, source: app)
            let appIcon = SettingsMemoryCatalog.icon(app["icon_image"] as? String, fallback: appID)
            return categories.enumerated().compactMap { categoryIndex, raw in
                guard let categoryID = raw["id"] as? String else { return nil }
                let name = translated("name_translation_key", fallback: categoryID, source: raw)
                let schema = (raw["schema_definition"] as? [String: Any]).map { SettingsMemorySchema(raw: $0, path: ["apps", appID, "settings_and_memories", String(categoryIndex), "schema_definition"], order: order) }
                let full = raw["example_entries"] as? [[String: Any]] ?? []
                let keys = raw["example_translation_keys"] as? [String] ?? []
                let examples = (0..<max(full.count, keys.count)).map { index -> SettingsMemoryEntry in
                    var fields: [String: SettingsMemoryValue] = [:]
                    if index < full.count {
                        for (key, rawValue) in full[index] {
                            if let string = rawValue as? String, string.contains("."), !string.contains(" "), !string.hasPrefix("http") {
                                fields[key] = .string(AppStrings.localized(string))
                            } else { fields[key] = SettingsMemoryValue.from(rawValue) }
                        }
                    }
                    let title = schema?.titleField.flatMap { fields[$0]?.display } ?? (index < keys.count ? AppStrings.localized(keys[index]) : name)
                    return .init(id: "example_\(index)", appId: appID, categoryId: categoryID, key: title,
                        value: (try? SettingsMemoryValue.object(fields).json()) ?? title, createdAt: 0, updatedAt: 0, version: 0, isExample: true, fields: fields)
                }
                return .init(appId: appID, appName: appName, categoryId: categoryID, categoryName: name,
                    iconName: SettingsMemoryCatalog.icon(raw["icon_image"] as? String, fallback: appIcon), examples: examples,
                    description: (raw["description_translation_key"] as? String).map(AppStrings.localized) ?? "", appIconName: appIcon, schema: schema)
            }
        }
    }
    private static func hash(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
    #if DEBUG
    static let fixtureCategory = SettingsMemoryCategory(appId: "travel", appName: AppStrings.localized("apps.travel"), categoryId: "preferred_activities",
        categoryName: AppStrings.localized("app_settings_memories.travel.preferred_activities"), iconName: "planning",
        examples: [.init(id: "example-travel-preferred-activities-0", appId: "travel", categoryId: "preferred_activities", key: "Beach walks",
            value: "Beach walks", createdAt: 0, updatedAt: 0, version: 0, isExample: true, fields: ["name": .string("Beach walks")])],
        description: "Activities and experiences you enjoy at destinations", appIconName: "travel",
        schema: .init(raw: ["type": "object", "properties": ["name": ["type": "string", "is_title": true]], "required": ["name"]]))
    static let fixtureSiblingCategory = SettingsMemoryCategory(appId: "travel", appName: AppStrings.localized("apps.travel"), categoryId: "preferred_airlines",
        categoryName: AppStrings.localized("app_settings_memories.travel.preferred_airlines"), iconName: "travel",
        examples: [.init(id: "example-airlines-synthetic", appId: "travel", categoryId: "preferred_airlines", key: "Synthetic airline",
            value: "Synthetic airline", createdAt: 0, updatedAt: 0, version: 0, isExample: true, fields: ["name": .string("Synthetic airline")])],
        description: "Airlines you prefer", appIconName: "travel", schema: .init(raw: ["properties": ["name": ["type": "string", "is_title": true]]]))
    #endif
}

enum SettingsMemoryServiceError: Error { case missingKey, invalidPayload }
