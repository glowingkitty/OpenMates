// Cryptographic failure and media compatibility coverage for Apple clients.
// Verifies native failures stop before returning zero or deterministic secrets.
// Freezes legacy external-nonce and explicit nonce-prefixed media readers.
// Unknown media encryption markers must fail closed without trial decryption.

import CryptoKit
import XCTest
@testable import OpenMates

final class CryptoFailureTests: XCTestCase {
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

    func testSecureRandomFailureThrowsWithoutReturningBytes() {
        XCTAssertThrowsError(try SecureRandom.data(count: 32, fill: { _, _ in -1 }))
        XCTAssertThrowsError(
            try SecureRandom.string(length: 6, alphabet: Array("123456789"), fill: { _, _ in -1 })
        )
    }

    func testLegacyAndExplicitV2MediaDecryptToSamePlaintext() throws {
        let plaintext = Data("apple-media-fixture".utf8)
        let keyData = Data(0..<32)
        let nonceData = Data(0..<12)
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
