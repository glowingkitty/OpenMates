// Remote command review cards (agentic coding). Validation, the acceptance
// policy, the canonical request and digest, decision payloads, output hygiene,
// the event reducer, the origin completion and status mapping live in the Rust
// core (`remote_command_review`, UniFFI `view_remote_commands`). This file keeps
// the per-card fence bookkeeping, CryptoKit/encrypt adapters and view state.
// Web counterpart: frontend/packages/ui/src/services/browserRemoteCommandClient.ts,
// frontend/packages/ui/src/components/projects/RemoteCommandReviewCard.svelte
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.remote.managed-jobs
import Combine
import CryptoKit
import Foundation

struct ProjectRemoteCommandPolicy: Decodable {
    let argv: [String]
    let cwd: String
    let mode: String
    let sourceAccess: String
    let deadlineMs: Int
    let writableProfiles: [String]
    let networkProfile: String?
    let credentialProfiles: [String]
}

struct ProjectRemoteCommandExplanation: Decodable {
    let summary: String
    let effects: [String]
    let risks: [String]
    let uncertainty: [String]
}

struct ProjectRemoteCommandReview: Decodable {
    let protocolVersion: Int
    let executionId: String
    let chatId: String
    let projectId: String
    let sourceId: String
    let state: String
    let createdAt: Int
    let reviewExpiresAt: Int
    let reviewToken: String
    let approvalRequirement: String
    let command: ProjectRemoteCommandPolicy
    let explanation: ProjectRemoteCommandExplanation

}

extension ProjectRemoteCommandReview {
    /// Card view of a review the core validated (`parseRemoteCommandReview`).
    init(record: RemoteCommandReviewRecord) {
        protocolVersion = 1
        executionId = record.executionId
        chatId = record.chatId
        projectId = record.projectId
        sourceId = record.sourceId
        state = "REVIEW_REQUIRED"
        createdAt = Int(clamping: record.createdAt)
        reviewExpiresAt = Int(clamping: record.reviewExpiresAt)
        reviewToken = record.reviewToken
        approvalRequirement = record.approvalRequirement
        command = ProjectRemoteCommandPolicy(argv: record.command.argv, cwd: record.command.cwd,
            mode: record.command.mode, sourceAccess: record.command.sourceAccess,
            deadlineMs: Int(clamping: record.command.deadlineMs),
            writableProfiles: record.command.writableProfiles,
            networkProfile: record.command.networkProfile,
            credentialProfiles: record.command.credentialProfiles)
        explanation = ProjectRemoteCommandExplanation(summary: record.explanation.summary,
            effects: record.explanation.effects, risks: record.explanation.risks,
            uncertainty: record.explanation.uncertainty)
    }

    /// The record the core functions take (policy decisions run in the core).
    var record: RemoteCommandReviewRecord {
        RemoteCommandReviewRecord(executionId: executionId, chatId: chatId, projectId: projectId,
            sourceId: sourceId, createdAt: UInt64(max(0, createdAt)),
            reviewExpiresAt: UInt64(max(0, reviewExpiresAt)), reviewToken: reviewToken,
            approvalRequirement: approvalRequirement,
            command: RemoteCommandPolicyRecord(argv: command.argv, cwd: command.cwd,
                mode: command.mode, sourceAccess: command.sourceAccess,
                deadlineMs: UInt64(max(0, command.deadlineMs)),
                writableProfiles: command.writableProfiles, networkProfile: command.networkProfile,
                credentialProfiles: command.credentialProfiles),
            explanation: RemoteCommandExplanationRecord(summary: explanation.summary,
                effects: explanation.effects, risks: explanation.risks,
                uncertainty: explanation.uncertainty))
    }
}

@MainActor
final class ProjectRemoteCommandCoordinator: ObservableObject {
    struct Entry: Identifiable {
        let id: String
        let reviewID = UUID()
        let accountID: String
        let scope: UUID
        let review: ProjectRemoteCommandReview
        let projectName: String
        let sourceName: String
        var status: String
        var latestOutput: String
        var errorCode: String?
        var lastSequence = -1
        var hasSequenceGap = false
        var upstreamTruncated = false
        var completionSent = false
        var completionSending = false
        var pendingTerminalCiphertext: String?
        var pendingTerminalSequence: Int?
        var pendingCompletion: [String: Any]?
    }

    @Published private(set) var entries: [Entry] = []
    private let contextResolver: ProjectReviewContextResolver
    private let eventKey: @MainActor (ProjectRemoteCommandReview, ProjectsWorkspaceFence) async throws -> SymmetricKey
    private let checkEventFence: @MainActor (ProjectsWorkspaceFence) async throws -> Void
    private var generation = UUID()
    private var invalidatedReviews: Set<UUID> = []

    init(contextResolver: ProjectReviewContextResolver = ProjectReviewContextResolver(),
         eventKey: (@MainActor (ProjectRemoteCommandReview, ProjectsWorkspaceFence) async throws -> SymmetricKey)? = nil,
         checkEventFence: (@MainActor (ProjectsWorkspaceFence) async throws -> Void)? = nil) {
        self.contextResolver = contextResolver
        self.eventKey = eventKey ?? { review, fence in
            let context = try await contextResolver.resolve(chatID: review.chatId,
                projectID: review.projectId, sourceID: review.sourceId, fence: fence)
            return context.project.key
        }
        self.checkEventFence = checkEventFence ?? { fence in try await fence.check() }
    }

    func reset() { generation = UUID(); entries = []; invalidatedReviews = [] }

    func invalidatePendingOperations() {
        generation = UUID()
        invalidatedReviews.formUnion(entries.map(\.reviewID))
        for index in entries.indices {
            entries[index].completionSending = false
            entries[index].pendingTerminalCiphertext = nil
            entries[index].pendingTerminalSequence = nil
            entries[index].pendingCompletion = nil
        }
    }

    #if DEBUG
    func installReviewForTesting(_ entry: Entry) {
        entries.removeAll { $0.id == entry.id }
        entries.append(entry)
    }
    #endif

    func receiveReview(_ payload: [String: Any], accountID: String,
                       activeChatID: String,
                       validateAuthority: @MainActor () throws -> Void = {}) async throws {
        // Validation and the acceptance policy (chat, expiry, window cap) run in the core.
        let record: RemoteCommandReviewRecord
        do {
            record = try parseRemoteCommandReview(payloadJson: Self.jsonText(payload))
        } catch { throw ProjectsWorkspaceError.invalidResponse }
        do {
            try checkRemoteCommandReviewAcceptable(review: record, activeChatId: activeChatID,
                nowUnix: UInt64(max(0, Date().timeIntervalSince1970)),
                openReviews: UInt32(entries.count))
        } catch { throw ProjectsWorkspaceError.invalidContext }
        let review = ProjectRemoteCommandReview(record: record)
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let requestGeneration = generation
        let context = try await contextResolver.resolve(chatID: review.chatId,
            projectID: review.projectId, sourceID: review.sourceId, fence: fence)
        guard let source = context.source, source.status == "connected" else {
            throw ProjectsWorkspaceError.unsupportedSource
        }
        try await fence.check()
        try ensureActive(requestGeneration)
        try validateAuthority()
        for replaced in entries where replaced.id == review.executionId {
            invalidatedReviews.remove(replaced.reviewID)
        }
        entries.removeAll { $0.id == review.executionId }
        entries.append(Entry(id: review.executionId, accountID: accountID, scope: fence.scope,
            review: review, projectName: context.project.name, sourceName: source.name,
            status: "pending", latestOutput: ""))
    }

    func decide(_ displayed: Entry, accepted: Bool, accountID: String,
                activeChatID: String,
                send: @MainActor (String, [String: Any]) async throws -> Void) async throws {
        let review = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: ["pending"]).review
        let id = displayed.id
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let requestGeneration = generation
        try await fence.check()
        try ensureActive(requestGeneration)
        guard review.reviewExpiresAt > Int(Date().timeIntervalSince1970) else {
            throw ProjectsWorkspaceError.invalidContext
        }
        if !accepted {
            _ = try currentReview(matching: displayed, accountID: accountID,
                activeChatID: activeChatID, allowedStatuses: ["pending"])
            try await send("remote_command_reject",
                try Self.jsonObject(remoteCommandRejectPayloadJson(review: review.record)))
            try await fence.check()
            try ensureActive(requestGeneration)
            _ = try currentReview(matching: displayed, accountID: accountID,
                activeChatID: activeChatID, allowedStatuses: ["pending"])
            if let index = entries.firstIndex(where: { $0.id == id }) { entries[index].status = "rejected" }
            return
        }
        let context = try await contextResolver.resolve(chatID: review.chatId,
            projectID: review.projectId, sourceID: review.sourceId, fence: fence)
        try ensureActive(requestGeneration)
        _ = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: ["pending"])
        guard context.source?.status == "connected" else { throw ProjectsWorkspaceError.unsupportedSource }
        // The web approval gate is the fresh active Project focus. The source
        // host applies the command's declared read/write sandbox policy.
        let canonical = Self.canonicalPortableRequest(review)
        // CryptoKit is the platform primitive; the digest and payload shape are core policy.
        let keyBytes = context.project.key.withUnsafeBytes { Data($0) }
        let digest = try remoteCommandRequestDigest(canonicalRequest: canonical, projectKey: keyBytes)
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey(canonical,
            masterKey: context.project.key)
        try ensureActive(requestGeneration)
        let payload = try Self.jsonObject(remoteCommandPreparePayloadJson(review: review.record,
            encryptedRequest: encrypted, requestDigest: digest))
        try await fence.check()
        try ensureActive(requestGeneration)
        _ = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: ["pending"])
        try await send("remote_command_prepare", payload)
        try await fence.check()
        try ensureActive(requestGeneration)
        _ = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: ["pending"])
        if let index = entries.firstIndex(where: { $0.id == id }) { entries[index].status = "preparing" }
    }

    func stop(_ displayed: Entry, accountID: String, activeChatID: String,
              send: @MainActor (String, [String: Any]) async throws -> Void) async throws {
        let activeStatuses = Set(["preparing", "waiting_for_executor", "authorizing", "running"]
            .filter { remoteCommandIsStoppable(status: $0) })
        let entry = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: activeStatuses)
        let id = displayed.id
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let requestGeneration = generation
        try await fence.check()
        try ensureActive(requestGeneration)
        _ = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: activeStatuses)
        try await send("remote_command_stop",
            try Self.jsonObject(remoteCommandStopPayloadJson(review: entry.review.record)))
        try await fence.check()
        try ensureActive(requestGeneration)
        _ = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: activeStatuses)
        if let index = entries.firstIndex(where: { $0.id == id }) { entries[index].status = "stop_requested" }
    }

    private func currentReview(matching displayed: Entry, accountID: String,
                               activeChatID: String, allowedStatuses: Set<String>) throws -> Entry {
        guard let current = entries.first(where: { $0.id == displayed.id }),
              current.reviewID == displayed.reviewID,
              !invalidatedReviews.contains(current.reviewID),
              current.accountID == accountID,
              current.scope == OfflineStore.shared.scopeGeneration,
              current.review.chatId == activeChatID,
              current.review.reviewToken == displayed.review.reviewToken,
              Self.canonicalPortableRequest(current.review) == Self.canonicalPortableRequest(displayed.review),
              allowedStatuses.contains(current.status) else {
            throw ProjectsWorkspaceError.invalidContext
        }
        return current
    }

    func receiveEvent(_ payload: [String: Any], accountID: String,
                      send: @MainActor (String, [String: Any]) async throws -> Void) async throws {
        guard let id = payload["execution_id"] as? String,
              let index = entries.firstIndex(where: { $0.id == id }),
              entries[index].accountID == accountID,
              entries[index].scope == OfflineStore.shared.scopeGeneration,
              payload["chat_id"] as? String == entries[index].review.chatId,
              payload["project_id"] as? String == entries[index].review.projectId,
              payload["source_id"] as? String == entries[index].review.sourceId,
              let ciphertext = payload["encrypted_event"] as? String,
              let sequence = payload["sequence"] as? Int,
              let eventKind = payload["event_kind"] as? String,
              let status = payload["status"] as? String else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let review = entries[index].review
        let reviewID = entries[index].reviewID
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let requestGeneration = generation
        let key = try await eventKey(review, fence)
        let plaintext = try await CryptoManager.shared.decryptContent(base64String: ciphertext,
            key: key)
        guard let data = plaintext.data(using: .utf8),
              let event = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              event["execution_id"] as? String == id,
              event["sequence"] as? Int == sequence,
              event["event_kind"] as? String == eventKind,
              event["status"] as? String == status,
              let current = entries.firstIndex(where: { $0.id == id }),
              entries[current].reviewID == reviewID,
              entries[current].scope == fence.scope else { throw ProjectsWorkspaceError.invalidResponse }
        let replay = eventKind == "terminal" && !entries[current].completionSent &&
            entries[current].pendingTerminalSequence == sequence &&
            entries[current].pendingTerminalCiphertext == ciphertext &&
            entries[current].pendingCompletion != nil
        guard entries[current].pendingCompletion == nil || replay else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        try await checkEventFence(fence)
        try ensureActive(requestGeneration)
        if !replay {
            // Kind/status pairing, sequence order, output hygiene and bounds are core policy.
            let folded: RemoteCommandOutputRecord
            do {
                folded = try remoteCommandApplyEvent(state: entries[current].outputRecord,
                    eventKind: eventKind, status: status, sequence: Int64(sequence),
                    text: eventKind == "output" ? event["text"] as? String : nil)
            } catch { throw ProjectsWorkspaceError.invalidResponse }
            entries[current].apply(folded)
        } else if sequence != entries[current].lastSequence {
            // A replay may only repeat the sequence it already applied.
            throw ProjectsWorkspaceError.invalidResponse
        }
        guard eventKind == "terminal", !entries[current].completionSent else { return }
        if !replay {
            let completion = try Self.jsonObject(remoteCommandCompletionPayloadJson(
                review: review.record, state: entries[current].outputRecord))
            entries[current].pendingTerminalCiphertext = ciphertext
            entries[current].pendingTerminalSequence = sequence
            entries[current].pendingCompletion = completion
        }
        guard !entries[current].completionSending,
              let completion = entries[current].pendingCompletion else { return }
        entries[current].completionSending = true
        do {
            try await checkEventFence(fence)
            try ensureActive(requestGeneration)
            try await send("remote_command_origin_completion", completion)
            try await checkEventFence(fence)
            try ensureActive(requestGeneration)
            guard let after = entries.firstIndex(where: { $0.id == id && $0.reviewID == reviewID }),
                  entries[after].pendingTerminalCiphertext == ciphertext,
                  entries[after].pendingTerminalSequence == sequence else {
                throw ProjectsWorkspaceError.invalidContext
            }
            entries[after].completionSent = true
            entries[after].completionSending = false
            entries[after].pendingTerminalCiphertext = nil
            entries[after].pendingTerminalSequence = nil
            entries[after].pendingCompletion = nil
        } catch {
            if let after = entries.firstIndex(where: { $0.id == id && $0.reviewID == reviewID }) {
                entries[after].completionSending = false
            }
            throw error
        }
    }

    func receiveResponse(kind: String, payload: [String: Any], accountID: String) {
        guard let id = payload["execution_id"] as? String,
              let index = entries.firstIndex(where: { $0.id == id && $0.accountID == accountID &&
                  $0.scope == OfflineStore.shared.scopeGeneration }) else { return }
        if kind == "remote_command_error" {
            entries[index].status = "error"
            entries[index].errorCode = payload["code"] as? String ?? "remote_command_failed"
            return
        }
        if let mapped = remoteCommandStatusForResponse(kind: kind, state: payload["state"] as? String,
            resultStatus: payload["result_status"] as? String) {
            entries[index].status = mapped
        }
    }

    private func ensureActive(_ requestGeneration: UUID) throws {
        guard generation == requestGeneration else { throw ProjectsWorkspaceError.accountChanged }
    }

    static func canonicalPortableRequest(_ review: ProjectRemoteCommandReview) -> String {
        remoteCommandCanonicalRequest(review: review.record)
    }

    /// Marshal a wire payload for the core (JSON text); the core owns its shape.
    private static func jsonText(_ payload: [String: Any]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: payload)
        guard let text = String(data: data, encoding: .utf8) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        return text
    }

    /// Decode a core-built payload for the WebSocket sender.
    private static func jsonObject(_ text: String) throws -> [String: Any] {
        guard let object = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        return object
    }
}

extension ProjectRemoteCommandCoordinator.Entry {
    /// The card's output state as the core reducer takes it.
    var outputRecord: RemoteCommandOutputRecord {
        RemoteCommandOutputRecord(lastSequence: Int64(lastSequence), status: status,
            latestOutput: latestOutput, hasSequenceGap: hasSequenceGap,
            upstreamTruncated: upstreamTruncated)
    }

    /// Store the core reducer's result back on the card.
    mutating func apply(_ record: RemoteCommandOutputRecord) {
        lastSequence = Int(clamping: record.lastSequence)
        status = record.status
        latestOutput = record.latestOutput
        hasSequenceGap = record.hasSequenceGap
        upstreamTruncated = record.upstreamTruncated
    }
}
