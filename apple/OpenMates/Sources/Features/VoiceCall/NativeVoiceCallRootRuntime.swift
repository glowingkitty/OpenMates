// Web sources: services/voiceCall.ts, voiceCallTools.ts, voiceCallMessages.ts.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.typed-input,
// video-call.privacy.first-call-warning, video-call.chat.skill-integration
#if !os(watchOS)
import Combine
import Foundation
import SwiftUI

private struct NativeVoiceCallRootRuntimeKey: EnvironmentKey {
    static let defaultValue: NativeVoiceCallRootRuntime? = nil
}
extension EnvironmentValues {
    var nativeVoiceCallRuntime: NativeVoiceCallRootRuntime? {
        get { self[NativeVoiceCallRootRuntimeKey.self] }
        set { self[NativeVoiceCallRootRuntimeKey.self] = newValue }
    }
}

/// In-memory snapshot only. Voice typed input does not admit attachment nodes;
/// preserving the complete original document and selection therefore preserves
/// every supported editor field without a plaintext file or secondary draft.
struct NativeVoiceCallRootDraftSnapshot: Codable {
    let document: ComposerDocumentV1
    let selectionLocation: Int
    let selectionLength: Int
}

/// Process-wide admission across retained app windows. These tokens contain no
/// text or credentials and do not report a queued/prepared send as completed.
@MainActor
final class NativeVoiceCallSendAdmission: ObservableObject {
    static let shared = NativeVoiceCallSendAdmission()
    @Published private var preparing: [UUID: (chatID: String, scope: UUID)] = [:]
    @Published private var callOwners: Set<UUID> = []
    var blocksOrdinary: Bool { !callOwners.isEmpty || AssistantSpeechAppRuntime.shared.hasLiveCallReservation }
    func beginOrdinary(chatID: String) -> UUID? {
        guard !blocksOrdinary else { return nil }
        let id = UUID(); preparing[id] = (chatID, OfflineStore.shared.scopeGeneration); return id
    }
    func endOrdinary(_ id: UUID) { preparing.removeValue(forKey: id) }
    func isPreparing(chatID: String) -> Bool {
        preparing.values.contains { $0.chatID == chatID && $0.scope == OfflineStore.shared.scopeGeneration }
    }
    func claimCall(_ owner: UUID, chatID: String) -> Bool {
        guard callOwners.isEmpty, !isPreparing(chatID: chatID) else { return false }
        callOwners.insert(owner); return true
    }
    func releaseCall(_ owner: UUID) { callOwners.remove(owner) }
}

/// Kept separate from root configuration so provider/ticker changes invalidate
/// only the call overlay, never MainApp or the retained chat transcript.
@MainActor
final class NativeVoiceCallRootPresentation: ObservableObject {
    @Published var creditsCharged: Double?
    @Published var toolWorking = false
}

@MainActor
final class NativeVoiceCallRootRuntime: ObservableObject {
    typealias ArtifactRouter = @MainActor @Sendable (NativeVoiceCallScope, String, NativeVoiceCallFrame) async throws -> NativeVoiceCallArtifactDisposition
    @Published private(set) var coordinator: NativeVoiceCallAppCoordinator?
    @Published private(set) var acceptedDrafts: [NativeVoiceCallDraftTicket] = []
    let presentation = NativeVoiceCallRootPresentation()
    let memory = NativeVoiceCallMemoryPermission()
    private var subscription: AnyCancellable?
    private var ownerIdentity: String?
    private let callAdmissionOwner = UUID()
    private var generation = UUID()
    private var teardown: Task<Void, Never>?
    private var auth: AuthManager?
    private var store: ChatStore?
    private var socket: WebSocketManager?
    private var factory: NativeVoiceCallAppFactory?
    private var admittedArtifactCount = 0
    private var team: TeamWorkspaceSnapshot?
    private var keyGeneration: UUID?
    private var router: ArtifactRouter?
    private struct DraftOperation {
        let ticket: NativeVoiceCallDraftTicket
        let editorID: UUID
        let accepted: @MainActor () -> Bool
        let unchanged: @MainActor () -> Bool
    }
    private var drafts: [UUID: DraftOperation] = [:]
    private var explicitlyRecovered: Set<UUID> = []

    static func identity(auth: AuthManager) -> String {
        [auth.currentUser?.id ?? "", auth.state == .authenticated ? "signed-in" : "signed-out",
         ServerProfile.current().id, OfflineStore.shared.scopeGeneration.uuidString,
         ChatKeyManager.shared.cacheGeneration.uuidString, String(TeamWorkspaceContext.shared.contextEpoch)].joined(separator: "|")
    }
    func configure(auth: AuthManager, store: ChatStore, socket: WebSocketManager,
                   ordinaryInferenceActive: @escaping @MainActor (String) -> Bool,
                   artifacts: @escaping ArtifactRouter) async {
        let identity = Self.identity(auth: auth)
        router = artifacts
        if ownerIdentity == identity, coordinator != nil { return }
        await invalidateOwner()
        guard !Task.isCancelled, identity == Self.identity(auth: auth), auth.state == .authenticated,
              TeamWorkspaceContext.shared.teamID == nil else { return }
        router = artifacts
        self.auth = auth; self.store = store; self.socket = socket
        team = TeamWorkspaceContext.shared.snapshot; keyGeneration = ChatKeyManager.shared.cacheGeneration
        ownerIdentity = identity
        let factory = NativeVoiceCallAppFactory(auth: auth, store: store, socket: socket,
            ordinaryInferenceActive: ordinaryInferenceActive)
        self.factory = factory
        let coordinator = NativeVoiceCallAppCoordinator(driver: factory,
            accepted: { [weak self] ticket, _ in self?.accept(ticket) },
            restore: { [weak self] ticket in self?.originalStillPresent(ticket) == true },
            artifacts: { [weak self] scope, callID, frame in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                try self.require(scope: scope, callID: callID)
                if frame["type"]?.string == "voice_memory" {
                    return try await self.memory.request(scope: scope, callID: callID, frame: frame,
                        validate: { [weak self] in
                            guard let self else { throw NativeVoiceCallError.scopeChanged }
                            try self.require(scope: scope, callID: callID)
                        })
                }
                if frame["type"]?.string == "voice_tool_status" {
                    guard frame["payload"]?.object != nil else { throw NativeVoiceCallError.invalidResponse }
                    self.presentation.toolWorking = true
                    return .presented // Actual transient state rendered by root overlay.
                }
                guard let route = self.router else { throw NativeVoiceCallError.unsupportedTransport }
                return try await route(scope, callID, frame)
            }, usage: { [weak self] scope, callID, frame in
                guard let self, (try? self.require(scope: scope, callID: callID)) != nil else { return }
                guard let credits = frame["credits_charged"]?.number, credits.isFinite, credits >= 0 else { return }
                self.presentation.creditsCharged = credits // Actual provider receipt, never an invented minute estimate.
                self.presentation.toolWorking = false
            })
        self.coordinator = coordinator
        subscription = coordinator.$state.map(\.status).removeDuplicates().sink { [weak self, weak coordinator] status in
            Task { @MainActor in
                guard let self, let coordinator, self.coordinator === coordinator else { return }
                if status == .ended || status == .failed {
                    self.memory.invalidate(); self.presentation.toolWorking = false
                    if self.admittedArtifactCount == 0 { NativeVoiceCallSendAdmission.shared.releaseCall(self.callAdmissionOwner) }
                }
                // NativeVoiceCallOverlay/StartControl observe coordinator directly.
                // No root objectWillChange forwarding, including clock/meter ticks.
            }
        }
    }
    /// Once a real broker artifact is admitted, normal hangup must not cancel
    /// its canonical encrypted commit. Owner change still revokes every send.
    func finishAdmittedArtifact(scope: NativeVoiceCallScope, callID: String,
        operation: @escaping @MainActor @Sendable () async throws -> NativeVoiceCallArtifactDisposition
    ) async throws -> NativeVoiceCallArtifactDisposition {
        try require(scope: scope, callID: callID)
        let admittedOwner = generation
        admittedArtifactCount += 1
        let completion = Task { @MainActor in
            defer {
                if generation == admittedOwner {
                    admittedArtifactCount -= 1
                    if admittedArtifactCount == 0, coordinator?.isActive != true {
                        NativeVoiceCallSendAdmission.shared.releaseCall(callAdmissionOwner)
                    }
                }
            }
            try requireOwner(scope)
            return try await operation()
        }
        return try await completion.value
    }
    func associateCommittedArtifact(scope: NativeVoiceCallScope, callID: String, functionCallID: String,
        assistantMessageID: String, userMessageID: String, reference: NativeVoiceCallFrame
    ) async throws {
        try requireOwner(scope)
        guard coordinator?.state.scope == scope, coordinator?.state.callID == callID, let factory
        else { throw NativeVoiceCallError.scopeChanged }
        try await factory.associateCommittedArtifact(scope: scope, callID: callID, functionCallID: functionCallID,
            assistantMessageID: assistantMessageID, userMessageID: userMessageID, reference: reference)
        try requireOwner(scope)
    }

    func requireOwner(_ scope: NativeVoiceCallScope) throws {
        guard let auth, auth.state == .authenticated, auth.currentUser?.id == scope.accountID,
              scope.profileID == ServerProfile.current().id,
              scope.workspaceGeneration == OfflineStore.shared.scopeGeneration,
              let team, team.teamID == nil, TeamWorkspaceContext.shared.isCurrent(team),
              keyGeneration == ChatKeyManager.shared.cacheGeneration,
              let chat = store?.chat(for: scope.chatID), chat.teamId == nil, chat.isSharedByOthers != true,
              ChatKeyManager.shared.encryptedKey(for: scope.chatID) == chat.encryptedChatKey,
              ChatKeyManager.shared.key(for: scope.chatID) != nil
        else { throw NativeVoiceCallError.scopeChanged }
        try Task.checkCancellation()
    }
    func require(scope: NativeVoiceCallScope, callID: String) throws {
        try requireOwner(scope)
        guard let coordinator, coordinator.state.status == .live,
              coordinator.state.scope == scope, coordinator.state.callID == callID
        else { throw NativeVoiceCallError.scopeChanged }
    }
    var blocksOrdinarySend: Bool { coordinator?.isActive == true || NativeVoiceCallSendAdmission.shared.blocksOrdinary }
    func supports(chat: Chat?) -> Bool {
        guard coordinator != nil, auth?.state == .authenticated, TeamWorkspaceContext.shared.teamID == nil else { return false }
        guard let chat else { return true }
        return UUID(uuidString: chat.id) != nil && chat.teamId == nil && chat.isSharedByOthers != true
            && !IncognitoChatSession.isIncognitoChatId(chat.id)
    }
    func canStart(chat: Chat?) -> Bool {
        supports(chat: chat) && coordinator?.isActive != true && !NativeVoiceCallSendAdmission.shared.blocksOrdinary
            && (chat.map { !NativeVoiceCallSendAdmission.shared.isPreparing(chatID: $0.id) } ?? true)
    }
    func start(_ destination: NativeVoiceCallAppDestination) async {
        let chatID: String
        switch destination { case .existing(let id): chatID = id; case .newPersonal(let id, _): chatID = id.uuidString.lowercased() }
        guard coordinator != nil, NativeVoiceCallSendAdmission.shared.claimCall(callAdmissionOwner, chatID: chatID) else { return }
        defer { if coordinator?.isActive != true { NativeVoiceCallSendAdmission.shared.releaseCall(callAdmissionOwner) } }
        presentation.creditsCharged = nil; presentation.toolWorking = false
        await coordinator?.start(destination)
    }
    func revokeOwner() {
        generation = UUID(); ownerIdentity = nil; memory.invalidate()
        NativeVoiceCallSendAdmission.shared.releaseCall(callAdmissionOwner)
        subscription?.cancel(); subscription = nil
        let previous = coordinator; coordinator = nil
        auth = nil; store = nil; socket = nil; factory = nil; admittedArtifactCount = 0; team = nil; keyGeneration = nil; router = nil
        // Draft plaintext must not cross the owner boundary. Original editor and
        // encrypted DraftService records were never cleared by a wire submission.
        drafts.removeAll(); explicitlyRecovered.removeAll(); acceptedDrafts.removeAll(); presentation.creditsCharged = nil; presentation.toolWorking = false
        let prior = teardown
        teardown = Task { await prior?.value; await previous?.invalidateOwner() }
    }
    func invalidateOwner() async {
        revokeOwner()
        await teardown?.value
    }
    func submit(chatID: String, editorID: UUID, text: String, document: ComposerDocumentV1,
                revision: Int, selection: NSRange, accepted: @escaping @MainActor () -> Bool,
                unchanged: @escaping @MainActor () -> Bool) async throws {
        guard let coordinator, coordinator.state.status == .live,
              let scope = coordinator.state.scope, scope.chatID == chatID, revision >= 0,
              !document.nodes.contains(where: { $0.kind == "embed" }),
              !drafts.values.contains(where: { $0.editorID == editorID && $0.ticket.revision == UInt64(revision) })
        else { throw NativeVoiceCallError.invalidState }
        try requireOwner(scope)
        let snapshot = NativeVoiceCallRootDraftSnapshot(document: document,
            selectionLocation: selection.location, selectionLength: selection.length)
        let ticket = NativeVoiceCallDraftTicket(id: UUID(), revision: UInt64(revision), scope: scope,
            text: text, originalComposerState: try JSONEncoder().encode(snapshot))
        drafts[ticket.id] = DraftOperation(ticket: ticket, editorID: editorID, accepted: accepted, unchanged: unchanged)
        do { try await coordinator.send(ticket) }
        catch {
            // The same original draft remains available on wire/rejection failure.
            // The coordinator records non-current editors for explicit recovery.
            throw error
        }
    }
    private func accept(_ ticket: NativeVoiceCallDraftTicket) {
        guard let operation = drafts[ticket.id], operation.ticket == ticket,
              (try? requireOwner(ticket.scope)) != nil else { return }
        if operation.accepted() { drafts.removeValue(forKey: ticket.id) }
        else if !acceptedDrafts.contains(ticket) { acceptedDrafts.append(ticket) }
    }
    private func originalStillPresent(_ ticket: NativeVoiceCallDraftTicket) -> Bool {
        if explicitlyRecovered.remove(ticket.id) != nil { return (try? requireOwner(ticket.scope)) != nil }
        guard let operation = drafts[ticket.id], operation.ticket == ticket,
              (try? requireOwner(ticket.scope)) != nil, operation.unchanged() else { return false }
        drafts.removeValue(forKey: ticket.id); return true
    }
    /// Explicit recovery cannot overwrite a newer editor. Caller must compare its
    /// current document and preserve the exact selection through loadDocument.
    func recover(_ ticket: NativeVoiceCallDraftTicket, apply: (NativeVoiceCallRootDraftSnapshot, Bool) -> Bool) {
        guard (try? requireOwner(ticket.scope)) != nil,
              let body = try? JSONDecoder().decode(NativeVoiceCallRootDraftSnapshot.self, from: ticket.originalComposerState)
        else { return }
        let alreadyAccepted = acceptedDrafts.contains(ticket)
        guard apply(body, alreadyAccepted) else { return }
        acceptedDrafts.removeAll { $0 == ticket }
        if !alreadyAccepted {
            explicitlyRecovered.insert(ticket.id)
            coordinator?.retryRestore(ticket.id)
        }
        drafts.removeValue(forKey: ticket.id)
    }
    func recoveryTickets(chatID: String) -> [NativeVoiceCallDraftTicket] {
        let pending = coordinator?.recoverableDrafts ?? []
        return (acceptedDrafts + pending).filter { $0.scope.chatID == chatID }
    }
}

@MainActor
struct NativeVoiceCallRootOverlay: View {
    @ObservedObject var runtime: NativeVoiceCallRootRuntime
    let returnToChat: (String) -> Void
    var body: some View {
        NativeVoiceCallRootOverlayContent(runtime: runtime, presentation: runtime.presentation, returnToChat: returnToChat)
    }
}

@MainActor
private struct NativeVoiceCallRootOverlayContent: View {
    @ObservedObject var runtime: NativeVoiceCallRootRuntime
    @ObservedObject var presentation: NativeVoiceCallRootPresentation
    let returnToChat: (String) -> Void
    var body: some View {
        ZStack {
            if let coordinator = runtime.coordinator {
                NativeVoiceCallOverlay(coordinator: coordinator, returnToChat: returnToChat)
                if presentation.toolWorking || presentation.creditsCharged != nil {
                    VStack {
                        Spacer()
                        HStack(spacing: .spacing4) {
                            if presentation.toolWorking { Text(AppStrings.nativeCall("working")) }
                            if let credits = presentation.creditsCharged {
                                Text(credits, format: .number.precision(.fractionLength(0...3)))
                                Text(AppStrings.nativeCall("credits"))
                            }
                        }.font(.omSmall).padding(.spacing4).background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius4))
                            .padding(.bottom, 84)
                    }.allowsHitTesting(false)
                }
            }
            NativeVoiceCallMemoryPermissionOverlay(runtime: runtime.memory)
        }
    }
}
#endif

#if !os(watchOS)
@MainActor
struct NativeVoiceCallDraftRecoveryStrip: View {
    @ObservedObject var runtime: NativeVoiceCallRootRuntime
    let chatID: String
    let recover: (NativeVoiceCallDraftTicket) -> Void
    var body: some View {
        let tickets = runtime.recoveryTickets(chatID: chatID)
        if !tickets.isEmpty {
            VStack(alignment: .leading, spacing: .spacing2) {
                ForEach(tickets) { ticket in
                    HStack(spacing: .spacing4) {
                        Text(AppStrings.draftBadge).font(.omSmall.weight(.semibold))
                        Text(ticket.text).font(.omSmall).lineLimit(1)
                        Button(runtime.acceptedDrafts.contains(ticket) ? AppStrings.delete : AppStrings.retry) { recover(ticket) }
                            .buttonStyle(OMSettingsButtonStyle())
                            .accessibilityIdentifier("voice-call-recover-draft")
                    }
                }
            }.padding(.spacing4).background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4)).padding(.bottom, 88)
        }
    }
}
#endif

#if !os(watchOS)
@MainActor
struct NativeVoiceCallStartControl: View {
    @ObservedObject var coordinator: NativeVoiceCallAppCoordinator
    @ObservedObject private var admission = NativeVoiceCallSendAdmission.shared
    let chatID: String
    let overlapsHeader: Bool
    let canBegin: Bool
    let action: () -> Void
    var body: some View {
        if !coordinator.isActive {
            NativeHeaderActionPill(icon: "audiocall", label: AppStrings.nativeCall("start"),
                overlapsHeader: overlapsHeader, accessibilityIdentifier: "voice-call-start", action: action)
                .disabled(!canBegin || admission.blocksOrdinary || admission.isPreparing(chatID: chatID))
        }
    }
}
#endif
