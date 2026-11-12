// Tests of `EmbedVersionEditModel` (Core/CoreBridge/CoreEmbedVersions.swift):
// the image fullscreen's Enhance button states, its operation id reuse after
// a timeout or cancel, restore with confirmation, the reload after a
// VersionConflict and the mapping of typed core errors to messages. The core
// calls go to a scripted fake (`FakeEmbedVersionsClient`); the core's own
// behaviour (versions, billing, idempotency) is covered by the crate tests.
import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class FakeEmbedVersionsClient: EmbedVersionsCoreClient {
    var histories: [Result<EmbedVersionHistoryRecord, EmbedEditError>] = []
    var starts: [Result<ImageEnhanceJobRecord, EmbedEditError>] = []
    var statuses: [Result<ImageEnhanceJobRecord, EmbedEditError>] = []
    var waits: [Result<ImageEnhanceJobRecord, EmbedEditError>] = []
    var saves: [Result<ImageEnhanceSavedRecord, EmbedEditError>] = []
    var restores: [Result<EmbedRevisionOutcomeRecord, EmbedEditError>] = []
    private(set) var calls: [String] = []
    private(set) var operationIds: [String] = []
    private(set) var historyScopes: [EmbedScopeRecord?] = []
    private var pending: [String: String] = [:]

    private func next<T>(_ queue: inout [Result<T, EmbedEditError>], _ name: String) throws -> T {
        calls.append(name)
        guard !queue.isEmpty else { throw EmbedEditError.Internal(reason: "unscripted_\(name)") }
        return try queue.removeFirst().get()
    }

    func versionHistory(embedId: String, scope: EmbedScopeRecord?) async throws -> EmbedVersionHistoryRecord {
        historyScopes.append(scope)
        if histories.isEmpty { calls.append("history"); return Self.history(current: 1) }
        return try next(&histories, "history")
    }
    func restoreVersion(embedId: String, scope: EmbedScopeRecord, fromVersion: Int64) async throws -> EmbedRevisionOutcomeRecord {
        try next(&restores, "restore:\(fromVersion)")
    }
    func startEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceJobRecord {
        operationIds.append(operationId)
        return try next(&starts, "start")
    }
    func enhanceStatus(operationId: String) async throws -> ImageEnhanceJobRecord {
        operationIds.append(operationId)
        return try next(&statuses, "status")
    }
    func waitEnhance(operationId: String, deadlineMs: UInt64) async throws -> ImageEnhanceJobRecord {
        operationIds.append(operationId)
        XCTAssertEqual(deadlineMs, EmbedVersionEditModel.waitSliceMs)
        return try next(&waits, "wait")
    }
    func saveEnhance(embedId: String, scope: EmbedScopeRecord, operationId: String) async throws -> ImageEnhanceSavedRecord {
        operationIds.append(operationId)
        return try next(&saves, "save")
    }
    func pendingEnhanceOperation(embedId: String) -> String? { pending[embedId] }
    func rememberEnhanceOperation(_ operationId: String?, embedId: String) { pending[embedId] = operationId }

    static func history(current: Int64) -> EmbedVersionHistoryRecord {
        EmbedVersionHistoryRecord(embedId: "embed-1", currentVersion: current, versions: (1...current).map { version in
            EmbedVersionRecord(version: version, origin: version == 1 ? .assistant : .user,
                               action: version == 1 ? nil : .enhance, createdAt: 1_700_000_000 + version,
                               isCurrent: version == current)
        })
    }

    static func job(_ state: ImageEnhanceStateRecord, operationId: String = "op") -> ImageEnhanceJobRecord {
        ImageEnhanceJobRecord(operationId: operationId, embedId: "embed-1", state: state, baseVersion: 1,
                              targetVersion: 2, credits: 63, charged: state != .failed, createdAt: 1_700_000_000,
                              expiresAt: 1_700_086_400, errorCode: state == .failed ? "provider_failed" : nil)
    }

    static func outcome(version: Int64, action: EmbedUpdateActionRecord, restoredFrom: Int64? = nil) -> EmbedRevisionOutcomeRecord {
        EmbedRevisionOutcomeRecord(embedId: "embed-1", operationId: "op", version: version, baseVersion: version - 1,
                                   action: action, restoredFrom: restoredFrom, surface: .chat, idempotent: false,
                                   cacheSynchronized: true, event: .written)
    }
}

final class CoreEmbedVersionsTests: XCTestCase {
    private let chatPlace = EmbedEditPlace(chatId: "chat-1")

    @MainActor
    private func makeModel(_ client: FakeEmbedVersionsClient, place: EmbedEditPlace? = nil,
                           enhanceable: Bool = true) async -> (EmbedVersionEditModel, [Int64?]) {
        let model = EmbedVersionEditModel(client: client)
        await model.open(embedId: "embed-1", place: place ?? chatPlace, enhanceable: enhanceable).value
        return (model, [])
    }

    // contract-test: supporting surface=gui.apple assertions=embed-user-edits.enhance.button
    @MainActor
    func testPlaceAvailabilityMirrorsWebScopeRules() {
        XCTAssertEqual(EmbedEditPlace(chatId: "c").availability, .available(.chat(chatId: "c", teamId: nil)))
        XCTAssertEqual(EmbedEditPlace(chatId: "c", chatTeamId: "t").availability, .unavailable(.team))
        XCTAssertEqual(EmbedEditPlace(chatId: "c", readOnly: true).availability, .unavailable(.readOnly))
        XCTAssertEqual(EmbedEditPlace().availability, .unavailable(.readOnly))
        XCTAssertEqual(EmbedEditPlace(chatId: "c", projectId: "p").availability, .available(.project(projectId: "p", teamId: nil)))
        XCTAssertEqual(EmbedEditPlace(projectId: "p", projectTeamId: "t").availability, .unavailable(.team))
        // Team embeds still read their history in their own scope.
        XCTAssertEqual(EmbedEditPlace(chatId: "c", chatTeamId: "t").readScope, .chat(chatId: "c", teamId: "t"))
    }

    // contract-test: direct surface=gui.apple assertions=embed-user-edits.enhance.button,embed-user-edits.edit.next-version
    @MainActor
    func testEnhanceRunsStartWaitSaveAndShowsTheNewVersion() async {
        let client = FakeEmbedVersionsClient()
        client.starts = [.success(FakeEmbedVersionsClient.job(.pending))]
        client.waits = [.success(FakeEmbedVersionsClient.job(.ready))]
        client.saves = [.success(.committed(operationId: "op", outcome: FakeEmbedVersionsClient.outcome(version: 2, action: .enhance)))]
        client.histories = [.success(FakeEmbedVersionsClient.history(current: 1)), .success(FakeEmbedVersionsClient.history(current: 2))]
        let (model, _) = await makeModel(client)
        var heads: [Int64?] = []
        model.onHeadChanged = { heads.append($0) }
        XCTAssertEqual(model.phase, .idle)

        let task = model.startEnhance()
        XCTAssertEqual(model.phase, .running)
        XCTAssertEqual(model.phase.buttonState, "running")
        XCTAssertNil(model.startEnhance(), "A running Enhance cannot be started a second time")
        await task?.value

        XCTAssertEqual(model.phase, .saved(version: 2))
        XCTAssertEqual(model.credits, 63)
        XCTAssertEqual(model.message, .enhanced(version: 2))
        XCTAssertEqual(heads, [2])
        XCTAssertEqual(model.history?.currentVersion, 2)
        XCTAssertTrue(model.showsVersionList)
        XCTAssertEqual(client.calls, ["history", "start", "wait", "save", "history"])
        XCTAssertEqual(Set(client.operationIds).count, 1, "One operation id for start, wait and save")
        XCTAssertNil(client.pendingEnhanceOperation(embedId: "embed-1"))
    }

    // contract-test: direct surface=gui.apple assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
    @MainActor
    func testTimeoutKeepsTheOperationIdAndTheNextPressResumesIt() async {
        let client = FakeEmbedVersionsClient()
        client.starts = [.success(FakeEmbedVersionsClient.job(.pending))]
        client.waits = Array(repeating: .failure(.EnhanceTimeout(operationId: "op")), count: EmbedVersionEditModel.maxWaitSlices)
        let (model, _) = await makeModel(client)

        await model.startEnhance()?.value
        XCTAssertEqual(model.phase, .failed)
        XCTAssertEqual(model.message, .enhanceFailed)
        XCTAssertEqual(client.calls.filter { $0 == "wait" }.count, EmbedVersionEditModel.maxWaitSlices)
        let operationId = try? XCTUnwrap(client.pendingEnhanceOperation(embedId: "embed-1"))
        XCTAssertNotNil(operationId)

        client.statuses = [.success(FakeEmbedVersionsClient.job(.ready))]
        client.saves = [.success(.alreadyCommitted(operationId: "op", version: 2))]
        await model.startEnhance()?.value

        XCTAssertEqual(model.phase, .saved(version: 2))
        XCTAssertEqual(client.calls.filter { $0 == "start" }.count, 1, "The resume reads the job instead of starting a new one")
        XCTAssertEqual(Set(client.operationIds), [operationId!], "Every call reuses the first operation id")
        XCTAssertNil(client.pendingEnhanceOperation(embedId: "embed-1"))
    }

    // contract-test: supporting surface=gui.apple assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
    @MainActor
    func testCancelKeepsTheOperationAndReopeningResumesIt() async {
        let client = FakeEmbedVersionsClient()
        client.starts = [.success(FakeEmbedVersionsClient.job(.pending))]
        client.waits = [.failure(.Cancelled)]
        let (model, _) = await makeModel(client)
        await model.startEnhance()?.value
        XCTAssertEqual(model.phase, .idle)
        XCTAssertNil(model.message)
        let operationId = client.pendingEnhanceOperation(embedId: "embed-1")
        XCTAssertNotNil(operationId)

        client.statuses = [.success(FakeEmbedVersionsClient.job(.committed))]
        client.saves = [.success(.alreadyCommitted(operationId: "op", version: 2))]
        await model.open(embedId: "embed-1", place: chatPlace, enhanceable: true).value
        for _ in 0..<100 where model.phase != .saved(version: 2) { await Task.yield() }

        XCTAssertEqual(model.phase, .saved(version: 2))
        XCTAssertEqual(client.operationIds.last, operationId)
    }

    // contract-test: direct surface=gui.apple assertions=embed-user-edits.edit.next-version
    @MainActor
    func testVersionConflictReloadsTheHistoryAndTheHead() async {
        let client = FakeEmbedVersionsClient()
        client.starts = [.failure(.VersionConflict(currentVersion: 4))]
        let (model, _) = await makeModel(client)
        var heads: [Int64?] = []
        model.onHeadChanged = { heads.append($0) }

        await model.startEnhance()?.value

        XCTAssertEqual(model.phase, .failed)
        XCTAssertEqual(model.message, .versionConflict)
        XCTAssertEqual(heads, [nil])
        XCTAssertEqual(client.calls, ["history", "start", "history"])
        XCTAssertNil(client.pendingEnhanceOperation(embedId: "embed-1"), "Nothing was charged: a new press starts fresh")
    }

    // contract-test: supporting surface=gui.apple assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
    @MainActor
    func testEnhanceErrorsMapToTheWebMessages() async {
        let cases: [(EmbedEditError, ImageEnhancePhase, EmbedEditMessage?, Bool)] = [
            (.InsufficientCredits, .insufficientCredits, .insufficientCredits, false),
            (.TeamUnavailable, .unavailable(.team), .teamUnavailable, false),
            (.EnhanceFailed(operationId: "op", code: "provider_failed"), .failed, .enhanceFailed, false),
            (.EnhanceExpired(operationId: "op"), .expired, .enhanceFailed, false),
            (.Offline, .failed, .enhanceFailed, true),
            (.RateLimited, .failed, .enhanceFailed, true),
            (.InvalidSource(code: "unsupported_format"), .failed, .enhanceFailed, false),
        ]
        for (error, phase, message, keepsOperation) in cases {
            let client = FakeEmbedVersionsClient()
            client.starts = [.failure(error)]
            let (model, _) = await makeModel(client)
            await model.startEnhance()?.value
            XCTAssertEqual(model.phase, phase, "\(error)")
            XCTAssertEqual(model.message, message, "\(error)")
            XCTAssertEqual(client.pendingEnhanceOperation(embedId: "embed-1") != nil, keepsOperation, "\(error)")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
    @MainActor
    func testFailedJobFromTheWaitIsNotSaved() async {
        let client = FakeEmbedVersionsClient()
        client.starts = [.success(FakeEmbedVersionsClient.job(.failed))]
        let (model, _) = await makeModel(client)
        await model.startEnhance()?.value
        XCTAssertEqual(model.phase, .failed)
        XCTAssertFalse(client.calls.contains("save"))
        XCTAssertNil(client.pendingEnhanceOperation(embedId: "embed-1"))
    }

    // contract-test: supporting surface=gui.apple assertions=embed-user-edits.enhance.button
    @MainActor
    func testTeamAndReadOnlyPlacesNeverCallTheCore() async {
        for place in [EmbedEditPlace(chatId: "c", chatTeamId: "t"), EmbedEditPlace(chatId: "c", readOnly: true)] {
            let client = FakeEmbedVersionsClient()
            let (model, _) = await makeModel(client, place: place)
            XCTAssertNil(model.startEnhance())
            XCTAssertFalse(model.canRestore)
            XCTAssertNil(model.requestRestore(1))
            XCTAssertEqual(client.calls, ["history"])
            XCTAssertEqual(model.phase.buttonState, "unavailable")
        }
    }

    // contract-test: direct surface=gui.apple assertions=embed-user-edits.restore.creates-version
    @MainActor
    func testRestoreNeedsASecondTapAndCreatesTheNextVersion() async {
        let client = FakeEmbedVersionsClient()
        client.histories = [.success(FakeEmbedVersionsClient.history(current: 2)), .success(FakeEmbedVersionsClient.history(current: 3))]
        client.restores = [.success(FakeEmbedVersionsClient.outcome(version: 3, action: .restore, restoredFrom: 1))]
        let (model, _) = await makeModel(client, enhanceable: false)
        var heads: [Int64?] = []
        model.onHeadChanged = { heads.append($0) }

        XCTAssertNil(model.requestRestore(2), "The current version cannot be restored")
        XCTAssertNil(model.requestRestore(1))
        XCTAssertEqual(model.restoreConfirmVersion, 1)
        XCTAssertFalse(client.calls.contains("restore:1"))

        await model.requestRestore(1)?.value

        XCTAssertEqual(client.calls, ["history", "restore:1", "history"])
        XCTAssertEqual(model.message, .restored(fromVersion: 1))
        XCTAssertEqual(heads, [3])
        XCTAssertEqual(model.history?.versions.count, 3, "Nothing is deleted: the restore is a new version")
        XCTAssertNil(model.restoreConfirmVersion)
        XCTAssertNil(model.restoringVersion)
    }

    // contract-test: supporting surface=gui.apple assertions=embed-user-edits.restore.creates-version,embed-user-edits.edit.next-version
    @MainActor
    func testRestoreConflictReloadsAndOtherRefusalsShowRestoreFailed() async {
        let client = FakeEmbedVersionsClient()
        client.histories = [.success(FakeEmbedVersionsClient.history(current: 2)), .success(FakeEmbedVersionsClient.history(current: 3)),
                            .success(FakeEmbedVersionsClient.history(current: 3))]
        client.restores = [.failure(.VersionConflict(currentVersion: 3)), .failure(.Refused(code: "restore_source_missing"))]
        let (model, _) = await makeModel(client, enhanceable: false)
        var heads: [Int64?] = []
        model.onHeadChanged = { heads.append($0) }

        model.requestRestore(1)
        await model.requestRestore(1)?.value
        XCTAssertEqual(model.message, .versionConflict)
        XCTAssertEqual(heads, [nil])
        XCTAssertEqual(model.history?.currentVersion, 3)

        model.requestRestore(1)
        await model.requestRestore(1)?.value
        XCTAssertEqual(model.message, .restoreFailed)
        XCTAssertEqual(model.restoreConfirmVersion, 1, "A failed restore can be confirmed again")
    }

    // contract-test: supporting surface=gui.apple assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
    @MainActor
    func testFailureClassesKeepOnlyUnsettledOperations() {
        XCTAssertTrue(EmbedEditFailure.classify(EmbedEditError.EnhanceTimeout(operationId: "op")).keepsOperation)
        XCTAssertTrue(EmbedEditFailure.classify(EmbedEditError.EnhanceNotReady(operationId: "op")).keepsOperation)
        XCTAssertTrue(EmbedEditFailure.classify(EmbedEditError.Offline).keepsOperation)
        XCTAssertTrue(EmbedEditFailure.classify(CancellationError()).keepsOperation)
        XCTAssertFalse(EmbedEditFailure.classify(EmbedEditError.OperationConflict).keepsOperation)
        XCTAssertFalse(EmbedEditFailure.classify(EmbedEditError.EnhanceExpired(operationId: "op")).keepsOperation)
        XCTAssertEqual(EmbedEditFailure.classify(EmbedEditError.VersionConflict(currentVersion: nil)), .versionConflict)
        XCTAssertEqual(EmbedEditFailure.classify(EmbedEditError.AccessDenied(code: "forbidden")), .refused("forbidden"))
    }
}
