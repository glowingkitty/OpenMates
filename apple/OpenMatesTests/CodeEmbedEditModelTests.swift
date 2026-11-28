// Tests of `CodeEmbedEditModel` (Features/Embeds/Views/CodeEmbedEditor.swift):
// saving an edited Project code file as the next version through a fake
// `EmbedVersionsCoreClient`, and the conflict and failure messages. The core's
// content building and compare-and-swap are covered by the crate tests.
import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class FakeCommitClient: EmbedVersionsCoreClient {
    var result: Result<EmbedRevisionOutcomeRecord, EmbedEditError> = .failure(.Internal(reason: "unscripted"))
    private(set) var commits: [(embedId: String, baseVersion: Int64, content: String)] = []

    func commitEdit(embedId: String, scope: EmbedScopeRecord, baseVersion: Int64, content: String) async throws -> EmbedRevisionOutcomeRecord {
        commits.append((embedId, baseVersion, content))
        return try result.get()
    }
    func versionHistory(embedId: String, scope: EmbedScopeRecord?) async throws -> EmbedVersionHistoryRecord { throw EmbedEditError.Internal(reason: "unused") }
    func restoreVersion(embedId: String, scope: EmbedScopeRecord, fromVersion: Int64) async throws -> EmbedRevisionOutcomeRecord { throw EmbedEditError.Internal(reason: "unused") }
    func startEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceJobRecord { throw EmbedEditError.Internal(reason: "unused") }
    func enhanceStatus(operationId: String) async throws -> ImageEnhanceJobRecord { throw EmbedEditError.Internal(reason: "unused") }
    func waitEnhance(operationId: String, deadlineMs: UInt64) async throws -> ImageEnhanceJobRecord { throw EmbedEditError.Internal(reason: "unused") }
    func saveEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceSavedRecord { throw EmbedEditError.Internal(reason: "unused") }
    func pendingEnhanceOperation(embedId: String) -> String? { nil }
    func rememberEnhanceOperation(_ operationId: String?, embedId: String) {}
}

final class CodeEmbedEditModelTests: XCTestCase {
    private let scope = EmbedScopeRecord.project(projectId: "project-1", teamId: nil)
    private let content: [String: Any] = ["type": "code", "code": "old", "version_number": 2]

    @MainActor
    private func makeModel(_ client: FakeCommitClient) -> CodeEmbedEditModel {
        CodeEmbedEditModel(client: client) { _, code, version in "built:\(code):\(version)" }
    }

    private func outcome(_ version: Int64) -> EmbedRevisionOutcomeRecord {
        EmbedRevisionOutcomeRecord(embedId: "embed-1", operationId: "op", version: version, baseVersion: version - 1,
                                   action: .edit, restoredFrom: nil, surface: .project, idempotent: false,
                                   cacheSynchronized: true, event: .written)
    }

    // contract-test: direct surface=gui.apple assertions=embed-user-edits.edit.next-version
    @MainActor
    func testSaveCommitsTheNextVersionAndClosesTheEditor() async {
        let client = FakeCommitClient()
        client.result = .success(outcome(3))
        let model = makeModel(client)
        model.begin(code: "old")
        model.draft = "new code"
        let version = await model.save(embedId: "embed-1", scope: scope, baseVersion: 2, currentContent: content)
        XCTAssertEqual(version, 3)
        XCTAssertEqual(client.commits.count, 1)
        XCTAssertEqual(client.commits.first?.baseVersion, 2)
        XCTAssertEqual(client.commits.first?.content, "built:new code:3")
        XCTAssertFalse(model.isEditing)
        XCTAssertNil(model.failure)
    }

    // contract-test: direct surface=gui.apple assertions=embed-user-edits.edit.next-version
    @MainActor
    func testVersionConflictShowsTheConflictMessageAndKeepsTheEditor() async {
        let client = FakeCommitClient()
        client.result = .failure(.VersionConflict(currentVersion: 4))
        let model = makeModel(client)
        model.begin(code: "old")
        let version = await model.save(embedId: "embed-1", scope: scope, baseVersion: 2, currentContent: content)
        XCTAssertNil(version)
        XCTAssertEqual(model.failure, .conflict)
        XCTAssertEqual(model.failure?.message, AppStrings.embedEditConflict)
        XCTAssertTrue(model.isEditing)
    }

    // contract-test: direct surface=gui.apple assertions=embed-user-edits.header.edit-save-button
    @MainActor
    func testOtherFailuresShowTheFailedMessageAndOnlyProjectScopeCanEdit() async {
        let client = FakeCommitClient()
        client.result = .failure(.Offline)
        let model = makeModel(client)
        model.begin(code: "old")
        _ = await model.save(embedId: "embed-1", scope: scope, baseVersion: 2, currentContent: content)
        XCTAssertEqual(model.failure, .failed)
        XCTAssertEqual(model.failure?.message, AppStrings.embedEditFailed)
        XCTAssertTrue(CodeEmbedEditModel.canEdit(availability: .available(scope), finished: true, isRemotePreview: false, hasPII: false))
        XCTAssertFalse(CodeEmbedEditModel.canEdit(availability: .available(.chat(chatId: "c", teamId: nil)), finished: true, isRemotePreview: false, hasPII: false))
        XCTAssertFalse(CodeEmbedEditModel.canEdit(availability: .available(scope), finished: true, isRemotePreview: true, hasPII: false))
        XCTAssertFalse(CodeEmbedEditModel.canEdit(availability: .available(scope), finished: true, isRemotePreview: false, hasPII: true))
    }
}
