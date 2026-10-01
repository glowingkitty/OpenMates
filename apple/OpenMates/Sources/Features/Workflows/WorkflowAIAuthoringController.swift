// Owner-fenced state for AI Workflow authoring and undo.
// Web source: frontend/apps/web_app/src/routes/workflows/+page.svelte

import SwiftUI

extension AppStrings {
    static var workflowAISaving: String { localized("workflows.builder.ai_saving") }
    static var workflowAIFailed: String { localized("workflows.builder.ai_failed") }
    static var workflowAIUndoFailed: String { localized("workflows.builder.ai_undo_failed") }
}

@MainActor
final class WorkflowAIAuthoringController: ObservableObject {
    @Published private(set) var pendingSession: WorkflowInputSession?
    @Published private(set) var completedSession: WorkflowInputSession?
    @Published private(set) var isSubmitting = false
    @Published private(set) var isUndoing = false
    @Published private(set) var errorMessage: String?

    private let service: any WorkflowAIAuthoringServing
    private let captureScope: @MainActor (String) -> WorkflowRequestScope
    private let checkScope: @MainActor (WorkflowRequestScope) async throws -> Void
    private var ownerAccountId: String?
    private var generation = 0
    private var pendingScope: WorkflowRequestScope?
    private var completedScope: WorkflowRequestScope?

    private func isCurrent(_ stamp: Int, owner: String?, scope: WorkflowRequestScope) -> Bool {
        generation == stamp && ownerAccountId == owner && scope.matchesContext()
    }

    init(service: any WorkflowAIAuthoringServing = WorkflowAIAuthoringService(),
         captureScope: @escaping @MainActor (String) -> WorkflowRequestScope = { WorkflowRequestScope.snapshot(accountId: $0) },
         checkScope: @escaping @MainActor (WorkflowRequestScope) async throws -> Void = { try await $0.check() }) {
        self.service = service
        self.captureScope = captureScope
        self.checkScope = checkScope
    }

    func reset(accountId: String?) {
        generation &+= 1
        ownerAccountId = accountId
        pendingSession = nil
        completedSession = nil
        isSubmitting = false
        isUndoing = false
        errorMessage = nil
        pendingScope = nil
        completedScope = nil
    }

    @discardableResult
    func submit(_ instruction: String, selectedWorkflowId: String?, timezone: String) async -> WorkflowInputSession? {
        let trimmed = instruction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let owner = ownerAccountId,
              !isSubmitting, pendingSession == nil else { return nil }
        let stamp = generation
        let scope = captureScope(owner)
        isSubmitting = true
        errorMessage = nil
        completedSession = nil
        defer { if generation == stamp { isSubmitting = false } }
        do {
            try await checkScope(scope)
            guard isCurrent(stamp, owner: owner, scope: scope) else { return nil }
            let session = try await service.submit(
                trimmed, selectedWorkflowId: selectedWorkflowId, timezone: timezone, scope: scope
            )
            try await checkScope(scope)
            guard isCurrent(stamp, owner: owner, scope: scope) else { return nil }
            return await finish(session, scope: scope, owner: owner, generation: stamp)
        } catch {
            guard isCurrent(stamp, owner: owner, scope: scope) else { return nil }
            errorMessage = error.localizedDescription
            return nil
        }
    }

    @discardableResult
    func resumePending() async -> WorkflowInputSession? {
        guard let pendingSession, let pendingScope, ownerAccountId != nil, !isSubmitting else { return nil }
        let owner = ownerAccountId
        let stamp = generation
        isSubmitting = true
        defer { if generation == stamp { isSubmitting = false } }
        do {
            try await checkScope(pendingScope)
            guard isCurrent(stamp, owner: owner, scope: pendingScope) else { return nil }
            let session = try await service.get(pendingSession.sessionId, scope: pendingScope)
            try await checkScope(pendingScope)
            guard isCurrent(stamp, owner: owner, scope: pendingScope) else { return nil }
            return await finish(session, scope: pendingScope, owner: owner, generation: stamp)
        } catch {
            guard isCurrent(stamp, owner: owner, scope: pendingScope) else { return nil }
            errorMessage = error.localizedDescription
            return nil
        }
    }

    @discardableResult
    func undo() async -> WorkflowInputSession? {
        guard let completedSession, let completedScope, completedSession.undoAvailable == true,
              ownerAccountId != nil, !isUndoing else { return nil }
        let owner = ownerAccountId
        let stamp = generation
        isUndoing = true
        errorMessage = nil
        defer { if generation == stamp { isUndoing = false } }
        do {
            try await checkScope(completedScope)
            guard isCurrent(stamp, owner: owner, scope: completedScope) else { return nil }
            let session = try await service.undo(completedSession.sessionId, scope: completedScope)
            try await checkScope(completedScope)
            guard isCurrent(stamp, owner: owner, scope: completedScope) else { return nil }
            if session.status == "executed" {
                self.completedSession = nil
                self.completedScope = nil
            } else {
                errorMessage = session.error ?? AppStrings.workflowAIUndoFailed
            }
            return session
        } catch {
            guard isCurrent(stamp, owner: owner, scope: completedScope) else { return nil }
            errorMessage = error.localizedDescription
            return nil
        }
    }

    private func finish(_ initial: WorkflowInputSession, scope: WorkflowRequestScope,
                        owner: String?, generation stamp: Int) async -> WorkflowInputSession? {
        var session = initial
        var checks = 0
        do {
            while session.status == "queued" || session.status == "saving" {
                guard isCurrent(stamp, owner: owner, scope: scope) else { return nil }
                pendingSession = session
                pendingScope = scope
                try Task.checkCancellation()
                try await Task.sleep(for: .milliseconds(checks < 2 ? 500 : 1_500))
                checks += 1
                session = try await service.get(session.sessionId, scope: scope)
            }
            try await checkScope(scope)
            guard isCurrent(stamp, owner: owner, scope: scope) else { return nil }
            pendingSession = nil
            pendingScope = nil
            if session.status == "executed" || session.status == "draft" {
                completedSession = session
                completedScope = scope
            } else {
                errorMessage = session.error ?? session.message ?? AppStrings.workflowAIFailed
            }
            return session
        } catch {
            guard isCurrent(stamp, owner: owner, scope: scope) else { return nil }
            errorMessage = error.localizedDescription
            return nil
        }
    }
}
