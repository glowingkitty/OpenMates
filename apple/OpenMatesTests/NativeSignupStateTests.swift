import CryptoKit
import XCTest
@testable import OpenMates

@MainActor final class NativeSignupStateTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testCloudSignupRequiresConfirmedEmailAndPasswordChoiceBeforeCreation() async throws {
        let runtime = RecordingNativeSignupRuntime()
        var logins = 0
        let model = makeModel(runtime) { _, id, password, form in
            XCTAssertEqual(id, "created-user"); XCTAssertEqual(password, "OrchidMeadow1!")
            XCTAssertEqual(form.email, "fixture@example.test"); XCTAssertTrue(form.stayLoggedIn)
            logins += 1
        }
        await prepareBasics(model)
        XCTAssertEqual(model.currentStep, .confirmEmail)
        XCTAssertEqual(runtime.events, ["requirements", "validate", "request-code"])
        model.password = "OrchidMeadow1!"; model.confirmPassword = model.password
        await model.setPassword()
        XCTAssertEqual(runtime.createCount, 0)
        model.verificationCode = "111111"; await model.confirmEmail()
        XCTAssertEqual(model.currentStep, .confirmEmail)
        XCTAssertEqual(model.error, .invalidEmailCode)
        XCTAssertEqual(model.verificationCode, "")
        model.verificationCode = "123456"; await model.confirmEmail()
        XCTAssertEqual(model.currentStep, .secureAccount)
        model.selectPassword(); await model.setPassword()
        XCTAssertEqual(model.currentStep, .complete)
        XCTAssertEqual(runtime.createCount, 1); XCTAssertEqual(logins, 1)
        XCTAssertEqual(model.password, ""); XCTAssertEqual(model.confirmPassword, "")
        XCTAssertEqual(runtime.events.suffix(3), ["confirm-code", "prepare-password", "create-password"])
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSelfHostedVerificationRequiredFallsBackToActualEmailConfirmation() async {
        let runtime = RecordingNativeSignupRuntime(selfHosted: true)
        runtime.creationError = .verificationRequired
        let model = makeModel(runtime)
        await prepareBasics(model)
        XCTAssertEqual(model.currentStep, .secureAccount)
        XCTAssertFalse(runtime.events.contains("request-code"))
        model.selectPassword(); setValidPassword(model); await model.setPassword()
        XCTAssertEqual(model.currentStep, .confirmEmail)
        XCTAssertFalse(model.transitionIsForward)
        XCTAssertEqual(model.error, .verificationRequired)
        XCTAssertFalse(model.creationAttempted)
        XCTAssertEqual(runtime.events.last, "request-code")
        runtime.creationError = nil
        model.verificationCode = "123456"; await model.confirmEmail(); model.selectPassword()
        XCTAssertTrue(model.transitionIsForward)
        await model.setPassword()
        XCTAssertEqual(model.currentStep, .complete)
        XCTAssertEqual(runtime.createCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testUncertainCreationRetriesKnownKeyLoginWithoutCreatingAgain() async {
        let runtime = RecordingNativeSignupRuntime(selfHosted: true)
        runtime.creationError = .invalidAccountResponse
        var proofs: [NativeSignupPasswordRequest] = []
        let model = makeModel(runtime) { material, id, password, _ in
            XCTAssertNil(id)
            XCTAssertEqual(password, "OrchidMeadow1!")
            proofs.append(material.request)
        }
        await prepareBasics(model); model.selectPassword(); setValidPassword(model)
        await model.setPassword()
        XCTAssertEqual(model.error, .creationUnconfirmed)
        XCTAssertTrue(model.creationAttempted)
        XCTAssertTrue(proofs.isEmpty)
        model.password = "ChangedUIValue1!" // Untrusted later view state must not replace the submitted password/key.
        await model.setPassword()
        XCTAssertEqual(model.currentStep, .complete)
        XCTAssertEqual(runtime.createCount, 1)
        XCTAssertEqual(runtime.prepareCount, 1)
        XCTAssertEqual(proofs, [runtime.material.request])
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testCreatedAccountCannotCompleteUntilNormalLoginProofSucceeds() async {
        let runtime = RecordingNativeSignupRuntime(selfHosted: true)
        var loginCalls = 0
        let model = makeModel(runtime) { _, id, _, _ in
            loginCalls += 1; XCTAssertEqual(id, "created-user")
            if loginCalls == 1 { throw NativeSignupError.sessionProofMismatch }
        }
        await prepareBasics(model); model.selectPassword(); setValidPassword(model)
        await model.setPassword()
        XCTAssertEqual(model.currentStep, .password)
        XCTAssertEqual(model.error, .creationUnconfirmed)
        await model.setPassword()
        XCTAssertEqual(model.currentStep, .complete)
        XCTAssertEqual(runtime.createCount, 1); XCTAssertEqual(loginCalls, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSuspendedCreationDeduplicatesAndLeavingFlowRejectsLateCompletion() async {
        let runtime = RecordingNativeSignupRuntime(selfHosted: true)
        runtime.suspendCreation = true
        var loginCalls = 0
        let model = makeModel(runtime) { _, _, _, _ in loginCalls += 1 }
        await prepareBasics(model); model.selectPassword(); setValidPassword(model)
        let task = Task { await model.setPassword() }
        await runtime.waitForCreation()
        XCTAssertTrue(model.isLoading)
        await model.setPassword()
        XCTAssertEqual(runtime.createCount, 1)
        model.cancel()
        runtime.completeCreation()
        await task.value
        XCTAssertEqual(loginCalls, 0)
        XCTAssertNotEqual(model.currentStep, .complete)
        XCTAssertFalse(model.isLoading)
        XCTAssertEqual(model.password, "")
        XCTAssertFalse(model.canSubmitPassword)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testInvitationAndLanguageSnapshotCannotChangeAfterAcceptedBasics() async {
        let runtime = RecordingNativeSignupRuntime()
        let model = makeModel(runtime)
        model.inviteCode = "accepted-invite"
        await prepareBasics(model)
        model.inviteCode = "later-edit"
        model.basicsModel.form.email = "changed@example.test"
        model.verificationCode = "123456"; await model.confirmEmail()
        let confirmed = runtime.confirmations.last
        XCTAssertEqual(confirmed?.0.email, "fixture@example.test")
        XCTAssertEqual(confirmed?.1.inviteCode, "accepted-invite")
        XCTAssertEqual(confirmed?.1.language, "de")
        XCTAssertEqual(confirmed?.1.darkmode, true)
    }

    private func makeModel(_ runtime: RecordingNativeSignupRuntime,
                           login: @escaping SignupViewModel.Login = { _, _, _, _ in }) -> SignupViewModel {
        .init(runtime: runtime, configuration: .init(inviteCode: nil, language: "de", darkmode: true), login: login)
    }
    private func prepareBasics(_ model: SignupViewModel) async {
        await model.loadRequirements(); model.continueFromDisclaimer()
        model.basicsModel.form = .init(email: "fixture@example.test", username: "Fixture", stayLoggedIn: true, termsAccepted: true, privacyAccepted: true)
        guard let submitted = await model.basicsModel.submit() else { XCTFail("Basics did not submit"); return }
        model.acceptRequestedEmailCode(submitted)
    }
    private func setValidPassword(_ model: SignupViewModel) { model.password = "OrchidMeadow1!"; model.confirmPassword = model.password }
}

@MainActor private final class RecordingNativeSignupRuntime: NativeSignupRuntime {
    let selfHosted: Bool
    var events: [String] = []
    var confirmations: [(SignupBasicsForm, SignupBasicsConfiguration)] = []
    var createCount = 0
    var prepareCount = 0
    var creationError: NativeSignupError?
    var suspendCreation = false
    private var creationStarted: CheckedContinuation<Void, Never>?
    private var creationContinuation: CheckedContinuation<Void, Never>?
    let material = NativeSignupPasswordMaterial(request: .init(hashedEmail: "hash", encryptedEmail: "encrypted-email", userEmailSalt: "email-salt", username: "Fixture", inviteCode: "", encryptedMasterKey: "wrapped-key", keyIv: "iv", salt: "wrapping-salt", lookupHash: "lookup", language: "de", darkmode: true, pendingGiftCardCode: nil), masterKey: SymmetricKey(data: Data(repeating: 1, count: 32)))
    init(selfHosted: Bool = false) { self.selfHosted = selfHosted }
    func requirements() async throws -> NativeSignupRequirements { events.append("requirements"); return .init(requiresInvite: false, isSelfHosted: selfHosted) }
    func validateBasics(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration, requirements: NativeSignupRequirements) async throws { events.append("validate") }
    func requestEmailCode(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws { events.append("request-code") }
    func subscribeNewsletter(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws { events.append("newsletter") }
    func confirmEmail(_ code: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
        events.append("confirm-code"); confirmations.append((form, configuration))
        guard code == "123456" else { throw NativeSignupError.invalidEmailCode }
    }
    func preparePassword(_ password: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasswordMaterial {
        events.append("prepare-password"); prepareCount += 1; return material
    }
    func createPassword(_ material: NativeSignupPasswordMaterial) async throws -> String {
        events.append("create-password"); createCount += 1
        creationStarted?.resume(); creationStarted = nil
        if suspendCreation { await withCheckedContinuation { creationContinuation = $0 } }
        if let creationError { throw creationError }
        return "created-user"
    }
    func waitForCreation() async { if createCount > 0 { return }; await withCheckedContinuation { creationStarted = $0 } }
    func completeCreation() { creationContinuation?.resume(); creationContinuation = nil }
}
