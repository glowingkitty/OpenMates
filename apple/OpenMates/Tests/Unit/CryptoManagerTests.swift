// CryptoManager unit tests — validates AES-GCM encryption/decryption, key derivation,
// and master key lifecycle. Mirrors the web app's encryption test coverage.

import XCTest
@testable import OpenMates

final class CryptoManagerTests: XCTestCase {

    func testEncryptDecryptRoundTrip() async throws {
        let plaintext = "Hello, OpenMates!"
        let key = CryptoManager.generateRandomKey()
        let encrypted = try CryptoManager.encrypt(plaintext, with: key)
        let decrypted = try CryptoManager.decrypt(encrypted.ciphertext, iv: encrypted.iv, with: key)
        XCTAssertEqual(decrypted, plaintext)
    }

    func testEncryptEmptyString() async throws {
        let key = CryptoManager.generateRandomKey()
        let encrypted = try CryptoManager.encrypt("", with: key)
        let decrypted = try CryptoManager.decrypt(encrypted.ciphertext, iv: encrypted.iv, with: key)
        XCTAssertEqual(decrypted, "")
    }

    func testEncryptUnicodeContent() async throws {
        let plaintext = "日本語テスト 🎉 Ñoño"
        let key = CryptoManager.generateRandomKey()
        let encrypted = try CryptoManager.encrypt(plaintext, with: key)
        let decrypted = try CryptoManager.decrypt(encrypted.ciphertext, iv: encrypted.iv, with: key)
        XCTAssertEqual(decrypted, plaintext)
    }

    func testDecryptWithWrongKeyFails() async throws {
        let plaintext = "Secret data"
        let correctKey = CryptoManager.generateRandomKey()
        let wrongKey = CryptoManager.generateRandomKey()
        let encrypted = try CryptoManager.encrypt(plaintext, with: correctKey)

        XCTAssertThrowsError(
            try CryptoManager.decrypt(encrypted.ciphertext, iv: encrypted.iv, with: wrongKey)
        )
    }

    func testGenerateRandomKeyLength() {
        let key = CryptoManager.generateRandomKey()
        // AES-256 key = 32 bytes, base64-encoded
        let keyData = Data(base64Encoded: key)
        XCTAssertNotNil(keyData)
        XCTAssertEqual(keyData?.count, 32)
    }

    func testDeriveKeyFromPassword() async throws {
        let password = "test-password-123"
        let salt = "test-salt-value"
        let key1 = try CryptoManager.deriveKey(from: password, salt: salt)
        let key2 = try CryptoManager.deriveKey(from: password, salt: salt)
        XCTAssertEqual(key1, key2, "Same password + salt should produce same key")

        let key3 = try CryptoManager.deriveKey(from: password, salt: "different-salt")
        XCTAssertNotEqual(key1, key3, "Different salt should produce different key")
    }

    func testEncryptionProducesDifferentIVs() async throws {
        let plaintext = "Same content"
        let key = CryptoManager.generateRandomKey()
        let encrypted1 = try CryptoManager.encrypt(plaintext, with: key)
        let encrypted2 = try CryptoManager.encrypt(plaintext, with: key)
        XCTAssertNotEqual(encrypted1.iv, encrypted2.iv, "Each encryption should use a unique IV")
    }
}
