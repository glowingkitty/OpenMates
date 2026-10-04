import XCTest
@testable import OpenMates

final class ActiveChatsPolicyTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget
    func testConcurrentChatsCountOnceAndDuplicateStartIsNotFreshEvidence() {
        var policy = ActiveChatsPolicy()
        XCTAssertTrue(policy.start(.init(chatID: "fixture-chat-a", turnID: "turn-a"), now: now))
        XCTAssertTrue(policy.start(.init(chatID: "fixture-chat-b", turnID: "turn-b"), now: now))
        XCTAssertFalse(policy.start(.init(chatID: "fixture-chat-a", turnID: "turn-a"), now: now.addingTimeInterval(80)))
        XCTAssertEqual(policy.items.count, 2)
        XCTAssertEqual(policy.orderedItems.map(\.ordinal), [1, 2])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget
    func testServerAliasCompletesProvisionalRunAndRejectsBothReplays() {
        var policy = ActiveChatsPolicy()
        policy.start(.init(chatID: "chat", turnID: "client-uuid"), now: now)
        XCTAssertTrue(policy.adopt(chatID: "chat", provisional: "client-uuid", server: "server-message", now: now))
        XCTAssertTrue(policy.finish(chatID: "chat", turnID: "server-message"))
        XCTAssertTrue(policy.items.isEmpty)
        XCTAssertFalse(policy.start(.init(chatID: "chat", turnID: "client-uuid"), now: now))
        XCTAssertFalse(policy.start(.init(chatID: "chat", turnID: "server-message"), now: now))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget
    func testOldTerminalAndLateAliasCannotEndOrAdoptReplacementTurn() {
        var policy = ActiveChatsPolicy()
        policy.start(.init(chatID: "chat", turnID: "old"), now: now)
        policy.start(.init(chatID: "chat", turnID: "new"), now: now)
        XCTAssertFalse(policy.finish(chatID: "chat", turnID: "old"))
        XCTAssertFalse(policy.adopt(chatID: "chat", provisional: "old", server: "late-server", now: now))
        XCTAssertFalse(policy.progress(chatID: "chat", turnID: "old", now: now))
        XCTAssertEqual(policy.items["chat"]?.turnID, "new")
        XCTAssertFalse(policy.start(.init(chatID: "chat", turnID: "old"), now: now))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget
    func testFinishBeforeStartSuppressesReconnectReplayButAllowsDifferentTurn() {
        var policy = ActiveChatsPolicy()
        XCTAssertFalse(policy.finish(chatID: "chat", turnID: "finished"))
        XCTAssertFalse(policy.start(.init(chatID: "chat", turnID: "finished"), now: now))
        XCTAssertTrue(policy.start(.init(chatID: "chat", turnID: "next"), now: now))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget
    func testNoEvidenceExpiresAtFifteenMinutesAndFreshEvidenceRenewsOnlyMatchingTurn() {
        var policy = ActiveChatsPolicy()
        policy.start(.init(chatID: "chat", turnID: "turn"), now: now)
        XCTAssertFalse(policy.progress(chatID: "chat", turnID: "other", now: now.addingTimeInterval(100)))
        XCTAssertTrue(policy.progress(chatID: "chat", turnID: "turn", now: now.addingTimeInterval(100)))
        policy.expire(now: now.addingTimeInterval(999)); XCTAssertEqual(policy.items.count, 1)
        policy.expire(now: now.addingTimeInterval(1_000)); XCTAssertTrue(policy.items.isEmpty)
        XCTAssertFalse(policy.start(.init(chatID: "chat", turnID: "turn"), now: now.addingTimeInterval(1_001)))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget
    func testAuthoritativeSnapshotRemovesAbsentRunsAndCannotResurrectCompletedRuns() {
        var policy = ActiveChatsPolicy()
        policy.start(.init(chatID: "a", turnID: "a1"), now: now)
        policy.start(.init(chatID: "b", turnID: "b1"), now: now)
        policy.reconcile([.init(chatID: "b", turnID: "b1")], now: now)
        XCTAssertEqual(Set(policy.items.keys), ["b"])
        policy.reconcile([.init(chatID: "a", turnID: "a1"), .init(chatID: "b", turnID: "b1")], now: now)
        XCTAssertEqual(Set(policy.items.keys), ["b"])
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testCoordinatorFencesAccountServerRuntimeAndTeamAndRequiresOnlyAuthentication() {
        let coordinator = ActiveChatsCoordinator(publishWidgetSnapshot: { _, _, _ in })
        let token = UUID()
        let team = APIRequestTeamContext(epoch: 1, teamID: "team")
        coordinator.configure(accountID: "account", server: .development, scope: token, team: team, authenticated: true)
        let scope = coordinator.currentScope!
        let mismatches = [
            ActiveChatsScope(accountID: "other", server: .development, scope: token, team: team),
            ActiveChatsScope(accountID: "account", server: .production, scope: token, team: team),
            ActiveChatsScope(accountID: "account", server: .development, scope: UUID(), team: team),
            ActiveChatsScope(accountID: "account", server: .development, scope: token, team: .init(epoch: 1, teamID: "other-team")),
            ActiveChatsScope(accountID: "account", server: .development, scope: token, team: .init(epoch: 2, teamID: "team"))]
        for mismatch in mismatches { coordinator.started(chatID: "chat", turnID: "turn", scope: mismatch, now: now) }
        XCTAssertTrue(coordinator.policy.items.isEmpty)
        coordinator.started(chatID: "chat", turnID: "turn", scope: scope, now: now)
        XCTAssertEqual(coordinator.policy.items.count, 1)
        coordinator.configure(accountID: "account", server: .development, scope: token, team: team, authenticated: true)
        XCTAssertEqual(coordinator.policy.items.count, 1)
        coordinator.started(chatID: "chat", turnID: "turn", scope: scope, now: now)
        XCTAssertEqual(coordinator.policy.items.count, 1)
        coordinator.configure(accountID: "account", server: .development, scope: token, team: team, authenticated: false)
        XCTAssertTrue(coordinator.policy.items.isEmpty)
        coordinator.reset()
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.processing.widget
    func testOrderedStreamAdoptsAcceptedSendButThinkingAndCancelRequestAreNotTerminal() {
        let coordinator = ActiveChatsCoordinator(publishWidgetSnapshot: { _, _, _ in })
        coordinator.configure(accountID: "account", server: .development, scope: UUID(), team: .init(epoch: 0, teamID: nil), authenticated: true)
        let scope = coordinator.currentScope!
        coordinator.started(chatID: "chat", turnID: "client-user", scope: scope)
        coordinator.consume(.taskInitiated(chatId: "chat", taskId: "task", userMessageId: "client-user"), chatID: "chat", scope: scope)
        let metadata = StreamingClient.ChatMetadata(title: nil, iconNames: [], category: nil, modelName: nil, providerName: nil, serverRegion: nil, userMessageId: "client-user", encryptedChatKey: nil)
        coordinator.consume(.typingStarted(chatId: "chat", messageId: "assistant", metadata: metadata), chatID: "chat", scope: scope)
        coordinator.consume(.thinkingComplete(chatId: "chat", messageId: "assistant"), chatID: "chat", scope: scope)
        coordinator.consume(.cancelRequested(chatId: "chat", taskId: "task"), chatID: "chat", scope: scope)
        coordinator.consume(.typingEnded(chatId: "chat", messageId: nil), chatID: "chat", scope: scope)
        XCTAssertEqual(coordinator.policy.items.count, 1)
        coordinator.consume(.chunk(chatId: "chat", messageId: "assistant", sequence: 1, content: "Disposable fixture", isFinal: true, userMessageId: "client-user", category: nil, modelName: nil, rejectionReason: nil), chatID: "chat", scope: scope)
        XCTAssertTrue(coordinator.policy.items.isEmpty)
        coordinator.consume(.taskInitiated(chatId: "chat", taskId: "task", userMessageId: "client-user"), chatID: "chat", scope: scope)
        XCTAssertTrue(coordinator.policy.items.isEmpty)
    }
}
