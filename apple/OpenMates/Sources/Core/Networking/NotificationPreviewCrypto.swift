// Device-local notification preview encryption helpers.
// Keeps the APNs notification private key in Keychain and exposes only the
// public key to the backend for encrypted preview payloads.
// Shared by the app target and Notification Service Extension so Apple only
// receives safe fallback alert text while the device can decrypt optional text.

import CryptoKit
import Foundation

enum NotificationPreviewCrypto {
    static let encryptionVersion = "x25519-aesgcm-v1"

    private static let privateKeyKeychainKey = "openmates.notificationEncryption.privateKey"
    private static let encryptionInfo = Data("openmates-apns-notification-v1".utf8)

    static func loadOrCreatePublicKey() -> String? {
        do {
            if let existingPrivateKeyData = try KeychainHelper.load(key: privateKeyKeychainKey) {
                let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: existingPrivateKeyData)
                return encodeBase64URL(privateKey.publicKey.rawRepresentation)
            }

            let privateKey = Curve25519.KeyAgreement.PrivateKey()
            try KeychainHelper.save(key: privateKeyKeychainKey, data: privateKey.rawRepresentation)
            return encodeBase64URL(privateKey.publicKey.rawRepresentation)
        } catch {
            print("[Push] Notification encryption key setup failed: \(error.localizedDescription)")
            return nil
        }
    }

    static func decryptPreview(userInfo: [AnyHashable: Any]) -> String? {
        guard let encrypted = userInfo["encrypted_notification"] as? [String: Any],
              encrypted["version"] as? String == encryptionVersion,
              let ephemeralPublicKeyValue = encrypted["ephemeral_public_key"] as? String,
              let nonceValue = encrypted["nonce"] as? String,
              let ciphertextValue = encrypted["ciphertext"] as? String,
              let privateKeyData = try? KeychainHelper.load(key: privateKeyKeychainKey),
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
            guard let envelope = try JSONSerialization.jsonObject(with: plaintext) as? [String: Any],
                  let preview = envelope["preview"] as? String,
                  !preview.isEmpty else {
                return nil
            }
            return preview
        } catch {
            print("[Push] Notification preview decrypt failed: \(error.localizedDescription)")
            return nil
        }
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
