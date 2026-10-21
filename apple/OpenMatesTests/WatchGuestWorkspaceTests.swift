// Production public catalog and pairing suspension fences; no account/network data.
import XCTest
@testable import OpenMates

@MainActor
final class WatchGuestWorkspaceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.compact-workspace,apple-watch.guest.account-isolation
    func testCatalogSearchAndReadingUseOnlyBundledExamplesAndPreserveMainWrapper() throws {
        let store = WatchPublicExampleStore(text: { LocalizationManager.shared.text($0) })
        XCTAssertEqual(Set(store.chats.map(\.id)), BundledPublicExampleCatalog.allowedIDs)
        XCTAssertEqual(store.chats.count, 6)
        XCTAssertTrue(store.search("private account title sentinel").isEmpty)
        let matches = store.search("Artemis")
        XCTAssertEqual(matches.map(\.id), ["example-artemis-ii-mission"])
        XCTAssertEqual(store.search("  ").count, store.chats.count)
        for id in BundledPublicExampleCatalog.orderedIDs {
            let watch = try XCTUnwrap(store.conversation(id: id))
            let main = try XCTUnwrap(PublicChatContent.chat(for: id))
            XCTAssertEqual(watch.summary.title, main.chat.title)
            XCTAssertEqual(watch.messages.map(\.id), main.messages.map(\.id))
            XCTAssertEqual(watch.messages.map(\.content), main.messages.map(\.content))
            XCTAssertEqual(Set(watch.records.map(\.id)), Set(main.embedRecords.values.map(\.id)))
            XCTAssertTrue(watch.messages.allSatisfy { $0.encryptedContent == nil && !$0.isPending })
            XCTAssertNil(watch.summary.encryptedChatKey)
        }
        for excluded in ["demo-for-everyone", "demo-for-developers", "legal-privacy", "private-chat-sentinel"] {
            XCTAssertNil(store.conversation(id: excluded))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.compact-workspace,apple-watch.chats.compact-layout
    func testBundledArtemisHydratesRealEmbedGroupsAndKeepsMarkersInPlace() throws {
        let store = WatchPublicExampleStore(text: { LocalizationManager.shared.text($0) })
        let conversation = try XCTUnwrap(store.conversation(id: "example-artemis-ii-mission"))
        XCTAssertFalse(conversation.records.isEmpty, "Watch bundles the same admitted static embed resources")
        let assistant = try XCTUnwrap(conversation.messages.last)
        XCTAssertFalse(assistant.embedRefs?.isEmpty ?? true)
        let segments = WatchMessageRenderProjection.segments(message: assistant, hydratedChildren: conversation.records)
        XCTAssertFalse(segments.isEmpty)
        XCTAssertTrue(segments.contains { segment in
            if case .embeds(let models) = segment.content { return models.contains { $0.state != .unavailable } }
            return false
        })
        let parsed = BundledPublicExampleCatalog.extractEmbeds(from: "Before\n```json\n{\"type\":\"code\",\"embed_id\":\"public-code\",\"code\":\"print(1)\"}\n```\nAfter", fallbackAppId: "code")
        XCTAssertTrue(parsed.content.hasPrefix("Before"))
        XCTAssertTrue(parsed.content.hasSuffix("After"))
        XCTAssertTrue(parsed.content.contains("[[embed:public-code]]"))
        XCTAssertEqual(parsed.records.first?.id, "public-code")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back
    func testLeavingAttemptInvalidatesPendingAndAcceptedTokensBeforeNextLogin() {
        var attempt = WatchPairAttemptState()
        let first = attempt.begin(serverProfile: .production)
        let response = PairLoginInitiation(token: "OLD346", pairURLString: "https://openmates.org/#pair=OLD346")
        XCTAssertTrue(attempt.accept(response, generation: first, serverProfile: .production))
        attempt.invalidate()
        XCTAssertNil(attempt.token)
        XCTAssertFalse(attempt.accepts(generation: first, serverProfile: .production))
        XCTAssertFalse(attempt.accept(response, generation: first, serverProfile: .production))
        let current = attempt.begin(serverProfile: .production)
        XCTAssertGreaterThan(current, first)
        XCTAssertFalse(attempt.accept(response, generation: first, serverProfile: .production))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back
    func testCancelledPairCannotPublishAcrossReceiverPushKeyOrAcknowledgementSuspensions() async throws {
        for stop in ["receiver", "push", "key", "ack"] {
            let reached = expectation(description: "Reached " + stop)
            let gate = WatchGuestTestGate()
            var effects: [String] = []
            var published = false
            var cleaned = false
            let task = Task { @MainActor in
                try await WatchPairCommitSequence.run(isCurrent: { true }, complete: {
                    effects.append("receiver")
                    if stop == "receiver" { await gate.hold(reached) }
                    return 42
                }, unregisterPush: {
                    effects.append("push")
                    if stop == "push" { await gate.hold(reached) }
                }, persistKey: { _ in
                    effects.append("key")
                    if stop == "key" { await gate.hold(reached) }
                }, persistMetadata: { _ in effects.append("metadata") }, acknowledge: {
                    effects.append("ack")
                    if stop == "ack" { await gate.hold(reached) }
                }, publish: { _ in published = true }, rollback: { _ in cleaned = true })
            }
            await fulfillment(of: [reached], timeout: 3)
            task.cancel()
            gate.release()
            do { try await task.value; XCTFail("Departed attempt must fail") } catch is CancellationError {} catch { XCTFail("Unexpected failure: \(error)") }
            XCTAssertFalse(published, stop)
            XCTAssertTrue(cleaned, stop)
            XCTAssertEqual(effects.last, stop, "No following mutation may start after cancellation")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back
    func testCurrentPairPublishesOnlyAfterAcknowledgementFinishes() async throws {
        let reached = expectation(description: "Acknowledgement pending")
        let gate = WatchGuestTestGate()
        var published: Int?
        var cleaned = false
        let task = Task { @MainActor in
            try await WatchPairCommitSequence.run(isCurrent: { true }, complete: { 42 },
                unregisterPush: {}, persistKey: { _ in }, persistMetadata: { _ in },
                acknowledge: { await gate.hold(reached) }, publish: { published = $0 }, rollback: { _ in cleaned = true })
        }
        await fulfillment(of: [reached], timeout: 3)
        XCTAssertNil(published)
        gate.release(); try await task.value
        XCTAssertEqual(published, 42)
        XCTAssertFalse(cleaned)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back
    func testLateCompletionFailsCurrentAttemptFenceWithoutTaskCancellation() async throws {
        var current = true
        var published = false
        var cleaned = false
        do {
            try await WatchPairCommitSequence.run(isCurrent: { current }, complete: { 42 },
                unregisterPush: {}, persistKey: { _ in }, persistMetadata: { _ in },
                acknowledge: { current = false }, publish: { _ in published = true }, rollback: { _ in cleaned = true })
            XCTFail("Late accepted response must be discarded")
        } catch is CancellationError {} catch { XCTFail("Unexpected failure: \(error)") }
        XCTAssertFalse(published)
        XCTAssertTrue(cleaned)
    }
}

@MainActor
private final class WatchGuestTestGate {
    private var continuation: CheckedContinuation<Void, Never>?
    func hold(_ reached: XCTestExpectation) async {
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            reached.fulfill()
        }
    }
    func release() { continuation?.resume(); continuation = nil }
}
