// Unit coverage for native auth/security state parity.
// These tests use in-memory state only and never touch credentials, passkeys,
// recovery keys, backup codes, Keychain records, network sessions, or screenshots.

import XCTest
@testable import OpenMates

@MainActor
final class AuthSecurityParityTests: XCTestCase {
    func testAuthFlowResetClearsSensitiveLookupState() {
        let state = AuthFlowState()
        state.authMode = .login
        state.currentStep = .passwordLogin
        state.email = "person@example.com"
        state.tfaEnabled = true
        state.userEmailSalt = "salt"

        state.reset()

        XCTAssertEqual(state.authMode, .signup)
        XCTAssertEqual(state.currentStep, .emailLookup)
        XCTAssertEqual(state.email, "")
        XCTAssertEqual(state.availableMethods, [])
        XCTAssertEqual(state.tfaEnabled, false)
        XCTAssertNil(state.userEmailSalt)
    }

    func testResetForAnotherAccountPreservesModeButClearsAccountSpecificState() {
        let state = AuthFlowState()
        state.authMode = .login
        state.currentStep = .passwordLogin
        state.email = "person@example.com"
        state.availableMethods = [.password]
        state.userEmailSalt = "salt"

        state.resetForAnotherAccount()

        XCTAssertEqual(state.authMode, .login)
        XCTAssertEqual(state.currentStep, .emailLookup)
        XCTAssertEqual(state.email, "")
        XCTAssertEqual(state.availableMethods, [])
        XCTAssertNil(state.userEmailSalt)
    }
}
