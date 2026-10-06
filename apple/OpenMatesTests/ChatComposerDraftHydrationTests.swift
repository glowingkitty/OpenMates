import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class ChatComposerDraftHydrationTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence,message-input.embeds.gated-send
    func testRestoredImageAndAudioRetainLocalPreviewAndResolvedSendBundle() throws {
        let image = ComposerPendingEmbed.uiTestFixture
        let audio = EmbedRecord(id: "synthetic-audio", type: "audio-recording", status: .finished,
            data: .raw(["type": AnyCodable("audio-recording"), "filename": AnyCodable("synthetic.m4a"),
                "transcript": AnyCodable("Synthetic recording words")]), parentEmbedId: nil,
            appId: "audio", skillId: "recording", embedIds: nil, createdAt: nil)
        let snapshots = [ComposerDraftAttachment(embedRecord: image.record, localData: image.localData),
            ComposerDraftAttachment(embedRecord: audio, localData: Data([0, 1, 2, 3]))]
        let restored = try snapshots.map { try XCTUnwrap(ChatView.restoredComposerDraftEmbed($0)) }
        XCTAssertEqual(restored.map(\.id), [image.id, audio.id])
        XCTAssertTrue(restored.allSatisfy { $0.localData != nil && $0.serverPayload != nil })
        let session = NativeComposerSession(canonicalMarkdown: restored.map(\.markdownReference).joined(separator: "\n\n"))
        let nodes = session.controller.document.nodes.filter { $0.kind == "embed" }
        XCTAssertEqual(nodes.count, 2)
        let resolved = Dictionary(uniqueKeysWithValues: zip(nodes, restored).map { ($0.0.id, $0.1) })
        let saved = try XCTUnwrap(ChatView.draftAttachmentSnapshot(document: session.controller.document, resolved: resolved))
        XCTAssertEqual(saved.map { $0.embedRecord.id }, restored.map(\.id))
        XCTAssertEqual(saved.map(\.localData), snapshots.map(\.localData))
        XCTAssertNil(ChatView.draftAttachmentSnapshot(document: session.controller.document, resolved: [:]),
            "Missing restored payload must preserve prior encrypted snapshots")
    }
}
