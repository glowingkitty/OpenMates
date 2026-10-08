// Cryptographic failure and media compatibility coverage for Apple clients.
// Verifies native failures stop before returning zero or deterministic secrets.
// Freezes legacy external-nonce and explicit nonce-prefixed media readers.
// Unknown media encryption markers must fail closed without trial decryption.

import CryptoKit
import XCTest
@testable import OpenMates

final class CryptoFailureTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.keys.client-wrapped
    func testPBKDF2FailureThrowsInsteadOfReturningZeroKeyMaterial() async {
        do {
            _ = try await CryptoManager.shared.deriveWrappingKeyFromPassword(
                password: "fixture-password",
                salt: Data("fixture-salt".utf8),
                derivation: { _, _, _ in (-1, Data(repeating: 0, count: 32)) }
            )
            XCTFail("PBKDF2 failure returned key material")
        } catch {
            XCTAssertNotNil(error as? CryptoManager.CryptoError)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.keys.client-wrapped
    func testSecureRandomFailureThrowsWithoutReturningBytes() {
        XCTAssertThrowsError(try SecureRandom.data(count: 32, fill: { _, _ in -1 }))
        XCTAssertThrowsError(
            try SecureRandom.string(length: 6, alphabet: Array("123456789"), fill: { _, _ in -1 })
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testLegacyAndExplicitV2MediaDecryptToSamePlaintext() throws {
        let plaintext = Data("apple-media-fixture".utf8)
        let keyData = Data((0..<32).map(UInt8.init))
        let nonceData = Data((0..<12).map(UInt8.init))
        let key = SymmetricKey(data: keyData)
        let nonce = try AES.GCM.Nonce(data: nonceData)
        let sealed = try AES.GCM.seal(plaintext, using: key, nonce: nonce)
        let encryptedBody = sealed.ciphertext + sealed.tag

        let legacy = try S3MediaClient.decryptAESGCM(
            data: encryptedBody,
            encodedKey: keyData.hexEncodedString,
            encodedNonce: nonceData.hexEncodedString,
            encryption: nil
        )
        let v2 = try S3MediaClient.decryptAESGCM(
            data: nonceData + encryptedBody,
            encodedKey: keyData.hexEncodedString,
            encodedNonce: nil,
            encryption: "aes-gcm-nonce-prefixed-v1"
        )

        XCTAssertEqual(legacy, plaintext)
        XCTAssertEqual(v2, plaintext)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testUnknownMediaEncryptionMarkerFailsClosed() throws {
        XCTAssertThrowsError(
            try S3MediaClient.decryptAESGCM(
                data: Data(repeating: 0, count: 29),
                encodedKey: Data(repeating: 1, count: 32).hexEncodedString,
                encodedNonce: nil,
                encryption: "unknown-media-format"
            )
        )
    }
}

private extension Data {
    var hexEncodedString: String {
        map { String(format: "%02x", $0) }.joined()
    }
}

/// Private instances and controlled continuations exercise production commit
/// windows without using a real account, Keychain, or crypto scheduling timing.
@MainActor
final class KeyRevocationTests: XCTestCase {
    private let fixtureKey = SymmetricKey(data: Data(repeating: 7, count: 32))

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testSingleChatUnwrapCannotInstallAfterRevocation() async {
        let started = expectation(description: "single unwrap suspended")
        let gate = RevocationCryptoGate<SymmetricKey>(started: started)
        let manager = ChatKeyManager(unwrapKey: { _, _ in await gate.suspend() })
        let pending = Task { await manager.loadChatKey(chatId: "revoked", encryptedChatKey: "wrapper", masterKey: fixtureKey) }
        await fulfillment(of: [started], timeout: 2)
        manager.removeKey(for: "revoked")
        await gate.resume(with: fixtureKey)
        let loaded = await pending.value
        XCTAssertFalse(loaded)
        XCTAssertFalse(manager.hasKey(for: "revoked"))
        XCTAssertNil(manager.encryptedKey(for: "revoked"))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testBulkUnwrapFencesPendingAndNotYetStartedRevokedEntries() async {
        let started = expectation(description: "bulk unwrap suspended")
        let gate = RevocationCryptoGate<SymmetricKey>(started: started)
        var requested: [String] = []
        let key = fixtureKey
        let manager = ChatKeyManager(unwrapKey: { wrapper, _ in
            requested.append(wrapper)
            if wrapper == "pending-wrapper" { return await gate.suspend() }
            return key
        })
        let pending = Task {
            await manager.loadChatKeys(from: [("pending", "pending-wrapper"), ("later", "later-wrapper"),
                                              ("retained", "retained-wrapper")], masterKey: key)
        }
        await fulfillment(of: [started], timeout: 2)
        manager.removeKey(for: "pending")
        manager.removeKey(for: "later")
        await gate.resume(with: key)
        await pending.value
        XCTAssertFalse(manager.hasKey(for: "pending"))
        XCTAssertNil(manager.encryptedKey(for: "pending"))
        XCTAssertFalse(manager.hasKey(for: "later"))
        XCTAssertNil(manager.encryptedKey(for: "later"))
        XCTAssertEqual(requested, ["pending-wrapper", "retained-wrapper"])
        XCTAssertTrue(manager.hasKey(for: "retained"), "A different chat's revocation must not cancel authorized bulk entries")
        XCTAssertTrue(manager.isReady)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testWrapperFallbackCannotStartFreshUnwrapAfterRevocation() async throws {
        let started = expectation(description: "first wrapper suspended")
        let gate = RevocationCryptoGate<SymmetricKey>(started: started)
        var calls = 0
        let key = fixtureKey
        let manager = ChatKeyManager(unwrapKey: { _, _ in
            calls += 1
            if calls == 1 { return await gate.suspend() }
            return key
        })
        let wrappers = try [wrapper("newer", version: 2), wrapper("older", version: 1)]
        let pending = Task { await manager.loadChatKey(chatId: "revoked", wrappers: wrappers, masterKey: fixtureKey) }
        await fulfillment(of: [started], timeout: 2)
        manager.removeKey(for: "revoked")
        await gate.resume(with: fixtureKey)
        let loaded = await pending.value
        XCTAssertFalse(loaded)
        XCTAssertEqual(calls, 1, "The older wrapper must not acquire a new fence after the first was revoked")
        XCTAssertFalse(manager.hasKey(for: "revoked"))
        XCTAssertNil(manager.encryptedKey(for: "revoked"))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testMembershipFenceRejectsSuspendedBulkAndSingleUnwrapWithoutCachedChat() async {
        for bulk in [true, false] {
            let started = expectation(description: "membership-scoped unwrap suspended")
            let gate = RevocationCryptoGate<SymmetricKey>(started: started)
            let manager = ChatKeyManager(unwrapKey: { _, _ in await gate.suspend() })
            var readableMembership = true
            let pending = Task {
                if bulk {
                    await manager.loadChatKeys(from: [("uncached-team-chat", "wrapper")], masterKey: fixtureKey,
                                               isCurrent: { readableMembership })
                    return manager.hasKey(for: "uncached-team-chat")
                }
                return await manager.loadChatKey(chatId: "uncached-team-chat", encryptedChatKey: "wrapper",
                                                 masterKey: fixtureKey, isCurrent: { readableMembership })
            }
            await fulfillment(of: [started], timeout: 2)
            // No cached chat exists for removeKey to discover. The caller's
            // authoritative membership fence must reject the late installation.
            readableMembership = false
            await gate.resume(with: fixtureKey)
            let loaded = await pending.value
            XCTAssertFalse(loaded)
            XCTAssertFalse(manager.hasKey(for: "uncached-team-chat"))
            XCTAssertNil(manager.encryptedKey(for: "uncached-team-chat"))
            XCTAssertFalse(manager.isReady)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testSuspendedMetadataAndMessageDecryptCannotReturnRevokedPlaintext() async {
        for metadata in [true, false] {
            let started = expectation(description: "content decrypt suspended")
            let gate = RevocationCryptoGate<String>(started: started)
            let manager = ChatKeyManager(decryptContent: { _, _ in await gate.suspend() })
            manager.setKey(fixtureKey, for: "revoked")
            let pending = Task {
                if metadata {
                    return await manager.decryptChatField(chatId: "revoked", encryptedValue: "ciphertext", fieldName: "title")
                }
                return await manager.decryptMessageContent(chatId: "revoked", encryptedContent: "ciphertext")
            }
            await fulfillment(of: [started], timeout: 2)
            manager.removeKey(for: "revoked")
            // A later authorized installation cannot make the earlier decrypt current.
            manager.setKey(fixtureKey, for: "revoked")
            await gate.resume(with: "synthetic secret")
            let plaintext = await pending.value
            XCTAssertNil(plaintext)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testRevocationInvalidatesValidatedInstallAndWrapperCompletionTokens() async {
        let started = expectation(description: "external validation suspended")
        let gate = RevocationCryptoGate<SymmetricKey>(started: started)
        let manager = ChatKeyManager()
        let generation = manager.cacheGeneration
        let pending = Task {
            let key = await gate.suspend()
            return manager.installValidatedKey(key, encryptedKey: "wrapper", for: "revoked", expectedGeneration: generation)
        }
        await fulfillment(of: [started], timeout: 2)
        manager.removeKey(for: "revoked")
        await gate.resume(with: fixtureKey)
        let wrapper = await pending.value
        XCTAssertNil(wrapper)
        XCTAssertNotEqual(generation, manager.cacheGeneration)
        XCTAssertFalse(manager.hasKey(for: "revoked"))
        manager.rememberEncryptedKey("late-wrapper", for: "revoked")
        XCTAssertNil(manager.encryptedKey(for: "revoked"))
        manager.setKey(fixtureKey, for: "revoked")
        XCTAssertNil(manager.rememberNewEncryptedKeyIfAbsent("late-wrapper", for: "revoked", matching: fixtureKey,
                                                             expectedGeneration: generation))
        XCTAssertNil(manager.encryptedKey(for: "revoked"))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testSuspendedNewChatKeyGenerationDoesNotReinstallRevokedKey() async {
        let started = expectation(description: "new key generation suspended")
        let gate = RevocationCryptoGate<SymmetricKey>(started: started)
        let manager = ChatKeyManager()
        let generation = manager.cacheGeneration
        let pending = Task { await manager.createKeyForNewChat("revoked", generateKey: { await gate.suspend() }) }
        await fulfillment(of: [started], timeout: 2)
        manager.removeKey(for: "revoked")
        await gate.resume(with: fixtureKey)
        let uninstalledKey = await pending.value
        XCTAssertFalse(manager.hasKey(for: "revoked"))
        XCTAssertNil(manager.rememberNewEncryptedKeyIfAbsent("wrapper", for: "revoked", matching: uninstalledKey,
                                                             expectedGeneration: generation))
        XCTAssertNil(manager.encryptedKey(for: "revoked"))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testAccountClearAlsoFencesSuspendedChatUnwrapAndPlaintext() async {
        let started = expectation(description: "unwrap suspended before account clear")
        let gate = RevocationCryptoGate<SymmetricKey>(started: started)
        let manager = ChatKeyManager(unwrapKey: { _, _ in await gate.suspend() })
        let pending = Task { await manager.loadChatKey(chatId: "old-account", encryptedChatKey: "wrapper", masterKey: fixtureKey) }
        await fulfillment(of: [started], timeout: 2)
        manager.clearAll()
        await gate.resume(with: fixtureKey)
        let loaded = await pending.value
        XCTAssertFalse(loaded)
        XCTAssertFalse(manager.hasKey(for: "old-account"))

        let decryptStarted = expectation(description: "decrypt suspended before account clear")
        let decryptGate = RevocationCryptoGate<String>(started: decryptStarted)
        let decryptManager = ChatKeyManager(decryptContent: { _, _ in await decryptGate.suspend() })
        decryptManager.setKey(fixtureKey, for: "old-account")
        let decrypt = Task { await decryptManager.decryptMessageContent(chatId: "old-account", encryptedContent: "ciphertext") }
        await fulfillment(of: [decryptStarted], timeout: 2)
        decryptManager.clearAll()
        await decryptGate.resume(with: "old-account plaintext")
        let plaintext = await decrypt.value
        XCTAssertNil(plaintext)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testSuspendedEmbedMasterKeyLoadCannotContinueUnwrapAfterRevocation() async {
        let started = expectation(description: "embed master key suspended")
        let gate = RevocationCryptoGate<SymmetricKey?>(started: started)
        var unwraps = 0
        let key = fixtureKey
        let manager = EmbedKeyManager(masterKey: { await gate.suspend() }, chatKey: { _ in nil }, unwrapKey: { _, _ in
            unwraps += 1
            return key
        })
        let embed = record("embed")
        manager.store([embedWrapper(embed.id, type: "master")], source: "synthetic-test")
        let pending = Task { await manager.key(for: embed, chatId: "revoked", allEmbeds: [:]) }
        await fulfillment(of: [started], timeout: 2)
        manager.removeKeys(for: "revoked")
        await gate.resume(with: key)
        let resolved = await pending.value
        XCTAssertNil(resolved)
        XCTAssertEqual(unwraps, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testSuspendedMasterChatAndRecursiveEmbedUnwrapCannotReturnOrCacheRevokedKeys() async {
        for mode in ["master", "chat", "recursive"] {
            let started = expectation(description: "\(mode) embed unwrap suspended")
            let gate = RevocationCryptoGate<SymmetricKey?>(started: started)
            var unwraps = 0
            let key = fixtureKey
            let manager = EmbedKeyManager(masterKey: { key }, chatKey: { _ in key }, unwrapKey: { _, _ in
                unwraps += 1
                if unwraps == 1 { return await gate.suspend() }
                return nil
            })
            let parent = record("parent-\(mode)")
            let embed = record("embed-\(mode)", parent: mode == "recursive" ? parent.id : nil)
            let wrappedId = mode == "recursive" ? parent.id : embed.id
            manager.store([embedWrapper(wrappedId, type: mode == "master" ? "master" : "chat")], source: "synthetic-test")
            let allEmbeds = [parent.id: parent, embed.id: embed]
            let pending = Task { await manager.key(for: embed, chatId: "revoked", allEmbeds: allEmbeds) }
            await fulfillment(of: [started], timeout: 2)
            manager.removeKeys(for: "revoked")
            await gate.resume(with: key)
            let resolved = await pending.value
            XCTAssertNil(resolved, "Suspended \(mode) unwrap cannot return the revoked key")
            let cached = await manager.key(for: embed, chatId: "revoked", allEmbeds: allEmbeds)
            XCTAssertNil(cached, "Late \(mode) completion cannot populate the child or parent cache")
        }
    }

    private func wrapper(_ encrypted: String, version: Int) throws -> ChatKeyWrapperRecord {
        let payload: [String: Any] = ["hashedChatId": ChatKeyWrapperRecord.hashedChatId(for: "revoked"),
                                      "keyType": "master", "encryptedChatKey": encrypted, "wrapperVersion": version]
        return try JSONDecoder().decode(ChatKeyWrapperRecord.self, from: JSONSerialization.data(withJSONObject: payload))
    }

    private func embedWrapper(_ embedId: String, type: String) -> EmbedKeyRecord {
        EmbedKeyRecord(hashedEmbedId: digest(embedId), keyType: type,
                       hashedChatId: type == "master" ? nil : digest("revoked"), encryptedEmbedKey: "synthetic-wrapper")
    }

    private func record(_ id: String, parent: String? = nil) -> EmbedRecord {
        EmbedRecord(id: id, type: "web-website", status: .finished, data: nil,
                    parentEmbedId: parent, appId: "web", skillId: "search", embedIds: nil, createdAt: nil)
    }

    private func digest(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

private actor RevocationCryptoGate<Value: Sendable> {
    private let started: XCTestExpectation
    private var continuation: CheckedContinuation<Value, Never>?

    init(started: XCTestExpectation) { self.started = started }

    func suspend() async -> Value {
        await withCheckedContinuation {
            continuation = $0
            started.fulfill()
        }
    }

    func resume(with value: Value) {
        continuation?.resume(returning: value)
        continuation = nil
    }
}
