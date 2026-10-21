// Source-order and disclosure regression coverage; synthetic placeholders only.
import XCTest
@testable import OpenMates

@MainActor
final class AssistantActivityProjectionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.rendering.assistant-document-convergence
    func testRunsPreserveProseOrderAndDoNotReverseSkills() {
        let blocks = [paragraph("Before", 0), references([("skill-1", "app-skill-use"), ("skill-2", "app-skill-use")], 1), paragraph("Between", 2), references([("skill-3", "app-skill-use")], 3), paragraph("After", 4)]
        let result = AssistantActivityProjection.segments(blocks: blocks, embeds: [:])
        XCTAssertEqual(result.map(\.isActivity), [false, true, false, true, false])
        XCTAssertEqual(result.filter(\.isActivity).map { $0.items.map(\.id) }, [["skill-1", "skill-2"], ["skill-3"]])
        XCTAssertEqual(result.filter { !$0.isActivity }.flatMap(\.units).map { $0.block.document.text }, ["Before", "Between", "After"])
        XCTAssertEqual(result[2].id, blocks[2].id)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testMixedEmbedGroupKeepsOrdinaryResultsAtSourcePosition() {
        let result = AssistantActivityProjection.segments(blocks: [references([("skill", "app-skill-use"), ("result", "web-website"), ("next", "app-skill-use")], 0)], embeds: [:])
        XCTAssertEqual(result.map(\.isActivity), [true, false, true])
        XCTAssertEqual(result.flatMap(\.units).flatMap { $0.block.document.embedReferences.map(\.id) }, ["skill", "result", "next"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testDuplicateInvocationRemovedButRepeatedFocusAnchorPreserved() {
        let result = AssistantActivityProjection.segments(blocks: [references([("skill", "app-skill-use"), ("focus", "focus-mode-activation")], 0), paragraph("After", 1), references([("skill", "app-skill-use"), ("focus", "focus-mode-activation")], 2)], embeds: [:])
        XCTAssertEqual(result.filter(\.isActivity).flatMap(\.items).map(\.id), ["skill", "focus", "focus"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.surface.semantic-parity
    func testUnknownSkillStaysPendingAndDoesNotEndResponse() {
        let result = AssistantActivityProjection.segments(blocks: [references([("missing", "app-skill-use")], 0)], embeds: [:])
        XCTAssertFalse(result[0].items[0].terminal)
        XCTAssertTrue(result[0].isActive(responseActive: true, thinkingStreaming: false, openFocusIDs: [], activeBatchIDs: []))
        XCTAssertFalse(result[0].isActive(responseActive: false, thinkingStreaming: false, openFocusIDs: [], activeBatchIDs: []))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDisclosureAutoCollapsesAndRetainsManualChoiceAcrossFinalization() {
        var automatic = AssistantActivityDisclosureState()
        automatic.synchronize(active: true); XCTAssertTrue(automatic.expanded)
        automatic.synchronize(active: false); XCTAssertFalse(automatic.expanded)
        var manual = AssistantActivityDisclosureState()
        manual.synchronize(active: true); manual.toggle()
        manual.synchronize(active: false); manual.synchronize(active: true)
        XCTAssertFalse(manual.expanded)
        manual.toggle(); manual.synchronize(active: false)
        XCTAssertTrue(manual.expanded)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testAppendingActivityKeepsExistingParagraphIdentity() {
        let before = [paragraph("First", 0), paragraph("Second", 1)]
        let first = AssistantActivityProjection.segments(blocks: before, embeds: [:])
        let second = AssistantActivityProjection.segments(blocks: before + [references([("skill", "app-skill-use")], 2), paragraph("Last", 3)], embeds: [:])
        XCTAssertEqual(Array(second.prefix(2)), first)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.surface.semantic-parity
    func testTrailingAuthoredProseSettlesPendingAndStaleProcessingSkills() {
        let stale = EmbedRecord(id: "stale-processing", type: "app-skill-use", status: .processing,
            data: nil, parentEmbedId: nil, appId: "web", skillId: nil, embedIds: nil, createdAt: nil)
        for skillID in ["pending", stale.id] {
            let segments = AssistantActivityProjection.segments(blocks: [
                references([(skillID, "app-skill-use")], 0), paragraph("Answer", 1)
            ], embeds: [stale.id: stale])
            let state = runState(segments[0], in: segments)
            XCTAssertFalse(state.active, skillID)
            XCTAssertFalse(state.usingApps, skillID)
            var disclosure = AssistantActivityDisclosureState()
            disclosure.synchronize(active: true)
            disclosure.synchronize(active: state.active)
            XCTAssertFalse(disclosure.expanded, skillID)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.surface.semantic-parity
    func testNewActivityAfterProseReceivesRequestActivityAndReconnectCannotReviveEarlierRun() {
        let segments = AssistantActivityProjection.segments(blocks: [
            references([("earlier", "app-skill-use")], 0), paragraph("Answer", 1),
            references([("new", "app-skill-use")], 2)
        ], embeds: [:])
        for responseActive in [true, false, true] {
            XCTAssertFalse(runState(segments[0], in: segments, responseActive: responseActive).active)
            XCTAssertFalse(runState(segments[0], in: segments, responseActive: responseActive).usingApps)
            let latest = runState(segments[2], in: segments, responseActive: responseActive)
            XCTAssertEqual(latest.active, responseActive)
            XCTAssertEqual(latest.usingApps, responseActive)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.surface.semantic-parity
    func testTerminalSkillStaysSettledAcrossReconnect() {
        let terminal = activitySegment(items: [.init(id: "complete", kind: .skill, appID: "web", terminal: true)])
        for responseActive in [true, false, true] {
            let state = runState(terminal, in: [terminal], responseActive: responseActive)
            XCTAssertFalse(state.active)
            XCTAssertFalse(state.usingApps)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testEarlierLiveFocusBatchAndThinkingKeepGroupOpenWithoutUsingStaleSkill() {
        let prose = AssistantActivityProjection.segments(blocks: [paragraph("Answer", 1)], embeds: [:])[0]
        for kind in [AssistantActivityItem.Kind.focus, .subChats] {
            let segment = activitySegment(items: [
                .init(id: "stale", kind: .skill, appID: "web", terminal: false),
                .init(id: "live", kind: kind, appID: nil, terminal: false)
            ])
            let state = runState(segment, in: [segment, prose], openFocusIDs: ["live"], activeBatchIDs: ["live"])
            XCTAssertTrue(state.active)
            XCTAssertFalse(state.usingApps)
            var manual = AssistantActivityDisclosureState()
            manual.synchronize(active: true)
            manual.toggle()
            manual.synchronize(active: state.active)
            XCTAssertFalse(manual.expanded)
        }
        let thinking = activitySegment(items: [.init(id: "stale", kind: .skill, appID: "web", terminal: false)])
        let state = runState(thinking, in: [thinking, prose], thinkingStreaming: true)
        XCTAssertTrue(state.active)
        XCTAssertFalse(state.usingApps)
    }

    private func runState(_ segment: AssistantActivitySegment, in segments: [AssistantActivitySegment],
                          responseActive: Bool = true, thinkingStreaming: Bool = false,
                          openFocusIDs: Set<String> = [], activeBatchIDs: Set<String> = []) -> AssistantActivityRunState {
        .init(segment: segment, finalSegmentID: segments.last?.id, responseActive: responseActive,
            thinkingStreaming: thinkingStreaming, openFocusIDs: openFocusIDs, activeBatchIDs: activeBatchIDs)
    }

    private func activitySegment(items: [AssistantActivityItem]) -> AssistantActivitySegment {
        .init(id: "activity", units: [.init(id: "unit", block: paragraph("", 0), items: items)], isActivity: true)
    }

    private func paragraph(_ text: String, _ ordinal: Int) -> ProgressiveMarkdownBlock { block(.paragraph(text), ordinal) }
    private func references(_ values: [(String, String)], _ ordinal: Int) -> ProgressiveMarkdownBlock {
        block(.embedGroup(values.map { MarkdownEmbedReference(value: $0.0, isRef: false, isLargePreview: false, type: $0.1) }), ordinal)
    }
    private func block(_ markdown: MarkdownBlock, _ ordinal: Int) -> ProgressiveMarkdownBlock {
        .init(ordinal: ordinal, markdown: markdown, document: .init(messageId: "response", index: ordinal, markdownBlock: markdown, embedRefsById: [:]), sourceStartUTF8: 0, sourceEndUTF8: 0)
    }
}

@MainActor
final class AssistantActivityMessageFormatTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testEnglishAndGermanCardinalCandidatesContainNoICUSyntax() {
        let english = "Loaded ‘{memory}’ memory & used {count, plural, one {# app} other {# apps}}"
        let german = "Erinnerung ‘{memory}’ geladen & {count, plural, one {# App} other {# Apps}} verwendet"
        XCTAssertEqual(AssistantActivityMessageFormat.format(english, values: ["memory": "Research", "count": "1"], language: "en"), "Loaded ‘Research’ memory & used 1 app")
        XCTAssertEqual(AssistantActivityMessageFormat.format(german, values: ["memory": "Recherche", "count": "2"], language: "de"), "Erinnerung ‘Recherche’ geladen & 2 Apps verwendet")
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNestedBracesAndInsertedValuesAreNotReparsed() {
        let source = "{count, plural, one {{name}} other {# items: {name}}}"
        XCTAssertEqual(AssistantActivityMessageFormat.format(source, values: ["count": "2", "name": "{private, plural, other {x}}"], language: "en"), "2 items: {private, plural, other {x}}")
        XCTAssertEqual(AssistantActivityMessageFormat.format("Activated ''{focus}''; '{'literal'}'", values: ["focus": "Research"], language: "en"), "Activated 'Research'; {literal}")
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMalformedOrUnsupportedMessagesFailClosed() {
        for source in ["{count, plural, one {# app}}", "{count, plural, other {# apps}", "{missing}", "{count, select, other {x}}", "{count, plural, other {x} other {y}}", "unbalanced }", "'{unterminated"] {
            XCTAssertNil(AssistantActivityMessageFormat.format(source, values: ["count": "2"], language: "en"), source)
        }
        XCTAssertNil(AssistantActivityMessageFormat.format("{count, plural, other {x}}", values: ["count": "invalid"], language: "en"))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSummaryCandidatesRetainEveryActivityKindWhenNamesAreLong() {
        let state = AssistantActivitySummaryState(apps: ["Very long app", "Another long app"], memories: ["Long memory"], focuses: ["Long focus"], subChats: true)
        for language in ["en", "de"] {
            let result = AssistantActivitySummary.candidates(state) { key, values in
                let suffix = String(key.split(separator: ".").last!)
                switch suffix {
                case "join": return values["first"]! + " & " + values["last"]!
                case "memory_count", "app_count", "focus_count": return language + ":" + suffix + ":" + values["count"]!
                default: return language + ":" + suffix
                }
            }
            XCTAssertTrue(result.contains { $0.contains("memory_count:1") && $0.contains("app_count:2") && $0.contains("focus_count:1") && $0.contains("sub_chat_count") })
            XCTAssertEqual(result.last, language + ":activity_done")
        }
    }
}

@MainActor
final class AssistantActivityProtocolParsingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.rendering.assistant-document-convergence
    func testClosedValidatedActivityAnchorExistsDuringStreamingAndHistory() {
        for language in ["json", "json_embed"] {
            let content = "Before\n\n```\(language)\n{\"type\":\"app_skill_use\",\"embed_id\":\"skill\"}\n```\n\nAfter"
            let stream = MarkdownParser.parseSpans(content, isStreaming: true).map(\.block)
            XCTAssertTrue(stream.contains { if case .embedGroup(let references) = $0 { return references.first?.value == "skill" }; return false })
            XCTAssertEqual(stream, MarkdownParser.parse(content))
        }
    }
    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testPartialAndUnknownInternalProtocolNeverBecomeRawCode() {
        for content in ["```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"skill\"", "```json_embed\n{\"type\":\"unknown\",\"embed_id\":\"private\"}\n```"] {
            XCTAssertEqual(MarkdownParser.parseSpans(content, isStreaming: true).map(\.block), [.hiddenProtocol])
        }
    }
}

@MainActor
final class AssistantActivityFocusAcknowledgementTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testOnlyObservedLiveFocusGetsOneAcknowledgementAndHistoryNeverReplaysIt() {
        var state = AssistantActivityFocusAcknowledgement()
        XCTAssertEqual(state.observe(openIDs: [], confirmedIDs: ["historical"]), [])
        XCTAssertEqual(state.visibleIDs(openIDs: [], confirmedIDs: ["historical"]), [])
        XCTAssertEqual(state.observe(openIDs: ["live"], confirmedIDs: ["historical"]), [])
        XCTAssertEqual(state.visibleIDs(openIDs: [], confirmedIDs: ["historical", "live"]), ["live"], "The confirmation render transaction must not briefly collapse")
        XCTAssertEqual(state.observe(openIDs: [], confirmedIDs: ["historical", "live"]), ["live"])
        XCTAssertEqual(state.observe(openIDs: [], confirmedIDs: ["historical", "live"]), [])
        XCTAssertEqual(state.visibleIDs(openIDs: [], confirmedIDs: ["historical", "live"]), ["live"])
        state.expire("live")
        XCTAssertEqual(state.visibleIDs(openIDs: [], confirmedIDs: ["historical", "live"]), [])
        XCTAssertEqual(state.observe(openIDs: [], confirmedIDs: ["historical", "live"]), [])
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCancelledFocusDoesNotReceiveAnAcknowledgement() {
        var state = AssistantActivityFocusAcknowledgement()
        _ = state.observe(openIDs: ["live"], confirmedIDs: [])
        XCTAssertEqual(state.visibleIDs(openIDs: [], confirmedIDs: []), [])
        XCTAssertEqual(state.observe(openIDs: [], confirmedIDs: []), [])
    }
}
