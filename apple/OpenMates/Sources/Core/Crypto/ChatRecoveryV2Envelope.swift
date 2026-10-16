// Crypto compatibility for the published synthetic chat_recovery_output_v2
// fixture. This reader does not implement discovery, persistence, or replay.
import CryptoKit
import Foundation

struct ChatRecoveryV2Envelope: Decodable, Sendable {
    struct Identity: Decodable, Sendable {
        let ownerId: String
        let rootChatId: String
        let targetChatId: String
        let turnId: String
        let recordId: String
        let subjectId: String
        // The published crypto contract authenticates this string. Output-kind
        // schemas and replay routing remain the responsibility of future APIs.
        let outputKind: String
        let keyVersion: UInt32
        let outputVersion: UInt32

        private enum CodingKeys: String, CodingKey, CaseIterable {
            case ownerId = "owner_id", rootChatId = "root_chat_id", targetChatId = "target_chat_id"
            case turnId = "turn_id", recordId = "record_id", subjectId = "subject_id"
            case outputKind = "output_kind", keyVersion = "key_version", outputVersion = "output_version"
        }

        init(from decoder: Decoder) throws {
            try ChatRecoveryV2Envelope.requireKeys(CodingKeys.allCases.map(\.rawValue), decoder: decoder)
            let values = try decoder.container(keyedBy: CodingKeys.self)
            ownerId = try values.decode(String.self, forKey: .ownerId)
            rootChatId = try values.decode(String.self, forKey: .rootChatId)
            targetChatId = try values.decode(String.self, forKey: .targetChatId)
            turnId = try values.decode(String.self, forKey: .turnId)
            recordId = try values.decode(String.self, forKey: .recordId)
            subjectId = try values.decode(String.self, forKey: .subjectId)
            outputKind = try values.decode(String.self, forKey: .outputKind)
            keyVersion = try values.decode(UInt32.self, forKey: .keyVersion)
            outputVersion = try values.decode(UInt32.self, forKey: .outputVersion)
            // Validate before exposing an identity, including when no decryption
            // is attempted. UUID case is part of the authenticated encoding.
            _ = try associatedData()
        }

        func associatedData() throws -> Data {
            var aad = Data("OMCR2".utf8)
            for (value, field) in [(ownerId, "owner_id"), (rootChatId, "root_chat_id"),
                (targetChatId, "target_chat_id"), (turnId, "turn_id"), (recordId, "record_id")] {
                guard UUID(uuidString: value)?.uuidString.lowercased() == value else {
                    throw Failure.invalidIdentity(field)
                }
                try ChatRecoveryV2Envelope.append(value, field: field, to: &aad)
            }
            try ChatRecoveryV2Envelope.append(subjectId, field: "subject_id", to: &aad)
            try ChatRecoveryV2Envelope.append(outputKind, field: "output_kind", to: &aad)
            guard keyVersion > 0, outputVersion > 0 else { throw Failure.invalidIdentity("version") }
            ChatRecoveryV2Envelope.append(keyVersion, to: &aad)
            ChatRecoveryV2Envelope.append(outputVersion, to: &aad)
            return aad
        }
    }

    enum Failure: Error, Equatable {
        case invalidShape, unsupportedVersion, invalidIdentity(String)
        case invalidEncoding(String), invalidLength(String), invalidSharedSecret
    }

    let v: UInt32
    let epk: String
    let nonce: String
    let ciphertext: String

    private enum CodingKeys: String, CodingKey, CaseIterable { case v, epk, nonce, ciphertext }

    init(from decoder: Decoder) throws {
        try Self.requireKeys(CodingKeys.allCases.map(\.rawValue), decoder: decoder)
        let values = try decoder.container(keyedBy: CodingKeys.self)
        v = try values.decode(UInt32.self, forKey: .v)
        guard v == 2 else { throw Failure.unsupportedVersion }
        epk = try values.decode(String.self, forKey: .epk)
        nonce = try values.decode(String.self, forKey: .nonce)
        ciphertext = try values.decode(String.self, forKey: .ciphertext)
        guard try Self.decodeBase64URL(epk, field: "epk").count == 32 else { throw Failure.invalidLength("epk") }
        guard try Self.decodeBase64URL(nonce, field: "nonce").count == 12 else { throw Failure.invalidLength("nonce") }
        guard try Self.decodeBase64URL(ciphertext, field: "ciphertext").count >= 16 else {
            throw Failure.invalidLength("ciphertext")
        }
    }

    /// Returns only authenticated bytes. Callers must independently enforce
    /// current account/Team scope and the eventual typed persistence contract.
    func open(recoveryPrivateKey: String, identity: Identity) throws -> Data {
        let privateBytes = try Self.decodeBase64URL(recoveryPrivateKey, field: "recovery_private_key")
        guard privateBytes.count == 32 else { throw Failure.invalidLength("recovery_private_key") }
        let privateKey = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: privateBytes)
        let ephemeral = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: Self.decodeBase64URL(epk, field: "epk"))
        let sharedSecret = try privateKey.sharedSecretFromKeyAgreement(with: ephemeral)
        guard sharedSecret.withUnsafeBytes({ $0.contains(where: { $0 != 0 }) }) else { throw Failure.invalidSharedSecret }
        let aad = try identity.associatedData()
        // v2 intentionally retains the v1 envelope salt, with OMCR2 in AAD.
        let key = sharedSecret.hkdfDerivedSymmetricKey(using: SHA256.self,
            salt: Data(SHA256.hash(data: Data("openmates:chat-recovery-envelope:v1".utf8))),
            sharedInfo: Data(SHA256.hash(data: aad)), outputByteCount: 32)
        let sealedBytes = try Self.decodeBase64URL(ciphertext, field: "ciphertext")
        let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: Self.decodeBase64URL(nonce, field: "nonce")),
            ciphertext: sealedBytes.dropLast(16), tag: sealedBytes.suffix(16))
        return try AES.GCM.open(box, using: key, authenticating: aad)
    }

    private static func append(_ value: String, field: String, to data: inout Data) throws {
        let bytes = Data(value.utf8)
        guard !bytes.isEmpty, let count = UInt32(exactly: bytes.count) else { throw Failure.invalidIdentity(field) }
        append(count, to: &data)
        data.append(bytes)
    }

    private static func append(_ value: UInt32, to data: inout Data) {
        var bigEndian = value.bigEndian
        withUnsafeBytes(of: &bigEndian) { data.append(contentsOf: $0) }
    }

    private static func decodeBase64URL(_ value: String, field: String) throws -> Data {
        guard !value.isEmpty, value.utf8.allSatisfy({
            (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95
        }) else { throw Failure.invalidEncoding(field) }
        let base64 = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        guard let bytes = Data(base64Encoded: base64 + String(repeating: "=", count: (4 - base64.count % 4) % 4)),
              bytes.base64EncodedString().replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") == value else {
            throw Failure.invalidEncoding(field)
        }
        return bytes
    }

    private struct AnyKey: CodingKey {
        let stringValue: String
        let intValue: Int? = nil
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }

    private static func requireKeys(_ keys: [String], decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: AnyKey.self)
        guard Set(values.allKeys.map(\.stringValue)) == Set(keys) else { throw Failure.invalidShape }
    }
}
