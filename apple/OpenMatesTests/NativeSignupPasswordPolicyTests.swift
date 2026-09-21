// Deterministic coverage of native signup password parity with the web policy.
// Fixtures are synthetic and never create accounts or touch external state.
// Covers validation precedence, the complete web blocklist, and Unicode edges.
// JavaScript UTF-16 length and exact confirmation equality are deliberate contracts.
// The parent owns project integration and execution of this private test file.

import XCTest
@testable import OpenMates

final class NativeSignupPasswordPolicyTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testEmptyFieldsSuppressWarningsButCannotSubmit() {
        let empty = NativeSignupPasswordPolicy.validate(password: "", confirmation: "")
        XCTAssertNil(empty.errorKey)
        XCTAssertFalse(empty.isValid)
        XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: ""), "signup.password_too_short")

        let noConfirmation = NativeSignupPasswordPolicy.validate(password: "OrchidMeadow1!", confirmation: "")
        XCTAssertNil(noConfirmation.errorKey)
        XCTAssertFalse(noConfirmation.isValid)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testValidationUsesWebCheckOrder() {
        let cases: [(String, String)] = [
            ("password", "signup.password_too_short"),
            (String(repeating: "1", count: 61), "signup.password_too_long"),
            ("1234567890", "signup.password_too_common"),
            ("9876543210", "signup.password_needs_letter"),
            ("abcdefghij", "signup.password_needs_number"),
            ("abcdefgh12", "signup.password_needs_special")
        ]
        for (password, expectedKey) in cases {
            XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: password), expectedKey)
        }
        let invalid = NativeSignupPasswordPolicy.validate(password: "short", confirmation: "different")
        XCTAssertEqual(invalid.errorKey, "signup.password_too_short")
        XCTAssertEqual(invalid.confirmationErrorKey, "signup.passwords_do_not_match")
        XCTAssertFalse(invalid.isValid)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testCompleteWebBlocklistIsPreservedAndCaseInsensitive() {
        // Golden fixture copied from PasswordTopContent.svelte; short entries still
        // fail length first, matching the web's check order.
        let expected: Set<String> = [
            "password1!", "password1@", "password1#", "password123!", "password123@",
            "qwerty12345", "qwerty123!", "iloveyou123!", "letmein123!", "admin12345!",
            "welcome123!", "changeme123!", "openmates123!", "openmates2024!",
            "openmates2025!", "openmates2026!", "abcd1234!", "test1234!", "test12345!",
            "12345678", "123456789", "1234567890", "12345678910", "qwerty123",
            "qwerty1234", "qwertyuiop", "password", "password1", "password12",
            "password123", "password1234", "passw0rd", "admin123", "welcome123",
            "letmein123", "iloveyou123", "changeme123", "openmates123", "openmates2024",
            "openmates2025", "openmates2026", "abcd1234", "abc12345", "test1234",
            "test12345", "asdf1234", "zxcv1234", "aa123456", "11111111", "00000000"
        ]
        XCTAssertEqual(NativeSignupPasswordPolicy.commonPasswordBlocklist, expected)
        for password in expected {
            let expectedKey = password.utf16.count < 10
                ? "signup.password_too_short" : "signup.password_too_common"
            XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: password), expectedKey)
            XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: password.uppercased()), expectedKey)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testASCIILengthBoundariesAreInclusive() {
        for length in [10, 60] {
            let password = String(repeating: "a", count: length - 2) + "1!"
            XCTAssertTrue(NativeSignupPasswordPolicy.validate(password: password, confirmation: password).isValid)
        }
        XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: "abcdefg1!"), "signup.password_too_short")
        XCTAssertEqual(
            NativeSignupPasswordPolicy.strengthErrorKey(for: String(repeating: "a", count: 59) + "1!"),
            "signup.password_too_long"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testEmojiLengthUsesTwoUTF16UnitsPerScalar() {
        let short = "a1!" + String(repeating: "😀", count: 3)
        XCTAssertEqual(short.utf16.count, 9)
        XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: short), "signup.password_too_short")
        XCTAssertNil(NativeSignupPasswordPolicy.strengthErrorKey(for: short + "a"))

        let longest = "a1!" + String(repeating: "😀", count: 28) + "a"
        XCTAssertEqual(longest.utf16.count, 60)
        XCTAssertNil(NativeSignupPasswordPolicy.strengthErrorKey(for: longest))
        XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: longest + "!"), "signup.password_too_long")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testDecomposedMarksCountTowardLengthAndAsSpecialCharacters() {
        let decomposed = String(repeating: "e\u{301}", count: 4) + "1a"
        XCTAssertEqual(decomposed.utf16.count, 10)
        XCTAssertNil(NativeSignupPasswordPolicy.strengthErrorKey(for: decomposed))
        let composed = String(repeating: "é", count: 4) + "1a"
        XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: composed), "signup.password_too_short")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testUnicodeLetterCategoriesMatchWebPropertyEscape() {
        XCTAssertNil(NativeSignupPasswordPolicy.strengthErrorKey(for: "日本語の秘密文字1!"))
        XCTAssertNil(NativeSignupPasswordPolicy.strengthErrorKey(for: "ʰ123456789!"))
        XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: "\u{301}123456789!"), "signup.password_needs_letter")
        XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: "Ⅳ123456789!"), "signup.password_needs_letter")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testOnlyASCIIDigitsSatisfyNumberRuleAndOtherDigitsCanBeSpecial() {
        XCTAssertEqual(NativeSignupPasswordPolicy.strengthErrorKey(for: "abcdefgh١!"), "signup.password_needs_number")
        XCTAssertNil(NativeSignupPasswordPolicy.strengthErrorKey(for: "abcdefgh1١"))
        XCTAssertNil(NativeSignupPasswordPolicy.strengthErrorKey(for: "abcdefgh1 "))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testConfirmationRequiresExactUTF16EqualityWithoutCanonicalNormalization() {
        let composed = "ébcdefgh1!"
        let decomposed = "e\u{301}bcdefgh1!"
        XCTAssertEqual(composed, decomposed, "Swift canonical equality differs from JavaScript equality")
        let mismatch = NativeSignupPasswordPolicy.validate(password: composed, confirmation: decomposed)
        XCTAssertNil(mismatch.strengthErrorKey)
        XCTAssertEqual(mismatch.confirmationErrorKey, "signup.passwords_do_not_match")
        XCTAssertFalse(mismatch.isValid)
        XCTAssertTrue(NativeSignupPasswordPolicy.validate(password: decomposed, confirmation: decomposed).isValid)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testMatchingValidPasswordEnablesSubmitAndMismatchRemainsCaseSensitive() {
        let password = "OrchidMeadow1!"
        let valid = NativeSignupPasswordPolicy.validate(password: password, confirmation: password)
        XCTAssertNil(valid.errorKey)
        XCTAssertTrue(valid.isValid)
        let mismatch = NativeSignupPasswordPolicy.validate(password: password, confirmation: password.lowercased())
        XCTAssertEqual(mismatch.errorKey, "signup.passwords_do_not_match")
        XCTAssertFalse(mismatch.isValid)
        XCTAssertFalse(NativeSignupPasswordPolicy.validate(password: "", confirmation: password).isValid)
    }
}
