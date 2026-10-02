// Unchanged fullscreen geometry refreshes preserve the actual native Mail selection.
// Web: frontend/packages/ui/src/components/embeds/mail/MailEmbedFullscreen.svelte
import XCTest
@testable import OpenMates
#if canImport(UIKit)
import UIKit

@MainActor
final class MailDraftTextSelectionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testUnchangedProductionUpdatePreservesTextSelection() {
        let view = MailDraftText.makeTextView()
        let draft = "Hi Anna,\n\nThe latest sprint review went well."
        MailDraftText.update(value: draft, in: view)
        view.selectedRange = NSRange(location: 10, length: 16)
        let selection = view.selectedRange
        let content = view.attributedText!

        MailDraftText.update(value: draft, in: view)

        XCTAssertEqual(view.selectedRange, selection)
        XCTAssertEqual(view.attributedText, content)
        XCTAssertTrue(view.isSelectable)
        XCTAssertFalse(view.isScrollEnabled)
        XCTAssertEqual(view.accessibilityLabel, draft)

        let replacement = "The draft changed."
        MailDraftText.update(value: replacement, in: view)
        XCTAssertEqual(view.text, replacement)
        XCTAssertEqual(view.accessibilityLabel, replacement)
    }
}
#endif
