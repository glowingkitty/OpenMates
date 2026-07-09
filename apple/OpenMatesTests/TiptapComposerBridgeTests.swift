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
            "embedCount": 1,
            "blockingEmbedCount": 0,
        ]))

        XCTAssertEqual(message.type, "contentChanged")
        XCTAssertEqual(message.text, "Draft")
        XCTAssertEqual(message.height, 72)
        XCTAssertEqual(message.embedCount, 1)
        XCTAssertEqual(message.blockingEmbedCount, 0)
    }

    func testEmbedBridgeCommandsSerialize() throws {
        let embed = TiptapComposerEmbedCommand(
            id: "embed-1",
            type: "image",
            status: "uploading",
            filename: "photo.png",
            referenceType: "image"
        )

        let insertScript = try XCTUnwrap(TiptapComposerCommand.insertEmbed(embed).script)
        XCTAssertTrue(insertScript.contains("insertEmbed"))
        XCTAssertTrue(insertScript.contains("photo.png"))

        let updateScript = try XCTUnwrap(TiptapComposerCommand.updateEmbed(id: "embed-1", attrs: embed).script)
        XCTAssertTrue(updateScript.contains("updateEmbed"))
        XCTAssertTrue(updateScript.contains("embed-1"))

        let removeScript = try XCTUnwrap(TiptapComposerCommand.removeEmbed("embed-1").script)
        XCTAssertTrue(removeScript.contains("removeEmbed"))
        XCTAssertTrue(removeScript.contains("embed-1"))

        XCTAssertTrue(try XCTUnwrap(TiptapComposerCommand.serializeMarkdown.script).contains("serializeMarkdown"))
        XCTAssertTrue(try XCTUnwrap(TiptapComposerCommand.getDiagnostics.script).contains("getDiagnostics"))
    }

    func testBridgeMessageDecodesEditorOwnedEmbedDiagnostics() throws {
        let message = try XCTUnwrap(TiptapComposerBridgeMessage.decode([
            "type": "diagnostics",
            "text": "```json\n{\"type\":\"image\",\"embed_id\":\"embed-1\"}\n```",
            "embedCount": 1,
            "blockingEmbedCount": 1,
            "extensions": ["StarterKit", "Placeholder", "Embed"],
            "embedCommandNames": ["insertEmbed", "updateEmbed", "removeEmbed", "serializeMarkdown", "getDiagnostics"],
        ]))

        XCTAssertEqual(message.type, "diagnostics")
        XCTAssertEqual(message.embedCount, 1)
        XCTAssertEqual(message.blockingEmbedCount, 1)
        XCTAssertTrue(message.extensions?.contains("Embed") == true)
        XCTAssertTrue(message.embedCommandNames?.contains("insertEmbed") == true)
    }

    func testComposerResourceIsBundledInMainTarget() {
        XCTAssertNotNil(TiptapComposerResource.indexURL(), "Expected TiptapComposer/index.html to be available in the app bundle")
    }
}
