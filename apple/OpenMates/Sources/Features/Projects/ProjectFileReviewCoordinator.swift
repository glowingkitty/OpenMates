import Combine
import CryptoKit
import Foundation

/// A proposal remains client-owned. Only the keyed commitment and the user's
/// approval receipt are sent to the server.
struct ProjectFileMutation {
    let operation: String
    let operationID: String
    let path: String
    let expectedBase: String?
    let content: String?
    let patch: String?

    init(operation: String, operationID: String, arguments: [String: Any]) throws {
        let allowed: Set<String> = ["path", "expected_base", "content", "patch"]
        let idPattern = try NSRegularExpression(pattern: "^[A-Za-z0-9._:-]{1,128}$")
        let hashPattern = try NSRegularExpression(pattern: "^[a-f0-9]{64}$")
        guard ["create_file", "update_file"].contains(operation),
              idPattern.firstMatch(in: operationID, range: NSRange(operationID.startIndex..<operationID.endIndex, in: operationID)) != nil,
              Set(arguments.keys).isSubset(of: allowed),
              let path = arguments["path"] as? String, path.utf8.count <= 4096,
              ProjectWorkspacePath.normalized(path) != nil,
              !path.contains("\0") else { throw ProjectsWorkspaceError.invalidResponse }
        let expectedBase = arguments["expected_base"] as? String
        let content = arguments["content"] as? String
        let patch = arguments["patch"] as? String
        if operation == "create_file" {
            guard arguments.keys.contains("expected_base"), arguments["expected_base"] is NSNull,
                  content != nil, patch == nil else { throw ProjectsWorkspaceError.invalidResponse }
        } else {
            guard let expectedBase,
                  hashPattern.firstMatch(in: expectedBase, range: NSRange(expectedBase.startIndex..<expectedBase.endIndex, in: expectedBase)) != nil,
                  let patch, !patch.isEmpty, content == nil else { throw ProjectsWorkspaceError.invalidResponse }
        }
        guard (content ?? patch ?? "").utf8.count <= 200 * 1024 else { throw ProjectsWorkspaceError.invalidResponse }
        self.operation = operation
        self.operationID = operationID
        self.path = path
        self.expectedBase = expectedBase
        self.content = content
        self.patch = patch
    }

    var payload: [String: Any] {
        var value: [String: Any] = ["operation": operation, "operation_id": operationID,
                                   "path": path, "expected_base": expectedBase.map { $0 as Any } ?? NSNull()]
        if let content { value["content"] = content }
        if let patch { value["patch"] = patch }
        return value
    }

    func commitment(projectID: String, chatID: String, key: SymmetricKey) throws -> String {
        // JSON.stringify's ordered tuple in projectFileMutationProtocol.ts.
        let fields: [Any] = ["openmates-project-file-proposal-v1", projectID, chatID,
                             operation, operationID, path, expectedBase.map { $0 as Any } ?? NSNull(),
                             content.map { $0 as Any } ?? NSNull(),
                             patch.map { $0 as Any } ?? NSNull()]
        let message = try JSONSerialization.data(withJSONObject: fields, options: [.withoutEscapingSlashes])
        let digest = HMAC<SHA256>.authenticationCode(for: message, using: key)
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}

struct ProjectFileJob {
    let operationID: String
    let chatID: String
    let projectID: String
    let sourceID: String?
    let operation: String
    let arguments: [String: Any]
    let leaseToken: String
    let leaseGeneration: Int
    let leaseExpiresAt: TimeInterval

    init(_ value: [String: Any]) throws {
        guard value["protocol_version"] as? Int == 1,
              let operationID = value["operation_id"] as? String, !operationID.isEmpty, operationID.count <= 128,
              let chatID = value["chat_id"] as? String, !chatID.isEmpty, chatID.count <= 128,
              let projectID = value["project_id"] as? String, !projectID.isEmpty, projectID.count <= 128,
              let operation = value["operation"] as? String,
              ["list", "search", "read_text", "create_file", "update_file"].contains(operation),
              let arguments = value["arguments"] as? [String: Any],
              let leaseToken = value["lease_token"] as? String, leaseToken.count >= 16,
              let leaseGeneration = value["lease_generation"] as? Int, leaseGeneration >= 1,
              let leaseExpiresAt = value["lease_expires_at"] as? TimeInterval,
              leaseExpiresAt.isFinite else { throw ProjectsWorkspaceError.invalidResponse }
        self.operationID = operationID
        self.chatID = chatID
        self.projectID = projectID
        self.sourceID = value["source_id"] as? String
        self.operation = operation
        self.arguments = arguments
        self.leaseToken = leaseToken
        self.leaseGeneration = leaseGeneration
        self.leaseExpiresAt = leaseExpiresAt
    }

    var scope: [String: Any] { ["protocol_version": 1, "operation_id": operationID,
                                "chat_id": chatID, "project_id": projectID] }
    var resultScope: [String: Any] {
        var value = scope
        value["lease_token"] = leaseToken
        value["lease_generation"] = leaseGeneration
        return value
    }
    var isLive: Bool { leaseExpiresAt > Date().timeIntervalSince1970 }
}

@MainActor
final class ProjectFileReviewCoordinator: ObservableObject {
    private struct ApprovalScope: Hashable {
        let accountID: String
        let accountScope: UUID
        let chatID: String
        let projectID: String
        let operationID: String
    }
    private struct ReadScope: Hashable {
        let approval: ApprovalScope
        let sourceID: String?
        let path: String
    }
    struct Entry: Identifiable {
        let id: String
        let reviewID = UUID()
        let accountID: String
        let scope: UUID
        let chatID: String
        let projectID: String
        let sourceID: String?
        let mutation: ProjectFileMutation?
        let readPath: String?
        let commitment: String?
        var status: String
        var errorCode: String?
    }

    typealias Send = @MainActor (String, [String: Any]) async throws -> Void
    typealias Commit = @MainActor ([String: Any]) async throws -> [String: Any]
    @Published private(set) var entries: [Entry] = []
    private var approvedWrites: [ApprovalScope: String] = [:]
    private var approvedReads: Set<ReadScope> = []
    private var processing: Set<String> = []
    private var invalidatedReviews: Set<UUID> = []
    private var generation = UUID()
    private let resolver: ProjectReviewContextResolver
    private let remote: ProjectRemoteSourceClient

    init(resolver: ProjectReviewContextResolver = ProjectReviewContextResolver(),
         remote: ProjectRemoteSourceClient = ProjectRemoteSourceClient()) {
        self.resolver = resolver
        self.remote = remote
    }

    func reset() {
        generation = UUID()
        entries = []
        approvedWrites = [:]
        approvedReads = []
        processing = []
        invalidatedReviews = []
    }

    /// A replaced socket invalidates outstanding work and approval authority,
    /// while keeping the last visible cards for status context.
    func invalidatePendingOperations() {
        generation = UUID()
        approvedWrites = [:]
        approvedReads = []
        processing = []
        invalidatedReviews.formUnion(entries.map(\.reviewID))
    }

    func receiveAvailable(_ payload: [String: Any], accountID: String,
                          activeChatID: String, send: Send,
                          validateAuthority: @MainActor () throws -> Void = {}) async throws {
        guard payload["protocol_version"] as? Int == 1,
              let id = payload["operation_id"] as? String, !id.isEmpty, id.count <= 128,
              let chatID = payload["chat_id"] as? String, chatID == activeChatID,
              let projectID = payload["project_id"] as? String, !projectID.isEmpty,
              !processing.contains(id) else { return }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let requestGeneration = generation
        try await fence.check()
        try ensureActive(requestGeneration)
        try validateAuthority()
        try await send("project_file_operation_claim", ["protocol_version": 1,
            "operation_id": id, "chat_id": chatID, "project_id": projectID])
        try ensureActive(requestGeneration)
    }

    func receiveRequest(_ payload: [String: Any], accountID: String,
                        activeChatID: String, send: Send,
                        commit: Commit? = nil,
                        validateAuthority: @MainActor () throws -> Void = {}) async throws {
        let job = try ProjectFileJob(payload)
        guard job.chatID == activeChatID, !processing.contains(job.operationID) else { return }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let requestGeneration = generation
        try await fence.check()
        processing.insert(job.operationID)
        defer {
            if generation == requestGeneration { processing.remove(job.operationID) }
        }
        var leaseReleased = false
        do {
            guard job.isLive else { throw ProjectsWorkspaceError.invalidContext }
            let context = try await resolver.resolve(chatID: job.chatID,
                projectID: job.projectID, sourceID: job.sourceID, fence: fence)
            try ensureActive(requestGeneration)
            try validateAuthority()
            guard let chatKey = ChatKeyManager.shared.key(for: job.chatID) else {
                throw ProjectsWorkspaceError.missingProjectKey
            }
            try await fence.check()
            try ensureActive(requestGeneration)
            let mutation = try ["create_file", "update_file"].contains(job.operation)
                ? ProjectFileMutation(operation: job.operation, operationID: job.operationID,
                                      arguments: job.arguments) : nil
            var commitment: String?
            if let mutation {
                guard !context.settings.selectionRequired else { throw ProjectsWorkspaceError.invalidContext }
                commitment = try mutation.commitment(projectID: job.projectID,
                    chatID: job.chatID, key: context.project.key)
                let approvalScope = ApprovalScope(accountID: accountID, accountScope: fence.scope,
                    chatID: job.chatID, projectID: job.projectID, operationID: job.operationID)
                if context.settings.writeMode == .alwaysAsk,
                   approvedWrites[approvalScope] != commitment {
                    try await result(job, status: "awaiting_approval", body: [
                        "proposal_commitment": commitment!, "proposal": mutation.payload],
                        fence: fence, generation: requestGeneration, send: send)
                    leaseReleased = true
                    try ensureActive(requestGeneration)
                    try validateAuthority()
                    publish(Entry(id: job.operationID, accountID: accountID, scope: fence.scope,
                        chatID: job.chatID, projectID: job.projectID, sourceID: context.source?.id,
                        mutation: mutation, readPath: nil, commitment: commitment,
                        status: "awaiting_approval", errorCode: nil))
                    return
                }
            }
            guard job.isLive else { throw ProjectsWorkspaceError.invalidContext }
            let output: [String: Any]
            let readScope = (job.operation == "read_text" ? job.arguments["path"] as? String : nil)
                .map { ReadScope(approval: ApprovalScope(accountID: accountID,
                    accountScope: fence.scope, chatID: job.chatID, projectID: job.projectID,
                    operationID: job.operationID), sourceID: context.source?.id, path: $0) }
            if let source = context.source {
                do {
                    output = try await remote.executeProjectFileJob(project: context.project,
                        source: source, operation: job.operation,
                        arguments: mutation?.payload ?? job.arguments,
                        chatID: job.chatID, operationID: job.operationID,
                        proposalDigest: commitment,
                        approvedIgnoredRead: readScope.flatMap { approvedReads.contains($0) ? $0.path : nil },
                        fence: fence)
                } catch let failure as ProjectRemoteResultError where failure.code == "ignored_path_requires_approval" {
                    guard let readScope, !approvedReads.contains(readScope) else { throw failure }
                    try await result(job, status: "awaiting_approval", body: [
                        "reason": "ignored_path_requires_approval", "path": readScope.path],
                        fence: fence, generation: requestGeneration, send: send)
                    leaseReleased = true
                    try ensureActive(requestGeneration)
                    try validateAuthority()
                    publish(Entry(id: job.operationID, accountID: accountID, scope: fence.scope,
                        chatID: job.chatID, projectID: job.projectID, sourceID: source.id,
                        mutation: nil, readPath: readScope.path, commitment: nil,
                        status: "awaiting_approval", errorCode: nil))
                    return
                }
            } else {
                guard let commit else { throw ProjectsWorkspaceError.unsupportedSource }
                let adapter = ProjectHostedWorkspaceAdapter(project: context.project,
                    chatKey: chatKey, fence: fence, commit: commit)
                do {
                    output = try await ProjectHostedFileExecutor(adapter: adapter).execute(
                        job: job, mutation: mutation,
                        approvedIgnoredRead: readScope.flatMap { approvedReads.contains($0) ? $0.path : nil },
                        fence: fence, validateAuthority: validateAuthority)
                } catch let failure as ProjectHostedFileError where failure.code == "ignored_path_requires_approval" {
                    guard let readScope, !approvedReads.contains(readScope) else { throw failure }
                    try await result(job, status: "awaiting_approval", body: [
                        "reason": "ignored_path_requires_approval", "path": readScope.path],
                        fence: fence, generation: requestGeneration, send: send)
                    leaseReleased = true
                    try ensureActive(requestGeneration)
                    try validateAuthority()
                    publish(Entry(id: job.operationID, accountID: accountID, scope: fence.scope,
                        chatID: job.chatID, projectID: job.projectID, sourceID: nil,
                        mutation: nil, readPath: readScope.path, commitment: nil,
                        status: "awaiting_approval", errorCode: nil))
                    return
                }
            }
            try await fence.check()
            try ensureActive(requestGeneration)
            guard job.isLive, activeChatID == job.chatID else { throw ProjectsWorkspaceError.invalidContext }
            try validateAuthority()
            var body = output
            if let commitment { body["proposal_commitment"] = commitment }
            try await result(job, status: "completed", body: body,
                fence: fence, generation: requestGeneration, send: send)
            try ensureActive(requestGeneration)
            try validateAuthority()
            approvedWrites.removeValue(forKey: ApprovalScope(accountID: accountID,
                accountScope: fence.scope, chatID: job.chatID, projectID: job.projectID,
                operationID: job.operationID))
            approvedReads = approvedReads.filter { $0.approval.operationID != job.operationID ||
                $0.approval.chatID != job.chatID || $0.approval.accountID != accountID }
            if let mutation {
                publish(Entry(id: job.operationID, accountID: accountID, scope: fence.scope,
                    chatID: job.chatID, projectID: job.projectID, sourceID: context.source?.id,
                    mutation: mutation, readPath: nil, commitment: commitment,
                    status: "applied", errorCode: nil))
            }
        } catch {
            if !leaseReleased {
                let (status, code) = Self.safeFailure(error)
                try? await result(job, status: status, body: ["code": code],
                    fence: fence, generation: requestGeneration, send: send)
            }
        }
    }

    func decide(_ displayed: Entry, accepted: Bool, accountID: String,
                activeChatID: String, send: Send) async throws {
        let entry = try currentApproval(matching: displayed, accountID: accountID,
            activeChatID: activeChatID)
        let id = entry.id
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let requestGeneration = generation
        try await fence.check()
        try ensureActive(requestGeneration)
        let scope: [String: Any] = ["protocol_version": 1, "operation_id": id,
                                    "chat_id": entry.chatID, "project_id": entry.projectID]
        if !accepted {
            _ = try currentApproval(matching: displayed, accountID: accountID,
                activeChatID: activeChatID)
            try await send("project_file_operation_reject", scope)
            try await fence.check()
            try ensureActive(requestGeneration)
            _ = try currentApproval(matching: displayed, accountID: accountID,
                activeChatID: activeChatID)
            if let index = entries.firstIndex(where: { $0.id == id }) { entries[index].status = "rejected" }
            return
        }
        let context = try await resolver.resolve(chatID: entry.chatID,
            projectID: entry.projectID, sourceID: entry.sourceID, fence: fence)
        try ensureActive(requestGeneration)
        _ = try currentApproval(matching: displayed, accountID: accountID,
            activeChatID: activeChatID)
        if let readPath = entry.readPath {
            guard context.source?.id == entry.sourceID,
                  ProjectWorkspacePath.normalized(readPath) != nil else {
                throw ProjectsWorkspaceError.invalidContext
            }
            approvedReads.insert(ReadScope(approval: ApprovalScope(accountID: accountID,
                accountScope: fence.scope, chatID: entry.chatID, projectID: entry.projectID,
                operationID: id), sourceID: entry.sourceID, path: readPath))
            try await fence.check()
            try ensureActive(requestGeneration)
            _ = try currentApproval(matching: displayed, accountID: accountID,
                activeChatID: activeChatID)
            try await send("project_file_operation_claim", scope)
            try await fence.check()
            try ensureActive(requestGeneration)
            _ = try currentApproval(matching: displayed, accountID: accountID,
                activeChatID: activeChatID)
            if let index = entries.firstIndex(where: { $0.id == id }) { entries[index].status = "approved" }
            return
        }
        guard let mutation = entry.mutation, let commitment = entry.commitment else {
            throw ProjectsWorkspaceError.invalidContext
        }
        guard !context.settings.selectionRequired,
              context.settings.writeMode == .alwaysAsk,
              try mutation.commitment(projectID: entry.projectID, chatID: entry.chatID,
                                      key: context.project.key) == commitment else {
            throw ProjectsWorkspaceError.invalidContext
        }
        let escapedID = Self.escaped(entry.projectID)
        let path = "/v1/projects/\(escapedID)/write-approvals" +
            (context.teamID.map { "?team_id=\(Self.escaped($0))" } ?? "")
        _ = try currentApproval(matching: displayed, accountID: accountID,
            activeChatID: activeChatID)
        let response: ApprovalResponse = try await APIClient.shared.request(.post, path: path,
            serverProfile: fence.serverProfile,
            body: ["chat_id": entry.chatID, "operation_id": id,
                   "proposal_digest": commitment],
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try ensureActive(requestGeneration)
        guard response.approval.approved,
              response.approval.operationId == id,
              response.approval.proposalDigest == commitment else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        try await fence.check()
        try ensureActive(requestGeneration)
        _ = try currentApproval(matching: displayed, accountID: accountID,
            activeChatID: activeChatID)
        approvedWrites[ApprovalScope(accountID: accountID, accountScope: fence.scope,
            chatID: entry.chatID, projectID: entry.projectID, operationID: id)] = commitment
        try await send("project_file_operation_claim", scope)
        try await fence.check()
        try ensureActive(requestGeneration)
        _ = try currentApproval(matching: displayed, accountID: accountID,
            activeChatID: activeChatID)
        if let index = entries.firstIndex(where: { $0.id == id }) { entries[index].status = "approved" }
    }

    private func currentApproval(matching displayed: Entry, accountID: String,
                                 activeChatID: String) throws -> Entry {
        guard let current = entries.first(where: { $0.id == displayed.id }),
              current.reviewID == displayed.reviewID,
              !invalidatedReviews.contains(current.reviewID),
              current.accountID == accountID,
              current.scope == OfflineStore.shared.scopeGeneration,
              current.chatID == activeChatID,
              current.chatID == displayed.chatID,
              current.projectID == displayed.projectID,
              current.sourceID == displayed.sourceID,
              current.readPath == displayed.readPath,
              current.commitment == displayed.commitment,
              current.mutation?.path == displayed.mutation?.path,
              current.status == "awaiting_approval" else {
            throw ProjectsWorkspaceError.invalidContext
        }
        return current
    }

    private struct ApprovalResponse: Decodable { let approval: Approval }
    private struct Approval: Decodable {
        let approved: Bool
        let operationId: String
        let proposalDigest: String
    }

    private func result(_ job: ProjectFileJob, status: String, body: [String: Any],
                        fence: ProjectsWorkspaceFence, generation requestGeneration: UUID,
                        send: Send) async throws {
        try await fence.check()
        try ensureActive(requestGeneration)
        var payload = job.resultScope
        payload["status"] = status
        payload["result"] = body
        try await send("project_file_operation_result", payload)
        try ensureActive(requestGeneration)
    }

    private func ensureActive(_ requestGeneration: UUID) throws {
        guard generation == requestGeneration else { throw ProjectsWorkspaceError.accountChanged }
    }

    private func publish(_ entry: Entry) {
        invalidatedReviews.remove(entry.reviewID)
        for replaced in entries where replaced.id == entry.id {
            invalidatedReviews.remove(replaced.reviewID)
        }
        if entries.contains(where: { $0.id == entry.id }) {
            approvedWrites = approvedWrites.filter { scope, _ in
                scope.operationID != entry.id || scope.accountID != entry.accountID ||
                    scope.chatID != entry.chatID || scope.projectID != entry.projectID
            }
            approvedReads = approvedReads.filter { scope in
                scope.approval.operationID != entry.id || scope.approval.accountID != entry.accountID ||
                    scope.approval.chatID != entry.chatID || scope.approval.projectID != entry.projectID
            }
        }
        entries.removeAll { $0.id == entry.id }
        if entries.count >= 32 {
            invalidatedReviews.remove(entries[0].reviewID)
            entries.removeFirst()
        }
        entries.append(entry)
    }

    #if DEBUG
    func installReviewForTesting(_ entry: Entry) { publish(entry) }
    #endif

    private static func safeFailure(_ error: Error) -> (String, String) {
        if let hosted = error as? ProjectHostedFileError {
            if ["stale_base", "revision_conflict", "file_exists", "file_changed",
                "target_exists", "operation_conflict"].contains(hosted.code) {
                return ("conflict", hosted.code)
            }
            if ["source_offline", "protocol_timeout", "file_key_unavailable"].contains(hosted.code) {
                return ("waiting_for_executor", hosted.code)
            }
            let safe = hosted.code.range(of: "^[a-z][a-z0-9_]{0,63}$", options: .regularExpression) != nil
            return ("failed", safe ? hosted.code : "client_execution_failed")
        }
        if let remote = error as? ProjectRemoteResultError {
            if ["stale_base", "revision_conflict", "file_exists", "file_changed",
                "target_exists", "operation_conflict"].contains(remote.code) {
                return ("conflict", remote.code)
            }
            if ["source_offline", "protocol_timeout"].contains(remote.code) {
                return ("waiting_for_executor", remote.code)
            }
            return ("failed", remote.code)
        }
        switch error {
        case ProjectsWorkspaceError.missingProjectKey: return ("waiting_for_executor", "file_key_unavailable")
        case ProjectsWorkspaceError.unsupportedSource: return ("waiting_for_executor", "source_offline")
        case ProjectsWorkspaceError.invalidContext: return ("failed", "project_focus_required")
        default: return ("failed", "client_execution_failed")
        }
    }

    private static func escaped(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }
}
