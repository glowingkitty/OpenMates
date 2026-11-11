// Ephemeral native OPAQUE binding for pair login and password-v2 key
// derivation. Both run in the shared Rust client core (UniFFI bindings in
// apple/OpenMatesCore, crate packages/openmates-apple-bindings); Swift only
// passes values through. No setup, record, PIN, or session key is persisted or
// sent to the relay.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.pair-login.single-use-zk, auth.keys.client-wrapped

import CryptoKit
import Foundation

enum PairOpaqueError: Error {
    case invalidExchange
}

/// Typed pass-through to the core's OPAQUE steps. Every core failure
/// (`CoreError`: malformed input, wrong PIN, wrong identifiers) surfaces as
/// `PairOpaqueError.invalidExchange`, the one error the pair-login flows and
/// their UI already handle; the core error is never shown or logged with values.
/// All calls are synchronous and CPU-bound; call them off the main actor.
enum PairOpaque {
    static func serverSetup() -> String {
        createServerSetup()
    }

    static func clientRegistrationStart(pin: String) throws -> ClientRegistrationStartRecord {
        try mapped { try startClientRegistration(password: pin) }
    }

    static func serverRegistrationResponse(
        serverSetup: String, userIdentifier: String, registrationRequest: String
    ) throws -> String {
        try mapped {
            try createServerRegistrationResponse(
                serverSetup: serverSetup, userIdentifier: userIdentifier,
                registrationRequest: registrationRequest)
        }
    }

    static func clientRegistrationFinish(
        pin: String, state: String, registrationResponse: String, identifiers: OpaqueIdentifiersRecord
    ) throws -> String {
        try mapped {
            try finishClientRegistration(
                password: pin, clientRegistrationState: state,
                registrationResponse: registrationResponse, identifiers: identifiers)
        }
    }

    static func clientLoginStart(pin: String) throws -> ClientLoginStartRecord {
        try mapped { try startClientLogin(password: pin) }
    }

    static func serverLoginStart(
        serverSetup: String, registrationRecord: String, startLoginRequest: String,
        userIdentifier: String, identifiers: OpaqueIdentifiersRecord
    ) throws -> ServerLoginStartRecord {
        try mapped {
            try startServerLogin(
                serverSetup: serverSetup, registrationRecord: registrationRecord,
                startLoginRequest: startLoginRequest, userIdentifier: userIdentifier,
                identifiers: identifiers)
        }
    }

    static func clientLoginFinish(
        pin: String, state: String, loginResponse: String, identifiers: OpaqueIdentifiersRecord
    ) throws -> ClientLoginFinishRecord {
        try mapped {
            try finishClientLogin(
                password: pin, clientLoginState: state,
                loginResponse: loginResponse, identifiers: identifiers)
        }
    }

    /// Returns the 64-byte session key (base64url), equal to the client's.
    static func serverLoginFinish(
        state: String, finishLoginRequest: String, identifiers: OpaqueIdentifiersRecord
    ) throws -> String {
        try mapped {
            try finishServerLogin(
                serverLoginState: state, finishLoginRequest: finishLoginRequest,
                identifiers: identifiers)
        }
    }

    static func passwordV2Keys(password: String, salt: Data) throws -> PasswordV2KeysRecord {
        try mapped { try derivePasswordV2(password: password, salt: salt) }
    }

    private static func mapped<T>(_ body: () throws -> T) throws -> T {
        do {
            return try body()
        } catch is CoreError {
            throw PairOpaqueError.invalidExchange
        }
    }
}

/// Version 2 account-password keys. The Rust core runs Argon2id and HKDF; Swift
/// never substitutes a weaker or platform-specific KDF.
struct PasswordV2Keys {
    let authenticationKey: Data
    let wrappingKey: SymmetricKey

    init(password: String, emailSalt: Data) throws {
        guard emailSalt.count == 16 else { throw PairOpaqueError.invalidExchange }
        let keys = try PairOpaque.passwordV2Keys(password: password, salt: emailSalt)
        guard keys.authKey.count == 32, keys.wrapKey.count == 32 else {
            throw PairOpaqueError.invalidExchange
        }
        authenticationKey = keys.authKey
        wrappingKey = SymmetricKey(data: keys.wrapKey)
    }
    func proof(purpose: String, nonce: Data) throws -> String {
        guard !purpose.isEmpty, purpose.utf8.count <= 64, nonce.count == 32,
              purpose.utf8.allSatisfy({ $0 >= 0x21 && $0 <= 0x7e }) else {
            throw PairOpaqueError.invalidExchange
        }
        var message = Data("openmates/password-v2/proof\0".utf8)
        message.append(contentsOf: purpose.utf8)
        message.append(0)
        message.append(nonce)
        let mac = HMAC<SHA256>.authenticationCode(for: message, using: SymmetricKey(data: authenticationKey))
        return Data(mac).base64URLEncodedString()
    }
}

struct PairV2Context: Equatable {
    let token: String
    let sessionID: String
    let receiverTokenHash: String
    let authorizerUserID: String
    let autoLogoutMinutes: Int?
    let bytes: Data
    let string: String

    init(token: String, sessionID: String, receiverTokenHash: String,
         authorizerUserID: String, autoLogoutMinutes: Int?) throws {
        func validASCII(_ value: String, max: Int) -> Bool {
            !value.isEmpty && value.utf8.count <= max &&
                value.utf8.allSatisfy { (0x21...0x7e).contains($0) }
        }
        guard token.range(of: "^[A-Z0-9]{6}$", options: .regularExpression) != nil,
              validASCII(sessionID, max: 128),
              receiverTokenHash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              validASCII(authorizerUserID, max: 128),
              autoLogoutMinutes.map { [30, 60, 240, 480, 1440].contains($0) } ?? true else {
            throw PairOpaqueError.invalidExchange
        }
        let fields: [Any] = [
            "openmates-pair", 2, token, sessionID,
            receiverTokenHash, authorizerUserID,
            autoLogoutMinutes.map { $0 as Any } ?? NSNull()
        ]
        let encoded = try JSONSerialization.data(withJSONObject: fields, options: [.withoutEscapingSlashes])
        guard encoded.count <= 512, let context = String(data: encoded, encoding: .utf8) else {
            throw PairOpaqueError.invalidExchange
        }
        self.token = token
        self.sessionID = sessionID
        self.receiverTokenHash = receiverTokenHash
        self.authorizerUserID = authorizerUserID
        self.autoLogoutMinutes = autoLogoutMinutes
        self.bytes = encoded
        self.string = context
    }

    var identifiers: OpaqueIdentifiersRecord {
        OpaqueIdentifiersRecord(
            client: "openmates-pair-v2/client/\(string)",
            server: "openmates-pair-v2/server/\(string)"
        )
    }

    var userIdentifier: String { string }
}

enum PairV2Crypto {
    static func encode(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    static func decode(_ value: String) throws -> Data {
        guard !value.isEmpty, value.utf8.count <= 87_384,
              value.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil else {
            throw PairOpaqueError.invalidExchange
        }
        let base64 = value.replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padded = base64 + String(repeating: "=", count: (4 - base64.count % 4) % 4)
        guard let data = Data(base64Encoded: padded), encode(data) == value else {
            throw PairOpaqueError.invalidExchange
        }
        return data
    }

    static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func key(sessionKey: String, context: PairV2Context) throws -> SymmetricKey {
        let input = try decode(sessionKey)
        guard input.count == 64 else { throw PairOpaqueError.invalidExchange }
        let salt = Data(SHA256.hash(data: context.bytes))
        return HKDF<SHA256>.deriveKey(
            inputKeyMaterial: SymmetricKey(data: input),
            salt: salt,
            info: Data("openmates-pair-v2/bundle".utf8),
            outputByteCount: 32
        )
    }

    static func seal(_ plaintext: Data, sessionKey: String, context: PairV2Context) throws -> (ciphertext: String, iv: String) {
        let nonce = AES.GCM.Nonce()
        let sealed = try AES.GCM.seal(plaintext, using: key(sessionKey: sessionKey, context: context), nonce: nonce, authenticating: context.bytes)
        return (encode(Data(sealed.ciphertext + sealed.tag)), encode(Data(nonce)))
    }

    static func open(ciphertext: String, iv: String, sessionKey: String, context: PairV2Context) throws -> Data {
        guard ciphertext.utf8.count <= 65_536, iv.utf8.count <= 64 else {
            throw PairOpaqueError.invalidExchange
        }
        let sealedData = try decode(ciphertext)
        let nonceData = try decode(iv)
        guard sealedData.count >= 16, nonceData.count == 12 else {
            throw PairOpaqueError.invalidExchange
        }
        let box = try AES.GCM.SealedBox(
            nonce: AES.GCM.Nonce(data: nonceData),
            ciphertext: sealedData.dropLast(16),
            tag: sealedData.suffix(16)
        )
        return try AES.GCM.open(box, using: key(sessionKey: sessionKey, context: context), authenticating: context.bytes)
    }
}
