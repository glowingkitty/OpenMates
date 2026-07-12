// E2EE crypto manager — ports the web app's ChatKeyManager + cryptoService to Apple.
// Handles the full key lifecycle: password → PBKDF2 → wrapping key → master key,
// master key → per-chat key unwrap, chat key → message/title decryption.
// Uses CryptoKit for AES-GCM and CommonCrypto for PBKDF2.
// Master key stored only in the local Apple Keychain for this app install.

import Foundation
import CryptoKit
import CommonCrypto

actor CryptoManager {
    static let shared = CryptoManager()

    struct RecoveryEnvelope: Equatable, Sendable {
        let v: Int
        let epk: String
        let nonce: String
        let ciphertext: String
    }

    struct RecoveryKeyPair: Equatable, Sendable {
        let privateKey: String
        let publicKey: String
    }

    private static let recoveryProtocolVersion = 1
    private static let recoveryKeyLength = 32
    private static let recoveryNonceLength = 12
    private static let recoveryMaximumPayloadBytes = 16 * 1024 * 1024
    private static let recoveryKeySalt = Data(SHA256.hash(data: Data("openmates:chat-recovery:v1".utf8)))
    private static let recoveryEnvelopeKeySalt = Data(SHA256.hash(data: Data("openmates:chat-recovery-envelope:v1".utf8)))

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

        let status = derivedKey.withUnsafeMutableBytes { derivedBytes in
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
        if status != kCCSuccess {
            assertionFailure("PBKDF2 derivation failed with status \(status)")
        }

        return SymmetricKey(data: derivedKey)
    }

    /// Derive the pair-login bundle key from PIN + token.
    /// Mirrors SettingsSessionsPairInitiate.svelte: PBKDF2-SHA256(PIN, upperToken, 100k) → AES-256-GCM.
    func derivePairLoginKey(pin: String, token: String) -> SymmetricKey {
        deriveWrappingKeyFromPassword(password: pin, salt: Data(token.uppercased().utf8))
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

    /// Generate a web-compatible raw AES-256 chat key.
    func generateChatKey() -> SymmetricKey {
        SymmetricKey(size: .bits256)
    }

    /// Wrap a per-chat key with the user's master key for cross-device sync.
    /// Format C: base64(IV[12 bytes] || ciphertext+tag), matching the web app.
    func wrapChatKey(_ chatKey: SymmetricKey, masterKey: SymmetricKey) throws -> String {
        let rawKey = chatKey.withUnsafeBytes { Data($0) }
        let encrypted = try encrypt(rawKey, using: masterKey)
        var combined = Data()
        combined.append(encrypted.nonce)
        combined.append(encrypted.ciphertext)
        return combined.base64EncodedString()
    }

    /// Encrypt message or metadata content with a chat key.
    /// Format A: base64("OM" || 4-byte FNV-1a key fingerprint || IV || ciphertext+tag).
    func encryptContent(_ plaintext: String, key: SymmetricKey) throws -> String {
        try encryptBlob(Data(plaintext.utf8), key: key, includeFingerprint: true)
    }

    /// Encrypt master-key metadata such as new-chat suggestions.
    /// Format D: base64(IV[12 bytes] || ciphertext+tag), matching the web app.
    func encryptWithMasterKey(_ plaintext: String, masterKey: SymmetricKey) throws -> String {
        try encryptBlob(Data(plaintext.utf8), key: masterKey, includeFingerprint: false)
    }

    // MARK: - Chat completion recovery

    func deriveRecoveryKeyPair(
        chatKey: SymmetricKey,
        chatId: String,
        keyVersion: UInt32
    ) throws -> RecoveryKeyPair {
        let chatKeyData = chatKey.withUnsafeBytes { Data($0) }
        guard chatKeyData.count == Self.recoveryKeyLength else {
            throw CryptoError.invalidKeyLength
        }

        var info = try Self.lengthPrefixedCanonicalUUID(chatId, field: "chat_id")
        try Self.appendKeyVersion(keyVersion, to: &info)
        let privateKeyData = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: chatKey,
            salt: Self.recoveryKeySalt,
            info: info,
            outputByteCount: Self.recoveryKeyLength
        ).withUnsafeBytes { Data($0) }
        let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: privateKeyData)

        return RecoveryKeyPair(
            privateKey: Self.encodeBase64URL(privateKeyData),
            publicKey: Self.encodeBase64URL(privateKey.publicKey.rawRepresentation)
        )
    }

    func buildRecoveryAssociatedData(
        ownerId: String,
        chatId: String,
        turnId: String,
        jobId: String,
        assistantMessageId: String,
        keyVersion: UInt32
    ) throws -> Data {
        var associatedData = Data("OMCR1".utf8)
        for (value, field) in [
            (ownerId, "owner_id"),
            (chatId, "chat_id"),
            (turnId, "turn_id"),
            (jobId, "job_id"),
            (assistantMessageId, "assistant_message_id"),
        ] {
            associatedData.append(try Self.lengthPrefixedCanonicalUUID(value, field: field))
        }
        try Self.appendKeyVersion(keyVersion, to: &associatedData)
        return associatedData
    }

    func sealRecoveryPayload(
        _ payload: Data,
        recoveryPublicKey: String,
        ownerId: String,
        chatId: String,
        turnId: String,
        jobId: String,
        assistantMessageId: String,
        keyVersion: UInt32,
        ephemeralPrivateKey: String? = nil,
        nonce: String? = nil
    ) throws -> RecoveryEnvelope {
        guard payload.count <= Self.recoveryMaximumPayloadBytes else {
            throw CryptoError.payloadTooLarge
        }

        let privateKeyData = try ephemeralPrivateKey.map {
            try Self.decodeBase64URL($0, field: "ephemeral_private_key")
        } ?? Curve25519.KeyAgreement.PrivateKey().rawRepresentation
        guard privateKeyData.count == Self.recoveryKeyLength else {
            throw CryptoError.invalidKeyLength
        }
        let nonceData = try nonce.map {
            try Self.decodeBase64URL($0, field: "nonce")
        } ?? Data(AES.GCM.Nonce())
        guard nonceData.count == Self.recoveryNonceLength else {
            throw CryptoError.invalidNonceLength
        }

        let associatedData = try buildRecoveryAssociatedData(
            ownerId: ownerId,
            chatId: chatId,
            turnId: turnId,
            jobId: jobId,
            assistantMessageId: assistantMessageId,
            keyVersion: keyVersion
        )
        let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: privateKeyData)
        let publicKeyData = try Self.decodeBase64URL(recoveryPublicKey, field: "recovery_public_key")
        let envelopeKey = try Self.deriveRecoveryEnvelopeKey(
            privateKey: privateKey,
            publicKeyData: publicKeyData,
            associatedData: associatedData
        )
        let sealed = try AES.GCM.seal(
            payload,
            using: envelopeKey,
            nonce: try AES.GCM.Nonce(data: nonceData),
            authenticating: associatedData
        )

        return RecoveryEnvelope(
            v: Self.recoveryProtocolVersion,
            epk: Self.encodeBase64URL(privateKey.publicKey.rawRepresentation),
            nonce: Self.encodeBase64URL(nonceData),
            ciphertext: Self.encodeBase64URL(sealed.ciphertext + sealed.tag)
        )
    }

    func openRecoveryEnvelope(
        _ envelope: RecoveryEnvelope,
        recoveryPrivateKey: String,
        ownerId: String,
        chatId: String,
        turnId: String,
        jobId: String,
        assistantMessageId: String,
        keyVersion: UInt32
    ) throws -> Data {
        guard envelope.v == Self.recoveryProtocolVersion else {
            throw CryptoError.unsupportedRecoveryEnvelope
        }

        let privateKeyData = try Self.decodeBase64URL(recoveryPrivateKey, field: "recovery_private_key")
        guard privateKeyData.count == Self.recoveryKeyLength else {
            throw CryptoError.invalidKeyLength
        }
        let ephemeralPublicKeyData = try Self.decodeBase64URL(envelope.epk, field: "epk")
        let nonceData = try Self.decodeBase64URL(envelope.nonce, field: "nonce")
        guard nonceData.count == Self.recoveryNonceLength else {
            throw CryptoError.invalidNonceLength
        }
        let ciphertext = try Self.decodeBase64URL(envelope.ciphertext, field: "ciphertext")
        guard ciphertext.count >= 16 else {
            throw CryptoError.dataTooShort
        }
        guard ciphertext.count <= Self.recoveryMaximumPayloadBytes + 16 else {
            throw CryptoError.payloadTooLarge
        }

        let associatedData = try buildRecoveryAssociatedData(
            ownerId: ownerId,
            chatId: chatId,
            turnId: turnId,
            jobId: jobId,
            assistantMessageId: assistantMessageId,
            keyVersion: keyVersion
        )
        let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: privateKeyData)
        let envelopeKey = try Self.deriveRecoveryEnvelopeKey(
            privateKey: privateKey,
            publicKeyData: ephemeralPublicKeyData,
            associatedData: associatedData
        )
        let sealedBox = try AES.GCM.SealedBox(
            nonce: AES.GCM.Nonce(data: nonceData),
            ciphertext: ciphertext.dropLast(16),
            tag: ciphertext.suffix(16)
        )
        return try AES.GCM.open(sealedBox, using: envelopeKey, authenticating: associatedData)
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

    private func encryptBlob(_ plaintext: Data, key: SymmetricKey, includeFingerprint: Bool) throws -> String {
        let encrypted = try encrypt(plaintext, using: key)
        var combined = Data()
        if includeFingerprint {
            combined.append(contentsOf: [0x4F, 0x4D])
            combined.append(keyFingerprintBytes(key))
        }
        combined.append(encrypted.nonce)
        combined.append(encrypted.ciphertext)
        return combined.base64EncodedString()
    }

    private func keyFingerprintBytes(_ key: SymmetricKey) -> Data {
        let raw = key.withUnsafeBytes { Data($0) }
        var hash: UInt32 = 0x811c9dc5
        for byte in raw {
            hash ^= UInt32(byte)
            hash = hash &* 0x01000193
        }
        return Data([
            UInt8((hash >> 24) & 0xff),
            UInt8((hash >> 16) & 0xff),
            UInt8((hash >> 8) & 0xff),
            UInt8(hash & 0xff),
        ])
    }

    private static func deriveRecoveryEnvelopeKey(
        privateKey: Curve25519.KeyAgreement.PrivateKey,
        publicKeyData: Data,
        associatedData: Data
    ) throws -> SymmetricKey {
        guard publicKeyData.count == recoveryKeyLength else {
            throw CryptoError.invalidKeyLength
        }
        let publicKey = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: publicKeyData)
        let sharedSecret = try privateKey.sharedSecretFromKeyAgreement(with: publicKey)
        let sharedSecretData = sharedSecret.withUnsafeBytes { Data($0) }
        guard sharedSecretData.contains(where: { $0 != 0 }) else {
            throw CryptoError.invalidSharedSecret
        }
        return sharedSecret.hkdfDerivedSymmetricKey(
            using: SHA256.self,
            salt: recoveryEnvelopeKeySalt,
            sharedInfo: Data(SHA256.hash(data: associatedData)),
            outputByteCount: recoveryKeyLength
        )
    }

    private static func lengthPrefixedCanonicalUUID(_ value: String, field: String) throws -> Data {
        guard let uuid = UUID(uuidString: value), uuid.uuidString.lowercased() == value else {
            throw CryptoError.invalidIdentifier(field)
        }
        let encoded = Data(value.utf8)
        var result = Data()
        appendUInt32(UInt32(encoded.count), to: &result)
        result.append(encoded)
        return result
    }

    private static func appendKeyVersion(_ keyVersion: UInt32, to data: inout Data) throws {
        guard keyVersion > 0 else {
            throw CryptoError.invalidKeyVersion
        }
        appendUInt32(keyVersion, to: &data)
    }

    private static func appendUInt32(_ value: UInt32, to data: inout Data) {
        data.append(contentsOf: [
            UInt8((value >> 24) & 0xff),
            UInt8((value >> 16) & 0xff),
            UInt8((value >> 8) & 0xff),
            UInt8(value & 0xff),
        ])
    }

    private static func encodeBase64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private static func decodeBase64URL(_ value: String, field: String) throws -> Data {
        guard !value.isEmpty, !value.contains("=") else {
            throw CryptoError.invalidBase64URL(field)
        }
        var base64 = value
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        base64.append(String(repeating: "=", count: (4 - base64.count % 4) % 4))
        guard let decoded = Data(base64Encoded: base64), encodeBase64URL(decoded) == value else {
            throw CryptoError.invalidBase64URL(field)
        }
        return decoded
    }

    // MARK: - Keychain storage

    func saveMasterKey(_ key: SymmetricKey, for userId: String) throws {
        try KeychainHelper.save(
            key: "openmates.masterKey.\(userId)",
            data: key.withUnsafeBytes { Data($0) }
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
        case invalidBase64URL(String)
        case invalidIdentifier(String)
        case invalidKeyLength
        case invalidNonceLength
        case invalidKeyVersion
        case invalidSharedSecret
        case payloadTooLarge
        case unsupportedRecoveryEnvelope

        var errorDescription: String? {
            switch self {
            case .invalidBase64: return "Invalid base64-encoded data"
            case .invalidUTF8: return "Decrypted data is not valid UTF-8"
            case .dataTooShort: return "Encrypted data too short"
            case .decryptionFailed: return "AES-GCM decryption failed"
            case .invalidBase64URL(let field): return "Invalid unpadded base64url for \(field)"
            case .invalidIdentifier(let field): return "Invalid canonical UUID for \(field)"
            case .invalidKeyLength: return "Recovery key must contain exactly 32 bytes"
            case .invalidNonceLength: return "Recovery nonce must contain exactly 12 bytes"
            case .invalidKeyVersion: return "Recovery key version must be greater than zero"
            case .invalidSharedSecret: return "Invalid X25519 shared secret"
            case .payloadTooLarge: return "Recovery payload exceeds 16 MiB"
            case .unsupportedRecoveryEnvelope: return "Unsupported recovery envelope"
            }
        }
    }
}

/// Shared embed-field crypto used by foreground and background send paths.
/// This stays in Core/Crypto so composer views and document models never own keys.
enum ComposerEmbedCrypto {
    private static let derivationSalt = Data("openmates-embed-key-v1".utf8)

    static func deriveKey(chatKey: SymmetricKey, embedId: String) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(
            inputKeyMaterial: chatKey,
            salt: derivationSalt,
            info: Data(embedId.utf8),
            outputByteCount: 32
        )
    }

    static func wrapKey(_ key: SymmetricKey, using wrappingKey: SymmetricKey) throws -> String {
        let rawKey = key.withUnsafeBytes { Data($0) }
        return try encrypt(rawKey, using: wrappingKey)
    }

    static func unwrapKey(_ encryptedKey: String, using wrappingKey: SymmetricKey) throws -> SymmetricKey {
        SymmetricKey(data: try decrypt(encryptedKey, using: wrappingKey))
    }

    static func encryptContent(_ plaintext: String, using key: SymmetricKey) throws -> String {
        try encrypt(Data(plaintext.utf8), using: key)
    }

    static func decryptContent(_ encryptedContent: String, using key: SymmetricKey) throws -> String {
        let plaintext = try decrypt(encryptedContent, using: key)
        guard let value = String(data: plaintext, encoding: .utf8) else {
            throw CryptoManager.CryptoError.invalidUTF8
        }
        return value
    }

    private static func encrypt(_ plaintext: Data, using key: SymmetricKey) throws -> String {
        let sealed = try AES.GCM.seal(plaintext, using: key)
        guard let combined = sealed.combined else {
            throw CryptoManager.CryptoError.decryptionFailed
        }
        return combined.base64EncodedString()
    }

    private static func decrypt(_ encryptedValue: String, using key: SymmetricKey) throws -> Data {
        guard let combined = Data(base64Encoded: encryptedValue) else {
            throw CryptoManager.CryptoError.invalidBase64
        }
        let sealed = try AES.GCM.SealedBox(combined: combined)
        return try AES.GCM.open(sealed, using: key)
    }
}
