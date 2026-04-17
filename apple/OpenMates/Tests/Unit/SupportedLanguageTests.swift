// SupportedLanguage unit tests — validates language enum, RTL detection, and locale matching.

import XCTest
@testable import OpenMates

final class SupportedLanguageTests: XCTestCase {

    func testAllLanguagesHaveNames() {
        for language in SupportedLanguage.allCases {
            XCTAssertFalse(language.name.isEmpty, "\(language.code) should have a name")
        }
    }

    func testLanguageCount() {
        XCTAssertEqual(SupportedLanguage.allCases.count, 21)
    }

    func testRTLLanguages() {
        XCTAssertTrue(SupportedLanguage.ar.isRTL, "Arabic should be RTL")
        XCTAssertTrue(SupportedLanguage.he.isRTL, "Hebrew should be RTL")
        XCTAssertFalse(SupportedLanguage.en.isRTL, "English should not be RTL")
        XCTAssertFalse(SupportedLanguage.de.isRTL, "German should not be RTL")
        XCTAssertFalse(SupportedLanguage.ja.isRTL, "Japanese should not be RTL")
    }

    func testFromCodeValid() {
        XCTAssertEqual(SupportedLanguage.from(code: "en"), .en)
        XCTAssertEqual(SupportedLanguage.from(code: "de"), .de)
        XCTAssertEqual(SupportedLanguage.from(code: "zh"), .zh)
        XCTAssertEqual(SupportedLanguage.from(code: "ar"), .ar)
    }

    func testFromCodeCaseInsensitive() {
        XCTAssertEqual(SupportedLanguage.from(code: "EN"), .en)
        XCTAssertEqual(SupportedLanguage.from(code: "De"), .de)
    }

    func testFromCodeInvalid() {
        XCTAssertNil(SupportedLanguage.from(code: "xx"))
        XCTAssertNil(SupportedLanguage.from(code: ""))
        XCTAssertNil(SupportedLanguage.from(code: "da"))  // Danish not in the list
    }

    func testShortCode() {
        XCTAssertEqual(SupportedLanguage.en.shortCode, "EN")
        XCTAssertEqual(SupportedLanguage.zh.shortCode, "ZH")
    }

    func testFromDeviceLocaleReturnsFallback() {
        // Should always return a valid language (defaults to .en)
        let detected = SupportedLanguage.fromDeviceLocale()
        XCTAssertTrue(SupportedLanguage.allCases.contains(detected))
    }
}
