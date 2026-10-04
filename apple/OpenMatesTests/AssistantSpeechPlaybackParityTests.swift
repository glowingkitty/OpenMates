import XCTest
@testable import OpenMates

@MainActor
final class AssistantSpeechPlaybackParityTests: XCTestCase {
    private let scope = AssistantSpeechScope(accountID: "test", serverID: "test", chatID: "chat")
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testManualSpeakDoesNotEnableAutoPreferenceAndRequestsSafeDeferredChapters() async {
        var actions: [String] = []
        var wire: [[String: Any]] = []
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in false },
            writePreference: { _, _ in XCTFail("Manual speak must not change preference") },
            resolveAudio: { _, _ in Data() }, play: { _ in }, stopPlayback: {}, cancelResponse: { _, _ in },
            requestSpeech: { _, _, action, parts in actions.append(action); wire = parts }))
        await speech.activate(scope)
        await speech.request(messageID: "response", markdown: "# Answer\n\nSee [docs](https://private.example/secret).\n\n```json\n{\"secret\":\"private\"}\n```")
        XCTAssertFalse(speech.enabled)
        XCTAssertEqual(actions, ["request"])
        XCTAssertEqual(wire.count, 3)
        XCTAssertFalse(wire.description.contains("private.example"))
        XCTAssertFalse(wire.description.contains("secret"))
        XCTAssertEqual(wire.last?["kind"] as? String, "code_summary")
        speech.reset()
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testPauseDuringAudioResolutionPreventsPlaybackUntilResumeAndCloseRejectsLateEvents() async {
        var resolve: CheckedContinuation<Data, Never>?
        let started = expectation(description: "audio resolving")
        let played = expectation(description: "resumed audio played")
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in true }, writePreference: { _, _ in },
            resolveAudio: { _, _ in await withCheckedContinuation { resolve = $0; started.fulfill() } },
            play: { _ in played.fulfill() }, stopPlayback: {}, cancelResponse: { _, _ in }))
        await speech.activate(scope); speech.expectResponse("response", in: scope)
        let event = AssistantSpeechStatus(chat_id: scope.chatID, message_id: "response", status: "ready",
            segment_id: "first", sequence: 0, generated_asset_id: "asset", segments: nil)
        speech.receive(event, in: scope)
        await fulfillment(of: [started], timeout: 1)
        speech.pause(); resolve?.resume(returning: Data())
        await Task.yield()
        XCTAssertEqual(speech.playbackStatus, .paused)
        speech.play()
        await fulfillment(of: [played], timeout: 1)
        await speech.stop(); speech.receive(event, in: scope)
        XCTAssertFalse(speech.playerVisible)
        XCTAssertEqual(speech.playbackStatus, .stopped)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testAcceptedProviderOffsetPreservesSourceChapterAndRequestsSelectedRegisteredChapter() async {
        let generated = expectation(description: "selected chapter requested")
        var generatedParts: [[String: Any]] = []
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in false }, writePreference: { _, _ in },
            resolveAudio: { _, _ in Data() }, play: { _ in try await Task.sleep(nanoseconds: 10_000_000_000) },
            stopPlayback: {}, cancelResponse: { _, _ in }, requestSpeech: { _, _, action, parts in
                if action == "generate" { generatedParts = parts; generated.fulfill() }
            }))
        await speech.activate(scope)
        await speech.request(messageID: "response", markdown: "# First\n\n# Second")
        speech.receive(.init(chat_id: scope.chatID, message_id: "response", status: "accepted",
            segment_id: nil, sequence: nil, generated_asset_id: nil, segments: [
                .init(segment_id: "first", sequence: 1, status: "ready", generated_asset_id: "asset"),
                .init(segment_id: "second", sequence: 2, status: "registered", generated_asset_id: nil)
            ]), in: scope)
        XCTAssertEqual(speech.activeSequence, 1)
        speech.next()
        XCTAssertEqual(speech.activeSequence, 2)
        XCTAssertEqual(speech.chapter(for: speech.activeSegment), "Second")
        XCTAssertEqual(speech.playbackStatus, .waitingForSegment)
        await fulfillment(of: [generated], timeout: 1)
        XCTAssertEqual(generatedParts.first?["sequence"] as? Int, 1)
        speech.reset()
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testComposerRetryResendsFailedManualRequestWithoutChangingPreference() async {
        var requests = 0
        let retried = expectation(description: "manual request retried")
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in false },
            writePreference: { _, _ in XCTFail("Retry must not enable auto speech") },
            resolveAudio: { _, _ in Data() }, play: { _ in }, stopPlayback: {}, cancelResponse: { _, _ in },
            requestSpeech: { _, _, action, _ in
                XCTAssertEqual(action, "request"); requests += 1
                if requests == 1 { throw URLError(.notConnectedToInternet) }
                retried.fulfill()
            }))
        await speech.activate(scope)
        await speech.request(messageID: "response", markdown: "Answer")
        XCTAssertEqual(speech.playbackStatus, .failed)
        await speech.retry()
        await fulfillment(of: [retried], timeout: 1)
        XCTAssertEqual(requests, 2); XCTAssertFalse(speech.enabled)
        XCTAssertEqual(speech.playbackStatus, .waitingForSegment)
        speech.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testLateCanonicalSourceRequestsRegisteredAutoChapterWithPreludeOffset() async {
        let generated = expectation(description: "auto chapter requested after text arrives")
        var requests: [[String: Any]] = []
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in true }, writePreference: { _, _ in },
            resolveAudio: { _, _ in Data() }, play: { _ in }, stopPlayback: {}, cancelResponse: { _, _ in },
            requestSpeech: { _, id, action, parts in
                XCTAssertEqual(id, "response"); XCTAssertEqual(action, "generate")
                requests = parts; generated.fulfill()
            }))
        await speech.activate(scope); speech.expectResponse("response", in: scope)
        speech.receive(.init(chat_id: scope.chatID, message_id: "response", status: "accepted",
            segment_id: nil, sequence: nil, generated_asset_id: nil, segments: [
                .init(segment_id: "prelude", sequence: 0, status: "ready", generated_asset_id: "asset", kind: "app_use_announcement"),
                .init(segment_id: "chapter", sequence: 1, status: "registered", generated_asset_id: nil)
            ]), in: scope)
        speech.select(sequence: 1)
        XCTAssertTrue(requests.isEmpty)
        speech.updateSource(from: [Message(id: "response", chatId: scope.chatID, role: .assistant,
            content: "See [docs](https://private.example/secret).", encryptedContent: nil,
            createdAt: "2026-10-04T00:00:00Z", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)])
        await fulfillment(of: [generated], timeout: 1)
        XCTAssertEqual(requests.first?["sequence"] as? Int, 0)
        XCTAssertEqual(requests.first?["speakable_text"] as? String, "See docs.")
        XCTAssertFalse(requests.description.contains("private.example"))
        speech.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testResetDuringReplacementCancellationCannotStartStaleRequest() async {
        let cancelling = expectation(description: "old response cancellation suspended")
        var finishCancellation: CheckedContinuation<Void, Never>?
        var requests: [String] = []
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in true }, writePreference: { _, _ in },
            resolveAudio: { _, _ in Data() }, play: { _ in }, stopPlayback: {},
            cancelResponse: { _, _ in await withCheckedContinuation { finishCancellation = $0; cancelling.fulfill() } },
            requestSpeech: { _, id, _, _ in requests.append(id) }))
        await speech.activate(scope); speech.expectResponse("old", in: scope)
        let replacement = Task { await speech.request(messageID: "new", markdown: "Answer") }
        await fulfillment(of: [cancelling], timeout: 1)
        speech.reset()
        finishCancellation?.resume(); await replacement.value
        XCTAssertTrue(requests.isEmpty)
        XCTAssertFalse(speech.playerVisible); XCTAssertNil(speech.scope)
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testClosingBeforeDeferredDispatchCannotRequestStaleChapter() async {
        var actions: [String] = []
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in false }, writePreference: { _, _ in },
            resolveAudio: { _, _ in Data() }, play: { _ in }, stopPlayback: {}, cancelResponse: { _, _ in },
            requestSpeech: { _, _, action, _ in actions.append(action) }))
        await speech.activate(scope)
        await speech.request(messageID: "response", markdown: "Answer")
        speech.receive(.init(chat_id: scope.chatID, message_id: "response", status: "accepted",
            segment_id: nil, sequence: nil, generated_asset_id: nil,
            segments: [.init(segment_id: "chapter", sequence: 0, status: "registered", generated_asset_id: nil)]), in: scope)
        await speech.stop()
        await Task.yield()
        XCTAssertEqual(actions, ["request"])
        XCTAssertEqual(speech.playbackStatus, .stopped)
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testDeletedObservedChatResetsItsSpeechOwnerAndRejectsLateReadyEvents() async {
        var stops = 0
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in true }, writePreference: { _, _ in },
            resolveAudio: { _, _ in XCTFail("Deleted audio must not resolve"); return Data() },
            play: { _ in XCTFail("Deleted audio must not play") }, stopPlayback: { stops += 1 }, cancelResponse: { _, _ in }))
        let runtime = AssistantSpeechAppRuntime(controllerFactory: { _ in speech })
        _ = runtime.controller(for: scope.chatID)
        runtime.reconcileChatIDs([scope.chatID])
        await speech.activate(scope); speech.expectResponse("response", in: scope)
        let before = stops
        runtime.reconcileChatIDs([])
        XCTAssertGreaterThan(stops, before); XCTAssertNil(speech.scope)
        speech.receive(.init(chat_id: scope.chatID, message_id: "response", status: "ready",
            segment_id: "late", sequence: 0, generated_asset_id: "asset", segments: nil), in: scope)
        XCTAssertFalse(speech.playerVisible)
        runtime.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testClosingBeforeRetryDispatchCannotResubmitDismissedResponse() async {
        var requests = 0
        let speech = NativeAssistantSpeech(dependencies: .init(readPreference: { _ in false }, writePreference: { _, _ in },
            resolveAudio: { _, _ in Data() }, play: { _ in }, stopPlayback: {}, cancelResponse: { _, _ in },
            requestSpeech: { _, _, _, _ in requests += 1; throw URLError(.notConnectedToInternet) }))
        await speech.activate(scope)
        await speech.request(messageID: "response", markdown: "Answer")
        speech.retryPlayback()
        await speech.stop()
        await Task.yield()
        XCTAssertEqual(requests, 1)
        XCTAssertEqual(speech.playbackStatus, .stopped)
        speech.reset()
    }

}
