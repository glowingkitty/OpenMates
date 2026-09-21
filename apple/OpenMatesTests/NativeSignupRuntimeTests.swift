// Contract fixtures use synthetic data and an injected transport, never live auth.
import CryptoKit
import Foundation
import Sodium
import XCTest
@testable import OpenMates

@MainActor final class NativeSignupRuntimeTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testPasswordMaterialMatchesIndependentWebCryptoVectorAndNaClEnvelope() async throws {
        let random = SignupVectorBytes()
        let material = try await CryptoManager.shared.prepareNativeSignupPassword("OrchidMeadow1!",
            form: form, configuration: config, random: { random.next($0) })
        let request = material.request
        XCTAssertEqual(request.hashedEmail, "cVv+0qOZTjYkxduzm3M+Gf8R/fU5X+6awyGBl9US08I=")
        XCTAssertEqual(request.lookupHash, "JYnzsYvQLRIWfisPfF13eAQzB4+jdYYQPDIHNDNxuHU=")
        XCTAssertEqual(request.salt, "ICEiIyQlJicoKSorLC0uLw==")
        XCTAssertEqual(request.userEmailSalt, "MDEyMzQ1Njc4OTo7PD0+Pw==")
        XCTAssertEqual(request.keyIv, "QEFCQ0RFRkdISUpL")
        XCTAssertEqual(request.encryptedMasterKey, "Q4913K+wSeMDG/KfHWhtInR671zI3rbBSrtU07qioQiepO5DNgMYx0ikIxZKmvR0")
        XCTAssertEqual(material.masterKey.withUnsafeBytes { Data($0).base64EncodedString() }, "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
        let emailKey = try XCTUnwrap(Data(base64Encoded: "ae4lhOTpPXlB4ixOaqCXHO5FS0+1JWpAIgz05XjFzQg="))
        let envelope = try XCTUnwrap(Data(base64Encoded: request.encryptedEmail))
        XCTAssertEqual(envelope.count, 24 + 16 + form.email.utf8.count)
        XCTAssertEqual(Array(envelope.prefix(24)), Array(UInt8(76)...UInt8(99)))
        let opened = Sodium().secretBox.open(nonceAndAuthenticatedCipherText: Array(envelope), secretKey: Array(emailKey))
        XCTAssertEqual(opened, Array(form.email.utf8))
        var tampered = Array(envelope); tampered[tampered.count - 1] ^= 1
        XCTAssertNil(Sodium().secretBox.open(nonceAndAuthenticatedCipherText: tampered, secretKey: Array(emailKey)))
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(request)) as? [String: Any])
        XCTAssertEqual(Set(body.keys), Set(["hashed_email", "encrypted_email", "user_email_salt", "username", "invite_code", "encrypted_master_key", "key_iv", "salt", "lookup_hash", "language", "darkmode"]))
        XCTAssertNil(body["password"]); XCTAssertNil(body["email"]); XCTAssertNil(body["master_key"])
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testMalformedRandomBytesFailBeforeProducingCredentialMaterial() async {
        do {
            _ = try await CryptoManager.shared.prepareNativeSignupPassword("OrchidMeadow1!", form: form,
                configuration: config, random: { Data(repeating: 0, count: max(0, $0 - 1)) })
            XCTFail("Invalid nonce/key length must fail")
        } catch { XCTAssertEqual(error as? NativeSignupError, .invalidCryptoMaterial) }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testTypedTransportUsesActualRoutesAndExactEmailConfirmationPayload() async throws {
        var requests: [(String, [String: Any])] = []
        let runtime = NativeSignupLiveRuntime(serverProfile: .development, sessionId: "fixture-session", contextIsCurrent: { true }) { method, path, bytes in
            let body = try bytes.map { try XCTUnwrap(JSONSerialization.jsonObject(with: $0) as? [String: Any]) } ?? [:]
            requests.append((path, body))
            switch path {
            case "/v1/auth/session":
                XCTAssertEqual(method, .post); XCTAssertEqual(body["session_id"] as? String, "fixture-session")
                return Data(#"{"success":false,"require_invite_code":true}"#.utf8)
            case "/v1/settings/server-status":
                XCTAssertEqual(method, .get)
                return Data(#"{"is_self_hosted":false}"#.utf8)
            case "/v1/auth/check_invite_token_valid": return Data(#"{"valid":true,"message":"ok"}"#.utf8)
            case "/v1/auth/check_username_valid": return Data(#"{"available":true,"message":"ok"}"#.utf8)
            default: return Data(#"{"success":true,"message":"ok"}"#.utf8)
            }
        }
        let requirements = try await runtime.requirements()
        XCTAssertEqual(requirements, .init(requiresInvite: true, isSelfHosted: false))
        try await runtime.validateBasics(form, configuration: config, requirements: requirements)
        try await runtime.requestEmailCode(form, configuration: config)
        try await runtime.confirmEmail("123456", form: form, configuration: config)
        XCTAssertEqual(requests.map(\.0), ["/v1/auth/session", "/v1/settings/server-status", "/v1/auth/check_invite_token_valid", "/v1/auth/check_username_valid", "/v1/auth/request_confirm_email_code", "/v1/auth/check_confirm_email_code"])
        let confirmation = try XCTUnwrap(requests.last?.1)
        XCTAssertEqual(Set(confirmation.keys), Set(["code", "email", "username", "invite_code", "language", "darkmode"]))
        XCTAssertEqual(confirmation["email"] as? String, form.email)
        XCTAssertEqual(confirmation["username"] as? String, form.username)
        XCTAssertEqual(confirmation["invite_code"] as? String, "fixture-invite")
        XCTAssertEqual(confirmation["language"] as? String, "de")
        XCTAssertEqual(confirmation["darkmode"] as? Bool, true)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testDelayedRequirementsFromOldSessionAreRejected() async {
        let gate = SignupTransportGate()
        var current = true
        let runtime = NativeSignupLiveRuntime(serverProfile: .development, sessionId: "old-session", contextIsCurrent: { current }) { _, _, _ in
            await gate.suspend()
            return Data(#"{"success":false,"require_invite_code":false}"#.utf8)
        }
        let task = Task { try await runtime.requirements() }
        await gate.waitUntilStarted()
        current = false
        gate.resume()
        do { _ = try await task.value; XCTFail("Stale requirements must not advance") }
        catch { XCTAssertEqual(error as? NativeSignupError, .staleContext) }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testInvalidCodesNeverReachTransportAndNewsletterRequiresExplicitOptIn() async throws {
        var paths: [String] = []
        let runtime = NativeSignupLiveRuntime(serverProfile: .development, sessionId: "fixture", contextIsCurrent: { true }) { _, path, _ in
            paths.append(path); return Data(#"{"success":true,"message":"ok"}"#.utf8)
        }
        for code in ["12345", "١٢٣٤٥٦", "abcdef"] {
            do { try await runtime.confirmEmail(code, form: form, configuration: config); XCTFail("Invalid code") }
            catch { XCTAssertEqual(error as? NativeSignupError, .invalidEmailCode) }
        }
        try await runtime.subscribeNewsletter(form, configuration: config)
        XCTAssertTrue(paths.isEmpty)
        var optedIn = form; optedIn.newsletter = true
        try await runtime.subscribeNewsletter(optedIn, configuration: config)
        XCTAssertEqual(paths, ["/v1/newsletter/subscribe"])
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testLoginProofRequiresSameUserWrappersAndMasterKeyBeforeAccountPublication() throws {
        let request = fixtureMaterial.request
        let proof = NativeSignupLoginProof(serverProfile: .development, sessionId: "fixture", expectedUserId: "created-user", masterKey: fixtureMaterial.masterKey, request: request)
        var user: [String: Any] = ["id": "created-user", "username": "Fixture", "encrypted_key": request.encryptedMasterKey, "key_iv": request.keyIv, "salt": request.salt, "user_email_salt": request.userEmailSalt]
        func response(_ user: [String: Any], extra: [String: Any] = [:]) throws -> LoginResponse {
            var payload: [String: Any] = ["success": true, "user": user]
            payload.merge(extra) { _, new in new }
            let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
            return try decoder.decode(LoginResponse.self, from: JSONSerialization.data(withJSONObject: payload))
        }
        XCTAssertTrue(proof.validates(try response(user)))
        for field in ["id", "encrypted_key", "key_iv", "salt", "user_email_salt"] {
            var changed = user; changed[field] = "other-value"
            XCTAssertFalse(proof.validates(try response(changed)), field)
        }
        XCTAssertFalse(proof.validates(try response(user, extra: ["tfa_required": true])))
        XCTAssertFalse(proof.validates(try response(user, extra: ["needs_device_verification": true])))
        XCTAssertTrue(proof.validatesMasterKey(fixtureMaterial.masterKey))
        XCTAssertFalse(proof.validatesMasterKey(SymmetricKey(data: Data(repeating: 9, count: 32))))
        user["salt"] = nil
        XCTAssertFalse(proof.validates(try response(user)))
    }
    private var form: SignupBasicsForm { .init(email: "fixture@example.test", username: "Fixture", termsAccepted: true, privacyAccepted: true) }
    private var config: SignupBasicsConfiguration { .init(inviteCode: "fixture-invite", language: "de", darkmode: true) }
    private var fixtureMaterial: NativeSignupPasswordMaterial {
        .init(request: .init(hashedEmail: "hash", encryptedEmail: "email-envelope", userEmailSalt: "email-salt", username: "Fixture", inviteCode: "", encryptedMasterKey: "wrapped", keyIv: "iv", salt: "salt", lookupHash: "lookup", language: "en", darkmode: false, pendingGiftCardCode: nil), masterKey: SymmetricKey(data: Data(repeating: 1, count: 32)))
    }
}

private final class SignupVectorBytes: @unchecked Sendable {
    private let lock = NSLock()
    private var nextByte = 0
    func next(_ count: Int) -> Data {
        lock.lock(); defer { lock.unlock() }
        defer { nextByte += count }
        return Data((nextByte..<(nextByte + count)).map(UInt8.init))
    }
}

@MainActor private final class SignupTransportGate {
    private var waiting: CheckedContinuation<Void, Never>?
    private var started: CheckedContinuation<Void, Never>?
    private var didStart = false
    func suspend() async {
        didStart = true; started?.resume(); started = nil
        await withCheckedContinuation { waiting = $0 }
    }
    func waitUntilStarted() async { if didStart { return }; await withCheckedContinuation { started = $0 } }
    func resume() { waiting?.resume(); waiting = nil }
}
