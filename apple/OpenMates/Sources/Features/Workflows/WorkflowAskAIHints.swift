// Debounced, owner-scoped Ask AI instruction hints.
// Web source: WorkflowGraphRenderer.svelte scheduleAskHints/loadAskHints.

import SwiftUI

struct WorkflowAskAIReferenceHint: Encodable, Sendable {
    let reference: String
    let label: String
    let valueType: String
    let inserted: Bool

    enum CodingKeys: String, CodingKey {
        case reference, label, inserted
        case valueType = "value_type"
    }
}

struct WorkflowAskAIHintsRequest: Encodable, Sendable {
    let instruction: String
    let references: [WorkflowAskAIReferenceHint]
}

struct WorkflowAskAIHintsResponse: Decodable, Sendable {
    let verdict: WorkflowAskAIVerdict
    let suggestedReferences: [String]
    let reminder: String?

    enum CodingKeys: String, CodingKey {
        case verdict, reminder
        case suggestedReferences = "suggested_references"
    }
}

enum WorkflowAskAIVerdict: String, Codable, Equatable, Sendable {
    case idle, checking, allowed, asksToInvokeAppSkill = "asks_to_invoke_app_skill", unverified

    var blocksSave: Bool { self == .asksToInvokeAppSkill }
}

enum WorkflowAskAISaveFailure: Equatable {
    case missingInstruction, missingEarlierReference, appSkillInvocation
}

enum WorkflowAskAISavePolicy {
    static func failure(instruction: String, hasEarlierReference: Bool,
                        verdict: WorkflowAskAIVerdict) -> WorkflowAskAISaveFailure? {
        if instruction.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return .missingInstruction
        }
        if !hasEarlierReference { return .missingEarlierReference }
        if verdict.blocksSave { return .appSkillInvocation }
        return nil
    }
}

protocol WorkflowAskAIHintServing: Sendable {
    func hints(_ request: WorkflowAskAIHintsRequest,
               scope: WorkflowRequestScope) async throws -> WorkflowAskAIHintsResponse
}

struct WorkflowAskAIHintContext: Equatable {
    let profile: ServerProfile
    let activeScopeID: String?
    let offlineGeneration: UUID
    let teamEpoch: UInt64
    let teamID: String?

    @MainActor static func current() -> Self {
        Self(profile: ServerProfile.current(),
             activeScopeID: OfflineStore.shared.activeScopeId,
             offlineGeneration: OfflineStore.shared.scopeGeneration,
             teamEpoch: TeamWorkspaceContext.shared.contextEpoch,
             teamID: TeamWorkspaceContext.shared.teamID)
    }
}

actor WorkflowAskAIHintService: WorkflowAskAIHintServing {
    private let client: APIClient

    init(client: APIClient = .shared) { self.client = client }

    func hints(_ request: WorkflowAskAIHintsRequest,
               scope: WorkflowRequestScope) async throws -> WorkflowAskAIHintsResponse {
        try await client.request(
            .post, path: "/v1/workflows/ai-authoring/hints",
            serverProfile: scope.serverProfile, body: request,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
    }
}

@MainActor
final class WorkflowAskAIHintsController: ObservableObject {
    @Published private(set) var verdict: WorkflowAskAIVerdict = .idle
    @Published private(set) var suggestedReferences: [String] = []
    @Published private(set) var reminder: String?

    private let service: any WorkflowAskAIHintServing
    private let context: @MainActor () -> WorkflowAskAIHintContext
    private let captureScope: @MainActor (String) async throws -> WorkflowRequestScope
    private let currentAccountID: @MainActor () async -> String?
    private var accountId: String?
    private var nodeId: String?
    private var instruction = ""
    private var revision = 0
    private var pending: Task<Void, Never>?

    init(service: any WorkflowAskAIHintServing = WorkflowAskAIHintService(),
         context: @escaping @MainActor () -> WorkflowAskAIHintContext = { .current() },
         captureScope: @escaping @MainActor (String) async throws -> WorkflowRequestScope = { try await WorkflowRequestScope.capture(accountId: $0) },
         currentAccountID: @escaping @MainActor () async -> String? = { await AuthManager.currentUserId() }) {
        self.service = service
        self.context = context
        self.captureScope = captureScope
        self.currentAccountID = currentAccountID
    }

    func reset(accountId: String?) {
        revision &+= 1
        pending?.cancel()
        pending = nil
        self.accountId = accountId
        nodeId = nil
        instruction = ""
        verdict = .idle
        suggestedReferences = []
        reminder = nil
    }

    func schedule(nodeId: String, instruction: String,
                  references: [WorkflowAskAIReferenceHint]) {
        revision &+= 1
        pending?.cancel()
        self.nodeId = nodeId
        self.instruction = instruction
        suggestedReferences = []
        reminder = nil
        let trimmed = instruction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { verdict = .idle; return }
        guard accountId != nil else {
            verdict = .unverified
            reminder = AppStrings.workflowBuilder(.ask_ai_validation_unavailable)
            return
        }
        verdict = .checking
        let stamp = revision
        let owner = accountId
        let startingContext = context()
        pending = Task { [weak self] in
            do {
                try await Task.sleep(for: .seconds(1))
                guard let self, let owner, self.isCurrent(stamp, nodeId, instruction, owner),
                      self.context() == startingContext else { return }
                let scope = try await self.captureScope(owner)
                guard scope.serverProfile == startingContext.profile,
                      scope.offlineScope == startingContext.offlineGeneration,
                      await self.isCurrent(stamp, nodeId, instruction,
                                           scope: scope, context: startingContext) else { return }
                let result = try await self.service.hints(
                    WorkflowAskAIHintsRequest(instruction: instruction, references: references), scope: scope
                )
                guard await self.isCurrent(stamp, nodeId, instruction,
                                           scope: scope, context: startingContext) else { return }
                self.verdict = result.verdict
                self.suggestedReferences = result.suggestedReferences
                self.reminder = result.reminder
            } catch is CancellationError {
                guard let self, let owner, self.isCurrent(stamp, nodeId, instruction, owner),
                      self.context() == startingContext else { return }
                self.verdict = .unverified
                self.reminder = AppStrings.workflowBuilder(.ask_ai_validation_unavailable)
                return
            } catch {
                guard let self, let owner, self.isCurrent(stamp, nodeId, instruction, owner),
                      self.context() == startingContext else { return }
                self.verdict = .unverified
                self.reminder = AppStrings.workflowBuilder(.ask_ai_validation_unavailable)
            }
        }
    }

    private func isCurrent(_ stamp: Int, _ nodeId: String, _ instruction: String,
                           _ owner: String) -> Bool {
        !Task.isCancelled && revision == stamp && self.nodeId == nodeId &&
            self.instruction == instruction && accountId == owner
    }

    private func isCurrent(_ stamp: Int, _ nodeId: String, _ instruction: String,
                           scope: WorkflowRequestScope,
                           context startingContext: WorkflowAskAIHintContext) async -> Bool {
        guard isCurrent(stamp, nodeId, instruction, scope.accountId),
              context() == startingContext,
              startingContext.offlineGeneration == scope.offlineScope,
              startingContext.profile == scope.serverProfile else { return false }
        return await currentAccountID() == scope.accountId &&
            context() == startingContext && isCurrent(stamp, nodeId, instruction, scope.accountId)
    }
}
