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
    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testModelWhitespaceBoundariesPreserveUnicodeSeparatorsAndExactExclusionValues() async throws {
        let text = "Ask\u{00A0} Élodie 👩🏽‍💻 \tthen 42 Test Lane \nplease."
        let source = text as NSString
        let detector = PrivacyFilterNativeDetector(runner: WhitespaceBoundaryPIIRunner(spans: [
            .init(label: .privatePerson, range: source.range(of: "\u{00A0} Élodie 👩🏽‍💻 \t"), score: 0.99),
            .init(label: .privateAddress, range: source.range(of: " 42 Test Lane \n"), score: 0.99),
            .init(label: .secret, range: source.range(of: " \t"), score: 0.99)
        ]))
        let spans = try await detector.detectModelSpans(in: text)
        XCTAssertEqual(spans.count, 2, "Whitespace-only model spans must not become empty highlights")
        XCTAssertEqual(spans.map { source.substring(with: $0.range) }, ["Élodie 👩🏽‍💻", "42 Test Lane"])
        let matches = PrivacyFilterSpanMerger.mergeMatches(text: text, regexMatches: [], modelSpans: spans, excludedIds: [])
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "synthetic", source: text)])
        let redacted = ComposerPIIDecorations.redactedDocument(document: document, detectedMatches: matches)
        let redactedText = try ComposerMarkdownAdapter.serialize(redacted.document)
        XCTAssertEqual(redactedText, "Ask\u{00A0} " + matches[0].placeholder + " \tthen " + matches[1].placeholder + " \nplease.")
        XCTAssertEqual(redacted.mappings.map(\.original), ["Élodie 👩🏽‍💻", "42 Test Lane"])
        XCTAssertEqual(PIIDetector.restorePII(in: redactedText, mappings: redacted.mappings), text)

        let excluded = PrivacyFilterSpanMerger.mergeMatches(text: text, regexMatches: [], modelSpans: spans,
            excludedIds: [matches[0].id])
        let excludingPerson = ComposerPIIDecorations.redactedDocument(document: document,
            excludedIds: [matches[0].id], detectedMatches: excluded)
        let excludingText = try ComposerMarkdownAdapter.serialize(excludingPerson.document)
        XCTAssertEqual(excludingText, "Ask\u{00A0} Élodie 👩🏽‍💻 \tthen " + matches[1].placeholder + " \nplease.")
        XCTAssertEqual(excludingPerson.mappings.map(\.original), ["42 Test Lane"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCanonicalMentionRenderingPreservesCodeEmailsAndUnknownSyntax() {
        let tokens = InlineMarkdownTokenizer.parse("Use @focus:workflows:clarify_workflows, @skill:web:search and @best-model:best. `@mate:software_development` a@mate:software_development @unknown:x")
        let mentions = tokens.compactMap { token -> NativeMentionPresentation? in
            if case .mention(let mention) = token { return mention }; return nil
        }
        XCTAssertEqual(mentions.map(\.syntax), ["@focus:workflows:clarify_workflows", "@skill:web:search", "@best-model:best"])
        XCTAssertTrue(tokens.contains(.inlineCode("@mate:software_development")))
        XCTAssertTrue(tokens.contains { if case .text(let text, _) = $0 { return text.contains("@unknown:x") }; return false })
        XCTAssertFalse(mentions.contains { $0.kind == "mate" })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFocusIndicatorResolvesHumanNameWithoutActivationDelay() {
        let focus = FocusModeManager.FocusModeInfo.resolve("workflows-clarify_workflows")!
        XCTAssertEqual(focus.name, AppStrings.localized("app_focus_modes.workflows.clarify_workflows"))
        XCTAssertEqual(focus.iconName, "workflow")
        XCTAssertEqual(NativeMentionPresentation.parse("@focus:workflows:clarify_workflows")?.label, "@Workflows-Clarify-Workflows")
        XCTAssertEqual(NativeMentionPresentation.parse("@mate:software_development")?.label, "@sophia")
        let manager = FocusModeManager()
        manager.activate(focus)
        XCTAssertEqual(manager.activeFocusMode, focus)
        manager.deactivate()
        XCTAssertNil(manager.activeFocusMode)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testEveryMentionKindBuildsCanonicalAtom() throws {
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
            let node = try service.node(candidate: item.0, nodeId: "mention-\(index)")
            XCTAssertEqual(node.canonicalSyntax, item.1)
            XCTAssertEqual(node.displayLabel, item.0.displayLabel)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMentionCandidatesRejectMissingCanonicalComponents() {
        let candidate = ComposerMentionCandidate(
            kind: .aiModel,
            targetId: "model-1",
            displayLabel: "Model"
        )
        XCTAssertThrowsError(try ComposerMentionService().node(candidate: candidate, nodeId: "mention-1"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMentionInsertionPreservesSurroundingOrderAndSelection() throws {
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "Hello world")])
        let controller = try NativeComposerController(
            document: document,
            selection: NSRange(location: 6, length: 0)
        )
        let candidate = ComposerMentionCandidate(kind: .mate, targetId: "mate-1", displayLabel: "Mate")
        let node = try ComposerMentionService().node(candidate: candidate, nodeId: "mention-1")

        try controller.insertMention(node)

        XCTAssertEqual(controller.document.nodes.map(\.kind), ["text", "mention", "text"])
        XCTAssertEqual(controller.document.nodes.first?.source, "Hello ")
        XCTAssertEqual(controller.document.nodes.last?.source, "world")
        XCTAssertEqual(controller.selection, NSRange(location: 7, length: 0))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMentionInsertionReplacesOnlyActiveQuery() throws {
        let document = ComposerDocumentV1(
            version: 1,
            nodes: [.text(id: "text-1", source: "Hello @ma world")]
        )
        let controller = try NativeComposerController(
            document: document,
            selection: NSRange(location: 9, length: 0)
        )
        let candidate = ComposerMentionCandidate(kind: .mate, targetId: "mate-1", displayLabel: "Mate")
        let node = try ComposerMentionService().node(candidate: candidate, nodeId: "mention-1")

        try controller.insertMention(node, replacing: NSRange(location: 6, length: 3))

        XCTAssertEqual(controller.document.nodes.map(\.kind), ["text", "mention", "text"])
        XCTAssertEqual(controller.document.nodes.first?.source, "Hello ")
        XCTAssertEqual(controller.document.nodes.last?.source, " world")
        XCTAssertEqual(controller.selection, NSRange(location: 7, length: 0))
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testPIIRedactionChangesVisibleTextOnly() throws {
        let email = "person@composer-fixture.invalid"
        let mention = try ComposerMentionService().node(
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

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testDocumentRedactionDoesNotScanEmbedMetadata() {
        let phone = "+49 170 1234567"
        let email = "person@composer-fixture.invalid"
        let embed = ComposerNodeV1.embed(
            id: "embed-1",
            embedType: "maps-location",
            canonicalSource: "```json\n{\"phone\":\"\(phone)\"}\n```",
            referenceOnly: true,
            display: .init(title: "Location", mediaKind: "maps-location")
        )
        let document = ComposerDocumentV1(
            version: 1,
            nodes: [.text(id: "text-1", source: "Email \(email)"), embed]
        )

        let result = ComposerPIIDecorations.redactedDocument(document: document)

        XCTAssertEqual(result.mappings.map(\.original), [email])
        XCTAssertFalse(result.document.nodes[0].source?.contains(email) ?? true)
        XCTAssertEqual(result.document.nodes[1].canonicalSource, embed.canonicalSource)
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testNativePIIDecorationMapsCanonicalRangePastEmbedToVisibleTextOffset() throws {
        let email = "person@composer-fixture.invalid"
        let embed = ComposerNodeV1.embed(
            id: "embed-1",
            embedType: "image",
            canonicalSource: "```json\n{\"embed_id\":\"embed-1\"}\n```",
            referenceOnly: true,
            display: .init(title: "Private image", mediaKind: "image")
        )
        let document = ComposerDocumentV1(
            version: 1,
            nodes: [embed, .text(id: "text-1", source: "Email \(email)")]
        )
        let canonical = try ComposerMarkdownAdapter.serialize(document)
        let controller = try NativeComposerController(document: document, selection: NSRange(location: 0, length: 0))
        let matches = PIIDetector.detect(in: canonical)

        let decorations = ComposerPIIDecorations.nativeDecorations(
            matches: matches,
            visibleText: controller.attributedString.string
        )

        let decoration = try XCTUnwrap(decorations.first)
        XCTAssertEqual(
            (controller.attributedString.string as NSString).substring(with: decoration.range),
            email
        )
        XCTAssertEqual(decoration.id, matches.first?.id)
    }
    // contract-test: supporting surface=gui.apple assertions=pii.composer.detect-redact-exclude,pii.apple.enhanced-local-detection
    func testRedactionReplacesOneMatchAcrossAdjacentTextNodes() {
        let document = ComposerDocumentV1(version: 1, nodes: [
            .text(id: "first", source: "ada@"), .text(id: "second", source: "example.test")
        ])
        let result = ComposerPIIDecorations.redactedDocument(document: document)
        XCTAssertEqual(result.mappings.map(\.original), ["ada@example.test"])
        XCTAssertEqual(result.document.nodes.map(\.id), ["first", "second"])
        XCTAssertEqual(result.document.nodes[1].source, "")
        XCTAssertFalse(ComposerPIIDecorations.visibleText(document: result.document).contains("ada@example.test"))
        XCTAssertEqual(result.document.nodes[0].source, result.mappings.first?.placeholder)
        XCTAssertEqual(document.nodes[0].source, "ada@")
    }

    // contract-test: supporting surface=gui.apple assertions=pii.composer.detect-redact-exclude,pii.apple.enhanced-local-detection
    func testEnhancedRedactionSpansHardBreakButCannotCrossOpaqueAtom() {
        let document = ComposerDocumentV1(version: 1, nodes: [
            .text(id: "first", source: "Ada"), .init(kind: "hardBreak", id: "break"),
            .text(id: "second", source: "Lovelace")
        ])
        let match = PIIMatch(id: "synthetic-model-match", type: .genericSecret,
            value: "Ada\nLovelace", range: NSRange(location: 0, length: 12), placeholder: "[PERSON]")
        let result = ComposerPIIDecorations.redactedDocument(document: document, detectedMatches: [match])
        XCTAssertEqual(result.mappings.map(\.original), ["Ada\nLovelace"])
        XCTAssertEqual(result.document.nodes.map(\.id), document.nodes.map(\.id))
        XCTAssertEqual(ComposerPIIDecorations.visibleText(document: result.document), "[PERSON]")
        XCTAssertEqual(document.nodes[1].kind, "hardBreak")
        let atom = ComposerNodeV1.mention(id: "opaque", mentionKind: "mate", targetId: "public-fixture",
            canonicalSyntax: "@mate:public-fixture", displayLabel: "Ada Lovelace")
        let opaqueDocument = ComposerDocumentV1(version: 1, nodes: [document.nodes[0], atom, document.nodes[2]])
        let unsafeMatch = PIIMatch(id: "cross-atom", type: .genericSecret,
            value: "Ada\u{FFFC}Lovelace", range: NSRange(location: 0, length: 12), placeholder: "[PERSON]")
        let safe = ComposerPIIDecorations.redactedDocument(document: opaqueDocument, detectedMatches: [unsafeMatch])
        XCTAssertEqual(safe.document, opaqueDocument)
        XCTAssertTrue(safe.mappings.isEmpty)
    }

}

private struct WhitespaceBoundaryPIIRunner: PrivacyFilterModelRunning {
    let spans: [PrivacyFilterModelSpan]
    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan] { spans }
}
