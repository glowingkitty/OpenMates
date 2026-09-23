// Unit coverage for the shared Apple message composer configuration contract.
// The visual component is verified by UI tests; these deterministic tests keep
// capability ordering and send visibility stable without launching SwiftUI,
// touching credentials, or sending private chat content.
// This is the fast contract layer for docs/specs/apple-unified-message-composer/spec.yml.

import XCTest
@testable import OpenMates

final class MessageComposerConfigurationTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.actions.visibility
    func testMainAndWelcomeComposerCapabilitiesUseWebActionOrder() {
        let expected: [MessageComposerAction] = [.files, .maps, .sketch, .camera, .recordAudio, .send]

        XCTAssertEqual(MessageComposerCapabilities.mainChat.orderedActions, expected)
        XCTAssertEqual(MessageComposerCapabilities.welcome.orderedActions, expected)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.actions.visibility
    func testQuickCaptureHidesUnavailableCapabilitiesWithoutReorderingAvailableActions() {
        XCTAssertEqual(MessageComposerCapabilities.quickCapture.orderedActions, [.recordAudio, .send])
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.actions.visibility
    func testSendButtonVisibilityFollowsTextAndPendingEmbeds() {
        let capabilities = MessageComposerCapabilities.mainChat

        XCTAssertFalse(capabilities.showsSendButton(text: "", hasPendingEmbeds: false))
        XCTAssertFalse(capabilities.showsSendButton(text: "   ", hasPendingEmbeds: false))
        XCTAssertTrue(capabilities.showsSendButton(text: "Hello", hasPendingEmbeds: false))
        XCTAssertTrue(capabilities.showsSendButton(text: "", hasPendingEmbeds: true))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.actions.visibility
    func testDisabledSendCapabilityNeverShowsSendButton() {
        let capabilities = MessageComposerCapabilities(send: false)

        XCTAssertFalse(capabilities.showsSendButton(text: "Hello", hasPendingEmbeds: false))
        XCTAssertFalse(capabilities.showsSendButton(text: "", hasPendingEmbeds: true))
        XCTAssertEqual(capabilities.orderedActions, [])
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testPlaceholderIsVisibleOnlyForEmptyBlurredComposer() {
        XCTAssertTrue(MessageComposerPresentation.showsPlaceholder(markdown: "", isFocused: false))
        XCTAssertFalse(MessageComposerPresentation.showsPlaceholder(markdown: "", isFocused: true))
        XCTAssertFalse(MessageComposerPresentation.showsPlaceholder(markdown: "Draft", isFocused: false))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testCollapsedTextEditorShowsAtMostThreeLinesBeforeScrolling() {
        let twoLineContentHeight =
            (MessageComposerMetric.editorVerticalInset * 2) + (MessageComposerMetric.editorLineHeight * 2)
        let fiveLineContentHeight =
            (MessageComposerMetric.editorVerticalInset * 2) + (MessageComposerMetric.editorLineHeight * 5)

        XCTAssertEqual(
            MessageComposerMetric.editorHeight(for: twoLineContentHeight, containsEmbed: false),
            twoLineContentHeight,
            accuracy: 0.01
        )
        XCTAssertEqual(
            MessageComposerMetric.editorHeight(for: fiveLineContentHeight, containsEmbed: false),
            MessageComposerMetric.collapsedTextEditorMaxHeight,
            accuracy: 0.01
        )
        XCTAssertEqual(
            MessageComposerMetric.collapsedTextFieldMaxHeight,
            MessageComposerMetric.collapsedTextEditorMaxHeight
                + MessageComposerMetric.expandedBottomReservedHeight,
            accuracy: 0.01
        )
        XCTAssertEqual(
            MessageComposerMetric.editorHeight(for: 220, containsEmbed: true),
            220,
            "Embed previews retain their existing larger editor viewport"
        )
    }
}
