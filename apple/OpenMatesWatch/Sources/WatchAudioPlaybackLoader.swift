// Web sources: frontend/packages/ui/src/components/embeds/audio/RecordingEmbedPreview.svelte
//              frontend/packages/ui/src/components/embeds/audio/RecordingEmbedFullscreen.svelte
//              frontend/packages/ui/src/components/embeds/audio/audioEmbedCrypto.ts
// Read-only Watch audio playback. Decrypted bytes remain in memory; no URLs,
// key material, transcripts or binary payloads enter diagnostics or disk.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.embeds.read-only-fullscreen
import SwiftUI
import AVFoundation

@MainActor
final class WatchAudioPlaybackLoader: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published private(set) var playing = false
    @Published private(set) var loading = false
    @Published private(set) var failed = false
    private static weak var current: WatchAudioPlaybackLoader?
    private var player: AVAudioPlayer?
    private var task: Task<Void, Never>?
    private var generation = UUID()

    func toggle(load: @escaping () async throws -> Data) {
        if playing || loading { stop(); return }
        Self.current?.stop(); stop(); Self.current = self
        failed = false; loading = true
        let attempt = generation
        task = Task { [weak self] in
            do {
                let data = try await load()
                try Task.checkCancellation()
                guard let self, self.generation == attempt else { return }
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.playback, mode: .default, policy: .longFormAudio)
                guard try await session.activate(options: []) else { throw URLError(.cannotDecodeContentData) }
                // watchOS activation is asynchronous and may show its route
                // chooser. A cancelled source must never start after it returns.
                guard self.generation == attempt, !Task.isCancelled else {
                    if Self.current == nil { try? session.setActive(false, options: .notifyOthersOnDeactivation) }
                    return
                }
                let player = try AVAudioPlayer(data: data)
                player.delegate = self; player.prepareToPlay()
                guard player.play() else { throw URLError(.cannotDecodeContentData) }
                self.player = player; self.playing = player.isPlaying; self.loading = false
            } catch is CancellationError { }
            catch {
                guard let self, self.generation == attempt else { return }
                self.stop(); self.failed = true
            }
        }
    }
    func stop() {
        generation = UUID(); task?.cancel(); task = nil
        player?.stop(); player = nil; playing = false; loading = false
        if Self.current === self {
            Self.current = nil
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let identity = ObjectIdentifier(player)
        Task { @MainActor [weak self] in
            guard let self, let current = self.player, ObjectIdentifier(current) == identity else { return }
            self.stop()
        }
    }
}

struct WatchAudioPlaybackControl: View {
    let model: WatchEmbedPreviewModel
    let loadAudio: ((WatchEmbedPreviewModel) async throws -> Data)?
    let fullscreen: Bool
    @StateObject private var playback = WatchAudioPlaybackLoader()
    @Environment(\.scenePhase) private var scenePhase
    private var playable: Bool { model.detailContent.audioData != nil || model.detailContent.audioSource != nil }
    private var prefix: String { fullscreen ? "watch-audio-fullscreen" : "watch-audio-preview" }
    var body: some View {
        VStack(spacing: .spacing1) {
            if playable {
                Button {
                    playback.toggle {
                        // Runtime loader validates current account/chat even for
                        // retained local bytes. Direct model bytes serve isolated
                        // leaf fixtures only when no runtime is mounted.
                        if let loadAudio { return try await loadAudio(model) }
                        if let data = model.detailContent.audioData { return data }
                        throw CancellationError()
                    }
                } label: {
                    Icon(playback.playing || playback.loading ? "stop_video" : "play", size: 22)
                        .frame(width: 44, height: 44)
                        .background(Color.grey0, in: Circle()).foregroundStyle(Color.fontPrimary)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier(prefix + "-playback")
                .accessibilityLabel(WatchLocalization.text(playback.playing || playback.loading ? "common.stop" : "audio.play"))
                .accessibilityValue(playback.playing ? "playing" : playback.loading ? "loading" : "stopped")
                if playback.loading {
                    ProgressView().accessibilityLabel(WatchLocalization.text("embeds.watch_audio_loading"))
                        .accessibilityIdentifier(prefix + "-loading")
                }
                if playback.failed {
                    Text(WatchLocalization.text("embeds.watch_audio_playback_failed")).font(.omSmall)
                        .accessibilityIdentifier(prefix + "-error")
                }
            } else if fullscreen {
                Text(WatchLocalization.text("embeds.watch_audio_metadata_unavailable")).font(.omSmall)
                    .accessibilityIdentifier(prefix + "-metadata-unavailable")
            }
        }
        .onDisappear { playback.stop() }
        .onChange(of: scenePhase) { _, phase in if phase != .active { playback.stop() } }
        .onChange(of: model.id) { _, _ in playback.stop() }
        .onChange(of: model.detailContent.audioSource) { _, _ in playback.stop() }
    }
}
