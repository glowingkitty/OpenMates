// E2EE crypto manager — ports the web app's ChatKeyManager to Apple platforms.
// Uses CryptoKit for key derivation and AES-GCM encryption.
// Master key stored in Keychain with iCloud Keychain sync for multi-device.

import Foundation
import CryptoKit

actor CryptoManager {
    static let shared = CryptoManager()

    private init() {}

    // MARK: - Email hashing (zero-knowledge lookup)

    /// Hash email for server lookup — mirrors web app's SHA-256 email hashing.
    func hashEmail(_ email: String) -> String {
        let data = Data(email.lowercased().trimmingCharacters(in: .whitespaces).utf8)
        let hash = SHA256.hash(data: data)
        return hash.compactMap { String(format: "%02x", $0) }.joined()
    }

    /// Derive email encryption key from email + salt.
    /// Matches web: SHA256(email + user_email_salt)
    func deriveEmailKey(email: String, salt: String) -> SymmetricKey {
        let input = email.lowercased() + salt
        let hash = SHA256.hash(data: Data(input.utf8))
        return SymmetricKey(data: hash)
    }

    // MARK: - Password-based key derivation

    /// Derive lookup hash from password for auth.
    /// Mirrors web app's password hashing before sending to server.
    func hashPassword(_ password: String, email: String) -> String {
        let input = password + email.lowercased()
        let hash = SHA256.hash(data: Data(input.utf8))
        return hash.compactMap { String(format: "%02x", $0) }.joined()
    }

    // MARK: - Master key operations

    /// Decrypt master key using a wrapping key (from password or PRF).
    func decryptMasterKey(
        encryptedKey: Data,
        iv: Data,
        wrappingKey: SymmetricKey
    ) throws -> SymmetricKey {
        let sealedBox = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: iv), ciphertext: encryptedKey, tag: Data())
        let decrypted = try AES.GCM.open(sealedBox, using: wrappingKey)
        return SymmetricKey(data: decrypted)
    }

    /// Derive wrapping key from PRF signature (passkey login).
    /// Mirrors web: HKDF(PRF_signature, user_email_salt)
    func deriveWrappingKeyFromPRF(prfSignature: Data, emailSalt: Data) -> SymmetricKey {
        let key = SymmetricKey(data: prfSignature)
        let derived = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: key,
            salt: emailSalt,
            info: Data("openmates-master-key".utf8),
            outputByteCount: 32
        )
        return derived
    }

    // MARK: - Message encryption/decryption

    func encrypt(_ plaintext: Data, using key: SymmetricKey) throws -> (ciphertext: Data, nonce: Data) {
        let nonce = AES.GCM.Nonce()
        let sealed = try AES.GCM.seal(plaintext, using: key, nonce: nonce)
        return (sealed.ciphertext + sealed.tag, Data(nonce))
    }

    func decrypt(ciphertext: Data, nonce: Data, using key: SymmetricKey) throws -> Data {
        let tagLength = 16
        let ct = ciphertext.prefix(ciphertext.count - tagLength)
        let tag = ciphertext.suffix(tagLength)
        let sealedBox = try AES.GCM.SealedBox(
            nonce: AES.GCM.Nonce(data: nonce),
            ciphertext: ct,
            tag: tag
        )
        return try AES.GCM.open(sealedBox, using: key)
    }

    // MARK: - Keychain storage

    func saveMasterKey(_ key: SymmetricKey, for userId: String) throws {
        try KeychainHelper.save(
            key: "openmates.masterKey.\(userId)",
            data: key.withUnsafeBytes { Data($0) },
            synchronizable: true
        )
    }

    func loadMasterKey(for userId: String) throws -> SymmetricKey? {
        guard let data = try KeychainHelper.load(key: "openmates.masterKey.\(userId)") else {
            return nil
        }
        return SymmetricKey(data: data)
    }

    func deleteMasterKey(for userId: String) throws {
        try KeychainHelper.delete(key: "openmates.masterKey.\(userId)")
    }
}
