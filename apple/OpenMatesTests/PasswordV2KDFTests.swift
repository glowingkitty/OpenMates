// Account-password KDF interop vector shared with web and CLI.
import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

final class PasswordV2KDFTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.keys.client-wrapped
    func testArgon2idHKDFMatchesCrossPlatformVector() throws {
        let salt = Data((0..<16).map(UInt8.init))
        let keys = try PasswordV2Keys(password: "Correct Horse Battery Staple!", emailSalt: salt)
        XCTAssertEqual(keys.authenticationKey.base64URLEncodedString(),
                       "vH4NzewPmDGymGUgH11VasH-0clzgc98FEOnn6SEB5o")
        XCTAssertEqual(keys.wrappingKey.withUnsafeBytes { Data($0).base64URLEncodedString() },
                       "d8EIpdqJ7JF5dhaA6xIcpQJTNu9kZGZimmu--sR-2Hc")
        XCTAssertEqual(try keys.proof(purpose: "login", nonce: Data((0x20..<0x40).map(UInt8.init))),
                       "4BZxiDKNYrtneUG0v46ZS8a65q64y1AsHKXpgB9XwO0")
        XCTAssertEqual(try keys.proof(purpose: "migration", nonce: Data((0x20..<0x40).map(UInt8.init))),
                       "FnvUc_hc_duRj64pRBOuVyTPHBdRvUehajVmLqFdXMY")
        XCTAssertThrowsError(try PasswordV2Keys(password: "password", emailSalt: Data(repeating: 0, count: 8)))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.keys.client-wrapped
    func testVersion2CredentialDTOsOmitReusableLegacyLookupHash() throws {
        var login = LoginRequest(
            hashedEmail: "hashed-email", lookupHash: nil, loginMethod: "password",
            tfaCode: nil, codeType: nil, emailEncryptionKey: nil,
            stayLoggedIn: false, sessionId: "session-id", deviceInfo: nil)
        login.credentialVersion = 2
        login.challengeId = "one-use-challenge"
        login.passwordProof = "one-use-proof"
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(login)) as? [String: Any])
        XCTAssertNil(body["lookup_hash"])
        XCTAssertNil(body["password_auth_key"])
        XCTAssertEqual(body["credential_version"] as? Int, 2)
        XCTAssertEqual(body["challenge_id"] as? String, "one-use-challenge")
        XCTAssertEqual(body["password_proof"] as? String, "one-use-proof")

        let sensitive = SensitiveEmailVerifyRequest(
            purpose: "credential_change", challengeId: "email-code-id", code: "123456",
            hashedEmail: "hashed-email", sessionId: "session-id", lookupHash: nil,
            passwordChallengeId: "one-use-challenge", passwordProof: "one-use-proof")
        let sensitiveBody = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(sensitive)) as? [String: Any])
        XCTAssertNil(sensitiveBody["lookup_hash"])
        XCTAssertEqual(sensitiveBody["password_challenge_id"] as? String, "one-use-challenge")
        XCTAssertEqual(sensitiveBody["password_proof"] as? String, "one-use-proof")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testAuthMethodsPreserveTwoFactorAvailabilityForPasswordChange() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let methods = try decoder.decode(AuthMethods.self, from: Data(
            #"{"has_passkey":true,"has_password":true,"has_2fa":true,"has_recovery_key":false}"#.utf8))
        XCTAssertTrue(methods.hasPasskey)
        XCTAssertTrue(methods.has2Fa)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.keys.client-wrapped
    func testNewWrapperIsVerifiedBeforeCredentialSubmission() async throws {
        let keys = try PasswordV2Keys(
            password: "OrchidMeadow1!", emailSalt: Data((0x20..<0x30).map(UInt8.init)))
        let master = SymmetricKey(data: Data((0..<32).map(UInt8.init)))
        let encrypted = try await CryptoManager.shared.encrypt(
            master.withUnsafeBytes { Data($0) }, using: keys.wrappingKey,
            nonceData: Data((0x30..<0x3c).map(UInt8.init)))
        let body = encrypted.ciphertext.base64EncodedString()
        let iv = encrypted.nonce.base64EncodedString()
        try await CryptoManager.shared.verifyMasterKeyRoundTrip(
            wrappedKeyBase64: body, ivBase64: iv,
            wrappingKey: keys.wrappingKey, expected: master)
        do {
            try await CryptoManager.shared.verifyMasterKeyRoundTrip(
                wrappedKeyBase64: body, ivBase64: iv, wrappingKey: keys.wrappingKey,
                expected: SymmetricKey(data: Data(repeating: 0, count: 32)))
            XCTFail("A wrong master key passed wrapper verification")
        } catch {
            XCTAssertNotNil(error as? CryptoManager.CryptoError)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.keys.client-wrapped
    func testMigrationRequiresExplicitStagedCapabilityAndSeparateConfirmationDTO() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let capabilities = try decoder.decode(PasswordV2MigrationCapabilities.self,
            from: Data(#"{"staged_protocol":2,"confirm_required":true}"#.utf8))
        XCTAssertEqual(capabilities.stagedProtocol, 2)
        XCTAssertTrue(capabilities.confirmRequired)

        let request = PasswordV2MigrationRequest(
            oldLookupHash: "old-lookup", passwordAuthKey: "auth-key",
            encryptedMasterKey: "wrapped", salt: "email-salt", keyIv: "nonce")
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(request)) as? [String: Any])
        XCTAssertEqual(body["old_lookup_hash"] as? String, "old-lookup")
        XCTAssertEqual(body["password_auth_key"] as? String, "auth-key")
        XCTAssertNil(body["confirm"])
    }
}
