// Admission policy evidence only. These tests cannot issue a physical lease or open a call.
import XCTest
@testable import OpenMates

final class WatchVoiceEvaluationPolicyTests: XCTestCase {
    private func binding(account: String = "account-a", profile: ServerProfile = .development,
                         generation: UInt64 = 1, chat: String = "11111111-1111-4111-8111-111111111111",
                         attempt: UUID, route: String = "observed-route-hash") -> WatchVoiceEvaluationBinding {
        WatchVoiceEvaluationBinding(accountID: account, profile: profile, accountGeneration: generation,
            chatID: chat, attemptID: attempt, routeFingerprint: route)
    }
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions,video-call.privacy
    func testDiagnosticOfferRequiresSameOwnerProfileGenerationChatAttemptAndRoute() throws {
        let attempt = UUID(), original = binding(attempt: attempt)
        let changed = [binding(account: "account-b", attempt: attempt),
            binding(profile: .production, attempt: attempt), binding(generation: 2, attempt: attempt),
            binding(chat: "22222222-2222-4222-8222-222222222222", attempt: attempt),
            binding(attempt: UUID()), binding(attempt: attempt, route: "different-route-hash")]
        for candidate in changed {
            var policy = WatchVoiceEvaluationPolicy(binding: original, observedAt: 100)
            XCTAssertFalse(policy.permitsStart(current: candidate, now: 101))
            XCTAssertThrowsError(try policy.consume(current: candidate, now: 101))
            XCTAssertFalse(policy.permitsStart(current: original, now: 101))
            XCTAssertFalse(policy.permitsExecution(current: original, now: 101))
        }
        let production = binding(profile: .production, attempt: attempt)
        var policy = WatchVoiceEvaluationPolicy(binding: production, observedAt: 100)
        XCTAssertThrowsError(try policy.consume(current: production, now: 101))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions,video-call.audio.single-owner
    func testOfferIsSingleUseAndExpiresBeforeAndDuringEvaluation() throws {
        let original = binding(attempt: UUID())
        var policy = WatchVoiceEvaluationPolicy(binding: original, observedAt: 100)
        XCTAssertFalse(policy.permitsExecution(current: original, now: 101))
        XCTAssertTrue(policy.permitsStart(current: original, now: 129))
        try policy.consume(current: original, now: 129)
        XCTAssertFalse(policy.permitsStart(current: original, now: 129))
        XCTAssertTrue(policy.permitsExecution(current: original, now: 188.99))
        XCTAssertFalse(policy.permitsExecution(current: original, now: 189))
        XCTAssertThrowsError(try policy.consume(current: original, now: 130))
        XCTAssertFalse(policy.permitsExecution(current: original, now: 131))
        var expired = WatchVoiceEvaluationPolicy(binding: original, observedAt: 100)
        XCTAssertThrowsError(try expired.consume(current: original, now: 130))
        var revoked = WatchVoiceEvaluationPolicy(binding: original, observedAt: 100)
        try revoked.consume(current: original, now: 101)
        revoked.revoke()
        XCTAssertFalse(revoked.permitsExecution(current: original, now: 102))
    }
}
