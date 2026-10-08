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
    func testFullscreenControlTracksInlineOverflowAndStaysReachableInFullscreen() {
        let handler = ComposerFullscreenControlHandler()
        XCTAssertFalse(handler.isVisible(compact: false, fullscreen: false, contentOverflows: false),
            "Empty, short, and fully visible inline content must not expose Expand")
        XCTAssertTrue(handler.isVisible(compact: false, fullscreen: false, contentOverflows: true))
        XCTAssertTrue(handler.isVisible(compact: false, fullscreen: true, contentOverflows: false),
            "Collapse stays reachable after fullscreen makes the document fit")
        XCTAssertFalse(handler.isVisible(compact: false, fullscreen: false, contentOverflows: false),
            "Reducing or clearing an inline document must remove its control and lane")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testCompactAndOverlayComposersHideTheFullscreenControlAndItsLane() {
        let handler = ComposerFullscreenControlHandler()
        XCTAssertFalse(handler.isVisible(compact: true, fullscreen: false, contentOverflows: true))
        XCTAssertFalse(handler.isVisible(compact: true, fullscreen: true, contentOverflows: true))
        let overlayHandler = ComposerFullscreenControlHandler(isEnabled: false)
        XCTAssertFalse(overlayHandler.isVisible(compact: false, fullscreen: false, contentOverflows: true))
        XCTAssertFalse(overlayHandler.isVisible(compact: false, fullscreen: true, contentOverflows: true))
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
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testImageEmbedRetainsPreviewAndThreeTextLinesBeforeScrolling() {
        let fourLineEmbedContentHeight =
            MessageComposerMetric.embedPreviewHeight
                + (MessageComposerMetric.editorVerticalInset * 2)
                + (MessageComposerMetric.editorLineHeight * 4)

        XCTAssertEqual(
            MessageComposerMetric.editorHeight(for: fourLineEmbedContentHeight, containsEmbed: true),
            MessageComposerMetric.embedTextEditorMaxHeight,
            accuracy: 0.01
        )
        XCTAssertEqual(
            MessageComposerMetric.embedTextFieldMaxHeight,
            MessageComposerMetric.embedTextEditorMaxHeight
                + MessageComposerMetric.expandedBottomReservedHeight,
            accuracy: 0.01,
            "The action row must remain outside the image and three visible text lines"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,message-input.layout.responsive-parity
    func testLongImageFilenameUsesMiddleEllipsisAndKeepsExtension() {
        let original = "Screenshot 2026-09-24 at 11.16.43 in OpenMates.jpg"
        let displayed = ComposerAttachmentFilename.displayName(for: original)

        XCTAssertEqual(displayed.count, ComposerAttachmentFilename.maximumDisplayLength)
        XCTAssertTrue(displayed.contains("…"))
        XCTAssertTrue(displayed.hasSuffix(".jpg"))
        XCTAssertEqual(ComposerAttachmentFilename.displayName(for: "photo.jpg"), "photo.jpg")
    }
}
