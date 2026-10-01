import CryptoKit
import Foundation

struct ProjectRemoteResultError: Error {
    let code: String
}

// Matches projectRemoteAccessCrypto.ts. The backend routes ciphertext only.
enum ProjectRemoteBridgeCrypto {
    struct Identity {
        let ownerID: String
        let projectID: String
        let sourceID: String
        let sourceSessionID: String
        let requestingClientID: String
        let keyEpoch: Int
        let team: TeamRouting?

        var version: Int { team == nil ? 1 : 2 }
        var values: [Any] {
            if let team {
                return [ownerID, "team", team.contextID, projectID, sourceID, sourceSessionID,
                        requestingClientID, team.hostMemberID, team.hostDeviceID,
                        team.requesterMemberID, team.requesterDeviceID, keyEpoch]
            }
            return [ownerID, projectID, sourceID, sourceSessionID, requestingClientID, keyEpoch]
        }
    }

    struct TeamRouting {
        let contextID: String
        let hostMemberID: String
        let hostDeviceID: String
        let requesterMemberID: String
        let requesterDeviceID: String
    }

    struct Handshake: Codable {
        let version: Int
        let role: String
        let publicKey: String
        let authenticationTag: String

        enum CodingKeys: String, CodingKey {
            case version, role
            case publicKey = "publicKey"
            case authenticationTag = "authenticationTag"
        }
    }

    struct Envelope: Decodable {
        let version: Int
        let nonce: String
        let ciphertext: String
    }

    struct ResultPayload: Decodable {
        let sourceHandshake: Handshake
        let envelope: Envelope
        enum CodingKeys: String, CodingKey {
            case sourceHandshake = "source_handshake"
            case envelope
        }
    }

    struct Requester {
        let privateKey: Curve25519.KeyAgreement.PrivateKey
        let handshake: Handshake
    }

    static func makeRequester(projectKey: SymmetricKey, identity: Identity) throws -> Requester {
        try validate(identity)
        let privateKey = Curve25519.KeyAgreement.PrivateKey()
        let publicKey = encodeBase64URL(privateKey.publicKey.rawRepresentation)
        let tag = try authenticate(projectKey: projectKey, identity: identity, role: "requester", publicKey: publicKey)
        return Requester(privateKey: privateKey,
                         handshake: Handshake(version: identity.version, role: "requester",
                                              publicKey: publicKey, authenticationTag: tag))
    }

    static func openResult(_ payload: ResultPayload, projectKey: SymmetricKey, identity: Identity,
                           requestID: String, requester: Requester) throws -> [String: Any] {
        try validate(identity)
        guard payload.sourceHandshake.version == identity.version,
              payload.sourceHandshake.role == "source",
              payload.envelope.version == identity.version,
              !requestID.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
        let sourceKeyData = try decodeBase64URL(payload.sourceHandshake.publicKey, expectedCount: 32)
        let sourceTag = try decodeBase64URL(payload.sourceHandshake.authenticationTag, expectedCount: 32)
        let handshakeAAD = try encoded(["OMRA-HANDSHAKE-\(identity.version)"] + identity.values
            + ["source", payload.sourceHandshake.publicKey])
        guard HMAC<SHA256>.isValidAuthenticationCode(sourceTag, authenticating: handshakeAAD,
                                                     using: projectKey) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let sourcePublicKey = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: sourceKeyData)
        let shared = try requester.privateKey.sharedSecretFromKeyAgreement(with: sourcePublicKey)
        let sharedData = shared.withUnsafeBytes { Data($0) }
        guard sharedData.contains(where: { $0 != 0 }) else { throw ProjectsWorkspaceError.invalidResponse }
        let transcript = try encoded(["OMRA-TRANSCRIPT-\(identity.version)"] + identity.values
            + [requester.handshake.publicKey, payload.sourceHandshake.publicKey])
        let info = Data(SHA256.hash(data: transcript))
        let sessionKey = HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: sharedData),
            salt: Data("openmates:project-remote-access:v\(identity.version)".utf8),
            info: info, outputByteCount: 32)
        let nonceData = try decodeBase64URL(payload.envelope.nonce, expectedCount: 12)
        let encrypted = try decodeBase64URL(payload.envelope.ciphertext)
        guard encrypted.count >= 16, encrypted.count <= 200 * 1024 + 16 else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let aad = try encoded(["OMRA-ENVELOPE-\(identity.version)"] + identity.values
            + [requestID, "result"])
        let sealed = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: nonceData),
            ciphertext: Data(encrypted.dropLast(16)), tag: Data(encrypted.suffix(16)))
        let plaintext = try AES.GCM.open(sealed, using: sessionKey, authenticating: aad)
        guard let object = try JSONSerialization.jsonObject(with: plaintext) as? [String: Any] else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        if object["ok"] as? Bool == false {
            let code = object["error"] as? String ?? "operation_failed"
            guard code.range(of: "^[a-z][a-z0-9_]{0,63}$", options: .regularExpression) != nil else {
                throw ProjectsWorkspaceError.invalidResponse
            }
            throw ProjectRemoteResultError(code: code)
        }
        guard object["ok"] as? Bool == true,
              let result = object["result"] as? [String: Any] else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        return result
    }

    private static func authenticate(projectKey: SymmetricKey, identity: Identity,
                                     role: String, publicKey: String) throws -> String {
        let aad = try encoded(["OMRA-HANDSHAKE-\(identity.version)"] + identity.values + [role, publicKey])
        let code = HMAC<SHA256>.authenticationCode(for: aad, using: projectKey)
        return encodeBase64URL(Data(code))
    }

    private static func validate(_ identity: Identity) throws {
        guard identity.keyEpoch >= 1,
              identity.values.compactMap({ $0 as? String }).allSatisfy({ !$0.isEmpty && $0.count <= 128 }) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
    }

    private static func encoded(_ values: [Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: values, options: [.fragmentsAllowed])
    }

    private static func encodeBase64URL(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private static func decodeBase64URL(_ value: String, expectedCount: Int? = nil) throws -> Data {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        guard !value.isEmpty, value.rangeOfCharacter(from: allowed.inverted) == nil else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let base64 = value.replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padded = base64 + String(repeating: "=", count: (4 - base64.count % 4) % 4)
        guard let data = Data(base64Encoded: padded), encodeBase64URL(data) == value,
              expectedCount == nil || data.count == expectedCount else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        return data
    }
}
