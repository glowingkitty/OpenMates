// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity
import Foundation
import MediaPlayer

// Web: assistantSpeechQueue.ts — best-effort OS media play/pause/chapter controls.
// Lock-screen metadata describes the control, never private response content.
@MainActor
final class AssistantSpeechSystemMedia {
    private var targets: [(MPRemoteCommand, Any)] = []
    private weak var speech: NativeAssistantSpeech?
    func activate(_ speech: NativeAssistantSpeech) {
        self.speech = speech
        guard targets.isEmpty else { return }
        let center = MPRemoteCommandCenter.shared()
        register(center.playCommand) { $0.play() }
        register(center.pauseCommand) { $0.pause() }
        register(center.togglePlayPauseCommand) { if $0.canPause { $0.pause() } else { $0.play() } }
        register(center.previousTrackCommand) { $0.previous() }
        register(center.nextTrackCommand) { $0.next() }
        register(center.stopCommand) { value in Task { await value.stop() } }
    }
    private func register(_ command: MPRemoteCommand, action: @escaping @MainActor (NativeAssistantSpeech) -> Void) {
        let target = command.addTarget { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, let speech, speech.playerVisible else { return }
                action(speech)
            }
            return .success
        }
        targets.append((command, target))
    }
    func refresh(_ speech: NativeAssistantSpeech) {
        guard self.speech === speech else { return }
        let center = MPRemoteCommandCenter.shared()
        center.playCommand.isEnabled = speech.playerVisible && !speech.canPause
        center.pauseCommand.isEnabled = speech.playerVisible && speech.canPause
        center.togglePlayPauseCommand.isEnabled = speech.playerVisible
        center.previousTrackCommand.isEnabled = speech.playerVisible && speech.hasPrevious
        center.nextTrackCommand.isEnabled = speech.playerVisible && speech.hasNext
        center.stopCommand.isEnabled = speech.playerVisible
        MPNowPlayingInfoCenter.default().nowPlayingInfo = speech.playerVisible ? [
            MPMediaItemPropertyTitle: "Voice response",
            MPMediaItemPropertyArtist: speech.mateName,
            MPNowPlayingInfoPropertyPlaybackRate: speech.playbackStatus == .playing ? 1.25 : 0
        ] : nil
    }
    func reset() {
        speech = nil
        for (command, target) in targets { command.removeTarget(target); command.isEnabled = false }
        targets.removeAll()
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
    }
}
