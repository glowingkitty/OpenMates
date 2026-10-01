import CryptoKit
import Combine
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

    func validate() throws {
        let identifier = try NSRegularExpression(pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
        guard protocolVersion == 1, state == "REVIEW_REQUIRED", reviewToken.count >= 32,
              reviewExpiresAt > createdAt,
              [executionId, chatId, projectId, sourceId].allSatisfy({
                  identifier.firstMatch(in: $0, range: NSRange($0.startIndex..<$0.endIndex, in: $0)) != nil
              }),
              approvalRequirement == "one_run" || approvalRequirement == "one_run_or_preset",
              !command.argv.isEmpty, command.argv.count <= 128,
              command.argv.allSatisfy({ !$0.isEmpty && !$0.contains("\0") && $0.count <= 128 }),
              !command.cwd.isEmpty, command.cwd.count <= 1024,
              !command.cwd.hasPrefix("/"), !command.cwd.contains("\\"),
              !command.cwd.split(separator: "/").contains(".."),
              ["foreground", "background"].contains(command.mode),
              ["read_only", "read_write"].contains(command.sourceAccess),
              (100...86_400_000).contains(command.deadlineMs),
              command.writableProfiles.count <= 32, command.credentialProfiles.count <= 32,
              explanation.summary.count <= 16_384 else {
            throw ProjectsWorkspaceError.invalidResponse
        }
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
        let review = try Self.decode(ProjectRemoteCommandReview.self, payload)
        try review.validate()
        guard review.chatId == activeChatID,
              review.reviewExpiresAt > Int(Date().timeIntervalSince1970),
              entries.count < 32 else { throw ProjectsWorkspaceError.invalidContext }
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
            try await send("remote_command_reject", ["protocol_version": 1,
                "execution_id": review.executionId, "chat_id": review.chatId,
                "project_id": review.projectId, "review_token": review.reviewToken])
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
        let identity = Self.jsonArray(["openmates-remote-command-request-v1", canonical])
        let digest = HMAC<SHA256>.authenticationCode(for: Data(identity.utf8), using: context.project.key)
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey(canonical,
            masterKey: context.project.key)
        try ensureActive(requestGeneration)
        let payload: [String: Any] = ["protocol_version": 1,
            "execution_id": review.executionId, "chat_id": review.chatId,
            "project_id": review.projectId, "source_id": review.sourceId,
            "review_token": review.reviewToken, "encrypted_request": encrypted,
            "request_digest": Self.base64URL(Data(digest)),
            "approval": ["kind": "one_run"]]
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
        let activeStatuses: Set<String> = ["preparing", "waiting_for_executor", "authorizing", "running"]
        let entry = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: activeStatuses)
        let id = displayed.id
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let requestGeneration = generation
        try await fence.check()
        try ensureActive(requestGeneration)
        _ = try currentReview(matching: displayed, accountID: accountID,
            activeChatID: activeChatID, allowedStatuses: activeStatuses)
        try await send("remote_command_stop", ["protocol_version": 1,
            "execution_id": entry.id, "chat_id": entry.review.chatId,
            "project_id": entry.review.projectId])
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
              ["status", "output", "output_truncated", "terminal"].contains(eventKind),
              ["authorizing", "running", "succeeded", "failed", "stopped", "timed_out"].contains(status),
              (eventKind == "terminal") == ["succeeded", "failed", "stopped", "timed_out"].contains(status),
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
        guard sequence > entries[current].lastSequence || replay else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        try await checkEventFence(fence)
        try ensureActive(requestGeneration)
        if !replay {
            if sequence != entries[current].lastSequence + 1 { entries[current].hasSequenceGap = true }
            entries[current].lastSequence = sequence
            entries[current].status = status
            if eventKind == "output", let output = event["text"] as? String {
                entries[current].latestOutput += Self.cleanTerminalText(output)
                if entries[current].latestOutput.count > 48_000 {
                    entries[current].latestOutput = Self.boundedOutput(entries[current].latestOutput)
                    entries[current].upstreamTruncated = true
                }
            }
            if eventKind == "output_truncated" { entries[current].upstreamTruncated = true }
        }
        guard eventKind == "terminal", !entries[current].completionSent else { return }
        if !replay {
            let output = Self.boundedOutput(entries[current].latestOutput)
            let modelText = entries[current].hasSequenceGap
                ? "[Incomplete terminal output: one or more event sequences were unavailable.]\n" + output : output
            let truncated = entries[current].upstreamTruncated || entries[current].hasSequenceGap
            var completion: [String: Any] = ["protocol_version": 1, "execution_id": id,
                "chat_id": review.chatId, "project_id": review.projectId,
                "result_status": status, "model_text": modelText,
                "upstream_truncated": truncated]
            if truncated { completion["omitted_chars"] = max(0, entries[current].latestOutput.count - output.count) }
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
        switch payload["state"] as? String {
        case "WAITING_FOR_EXECUTOR": entries[index].status = "waiting_for_executor"
        case "STOP_REQUESTED": entries[index].status = "stop_requested"
        case "REJECTED": entries[index].status = "rejected"
        case "TERMINAL": entries[index].status = payload["result_status"] as? String ?? "succeeded"
        default: break
        }
    }

    private func ensureActive(_ requestGeneration: UUID) throws {
        guard generation == requestGeneration else { throw ProjectsWorkspaceError.accountChanged }
    }

    static func canonicalPortableRequest(_ review: ProjectRemoteCommandReview) -> String {
        let command = review.command
        let policy = "{\"argv\":\(jsonArray(command.argv)),\"cwd\":\(jsonString(command.cwd))," +
            "\"mode\":\(jsonString(command.mode)),\"source_access\":\(jsonString(command.sourceAccess))," +
            "\"deadline_ms\":\(command.deadlineMs),\"writable_profiles\":\(jsonArray(command.writableProfiles))," +
            "\"network_profile\":\(command.networkProfile.map(jsonString) ?? "null")," +
            "\"credential_profiles\":\(jsonArray(command.credentialProfiles))}"
        return "{\"protocol_version\":1,\"execution_id\":\(jsonString(review.executionId))," +
            "\"chat_id\":\(jsonString(review.chatId)),\"project_id\":\(jsonString(review.projectId))," +
            "\"source_id\":\(jsonString(review.sourceId)),\"policy\":\(policy)," +
            "\"approval\":{\"kind\":\"one_run\"}}"
    }

    private static func decode<T: Decodable>(_ type: T.Type, _ payload: [String: Any]) throws -> T {
        let data = try JSONSerialization.data(withJSONObject: payload)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: data)
    }

    private static func jsonString(_ value: String) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [value], options: [.withoutEscapingSlashes])
        let encoded = String(data: data, encoding: .utf8)!
        return String(encoded.dropFirst().dropLast())
    }

    private static func jsonArray(_ values: [String]) -> String {
        let data = try! JSONSerialization.data(withJSONObject: values, options: [.withoutEscapingSlashes])
        return String(data: data, encoding: .utf8)!
    }

    private static func base64URL(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    private static func cleanTerminalText(_ value: String) -> String {
        value.replacingOccurrences(of: "\\u{001B}\\][^\\u{0007}\\u{001B}]*(?:\\u{0007}|\\u{001B}\\\\)",
                                     with: "", options: .regularExpression)
            .replacingOccurrences(of: "\\u{001B}\\[[0-?]*[ -/]*[@-~]", with: "", options: .regularExpression)
            .replacingOccurrences(of: "[\\u{202A}-\\u{202E}\\u{2066}-\\u{2069}\\u{0000}-\\u{001F}\\u{007F}]",
                                  with: "", options: .regularExpression)
    }

    private static func boundedOutput(_ value: String) -> String {
        guard value.count > 24_000 else { return value }
        let marker = "\n\n[... terminal output omitted ...]\n\n"
        let half = (24_000 - marker.count) / 2
        return String(value.prefix(half)) + marker + String(value.suffix(half))
    }
}
