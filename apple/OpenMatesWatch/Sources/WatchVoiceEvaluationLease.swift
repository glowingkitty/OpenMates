// Physical-only diagnostic authorization from this attempt's actual hardware observation.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy, video-call.privacy.first-call-warning, video-call.audio.single-owner
#if os(watchOS)
import AVFoundation
import CryptoKit
import Foundation
import WatchKit

@MainActor
enum WatchVoiceEvaluationRoute {
    static var fingerprint: String {
        let route = AVAudioSession.sharedInstance().currentRoute
        let identity = route.inputs.map { "in:" + $0.portType.rawValue + ":" + $0.uid } +
            route.outputs.map { "out:" + $0.portType.rawValue + ":" + $0.uid }
        return SHA256.hash(data: Data(identity.joined(separator: "\n").utf8))
            .map { String(format: "%02x", $0) }.joined()
    }
}

@MainActor
final class WatchVoiceEvaluationLease {
    let context: WatchChatRequestContext
    let chatID: String
    let hardwareReceipt: NativeVoiceCallWatchHardwareReceipt
    private weak var authOwner: WatchAuthStore?
    private weak var runtimeOwner: WatchChatRuntime?
    private var policy: WatchVoiceEvaluationPolicy
    private let currentBinding: @MainActor () throws -> WatchVoiceEvaluationBinding
    // No public/internal constructor, decoder, launch flag, injected probe or
    // receipt-import API can manufacture this capability.
    private init(auth: WatchAuthStore, runtime: WatchChatRuntime, context: WatchChatRequestContext, chatID: String,
                 receipt: NativeVoiceCallWatchHardwareReceipt, binding: WatchVoiceEvaluationBinding,
                 current: @escaping @MainActor () throws -> WatchVoiceEvaluationBinding) {
        authOwner = auth; runtimeOwner = runtime
        self.context = context; self.chatID = chatID; hardwareReceipt = receipt
        policy = WatchVoiceEvaluationPolicy(binding: binding, observedAt: ProcessInfo.processInfo.systemUptime)
        currentBinding = current
    }
    static func observe(auth: WatchAuthStore, runtime: WatchChatRuntime, chatID: String,
                        attemptID: UUID) async throws -> WatchVoiceEvaluationLease {
#if targetEnvironment(simulator)
        throw NativeVoiceCallError.unsupportedTransport
#else
        let request = try runtime.voiceCallContext(for: chatID)
        let current: @MainActor () throws -> WatchVoiceEvaluationBinding = { [weak auth, weak runtime] in
            try Task.checkCancellation(); try request.check()
            guard let auth, let runtime, !runtime.isStopped, !runtime.isPreviewFixture,
                  auth.state == .authenticated, auth.isVerifiedOnline,
                  let owner = request.accountID, auth.currentUser?.id == owner,
                  request.profile == .development, ServerProfile.current() == .development,
                  runtime.selectedChatId == chatID, WKExtension.shared().applicationState == .active else {
                throw NativeVoiceCallError.scopeChanged
            }
            return WatchVoiceEvaluationBinding(accountID: owner, profile: request.profile,
                accountGeneration: request.accountGeneration, chatID: chatID,
                attemptID: attemptID, routeFingerprint: WatchVoiceEvaluationRoute.fingerprint)
        }
        _ = try current()
        let receipt = await NativeVoiceCallWatchHardwareProbe.run(auth: auth, context: request,
            chatID: chatID, userInitiated: true)
        try Task.checkCancellation()
        let binding = try current()
        guard receipt.failureCategory == nil, receipt.physicalWatch, receipt.foreground,
              receipt.savedProcessingConsent, receipt.microphoneFramesObserved,
              receipt.audioSessionActivated, receipt.authenticatedSocketPong,
              receipt.manualMuteStopsForwardedFrames, receipt.ownedAudioReleased,
              receipt.observedRouteFingerprint == binding.routeFingerprint,
              WatchAudioOwnership.shared.currentLease == nil else { throw NativeVoiceCallError.audioUnavailable }
        return WatchVoiceEvaluationLease(auth: auth, runtime: runtime, context: request, chatID: chatID, receipt: receipt,
            binding: binding, current: current)
#endif
    }
    func checkOwner(auth: WatchAuthStore, runtime: WatchChatRuntime) throws {
        guard authOwner === auth, runtimeOwner === runtime else { throw NativeVoiceCallError.scopeChanged }
    }
    var canStart: Bool {
        guard let current = try? currentBinding() else { return false }
        return policy.permitsStart(current: current, now: ProcessInfo.processInfo.systemUptime)
    }
    func consume(attemptID: UUID) throws {
        let current = try currentBinding()
        guard current.attemptID == attemptID else { revoke(); throw NativeVoiceCallError.scopeChanged }
        try policy.consume(current: current, now: ProcessInfo.processInfo.systemUptime)
    }
    func checkExecution() throws {
        let current = try currentBinding()
        guard policy.permitsExecution(current: current, now: ProcessInfo.processInfo.systemUptime)
        else { throw NativeVoiceCallError.scopeChanged }
    }
    var permitsCurrentCapture: Bool { (try? checkExecution()) != nil }
    func revoke() { policy.revoke() }
}
#endif
