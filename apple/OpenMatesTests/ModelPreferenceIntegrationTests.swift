// PRIVATE: authored, not registered/run. Requires all proposed production files.
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor final class ModelPreferenceIntegrationTests: XCTestCase {
    private let scope = ModelPreferenceScope(server: "https://dev.invalid", userID: "owner", chatID: "saved")
    private func catalog() -> ModelRoutingCatalog {
        .init(entries: [.init(provider: "provider", modelID: "model", skill: "ai.ask", servers: ["server"])])
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testDraftPromotionWritesOnceAndIncognitoNeverPersists() async throws {
        let fake = ChatModelPreferenceServiceTests.Fake()
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        let controller = ComposerModelPreferenceController(service: service, catalog: catalog)
        try await controller.activate(.draft(server: scope.server, userID: scope.userID, draftID: "draft"))
        try await controller.select("provider/model")
        let draftText = try await controller.textForSend("Hello")
        XCTAssertEqual(draftText, "@ai-model:model:provider Hello")
        XCTAssertTrue(fake.local.isEmpty)
        XCTAssertTrue(fake.expected.isEmpty)
        try await controller.promoteDraft(draftID: "draft", to: scope)
        try await controller.promoteDraft(draftID: "draft", to: scope)
        XCTAssertEqual(fake.expected.count, 1)
        try await controller.activate(.incognito(server: scope.server, userID: scope.userID, chatID: "incognito:test"))
        try await controller.select("provider/model")
        XCTAssertEqual(fake.expected.count, 1)
        XCTAssertEqual(fake.local.count, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testForeignDraftCannotBePromotedToAnotherAccountOrServer() async throws {
        let fake = ChatModelPreferenceServiceTests.Fake()
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        let controller = ComposerModelPreferenceController(service: service, catalog: catalog)
        try await controller.activate(.draft(server: scope.server, userID: scope.userID, draftID: "draft"))
        let foreign = ModelPreferenceScope(server: "https://other.invalid", userID: scope.userID, chatID: "saved")
        do { try await controller.promoteDraft(draftID: "draft", to: foreign); XCTFail("Expected scope mismatch") }
        catch { XCTAssertEqual(error as? ModelPreferenceFailure, .staleContext) }
        XCTAssertTrue(fake.local.isEmpty)
        XCTAssertTrue(fake.expected.isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testEncryptedRepositoryRestartsWithPendingIntentAndSeparatesAccountAndServer() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = ModelPreferenceEncryptedRepository(directory: directory)
        let record = EncryptedModelPreference(ciphertext: "synthetic-ciphertext", version: 3, pendingExpectedVersion: 2)
        try first.write(record, scope: scope)
        let restarted = ModelPreferenceEncryptedRepository(directory: directory)
        XCTAssertEqual(try restarted.read(scope), record)
        XCTAssertNil(try restarted.read(.init(server: scope.server, userID: "another", chatID: scope.chatID)))
        XCTAssertNil(try restarted.read(.init(server: "https://another.invalid", userID: scope.userID, chatID: scope.chatID)))
        let file = try XCTUnwrap(FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil).first)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
        XCTAssertEqual(Set(object.keys), Set(["ciphertext", "version", "pendingExpectedVersion"]))
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testWireAdapterSendsExactWebFieldsAndOmitsLocalPendingMarker() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let connection = ModelPreferenceConnection(server: scope.server, userID: scope.userID, socketGeneration: 3)
        let adapter = ModelPreferenceNativeAdapters(repository: .init(directory: directory),
            currentConnection: { connection }, request: { bound, type, payload, events, timeout in
                XCTAssertEqual(bound, connection)
                XCTAssertEqual(type, "update_chat_model_preference")
                XCTAssertEqual(Set(payload.keys), Set(["chat_id", "encrypted_selected_ai_model", "expected_preference_v"]))
                XCTAssertEqual(payload["expected_preference_v"] as? Int, 2)
                XCTAssertTrue(events.contains("chat_model_preference_conflict"))
                XCTAssertEqual(timeout, .seconds(10))
                return .init(type: "chat_model_preference_updated", fields: [
                    "chat_id": self.scope.chatID,
                    "preference": ["encrypted_selected_ai_model": "ciphertext", "preference_v": 3],
                ])
            }, masterKey: { _ in SymmetricKey(data: Data(repeating: 1, count: 32)) })
        let accepted = try await adapter.compareAndSet(.init(ciphertext: "ciphertext", version: 3, pendingExpectedVersion: 2),
                                                      expected: 2, scope: scope)
        XCTAssertEqual(accepted?.version, 3)
        XCTAssertNil(accepted?.pendingExpectedVersion)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testFormatDPreferenceRoundTripsUsingTheExistingMasterKeyAPI() async throws {
        let key = SymmetricKey(data: Data(repeating: 2, count: 32))
        let plaintext = #"{"mode":"exact","model":"provider/model"}"#
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey(plaintext, masterKey: key)
        let bytes = try XCTUnwrap(Data(base64Encoded: encrypted))
        XCTAssertEqual(bytes.count, plaintext.utf8.count + 12 + 16, "Format D adds IV and tag without Format A magic/fingerprint")
        let decrypted = try await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
        XCTAssertEqual(decrypted, plaintext)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testWelcomePromotionStagesBeforeNavigationAndSavedHostReplaysOriginalIntentOnce() async throws {
        let fake = ChatModelPreferenceServiceTests.Fake()
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        let controller = ComposerModelPreferenceController(service: service, catalog: catalog)
        try await controller.activate(.draft(server: scope.server, userID: scope.userID, draftID: "composer-session"))
        try await controller.select("provider/model")
        try await controller.promoteDraft(draftID: "composer-session", to: scope, waitForRemote: false)
        let pending = try XCTUnwrap(fake.local[scope])
        XCTAssertEqual(pending.pendingExpectedVersion, 0)
        XCTAssertTrue(fake.expected.isEmpty, "Welcome navigation must not await remote chat materialization")
        controller.invalidate()
        let saved = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        saved.activate(scope)
        let restored = try await saved.restore()
        XCTAssertEqual(restored, "provider/model")
        XCTAssertEqual(fake.expected, [0])
        XCTAssertEqual(fake.local[scope]?.ciphertext, pending.ciphertext)
        XCTAssertNil(fake.local[scope]?.pendingExpectedVersion)
    }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testLateSelectionFailureCannotPublishAnErrorIntoReplacementDraft() async throws {
        let fake = ChatModelPreferenceServiceTests.Fake()
        let service = ChatModelPreferenceService(adapters: fake, catalog: catalog, notify: { _ in })
        let controller = ComposerModelPreferenceController(service: service, catalog: catalog)
        try await controller.activate(.saved(scope))
        let started = expectation(description: "selection CAS suspended")
        var release: CheckedContinuation<Void, Never>?
        fake.onCompare = { await withCheckedContinuation { release = $0; started.fulfill() } }
        let pending = Task { await controller.selectVisible("provider/model") }
        await fulfillment(of: [started], timeout: 2)
        controller.invalidate()
        try await controller.activate(.draft(server: "other-server", userID: "other-user", draftID: "other-draft"))
        release?.resume(); await pending.value
        XCTAssertNil(controller.visibleError)
        XCTAssertEqual(controller.selection, "auto")
        XCTAssertTrue(controller.isReady)
    }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testRoutingSendOwnershipRejectsChangedChatAccountAndServer() {
        let generation = UUID()
        let owner = ComposerModelSendOwnership(server: "dev", accountGeneration: generation, chatID: "chat-a")
        XCTAssertTrue(owner.matches(server: "dev", accountGeneration: generation, chatID: "chat-a"))
        XCTAssertFalse(owner.matches(server: "dev", accountGeneration: generation, chatID: "chat-b"))
        XCTAssertFalse(owner.matches(server: "dev", accountGeneration: UUID(), chatID: "chat-a"))
        XCTAssertFalse(owner.matches(server: "other", accountGeneration: generation, chatID: "chat-a"))
        XCTAssertFalse(owner.matches(server: "dev", accountGeneration: generation, chatID: nil))
    }

}
