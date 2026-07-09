// Unit coverage for the Apple Tiptap composer bridge contract.
// The WebView itself is verified by UI tests; these fast checks keep command
// serialization, event decoding, and bundled resource availability stable.
// No private message content or network state is needed for these tests.

import XCTest
@testable import OpenMates

final class TiptapComposerBridgeTests: XCTestCase {
    func testCommandScriptSerializesTextSafely() throws {
        let script = try XCTUnwrap(TiptapComposerCommand.setContent("Hello \"OpenMates\"").script)

        XCTAssertTrue(script.contains("OpenMatesComposer.receive"))
        XCTAssertTrue(script.contains("setContent"))
        XCTAssertTrue(script.contains("Hello"))
        XCTAssertTrue(script.contains("\\\"OpenMates\\\""))
    }

    func testBridgeMessageDecodesContentChangedEvent() throws {
        let message = try XCTUnwrap(TiptapComposerBridgeMessage.decode([
            "type": "contentChanged",
            "text": "Draft",
            "height": 72,
        ]))

        XCTAssertEqual(message.type, "contentChanged")
        XCTAssertEqual(message.text, "Draft")
        XCTAssertEqual(message.height, 72)
    }

    func testComposerResourceIsBundledInMainTarget() {
        XCTAssertNotNil(TiptapComposerResource.indexURL(), "Expected TiptapComposer/index.html to be available in the app bundle")
    }
}
