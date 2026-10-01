// Scoped realtime speech input for Workflow prompts. The audio stream is sent
// through the same authenticated transcription client as the chat composer;
// its temporary recording file is removed as soon as capture stops.
// Web source: WorkflowVoiceInput.svelte.

import SwiftUI

private final class WorkflowPCMState: @unchecked Sendable {
    private enum Phase { case open, finishing, failed, cancelled }
    private let lock = NSLock()
    private var phase: Phase = .open

    var isOpen: Bool { lock.withLock { phase == .open } }
    var isFinishing: Bool { lock.withLock { phase == .finishing } }
    func markFinishing() -> Bool { lock.withLock {
        guard phase == .open else { return false }
        phase = .finishing
        return true
    } }
    func markFailed() -> Bool { lock.withLock {
        guard phase == .open else { return false }
        phase = .failed
        return true
    } }
    func markCancelled() { lock.withLock { phase = .cancelled } }
}

private final class WorkflowPCMForwarder: @unchecked Sendable {
    private struct Chunk: Sendable {
        let samples: [Float]
        let sampleRate: Double
    }

    private let continuation: AsyncStream<Chunk>.Continuation
    private let consumer: Task<Void, Never>
    private let state: WorkflowPCMState
    private let onFailure: @Sendable () async -> Void

    init(client: AudioRealtimeTranscriptionClient,
         canForward: @escaping @Sendable () async -> Bool,
         onFailure: @escaping @Sendable () async -> Void) {
        self.onFailure = onFailure
        let state = WorkflowPCMState()
        self.state = state
        var captured: AsyncStream<Chunk>.Continuation?
        let stream = AsyncStream<Chunk>(bufferingPolicy: .bufferingNewest(96)) { captured = $0 }
        continuation = captured!
        consumer = Task {
            do {
                guard await canForward() else { await client.cancel(); await onFailure(); return }
                try await client.start()
                guard !Task.isCancelled, await canForward() else {
                    await client.cancel(); await onFailure(); return
                }
                for await chunk in stream {
                    guard !Task.isCancelled, await canForward() else {
                        await client.cancel(); await onFailure(); return
                    }
                    try await client.append(samples: chunk.samples, sourceSampleRate: chunk.sampleRate)
                }
                guard state.isFinishing, !Task.isCancelled, await canForward() else {
                    await client.cancel(); return
                }
                await client.finish()
            } catch {
                await client.cancel()
                await onFailure()
            }
        }
    }

    func append(samples: [Float], sampleRate: Double) {
        guard state.isOpen else { return }
        if case .dropped = continuation.yield(Chunk(samples: samples, sampleRate: sampleRate)) {
            // Preserve bounded memory and fail closed rather than sending a
            // transcript with missing audio segments.
            let notify = state.markFailed()
            continuation.finish()
            consumer.cancel()
            if notify { Task { await onFailure() } }
        }
    }

    func finish() {
        if state.markFinishing() { continuation.finish() }
    }
    func cancel() {
        state.markCancelled()
        continuation.finish()
        consumer.cancel()
    }

    deinit { cancel() }
}

@MainActor
private final class WorkflowVoiceInputController: ObservableObject {
    @Published private(set) var status = "connecting"
    @Published private(set) var preview = ""
    @Published private(set) var error: String?
    @Published private(set) var recording = false
    @Published private(set) var finishing = false

    private let recorder = VoiceRecorder()
    private var client: AudioRealtimeTranscriptionClient?
    private var forwarder: WorkflowPCMForwarder?
    private var rawTranscript = ""
    private var finishTimeout: Task<Void, Never>?
    private var generation = UUID()
    private var owner: String?
    private var scope: CodeRunScopeFence?
    private weak var authManager: AuthManager?
    private var onOutcome: ((_ text: String, _ corrected: Bool) -> Void)?

    func begin(authManager: AuthManager, owner: String?,
               onOutcome: @escaping (_ text: String, _ corrected: Bool) -> Void) async {
        guard let owner, authManager.state == .authenticated,
              authManager.currentUser?.id == owner else {
            error = AppStrings.localized("workflows.builder.voice_transcription_failed")
            return
        }
        let fence = CodeRunScopeFence(store: OfflineStore.shared)
        guard fence.isCurrent(in: OfflineStore.shared) else {
            error = AppStrings.localized("workflows.builder.voice_transcription_failed")
            return
        }
        let token = UUID()
        generation = token
        self.owner = owner
        self.scope = fence
        self.authManager = authManager
        self.onOutcome = onOutcome
        let microphoneAllowed = await recorder.requestPermission()
        guard isCurrent(token) else { await cancel(); return }
        guard microphoneAllowed else {
            error = AppStrings.localized("workflows.builder.voice_microphone_unavailable")
            return
        }

        let realtime = AudioRealtimeTranscriptionClient.live(authManager: authManager) { [weak self] event in
            await self?.receive(event, token: token)
        }
        client = realtime
        let sender = WorkflowPCMForwarder(client: realtime, canForward: { [weak self] in
            await self?.isCurrent(token) == true
        }) { [weak self] in
            await self?.fail(token: token)
        }
        forwarder = sender
        recorder.setPCMHandler { [weak sender] samples, sampleRate in
            sender?.append(samples: samples, sampleRate: sampleRate)
        }
        recorder.startRecording()
        guard recorder.isRecording else {
            error = recorder.error ?? AppStrings.localized("workflows.builder.voice_microphone_unavailable")
            await cancel()
            return
        }
        status = "connecting"
        recording = true
    }

    func finish() {
        guard recording, !finishing else { return }
        guard isCurrent(generation) else { Task { await cancel() }; return }
        recording = false
        finishing = true
        status = "correcting"
        if let url = recorder.stopRecording() {
            try? FileManager.default.removeItem(at: url)
        }
        recorder.setPCMHandler(nil)
        forwarder?.finish()
        let token = generation
        finishTimeout = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(12))
            guard !Task.isCancelled else { return }
            self?.complete(text: self?.rawTranscript ?? "", corrected: false, token: token)
        }
    }

    func cancel() async {
        let closing = close()
        if let closing { await closing.cancel() }
    }

    private func close() -> AudioRealtimeTranscriptionClient? {
        generation = UUID()
        finishTimeout?.cancel()
        finishTimeout = nil
        recorder.setPCMHandler(nil)
        recorder.cancelRecording()
        forwarder?.cancel()
        forwarder = nil
        let closing = client
        self.client = nil
        recording = false
        finishing = false
        onOutcome = nil
        rawTranscript = ""
        preview = ""
        owner = nil
        scope = nil
        authManager = nil
        return closing
    }

    private func isCurrent(_ token: UUID) -> Bool {
        generation == token && owner != nil
            && authManager?.state == .authenticated
            && authManager?.sessionValidationState == .onlineAuthenticated
            && authManager?.currentUser?.id == owner
            && scope?.isCurrent(in: OfflineStore.shared) == true
    }

    private func receive(_ event: AudioRealtimeTranscriptionClient.Event, token: UUID) {
        guard isCurrent(token) else {
            if generation == token { fail(token: token) }
            return
        }
        switch event {
        case .status(.connecting): status = "connecting"
        case .status(.listening): status = "listening"
        case .status(.correcting): status = "correcting"
        case .status(.failed): fail(token: token)
        case .status(.cancelled), .status(.completed): break
        case .transcript(let text):
            preview = text
            if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { rawTranscript = text }
        case .transcriptionDone(let result):
            preview = result.transcript
            rawTranscript = result.transcript
        case .correctionDone(let result):
            preview = result.transcript
            complete(text: result.useCorrected ? result.transcriptCorrected ?? "" : result.transcriptOriginal,
                     corrected: result.useCorrected, token: token)
        }
    }

    private func complete(text: String, corrected: Bool, token: UUID) {
        guard isCurrent(token), finishing else { return }
        finishTimeout?.cancel()
        finishTimeout = nil
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else {
            error = AppStrings.localized("workflows.builder.voice_no_speech")
            finishing = false
            return
        }
        let callback = onOutcome
        onOutcome = nil
        callback?(value, corrected)
    }

    private func fail(token: UUID) {
        guard generation == token else { return }
        error = AppStrings.localized("workflows.builder.voice_transcription_failed")
        let closing = close()
        if let closing { Task { await closing.cancel() } }
    }
}

struct WorkflowVoiceInputView: View {
    @ObservedObject var authManager: AuthManager
    let expectedAccountID: String?
    let onSubmit: (String) -> Void
    let onReview: (String) -> Void
    let onClose: () -> Void

    @StateObject private var controller = WorkflowVoiceInputController()
    @ObservedObject private var offlineStore = OfflineStore.shared
    @State private var capturedScopeGeneration: UUID?

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(AppStrings.localized("workflows.builder.voice_\(controller.status)"))
                .font(.omP.weight(.semibold))
            Text(controller.preview.isEmpty
                 ? AppStrings.localized("workflows.builder.voice_preview") : controller.preview)
                .font(.omP)
                .frame(maxWidth: .infinity, minHeight: 40, alignment: .leading)
                .accessibilityIdentifier("workflow-voice-preview")
            if let error = controller.error {
                Text(error).font(.omP).foregroundStyle(Color.error)
            }
            HStack {
                Spacer()
                Button(AppStrings.localized("workflows.builder.voice_cancel")) {
                    Task { await controller.cancel(); onClose() }
                }
                Button(AppStrings.localized("workflows.builder.voice_finish")) { controller.finish() }
                    .disabled(!controller.recording || controller.finishing)
                    .accessibilityIdentifier("workflow-voice-finish")
            }
            .buttonStyle(OMPrimaryButtonStyle())
        }
        .padding(.spacing8)
        .frame(maxWidth: 629)
        .background(Color.greyBlue, in: RoundedRectangle(cornerRadius: 20))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-voice-input")
        .task {
            capturedScopeGeneration = offlineStore.scopeGeneration
            await controller.begin(authManager: authManager, owner: expectedAccountID) { text, corrected in
                if corrected { onSubmit(text) } else { onReview(text) }
                onClose()
            }
        }
        .onChange(of: authManager.currentUser?.id) { _, newOwner in
            if newOwner != expectedAccountID { Task { await controller.cancel(); onClose() } }
        }
        .onChange(of: authManager.state) { _, state in
            if state != .authenticated { Task { await controller.cancel(); onClose() } }
        }
        .onChange(of: authManager.sessionValidationState) { _, state in
            if state != .onlineAuthenticated { Task { await controller.cancel(); onClose() } }
        }
        .onChange(of: offlineStore.scopeGeneration) { _, generation in
            if let capturedScopeGeneration, generation != capturedScopeGeneration {
                Task { await controller.cancel(); onClose() }
            }
        }
        .onChange(of: offlineStore.activeScopeId) { _, scopeId in
            if scopeId == nil { Task { await controller.cancel(); onClose() } }
        }
        .onDisappear { Task { await controller.cancel() } }
    }
}
