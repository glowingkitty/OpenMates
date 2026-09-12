// Platform capability adapter for native signup; same ASAuthorization/PRF APIs
// used by PasskeyRegistrationCoordinator and PasskeyLoginCoordinator. The web
// reference is cryptoService.getPRFSignatureForPasskeyRegistration. Pure validation
// runs before any registration completion request reaches the account endpoint.
import AuthenticationServices
import CryptoKit
import Foundation

@MainActor final class NativeSignupPasskeyPlatform: NativeSignupPasskeyAuthorizer {
    var isAvailable: Bool {
        if #available(iOS 18.0, macOS 15.0, *) { return true }
        return false
    }
    func register(options: NativeSignupPasskeyOptions, challenge: Data, userID: Data, prfSalt: Data) async throws -> NativePasskeyRegistrationResult {
        guard #available(iOS 18.0, macOS 15.0, *) else { throw NativeSignupError.passkeyUnsupported }
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: options.rp.id)
        let request = provider.createCredentialRegistrationRequest(challenge: challenge, name: options.user.name, userID: userID)
        request.displayName = options.user.displayName
        request.userVerificationPreference = .required
        request.attestationPreference = .direct
        request.prf = .inputValues(.saltInput1(prfSalt))
        let result = try await NativeSignupPasskeyAuthorization.perform(request)
        guard case .registration(let registration) = result else { throw NativeSignupError.invalidPasskeyChallenge }
        return registration
    }
    func assert(rpID: String, challenge: Data, credentialID: Data, prfSalt: Data) async throws -> NativePasskeyAssertionResult {
        guard #available(iOS 18.0, macOS 15.0, *) else { throw NativeSignupError.passkeyUnsupported }
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpID)
        let request = provider.createCredentialAssertionRequest(challenge: challenge)
        request.allowedCredentials = [.init(credentialID: credentialID)]
        request.userVerificationPreference = .required
        request.prf = .inputValues(.saltInput1(prfSalt))
        let result = try await NativeSignupPasskeyAuthorization.perform(request)
        guard case .assertion(let assertion) = result else { throw NativeSignupError.invalidPasskeyChallenge }
        return assertion
    }
}

@MainActor private final class NativeSignupPasskeyAuthorization: NSObject,
    ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    enum Result { case registration(NativePasskeyRegistrationResult), assertion(NativePasskeyAssertionResult) }
    private var continuation: CheckedContinuation<Result, Error>?
    private var controller: ASAuthorizationController?
    private var cancelled = false

    static func perform(_ request: ASAuthorizationRequest) async throws -> Result {
        let operation = NativeSignupPasskeyAuthorization()
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await operation.run(request)
        } onCancel: {
            Task { @MainActor in operation.cancel() }
        }
    }
    private func run(_ request: ASAuthorizationRequest) async throws -> Result {
        try await withCheckedThrowingContinuation { continuation in
            guard !cancelled, !Task.isCancelled else { continuation.resume(throwing: CancellationError()); return }
            self.continuation = continuation
            let controller = ASAuthorizationController(authorizationRequests: [request])
            self.controller = controller
            controller.delegate = self
            controller.presentationContextProvider = self
            controller.performRequests()
        }
    }
    private func complete(_ result: Swift.Result<Result, Error>) {
        let continuation = continuation
        self.continuation = nil
        controller = nil
        continuation?.resume(with: result)
    }
    private func cancel() {
        cancelled = true
        controller?.cancel()
        complete(.failure(CancellationError()))
    }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithAuthorization authorization: ASAuthorization) {
        guard !cancelled else { return }
        if let credential = authorization.credential as? ASAuthorizationPlatformPublicKeyCredentialRegistration,
           let attestation = credential.rawAttestationObject {
            guard #available(iOS 18.0, macOS 15.0, *) else { complete(.failure(NativeSignupError.passkeyUnsupported)); return }
            complete(.success(.registration(.init(credentialID: credential.credentialID,
                clientDataJSON: credential.rawClientDataJSON, attestationObject: attestation,
                prfOutput: credential.prf?.first?.withUnsafeBytes { Data($0) }, supportsPRF: credential.prf?.isSupported))))
        } else if let credential = authorization.credential as? ASAuthorizationPlatformPublicKeyCredentialAssertion {
            guard #available(iOS 18.0, macOS 15.0, *) else { complete(.failure(NativeSignupError.passkeyUnsupported)); return }
            complete(.success(.assertion(.init(credentialID: credential.credentialID,
                clientDataJSON: credential.rawClientDataJSON, authenticatorData: credential.rawAuthenticatorData,
                signature: credential.signature, userHandle: credential.userID,
                prfOutput: credential.prf?.first.withUnsafeBytes { Data($0) }))))
        } else { complete(.failure(NativeSignupError.invalidPasskeyChallenge)) }
    }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        if (error as? ASAuthorizationError)?.code == .canceled { complete(.failure(NativeSignupError.passkeyCancelled)) }
        else { complete(.failure(error)) }
    }
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        #if os(iOS)
        return UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
            .first { $0.isKeyWindow } ?? ASPresentationAnchor()
        #elseif os(macOS)
        return NSApplication.shared.keyWindow ?? ASPresentationAnchor()
        #endif
    }
}

enum NativePasskeyValidation {
    static func challenge(_ encoded: String) throws -> Data {
        guard encoded.utf8.count <= 128, let data = Data(base64URLEncoded: encoded), data.count == 32 else {
            throw NativeSignupError.invalidPasskeyChallenge
        }
        return data
    }
    static func prfSalt(rpID: String, extensions: PasskeyAssertionExtensions?, profile: ServerProfile) throws -> Data {
        guard profile.webBaseURL.scheme == "https", rpID == profile.webBaseURL.host,
              let encoded = extensions?.prf?.eval?.first, let salt = Data(base64URLEncoded: encoded),
              salt == Data(SHA256.hash(data: Data(rpID.utf8))) else { throw NativeSignupError.invalidPasskeyChallenge }
        // The current server contract is SHA256(rpID) on create AND get. Never
        // substitute an ephemeral challenge: that would make future unwrap fail.
        return salt
    }
    static func prf(_ output: Data?) throws -> Data {
        guard let output, output.count == 32 else { throw NativeSignupError.passkeyUnsupported }
        return output
    }
    static func clientData(_ data: Data, type: String, challenge: Data, profile: ServerProfile) throws {
        struct ClientData: Decodable { let type: String; let challenge: String; let origin: String; let crossOrigin: Bool? }
        guard data.count <= 16_384, let value = try? JSONDecoder().decode(ClientData.self, from: data),
              value.type == type, value.crossOrigin != true, Data(base64URLEncoded: value.challenge) == challenge,
              let origin = URLComponents(string: value.origin), origin.scheme == "https",
              origin.host == profile.webBaseURL.host, origin.port == profile.webBaseURL.port,
              origin.user == nil, origin.password == nil, origin.query == nil, origin.fragment == nil,
              origin.path.isEmpty || origin.path == "/" else { throw NativeSignupError.invalidPasskeyChallenge }
    }
    static func registrationAuthenticatorData(_ result: NativePasskeyRegistrationResult, rpID: String) throws -> Data {
        guard !result.credentialID.isEmpty, result.credentialID.count <= 1_024 else { throw NativeSignupError.invalidPasskeyChallenge }
        var reader = AttestationReader(data: result.attestationObject)
        let data = try reader.authenticatorData()
        try validateAuthenticatorData(data, rpID: rpID)
        let bytes = [UInt8](data)
        guard bytes.count >= 55, bytes[32] & 0x40 != 0 else { throw NativeSignupError.invalidPasskeyChallenge }
        let count = Int(bytes[53]) * 256 + Int(bytes[54])
        guard count > 0, count <= 1_024, bytes.count > 55 + count,
              Data(bytes[55..<(55 + count)]) == result.credentialID else { throw NativeSignupError.invalidPasskeyChallenge }
        return data
    }
    static func assertion(_ result: NativePasskeyAssertionResult, credentialID: Data, userID: Data, challenge: Data, profile: ServerProfile) throws {
        guard result.credentialID == credentialID,
              result.userHandle == nil || result.userHandle?.isEmpty == true || result.userHandle == userID,
              !result.signature.isEmpty, result.signature.count <= 1_024 else {
            throw NativeSignupError.sessionProofMismatch
        }
        try clientData(result.clientDataJSON, type: "webauthn.get", challenge: challenge, profile: profile)
        try validateAuthenticatorData(result.authenticatorData, rpID: profile.webBaseURL.host ?? "")
    }
    private static func validateAuthenticatorData(_ data: Data, rpID: String) throws {
        let bytes = [UInt8](data)
        guard bytes.count >= 37, bytes.count <= 65_536,
              Data(bytes.prefix(32)) == Data(SHA256.hash(data: Data(rpID.utf8))),
              bytes[32] & 0x05 == 0x05 else { throw NativeSignupError.invalidPasskeyChallenge }
    }

    // Bounded CBOR extraction. Apple's attestation is a definite-length map;
    // authData is the byte string, not the first37 bytes of the CBOR envelope.
    // Do not interpret/verify the COSE key here; the backend verifies attestation.
    private struct AttestationReader {
        let bytes: [UInt8]
        var offset = 0
        init(data: Data) { bytes = Array(data) }
        mutating func authenticatorData() throws -> Data {
            guard !bytes.isEmpty, bytes.count <= 65_536 else { throw NativeSignupError.invalidPasskeyChallenge }
            let (major, count) = try header()
            guard major == 5, count <= 32 else { throw NativeSignupError.invalidPasskeyChallenge }
            var result: Data?
            for _ in 0..<count {
                let (keyType, keyCount) = try header()
                guard keyType == 3, keyCount <= 128 else { throw NativeSignupError.invalidPasskeyChallenge }
                let key = try consume(keyCount)
                if String(bytes: key, encoding: .utf8) == "authData" {
                    guard result == nil else { throw NativeSignupError.invalidPasskeyChallenge }
                    let (type, length) = try header()
                    guard type == 2 else { throw NativeSignupError.invalidPasskeyChallenge }
                    result = Data(try consume(length))
                } else { try skip(depth: 0) }
            }
            guard offset == bytes.count, let result else { throw NativeSignupError.invalidPasskeyChallenge }
            return result
        }
        mutating func consume(_ count: Int) throws -> ArraySlice<UInt8> {
            guard count >= 0, count <= bytes.count - offset else { throw NativeSignupError.invalidPasskeyChallenge }
            defer { offset += count }
            return bytes[offset..<(offset + count)]
        }
        mutating func header() throws -> (Int, Int) {
            guard let value = try consume(1).first else { throw NativeSignupError.invalidPasskeyChallenge }
            let additional = Int(value & 31)
            if additional < 24 { return (Int(value >> 5), additional) }
            guard additional <= 27 else { throw NativeSignupError.invalidPasskeyChallenge }
            let length = 1 << (additional - 24)
            var number: UInt64 = 0
            for byte in try consume(length) { number = number << 8 | UInt64(byte) }
            guard number <= UInt64(Int.max) else { throw NativeSignupError.invalidPasskeyChallenge }
            return (Int(value >> 5), Int(number))
        }
        mutating func skip(depth: Int) throws {
            guard depth <= 8 else { throw NativeSignupError.invalidPasskeyChallenge }
            let (major, count) = try header()
            switch major {
            case 0, 1, 7: return
            case 2, 3: _ = try consume(count)
            case 4, 5:
                guard count <= 256 else { throw NativeSignupError.invalidPasskeyChallenge }
                for _ in 0..<(major == 5 ? count * 2 : count) { try skip(depth: depth + 1) }
            case 6: try skip(depth: depth + 1)
            default: throw NativeSignupError.invalidPasskeyChallenge
            }
        }
    }
}
