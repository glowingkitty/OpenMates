// Explicit development-only physical call evaluation; ordinary phone admission is unchanged.
// Web: frontend/packages/ui/src/components/EnterMessage.svelte; styles/chat.css
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy, video-call.privacy.first-call-warning, video-call.audio.single-owner,
// video-call.audio.automatic-idle, video-call.lifecycle.recovery-and-billing,
// video-call.chat.fixed-binding, video-call.chat.skill-integration
import AVFoundation
import Foundation
import SwiftUI

@MainActor
final class WatchVoiceEvaluationOwner: ObservableObject {
    @Published private(set) var chosenChatID: String?
    @Published private(set) var savedConsent = false
    @Published private(set) var hardwareReady = false
    @Published private(set) var busy = false
    @Published private(set) var stopping = false
    @Published private(set) var failed = false
    @Published private(set) var snapshot = NativeVoiceCallSnapshot()
    @Published private(set) var playedFrames = 0
    @Published private(set) var heardReply = false
    @Published private(set) var finished = false
    private let auth: WatchAuthStore
    private let runtime: WatchChatRuntime
    private let consent: WatchVoiceCallConsent
    let tools = WatchVoiceCallToolCoordinator()
    let memory = WatchVoiceCallMemoryPermission()
    private var attemptID = UUID()
    private var lease: WatchVoiceEvaluationLease?
    private var factory: NativeVoiceCallWatchFactory?
    private var work: Task<Void, Never>?
    private var monitor: Task<Void, Never>?
    private var observers: [NSObjectProtocol] = []
    private var departed = false
    private var observedHardware: NativeVoiceCallWatchHardwareReceipt?
    private var paidAttemptID: UUID?
    private var providerReadyObserved = false
    private var lastServerListening = false
    private var serverListeningStoppedWhileMuted = false
    private var idleWithServerPauseObserved = false
    private var userFinalIDs = Set<String>()
    private var assistantFinalIDs = Set<String>()

    init(auth: WatchAuthStore, runtime: WatchChatRuntime, consent: WatchVoiceCallConsent) {
        self.auth = auth; self.runtime = runtime; self.consent = consent
    }
    var ownsCall: Bool { factory != nil }
    var blocksNewWork: Bool { busy || stopping }
    var canStart: Bool { !blocksNewWork && !ownsCall && lease?.canStart == true && hardwareReady }
    private func context() throws -> WatchChatRequestContext {
        guard !departed, auth.state == .authenticated, auth.isVerifiedOnline,
              ServerProfile.current() == .development, let chosenChatID,
              runtime.selectedChatId == chosenChatID else { throw NativeVoiceCallError.scopeChanged }
        let request = try runtime.voiceCallContext(for: chosenChatID)
        guard request.profile == .development, request.accountID == auth.currentUser?.id else {
            throw NativeVoiceCallError.scopeChanged
        }
        try request.check(); return request
    }
    func activate() {
        guard monitor == nil, !departed else { return }
        observers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification,
            object: nil, queue: .main) { [weak self] notification in
                // Category changes from our own real capture setup are expected.
                // Device arrival/departure invalidates this attempt permanently.
                let reason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
                if reason == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue ||
                    reason == AVAudioSession.RouteChangeReason.newDeviceAvailable.rawValue ||
                    reason == AVAudioSession.RouteChangeReason.override.rawValue {
                    Task { @MainActor in await self?.invalidate() }
                }
            })
        observers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification,
            object: nil, queue: .main) { [weak self] _ in Task { @MainActor in await self?.invalidate() } })
        monitor = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
                guard let self, !self.departed else { return }
                // Normal hangup may be draining an already admitted encrypted
                // artifact; it retains the consumed lease until that drain ends.
                if self.stopping { continue }
                if let lease = self.lease {
                    let valid = self.ownsCall ? lease.permitsCurrentCapture : lease.canStart
                    if !valid { await self.invalidate(); continue }
                }
                if let factory = self.factory {
                    if self.snapshot.status == .ended || self.snapshot.status == .failed {
                        await self.stop(revokeFirst: false); continue
                    }
                    self.playedFrames = factory.evaluationAudioDiagnostics()?.playedFrames ?? 0
                }
            }
        }
    }
    private func perform(_ operation: @escaping @MainActor () async throws -> Void) {
        guard !blocksNewWork, !departed, !ownsCall else { return }
        busy = true; failed = false
        work = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.busy = false; self.work = nil }
            do { try await operation() }
            catch { if !Task.isCancelled, !self.departed { self.failed = true } }
        }
    }
    /// Explicit user choice always creates a fresh disposable personal chat.
    /// Existing selected drafts remain under their normal runtime ownership.
    func chooseNewChat() {
        perform { [self] in
            guard auth.state == .authenticated, auth.isVerifiedOnline,
                  ServerProfile.current() == .development else { throw NativeVoiceCallError.scopeChanged }
            lease?.revoke(); lease = nil; hardwareReady = false; savedConsent = false
            attemptID = UUID(); finished = false; heardReply = false; playedFrames = 0
            observedHardware = nil; paidAttemptID = nil
            providerReadyObserved = false; lastServerListening = false
            serverListeningStoppedWhileMuted = false; idleWithServerPauseObserved = false
            userFinalIDs.removeAll(); assistantFinalIDs.removeAll()
            let previous = runtime.selectedChatId
            await runtime.createNewChat()
            try Task.checkCancellation()
            guard let created = runtime.selectedChatId, created != previous else { throw NativeVoiceCallError.contextUnavailable }
            chosenChatID = created
            _ = try context()
        }
    }
    func reviewConsent() {
        perform { [self] in
            let request = try context()
            try await NativeVoiceCallWatchEnvironment.ensureSavedConsent(auth: auth, request: request,
                decision: { [weak consent] in await consent?.request() ?? false })
            try Task.checkCancellation(); try request.check(); _ = try context()
            savedConsent = true
        }
    }
    func checkHardware() {
        perform { [self] in
            guard savedConsent, let chosenChatID else { throw NativeVoiceCallError.consentRequired }
            _ = try context(); lease?.revoke(); lease = nil; hardwareReady = false
            let observedAttempt = attemptID
            let observed = try await WatchVoiceEvaluationLease.observe(auth: auth, runtime: runtime,
                chatID: chosenChatID, attemptID: observedAttempt)
            guard !Task.isCancelled, !departed, attemptID == observedAttempt else {
                observed.revoke(); throw CancellationError()
            }
            _ = try context(); lease = observed; observedHardware = observed.hardwareReceipt
            hardwareReady = observed.canStart
        }
    }
    /// Only this separately labelled user action consumes the volatile offer.
    /// Constructor/start exceptions terminate the actual owner with no reconnect.
    func startPaidEvaluation() {
        guard canStart, let lease else { return }
        hardwareReady = false; busy = true; failed = false; finished = false
        work = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.busy = false; self.work = nil }
            do {
                _ = try self.context()
                let runningAttempt = self.attemptID
                self.paidAttemptID = runningAttempt
                let factory = try NativeVoiceCallWatchFactory.developmentEvaluation(auth: self.auth,
                    runtime: self.runtime, lease: lease, attemptID: self.attemptID,
                    event: { [weak self] event in
                        guard let self, self.attemptID == runningAttempt else { return }
                        await self.receive(event)
                    })
                self.factory = factory
                factory.bindTools(to: self.tools, memory: self.memory)
                try await factory.startDevelopmentEvaluation()
            } catch {
                self.failed = !Task.isCancelled
                await self.stop(revokeFirst: true)
            }
        }
    }
    private func receive(_ event: NativeVoiceCallEvent) async {
        switch event {
        case .state(let value):
            if value.status == .live, value.callID != nil { providerReadyObserved = true }
            if lastServerListening, !value.inputListening, value.muted { serverListeningStoppedWhileMuted = true }
            if lastServerListening, value.inputIdle, !value.inputListening, value.status == .live { idleWithServerPauseObserved = true }
            lastServerListening = value.inputListening
            snapshot = value
            if value.status == .failed { failed = true }
        case .transcript(let value):
            if value.final, value.role == .user, userFinalIDs.count < 256 { userFinalIDs.insert(value.messageID) }
            if value.final, value.role == .assistant, assistantFinalIDs.count < 256 { assistantFinalIDs.insert(value.messageID) }
        default: break
        }
        await tools.receive(event)
    }
    func toggleMute() { guard let factory else { return }; Task { await factory.controller.setMuted(!snapshot.muted) } }
    func confirmHeardReply() { if ownsCall, playedFrames > 0 { heardReply = true } }
    func hangup() { Task { await stop(revokeFirst: false) } }
    func invalidate() async {
        attemptID = UUID(); hardwareReady = false; savedConsent = false
        tools.invalidateOwner(); memory.invalidate()
        lease?.revoke(); lease = nil; work?.cancel(); consent.cancel()
        await stop(revokeFirst: true)
    }
    private func stop(revokeFirst: Bool) async {
        guard !stopping else { return }
        guard let departedFactory = factory else { lease?.revoke(); return }
        stopping = true
        defer { stopping = false }
        factory = nil; hardwareReady = false
        if revokeFirst { tools.invalidateOwner(); memory.invalidate(); lease?.revoke() }
        await departedFactory.controller.hangup()
        if !revokeFirst { await tools.finishAdmittedArtifacts() }
        await departedFactory.stop()
        lease?.revoke(); lease = nil
        playedFrames = departedFactory.evaluationAudioDiagnostics()?.playedFrames ?? playedFrames
        finished = true
        // Counters/flags only. External TestFlight build/source evidence remains
        // necessary; a successful partial receipt never enables product calls.
        struct Receipt: Encodable {
            let schema = 1
            let version: String
            let build: String
            let attemptID: String?
            let hardwareObservation: NativeVoiceCallWatchHardwareReceipt?
            let physicalProof = false
            let evaluationOnly = true
            let playedFrames: Int
            let heardReply: Bool
            let capturedFrames: Int
            let audioReleased: Bool
            let failureCategory: String?
            let providerReadyObserved: Bool
            let finalUserMessages: Int
            let finalAssistantMessages: Int
            let serverListeningStoppedWhileMuted: Bool
            let idleWithServerPauseObserved: Bool
            let sourceBound = false
            let pending = ["wire_upload_pause_and_prespeech_order", "wrist_down", "route_changes", "interruption",
                "standalone_wifi_cellular", "resource_measurements", "encrypted_relaunch_continuity", "source_binding_review"]
        }
        let diagnostics = departedFactory.evaluationAudioDiagnostics()
        let receipt = Receipt(version: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "",
            build: Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "",
            attemptID: paidAttemptID?.uuidString, hardwareObservation: observedHardware,
            playedFrames: playedFrames, heardReply: heardReply, capturedFrames: diagnostics?.capturedFrames ?? 0,
            audioReleased: diagnostics?.ownershipReleased == true, failureCategory: snapshot.error?.rawValue,
            providerReadyObserved: providerReadyObserved, finalUserMessages: userFinalIDs.count,
            finalAssistantMessages: assistantFinalIDs.count,
            serverListeningStoppedWhileMuted: serverListeningStoppedWhileMuted,
            idleWithServerPauseObserved: idleWithServerPauseObserved)
        do {
            let directory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("OpenMatesWatch/voice-evaluation", isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            let file = directory.appendingPathComponent("latest.json")
            try JSONEncoder().encode(receipt).write(to: file, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        } catch { NativeDiagnostics.failure("evaluation_receipt_failed", category: "watch_voice_probe", level: .warning, error: error) }
    }
    func depart() {
        departed = true; attemptID = UUID(); hardwareReady = false
        tools.invalidateOwner(); memory.invalidate()
        lease?.revoke(); work?.cancel(); consent.cancel()
        monitor?.cancel(); monitor = nil
        observers.forEach { NotificationCenter.default.removeObserver($0) }; observers.removeAll()
        Task { await stop(revokeFirst: true) }
    }
}

struct WatchVoiceEvaluationView: View {
    @StateObject private var owner: WatchVoiceEvaluationOwner
    @Environment(\.scenePhase) private var scenePhase
    let close: () -> Void
    init(auth: WatchAuthStore, runtime: WatchChatRuntime, consent: WatchVoiceCallConsent, close: @escaping () -> Void) {
        _owner = StateObject(wrappedValue: WatchVoiceEvaluationOwner(auth: auth, runtime: runtime, consent: consent))
        self.close = close
    }
    private func copy(_ key: String) -> String { WatchLocalization.text("watch.voice_evaluation." + key) }
    private func action(_ key: String, id: String, disabled: Bool = false, perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            Text(copy(key)).font(.omSmall.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: .spacing8)
                .background(WatchWorkspacePalette.surface, in: Capsule())
        }.buttonStyle(.plain).disabled(disabled).accessibilityIdentifier(id)
    }
    var body: some View {
        ScrollView {
            VStack(spacing: .spacing3) {
                Text(copy("title")).font(.omSmall.weight(.semibold))
                Text(copy("scope")).font(.omXs)
                action(owner.chosenChatID == nil ? "choose" : "chosen", id: "watch-voice-evaluation-choose",
                    disabled: owner.blocksNewWork || owner.ownsCall, perform: owner.chooseNewChat)
                if owner.chosenChatID != nil {
                    action(owner.savedConsent ? "consent_saved" : "consent", id: "watch-voice-evaluation-consent",
                        disabled: owner.blocksNewWork || owner.ownsCall, perform: owner.reviewConsent)
                    action(owner.hardwareReady ? "hardware_ready" : "hardware", id: "watch-voice-evaluation-hardware",
                        disabled: owner.blocksNewWork || owner.ownsCall || !owner.savedConsent, perform: owner.checkHardware)
                    Text(copy("paid_disclosure")).font(.omXs).accessibilityIdentifier("watch-voice-evaluation-paid-disclosure")
                    action("start", id: "watch-voice-evaluation-start", disabled: !owner.canStart, perform: owner.startPaidEvaluation)
                }
                if owner.ownsCall {
                    Text(copy(owner.snapshot.status == .live ? "live" : "connecting")).font(.omXs)
                    action(owner.snapshot.muted ? "unmute" : "mute", id: "watch-voice-evaluation-mute",
                        disabled: owner.snapshot.status != .live, perform: owner.toggleMute)
                    action("hangup", id: "watch-voice-evaluation-hangup", perform: owner.hangup)
                    action(owner.heardReply ? "heard_saved" : "heard", id: "watch-voice-evaluation-heard",
                        disabled: owner.playedFrames == 0, perform: owner.confirmHeardReply)
                }
                if owner.failed { Text(copy("failed")).font(.omXs).accessibilityIdentifier("watch-voice-evaluation-failed") }
                if owner.finished { Text(copy("finished")).font(.omXs).accessibilityIdentifier("watch-voice-evaluation-finished") }
                action("close", id: "watch-voice-evaluation-close", perform: close)
            }.padding(.spacing3)
        }.foregroundStyle(WatchWorkspacePalette.foreground)
            .background(WatchWorkspacePalette.background.ignoresSafeArea())
            .accessibilityIdentifier("watch-voice-evaluation")
            .overlay {
                WatchVoiceCallToolStatusView(coordinator: owner.tools)
                WatchVoiceCallMemoryPermissionView(permission: owner.memory)
            }
            .task { owner.activate() }
            .onChange(of: scenePhase) { _, phase in if phase != .active { Task { await owner.invalidate() } } }
            .onDisappear { owner.depart() }
    }
}
