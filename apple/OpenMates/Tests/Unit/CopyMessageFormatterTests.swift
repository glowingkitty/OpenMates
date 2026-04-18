// CopyMessageFormatter unit tests — validates smart copy with embed-to-text conversion.

import XCTest
@testable import OpenMates

final class CopyMessageFormatterTests: XCTestCase {

    func testPlainTextPassthrough() {
        let result = CopyMessageFormatter.formatForCopy(content: "Hello world", embeds: [])
        XCTAssertEqual(result, "Hello world")
    }

    func testMarkdownBoldStripped() {
        let result = CopyMessageFormatter.formatForCopy(content: "This is **bold** text", embeds: [])
        XCTAssertEqual(result, "This is bold text")
    }

    func testMarkdownItalicStripped() {
        let result = CopyMessageFormatter.formatForCopy(content: "This is *italic* text", embeds: [])
        XCTAssertEqual(result, "This is italic text")
    }

    func testMarkdownHeaderStripped() {
        let result = CopyMessageFormatter.formatForCopy(content: "## Header Text\nBody", embeds: [])
        XCTAssertTrue(result.contains("Header Text"))
        XCTAssertFalse(result.contains("##"))
    }

    func testMarkdownLinkConverted() {
        let result = CopyMessageFormatter.formatForCopy(
            content: "Visit [OpenMates](https://openmates.org) today",
            embeds: []
        )
        XCTAssertTrue(result.contains("OpenMates"))
        XCTAssertTrue(result.contains("https://openmates.org"))
        XCTAssertFalse(result.contains("[OpenMates]"))
    }

    func testInlineCodeStripped() {
        let result = CopyMessageFormatter.formatForCopy(content: "Run `npm install` now", embeds: [])
        XCTAssertEqual(result, "Run npm install now")
    }

    func testWhitespaceTrimmmed() {
        let result = CopyMessageFormatter.formatForCopy(content: "  Hello  \n\n  ", embeds: [])
        XCTAssertEqual(result, "Hello")
    }
}
