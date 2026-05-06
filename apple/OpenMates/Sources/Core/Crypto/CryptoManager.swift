// E2EE crypto manager — ports the web app's ChatKeyManager + cryptoService to Apple.
// Handles the full key lifecycle: password → PBKDF2 → wrapping key → master key,
// master key → per-chat key unwrap, chat key → message/title decryption.
// Uses CryptoKit for AES-GCM and CommonCrypto for PBKDF2.
// Master key stored in Keychain with iCloud Keychain sync for multi-device.

import Foundation
import CryptoKit
import CommonCrypto

actor CryptoManager {
    static let shared = CryptoManager()

    private init() {}

    // MARK: - Email hashing (zero-knowledge lookup)

    /// Hash email for server lookup — mirrors web app's SHA-256 email hashing.
    func hashEmail(_ email: String) -> String {
        let data = Data(email.utf8)
        let hash = SHA256.hash(data: data)
        return Data(hash).base64EncodedString()
    }

    /// Derive email encryption key from email + user_email_salt.
    /// Mirrors web cryptoService.deriveEmailEncryptionKey(email, salt): SHA256(email bytes + salt bytes).
    func deriveEmailEncryptionKey(email: String, salt: Data) -> Data {
        var input = Data(email.utf8)
        input.append(salt)
        let hash = SHA256.hash(data: input)
        return Data(hash)
    }

    // MARK: - Password-based key derivation (PBKDF2)

    /// Derive lookup hash from a login secret and user_email_salt.
    /// Mirrors web cryptoService.hashKey(secret, salt): SHA256(secret bytes + salt bytes), base64 encoded.
    func hashKey(_ key: String, salt: Data) -> String {
        var input = Data(key.utf8)
        input.append(salt)
        let hash = SHA256.hash(data: input)
        return Data(hash).base64EncodedString()
    }

    /// Derive wrapping key from password using PBKDF2-SHA256 with 100,000 iterations.
    /// Mirrors web: crypto.subtle.deriveBits({ name: "PBKDF2", salt, iterations: 100000, hash: "SHA-256" })
    func deriveWrappingKeyFromPassword(password: String, salt: Data) -> SymmetricKey {
        var derivedKey = Data(count: 32) // 256 bits
        let passwordData = password.data(using: .utf8)!

        derivedKey.withUnsafeMutableBytes { derivedBytes in
            passwordData.withUnsafeBytes { passwordBytes in
                salt.withUnsafeBytes { saltBytes in
                    CCKeyDerivationPBKDF(
                        CCPBKDFAlgorithm(kCCPBKDF2),
                        passwordBytes.baseAddress?.assumingMemoryBound(to: Int8.self),
                        passwordData.count,
                        saltBytes.baseAddress?.assumingMemoryBound(to: UInt8.self),
                        salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256),
                        100_000,
                        derivedBytes.baseAddress?.assumingMemoryBound(to: UInt8.self),
                        32
                    )
                }
            }
        }

        return SymmetricKey(data: derivedKey)
    }

    // MARK: - Master key operations

    /// Unwrap master key using AES-GCM with the PBKDF2-derived wrapping key.
    /// The web app uses crypto.subtle.unwrapKey("raw", wrappedKey, wrappingKey, {AES-GCM, iv}).
    /// unwrapKey with "raw" format = AES-GCM decrypt, output is the raw key bytes.
    func unwrapMasterKey(
        wrappedKeyBase64: String,
        ivBase64: String,
        wrappingKey: SymmetricKey
    ) throws -> SymmetricKey {
        guard let wrappedData = Data(base64Encoded: wrappedKeyBase64),
              let ivData = Data(base64Encoded: ivBase64) else {
            throw CryptoError.invalidBase64
        }
        let decrypted = try decryptAESGCM(ciphertext: wrappedData, iv: ivData, key: wrappingKey)
        return SymmetricKey(data: decrypted)
    }

    /// Derive wrapping key from PRF signature (passkey login).
    /// Mirrors web: HKDF(PRF_signature, user_email_salt, info="masterkey_wrapping")
    func deriveWrappingKeyFromPRF(prfSignature: Data, emailSalt: Data) -> SymmetricKey {
        let key = SymmetricKey(data: prfSignature)
        let derived = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: key,
            salt: emailSalt,
            info: Data("masterkey_wrapping".utf8),
            outputByteCount: 32
        )
        return derived
    }

    /// Lookup hash for passkey authentication.
    /// Mirrors web cryptoService.hashKeyFromPRF(): SHA256(PRF_signature + user_email_salt), base64.
    func hashKeyFromPRF(prfSignature: Data, emailSalt: Data) -> String {
        var input = prfSignature
        input.append(emailSalt)
        let hash = SHA256.hash(data: input)
        return Data(hash).base64EncodedString()
    }

    // MARK: - Per-chat key operations

    /// Unwrap a per-chat key from the encrypted_chat_key blob using the master key.
    /// Format: base64(IV[12 bytes] || ciphertext+tag). Same as all AES-GCM blobs.
    func unwrapChatKey(encryptedChatKeyBase64: String, masterKey: SymmetricKey) throws -> SymmetricKey {
        let plaintext = try decryptBlob(base64String: encryptedChatKeyBase64, key: masterKey)
        return SymmetricKey(data: plaintext)
    }

    // MARK: - Content decryption (messages, titles, embeds)

    /// Decrypt an encrypted blob (message content, title, embed data).
    /// Handles both formats:
    ///   - New: 0x4F 0x4D (magic "OM") + 4-byte fingerprint + 12-byte IV + ciphertext+tag
    ///   - Legacy: 12-byte IV + ciphertext+tag
    func decryptContent(base64String: String, key: SymmetricKey) throws -> String {
        let plaintext = try decryptBlob(base64String: base64String, key: key)
        guard let text = String(data: plaintext, encoding: .utf8) else {
            throw CryptoError.invalidUTF8
        }
        return text
    }

    /// Decrypt a base64-encoded AES-GCM blob, handling "OM" magic prefix.
    func decryptBlob(base64String: String, key: SymmetricKey) throws -> Data {
        guard let data = Data(base64Encoded: base64String) else {
            throw CryptoError.invalidBase64
        }

        var offset = 0

        // Check for "OM" magic bytes (0x4F, 0x4D) — new format with key fingerprint
        if data.count > 18 && data[0] == 0x4F && data[1] == 0x4D {
            // Skip magic (2 bytes) + FNV-1a fingerprint (4 bytes)
            offset = 6
        }

        guard data.count >= offset + 12 + 16 else {
            throw CryptoError.dataTooShort
        }

        let iv = data[offset..<(offset + 12)]
        let ciphertextWithTag = data[(offset + 12)...]

        return try decryptAESGCM(
            ciphertext: Data(ciphertextWithTag),
            iv: Data(iv),
            key: key
        )
    }

    // MARK: - Low-level AES-GCM

    /// AES-256-GCM decrypt. Ciphertext includes the 16-byte authentication tag appended.
    func decryptAESGCM(ciphertext: Data, iv: Data, key: SymmetricKey) throws -> Data {
        let tagLength = 16
        guard ciphertext.count >= tagLength else {
            throw CryptoError.dataTooShort
        }
        let ct = ciphertext.prefix(ciphertext.count - tagLength)
        let tag = ciphertext.suffix(tagLength)
        let sealedBox = try AES.GCM.SealedBox(
            nonce: AES.GCM.Nonce(data: iv),
            ciphertext: ct,
            tag: tag
        )
        return try AES.GCM.open(sealedBox, using: key)
    }

    func encrypt(_ plaintext: Data, using key: SymmetricKey) throws -> (ciphertext: Data, nonce: Data) {
        let nonce = AES.GCM.Nonce()
        let sealed = try AES.GCM.seal(plaintext, using: key, nonce: nonce)
        return (sealed.ciphertext + sealed.tag, Data(nonce))
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

    // MARK: - Errors

    enum CryptoError: LocalizedError {
        case invalidBase64
        case invalidUTF8
        case dataTooShort
        case decryptionFailed

        var errorDescription: String? {
            switch self {
            case .invalidBase64: return "Invalid base64-encoded data"
            case .invalidUTF8: return "Decrypted data is not valid UTF-8"
            case .dataTooShort: return "Encrypted data too short"
            case .decryptionFailed: return "AES-GCM decryption failed"
            }
        }
    }
}
