// Detached, real-crypto key and routing-state coverage. No server writes.
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class EmbedShareSettingsParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,chats.surface.semantic-parity
    func testShareTargetRetainsSelectedChildAndOwningChat() throws {
        let parent = record("parent")
        let child = record("child", parent: parent.id)
        let target = EmbedShareSettingsTarget(embed: child, chatId: "owner-chat",
            allEmbedRecords: [parent.id: parent, child.id: child])
        let key = SymmetricKey(size: .bits256)
        let context = target.context(key: key)
        XCTAssertEqual(context.contentType, .embed)
        XCTAssertEqual(context.id, child.id)
        XCTAssertEqual(context.chatId, "owner-chat")
        XCTAssertEqual(context.path, "share/embed")
        XCTAssertEqual(context.keyField, "embed_encryption_key")
        XCTAssertEqual(context.title, "Title child")
        XCTAssertEqual(context.summary, "Summary child")
        XCTAssertEqual(target.allEmbedRecords[child.id]?.parentEmbedId, parent.id)
        XCTAssertNotEqual(target.requestID,
            EmbedShareSettingsTarget(embed: child, chatId: "owner-chat", allEmbedRecords: [:]).requestID)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testShareSettingsResolvesActualParentWrappedKeyForSelectedChild() async throws {
        let chatId = "share-key-test-\(UUID())"
        let parent = record("parent-\(UUID())")
        let child = record("child-\(UUID())", parent: parent.id)
        let chatKey = SymmetricKey(size: .bits256)
        let embedKey = SymmetricKey(size: .bits256)
        ChatKeyManager.shared.setKey(chatKey, for: chatId)
        defer {
            ChatKeyManager.shared.removeKey(for: chatId)
            EmbedKeyManager.shared.removeKeys(for: chatId)
        }
        let wrapper = try await CryptoManager.shared.wrapChatKey(embedKey, masterKey: chatKey)
        EmbedKeyManager.shared.store([EmbedKeyRecord(hashedEmbedId: digest(parent.id), keyType: "chat",
            hashedChatId: digest(chatId), encryptedEmbedKey: wrapper)], source: "share-settings-test")
        let target = EmbedShareSettingsTarget(embed: child, chatId: chatId,
            allEmbedRecords: [parent.id: parent, child.id: child])
        let model = EmbedShareSettingsModel()
        await model.load(target) { request in
            await EmbedKeyManager.shared.key(for: request.embed, chatId: request.chatId, allEmbeds: request.allEmbedRecords)
        }
        let context = try XCTUnwrap(model.context)
        XCTAssertEqual(context.id, child.id)
        XCTAssertEqual(context.key.withUnsafeBytes { Data($0) }, embedKey.withUnsafeBytes { Data($0) })
        XCTAssertFalse(model.failed)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing
    func testOldKeyResolutionCannotReplaceNewShareTarget() async throws {
        let model = EmbedShareSettingsModel()
        let first = target("first")
        let second = target("second")
        let secondKey = SymmetricKey(size: .bits256)
        var suspended: CheckedContinuation<SymmetricKey?, Never>?
        let started = expectation(description: "first key resolution suspended")
        let pending = Task {
            await model.load(first) { _ in
                await withCheckedContinuation { continuation in suspended = continuation; started.fulfill() }
            }
        }
        await fulfillment(of: [started], timeout: 2)
        await model.load(second) { _ in secondKey }
        suspended?.resume(returning: SymmetricKey(size: .bits256))
        await pending.value
        XCTAssertEqual(model.context?.id, second.id)
        XCTAssertEqual(model.context?.key.withUnsafeBytes { Data($0) }, secondKey.withUnsafeBytes { Data($0) })
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.parent-return
    func testCloseInvalidatesPendingKeyAndMissingKeyShowsError() async {
        let model = EmbedShareSettingsModel()
        var suspended: CheckedContinuation<SymmetricKey?, Never>?
        let started = expectation(description: "key resolution suspended")
        let pending = Task {
            await model.load(target("closed")) { _ in
                await withCheckedContinuation { continuation in suspended = continuation; started.fulfill() }
            }
        }
        await fulfillment(of: [started], timeout: 2)
        model.clear()
        suspended?.resume(returning: SymmetricKey(size: .bits256))
        await pending.value
        XCTAssertNil(model.context)
        XCTAssertFalse(model.failed)
        await model.load(target("missing")) { _ in nil }
        XCTAssertNil(model.context)
        XCTAssertTrue(model.failed)
    }

    private func target(_ id: String) -> EmbedShareSettingsTarget {
        EmbedShareSettingsTarget(embed: record(id), chatId: "owner-chat", allEmbedRecords: [:])
    }
    private func record(_ id: String, parent: String? = nil) -> EmbedRecord {
        EmbedRecord(id: id, type: "web-website", status: .finished,
            data: .raw(["title": AnyCodable("Title \(id)"), "description": AnyCodable("Summary \(id)")]),
            parentEmbedId: parent, appId: "web", skillId: "search", embedIds: nil, createdAt: nil)
    }
    private func digest(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
}
