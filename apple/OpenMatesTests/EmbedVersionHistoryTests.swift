// Synthetic encrypted bounded-history proof. No inference, account data or mutations.
import XCTest
import CryptoKit
@testable import OpenMates

@MainActor final class EmbedVersionHistoryTests: XCTestCase {
    private let embedID = "synthetic-artifact"
    private let key = SymmetricKey(data: Data(repeating: 31, count: 32))
    private func encrypted(_ text: String) throws -> String { try ComposerEmbedCrypto.encryptContent(text, using: key) }
    private func json(_ value: [String: Any]) throws -> Data { try JSONSerialization.data(withJSONObject: value) }
    private func metadata(_ numbers: [Int], current: Int = 1000, cursor: Int? = nil) throws -> Data {
        try json(["embed_id": embedID, "current_version": current, "readonly": true,
            "next_cursor": cursor.map { $0 as Any } ?? NSNull(),
            "versions": numbers.map { ["version_number": $0, "created_at": NSNull(), "has_snapshot": $0 % 32 == 0, "has_patch": true] as [String: Any] }])
    }
    private func content(_ number: Int, rows: [[String: Any]], bounded: Bool = true, id: String? = nil, current: Int = 1000) throws -> Data {
        try json(["embed_id": id ?? embedID, "version_number": number, "current_version": current,
                  "readonly": true, "bounded": bounded, "rows": rows])
    }
    private func snapshot(_ number: Int, _ text: String) throws -> [String: Any] {
        ["version_number": number, "encrypted_snapshot": try encrypted(text)]
    }
    private func patch(_ old: Int, _ next: Int) throws -> [String: Any] {
        ["version_number": next, "encrypted_patch": try encrypted("@@ -1 +1 @@\n-v\(old)\n+v\(next)\n")]
    }
    private func session(fetch: @escaping (String) async throws -> Data,
        validate: @escaping () async throws -> Void = {}) -> EmbedVersionHistorySession {
        EmbedVersionHistorySession(fetch: fetch, decrypt: { [key] in try ComposerEmbedCrypto.decryptContent($0, using: key) },
            validate: validate, context: EmbedVersionReadContext(chatID: "synthetic-chat"))
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.metadata-and-payload
    func testMetadataOpensOnePageAndShowMoreUsesExclusiveCursorWithoutCiphertext() async throws {
        var paths: [String] = []
        let first = try metadata(Array((969...1000).reversed()), cursor: 969)
        let second = try metadata(Array((937...968).reversed()), cursor: 937)
        let reader = EmbedVersionHistoryController()
        await reader.open(embedID: embedID, currentVersion: 1000, session: session { path in
            paths.append(path); return paths.count == 1 ? first : second
        })
        XCTAssertEqual(paths.count, 1); XCTAssertEqual(reader.versions.count, 32)
        XCTAssertTrue(paths[0].contains("limit=32")); XCTAssertTrue(paths[0].contains("order=desc"))
        XCTAssertFalse(paths[0].contains("capability")); XCTAssertNil(reader.content)
        await reader.loadMore()
        XCTAssertEqual(paths.count, 2); XCTAssertTrue(paths[1].contains("cursor=969"))
        XCTAssertEqual(reader.versions.map(\.versionNumber), Array((937...1000).reversed()))
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.metadata-and-payload,storage.versions.bounded-reconstruction
    func testNewMetadataHeadFetchesVerifiedContentInsteadOfRelabelingCachedPayload() async throws {
        let page = try metadata([101, 100], current: 101)
        let latest = try content(101, rows: [snapshot(101, "verified v101")], current: 101)
        var paths: [String] = []
        var suspended: CheckedContinuation<Data, Never>?
        let waiting = expectation(description: "new head content fetch is waiting")
        let reader = EmbedVersionHistoryController()
        let opening = Task {
            await reader.open(embedID: embedID, currentVersion: 100, session: session { path in
                paths.append(path)
                if path.contains("/versions/101?") {
                    return await withCheckedContinuation { suspended = $0; waiting.fulfill() }
                }
                if path.contains("/versions/100?") { return latest }
                return page
            })
        }
        await fulfillment(of: [waiting], timeout: 2)
        XCTAssertEqual(reader.payloadVersion, 100)
        XCTAssertEqual(reader.currentVersion, 101); XCTAssertEqual(reader.selectedVersion, 101)
        XCTAssertFalse(reader.isHistorical); XCTAssertTrue(reader.requiresVersionContent)
        XCTAssertTrue(reader.loadingContent); XCTAssertNil(reader.content)
        suspended?.resume(returning: latest); await opening.value
        XCTAssertEqual(reader.content, "verified v101"); XCTAssertNil(reader.failure)
        XCTAssertTrue(reader.requiresVersionContent)
        XCTAssertEqual(paths.count, 2)
        XCTAssertTrue(paths[1].contains("capability=bounded-v1"))
        await reader.select(100)
        XCTAssertTrue(reader.isHistorical); XCTAssertTrue(reader.requiresVersionContent)
        XCTAssertNil(reader.content) // The mismatched response cannot become version 100.
        XCTAssertEqual(reader.failure, .invalidResponse)
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.metadata-and-payload,storage.versions.bounded-reconstruction
    func testUnavailableNewHeadNeverFallsBackToOldPayloadAndRetryFetchesExactVersion() async throws {
        let page = try metadata([101, 100], current: 101)
        let latest = try content(101, rows: [snapshot(101, "verified")], current: 101)
        var ready = false; var contentReads = 0
        let reader = EmbedVersionHistoryController()
        await reader.open(embedID: embedID, currentVersion: 100, session: session { path in
            guard path.contains("/versions/101?") else { return page }
            contentReads += 1
            if !ready { throw APIError.httpError(status: 409, message: "snapshot_required") }
            return latest
        })
        XCTAssertEqual(reader.failure, .snapshotRequired); XCTAssertNil(reader.content)
        XCTAssertTrue(reader.requiresVersionContent); XCTAssertEqual(reader.payloadVersion, 100)
        ready = true; await reader.retry()
        XCTAssertEqual(reader.content, "verified"); XCTAssertNil(reader.failure)
        XCTAssertEqual(contentReads, 2); XCTAssertTrue(reader.requiresVersionContent)
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.metadata-and-payload,storage.versions.bounded-reconstruction
    func testHeadMismatchRequiresFreshMetadataBeforePublishingSelectedPayload() async throws {
        for racedHead in [100, 102] {
            let first = try metadata([101, 100], current: 101)
            let fresh = try metadata([102, 101, 100], current: 102)
            let mismatch = try content(101, rows: [snapshot(101, "must remain hidden")], current: racedHead)
            let latest = try content(102, rows: [snapshot(102, "fresh head")], current: 102)
            var indexReads = 0; var decryptions = 0
            let reader = EmbedVersionHistoryController()
            let scoped = EmbedVersionHistorySession(fetch: { path in
                if path.contains("/versions/101?") { return mismatch }
                if path.contains("/versions/102?") { return latest }
                indexReads += 1; return indexReads == 1 ? first : fresh
            }, decrypt: { [key] ciphertext in
                decryptions += 1
                return try ComposerEmbedCrypto.decryptContent(ciphertext, using: key)
            }, validate: {}, context: EmbedVersionReadContext(chatID: "synthetic-chat"))
            await reader.open(embedID: embedID, currentVersion: 100, session: scoped)
            XCTAssertEqual(reader.failure, .invalidResponse); XCTAssertNil(reader.content)
            XCTAssertTrue(reader.versions.isEmpty); XCTAssertNil(reader.nextCursor)
            XCTAssertTrue(reader.requiresVersionContent); XCTAssertEqual(decryptions, 0)
            await reader.retry()
            XCTAssertEqual(indexReads, 2); XCTAssertEqual(decryptions, 1)
            XCTAssertEqual(reader.currentVersion, 102); XCTAssertEqual(reader.selectedVersion, 102)
            XCTAssertEqual(reader.payloadVersion, 100); XCTAssertEqual(reader.content, "fresh head")
        }
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction,storage.cold.shared-team-authorized
    func testScopeChangeWhileFetchingNewHeadKeepsCachedAndFetchedContentHidden() async throws {
        var valid = true
        let page = try metadata([101, 100], current: 101)
        let latest = try content(101, rows: [snapshot(101, "private head")], current: 101)
        let reader = EmbedVersionHistoryController()
        await reader.open(embedID: embedID, currentVersion: 100, session: session(fetch: { path in
            if path.contains("/versions/101?") { valid = false; return latest }
            return page
        }, validate: { if !valid { throw CancellationError() } }))
        XCTAssertEqual(reader.failure, .accessChanged); XCTAssertNil(reader.content)
        XCTAssertTrue(reader.versions.isEmpty); XCTAssertTrue(reader.requiresVersionContent)
        reader.reset()
        XCTAssertEqual(reader.payloadVersion, 1); XCTAssertFalse(reader.requiresVersionContent)
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.metadata-and-payload
    func testMetadataRejectsPayloadsDuplicatesAndRegressingCursors() throws {
        let data = try json(["embed_id": embedID, "current_version": 1000, "readonly": false,
            "versions": [["version_number": 1000, "created_at": 0, "has_snapshot": true, "has_patch": false,
                          "encrypted_snapshot": "forbidden-on-index"]]])
        XCTAssertThrowsError(try EmbedVersionHistoryController.decodePage(data, embedID: embedID, cursor: nil))
        XCTAssertThrowsError(try EmbedVersionHistoryController.decodePage(metadata([999, 999]), embedID: embedID, cursor: nil))
        XCTAssertThrowsError(try EmbedVersionHistoryController.decodePage(metadata([969], cursor: 999), embedID: embedID, cursor: 970))
        XCTAssertThrowsError(try EmbedVersionHistoryController.decodePage(metadata(Array((968...1000).reversed())), embedID: embedID, cursor: nil))
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction,storage.privacy.ciphertext-boundary
    func testVersion101UsesNearbyAuthenticatedSnapshotAndFivePatches() async throws {
        var rows = [try snapshot(96, "v96")]
        for number in 97...101 { rows.append(try patch(number - 1, number)) }
        let response = try JSONDecoder().decode(EmbedVersionContent.self, from: content(101, rows: rows))
        var decryptions = 0
        let text = try await EmbedVersionReconstruction.reconstruct(response, embedID: embedID, version: 101,
            decrypt: { [key] ciphertext in decryptions += 1; return try ComposerEmbedCrypto.decryptContent(ciphertext, using: key) }, validate: {})
        XCTAssertEqual(text, "v101"); XCTAssertEqual(decryptions, 6)
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction
    func testReconstructionAccepts32PatchesAndRejectsReplayBeyondBoundBeforeDecrypting() async throws {
        var rows = [try snapshot(96, "v96")]
        for number in 97...128 { rows.append(try patch(number - 1, number)) }
        let bounded = try JSONDecoder().decode(EmbedVersionContent.self, from: content(128, rows: rows))
        let text = try await EmbedVersionReconstruction.reconstruct(bounded, embedID: embedID, version: 128,
            decrypt: { [key] in try ComposerEmbedCrypto.decryptContent($0, using: key) }, validate: {})
        XCTAssertEqual(text, "v128")
        rows.append(try patch(128, 129))
        let tooLong = try JSONDecoder().decode(EmbedVersionContent.self, from: content(129, rows: rows))
        var decryptions = 0
        do {
            _ = try await EmbedVersionReconstruction.reconstruct(tooLong, embedID: embedID, version: 129,
                decrypt: { _ in decryptions += 1; return "unexpected" }, validate: {})
            XCTFail("An unbounded chain must remain unread")
        } catch { XCTAssertEqual(error as? EmbedVersionHistoryFailure, .invalidResponse) }
        XCTAssertEqual(decryptions, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction
    func testSnapshotRequiredRemainsVisibleAndRetryNeverFallsBackToLegacyOrPublishes() async throws {
        var paths: [String] = []; var snapshotsReady = false
        let page = try metadata([101, 100], current: 101)
        let selected = try content(100, rows: [snapshot(100, "historical")], current: 101)
        let reader = EmbedVersionHistoryController()
        await reader.open(embedID: embedID, currentVersion: 101, session: session { path in
            paths.append(path)
            if !path.contains("/versions/100?") { return page }
            if !snapshotsReady { throw APIError.httpError(status: 409, message: "snapshot_required") }
            return selected
        })
        await reader.select(100)
        XCTAssertEqual(reader.failure, .snapshotRequired); XCTAssertNil(reader.content)
        XCTAssertTrue(reader.isHistorical); XCTAssertEqual(paths.count, 2)
        snapshotsReady = true; await reader.retry()
        XCTAssertEqual(reader.content, "historical"); XCTAssertNil(reader.failure)
        XCTAssertEqual(paths.count, 3)
        XCTAssertTrue(paths.dropFirst().allSatisfy { $0.contains("capability=bounded-v1") && !$0.contains("/snapshot") })
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction,storage.cold.shared-team-authorized
    func testScopeChangeAfterFetchClearsHistoricalContentAndMetadata() async throws {
        var valid = true
        let page = try metadata([101, 100], current: 101)
        let selected = try content(100, rows: [snapshot(100, "must stay private")], current: 101)
        let reader = EmbedVersionHistoryController()
        await reader.open(embedID: embedID, currentVersion: 101, session: session(fetch: { path in
            if path.contains("/versions/100?") { valid = false; return selected }; return page
        }, validate: { if !valid { throw CancellationError() } }))
        await reader.select(100)
        XCTAssertEqual(reader.failure, .accessChanged); XCTAssertNil(reader.content)
        XCTAssertTrue(reader.versions.isEmpty); XCTAssertNil(reader.nextCursor)
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction,storage.cold.shared-team-authorized
    func testAccountOrTeamChangeDuringDecryptAndRevokedFetchKeepPlaintextHidden() async throws {
        let page = try metadata([101, 100], current: 101)
        let selected = try content(100, rows: [snapshot(100, "private history")], current: 101)
        for boundary in ["account", "team", "revoked"] {
            var valid = true
            let reader = EmbedVersionHistoryController()
            let scoped = EmbedVersionHistorySession(fetch: { path in
                if path.contains("/versions/100?") {
                    if boundary == "revoked" { throw APIError.httpError(status: 404, message: "Embed not found") }
                    return selected
                }
                return page
            }, decrypt: { [key] ciphertext in
                let plaintext = try ComposerEmbedCrypto.decryptContent(ciphertext, using: key)
                valid = false
                return plaintext
            }, validate: { if !valid { throw CancellationError() } }, context: EmbedVersionReadContext(chatID: "synthetic-chat", teamID: "synthetic-team"))
            await reader.open(embedID: embedID, currentVersion: 101, session: scoped)
            await reader.select(100)
            XCTAssertEqual(reader.failure, .accessChanged, boundary)
            XCTAssertNil(reader.content, boundary); XCTAssertTrue(reader.versions.isEmpty, boundary)
        }
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction
    func testLateOldSelectionCannotReplaceCurrentOrNewerSelectedContent() async throws {
        let page = try metadata([103, 102, 101], current: 103)
        let old = try content(101, rows: [snapshot(101, "old")], current: 103)
        let newer = try content(102, rows: [snapshot(102, "newer")], current: 103)
        var suspended: CheckedContinuation<Data, Never>?
        let waiting = expectation(description: "old selection fetch is waiting")
        let reader = EmbedVersionHistoryController()
        await reader.open(embedID: embedID, currentVersion: 103, session: session { path in
            if path.contains("/versions/101?") {
                return await withCheckedContinuation { suspended = $0; waiting.fulfill() }
            }
            return path.contains("/versions/102?") ? newer : page
        })
        let first = Task { await reader.select(101) }
        await fulfillment(of: [waiting], timeout: 2)
        await reader.select(102)
        suspended?.resume(returning: old); await first.value
        XCTAssertEqual(reader.selectedVersion, 102); XCTAssertEqual(reader.content, "newer")
        await reader.select(103)
        XCTAssertFalse(reader.isHistorical); XCTAssertNil(reader.content)
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction
    func testGapWrongIdentityUnboundedResponseAndCorruptCiphertextNeverRender() async throws {
        let fixtures = [
            try content(101, rows: [snapshot(99, "v99"), patch(100, 101)]),
            try content(101, rows: [snapshot(101, "v101")], id: "wrong-artifact"),
            try content(101, rows: [snapshot(101, "v101")], bounded: false),
            try content(101, rows: [["version_number": 101, "encrypted_snapshot": "corrupt"]]),
        ]
        for data in fixtures {
            let response = try JSONDecoder().decode(EmbedVersionContent.self, from: data)
            do {
                _ = try await EmbedVersionReconstruction.reconstruct(response, embedID: embedID, version: 101,
                    decrypt: { [key] in try ComposerEmbedCrypto.decryptContent($0, using: key) }, validate: {})
                XCTFail("Invalid source must remain pending")
            } catch { /* All failures remain unavailable to the UI. */ }
        }
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.bounded-reconstruction
    func testPatchMatchesLegacyLFShapeAndExactNoNewlineMarkerWithoutFuzzyContext() throws {
        XCTAssertEqual(try EmbedVersionPatch.apply("@@ -1 +1 @@\n-old\n+new\n", to: "old"), "new")
        XCTAssertEqual(try EmbedVersionPatch.apply("@@ -1,2 +1,2 @@\n-old\n+new\n \n", to: "old\n"), "new\n")
        let marker = "--- a/v100\n+++ b/v101\n@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"
        XCTAssertEqual(try EmbedVersionPatch.apply(marker, to: "old"), "new")
        XCTAssertThrowsError(try EmbedVersionPatch.apply("@@ -1 +1 @@\n-different\n+new\n", to: "old"))
        XCTAssertThrowsError(try EmbedVersionPatch.apply("@@ -1,2 +1 @@\n-old\n+new\n", to: "old"))
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.metadata-and-payload,storage.cold.shared-team-authorized
    func testReadScopeKeepsTeamAndProjectOrChatIdentityAndNeverUsesMutationEndpoints() throws {
        let scope = EmbedVersionReadContext(projectID: "project/?", teamID: "team/?")
        let path = try scope.path(embedID: "embed/with?separator", version: 101)
        XCTAssertTrue(path.contains("embed%2Fwith%3Fseparator/versions/101?"))
        let query = try XCTUnwrap(URLComponents(string: "https://example.invalid" + path)?.queryItems)
        XCTAssertEqual(query.first { $0.name == "project_id" }?.value, "project/?")
        XCTAssertEqual(query.first { $0.name == "team_id" }?.value, "team/?")
        XCTAssertTrue(path.contains("capability=bounded-v1")); XCTAssertFalse(path.contains("/restore"))
        XCTAssertThrowsError(try EmbedVersionReadContext(chatID: "chat", projectID: "project").path(embedID: embedID))
        XCTAssertThrowsError(try EmbedVersionReadContext(teamID: "team").path(embedID: embedID))
    }
    // contract-test: supporting surface=gui.apple assertions=storage.versions.metadata-and-payload
    func testWatchMapperPreservesRealVersionIdentityForBoundedHistory() {
        let record = EmbedRecord(id: embedID, type: "code-code", status: .finished,
            data: .raw(["code": AnyCodable("v101"), "version_number": AnyCodable(101)]),
            parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, versionNumber: 101, createdAt: nil)
        let model = WatchEmbedPreviewMapper.makeModel(for: record, chatId: "synthetic-chat")
        XCTAssertEqual(model.currentVersion, 101)
        let ref = WatchEmbedRef(id: embedID, type: "code-code", status: "finished", data: record.rawData)
        XCTAssertEqual(WatchEmbedPreviewMapper.embedRecord(from: ref).versionNumber, 101)
    }
}
