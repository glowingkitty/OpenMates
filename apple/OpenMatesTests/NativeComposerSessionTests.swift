// Contract tests for the host-owned native composer session.
// The session is the only product authority for markdown, nodes, and revision.
// Pending attachments update in place under one stable semantic node identity.
// Serialization omits unresolved placeholders and emits durable references only.
// Removing an inline atom updates both the TextKit document and host markdown.

import XCTest
@testable import OpenMates

@MainActor
final class NativeComposerSessionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence
    func testTextMutationPublishesCanonicalMarkdownAndRevision() throws {
        let session = NativeComposerSession(canonicalMarkdown: "Hello")
        let initialRevision = session.revision

        try session.controller.setSelection(NSRange(location: 5, length: 0))
        try session.replaceSelection(with: " world")

        XCTAssertEqual(session.canonicalMarkdown, "Hello world")
        XCTAssertGreaterThan(session.revision, initialRevision)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testPendingEmbedResolvesInPlaceAndSerializesDurableReference() throws {
        let session = NativeComposerSession(canonicalMarkdown: "Before ")
        let nodeID = "composer:embed:upload-1"

        try session.insertPendingEmbed(
            nodeID: nodeID,
            embedType: "image",
            title: "Fixture image"
        )
        XCTAssertEqual(session.controller.document.nodes.last?.id, nodeID)
        XCTAssertEqual(session.controller.document.nodes.last?.status, "draft")
        XCTAssertTrue(session.hasBlockingEmbeds)
        XCTAssertFalse(session.canonicalMarkdown.contains("upload-1"))

        try session.resolveEmbed(
            nodeID: nodeID,
            durableEmbedID: "durable-image-1",
            referenceType: "image",
            status: "finished"
        )

        XCTAssertEqual(session.controller.document.nodes.last?.id, nodeID)
        XCTAssertEqual(session.controller.document.nodes.last?.status, "finished")
        XCTAssertFalse(session.hasBlockingEmbeds)
        XCTAssertTrue(session.canonicalMarkdown.contains("durable-image-1"))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testPendingRecordingPublishesRawTranscriptWithoutInventingDurableIdentity() throws {
        let session = NativeComposerSession(canonicalMarkdown: "")
        let nodeID = "composer:embed:recording-1"
        try session.insertPendingEmbed(nodeID: nodeID, embedType: "recording", title: "recording.m4a")

        try session.updatePendingEmbedTitle(nodeID: nodeID, title: "Raw words from realtime transcription")

        let pending = try XCTUnwrap(session.controller.document.nodes.first)
        XCTAssertEqual(pending.id, nodeID)
        XCTAssertEqual(pending.display?.title, "Raw words from realtime transcription")
        XCTAssertNil(pending.contentRef)
        XCTAssertFalse(session.canonicalMarkdown.contains("embed_id"))
        XCTAssertTrue(session.hasBlockingEmbeds)

        try session.resolveEmbed(
            nodeID: nodeID,
            durableEmbedID: "server-recording-1",
            referenceType: "audio-recording",
            status: "finished"
        )
        let resolved = try XCTUnwrap(session.controller.document.nodes.first)
        XCTAssertEqual(resolved.id, nodeID)
        XCTAssertEqual(resolved.contentRef, "embed:server-recording-1")
        XCTAssertFalse(session.hasBlockingEmbeds)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testRemoveEmbedUpdatesDocumentAndMarkdown() throws {
        let session = NativeComposerSession(canonicalMarkdown: "")
        try session.insertPendingEmbed(nodeID: "node-1", embedType: "pdf", title: "PDF")
        try session.resolveEmbed(
            nodeID: "node-1",
            durableEmbedID: "pdf-1",
            referenceType: "pdf",
            status: "finished"
        )

        try session.removeEmbed(nodeID: "node-1")

        XCTAssertTrue(session.controller.document.nodes.isEmpty)
        XCTAssertEqual(session.canonicalMarkdown, "")
    }
}
