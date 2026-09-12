// Synthetic credentials only. These tests exercise the real native protocol,
// serializer, PRF fallback, key wrapping and signup coordinator; no OS prompt,
// Keychain write, account creation, cookie or server request occurs.
import CryptoKit
import Sodium
import XCTest
@testable import OpenMates

@MainActor final class NativeSignupPasskeyTests: XCTestCase {
    private let form = SignupBasicsForm(email: "fixture@example.test", username: "Fixture", stayLoggedIn: true,
        termsAccepted: true, privacyAccepted: true)
    private let configuration = SignupBasicsConfiguration(inviteCode: "accepted-invite", language: "en", darkmode: false)

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,auth.login.method-convergence
    func testCompleteWirePreservesWebAuthnCamelCaseAndUsesParsedAuthenticatorData() async throws {
        let harness = PreviewSignupPasskeyHarness()
        let material = try await harness.runtime.prepare(form: form, configuration: configuration)
        let wire = try XCTUnwrap(JSONSerialization.jsonObject(with: material.request.wireData()) as? [String: Any])
        let attestation = try XCTUnwrap(wire["attestation_response"] as? [String: Any])
        XCTAssertNotNil(attestation["attestationObject"])
        XCTAssertNotNil(attestation["publicKey"])
        XCTAssertNil(attestation["attestation_object"])
        XCTAssertTrue(wire["user_id"] is NSNull)
        XCTAssertEqual(wire["prf_enabled"] as? Bool, true)
        XCTAssertEqual(wire["salt"] as? String, wire["user_email_salt"] as? String)
        XCTAssertEqual(wire["invite_code"] as? String, "accepted-invite")
        let authData = try XCTUnwrap(Data(base64Encoded: material.request.authenticatorData))
        XCTAssertEqual(authData, harness.authorizer.authenticatorData(rpID: ServerProfile.development.webBaseURL.host!, registration: true))
        XCTAssertNotEqual(authData, Data(Data(base64Encoded: material.request.attestationObject)!.prefix(37)))
        let initiation = try XCTUnwrap(JSONSerialization.jsonObject(with: harness.requests[0].1) as? [String: Any])
        XCTAssertTrue(initiation["user_id"] is NSNull)
        XCTAssertEqual(harness.authorizer.registrationCount, 1)
        XCTAssertEqual(harness.completionCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,auth.login.method-convergence
    func testRegistrationMaterialUnwrapsAndBothEncryptedEmailsUseWebFormats() async throws {
        let harness = PreviewSignupPasskeyHarness()
        let material = try await harness.runtime.prepare(form: form, configuration: configuration)
        let salt = try XCTUnwrap(Data(base64Encoded: material.request.userEmailSalt))
        let wrapping = await CryptoManager.shared.deriveWrappingKeyFromPRF(prfSignature: harness.authorizer.prf, emailSalt: salt)
        let unwrapped = try await CryptoManager.shared.unwrapMasterKey(wrappedKeyBase64: material.request.encryptedMasterKey,
            ivBase64: material.request.keyIv, wrappingKey: wrapping)
        XCTAssertEqual(unwrapped.withUnsafeBytes { Data($0) }, material.masterKey.withUnsafeBytes { Data($0) })
        let lookup = await CryptoManager.shared.hashKeyFromPRF(prfSignature: harness.authorizer.prf, emailSalt: salt)
        XCTAssertEqual(lookup, material.request.lookupHash)
        let recovered = try await CryptoManager.shared.decryptContent(base64String: material.request.encryptedEmailWithMasterKey, key: unwrapped)
        let device = try await CryptoManager.shared.decryptContent(base64String: material.request.encryptedDeviceName, key: unwrapped)
        XCTAssertEqual(recovered, form.email); XCTAssertEqual(device, "Local fixture")
        let emailKey = await CryptoManager.shared.deriveEmailEncryptionKey(email: form.email, salt: salt)
        let encryptedEmail = try XCTUnwrap(Data(base64Encoded: material.request.encryptedEmail))
        let plaintext = Sodium().secretBox.open(nonceAndAuthenticatedCipherText: Array(encryptedEmail), secretKey: Array(emailKey))
        XCTAssertEqual(plaintext.flatMap { String(bytes: $0, encoding: .utf8) }, form.email)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testMissingCreatePRFUsesOnlyNewCredentialAndRejectsForeignFallback() async throws {
        let harness = PreviewSignupPasskeyHarness()
        harness.authorizer.omitCreatePRF = true
        _ = try await harness.runtime.prepare(form: form, configuration: configuration)
        XCTAssertEqual(harness.authorizer.assertedCredentialIDs, [harness.authorizer.credentialID])
        harness.authorizer.returnForeignCredential = true
        do { _ = try await harness.runtime.prepare(form: form, configuration: configuration); XCTFail("Foreign fallback was accepted") }
        catch { XCTAssertEqual(error as? NativeSignupError, .sessionProofMismatch) }
        harness.authorizer.returnForeignCredential = false
        harness.authorizer.returnForeignUserHandle = true
        do { _ = try await harness.runtime.prepare(form: form, configuration: configuration); XCTFail("Foreign user handle was accepted") }
        catch { XCTAssertEqual(error as? NativeSignupError, .sessionProofMismatch) }
        XCTAssertEqual(harness.completionCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testInvalidChallengeAndClientOriginCannotReachAccountCompletion() async throws {
        let harness = PreviewSignupPasskeyHarness()
        harness.wrongChallenge = true
        do { _ = try await harness.runtime.prepare(form: form, configuration: configuration); XCTFail("Invalid challenge accepted") }
        catch { XCTAssertEqual(error as? NativeSignupError, .invalidPasskeyChallenge) }
        XCTAssertEqual(harness.authorizer.registrationCount, 0)
        harness.wrongChallenge = false
        harness.authorizer.registrationOrigin = "https://other.example"
        do { _ = try await harness.runtime.prepare(form: form, configuration: configuration); XCTFail("Foreign origin accepted") }
        catch { XCTAssertEqual(error as? NativeSignupError, .invalidPasskeyChallenge) }
        XCTAssertEqual(harness.completionCount, 0)
        XCTAssertThrowsError(try NativePasskeyValidation.prf(Data(repeating: 1, count: 31)))
        let extensionValue = PasskeyAssertionExtensions(prf: .init(eval: .init(first: Data(repeating: 1, count: 32).base64URLEncodedString())))
        XCTAssertThrowsError(try NativePasskeyValidation.prfSalt(rpID: ServerProfile.development.webBaseURL.host!, extensions: extensionValue, profile: .development))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,auth.login.method-convergence
    func testFreshAssertionVerifyAndLoginMustProveRegisteredEnvelopeBeforePublication() async throws {
        let harness = PreviewSignupPasskeyHarness()
        let material = try await harness.runtime.prepare(form: form, configuration: configuration)
        let userID = try await harness.runtime.create(material)
        harness.wrongVerifiedEnvelope = true
        do { try await harness.runtime.finish(material, expectedUserID: userID, form: form); XCTFail("Foreign envelope published") }
        catch { XCTAssertEqual(error as? NativeSignupError, .sessionProofMismatch) }
        XCTAssertEqual(harness.publishCount, 0)
        XCTAssertFalse(harness.requests.contains { $0.0 == "/v1/auth/login" })
        harness.wrongVerifiedEnvelope = false
        try await harness.runtime.finish(material, expectedUserID: userID, form: form)
        XCTAssertEqual(harness.publishCount, 1)
        let login = try XCTUnwrap(harness.requests.last { $0.0 == "/v1/auth/login" })
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: login.1) as? [String: Any])
        XCTAssertEqual(payload["credential_id"] as? String, material.request.credentialId)
        XCTAssertEqual(payload["lookup_hash"] as? String, material.request.lookupHash)
        XCTAssertEqual(payload["login_method"] as? String, "passkey")
        XCTAssertEqual(payload["stay_logged_in"] as? Bool, true)
        XCTAssertEqual(payload["session_id"] as? String, "local-signup-session")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testAccountChangeWhileAuthorizationOrLoginIsSuspendedPreventsPublication() async throws {
        let harness = PreviewSignupPasskeyHarness()
        harness.authorizer.beforeReturn = { harness.active = false }
        do { _ = try await harness.runtime.prepare(form: form, configuration: configuration); XCTFail("Stale registration continued") }
        catch { XCTAssertEqual(error as? NativeSignupError, .staleContext) }
        XCTAssertEqual(harness.completionCount, 0)
        harness.active = true; harness.authorizer.beforeReturn = nil
        let material = try await harness.runtime.prepare(form: form, configuration: configuration)
        let userID = try await harness.runtime.create(material)
        harness.beforeTransportReturn = { if $0 == "/v1/auth/login" { harness.active = false } }
        do { try await harness.runtime.finish(material, expectedUserID: userID, form: form); XCTFail("Stale login published") }
        catch { XCTAssertEqual(error as? NativeSignupError, .staleContext) }
        XCTAssertEqual(harness.publishCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,auth.login.method-convergence
    func testUncertainCompletionRetriesLoginWithoutNewCredentialOrAccountRequest() async throws {
        let adapter = PasskeySignupCoordinatorAdapter(variant: "passkey-uncertain")
        let model = await preparedModel(adapter)
        await model.registerPasskey()
        XCTAssertEqual(model.currentStep, .secureAccount)
        XCTAssertEqual(model.error, .creationUnconfirmed)
        XCTAssertTrue(model.passkeyCreationAttempted)
        XCTAssertFalse(model.canChoosePassword)
        XCTAssertEqual(adapter.harness.authorizer.registrationCount, 1)
        XCTAssertEqual(adapter.harness.completionCount, 1)
        await model.registerPasskey()
        XCTAssertEqual(model.currentStep, .complete)
        XCTAssertEqual(adapter.harness.publishCount, 1)
        XCTAssertEqual(adapter.harness.completionCount, 1)
        XCTAssertEqual(adapter.harness.authorizer.registrationCount, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testCancellationAllowsRetryAndUnsupportedPRFReturnsToWorkingPasswordChoice() async throws {
        let cancelled = PasskeySignupCoordinatorAdapter(variant: "passkey-cancel")
        let model = await preparedModel(cancelled)
        await model.registerPasskey()
        XCTAssertNil(model.error); XCTAssertTrue(model.canRegisterPasskey)
        XCTAssertEqual(cancelled.harness.completionCount, 0)
        await model.registerPasskey()
        XCTAssertEqual(model.currentStep, .complete)
        XCTAssertEqual(cancelled.harness.completionCount, 1)
        let unsupported = PasskeySignupCoordinatorAdapter(variant: "passkey-prf-error")
        let fallback = await preparedModel(unsupported)
        await fallback.registerPasskey()
        XCTAssertEqual(fallback.currentStep, .passkeyPRFError)
        XCTAssertEqual(unsupported.harness.completionCount, 0)
        fallback.returnFromPasskeyError(); XCTAssertTrue(fallback.canChoosePassword)
        fallback.selectPassword(); XCTAssertEqual(fallback.currentStep, .password)
        XCTAssertFalse(fallback.passkeyCreationAttempted)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testLeavingSignupWhileCredentialCreationWaitsCannotSubmitLateCredential() async throws {
        let adapter = PasskeySignupCoordinatorAdapter()
        let model = await preparedModel(adapter)
        adapter.harness.authorizer.beforeReturn = { model.cancel() }
        await model.registerPasskey()
        XCTAssertFalse(model.canRegisterPasskey)
        XCTAssertFalse(model.passkeyCreationAttempted)
        XCTAssertEqual(adapter.harness.completionCount, 0)
        XCTAssertEqual(adapter.harness.publishCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testAttestationReaderRejectsTruncationDuplicateAuthDataAndCredentialMismatch() async throws {
        let harness = PreviewSignupPasskeyHarness()
        let material = try await harness.runtime.prepare(form: form, configuration: configuration)
        let cbor = try XCTUnwrap(Data(base64Encoded: material.request.attestationObject))
        let authData = try XCTUnwrap(Data(base64Encoded: material.request.authenticatorData))
        let clientData = try XCTUnwrap(Data(base64Encoded: material.request.clientDataJSON))
        let duplicate = Data([0xA4]) + cbor.dropFirst() + Data([0x68]) + Data("authData".utf8) + Data([0x58, UInt8(authData.count)]) + authData
        let rpID = ServerProfile.development.webBaseURL.host!
        for invalid in [Data(cbor.dropLast()), duplicate, Data([0xBF]), Data(repeating: 0, count: 65_537)] {
            let registration = NativePasskeyRegistrationResult(credentialID: harness.authorizer.credentialID,
                clientDataJSON: clientData, attestationObject: invalid, prfOutput: nil, supportsPRF: true)
            XCTAssertThrowsError(try NativePasskeyValidation.registrationAuthenticatorData(registration, rpID: rpID))
        }
        let foreign = NativePasskeyRegistrationResult(credentialID: Data([99]), clientDataJSON: clientData,
            attestationObject: cbor, prfOutput: nil, supportsPRF: true)
        XCTAssertThrowsError(try NativePasskeyValidation.registrationAuthenticatorData(foreign, rpID: rpID))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testPRFDerivationMatchesIndependentRFC5869SHA256Vector() async throws {
        // RFC5869 extract/expand, info="masterkey_wrapping", 32-byte result.
        // Expected bytes computed independently with Python hmac/hashlib, matching
        // web cryptoService. This does not compare an implementation to itself.
        let prf = Data(repeating: 11, count: 32)
        let salt = Data(0..<16)
        let key = await CryptoManager.shared.deriveWrappingKeyFromPRF(prfSignature: prf, emailSalt: salt)
        XCTAssertEqual(key.withUnsafeBytes { Data($0).base64EncodedString() }, "P45sAilIpbMBcDBeBaJhkK4AcTzMz91DdUx9x84ZRaM=")
        let lookup = await CryptoManager.shared.hashKeyFromPRF(prfSignature: prf, emailSalt: salt)
        XCTAssertEqual(lookup, "qDyAWG+WoM4PDSXsQ5RjSmtsPMDxP6FgAbxU6miz1M0=")
    }

    private func preparedModel(_ runtime: PasskeySignupCoordinatorAdapter) async -> SignupViewModel {
        let model = SignupViewModel(runtime: runtime, configuration: configuration)
        await model.loadRequirements(); model.continueFromDisclaimer()
        model.basicsModel.form = form
        guard let accepted = await model.basicsModel.submit() else { XCTFail("Basics did not submit"); return model }
        model.acceptRequestedEmailCode(accepted)
        model.verificationCode = "123456"; await model.confirmEmail()
        return model
    }
}

@MainActor private final class PasskeySignupCoordinatorAdapter: NativeSignupRuntime {
    let harness: PreviewSignupPasskeyHarness
    var supportsPasskey: Bool { true }
    init(variant: String = "passkey") { harness = .init(variant: variant) }
    func requirements() async throws -> NativeSignupRequirements { .init(requiresInvite: false, isSelfHosted: false) }
    func validateBasics(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration, requirements: NativeSignupRequirements) async throws {}
    func requestEmailCode(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {}
    func subscribeNewsletter(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {}
    func confirmEmail(_ code: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
        guard code == "123456" else { throw NativeSignupError.invalidEmailCode }
    }
    func preparePassword(_ password: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasswordMaterial { throw NativeSignupError.invalidForm }
    func createPassword(_ material: NativeSignupPasswordMaterial) async throws -> String { throw NativeSignupError.invalidForm }
    func preparePasskey(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasskeyMaterial { try await harness.runtime.prepare(form: form, configuration: configuration) }
    func createPasskey(_ material: NativeSignupPasskeyMaterial) async throws -> String { try await harness.runtime.create(material) }
    func finishPasskey(_ material: NativeSignupPasskeyMaterial, expectedUserID: String?, form: SignupBasicsForm) async throws { try await harness.runtime.finish(material, expectedUserID: expectedUserID, form: form) }
}
