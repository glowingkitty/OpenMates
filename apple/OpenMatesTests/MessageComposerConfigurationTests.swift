// Unit coverage for the shared Apple message composer configuration contract.
// The visual component is verified by UI tests; these deterministic tests keep
// capability ordering and send visibility stable without launching SwiftUI,
// touching credentials, or sending private chat content.
// This is the fast contract layer for docs/specs/apple-unified-message-composer/spec.yml.

import XCTest
@testable import OpenMates

final class MessageComposerConfigurationTests: XCTestCase {
    func testMainAndWelcomeComposerCapabilitiesUseWebActionOrder() {
        let expected: [MessageComposerAction] = [.files, .maps, .sketch, .camera, .recordAudio, .send]

        XCTAssertEqual(MessageComposerCapabilities.mainChat.orderedActions, expected)
        XCTAssertEqual(MessageComposerCapabilities.welcome.orderedActions, expected)
    }

    func testQuickCaptureHidesUnavailableCapabilitiesWithoutReorderingAvailableActions() {
        XCTAssertEqual(MessageComposerCapabilities.quickCapture.orderedActions, [.recordAudio, .send])
    }

    func testSendButtonVisibilityFollowsTextAndPendingEmbeds() {
        let capabilities = MessageComposerCapabilities.mainChat

        XCTAssertFalse(capabilities.showsSendButton(text: "", hasPendingEmbeds: false))
        XCTAssertFalse(capabilities.showsSendButton(text: "   ", hasPendingEmbeds: false))
        XCTAssertTrue(capabilities.showsSendButton(text: "Hello", hasPendingEmbeds: false))
        XCTAssertTrue(capabilities.showsSendButton(text: "", hasPendingEmbeds: true))
    }

    func testDisabledSendCapabilityNeverShowsSendButton() {
        let capabilities = MessageComposerCapabilities(send: false)

        XCTAssertFalse(capabilities.showsSendButton(text: "Hello", hasPendingEmbeds: false))
        XCTAssertFalse(capabilities.showsSendButton(text: "", hasPendingEmbeds: true))
        XCTAssertEqual(capabilities.orderedActions, [])
    }
}
