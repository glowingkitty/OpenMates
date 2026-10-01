// Web source: frontend/packages/ui/src/components/settings/SettingsMemoriesHub.svelte,
// AppSettingsMemoriesEntryDetail.svelte; stores/appSettingsMemoriesStore.ts.
// Synthetic metadata and ephemeral keys only; no account, disk, or network mutations.
import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class SettingsMemoryContractsTests: XCTestCase {
    private func category(_ app: String, _ id: String, examples: Bool = false, schema: SettingsMemorySchema? = nil) -> SettingsMemoryCategory {
        .init(appId: app, appName: app, categoryId: id, categoryName: id, iconName: "memory",
            examples: examples ? [entry(app, id, time: 0, example: true)] : [], schema: schema)
    }
    private func entry(_ app: String, _ id: String, time: Int, example: Bool = false) -> SettingsMemoryEntry {
        .init(id: "\(app)-\(id)-\(time)", appId: app, categoryId: id, key: id, value: "{}", createdAt: 1, updatedAt: time, version: 1, isExample: example)
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testHubGroupsNonemptyCategoriesByMostRecentUpdateAndPreservesGuestMetadataOrder() {
        let categories = [category("books", "favorites", examples: true), category("travel", "trips", examples: true), category("books", "reading"), category("code", "empty")]
        let entries = [entry("books", "favorites", time: 5), entry("travel", "trips", time: 20), entry("books", "reading", time: 30)]
        let sections = SettingsMemoryCatalog.sections(categories: categories, entries: entries, authenticated: true)
        XCTAssertEqual(sections.map(\.appId), ["books", "travel"])
        XCTAssertEqual(sections[0].categories.map(\.categoryId), ["reading", "favorites"])
        XCTAssertEqual(SettingsMemoryCatalog.sections(categories: categories, entries: [], authenticated: false).map(\.appId), ["books", "travel"])
        XCTAssertTrue(SettingsMemoryCatalog.sections(categories: categories, entries: [], authenticated: true).isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testLegacyCategoryMigrationAndCanonicalDetailReturn() {
        XCTAssertEqual(SettingsMemoryCatalog.categoryID(appID: "travel", itemType: "interests"), "preferred_activities")
        XCTAssertEqual(SettingsMemoryCatalog.categoryID(appID: "code", itemType: "interests"), "interests")
        let route = SettingsMemoryRoute(path: "apps/travel/settings_memories/interests/entry/synthetic/edit")
        XCTAssertEqual(route, .editor("travel", "preferred_activities", "synthetic"))
        XCTAssertEqual(route.parent, .entry("travel", "preferred_activities", "synthetic"))
        XCTAssertEqual(route.parent.parent, .category("travel", "preferred_activities"))
        XCTAssertEqual(route.parent.parent.parent, .hub)
        XCTAssertEqual(SettingsMemoryRoute(path: "apps/travel/settings_memories/preferred_activities/create").parent, .category("travel", "preferred_activities"))
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity,settings-ui.navigation.parent-return
    func testMemoryDeepLinksPermitPublicExamplesAndFencePrivateEditors() {
        for path in ["apps/books/settings_memories/favorite_books", "apps/books/settings_memories/favorite_books/entry/example_0", "apps/all"] {
            let route = SettingsDeepLinkRoute(path)
            XCTAssertTrue(route.hasNativeChild); XCTAssertTrue(route.canOpen(authenticated: false, admin: false))
        }
        for path in ["apps/books/settings_memories/favorite_books/create", "apps/books/settings_memories/favorite_books/entry/private", "apps/books/settings_memories/favorite_books/entry/example_0/edit"] {
            let route = SettingsDeepLinkRoute(path)
            XCTAssertTrue(route.hasNativeChild); XCTAssertFalse(route.canOpen(authenticated: false, admin: false))
            XCTAssertTrue(route.canOpen(authenticated: true, admin: false))
        }
        for path in ["apps/books", "apps/books/settings_memories/favorite_books/noop", "apps/books/settings_memories/favorite_books/entry", "apps/books/settings_memories/favorite_books/entry/example_0/edit/extra"] {
            XCTAssertFalse(SettingsDeepLinkRoute(path).hasNativeChild)
        }
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity,settings-ui.navigation.parent-return
    func testCategorySiblingNavigationStaysWithinAppMetadataOrder() {
        let first = category("books", "favorites"), middle = category("books", "reading"), last = category("books", "read")
        let categories = [first, category("travel", "trips"), middle, last]
        let initial = SettingsMemoryCatalog.siblings(categories: categories, selected: first)
        XCTAssertNil(initial.previous); XCTAssertEqual(initial.next?.id, middle.id)
        let neighbors = SettingsMemoryCatalog.siblings(categories: categories, selected: middle)
        XCTAssertEqual(neighbors.previous?.id, first.id); XCTAssertEqual(neighbors.next?.id, last.id)
        let ending = SettingsMemoryCatalog.siblings(categories: categories, selected: last)
        XCTAssertEqual(ending.previous?.id, middle.id); XCTAssertNil(ending.next)
        let navigation = SettingsChildBannerNavigation(title: "Memory", description: "", onBack: {})
        XCTAssertNil(navigation.previous); XCTAssertNil(navigation.next)
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testTypedEditorPreservesPayloadTypesAndAutoGeneratedValues() throws {
        let schema = SettingsMemorySchema(raw: ["properties": [
            "name": ["type": "string", "is_title": true], "count": ["type": "integer", "minimum": 1, "maximum": 5],
            "enabled": ["type": "boolean"], "level": ["type": "string", "enum": ["basic", "advanced"]],
            "options": ["type": "object", "required": ["label"], "properties": ["label": ["type": "string"]]],
            "tags": ["type": "array", "items": ["type": "string"]], "created_at": ["type": "integer", "auto_generated": true]],
            "required": ["name", "created_at"]])
        var draft = SettingsMemoryDraft(category: category("code", "tech", schema: schema), entry: nil)
        draft.inputs = ["name": "Swift", "count": "3", "enabled": "false", "level": "advanced", "options": "{\"label\":\"safe\"}", "tags": "[\"one\",\"two\"]"]
        let payload = try draft.payload(now: 123)
        XCTAssertEqual(payload.key, "tech.Swift")
        XCTAssertEqual(payload.fields["count"], .number(3)); XCTAssertEqual(payload.fields["enabled"], .bool(false))
        XCTAssertEqual(payload.fields["created_at"], .number(123)); XCTAssertEqual(payload.fields["tags"], .array([.string("one"), .string("two")]))
        for (field, invalid) in [("count", "6"), ("count", "1.5"), ("level", "forbidden"), ("options", "{}"), ("tags", "[3]"), ("name", String(repeating: "x", count: 101))] {
            let previous = draft.inputs[field]; draft.inputs[field] = invalid
            XCTAssertThrowsError(try draft.payload(), "Invalid \(field) must be rejected")
            draft.inputs[field] = previous
        }
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testEditingClearedOptionalFieldsRemovesOldValuesAndPreservesNoneditableFields() throws {
        let schema = SettingsMemorySchema(raw: ["properties": [
            "name": ["type": "string", "is_title": true], "notes": ["type": "string", "multiline": true],
            "details": ["type": "string", "multiline": true], "created_at": ["type": "integer", "auto_generated": true],
            "embed_id": ["type": "string"]], "required": ["name"]])
        let original = SettingsMemoryEntry(id: "synthetic", appId: "health", categoryId: "appointments", key: "appointments.Synthetic",
            value: "{}", createdAt: 1, updatedAt: 2, version: 1, isExample: false,
            fields: ["name": .string("Synthetic"), "notes": .string("Old synthetic notes"), "details": .string("Old synthetic details"),
                "created_at": .number(1), "embed_id": .string("synthetic-embed"), "unknown_field": .string("Preserved")])
        var draft = SettingsMemoryDraft(category: category("health", "appointments", schema: schema), entry: original)
        draft.inputs["notes"] = ""
        draft.inputs["details"] = " \n\t "
        let payload = try draft.payload(now: 3)
        XCTAssertNil(payload.fields["notes"]); XCTAssertNil(payload.fields["details"])
        XCTAssertEqual(payload.fields["name"], .string("Synthetic"))
        XCTAssertEqual(payload.fields["created_at"], .number(1))
        XCTAssertEqual(payload.fields["embed_id"], .string("synthetic-embed"))
        XCTAssertEqual(payload.fields["unknown_field"], .string("Preserved"))
        draft.inputs["name"] = " "
        XCTAssertThrowsError(try draft.payload(now: 3), "Clearing a required field must still fail validation")
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testCatalogUsesTranslatedMetadataIconsAndFullReadOnlyExamples() throws {
        let metadata: [String: Any] = ["apps": ["travel": ["id": "travel", "name_translation_key": "apps.travel", "icon_image": "travel.svg",
            "settings_and_memories": [["id": "preferred_activities", "name_translation_key": "app_settings_memories.travel.preferred_activities", "icon_image": "planning.svg",
                "schema_definition": ["properties": ["name": ["type": "string", "is_title": true]]], "example_entries": [["name": "Beach walks", "enabled": true]]]]]]]
        let decoded = try SettingsMemoryService.decodeCatalog(JSONSerialization.data(withJSONObject: metadata))
        XCTAssertEqual(decoded.first?.iconName, "planning"); XCTAssertEqual(decoded.first?.appIconName, "travel")
        XCTAssertEqual(decoded.first?.appName, AppStrings.localized("apps.travel"))
        XCTAssertEqual(decoded.first?.examples.first?.fields["enabled"], .bool(true))
        XCTAssertEqual(decoded.first?.examples.first?.isExample, true)
        XCTAssertEqual(SettingsMemoryCatalog.icon("coding.svg", fallback: "code"), "code")
    }
    private var metadata: Data { Data("{\"apps\":{\"travel\":{\"id\":\"travel\",\"settings_and_memories\":[{\"id\":\"preferred_activities\",\"schema_definition\":{\"properties\":{\"name\":{\"type\":\"string\"}}}}]}}}".utf8) }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testEncryptedCRUDAndMigrationNeverExposePlaintextKeysInTransport() async throws {
        let key = SymmetricKey(size: .bits256), scope = UUID(), server = ServerProfile.current()
        let ciphertext = try await CryptoManager.shared.encryptWithMasterKey("{\"_original_item_key\":\"private title\",\"settings_group\":\"interests\",\"name\":\"Beach walks\"}", masterKey: key)
        let record = SettingsEncryptedMemoryRecord(id: "synthetic", appId: "travel", itemKey: String(repeating: "a", count: 64), itemType: "interests",
            encryptedItemJson: ciphertext, encryptedAppKey: "", createdAt: 1, updatedAt: 2, itemVersion: 4)
        let records = try JSONSerialization.data(withJSONObject: ["memories": JSONSerialization.jsonObject(with: JSONEncoder().encode([record]))])
        var sent: SettingsEncryptedMemoryRecord?
        let service = SettingsMemoryService(transport: { method, path, body, _ in
            if path.contains("metadata") { return self.metadata }
            if method == .get { return records }
            if let body, let object = try JSONSerialization.jsonObject(with: body) as? [String: Any], let entry = object["entry"] {
                sent = try JSONDecoder().decode(SettingsEncryptedMemoryRecord.self, from: JSONSerialization.data(withJSONObject: entry))
                XCTAssertFalse(String(decoding: body, as: UTF8.self).contains("private title"))
            }
            return Data("{}".utf8)
        }, keyLoader: { _ in key }, environment: .init(currentAccountID: { "synthetic-account" }, scopeGeneration: { scope }, serverProfile: { server }),
           teamContext: { .init(epoch: 0, teamID: nil) }, observesSync: false)
        await service.load()
        XCTAssertEqual(service.entries.first?.categoryId, "preferred_activities")
        XCTAssertEqual(service.entries.first?.key, "private title")
        let saved = await service.save(entry: service.entries.first, category: try XCTUnwrap(service.categories.first), key: "private title", fields: ["name": .string("Updated activity")])
        XCTAssertTrue(saved); XCTAssertEqual(sent?.itemKey, record.itemKey); XCTAssertEqual(sent?.itemVersion, 5)
        let decrypted = try await CryptoManager.shared.decryptContent(base64String: try XCTUnwrap(sent?.encryptedItemJson), key: key)
        XCTAssertEqual(try SettingsMemoryService.decodePayload(decrypted, fallbackKey: "").value["name"], .string("Updated activity"))
        let deleted = await service.delete(try XCTUnwrap(service.entries.first)); XCTAssertTrue(deleted); XCTAssertTrue(service.entries.isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testStaleLoadClearsPlaintextAndGuestWritesAreRejected() async throws {
        let scope = UUID(), server = ServerProfile.current(); var account: String? = "first"
        let service = SettingsMemoryService(transport: { _, _, _, _ in account = "second"; return self.metadata },
            environment: .init(currentAccountID: { account }, scopeGeneration: { scope }, serverProfile: { server }),
            teamContext: { .init(epoch: 0, teamID: nil) }, observesSync: false)
        await service.load(); XCTAssertTrue(service.entries.isEmpty); XCTAssertFalse(service.isAuthenticated)
        let guestCategory = category("travel", "preferred_activities", examples: true)
        let saved = await service.save(entry: guestCategory.examples.first, category: guestCategory, key: "example", fields: ["name": .string("example")])
        XCTAssertFalse(saved); let deleted = await service.delete(guestCategory.examples[0]); XCTAssertFalse(deleted)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testScopeServerAndWorkspaceSwitchesInvalidateCapturedContext() async {
        var scope = UUID(), server = ServerProfile.production, epoch: UInt64 = 0
        var teamID: String? = nil
        let environment = TeamWorkspaceEnvironment(currentAccountID: { "synthetic-account" }, scopeGeneration: { scope }, serverProfile: { server })
        func context() -> SettingsMemoryContext { .init(accountID: "synthetic-account", server: server, scope: scope, team: .init(epoch: epoch, teamID: teamID)) }
        let pinned = context()
        scope = UUID()
        do { try await pinned.check(environment: environment, teamContext: { .init(epoch: epoch, teamID: teamID) }); XCTFail("Scope switch must fence memory access") } catch { XCTAssertTrue(error is CancellationError) }
        let beforeServer = context(); server = .development
        do { try await beforeServer.check(environment: environment, teamContext: { .init(epoch: epoch, teamID: teamID) }); XCTFail("Server switch must fence memory access") } catch { XCTAssertTrue(error is CancellationError) }
        let beforeTeam = context(); epoch = 1; teamID = "synthetic-team"
        do { try await beforeTeam.check(environment: environment, teamContext: { .init(epoch: epoch, teamID: teamID) }); XCTFail("Workspace switch must fence memory access") } catch { XCTAssertTrue(error is CancellationError) }
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testMetadataJSONOrderIsRetainedForGuestSectionsAndEditorFields() throws {
        let metadata = Data("{\"apps\":{\"travel\":{\"settings_and_memories\":[{\"id\":\"preferred_activities\",\"schema_definition\":{\"properties\":{\"z_title\":{\"type\":\"string\"},\"a_note\":{\"type\":\"string\"}}}}]},\"books\":{\"settings_and_memories\":[{\"id\":\"favorites\"}]}}}".utf8)
        let categories = try SettingsMemoryService.decodeCatalog(metadata)
        XCTAssertEqual(categories.map(\.appId), ["travel", "books"])
        XCTAssertEqual(categories.first?.schema?.fields.map(\.name), ["z_title", "a_note"])
    }
}
