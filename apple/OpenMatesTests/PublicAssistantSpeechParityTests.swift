import XCTest
@testable import OpenMates

@MainActor
final class PublicAssistantSpeechParityTests: XCTestCase {
    private let digest = String(repeating: "a", count: 64)
    private var source: String {
        """
        // Fake property in a comment: public_speech: { "wrong": [] }
        export const fixture = {
          chat_id: "example-fixture",
          messages: [{ id: "source-uuid", role: "assistant", content: "example_chats.fixture.assistant_message_1" }],
          embeds: [{ content: `public_speech: { fake: [] }` }],
          public_speech: {
            "source-uuid": [{ segment_id: "published", sequence: 0,
              public_url: "https://public.example/reviewed.mp3?signature=a%2Bb&expires=123",
              sha256: "\(digest)", duration_seconds: 3.5, waveform: [4, 32, 80], }],
          },
        };
        """
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testStaticManifestPreservesSignedURLAndUsesExactUntranslatedIdentity() throws {
        let parsed = try XCTUnwrap(PublicAssistantSpeechManifest.parse(source))
        XCTAssertEqual(parsed.chatID, "example-fixture")
        let id = parsed.originalID(contentKey: "example_chats.fixture.assistant_message_1", role: "assistant")
        XCTAssertEqual(id, "source-uuid")
        let audio = try XCTUnwrap(parsed.segments(messageID: "source-uuid").first)
        XCTAssertEqual(PublicAssistantSpeechSegment.url(audio.publicUrl)?.absoluteString, audio.publicUrl)
        XCTAssertEqual(audio.waveform, [4, 32, 80])
        XCTAssertTrue(parsed.segments(messageID: "another-message").isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testMissingInvalidOrAmbiguousMetadataCannotExposePublicSpeak() throws {
        XCTAssertNil(PublicAssistantSpeechManifest.parse("export const fixture = { chat_id: 'example-fixture', messages: [] };"))
        let ambiguous = source.replacingOccurrences(of: "messages: [{", with: "messages: [{ id: 'duplicate', role: 'assistant', content: 'example_chats.fixture.assistant_message_1' }, {")
        let parsed = try XCTUnwrap(PublicAssistantSpeechManifest.parse(ambiguous))
        XCTAssertNil(parsed.originalID(contentKey: "example_chats.fixture.assistant_message_1", role: "assistant"))
        let malformed = source.replacingOccurrences(of: "https://public.example/reviewed.mp3?signature=a%2Bb&expires=123", with: "javascript:unsafe")
        XCTAssertTrue(try XCTUnwrap(PublicAssistantSpeechManifest.parse(malformed)).segments(messageID: "source-uuid").isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testAnonymousPlaybackNeverLoadsPreferencesGeneratesOrCancelsAndReusesPublicBytes() async {
        let initial = expectation(description: "public clip played")
        let replayed = expectation(description: "public clip replayed")
        var playCount = 0
        var resolved: [String] = []
        let scope = AssistantSpeechScope(accountID: "public", serverID: "test", chatID: "example-fixture")
        let speech = NativeAssistantSpeech(dependencies: .init(
            readPreference: { _ in XCTFail("Anonymous playback cannot read private preference"); return false },
            writePreference: { _, _ in XCTFail("Anonymous playback cannot write preference") },
            resolveAudio: { _, _ in XCTFail("Anonymous playback cannot resolve private assets"); return Data() },
            play: { _ in playCount += 1; if playCount == 1 { initial.fulfill() } else { replayed.fulfill() }; try await Task.sleep(nanoseconds: 10_000_000_000) },
            stopPlayback: {}, cancelResponse: { _, _ in XCTFail("Anonymous playback cannot send cancellation") },
            resolvePublicAudio: { segment in resolved.append(segment.publicUrl); return Data() },
            requestSpeech: { _, _, _, _ in XCTFail("Anonymous playback cannot generate provider audio") },
            waveformSamples: { _ in [4, 50, 80] }))
        speech.activatePublic(scope)
        let fixture = PublicAssistantSpeechSegment(segmentId: "public", sequence: 4,
            publicUrl: "https://public.example/published.mp3?signature=immutable", sha256: digest, durationSeconds: 4)
        await speech.playPublicExample(messageID: "source-uuid", fixtures: [fixture])
        await fulfillment(of: [initial], timeout: 2)
        speech.pause(); XCTAssertEqual(speech.playbackStatus, .paused)
        speech.select(sequence: 4)
        await fulfillment(of: [replayed], timeout: 2)
        XCTAssertEqual(resolved, [fixture.publicUrl])
        await speech.toggle()
        await speech.request(messageID: "another", markdown: "Anonymous generation must not run")
        XCTAssertFalse(speech.enabled)
        await speech.stop(); XCTAssertFalse(speech.playerVisible)
    }
    private enum SuspendedInterruption { case cancellation, reset, departure, newerActivation }

    private func checkSuspendedPublicActivation(_ interruption: SuspendedInterruption) async {
        let stopped = expectation(description: "previous controller cancellation suspended")
        var release: CheckedContinuation<Void, Never>?
        var stopCount = 0
        let runtime = AssistantSpeechAppRuntime(controllerFactory: { _ in
            NativeAssistantSpeech(dependencies: .init(
                readPreference: { _ in false }, writePreference: { _, _ in },
                resolveAudio: { _, _ in XCTFail("Stale activation resolved private audio"); return Data() },
                play: { _ in XCTFail("Stale activation started playback") }, stopPlayback: {}, cancelResponse: { _, _ in },
                resolvePublicAudio: { _ in XCTFail("Stale activation fetched public audio"); return Data() }))
        }, stopController: { _ in
            stopCount += 1
            if stopCount == 1 {
                await withCheckedContinuation { continuation in
                    release = continuation; stopped.fulfill()
                }
            }
        })
        _ = await runtime.activate(chatID: "previous", supported: false, ownerID: UUID())
        let target = runtime.controller(for: "public-target")
        let fixture = PublicAssistantSpeechSegment(segmentId: "public", sequence: 0,
            publicUrl: "https://public.example/reviewed.mp3", sha256: digest, durationSeconds: 4)
        let pending = Task { @MainActor in
            await runtime.playPublicExample(chatID: "public-target", messageID: "source-uuid", fixtures: [fixture])
        }
        await fulfillment(of: [stopped], timeout: 2)
        switch interruption {
        case .cancellation: pending.cancel()
        case .reset: runtime.reset()
        case .departure: runtime.stopPublic(chatID: "public-target")
        case .newerActivation:
            _ = await runtime.activate(chatID: "newer", supported: false, ownerID: UUID())
        }
        release?.resume()
        await pending.value
        XCTAssertNil(target.scope, "Suspended public activation must not resurrect its scope")
        XCTAssertFalse(target.playerVisible)
        runtime.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testCancelledPublicActivationCannotResumeAfterSuspendedCancellation() async {
        await checkSuspendedPublicActivation(.cancellation)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testResetPublicActivationCannotResumeAfterSuspendedCancellation() async {
        await checkSuspendedPublicActivation(.reset)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testDepartedPublicViewCannotResumeAfterSuspendedCancellation() async {
        await checkSuspendedPublicActivation(.departure)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testNewerActivationSupersedesSuspendedPublicActivation() async {
        await checkSuspendedPublicActivation(.newerActivation)
    }

}
