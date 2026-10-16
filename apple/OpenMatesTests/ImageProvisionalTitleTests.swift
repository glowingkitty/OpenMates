// Cold chat image references retain their readable attachment kind.
import XCTest
@testable import OpenMates

@MainActor
final class ImageProvisionalTitleTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPersistedImageReferenceUsesImageLabelWithoutRawIdentityOrDuplicateLabel() {
        for content in ["[[embed:photo-id]] describe the image", "describe the image\n\n[[embed:photo-id]]", "[[embedref:photo-id]] describe the image"] {
            XCTAssertEqual(ChatSendPipeline.provisionalTitleSource(content: content, composerEmbeds: [],
                embedTypesByID: ["photo-id": "image"]), "[Image] describe the image")
        }
        XCTAssertEqual(ChatSendPipeline.provisionalTitleSource(content: "[[embed:photo-id]]", composerEmbeds: [],
            embedTypesByID: ["photo-id": "image"]), "[Image]")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTitleReferenceTypesResolvePerIdentityAndUnknownReferencesStayGeneric() {
        XCTAssertEqual(ChatSendPipeline.titleByReplacingEmbedReferences("[[embed:photo]] [[embed:voice]]", embedTypes: [],
            embedTypesByID: ["photo": "image", "voice": "audio-recording"]), "[Image] [Audio]")
        XCTAssertEqual(ChatSendPipeline.provisionalTitleSource(content: "[[embed:unknown]] describe", composerEmbeds: []), "[Attachment] describe")
        XCTAssertEqual(ChatSendPipeline.provisionalTitleSource(content: "plain text", composerEmbeds: [], embedTypesByID: ["unrelated": "image"]), "plain text")
    }
}
