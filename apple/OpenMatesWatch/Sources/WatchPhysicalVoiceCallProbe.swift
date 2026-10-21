// Opt-in real-device diagnostics for the genuine Watch audio/network route.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
#if DEBUG && os(watchOS)
import AVFoundation
import Foundation

struct WatchPhysicalVoiceCallProbeReceipt: Codable, Sendable {
    let schema = 1
    var ranOnPhysicalWatch = false
    var providerReadyWithCallID = false
    var manualMuteAcknowledged = false
    var endedObserved = false
    let audioReleaseVerified = false
    var inputRouteKinds: [String] = []
    var outputRouteKinds: [String] = []
    var failureCategory: String?
    // This bounded spike cannot prove Bluetooth changes, wrist-down, idle,
    // background, cellular/no-phone, or local-model resource viability.
    let physicalProof = false
    let remainingChecks = ["real_microphone_and_playback", "mute_stops_upload",
        "verified_idle_stops_upload", "wrist_down", "interruption", "bluetooth_route_change",
        "wifi_no_phone", "cellular_no_phone", "foreground_background_policy", "no_silent_keepalive",
        "memory_thermal", "privacy_and_encrypted_transcript"]
}

@MainActor
enum WatchPhysicalVoiceCallProbe {
    /// The host explicitly supplies the real production controller/scope after
    /// privacy consent and canonical chat preparation. Never run automatically.
    /// No synthetic audio, fake transport, or Simulator result can qualify.
    static func run(controller: NativeVoiceCallController, scope: NativeVoiceCallScope,
                    context: WatchChatRequestContext) async -> WatchPhysicalVoiceCallProbeReceipt {
        var receipt = WatchPhysicalVoiceCallProbeReceipt()
#if targetEnvironment(simulator)
        receipt.failureCategory = "physical_watch_required"
        return receipt
#else
        guard ProcessInfo.processInfo.arguments.contains("--watch-voice-physical-probe") else {
            receipt.failureCategory = "explicit_probe_launch_required"
            return receipt
        }
        receipt.ranOnPhysicalWatch = true
        do {
            try context.check()
            guard context.accountID == scope.accountID else { throw NativeVoiceCallError.scopeChanged }
            try await controller.start(scope: scope)
            let deadline = Date().addingTimeInterval(20)
            while Date() < deadline {
                try context.check()
                let state = await controller.snapshot()
                if state.status == .live, state.callID != nil {
                    receipt.providerReadyWithCallID = true
                    break
                }
                if state.status == .failed || state.status == .ended { throw NativeVoiceCallError.connectionLost }
                try await Task.sleep(for: .milliseconds(100))
            }
            guard receipt.providerReadyWithCallID else { throw NativeVoiceCallError.startupTimedOut }
            let route = AVAudioSession.sharedInstance().currentRoute
            receipt.inputRouteKinds = route.inputs.map { $0.portType.rawValue }
            receipt.outputRouteKinds = route.outputs.map { $0.portType.rawValue }
            await controller.setMuted(true)
            let muted = await controller.snapshot()
            receipt.manualMuteAcknowledged = muted.muted
            await controller.hangup()
            let ended = await controller.snapshot()
            receipt.endedObserved = ended.status == .ended
        } catch {
            receipt.failureCategory = (error as? NativeVoiceCallError)?.rawValue ?? "probe_failed"
            await controller.hangup()
        }
        return receipt
#endif
    }
}
#endif
