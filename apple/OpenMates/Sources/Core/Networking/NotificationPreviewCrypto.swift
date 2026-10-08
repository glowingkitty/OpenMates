// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.payload.privacy-safe, apple-notifications.preview.readable
// Device-local notification preview encryption helpers.
// Keeps the APNs notification private key in Keychain and exposes only the
// public key to the backend for encrypted preview payloads.
// Shared by the app target and Notification Service Extension so Apple only
// receives safe fallback alert text while the device can decrypt optional text.

import CryptoKit
import Foundation
import Security

enum NotificationPreviewCrypto {
    static let encryptionVersion = "x25519-aesgcm-v1"

    static let maximumDisplayCharacters = 4096

    private static let privateKeyKeychainKey = "openmates.notificationEncryption.privateKey"
    private static let encryptionInfo = Data("openmates-apns-notification-v1".utf8)

    static func loadOrCreatePublicKey() -> String? {
        do {
            #if os(macOS)
            // Only the authenticated containing app migrates/creates the device key.
            let privateKeyData = try NotificationPreviewKeychain().loadOrCreate()
            let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: privateKeyData)
            return encodeBase64URL(privateKey.publicKey.rawRepresentation)
            #else
            if let existingPrivateKeyData = try KeychainHelper.load(key: privateKeyKeychainKey) {
                let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: existingPrivateKeyData)
                return encodeBase64URL(privateKey.publicKey.rawRepresentation)
            }

            let privateKey = Curve25519.KeyAgreement.PrivateKey()
            try KeychainHelper.save(key: privateKeyKeychainKey, data: privateKey.rawRepresentation)
            return encodeBase64URL(privateKey.publicKey.rawRepresentation)
            #endif
        } catch {
            return nil
        }
    }

    static func clearPrivateKey() {
        #if os(macOS)
        NotificationPreviewKeychain().clear()
        #else
        try? KeychainHelper.delete(key: privateKeyKeychainKey)
        #endif
    }

    static func decryptPreview(userInfo: [AnyHashable: Any]) -> String? {
        #if os(macOS)
        // Extensions never query the legacy keychain or create a replacement key.
        guard let privateKeyData = try? NotificationPreviewKeychain().loadShared() else { return nil }
        #else
        guard let privateKeyData = try? KeychainHelper.load(key: privateKeyKeychainKey) else { return nil }
        #endif
        return decryptPreview(userInfo: userInfo, privateKeyData: privateKeyData)
    }

    // Explicit key input lets synthetic tests exercise the actual authenticated
    // ciphertext path without reading or replacing the device's Keychain key.
    static func decryptPreview(userInfo: [AnyHashable: Any], privateKeyData: Data) -> String? {
        guard let encrypted = userInfo["encrypted_notification"] as? [String: Any],
              encrypted["version"] as? String == encryptionVersion,
              let ephemeralPublicKeyValue = encrypted["ephemeral_public_key"] as? String,
              let nonceValue = encrypted["nonce"] as? String,
              let ciphertextValue = encrypted["ciphertext"] as? String,
              let ephemeralPublicKeyData = decodeBase64URL(ephemeralPublicKeyValue),
              let nonceData = decodeBase64URL(nonceValue),
              let encryptedData = decodeBase64URL(ciphertextValue),
              encryptedData.count > 16 else {
            return nil
        }

        do {
            let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: privateKeyData)
            let ephemeralPublicKey = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: ephemeralPublicKeyData)
            let sharedSecret = try privateKey.sharedSecretFromKeyAgreement(with: ephemeralPublicKey)
            let symmetricKey = sharedSecret.hkdfDerivedSymmetricKey(
                using: SHA256.self,
                salt: Data(),
                sharedInfo: encryptionInfo,
                outputByteCount: 32
            )
            let sealedBox = try AES.GCM.SealedBox(
                nonce: AES.GCM.Nonce(data: nonceData),
                ciphertext: encryptedData.dropLast(16),
                tag: encryptedData.suffix(16)
            )
            let plaintext = try AES.GCM.open(sealedBox, using: symmetricKey)
            return previewFromDecryptedEnvelope(plaintext)
        } catch {
            return nil
        }
    }

    // Treat decrypted content as display input, not trusted protocol-free prose.
    // Older servers bounded raw Markdown before encryption, including partial fences.
    static func previewFromDecryptedEnvelope(_ plaintext: Data) -> String? {
        guard let envelope = try? JSONSerialization.jsonObject(with: plaintext) as? [String: Any],
              let preview = envelope["preview"] as? String else { return nil }
        return safeDisplayPreview(preview)
    }

    static func safeDisplayPreview(_ raw: String) -> String? {
        var text = raw.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
        for fence in ["```", "~~~"] {
            text = text.replacingOccurrences(
                of: "(?s)" + fence + ".*?(?:" + fence + "|$)",
                with: " ", options: .regularExpression)
        }
        text = text.replacingOccurrences(of: #"\[embed:[^\]]*(?:\]|$)"#,
                                         with: " ", options: .regularExpression)
        // A malformed/flattened protocol object must never surface its identifiers.
        let protocolObject = #"(?s)^\s*\{.*"(?:embed_id|embed_ids|embed_ref)"\s*:"#
        guard text.range(of: protocolObject, options: .regularExpression) == nil else { return nil }
        text = text.replacingOccurrences(of: #"!?\[([^\]]*)\]\([^)]*(?:\)|$)"#,
                                         with: "$1", options: .regularExpression)
        text = text.replacingOccurrences(of: #"(?m)^[ \t]{0,3}(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+\.\s+)"#,
                                         with: "", options: .regularExpression)
        for pattern in [#"\*{1,3}([^*]+)\*{1,3}"#, #"(?<!\w)_{1,3}([^_]+)_{1,3}(?!\w)"#,
                        #"`([^`]+)`"#, #"~~([^~]+)~~"#] {
            text = text.replacingOccurrences(of: pattern, with: "$1", options: .regularExpression)
        }
        text = text.replacingOccurrences(of: #"[^\S\n]+"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: #" *\n *"#, with: "\n", options: .regularExpression)
            .replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        return String(text.prefix(maximumDisplayCharacters))
    }

    private static func encodeBase64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private static func decodeBase64URL(_ value: String) -> Data? {
        var base64 = value
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let remainder = base64.count % 4
        if remainder > 0 {
            base64.append(String(repeating: "=", count: 4 - remainder))
        }
        return Data(base64Encoded: base64)
    }
}

// macOS access-group sharing uses the data protection keychain. Migrate only the
// notification key; authentication/master-key storage keeps its existing policy.
// Synthetic operation injection verifies migration without touching a real key.
struct NotificationPreviewKeychain {
    struct Operations {
        let copy: ([CFString: Any]) -> (OSStatus, Data?)
        let add: ([CFString: Any]) -> OSStatus
        var delete: ([CFString: Any]) -> OSStatus = { SecItemDelete($0 as CFDictionary) }
        static var live: Operations { Operations(copy: { query in
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            return (status, result as? Data)
        }, add: { SecItemAdd($0 as CFDictionary, nil) }) }
    }

    var accessGroup: String? = KeychainHelper.queryAccessGroup
    var operations: Operations = .live
    var makeKey: () -> Data = { Curve25519.KeyAgreement.PrivateKey().rawRepresentation }

    func query(legacy: Bool = false) -> [CFString: Any] {
        var query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: "org.openmates.app",
            kSecAttrAccount: "openmates.notificationEncryption.privateKey",
            kSecAttrSynchronizable: kCFBooleanFalse!,
            kSecUseAuthenticationUI: kSecUseAuthenticationUIFail,
        ]
        if !legacy {
            query[kSecUseDataProtectionKeychain] = true
            if let accessGroup { query[kSecAttrAccessGroup] = accessGroup }
        }
        return query
    }

    private func read(legacy: Bool = false) -> (OSStatus, Data?) {
        var request = query(legacy: legacy)
        request[kSecReturnData] = true
        request[kSecMatchLimit] = kSecMatchLimitOne
        return operations.copy(request)
    }

    private func validated(_ bytes: Data?) throws -> Data {
        guard let bytes, bytes.count == 32 else { throw KeychainError.loadFailed(errSecDecode) }
        return bytes
    }

    func loadShared() throws -> Data? {
        guard accessGroup != nil else { throw KeychainError.loadFailed(errSecMissingEntitlement) }
        let (status, bytes) = read()
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw KeychainError.loadFailed(status) }
        return try validated(bytes)
    }

    func clear() {
        guard accessGroup != nil else { return }
        _ = operations.delete(query())
        _ = operations.delete(query(legacy: true))
    }

    func loadOrCreate() throws -> Data {
        if let shared = try loadShared() { return shared }
        let (legacyStatus, legacyBytes) = read(legacy: true)
        let bytes: Data
        switch legacyStatus {
        case errSecSuccess: bytes = try validated(legacyBytes)
        case errSecItemNotFound: bytes = try validated(makeKey())
        default: throw KeychainError.loadFailed(legacyStatus)
        }
        var insertion = query()
        insertion[kSecValueData] = bytes
        insertion[kSecAttrAccessible] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        switch operations.add(insertion) {
        case errSecSuccess: return bytes
        case errSecDuplicateItem:
            // A concurrent writer must have retained the identical recipient key.
            guard let winner = try loadShared(), winner == bytes else {
                throw KeychainError.saveFailed(errSecDuplicateItem)
            }
            return winner
        case let status: throw KeychainError.saveFailed(status)
        }
    }
}
