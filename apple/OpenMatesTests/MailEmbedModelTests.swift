// Web contract: mail/MailEmbedPreview.svelte and mail/MailEmbedFullscreen.svelte.
import XCTest
@testable import OpenMates

@MainActor
final class MailEmbedModelTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCanonicalFieldsAndLegacySearchAliases() {
        let mail = MailEmbedModel(["receiver": AnyCodable("team@example.test"), "to": AnyCodable("old@example.test"), "subject": AnyCodable("Update"), "content": AnyCodable("  Hi,  \n\n Body \n"), "body": AnyCodable("old")])
        XCTAssertEqual(mail.receiver, "team@example.test")
        XCTAssertEqual(mail.previewBody, "Hi,\nBody")
        XCTAssertEqual(mail.content, "  Hi,  \n\n Body \n")
        let legacy = MailEmbedModel(["from": AnyCodable("sender@example.test"), "snippet": AnyCodable("Search result")])
        XCTAssertEqual(legacy.receiver, "sender@example.test")
        XCTAssertEqual(legacy.content, "Search result")
        XCTAssertEqual(MailEmbedModel(["to": AnyCodable("to@example.test"), "body": AnyCodable("Body")]).content, "Body")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMailURLIncludesEscapedSubjectBodyAndFooter() {
        let mail = MailEmbedModel(["receiver": AnyCodable("a+b@example.test"), "subject": AnyCodable("A & B?"), "content": AnyCodable("One\r\nTwo #3"), "footer": AnyCodable("Regards")])
        XCTAssertEqual(mail.mailtoURL?.absoluteString, "mailto:a%2Bb%40example.test?subject=A%20%26%20B%3F&body=One%0D%0ATwo%20%233%0A%0ARegards")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPIIVisibilityAppliesToEveryDisplayedAndExportedFieldWithoutMutatingSource() {
        let mapping = PIIMapping(placeholder: "[EMAIL_1_com]", original: "anna@example.test", type: "email")
        let source = MailEmbedModel(["receiver": AnyCodable(mapping.original), "subject": AnyCodable(mapping.original), "content": AnyCodable(mapping.original), "footer": AnyCodable(mapping.original)])
        let hidden = source.applyingPII(mappings: [mapping], revealed: false)
        XCTAssertEqual(hidden.receiver, mapping.placeholder)
        XCTAssertEqual(hidden.subject, mapping.placeholder)
        XCTAssertEqual(hidden.content, mapping.placeholder)
        XCTAssertEqual(hidden.footer, mapping.placeholder)
        XCTAssertFalse(hidden.copyText.contains(mapping.original))
        XCTAssertFalse(hidden.mailtoURL!.absoluteString.contains("anna"))
        let visible = hidden.applyingPII(mappings: [mapping], revealed: true)
        XCTAssertEqual(visible.receiver, mapping.original)
        XCTAssertTrue(visible.mailtoURL!.absoluteString.contains("anna%40example.test"))
        XCTAssertEqual(source.receiver, mapping.original)
    }
}
