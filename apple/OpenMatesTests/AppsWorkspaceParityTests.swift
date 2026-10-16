// Web source: components/apps/appsSkillFormUtils.ts, services/appsWorkspaceResultsService.ts
import CryptoKit
import Combine
import SwiftUI
import XCTest
@testable import OpenMates

@MainActor
final class AppsWorkspaceParityTests: XCTestCase {
    private let rootID = "00000000-0000-4000-8000-000000000100"

    // contract-test: supporting surface=gui.apple assertions=apps.forms.metadata-driven
    func testPrimaryProjectionKeepsTransportEnvelopeAndUnshownDefaults() throws {
        let details = AppsWorkspacePreviewFixture.details
        let schema = try XCTUnwrap(AppsSkillInput.select(details.inputSchema.mapValues(\.value), paths: details.primaryFields))
        let input = details.defaults.mapValues(\.value)
        let projection = try XCTUnwrap(WorkflowRequestInputProjection(schema: schema, input: input))
        var request = try XCTUnwrap(projection.requests.first as? [String: Any]); request["query"] = "Berlin"
        let changed = projection.replacingRequest(at: 0, with: request)
        XCTAssertEqual(AppsSkillInput.value(changed, path: "requests[].query") as? String, "Berlin")
        XCTAssertEqual(AppsSkillInput.value(changed, path: "requests[].count") as? Int, 6)
        XCTAssertNil(changed["query"])
        XCTAssertFalse((projection.requestSchema["properties"] as? [String: Any])?.keys.contains("count") ?? true)
        XCTAssertTrue(AppsSkillInput.validation(details.inputSchema.mapValues(\.value), input: changed).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apps.forms.metadata-driven,apps.execution.direct-shared-contract
    func testRequiredInvalidFieldsAreRejectedWithoutFabrication() {
        let schema = AppsWorkspacePreviewFixture.schema
        XCTAssertEqual(AppsSkillInput.validation(schema, input: ["requests": [["query": "", "count": 6]]]), ["requests[0].query"])
        XCTAssertEqual(AppsSkillInput.validation(schema, input: ["requests": [["query": "Berlin", "count": 21]]]), ["requests[0].count"])
        XCTAssertEqual(AppsSkillInput.validation(schema, input: ["requests": [["query": "Berlin", "count": true]]]), ["requests[0].count"])
        let original: [String: Any] = ["requests": [["count": 6]]]
        let prepared = AppsSkillInput.prepare(schema, input: original)
        XCTAssertNil(AppsSkillInput.value(prepared, path: "requests[].query"))
        XCTAssertFalse(AppsSkillInput.validation(schema, input: prepared).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apps.forms.metadata-driven,apps.execution.direct-shared-contract
    func testNumericRequestBoundsWorkForNativeAndJSONMetadataWithoutChangingInput() throws {
        let integerSchemas: [[String: Any]] = [
            ["type": "integer", "minimum": 1, "maximum": 20],
            ["type": "integer", "minimum": 1.0, "maximum": 20.0],
            try XCTUnwrap(JSONSerialization.jsonObject(with: Data(#"{"type":"integer","minimum":1,"maximum":20}"#.utf8)) as? [String: Any])
        ]
        for countSchema in integerSchemas {
            let schema: [String: Any] = ["type": "object", "required": ["requests"], "properties": [
                "requests": ["type": "array", "minItems": 1, "items": ["type": "object", "properties": ["count": countSchema]]]
            ]]
            for valid in [1, 6, 20] {
                XCTAssertTrue(AppsSkillInput.validation(schema, input: ["requests": [["count": valid]]]).isEmpty)
            }
            for invalid: Any in [0, 21, 1.5, true, Double.nan, Double.infinity] {
                XCTAssertEqual(AppsSkillInput.validation(schema, input: ["requests": [["count": invalid]]]), ["requests[0].count"])
            }
            let original: [String: Any] = ["requests": [["count": 21]]]
            let prepared = AppsSkillInput.prepare(schema, input: original)
            XCTAssertEqual(AppsSkillInput.value(prepared, path: "requests[].count") as? Int, 21,
                "Validation must report supplied values rather than clamp or fabricate them")
            XCTAssertEqual(AppsSkillInput.validation(schema, input: prepared), ["requests[0].count"])
            XCTAssertTrue(AppsSkillInput.validation(schema, input: ["requests": [[:]]]).isEmpty,
                "A missing optional count stays optional")
        }
        let numberSchema: [String: Any] = ["type": "number", "minimum": 0.5, "maximum": 2.5]
        for valid in [0.5, 1.25, 2.5] { XCTAssertTrue(AppsSkillInput.validation(numberSchema, input: valid).isEmpty) }
        for invalid in [0.25, 2.75] { XCTAssertEqual(AppsSkillInput.validation(numberSchema, input: invalid), [""]) }
    }

    // contract-test: supporting surface=gui.apple assertions=apps.results.web-retained-graph
    func testResultGraphEncryptsRequestAndChildrenAndKeepsStableIDsForSaveRetry() throws {
        let key = SymmetricKey(size: .bits256), master = SymmetricKey(size: .bits256)
        let wrapper = try ComposerEmbedCrypto.wrapKey(key, using: master)
        let input: [String: Any] = ["requests": [["query": "private-query-marker", "count": 6]]]
        let graph = try AppsResultGraph.make(rootID: rootID, appID: "web", skillID: "search", input: input,
            response: AppsWorkspacePreviewFixture.response, accountID: "fixture-owner", teamID: nil, key: key, wrapper: wrapper)
        let wire = String(decoding: try JSONEncoder().encode(graph), as: UTF8.self)
        XCTAssertFalse(wire.contains("private-query-marker")); XCTAssertFalse(wire.contains("Useful tools"))
        XCTAssertEqual(graph.embeds.count, 2)
        XCTAssertEqual(graph.embeds[0].embedIDs, [AppsResultGraph.childID(rootID: rootID, index: 0)])
        XCTAssertEqual(graph.embeds[1].parentEmbedID, rootID)
        let reopenedKey = try ComposerEmbedCrypto.unwrapKey(wrapper, using: master)
        let records = try AppsResultGraph.records(rows: graph.embeds, key: reopenedKey, appID: "web", skillID: "search")
        XCTAssertEqual(records[0].rawData?["query"]?.value as? String, "private-query-marker")
        XCTAssertEqual(records[1].rawData?["title"]?.value as? String, "OpenMates")
        XCTAssertThrowsError(try ComposerEmbedCrypto.unwrapKey(wrapper, using: SymmetricKey(size: .bits256)))
        let second = try AppsResultGraph.make(rootID: rootID, appID: "web", skillID: "search", input: input,
            response: AppsWorkspacePreviewFixture.response, accountID: "fixture-owner", teamID: nil, key: key, wrapper: wrapper)
        XCTAssertEqual(second.embeds.map(\.embedID), graph.embeds.map(\.embedID))
        XCTAssertEqual(second.encryptedEmbedKey, graph.encryptedEmbedKey)
    }

    // contract-test: supporting surface=gui.apple assertions=apps.results.web-retained-graph,apps.execution.direct-shared-contract
    func testGeneratedResultReusesExistingAssetIDAndAcceptedTasksRemainOnEncryptedParent() throws {
        let asset = "00000000-0000-4000-8000-000000000200", key = SymmetricKey(size: .bits256)
        let graph = try AppsResultGraph.make(rootID: rootID, appID: "images", skillID: "generate", input: [:],
            response: ["data": ["embed_id": asset, "type": "image", "prompt": "fixture"]], accountID: "owner", teamID: nil, key: key, wrapper: "fixture")
        XCTAssertEqual(graph.embeds.map(\.embedID), [rootID, asset])
        XCTAssertEqual(graph.embeds[0].embedIDs, [asset])
        let processing = try AppsResultGraph.make(rootID: rootID, appID: "images", skillID: "generate", input: [:],
            response: ["status": "processing", "task_ids": ["fixture-task"]], accountID: "owner", teamID: nil, key: key, wrapper: "fixture")
        let record = try XCTUnwrap(AppsResultGraph.records(rows: processing.embeds, key: key, appID: "images", skillID: "generate").first)
        XCTAssertEqual(record.status, .processing)
        XCTAssertEqual(AppsResultGraph.taskIDs(record.rawData?.mapValues(\.value) ?? [:]), ["fixture-task"])
    }

    // contract-test: supporting surface=gui.apple assertions=apps.anonymous.local-results-and-promotion
    func testGuestPromotionRewrapsWithoutChangingCiphertextAndBindsFirstAccount() throws {
        let key = SymmetricKey(size: .bits256), guestSessionKey = SymmetricKey(size: .bits256), master = SymmetricKey(size: .bits256)
        let guest = try AppsResultGraph.make(rootID: rootID, appID: "web", skillID: "search", input: [:],
            response: AppsWorkspacePreviewFixture.response, accountID: "", teamID: nil, key: key,
            wrapper: ComposerEmbedCrypto.wrapKey(key, using: guestSessionKey))
        let promoted = try AppsResultGraph.promoting(guest, accountID: "first-owner", key: key, masterKey: master)
        XCTAssertEqual(promoted.rootEmbedID, guest.rootEmbedID)
        XCTAssertEqual(promoted.embeds.map(\.encryptedContent), guest.embeds.map(\.encryptedContent))
        XCTAssertNotEqual(promoted.encryptedEmbedKey, guest.encryptedEmbedKey)
        XCTAssertEqual(promoted.expectedUserID, "first-owner")
        XCTAssertNoThrow(try ComposerEmbedCrypto.unwrapKey(promoted.encryptedEmbedKey, using: master))
        let retry = try AppsResultGraph.promoting(promoted, accountID: "first-owner", key: key, masterKey: master)
        XCTAssertEqual(retry.encryptedEmbedKey, promoted.encryptedEmbedKey)
        XCTAssertThrowsError(try AppsResultGraph.promoting(promoted, accountID: "second-owner", key: key, masterKey: master))
        let receipt = AppsGuestReceipt(graph: guest, createdAt: 1, server: "https://one.example", anonymousID: "guest-one")
        XCTAssertTrue(receipt.matches(server: "https://one.example", anonymousID: "guest-one"))
        XCTAssertFalse(receipt.matches(server: "https://two.example", anonymousID: "guest-one"))
        XCTAssertFalse(receipt.matches(server: "https://one.example", anonymousID: "guest-two"))
    }

    // contract-test: supporting surface=gui.apple assertions=apps.execution.direct-shared-contract,apps.discovery.public-catalog
    func testCatalogAndSkillSelectionNeverRunUntilExplicitSubmitAndDuplicateTapIsCoalesced() async throws {
        let store = AppsWorkspaceStore(); store.installPreviewFixture()
        store.openRoute("apps/web/search")
        XCTAssertNil(store.inlineResult); XCTAssertEqual(store.previewDispatchCount, 0)
        store.updateInput(["requests": [["query": "Berlin", "count": 6]]])
        let completed = expectation(description: "explicit result")
        let subscription = store.$inlineResult.compactMap { $0 }.sink { _ in completed.fulfill() }
        store.submit(); store.submit()
        XCTAssertEqual(store.previewDispatchCount, 1)
        await fulfillment(of: [completed], timeout: 3)
        XCTAssertNotNil(store.inlineResult)
        subscription.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=apps.forms.metadata-driven
    func testFormShowsProviderModelAndActualCreditRatesWithoutInventedQuote() {
        let sample = AppsWorkspacePreviewFixture.details
        let details = AppsSkillDetails(appID: sample.appID, skillID: sample.skillID, slug: sample.slug,
            name: sample.name, description: sample.description, inputSchema: sample.inputSchema,
            primaryFields: sample.primaryFields, defaults: sample.defaults,
            pricing: ["fixed": AnyCodable(2), "per_second": AnyCodable(3), "per_minute": AnyCodable(true),
                "per_unit": AnyCodable(["credits": 4, "unit_name": "image"]),
                "tokens": AnyCodable(["input": ["per_credit_unit": 500]])],
            providers: [["name": AnyCodable("Brave")], ["name": AnyCodable("Brave")]],
            models: [["name": AnyCodable("Model A"), "pricing": AnyCodable(["fixed": 7])]],
            anonymousAllowed: true, executionAvailable: true, unavailableReason: nil, executionMode: "sync")
        let labels = AppsWorkspaceStore.executionLabels(details)
        XCTAssertEqual(labels.count, 7)
        XCTAssertEqual(labels.filter { $0.contains("Brave") }.count, 1)
        XCTAssertTrue(labels.contains { $0.contains("500") })
        XCTAssertTrue(labels.contains { $0.contains("image") && $0.contains("4") })
        XCTAssertTrue(labels.contains { $0.contains("Model A") && $0.contains("7") })
    }

    // contract-test: supporting surface=gui.apple assertions=apps.presentation.shared-detail-and-recency
    func testCatalogHeaderOverridesIdentityAndOrdinaryHeaderKeepsItsDefault() {
        let embed = EmbedRecord(id: rootID, type: "app:web:search", status: .finished, data: .raw(["query": AnyCodable("Berlin")]),
            parentEmbedId: nil, appId: "web", skillId: "search", embedIds: nil, createdAt: nil)
        let original = EmbedFullscreenHeader(embed: embed)
        let override = EmbedFullscreenHeader(embed: embed, presentation: EmbedFullscreenHeaderPresentation(title: "Catalog Search",
            subtitle: "Metadata description", icon: "search", eyebrow: "Web skill", providers: "Brave", footer: nil))
        XCTAssertNotEqual(original.headerTitle, "Catalog Search")
        XCTAssertEqual(original.skillIconName, EmbedVisualSkillIcon.name(for: embed, fullscreen: true))
        XCTAssertEqual(override.headerTitle, "Catalog Search"); XCTAssertEqual(override.headerSubtitle, "Metadata description")
        XCTAssertEqual(override.skillIconName, "search")
        XCTAssertEqual(AppsWorkspacePaths.page(appID: "web", offset: 20, teamID: "team id"), "/v1/apps/workspace/results?app_id=web&offset=20&limit=20&team_id=team%20id")
    }
}
