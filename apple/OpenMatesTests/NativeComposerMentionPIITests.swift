// Contract tests for selection-aware mentions and safe PII decorations.
// Every approved mention kind has deterministic canonical syntax.
// Mention insertion preserves surrounding document order and UTF-16 selection.
// PII detection scans visible text nodes but not machine metadata atoms.
// Redaction snapshots never mutate embed IDs or canonical mention syntax.

import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class NativeComposerMentionPIITests: XCTestCase {
    func testEveryMentionKindBuildsCanonicalAtom() {
        let service = ComposerMentionService()
        let cases: [(ComposerMentionCandidate, String)] = [
            (.init(kind: .mate, targetId: "mate-1", displayLabel: "Mate"), "@mate:mate-1"),
            (.init(kind: .aiModel, targetId: "model-1", displayLabel: "Model", providerId: "provider-1"), "@ai-model:model-1:provider-1"),
            (.init(kind: .bestModel, targetId: "best", displayLabel: "Best"), "@best-model:best"),
            (.init(kind: .skill, targetId: "search", displayLabel: "Search", appId: "web"), "@skill:web:search"),
            (.init(kind: .focus, targetId: "research", displayLabel: "Research", appId: "web"), "@focus:web:research"),
            (.init(kind: .project, targetId: "project-1", displayLabel: "Project", accessMode: "read"), "@project:project-1:read"),
            (.init(kind: .memory, targetId: "preferences", displayLabel: "Memory", appId: "ai", memoryType: "text"), "@memory:ai:preferences:text"),
        ]

        for (index, item) in cases.enumerated() {
            let node = service.node(candidate: item.0, nodeId: "mention-\(index)")
            XCTAssertEqual(node.canonicalSyntax, item.1)
            XCTAssertEqual(node.displayLabel, item.0.displayLabel)
        }
    }

    func testMentionInsertionPreservesSurroundingOrderAndSelection() throws {
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "Hello world")])
        let controller = try NativeComposerController(
            document: document,
            selection: NSRange(location: 6, length: 0)
        )
        let candidate = ComposerMentionCandidate(kind: .mate, targetId: "mate-1", displayLabel: "Mate")
        let node = ComposerMentionService().node(candidate: candidate, nodeId: "mention-1")

        try controller.insertMention(node)

        XCTAssertEqual(controller.document.nodes.map(\.kind), ["text", "mention", "text"])
        XCTAssertEqual(controller.document.nodes.first?.source, "Hello ")
        XCTAssertEqual(controller.document.nodes.last?.source, "world")
        XCTAssertEqual(controller.selection, NSRange(location: 7, length: 0))
    }

    func testPIIRedactionChangesVisibleTextOnly() {
        let email = "person@composer-fixture.invalid"
        let mention = ComposerMentionService().node(
            candidate: .init(kind: .mate, targetId: email, displayLabel: "Private mate"),
            nodeId: "mention-1"
        )
        let embed = ComposerNodeV1.embed(
            id: "embed-1",
            embedType: "image",
            canonicalSource: "```json\n{\"embed_id\":\"\(email)\"}\n```",
            referenceOnly: true,
            display: .init(title: "Private image", mediaKind: "image")
        )
        let document = ComposerDocumentV1(
            version: 1,
            nodes: [.text(id: "text-1", source: "Email \(email)"), mention, embed]
        )

        let snapshot = ComposerPIIDecorations().redactedSnapshot(document: document)

        XCTAssertEqual(snapshot.mappings.count, 1)
        XCTAssertEqual(snapshot.mappings.first?.original, email)
        XCTAssertEqual(snapshot.document.nodes[0].source, "Email {{EMAIL_1}}")
        XCTAssertEqual(snapshot.document.nodes[1].canonicalSyntax, mention.canonicalSyntax)
        XCTAssertEqual(snapshot.document.nodes[2].canonicalSource, embed.canonicalSource)
    }
}
