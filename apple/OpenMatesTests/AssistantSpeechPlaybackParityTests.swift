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
}
