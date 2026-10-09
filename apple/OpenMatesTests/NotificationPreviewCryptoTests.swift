import CryptoKit
import Foundation
import Security
import XCTest
@testable import OpenMates

final class NotificationPreviewCryptoTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=notifications.workflow-run.completed-delivery
    func testWorkflowCompletionEncryptedDisplaySeparatesTitleAndBody() throws {
        let recipient = Curve25519.KeyAgreement.PrivateKey()
        let ephemeral = Curve25519.KeyAgreement.PrivateKey()
        let secret = try ephemeral.sharedSecretFromKeyAgreement(with: recipient.publicKey)
        let key = secret.hkdfDerivedSymmetricKey(using: SHA256.self, salt: Data(),
            sharedInfo: Data("openmates-apns-notification-v1".utf8), outputByteCount: 32)
        let plaintext = try JSONSerialization.data(withJSONObject: [
            "title": "# **Morning workflow**", "body": "Your scheduled workflow completed."])
        let box = try AES.GCM.seal(plaintext, using: key)
        func encode(_ data: Data) -> String {
            data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        }
        let userInfo: [AnyHashable: Any] = ["encrypted_notification": [
            "version": NotificationPreviewCrypto.encryptionVersion,
            "ephemeral_public_key": encode(ephemeral.publicKey.rawRepresentation),
            "nonce": encode(box.nonce.withUnsafeBytes { Data($0) }),
            "ciphertext": encode(box.ciphertext + box.tag)]]
        XCTAssertEqual(NotificationPreviewCrypto.decryptDisplay(userInfo: userInfo,
            privateKeyData: recipient.rawRepresentation),
            .init(title: "Morning workflow", body: "Your scheduled workflow completed."))
        XCTAssertNil(NotificationPreviewCrypto.decryptDisplay(userInfo: userInfo,
            privateKeyData: Curve25519.KeyAgreement.PrivateKey().rawRepresentation))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
    func testNotificationPreviewRemovesCompleteAndTruncatedProtocolFences() {
        let wire = "```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"private-reference\"}\n```"
        XCTAssertEqual(NotificationPreviewCrypto.safeDisplayPreview("Before. " + wire + " After."), "Before. After.")
        XCTAssertNil(NotificationPreviewCrypto.safeDisplayPreview(wire))
        XCTAssertEqual(NotificationPreviewCrypto.safeDisplayPreview("Readable prose. ```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"partial"), "Readable prose.")
        XCTAssertNil(NotificationPreviewCrypto.safeDisplayPreview("~~~json_embed\n{\"embed_id\":\"partial"))
        XCTAssertNil(NotificationPreviewCrypto.safeDisplayPreview("{\"type\":\"app_skill_use\",\"embed_id\":\"private-reference\"}"))
        XCTAssertEqual(NotificationPreviewCrypto.safeDisplayPreview("Result [embed:private-reference] ready."), "Result ready.")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
    func testNotificationDecryptedEnvelopeUsesBoundedPlainProseAndSafeFallback() throws {
        let prose = "# **Results**\n- Read [the summary](https://example.invalid/private)."
        let envelope = try JSONSerialization.data(withJSONObject: ["preview": prose])
        XCTAssertEqual(NotificationPreviewCrypto.previewFromDecryptedEnvelope(envelope), "Results\nRead the summary.")
        let unsafe = try JSONSerialization.data(withJSONObject: ["preview": "```json\n{\"embed_id\":\"partial"])
        XCTAssertNil(NotificationPreviewCrypto.previewFromDecryptedEnvelope(unsafe))
        XCTAssertNil(NotificationPreviewCrypto.previewFromDecryptedEnvelope(Data("invalid".utf8)))
        XCTAssertEqual(NotificationPreviewCrypto.safeDisplayPreview(String(repeating: "界", count: 4097))?.count, 4096)
        XCTAssertEqual(NotificationPreviewCrypto.safeDisplayPreview("Ordinary useful reply."), "Ordinary useful reply.")
        XCTAssertEqual(NotificationPreviewCrypto.safeDisplayPreview("The JSON field embed_id belongs to app_skill_use."),
                       "The JSON field embed_id belongs to app_skill_use.")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
    func testEncryptedPreviewSanitizesActualAuthenticatedEnvelopeWithoutDeviceKeychain() throws {
        let recipient = Curve25519.KeyAgreement.PrivateKey()
        let ephemeral = Curve25519.KeyAgreement.PrivateKey()
        let secret = try ephemeral.sharedSecretFromKeyAgreement(with: recipient.publicKey)
        let key = secret.hkdfDerivedSymmetricKey(using: SHA256.self, salt: Data(),
            sharedInfo: Data("openmates-apns-notification-v1".utf8), outputByteCount: 32)
        func payload(_ preview: String) throws -> [AnyHashable: Any] {
            let envelope = try JSONSerialization.data(withJSONObject: ["preview": preview])
            let box = try AES.GCM.seal(envelope, using: key)
            func encode(_ data: Data) -> String {
                data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
                    .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
            }
            return ["encrypted_notification": ["version": NotificationPreviewCrypto.encryptionVersion,
                "ephemeral_public_key": encode(ephemeral.publicKey.rawRepresentation),
                "nonce": encode(box.nonce.withUnsafeBytes { Data($0) }),
                "ciphertext": encode(box.ciphertext + box.tag)]]
        }
        let mixed = try payload("Web | Search: 'synthetic query' & 3 other app skills\n\n**Ready.** [3 Images] ```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"synthetic-reference\"}\n```")
        XCTAssertEqual(NotificationPreviewCrypto.decryptPreview(userInfo: mixed,
            privateKeyData: recipient.rawRepresentation), "Web | Search: 'synthetic query' & 3 other app skills\n\nReady. [3 Images]")
        let onlyProtocol = try payload("```json\n{\"embed_id\":\"truncated")
        XCTAssertNil(NotificationPreviewCrypto.decryptPreview(userInfo: onlyProtocol,
            privateKeyData: recipient.rawRepresentation))
        XCTAssertNil(NotificationPreviewCrypto.decryptPreview(userInfo: mixed,
            privateKeyData: Curve25519.KeyAgreement.PrivateKey().rawRepresentation))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.preview.readable
    func testDisplayReadyPreviewPreservesSkillSummaryResponseStartAndInlineMarkers() {
        let prefix = "Web | Search: 'GPT6.1 Astra' & 3 other app skills"
        let preview = prefix + "\n\n" + String(repeating: "Readable response. ", count: 30) + "[3 Images]"
        XCTAssertEqual(NotificationPreviewCrypto.safeDisplayPreview(preview), preview)
        XCTAssertEqual(NotificationPreviewCrypto.safeDisplayPreview(prefix + "\r\n\r\nResult [3 Images]"),
                       prefix + "\n\nResult [3 Images]")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
    func testMacPreviewKeyMigrationRetainsLegacyRecipientWithoutDeviceKeychain() throws {
        let legacyKey = Data(repeating: 7, count: 32)
        var queries: [[CFString: Any]] = []
        var inserted: [CFString: Any]?
        let store = NotificationPreviewKeychain(accessGroup: "FIXTURE.org.openmates.app",
            operations: .init(copy: { query in
                queries.append(query)
                return query[kSecUseDataProtectionKeychain] != nil ? (errSecItemNotFound, nil) : (errSecSuccess, legacyKey)
            }, add: { inserted = $0; return errSecSuccess }),
            makeKey: { XCTFail("Migration must retain the existing notification recipient"); return Data() })
        XCTAssertEqual(try store.loadOrCreate(), legacyKey)
        XCTAssertEqual(queries.count, 2)
        XCTAssertEqual(queries[0][kSecAttrAccessGroup] as? String, "FIXTURE.org.openmates.app")
        XCTAssertNil(queries[1][kSecAttrAccessGroup])
        XCTAssertEqual(inserted?[kSecValueData] as? Data, legacyKey)
        XCTAssertEqual(inserted?[kSecUseDataProtectionKeychain] as? Bool, true)
        XCTAssertEqual(inserted?[kSecAttrSynchronizable] as? Bool, false)
        XCTAssertEqual(inserted?[kSecAttrAccessible] as? String, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
    func testMacExtensionReadsOnlySharedKeyAndFailsClosedOnLockedOrMissingKey() throws {
        for status in [errSecItemNotFound, errSecInteractionNotAllowed] {
            var reads = 0
            let store = NotificationPreviewKeychain(accessGroup: "FIXTURE.org.openmates.app",
                operations: .init(copy: { query in
                    reads += 1
                    XCTAssertEqual(query[kSecUseDataProtectionKeychain] as? Bool, true)
                    return (status, nil)
                }, add: { _ in XCTFail("Extension must never create or migrate a key"); return errSecSuccess }))
            if status == errSecItemNotFound { XCTAssertNil(try store.loadShared()) }
            else { XCTAssertThrowsError(try store.loadShared()) }
            XCTAssertEqual(reads, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
    func testMacKeyMigrationDoesNotReplaceInaccessibleOrMalformedExistingKey() {
        for (status, bytes) in [(errSecInteractionNotAllowed, nil), (errSecSuccess, Data(repeating: 1, count: 8))] {
            let store = NotificationPreviewKeychain(accessGroup: "FIXTURE.org.openmates.app",
                operations: .init(copy: { query in
                    query[kSecUseDataProtectionKeychain] != nil ? (errSecItemNotFound, nil) : (status, bytes)
                }, add: { _ in XCTFail("Existing recipient key must not be replaced"); return errSecSuccess }),
                makeKey: { XCTFail("Existing recipient key must not be replaced"); return Data() })
            XCTAssertThrowsError(try store.loadOrCreate())
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testMacNotificationKeyPurgeDeletesSharedAndLegacyNamespacesWithoutReadingPrivateKey() {
        var deletions: [[CFString: Any]] = []
        let store = NotificationPreviewKeychain(accessGroup: "FIXTURE.org.openmates.app",
            operations: .init(copy: { _ in XCTFail("Logout must not read key bytes"); return (errSecItemNotFound, nil) },
                add: { _ in XCTFail("Logout must not create keys"); return errSecSuccess },
                delete: { deletions.append($0); return errSecSuccess }))
        store.clear()
        XCTAssertEqual(deletions.count, 2)
        XCTAssertEqual(deletions[0][kSecUseDataProtectionKeychain] as? Bool, true)
        XCTAssertEqual(deletions[0][kSecAttrAccessGroup] as? String, "FIXTURE.org.openmates.app")
        XCTAssertNil(deletions[1][kSecUseDataProtectionKeychain])
        XCTAssertNil(deletions[1][kSecAttrAccessGroup])
        XCTAssertEqual(deletions[1][kSecAttrAccount] as? String, "openmates.notificationEncryption.privateKey")
    }

}
