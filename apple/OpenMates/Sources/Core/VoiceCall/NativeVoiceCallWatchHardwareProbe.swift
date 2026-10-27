// Genuine foreground hardware/network stage probe; no provider start or media upload.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.audio.single-owner, video-call.lifecycle.recovery-and-billing
#if os(watchOS)
import AVFoundation
import Foundation
import WatchKit

struct NativeVoiceCallWatchHardwareReceipt: Codable, Sendable {
    let schemaVersion = 1
    var physicalWatch = false
    var foreground = false
    var savedProcessingConsent = false
    var microphoneFramesObserved = false
    var audioSessionActivated = false
    var hardwareSampleRate: Double = 0
    var inputRouteKinds: [String] = []
    var outputRouteKinds: [String] = []
    var authenticatedSocketPong = false
    var manualMuteStopsForwardedFrames = false
    var ownedAudioReleased = false
    // Hash of actual port kinds and device UIDs, never a qualification flag.
    var observedRouteFingerprint: String?
    var failureCategory: String?
    // These are narrow real stages, never a completed physical call claim.
    let providerStarted = false
    let microphoneUploaded = false
    let physicalProof = false
    let pending = ["provider_ready_and_real_speech", "24k_playback_heard", "mute_server_end_marker",
        "five_second_energy_idle_and_prespeech_resume", "wrist_down", "bluetooth_route_change",
        "interruption", "wifi_no_phone", "cellular_no_phone", "background_policy", "memory_thermal"]
}

@MainActor
enum NativeVoiceCallWatchHardwareProbe {
    /// Invoke only through the root's explicit development-profile probe action on a physical
    /// Watch. Reads saved consent; it never records consent or starts a provider.
    static func run(auth: WatchAuthStore, context: WatchChatRequestContext,
                    chatID: String, userInitiated: Bool) async -> NativeVoiceCallWatchHardwareReceipt {
        var receipt = NativeVoiceCallWatchHardwareReceipt()
#if targetEnvironment(simulator)
        receipt.failureCategory = "physical_watch_required"
        return receipt
#else
        guard userInitiated, !Task.isCancelled, auth.state == .authenticated,
              context.profile == .development, ServerProfile.current() == .development,
              WKExtension.shared().applicationState == .active else {
            receipt.failureCategory = "explicit_foreground_probe_required"
            return receipt
        }
        receipt.physicalWatch = true; receipt.foreground = true
        let audio = NativeVoiceCallWatchAudio(ownership: .shared, eligible: {
            userInitiated && !Task.isCancelled && auth.state == .authenticated &&
                context.profile == .development && ServerProfile.current() == .development &&
                (try? context.check()) != nil && WKExtension.shared().applicationState == .active
        }, inputIdle: { _ in })
        return await withTaskCancellationHandler(operation: {
        var socket: URLSessionWebSocketTask?
        var session: URLSession?
        do {
            try context.check()
            guard let owner = context.accountID, auth.currentUser?.id == owner, auth.isVerifiedOnline,
                  let token = auth.webSocketToken, UUID(uuidString: chatID) != nil else { throw NativeVoiceCallError.scopeChanged }
            let response = try await APIClient.shared.requestForVerifiedWatchSession(.get,
                path: "/v1/settings/voice-processing-ack", serverProfile: context.profile,
                validate: { try context.check() })
            let ack = try JSONDecoder().decode(NativeVoiceCallFrame.self, from: response)
            guard ack["version"]?.number == 2, ack["acknowledged"]?.bool == true,
                  (ack["acknowledged_at"]?.number ?? 0) > 0 else { throw NativeVoiceCallError.consentRequired }
            receipt.savedProcessingConsent = true
            let scope = NativeVoiceCallScope(accountID: owner, profileID: context.profile.id,
                workspaceGeneration: UUID(), chatID: chatID, mateCategory: "general_knowledge")
            try await audio.reserve(scope: scope)
            try await audio.start(input: { _ in }, failure: { [weak audio] _ in await audio?.stop() })
            try await Task.sleep(for: .milliseconds(700))
            try context.check()
            let hardware = audio.diagnostics
            receipt.audioSessionActivated = hardware.activated
            receipt.hardwareSampleRate = hardware.hardwareSampleRate
            receipt.observedRouteFingerprint = WatchVoiceEvaluationRoute.fingerprint
            receipt.inputRouteKinds = hardware.inputRouteKinds
            receipt.outputRouteKinds = hardware.outputRouteKinds
            receipt.microphoneFramesObserved = hardware.capturedFrames > 0
            guard receipt.microphoneFramesObserved, !hardware.ownershipReleased,
                  WKExtension.shared().applicationState == .active else { throw NativeVoiceCallError.audioUnavailable }
            let configuration = URLSessionConfiguration.ephemeral
            configuration.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
            configuration.httpShouldSetCookies = true
            let network = URLSession(configuration: configuration)
            session = network
            let authentication = NativeVoiceCallAuthentication(apiBaseURL: context.profile.apiBaseURL,
                webOrigin: context.profile.webBaseURL.absoluteString,
                sessionID: WatchCompatibleSession.nativeSessionId, webSocketToken: token,
                nativeHeaders: APIClient.nativeClientHeaders)
            let connection = network.webSocketTask(with: try authentication.request())
            socket = connection; connection.resume()
            // Ping checks genuine low-level admission under the active route.
            // No 'start', mic_audio or silent payload is sent; provider stays closed.
            try await withThrowingTaskGroup(of: Void.self) { group in
                group.addTask {
                    try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, any Error>) in
                        connection.sendPing { error in
                            if let error { continuation.resume(throwing: error) }
                            else { continuation.resume() }
                        }
                    }
                }
                group.addTask {
                    try await Task.sleep(for: .seconds(5))
                    connection.cancel(with: .goingAway, reason: nil)
                    throw NativeVoiceCallError.connectionLost
                }
                _ = try await group.next()
                group.cancelAll()
            }
            try Task.checkCancellation()
            try context.check()
            guard WKExtension.shared().applicationState == .active, !audio.diagnostics.ownershipReleased
            else { throw NativeVoiceCallError.audioUnavailable }
            receipt.authenticatedSocketPong = true
            await audio.setMicrophoneEnabled(false)
            let frames = audio.diagnostics.capturedFrames
            try await Task.sleep(for: .milliseconds(250))
            receipt.manualMuteStopsForwardedFrames = audio.diagnostics.capturedFrames == frames
        } catch {
            receipt.failureCategory = (error as? NativeVoiceCallError)?.rawValue ?? "audio_or_network_unavailable"
        }
        socket?.cancel(with: .normalClosure, reason: nil); session?.invalidateAndCancel()
        await audio.stop()
        receipt.ownedAudioReleased = audio.diagnostics.ownershipReleased && WatchAudioOwnership.shared.currentLease == nil
        return receipt
        }, onCancel: { Task { @MainActor in await audio.stop() } })
#endif
    }
}
#endif
