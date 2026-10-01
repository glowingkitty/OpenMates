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
