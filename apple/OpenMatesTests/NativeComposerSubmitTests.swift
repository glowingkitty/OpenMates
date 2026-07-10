// Contract tests for native composer submit and newline policy.
// Touch Return inserts a break while desktop Return submits when eligible.
// Marked text, empty content, conversions, and blocking embeds never send early.
// Finished or processing embeds are sendable without surrounding text.
// Request and revision guards allow at most one remote handoff per submit.

import Foundation
import XCTest
@testable import OpenMates

final class NativeComposerSubmitTests: XCTestCase {
    func testPlatformReturnAndModifierPolicyMatchesWebContract() {
        let document = textDocument("Hello")
        XCTAssertEqual(
            ComposerSubmitPolicy.decision(
                document: document,
                platform: .touch,
                trigger: .returnKey,
                modifiers: [],
                markedTextRange: nil,
                conversionInFlight: false
            ),
            .insertHardBreak
        )
        XCTAssertEqual(
            ComposerSubmitPolicy.decision(
                document: document,
                platform: .desktop,
                trigger: .returnKey,
                modifiers: [.shift],
                markedTextRange: nil,
                conversionInFlight: false
            ),
            .insertHardBreak
        )
        XCTAssertEqual(
            ComposerSubmitPolicy.decision(
                document: document,
                platform: .desktop,
                trigger: .returnKey,
                modifiers: [],
                markedTextRange: nil,
                conversionInFlight: false
            ),
            .submit
        )
    }

    func testEmptySingleMentionMarkedTextAndConversionAreBlockedOrDeferred() {
        let empty = textDocument("  \n")
        XCTAssertEqual(decision(for: empty), .blocked(.empty))

        let singleMention = ComposerDocumentV1(version: 1, nodes: [mention(id: "mention-1")])
        XCTAssertEqual(decision(for: singleMention), .blocked(.empty))

        let twoMentions = ComposerDocumentV1(
            version: 1,
            nodes: [mention(id: "mention-1"), mention(id: "mention-2")]
        )
        XCTAssertEqual(decision(for: twoMentions), .submit)

        XCTAssertEqual(
            ComposerSubmitPolicy.decision(
                document: textDocument("IME"),
                platform: .desktop,
                trigger: .sendButton,
                modifiers: [],
                markedTextRange: NSRange(location: 0, length: 1),
                conversionInFlight: false
            ),
            .blocked(.markedText)
        )
        XCTAssertEqual(
            ComposerSubmitPolicy.decision(
                document: textDocument("Converting"),
                platform: .desktop,
                trigger: .sendButton,
                modifiers: [],
                markedTextRange: nil,
                conversionInFlight: true
            ),
            .deferred([])
        )
    }

    func testEmbedLifecycleDeterminesSendabilityAndBlockers() {
        XCTAssertEqual(decision(for: embedDocument(status: .finished)), .submit)
        XCTAssertEqual(decision(for: embedDocument(status: .processing)), .submit)
        XCTAssertEqual(
            decision(for: embedDocument(status: .uploading)),
            .deferred([.init(nodeId: "embed-1", generation: 1)])
        )
        XCTAssertEqual(
            decision(for: embedDocument(status: .error)),
            .deferred([.init(nodeId: "embed-1", generation: 1)])
        )
        XCTAssertEqual(decision(for: embedDocument(status: .cancelled)), .blocked(.empty))
    }

    func testSubmitGuardRejectsRepeatedButtonKeyboardAndEditSaveRequests() async {
        let guardState = ComposerSubmitGuard()
        let first = await guardState.begin(requestId: "request-1", documentRevision: 13)
        let repeated = await guardState.begin(requestId: "request-1", documentRevision: 13)
        let sameRevision = await guardState.begin(requestId: "request-2", documentRevision: 13)
        XCTAssertTrue(first)
        XCTAssertFalse(repeated)
        XCTAssertFalse(sameRevision)

        await guardState.complete(requestId: "request-1")
        let replay = await guardState.begin(requestId: "request-1", documentRevision: 13)
        let edited = await guardState.begin(requestId: "request-3", documentRevision: 14)
        XCTAssertFalse(replay)
        XCTAssertTrue(edited)
    }

    private func decision(for document: ComposerDocumentV1) -> ComposerSubmitDecision {
        ComposerSubmitPolicy.decision(
            document: document,
            platform: .desktop,
            trigger: .sendButton,
            modifiers: [],
            markedTextRange: nil,
            conversionInFlight: false
        )
    }

    private func textDocument(_ source: String) -> ComposerDocumentV1 {
        .init(version: 1, nodes: [.text(id: "text-1", source: source)])
    }

    private func mention(id: String) -> ComposerNodeV1 {
        .mention(
            id: id,
            mentionKind: "mate",
            targetId: id,
            canonicalSyntax: "@mate:\(id)",
            displayLabel: "Synthetic mate"
        )
    }

    private func embedDocument(status: AppleComposerEmbedLifecycleState) -> ComposerDocumentV1 {
        let node = ComposerNodeV1.embed(
            id: "embed-1",
            embedType: "image",
            canonicalSource: "```json\n{\"type\":\"image\",\"embed_id\":\"synthetic\"}\n```",
            referenceOnly: true,
            display: .init(title: "Synthetic", mediaKind: "image")
        ).updatingStatus(status.rawValue)
        return .init(version: 1, nodes: [node])
    }
}
