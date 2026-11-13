// Tests of `CoreSendMapping` (Core/CoreBridge/CoreSendMapping.swift): composer
// embed nodes (finished, processing, reference without content, states the
// record cannot express), PII mappings and exclusions and the options builder
// map to the core's send records without approximation.
import Foundation
import XCTest
@testable import OpenMates

final class CoreSendMappingTests: XCTestCase {
    private static let display = ComposerEmbedDisplayV1(title: "Floor plan", mediaKind: "image")

    private func node(id: String = "composer:embed:0", type: String = "image", status: String = "finished",
                      ref: String? = "embed:embed-1", referenceOnly: Bool = false) -> ComposerNodeV1 {
        ComposerNodeV1(kind: "embed", id: id, embedType: type, status: status, contentRef: ref,
                       referenceOnly: referenceOnly, canonicalSource: "```json_embed\n{}\n```", display: Self.display)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testFinishedEmbedMapsWithItsCallerSuppliedContent() {
        let record = CoreSendMapping.embedRecord(
            from: node(), content: "{\"file\":\"plan.png\"}", textPreview: "Floor plan", childEmbedIds: ["child-1"])
        XCTAssertEqual(record, SendEmbedRecord(
            embedId: "embed-1", embedType: "image", referenceType: nil, status: "finished",
            content: "{\"file\":\"plan.png\"}", textPreview: "Floor plan", childEmbedIds: ["child-1"]))
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testProcessingEmbedAndRecordingTypeMapToTheBackendType() {
        let record = CoreSendMapping.embedRecord(from: node(type: "recording", status: "processing"))
        XCTAssertEqual(record?.status, "processing")
        XCTAssertEqual(record?.embedType, "audio-recording")
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testReferenceWithoutContentKeepsContentNil() {
        let record = CoreSendMapping.embedRecord(from: node(referenceOnly: true))
        XCTAssertEqual(record?.embedId, "embed-1")
        XCTAssertNil(record?.content)
        XCTAssertNil(record?.textPreview)
        XCTAssertNil(record?.childEmbedIds)
        XCTAssertNil(record?.referenceType)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testNodesTheRecordCannotExpressAreReportedNotApproximated() {
        let document = ComposerDocumentV1(version: 1, nodes: [
            .text(id: "composer:text:0", source: "Hello"),
            node(id: "composer:embed:0"),
            node(id: "composer:embed:1", status: "uploading"),
            node(id: "composer:embed:2", ref: nil),
            node(id: "composer:embed:3", ref: "embed:"),
            node(id: "composer:embed:4", status: "error"),
        ])
        let mapping = CoreSendMapping.embedRecords(from: document)
        XCTAssertEqual(mapping.records.map(\.embedId), ["embed-1"])
        XCTAssertEqual(mapping.unmapped, ["composer:embed:1", "composer:embed:2", "composer:embed:3", "composer:embed:4"])
        XCTAssertNil(CoreSendMapping.embedRecord(from: .text(id: "composer:text:0", source: "Hello")))
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testPiiMappingsAndExclusionsMapIntoTheOptions() {
        let embed = SendEmbedRecord(embedId: "embed-1", embedType: "image", referenceType: nil, status: "finished",
                                    content: nil, textPreview: nil, childEmbedIds: nil)
        let options = CoreSendMapping.options(
            piiDetection: false, incognito: true, slug: "kitchen", reservedChatId: "chat-1",
            reservedMessageId: "message-1", embeds: [embed],
            excludedPiiOriginals: ["Ada", "Bob"], excludedPiiPlaceholders: ["[NAME_2]", "[NAME_1]"],
            piiMappings: [PIIMapping(placeholder: "[EMAIL_1]", original: "ada@example.org", type: "EMAIL")],
            projectId: "project-1")
        XCTAssertEqual(options, SendOptionsRecord(
            piiDetection: false, incognito: true, slug: "kitchen", reservedChatId: "chat-1",
            reservedMessageId: "message-1", embeds: [embed], excludedPiiOriginals: ["Ada", "Bob"],
            excludedPiiPlaceholders: ["[NAME_1]", "[NAME_2]"],
            piiMappings: [PiiMappingRecord(placeholder: "[EMAIL_1]", original: "ada@example.org", kind: "EMAIL")],
            projectId: "project-1", projectCreateRequests: true, machineProject: .unavailable))
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testDefaultOptionsDetectPiiAndCarryNothingElse() {
        let options = CoreSendMapping.options()
        XCTAssertTrue(options.piiDetection)
        XCTAssertFalse(options.incognito)
        XCTAssertNil(options.slug)
        XCTAssertNil(options.reservedChatId)
        XCTAssertNil(options.reservedMessageId)
        XCTAssertNil(options.projectId)
        XCTAssertTrue(options.embeds.isEmpty)
        XCTAssertTrue(options.excludedPiiOriginals.isEmpty)
        XCTAssertTrue(options.excludedPiiPlaceholders.isEmpty)
        XCTAssertTrue(options.piiMappings.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testComposerPendingEmbedMapsLikeNodesAndRejectsUnsendableStatus() {
        func pending(type: String, status: String) -> ComposerPendingEmbed {
            let record = EmbedRecord(id: "embed-1", type: type, status: .finished, data: nil,
                parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil,
                hashedChatId: nil, createdAt: nil)
            return ComposerPendingEmbed(id: "embed-1", type: type, referenceType: "", status: status,
                content: "body", textPreview: "preview", record: record, localData: nil,
                filename: "a", size: 0, piiMappings: [])
        }
        let recording = CoreSendMapping.embedRecord(from: pending(type: "recording", status: "finished"))
        XCTAssertEqual(recording?.embedType, "audio-recording")
        XCTAssertEqual(recording?.embedId, "embed-1")
        XCTAssertEqual(recording?.content, "body")
        XCTAssertNil(recording?.referenceType)
        XCTAssertNotNil(CoreSendMapping.embedRecord(from: pending(type: "image", status: "processing")))
        XCTAssertNil(CoreSendMapping.embedRecord(from: pending(type: "image", status: "error")))
    }
}
