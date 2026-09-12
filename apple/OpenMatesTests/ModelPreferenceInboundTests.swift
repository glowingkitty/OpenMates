import XCTest
@testable import OpenMates
@MainActor final class ModelPreferenceInboundTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testBackgroundChatPersistsAndStagedIntentSurvivesOtherClientUpdate() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let repository = ModelPreferenceEncryptedRepository(directory: directory)
        let connection = ModelPreferenceConnection(server: "dev", userID: "fixture", socketGeneration: 1)
        let coordinator = ModelPreferenceInboundCoordinator(repository: repository, current: { connection }, ownsChat: { $0 == "chat" })
        let scope = ModelPreferenceScope(server: "dev", userID: "fixture", chatID: "chat")
        var emissions = 0
        _ = coordinator.subscribe { _, _ in emissions += 1 }
        try coordinator.receive(type: "chat_model_preference_synced", fields: fields("remote", 2), generation: 1)
        XCTAssertEqual(try repository.read(scope)?.ciphertext, "remote")
        XCTAssertEqual(emissions, 1)
        try repository.write(.init(ciphertext: "pending", version: 3, pendingExpectedVersion: 2), scope: scope)
        try coordinator.receive(type: "chat_model_preference_synced", fields: fields("other-client", 4), generation: 1)
        XCTAssertEqual(try repository.read(scope)?.ciphertext, "pending")
        XCTAssertEqual(emissions, 1)
        try coordinator.receive(type: "chat_model_preference_synced", fields: fields("pending", 5), generation: 1)
        XCTAssertNil(try repository.read(scope)?.pendingExpectedVersion)
        XCTAssertEqual(emissions, 2)
    }
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
    func testOldSocketAndUnownedChatCannotPopulateAccountCache() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let repository = ModelPreferenceEncryptedRepository(directory: directory)
        let coordinator = ModelPreferenceInboundCoordinator(repository: repository,
            current: { .init(server: "dev", userID: "fixture", socketGeneration: 2) }, ownsChat: { _ in false })
        try coordinator.receive(type: "chat_model_preference_synced", fields: fields("ciphertext", 1), generation: 1)
        try coordinator.receive(type: "chat_model_preference_synced", fields: fields("ciphertext", 1), generation: 2)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
    }
    private func fields(_ ciphertext: String, _ version: Int) -> [String: Any] {
        ["chat_id": "chat", "preference": ["encrypted_selected_ai_model": ciphertext, "preference_v": version]]
    }
}
