import Foundation
import XCTest
@testable import OpenMates

@MainActor final class AuthFormTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSignupStartsWithAllPreferencesAndConsentsOff() {
        let form = SignupBasicsForm()
        XCTAssertFalse(form.stayLoggedIn)
        XCTAssertFalse(form.newsletter)
        XCTAssertFalse(form.termsAccepted)
        XCTAssertFalse(form.privacyAccepted)
        XCTAssertFalse(form.canSubmit)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSignupMatchesWebUsernameFormatAndRequiresBothConsents() {
        var form = validForm()
        for invalid in ["ab", String(repeating: "a", count: 21), "1234", "has space", "a-b"] {
            form.username = invalid
            XCTAssertNotNil(form.usernameErrorKey, invalid)
            XCTAssertFalse(form.canSubmit, invalid)
        }
        for valid in ["Fixture", "e\u{301}quipe", "名前_123", "a.b"] {
            form.username = valid
            XCTAssertNil(form.usernameErrorKey, valid)
            XCTAssertTrue(form.canSubmit, valid)
        }
        form.termsAccepted = false
        XCTAssertFalse(form.canSubmit)
        form.termsAccepted = true
        form.privacyAccepted = false
        XCTAssertFalse(form.canSubmit)
        form.privacyAccepted = true
        XCTAssertTrue(form.canSubmit)
        XCTAssertFalse(form.newsletter)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testEmailSuggestsUsernameOnlyWhileEmptyLikeWebBasics() {
        var form = SignupBasicsForm(email: "_first--last_@example.test")
        form.suggestUsernameIfEmpty()
        XCTAssertEqual(form.username, "first_last")
        form.email = "different@example.test"
        form.suggestUsernameIfEmpty()
        XCTAssertEqual(form.username, "first_last")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testUnavailableSignupCannotSubmitOrPretendNetworkFailure() async {
        let model = model(runtime: nil)
        model.form = validForm()
        XCTAssertFalse(model.isAvailable)
        XCTAssertFalse(model.canSubmit)
        let submitted = await model.submit()
        XCTAssertNil(submitted)
        XCTAssertNil(model.submittedForm)
        XCTAssertNil(model.error)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testRejectedBasicsRetainsFormAndNeverAdvances() async {
        let runtime = RecordingBasicsRuntime(rejects: true)
        let model = model(runtime: runtime)
        model.form = validForm()
        let submitted = await model.submit()
        XCTAssertNil(submitted)
        XCTAssertNil(model.submittedForm)
        XCTAssertEqual(model.error, .rejected)
        XCTAssertEqual(model.form, validForm())
        XCTAssertFalse(model.loading)
        XCTAssertTrue(model.canSubmit)
        XCTAssertEqual(runtime.calls.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSuspendedSubmissionDeduplicatesAndCommitsExactAcceptedSnapshotToParent() async {
        let runtime = RecordingBasicsRuntime(suspends: true)
        let model = model(runtime: runtime)
        var accepted = validForm()
        accepted.stayLoggedIn = true
        accepted.newsletter = true
        model.form = accepted
        let task = Task { await model.submit() }
        await runtime.waitUntilStarted()
        XCTAssertTrue(model.loading)
        XCTAssertFalse(model.canSubmit)
        let duplicate = await model.submit()
        XCTAssertNil(duplicate)
        model.form.username = "LaterEdit"
        runtime.complete()
        let result = await task.value
        XCTAssertEqual(result, accepted)
        XCTAssertEqual(model.submittedForm, accepted)
        XCTAssertEqual(runtime.calls, [accepted])
        let parent = SignupViewModel(basicsModel: model)
        parent.acceptRequestedEmailCode(accepted)
        XCTAssertEqual(parent.currentStep, .confirmEmail)
        XCTAssertEqual(parent.email, accepted.email)
        XCTAssertEqual(parent.username, accepted.username)
        XCTAssertEqual(parent.submittedBasics, accepted)
        parent.acceptRequestedEmailCode(model.form)
        XCTAssertEqual(parent.submittedBasics, accepted)
        XCTAssertFalse(model.canSubmit)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testOTPAndBackupInputMatchWebFormattingAndPayloadLengths() {
        XCTAssertEqual(PasswordLoginInputPolicy.sanitizedCode("1a٢234567", backup: false), "123456")
        XCTAssertEqual(PasswordLoginInputPolicy.sanitizedCode("abcd", backup: true), "ABCD-")
        XCTAssertEqual(PasswordLoginInputPolicy.sanitizedCode("abcd-efgh", backup: true), "ABCD-EFGH-")
        XCTAssertEqual(PasswordLoginInputPolicy.sanitizedCode("abcd-efgh-1234zz", backup: true), "ABCD-EFGH-1234")
        XCTAssertEqual(PasswordLoginInputPolicy.sanitizedCode("abcdefgh1234", backup: true), "ABCD-EFGH-1234")
        XCTAssertEqual(PasswordLoginInputPolicy.sanitizedCode("ABCDEFGH1-234", backup: true), "ABCD-EFGH-1234")
    }

    private func validForm() -> SignupBasicsForm {
        .init(email: "fixture@example.test", username: "Fixture", termsAccepted: true, privacyAccepted: true)
    }
    private func model(runtime: (any SignupBasicsRuntime)?) -> SignupBasicsFormModel {
        SignupBasicsFormModel(runtime: runtime, configuration: .init(inviteCode: nil, language: "en", darkmode: false))
    }
}

@MainActor private final class RecordingBasicsRuntime: SignupBasicsRuntime {
    let rejects: Bool
    let suspends: Bool
    var calls: [SignupBasicsForm] = []
    private var started: CheckedContinuation<Void, Never>?
    private var pending: CheckedContinuation<Void, Never>?
    init(rejects: Bool = false, suspends: Bool = false) { self.rejects = rejects; self.suspends = suspends }
    func requestCode(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
        calls.append(form)
        started?.resume()
        started = nil
        if rejects { throw AuthFormError.rejected }
        if suspends { await withCheckedContinuation { pending = $0 } }
    }
    func waitUntilStarted() async {
        if !calls.isEmpty { return }
        await withCheckedContinuation { started = $0 }
    }
    func complete() { pending?.resume(); pending = nil }
}
