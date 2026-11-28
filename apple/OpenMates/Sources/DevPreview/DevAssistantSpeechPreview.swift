#if DEBUG
import SwiftUI

// Web source: AssistantSpeechPlayer.preview.ts and AssistantSpeechPlayer.svelte.
// Isolated fixture transport: no account, persistence, network or audio session.
struct DevAssistantSpeechPreview: View {
    let variant: String
    @StateObject private var speech: NativeAssistantSpeech
    init(variant: String = "default") {
        self.variant = variant
        var controller: NativeAssistantSpeech?
        let dependencies = NativeAssistantSpeech.Dependencies(
            readPreference: { _ in true }, writePreference: { _, _ in },
            resolveAudio: { _, _ in Data() },
            play: { _ in try await Task.sleep(nanoseconds: 3_600_000_000_000) },
            stopPlayback: {}, cancelResponse: { _, _ in },
            resolveAcknowledgement: { _, _ in Data() },
            resolvePublicAudio: { _ in Data() },
            requestSpeech: { scope, id, action, parts in
                if action == "generate" { try await Task.sleep(nanoseconds: 3_000_000_000) }
                let segments = parts.compactMap { part -> AssistantSpeechSegment? in
                    guard let index = part["sequence"] as? Int else { return nil }
                    return .init(segment_id: "segment-\(index)", sequence: index,
                        status: index == 2 && action != "generate" ? "registered" : "ready", generated_asset_id: "asset-\(index)")
                }
                controller?.receive(.init(chat_id: scope.chatID, message_id: id, status: "accepted",
                    segment_id: nil, sequence: nil, generated_asset_id: nil, segments: segments), in: scope)
            }, waveformSamples: { _ in [32, 58, 82, 44, 72, 96, 54, 76, 38, 68, 88, 48] })
        let value = NativeAssistantSpeech(dependencies: dependencies)
        controller = value
        _speech = StateObject(wrappedValue: value)
    }
    private static let publicFixtures: [PublicAssistantSpeechSegment] = [
        .init(segmentId: "public-first", sequence: 0, publicUrl: "https://example.org/reviewed.mp3?signature=fixture",
              sha256: String(repeating: "0", count: 64), durationSeconds: 4, waveform: [32, 58, 82, 44, 72, 96]),
        .init(segmentId: "public-second", sequence: 1, publicUrl: "https://example.org/reviewed-next.mp3",
              sha256: String(repeating: "1", count: 64), durationSeconds: 4, waveform: [38, 68, 88, 48])
    ]
    var body: some View {
        GeometryReader { geometry in
            VStack {
                if variant == "publicExample" {
                    HStack(spacing: .spacing2) {
                        Text("Reviewed public example").font(.omSmall)
                        AssistantMessageSpeakButton {
                            Task { await speech.playPublicExample(messageID: "preview-public-message", fixtures: Self.publicFixtures) }
                        }
                    }.accessibilityElement(children: .contain).accessibilityIdentifier("public-speech-fixture")
                }
                if speech.playerVisible { AssistantSpeechPlayerView(speech: speech, viewportWidth: geometry.size.width) }
                Spacer()
            }
        }.task {
            let scope = AssistantSpeechScope(accountID: "preview", serverID: "preview", chatID: "preview-chat")
            if variant == "publicExample" {
                speech.activatePublic(scope)
                return
            }
            await speech.activate(scope)
            if variant == "passiveConfirmation" {
                speech.expectResponse("preview-message", in: scope)
                let segment = AssistantSpeechSegment(segment_id: "confirmation", sequence: -1, status: "ready",
                    generated_asset_id: nil, kind: "acknowledgement", audio_url: "/audio/assistant-acknowledgements/preview.mp3")
                speech.receive(.init(chat_id: scope.chatID, message_id: "preview-message", status: "ready",
                    segment_id: nil, sequence: nil, generated_asset_id: nil, segments: [segment]), in: scope)
                return
            }
            await speech.request(messageID: "preview-message", markdown: "# Short answer\n\n# Key considerations\n\n# Optimization\n\n# Implementation", mateName: "Sophia", mateCategory: "software_development")
            speech.select(sequence: 1)
            if variant == "paused" { speech.pause() }
            if variant == "failed" {
                speech.receive(.init(chat_id: scope.chatID, message_id: "preview-message", status: "error",
                    segment_id: nil, sequence: nil, generated_asset_id: nil, segments: nil), in: scope)
            }
            if variant == "awaitingAudio" { speech.select(sequence: 2) }
        }
    }
}
#endif

#if DEBUG && os(iOS)
import AVFoundation

/// Starts the production call audio (`NativeVoiceCallAppleAudio`) on the device
/// microphone and speaker with no account or server: permission, session,
/// voice-processing engine, microphone and playback taps, one played buffer.
/// AVFoundation runs those callbacks on its audio threads, which is where the
/// call crashed on start; the status reports how many callbacks really ran.
struct DevVoiceCallAudioEnginePreview: View {
    @State private var status = "starting"
    @State private var audio: NativeVoiceCallAppleAudio?
    private let counter = DevVoiceCallAudioCounter()

    var body: some View {
        VStack(spacing: .spacing4) {
            Text(status).font(.omSmall)
                .accessibilityIdentifier("voice-call-audio-engine-status")
            Text("captured \(counter.capturedChunks)").font(.omSmall)
                .accessibilityIdentifier("voice-call-audio-engine-captured")
        }
        .task {
            let audio = NativeVoiceCallAppleAudio(invalidated: {})
            self.audio = audio
            let scope = NativeVoiceCallScope(accountID: "preview", profileID: "preview",
                                             workspaceGeneration: UUID(), chatID: "preview-call",
                                             mateCategory: "software_development")
            var stage = "reserve"
            do {
                try await audio.reserve(scope: scope)
                stage = "start"
                let counter = counter
                try await audio.start(input: { _ in await counter.capture() },
                                      failure: { error in await counter.fail(error) })
                stage = "engine"
                // The engine can report running a moment after start(); wait for
                // it (or the first microphone buffer) before playing.
                for _ in 0..<30 where !audio.isEngineRunning && counter.capturedChunks == 0 {
                    try await Task.sleep(nanoseconds: 100_000_000)
                }
                guard audio.isEngineRunning else { throw NativeVoiceCallError.audioUnavailable }
                stage = "play"
                // 0.25 s of silence at 24 kHz exercises playback and its completion handler.
                try audio.play(Data(count: 24_000 / 2), sampleRate: 24_000)
                stage = "callback"
                status = "running"
                // The played-back completion runs on an audio thread and hops to
                // the main actor; it empties the playback queue when it ran.
                for _ in 0..<40 {
                    try await Task.sleep(nanoseconds: 100_000_000)
                    if let failure = counter.failure { status = "failed callback \(failure.rawValue)"; break }
                    if audio.smokeDiagnostics.hasSuffix("queued=0") { break }
                }
                if status == "running" {
                    let playedBack = audio.smokeDiagnostics.hasSuffix("queued=0")
                    // Played-back completions need a rendering output device; a
                    // hosted CI virtual machine can have none, which is reported.
                    let outputs = AVAudioSession.sharedInstance().currentRoute.outputs.count
                    status = "running \(counter.capturedChunks > 0 ? "with" : "without") microphone input, " +
                        "outputs \(outputs), playback \(playedBack ? "completed" : "pending")"
                }
            } catch {
                let code = (error as? NativeVoiceCallError)?.rawValue ?? "\(type(of: error)) \((error as NSError).code)"
                status = "failed \(stage) \(code) \(audio.smokeDiagnostics)"
            }
            audio.stop()
        }
    }
}

@MainActor
private final class DevVoiceCallAudioCounter: Sendable {
    private(set) var capturedChunks = 0
    private(set) var failure: NativeVoiceCallError?
    func capture() { capturedChunks += 1 }
    func fail(_ error: NativeVoiceCallError) { failure = error }
}
#endif
