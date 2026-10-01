import Combine
import Foundation
import SwiftUI

/// One review owner for the app's shared socket. Plaintext proposals and command
/// output live only in memory and are discarded when the account scope changes.
@MainActor
final class ProjectWorkspaceReviewRuntime: ObservableObject {
    static let shared = ProjectWorkspaceReviewRuntime()

    let files: ProjectFileReviewCoordinator
    let commands: ProjectRemoteCommandCoordinator
    @Published private(set) var actionError: String?
    @Published private(set) var actionErrorChatID: String?
    private(set) var accountID: String?
    private var accountScope: UUID?
    private var activeChatID: String?
    private var activeOwnerID: UUID?
    private var authorityEpoch: UInt64 = 0
    private var serverProfile: ServerProfile?
    private weak var socket: WebSocketManager?
    private var inboundTail: Task<Void, Never>?
    private var pendingInboundCount = 0
    private var generation = UUID()
    private var subscriptions = Set<AnyCancellable>()

    init(files: ProjectFileReviewCoordinator = ProjectFileReviewCoordinator(),
         commands: ProjectRemoteCommandCoordinator = ProjectRemoteCommandCoordinator()) {
        self.files = files
        self.commands = commands
        files.objectWillChange.sink { [weak self] in self?.objectWillChange.send() }.store(in: &subscriptions)
        commands.objectWillChange.sink { [weak self] in self?.objectWillChange.send() }.store(in: &subscriptions)
    }

    func activate(accountID: String, chatID: String?, ownerID: UUID,
                  socket: WebSocketManager) {
        guard !accountID.isEmpty else { return }
        if self.accountID != accountID || accountScope != OfflineStore.shared.scopeGeneration ||
            serverProfile != ServerProfile.current() {
            reset()
        }
        if self.socket !== socket {
            invalidateInboundQueue()
            files.invalidatePendingOperations()
            commands.invalidatePendingOperations()
        }
        if activeOwnerID != ownerID || activeChatID != chatID || self.socket !== socket {
            authorityEpoch &+= 1
        }
        self.accountID = accountID
        accountScope = OfflineStore.shared.scopeGeneration
        serverProfile = ServerProfile.current()
        activeChatID = chatID
        activeOwnerID = ownerID
        self.socket = socket
    }

    func deactivate(ownerID: UUID) {
        guard activeOwnerID == ownerID else { return }
        authorityEpoch &+= 1
        activeOwnerID = nil
        activeChatID = nil
    }

    func reset() {
        authorityEpoch &+= 1
        invalidateInboundQueue()
        accountID = nil
        accountScope = nil
        serverProfile = nil
        activeChatID = nil
        activeOwnerID = nil
        socket = nil
        actionError = nil
        actionErrorChatID = nil
        files.reset()
        commands.reset()
    }

    private func invalidateInboundQueue() {
        generation = UUID()
        inboundTail?.cancel()
        inboundTail = nil
        pendingInboundCount = 0
    }

    func isActive(ownerID: UUID, chatID: String) -> Bool {
        activeOwnerID == ownerID && activeChatID == chatID &&
            accountScope == OfflineStore.shared.scopeGeneration && serverProfile == ServerProfile.current()
    }

    /// Output may be truncated under backpressure; final acknowledgements must
    /// still reach the coordinator so it can report completion and sequence gaps.
    static func acceptsInbound(type: String, eventKind: String?, pendingCount: Int) -> Bool {
        pendingCount < 128 || (type == "remote_command_event" && eventKind == "terminal") ||
            ["remote_command_prepared", "remote_command_rejected", "remote_command_stop_ack",
             "remote_command_origin_completion_ack", "remote_command_error"].contains(type)
    }

    static let inboundTypes: Set<String> = [
        "project_file_operation_available", "project_file_operation_request",
        "remote_command_review_required", "remote_command_event",
        "remote_command_prepared", "remote_command_rejected", "remote_command_stop_ack",
        "remote_command_origin_completion_ack", "remote_command_error"
    ]

    /// Serialize events so two terminal frames cannot publish the same command
    /// completion. Each queued frame is bound to the socket and account that
    /// received it; reconnect or logout invalidates the captured sender.
    func receive(type eventType: String, fields: [String: Any], from incomingSocket: WebSocketManager) {
        guard Self.inboundTypes.contains(eventType), socket === incomingSocket,
              let accountID, accountScope == OfflineStore.shared.scopeGeneration,
              serverProfile == ServerProfile.current(),
              Self.acceptsInbound(type: eventType, eventKind: fields["event_kind"] as? String,
                                  pendingCount: pendingInboundCount) else { return }
        let expectedGeneration = generation
        let scope = OfflineStore.shared.scopeGeneration
        let transport = incomingSocket.transportGeneration
        let receivedChatID = activeChatID
        let receivedOwnerID = activeOwnerID
        let receivedAuthorityEpoch = authorityEpoch
        let previous = inboundTail
        pendingInboundCount += 1
        inboundTail = Task { @MainActor [weak self, weak incomingSocket] in
            await previous?.value
            guard let self, let incomingSocket else { return }
            defer {
                if expectedGeneration == self.generation {
                    self.pendingInboundCount = max(0, self.pendingInboundCount - 1)
                }
            }
            guard !Task.isCancelled, self.generation == expectedGeneration,
                  self.socket === incomingSocket, self.serverProfile == ServerProfile.current(),
                  self.accountID == accountID, OfflineStore.shared.scopeGeneration == scope,
                  incomingSocket.transportGeneration == transport,
                  await AuthManager.currentUserId() == accountID,
                  self.generation == expectedGeneration, self.socket === incomingSocket,
                  self.serverProfile == ServerProfile.current(),
                  OfflineStore.shared.scopeGeneration == scope else { return }
            let needsFocus = ["project_file_operation_available", "project_file_operation_request", "remote_command_review_required"].contains(eventType)
            let send = self.sender(accountID: accountID, scope: scope,
                                   transport: transport, socket: incomingSocket,
                                   requiredChatID: needsFocus ? receivedChatID : nil,
                                   requiredOwnerID: needsFocus ? receivedOwnerID : nil,
                                   requiredAuthorityEpoch: needsFocus ? receivedAuthorityEpoch : nil)
            do {
                switch eventType {
                case "project_file_operation_available", "project_file_operation_request", "remote_command_review_required":
                    guard let chatID = receivedChatID, let ownerID = receivedOwnerID,
                          self.isActive(ownerID: ownerID, chatID: chatID),
                          self.authorityEpoch == receivedAuthorityEpoch else { return }
                    let validateAuthority: @MainActor () throws -> Void = { [weak self, weak incomingSocket] in
                        guard let self, let incomingSocket,
                              self.generation == expectedGeneration, self.socket === incomingSocket,
                              incomingSocket.transportGeneration == transport,
                              self.isActive(ownerID: ownerID, chatID: chatID),
                              self.authorityEpoch == receivedAuthorityEpoch else { throw CancellationError() }
                    }
                    if eventType == "project_file_operation_available" {
                        try await self.files.receiveAvailable(fields, accountID: accountID,
                            activeChatID: chatID, send: send, validateAuthority: validateAuthority)
                    } else if eventType == "project_file_operation_request" {
                        try await self.files.receiveRequest(fields, accountID: accountID,
                            activeChatID: chatID, send: send,
                            commit: self.committer(accountID: accountID, scope: scope, transport: transport,
                                socket: incomingSocket, chatID: chatID, ownerID: ownerID,
                                authorityEpoch: receivedAuthorityEpoch),
                            validateAuthority: validateAuthority)
                    } else {
                        try await self.commands.receiveReview(fields, accountID: accountID, activeChatID: chatID,
                                                              validateAuthority: validateAuthority)
                    }
                case "remote_command_event":
                    try await self.commands.receiveEvent(fields, accountID: accountID, send: send)
                default:
                    self.commands.receiveResponse(kind: eventType, payload: fields, accountID: accountID)
                }
            } catch {
                // Never log proposal contents, command output, paths, or IDs.
                NativeDiagnostics.warning("Project review event failed: \(type(of: error))", category: "projects")
            }
        }
    }

    func decideFile(_ displayed: ProjectFileReviewCoordinator.Entry, accepted: Bool,
                    chatID: String, ownerID: UUID) async {
        await perform(chatID: chatID, ownerID: ownerID) { accountID, send in
            try await self.files.decide(displayed, accepted: accepted, accountID: accountID,
                                       activeChatID: chatID, send: send)
        }
    }

    func decideCommand(_ displayed: ProjectRemoteCommandCoordinator.Entry, accepted: Bool,
                       chatID: String, ownerID: UUID) async {
        await perform(chatID: chatID, ownerID: ownerID) { accountID, send in
            try await self.commands.decide(displayed, accepted: accepted, accountID: accountID,
                                          activeChatID: chatID, send: send)
        }
    }

    func stopCommand(_ displayed: ProjectRemoteCommandCoordinator.Entry, chatID: String, ownerID: UUID) async {
        await perform(chatID: chatID, ownerID: ownerID) { accountID, send in
            try await self.commands.stop(displayed, accountID: accountID, activeChatID: chatID, send: send)
        }
    }

    private func perform(chatID: String, ownerID: UUID,
                         action: @MainActor (String, ProjectFileReviewCoordinator.Send) async throws -> Void) async {
        let expectedAuthorityEpoch = authorityEpoch
        guard let accountID, let accountScope, let socket,
              isActive(ownerID: ownerID, chatID: chatID),
              await AuthManager.currentUserId() == accountID,
              await AuthManager.isRecoveryEligibleDevice(),
              isActive(ownerID: ownerID, chatID: chatID), authorityEpoch == expectedAuthorityEpoch else { return }
        let expectedGeneration = generation
        do {
            try await action(accountID, sender(accountID: accountID, scope: accountScope,
                transport: socket.transportGeneration, socket: socket, requiredChatID: chatID,
                requiredOwnerID: ownerID, requiredAuthorityEpoch: expectedAuthorityEpoch))
            guard generation == expectedGeneration, authorityEpoch == expectedAuthorityEpoch else { return }
            actionError = nil
            actionErrorChatID = nil
        } catch {
            guard generation == expectedGeneration, authorityEpoch == expectedAuthorityEpoch else { return }
            actionError = AppStrings.projectError(error)
            actionErrorChatID = chatID
        }
    }

    private func sender(accountID: String, scope: UUID, transport: Int,
                        socket: WebSocketManager,
                        requiredChatID: String? = nil, requiredOwnerID: UUID? = nil,
                        requiredAuthorityEpoch: UInt64? = nil) -> ProjectFileReviewCoordinator.Send {
        let senderGeneration = generation
        return { [weak self, weak socket] type, payload in
            guard let self, let socket, self.accountID == accountID,
                  self.socket === socket, self.serverProfile == ServerProfile.current(),
                  self.generation == senderGeneration,
                  requiredChatID == nil || self.activeChatID == requiredChatID,
                  requiredOwnerID == nil || self.activeOwnerID == requiredOwnerID,
                  requiredAuthorityEpoch == nil || self.authorityEpoch == requiredAuthorityEpoch,
                  self.accountScope == scope, OfflineStore.shared.scopeGeneration == scope,
                  socket.transportGeneration == transport,
                  await AuthManager.currentUserId() == accountID,
                  self.socket === socket, self.generation == senderGeneration,
                  self.serverProfile == ServerProfile.current(),
                  OfflineStore.shared.scopeGeneration == scope,
                  requiredAuthorityEpoch == nil || self.authorityEpoch == requiredAuthorityEpoch else {
                throw CancellationError()
            }
            try await socket.send(WSOutboundMessage(type: type, payload: payload))
        }
    }

    private func committer(accountID: String, scope: UUID, transport: Int,
                           socket: WebSocketManager, chatID: String, ownerID: UUID,
                           authorityEpoch expectedAuthorityEpoch: UInt64) -> ProjectFileReviewCoordinator.Commit {
        let expectedGeneration = generation
        let validate: @MainActor () async throws -> Void = { [weak self, weak socket] in
            guard let self, let socket,
                  await AuthManager.currentUserId() == accountID,
                  await AuthManager.isRecoveryEligibleDevice(),
                  self.accountID == accountID, self.accountScope == scope,
                  OfflineStore.shared.scopeGeneration == scope,
                  self.generation == expectedGeneration, self.socket === socket,
                  socket.transportGeneration == transport,
                  self.isActive(ownerID: ownerID, chatID: chatID),
                  self.authorityEpoch == expectedAuthorityEpoch else { throw CancellationError() }
        }
        return { [weak socket] payload in
            guard let socket, payload["chat_id"] as? String == chatID else { throw CancellationError() }
            try await validate()
            let requestID = UUID().uuidString.lowercased()
            var request = payload
            request["request_id"] = requestID
            let response = try await socket.sendAndWait(
                WSOutboundMessage(type: "commit_embed_revision", payload: request),
                responseTypes: ["commit_embed_revision_result"],
                matching: { $0["request_id"] as? String == requestID },
                beforeSend: validate)
            try await validate()
            return response.fields
        }
    }
}

/// Uses the production review cards within the transcript, with account and chat
/// filtering on every render. Selecting a different window never moves approval
/// authority away from the app's active foreground chat.
struct ProjectWorkspaceReviewTranscriptView: View {
    @ObservedObject var runtime: ProjectWorkspaceReviewRuntime
    let chatID: String
    let accountID: String
    let ownerID: UUID

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            ForEach(runtime.files.entries.filter {
                $0.accountID == accountID && $0.scope == OfflineStore.shared.scopeGeneration && $0.chatID == chatID
            }) { entry in
                ProjectFileApprovalCard(entry: entry) { displayed, accepted in
                    Task { await runtime.decideFile(displayed, accepted: accepted, chatID: chatID, ownerID: ownerID) }
                }
            }
            ForEach(runtime.commands.entries.filter {
                $0.accountID == accountID && $0.scope == OfflineStore.shared.scopeGeneration && $0.review.chatId == chatID
            }) { entry in
                ProjectRemoteCommandReviewCard(entry: entry, onDecision: { displayed, accepted in
                    Task { await runtime.decideCommand(displayed, accepted: accepted, chatID: chatID, ownerID: ownerID) }
                }, onStop: { displayed in
                    Task { await runtime.stopCommand(displayed, chatID: chatID, ownerID: ownerID) }
                })
            }
            if runtime.actionErrorChatID == chatID, let error = runtime.actionError {
                Text(error).font(.omSmall).foregroundStyle(Color.warning)
                    .accessibilityIdentifier("project-review-action-error")
            }
        }
    }
}
