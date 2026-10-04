// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.isolation, apple-workspaces.maintenance
// Client-side encrypted Plans V1 service for the Tasks board and Plan workspace.
// Mirrors userPlanService.ts: a per-plan key wraps under the account master key,
// while Project/Chat wrappers authorize linked contexts without plaintext fields.

import CryptoKit
import Foundation

@MainActor
final class UserPlansService {
    private struct ListResponse: Decodable, Sendable { let plans: [EncryptedUserPlanRecord] }
    private struct PlanResponse: Decodable, Sendable { let plan: EncryptedUserPlanRecord }
    private struct CriteriaResponse: Decodable, Sendable { let criteria: [EncryptedPlanCriterion] }
    private struct VerificationsResponse: Decodable, Sendable { let verifications: [EncryptedPlanVerification] }
    private struct AssumptionsResponse: Decodable, Sendable { let assumptions: [EncryptedPlanAssumption] }
    private struct PatternsResponse: Decodable, Sendable { let referencePatterns: [EncryptedPlanReferencePattern] }

    private let api: APIClient
    private let projects: ProjectsWorkspaceServing

    init(api: APIClient = .shared, projects: ProjectsWorkspaceServing = ProjectsWorkspaceService()) {
        self.api = api
        self.projects = projects
    }

    private func openPlans(_ data: Data, status: UserPlanStatus?, chatID: String?, projectID: String?,
                           fence: UserTasksAccountFence) async throws -> [UserPlanItem] {
        let response = try await NativeWorkspaceOfflineRuntime.decodeResponse(ListResponse.self, data: data)
        let masterKey = try await requireMasterKey(fence)
        var opened: [UserPlanItem] = []
        for record in response.plans {
            try await fence.check()
            if let item = try await open(record, masterKey: masterKey),
               status == nil || item.status == status,
               chatID == nil || item.primaryChatId == chatID,
               projectID == nil || item.linkedProjectIds.contains(projectID!) { opened.append(item) }
        }
        try await fence.check()
        return opened
    }

    func cachedPlans(projectID: String? = nil, teamID: String? = nil,
                     fence: UserTasksAccountFence) async throws -> [UserPlanItem]? {
        let scope = try await NativeWorkspaceOfflineRuntime.configure(accountID: fence.accountID, teamID: teamID)
        let path = NativeWorkspaceOfflineRuntime.inventoryPath("/v1/user-plans", teamID: teamID)
        guard let data = try await NativeWorkspaceOfflineRuntime.cached(namespace: "user-plans", path: path, scope: scope) else { return nil }
        return try await openPlans(data, status: nil, chatID: nil, projectID: projectID, fence: fence)
    }

    func list(status: UserPlanStatus? = nil, chatID: String? = nil,
              projectID: String? = nil, teamID: String? = nil,
              fence: UserTasksAccountFence) async throws -> [UserPlanItem] {
        try await fence.check()
        let scope = try await NativeWorkspaceOfflineRuntime.configure(accountID: fence.accountID, teamID: teamID)
        let data = try await inventory(scope: scope)
        return try await openPlans(data, status: status, chatID: chatID, projectID: projectID, fence: fence)
    }

    private func inventory(scope: NativeWorkspaceOfflineScope) async throws -> Data {
        try await NativeWorkspaceOfflineRuntime.coalescedInventory(namespace: "user-plans", scope: scope) {
            try await self.fetchInventory(scope: scope)
        }
    }

    private func fetchInventory(scope: NativeWorkspaceOfflineScope) async throws -> Data {
        let cache = NativeWorkspaceOfflineCache.shared
        let data = try await NativeWorkspaceOfflineRuntime.pagedInventory(namespace: "user-plans", collection: "plans",
            idKey: "plan_id", scope: scope, api: api)
        try await NativeWorkspaceOfflineRuntime.check(scope)
        let path = NativeWorkspaceOfflineRuntime.inventoryPath("/v1/user-plans", teamID: scope.teamID)
        try await cache.retain(namespace: "user-plans", path: path, data: data, scope: scope)
        return data
    }

    func maintainOffline(scope: NativeWorkspaceOfflineScope) async throws {
        let data = try await NativeWorkspaceOfflineRuntime.pagedInventory(namespace: "user-plans", collection: "plans",
            idKey: "plan_id", scope: scope, api: api)
        let inventory = try await NativeWorkspaceOfflineRuntime.decodeResponse(ListResponse.self, data: data)
        let cache = NativeWorkspaceOfflineCache.shared
        let revision = try await cache.beginRefresh(namespace: "user-plans", scope: scope)
        let listPath = NativeWorkspaceOfflineRuntime.inventoryPath("/v1/user-plans", teamID: scope.teamID)
        var responses = [listPath: data]
        for plan in inventory.plans {
            for suffix in ["/assumptions", "/criteria", "/verification", "/reference-patterns"] {
                let path = UserTasksPaths.scoped(Self.path(plan.planId) + suffix, teamID: scope.teamID)
                let collection = Self.detailCollection(suffix)
                let raw = try await NativeWorkspaceOfflineRuntime.pagedInventory(namespace: "user-plans",
                    collection: collection, idKey: "id", scope: scope, api: api,
                    basePath: Self.path(plan.planId) + suffix)
                switch suffix {
                case "/assumptions": _ = try await NativeWorkspaceOfflineRuntime.decodeResponse(AssumptionsResponse.self, data: raw)
                case "/criteria": _ = try await NativeWorkspaceOfflineRuntime.decodeResponse(CriteriaResponse.self, data: raw)
                case "/verification": _ = try await NativeWorkspaceOfflineRuntime.decodeResponse(VerificationsResponse.self, data: raw)
                default: _ = try await NativeWorkspaceOfflineRuntime.decodeResponse(PatternsResponse.self, data: raw)
                }
                responses[path] = raw
            }
        }
        try await NativeWorkspaceOfflineRuntime.check(scope)
        try await cache.commit(namespace: "user-plans", responses: responses, scope: scope, revision: revision)
    }

    private static func detailCollection(_ suffix: String) -> String {
        switch suffix {
        case "/assumptions": "assumptions"
        case "/criteria": "criteria"
        case "/verification": "verifications"
        default: "reference_patterns"
        }
    }

    private func localResponse<T: Decodable & Sendable>(_ type: T.Type, path: String,
                                             fence: UserTasksAccountFence) async throws -> T {
        let teamID = TeamWorkspaceContext.shared.teamID
        let scope = try await NativeWorkspaceOfflineRuntime.configure(accountID: fence.accountID, teamID: teamID)
        let scopedPath = UserTasksPaths.scoped(path, teamID: teamID)
        let raw: Data
        if let cached = try await NativeWorkspaceOfflineRuntime.cached(namespace: "user-plans", path: scopedPath, scope: scope) {
            raw = cached
        } else {
            let suffix = "/" + (path.split(separator: "/").last.map(String.init) ?? "")
            raw = try await NativeWorkspaceOfflineRuntime.pagedInventory(namespace: "user-plans",
                collection: Self.detailCollection(suffix), idKey: "id", scope: scope, api: api, basePath: path)
            try await NativeWorkspaceOfflineCache.shared.retain(namespace: "user-plans", path: scopedPath, data: raw, scope: scope)
        }
        try await fence.check()
        return try await NativeWorkspaceOfflineRuntime.decodeResponse(type, data: raw)
    }

    func create(title: String, goal: String, projectIDs: [String],
                chatID: String? = nil, teamID: String? = nil,
                fence: UserTasksAccountFence) async throws -> UserPlanItem {
        try await fence.check()
        let normalizedProjects = Array(Set(projectIDs.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }))
            .filter { !$0.isEmpty }
        guard !normalizedProjects.isEmpty, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw UserTasksError.invalidResponse
        }
        let masterKey = try await requireMasterKey(fence)
        let planKey = SymmetricKey(size: .bits256)
        let wrappedMaster = try await CryptoManager.shared.wrapChatKey(planKey, masterKey: masterKey)
        let timestamp = Int(Date().timeIntervalSince1970)
        let wrappers = try await keyWrappers(planKey: planKey, masterWrapper: wrappedMaster,
            timestamp: timestamp, chatID: chatID, projectIDs: normalizedProjects,
            teamID: teamID, fence: fence)
        let body: [String: Any] = [
            "plan_id": UUID().uuidString.lowercased(),
            "encrypted_title": try ComposerEmbedCrypto.encryptContent(title, using: planKey),
            "encrypted_goal": try ComposerEmbedCrypto.encryptContent(goal, using: planKey),
            "encrypted_scope_in": try ComposerEmbedCrypto.encryptContent("", using: planKey),
            "encrypted_scope_out": try ComposerEmbedCrypto.encryptContent("", using: planKey),
            "encrypted_user_flows": try ComposerEmbedCrypto.encryptContent("[]", using: planKey),
            "encrypted_assumptions": try ComposerEmbedCrypto.encryptContent("", using: planKey),
            "encrypted_open_questions": try ComposerEmbedCrypto.encryptContent("", using: planKey),
            "encrypted_constraints": try ComposerEmbedCrypto.encryptContent("", using: planKey),
            "encrypted_decisions": try ComposerEmbedCrypto.encryptContent("", using: planKey),
            "encrypted_risks": try ComposerEmbedCrypto.encryptContent("", using: planKey),
            "encrypted_linked_project_ids": try ComposerEmbedCrypto.encryptContent(Self.jsonArray(normalizedProjects), using: planKey),
            "status": UserPlanStatus.draft.rawValue,
            "primary_chat_id": chatID as Any? ?? NSNull(),
            "linked_project_ids": normalizedProjects,
            "created_at": timestamp,
            "updated_at": timestamp,
            "key_wrappers": wrappers,
        ]
        let response: PlanResponse = try await requestJSON(.post, path: "/v1/user-plans", body: body, fence: fence)
        try await fence.check()
        guard let opened = try await open(response.plan, masterKey: masterKey) else {
            throw UserTasksError.taskKeyUnavailable
        }
        return opened
    }

    func update(_ plan: UserPlanItem, title: String? = nil, goal: String? = nil,
                status: UserPlanStatus? = nil, fence: UserTasksAccountFence) async throws -> UserPlanItem {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        let planKey = try await requirePlanKey(plan.record, masterKey: masterKey)
        var body: [String: Any] = ["version": plan.version, "updated_at": Int(Date().timeIntervalSince1970)]
        if let title { body["encrypted_title"] = try ComposerEmbedCrypto.encryptContent(title, using: planKey) }
        if let goal { body["encrypted_goal"] = try ComposerEmbedCrypto.encryptContent(goal, using: planKey) }
        if let status { body["status"] = status.rawValue }
        let response: PlanResponse = try await requestJSON(.patch, path: Self.path(plan.id), body: body, fence: fence)
        try await fence.check()
        guard let opened = try await open(response.plan, masterKey: masterKey) else {
            throw UserTasksError.taskKeyUnavailable
        }
        return opened
    }

    func activate(_ plan: UserPlanItem, fence: UserTasksAccountFence) async throws -> UserPlanItem {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        let response: PlanResponse = try await requestJSON(.post, path: "\(Self.path(plan.id))/activate", body: [
            "version": plan.version, "updated_at": Int(Date().timeIntervalSince1970),
            "chat_id": plan.primaryChatId as Any? ?? NSNull(),
        ], fence: fence)
        try await fence.check()
        guard let opened = try await open(response.plan, masterKey: masterKey) else {
            throw UserTasksError.taskKeyUnavailable
        }
        return opened
    }

    func complete(_ plan: UserPlanItem, note: String? = nil,
                  fence: UserTasksAccountFence) async throws -> UserPlanItem {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        let response: PlanResponse = try await requestJSON(.post, path: "\(Self.path(plan.id))/complete", body: [
            "version": plan.version, "updated_at": Int(Date().timeIntervalSince1970),
            "completion_note": note as Any? ?? NSNull(),
        ], fence: fence)
        try await fence.check()
        guard let opened = try await open(response.plan, masterKey: masterKey) else {
            throw UserTasksError.taskKeyUnavailable
        }
        return opened
    }

    func detail(_ plan: UserPlanItem, fence: UserTasksAccountFence) async throws -> UserPlanDetailState {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        let planKey = try await requirePlanKey(plan.record, masterKey: masterKey)
        let base = Self.path(plan.id)
        let assumptions: AssumptionsResponse = try await localResponse(AssumptionsResponse.self, path: "\(base)/assumptions", fence: fence)
        let criteria: CriteriaResponse = try await localResponse(CriteriaResponse.self, path: "\(base)/criteria", fence: fence)
        let verifications: VerificationsResponse = try await localResponse(VerificationsResponse.self, path: "\(base)/verification", fence: fence)
        let patterns: PatternsResponse = try await localResponse(PatternsResponse.self, path: "\(base)/reference-patterns", fence: fence)
        try await fence.check()
        return UserPlanDetailState(
            assumptions: try assumptions.assumptions.map { value in
                UserPlanDetailEntry(id: value.id, title: try decrypt(value.encryptedText, key: planKey),
                    subtitle: "\(value.status) before \(value.requiredBefore ?? "implementation")",
                    evidence: try decrypt(value.encryptedEvidenceSummary, key: planKey), status: value.status)
            },
            criteria: try criteria.criteria.map { value in
                UserPlanDetailEntry(id: value.id, title: try decrypt(value.encryptedText, key: planKey),
                    subtitle: "\(value.coverageStatus ?? "uncovered") · \(value.verificationIds?.count ?? 0) checks",
                    evidence: try decrypt(value.encryptedEvidence, key: planKey), status: value.status)
            },
            verifications: try verifications.verifications.map { value in
                let description = try decrypt(value.encryptedDescription, key: planKey)
                let command = try decrypt(value.encryptedCommand, key: planKey)
                return UserPlanDetailEntry(id: value.id,
                    title: !description.isEmpty ? description : (!command.isEmpty ? command : value.kind),
                    subtitle: "\(value.status) · covers \(value.covers?.count ?? 0) criteria",
                    evidence: try decrypt(value.encryptedResultSummary, key: planKey), status: value.status)
            },
            referencePatterns: try patterns.referencePatterns.map { value in
                UserPlanDetailEntry(id: value.id, title: try decrypt(value.encryptedTitle, key: planKey),
                    subtitle: "\(value.status) · \(value.sourceCount ?? 0) sources",
                    evidence: try decrypt(value.encryptedEvidenceSummary, key: planKey), status: value.status)
            }
        )
    }

    func createAssumption(_ text: String, plan: UserPlanItem,
                          fence: UserTasksAccountFence) async throws {
        let key = try await writableKey(plan, fence: fence)
        let timestamp = Int(Date().timeIntervalSince1970)
        let body: [String: Any] = [
            "assumption_id": UUID().uuidString.lowercased(),
            "encrypted_text": try ComposerEmbedCrypto.encryptContent(text, using: key),
            "category": "other", "status": "unchecked",
            "required_before": "implementation", "linked_criterion_ids": [], "source_count": 0,
            "encrypted_corrected_text": try ComposerEmbedCrypto.encryptContent("", using: key),
            "encrypted_evidence_summary": try ComposerEmbedCrypto.encryptContent("", using: key),
            "encrypted_blocker_reason": try ComposerEmbedCrypto.encryptContent("", using: key),
            "encrypted_waiver_reason": try ComposerEmbedCrypto.encryptContent("", using: key),
            "encrypted_sources": try ComposerEmbedCrypto.encryptContent("", using: key),
            "created_at": timestamp, "updated_at": timestamp,
        ]
        let _: Data = try await requestPinned(.post, path: "\(Self.path(plan.id))/assumptions", body: body, fence: fence)
        try await fence.check()
    }

    func confirmAssumption(_ id: String, plan: UserPlanItem,
                           fence: UserTasksAccountFence) async throws {
        let key = try await writableKey(plan, fence: fence)
        let body: [String: Any] = [
            "status": "confirmed",
            "encrypted_evidence_summary": try ComposerEmbedCrypto.encryptContent("Confirmed from plan review.", using: key),
            "updated_at": Int(Date().timeIntervalSince1970),
        ]
        let _: Data = try await requestPinned(.patch,
            path: "\(Self.path(plan.id))/assumptions/\(UserTasksPaths.escaped(id))", body: body, fence: fence)
        try await fence.check()
    }

    func createCriterion(_ text: String, plan: UserPlanItem,
                         fence: UserTasksAccountFence) async throws {
        let key = try await writableKey(plan, fence: fence)
        let timestamp = Int(Date().timeIntervalSince1970)
        let body: [String: Any] = [
            "criterion_id": UUID().uuidString.lowercased(),
            "encrypted_text": try ComposerEmbedCrypto.encryptContent(text, using: key),
            "type": "acceptance", "status": "pending", "required": true,
            "linked_task_ids": [], "verification_ids": [], "coverage_status": "uncovered",
            "created_at": timestamp, "updated_at": timestamp,
        ]
        let _: Data = try await requestPinned(.post, path: "\(Self.path(plan.id))/criteria", body: body, fence: fence)
        try await fence.check()
    }

    func createVerification(title: String, command: String, covering criterionIDs: [String],
                            plan: UserPlanItem, fence: UserTasksAccountFence) async throws {
        let key = try await writableKey(plan, fence: fence)
        let timestamp = Int(Date().timeIntervalSince1970)
        let verificationID = UUID().uuidString.lowercased()
        let body: [String: Any] = [
            "verification_id": verificationID,
            "kind": command.isEmpty ? "manual" : "command",
            "phase": "final", "status": "pending", "lifecycle_status": "proposed",
            "required_for_done": true, "covers": criterionIDs,
            "create_task": false, "task_key_wrappers": [],
            "encrypted_description": try ComposerEmbedCrypto.encryptContent(title, using: key),
            "encrypted_title": try ComposerEmbedCrypto.encryptContent(title, using: key),
            "encrypted_command": try ComposerEmbedCrypto.encryptContent(command, using: key),
            "encrypted_evaluation_prompt": try ComposerEmbedCrypto.encryptContent("", using: key),
            "encrypted_expected_result": try ComposerEmbedCrypto.encryptContent("", using: key),
            "primary_chat_id": plan.primaryChatId as Any? ?? NSNull(),
            "linked_project_ids": plan.linkedProjectIds,
            "assignee_type": "user", "created_at": timestamp, "updated_at": timestamp,
        ]
        let _: Data = try await requestPinned(.post, path: "\(Self.path(plan.id))/verification", body: body, fence: fence)
        try await fence.check()
        let response: CriteriaResponse = try await api.request(.get, path: "\(Self.path(plan.id))/criteria",
            serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        for criterion in response.criteria where criterionIDs.contains(criterion.id) {
            let ids = Array(Set((criterion.verificationIds ?? []) + [verificationID]))
            let patch: [String: Any] = ["verification_ids": ids, "coverage_status": "covered",
                                         "verification_scope": title, "updated_at": timestamp]
            let _: Data = try await requestPinned(.patch,
                path: "\(Self.path(plan.id))/criteria/\(UserTasksPaths.escaped(criterion.id))",
                body: patch, fence: fence)
            try await fence.check()
        }
    }

    func addVerificationEvidence(_ summary: String, verificationID: String,
                                 plan: UserPlanItem, fence: UserTasksAccountFence) async throws {
        let key = try await writableKey(plan, fence: fence)
        let body: [String: Any] = [
            "status": "passed",
            "encrypted_result_summary": try ComposerEmbedCrypto.encryptContent(summary, using: key),
            "encrypted_required_fixes": try ComposerEmbedCrypto.encryptContent("", using: key),
            "updated_at": Int(Date().timeIntervalSince1970),
        ]
        let _: Data = try await requestPinned(.post,
            path: "\(Self.path(plan.id))/verification/\(UserTasksPaths.escaped(verificationID))/evidence",
            body: body, fence: fence)
        try await fence.check()
    }

    private func writableKey(_ plan: UserPlanItem,
                             fence: UserTasksAccountFence) async throws -> SymmetricKey {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        return try await requirePlanKey(plan.record, masterKey: masterKey)
    }

    private static func path(_ id: String) -> String { "/v1/user-plans/\(UserTasksPaths.escaped(id))" }

    private func open(_ record: EncryptedUserPlanRecord,
                      masterKey: SymmetricKey) async throws -> UserPlanItem? {
        guard record.keyWrappers?.contains(where: { $0.keyType == "master" }) == true else { return nil }
        let key = try await requirePlanKey(record, masterKey: masterKey)
        let flowsText = try decrypt(record.encryptedUserFlows, key: key)
        let flows: [UserPlanFlow]
        if let data = flowsText.data(using: .utf8), !flowsText.isEmpty {
            flows = try Self.decodeOpenedJSON([UserPlanFlow].self, from: data, field: .userFlows)
        } else { flows = [] }
        let projectIDsText = try decrypt(record.encryptedLinkedProjectIds, key: key)
        let projectIDs: [String]
        if let data = projectIDsText.data(using: .utf8), !projectIDsText.isEmpty {
            projectIDs = try Self.decodeOpenedJSON([String].self, from: data, field: .linkedProjectIDs)
        } else { projectIDs = [] }
        return UserPlanItem(record: record, title: try decrypt(record.encryptedTitle, key: key),
            goal: try decrypt(record.encryptedGoal, key: key),
            scopeIn: try decrypt(record.encryptedScopeIn, key: key),
            scopeOut: try decrypt(record.encryptedScopeOut, key: key), userFlows: flows,
            assumptions: try decrypt(record.encryptedAssumptions, key: key),
            openQuestions: try decrypt(record.encryptedOpenQuestions, key: key),
            constraints: try decrypt(record.encryptedConstraints, key: key),
            decisions: try decrypt(record.encryptedDecisions, key: key),
            risks: try decrypt(record.encryptedRisks, key: key), linkedProjectIds: projectIDs)
    }

    enum OpenedJSONField: String { case userFlows = "user_flows", linkedProjectIDs = "linked_project_ids" }

    static func decodeOpenedJSON<T: Decodable>(_ type: T.Type, from data: Data,
                                               field: OpenedJSONField) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(type, from: data)
        } catch {
            // Call sites provide fixed field names. Never record plaintext JSON.
            NativeDiagnostics.error("Plan opened content decoding failed field=\(field.rawValue)", category: "tasks")
            APIResponseDecodingDiagnostics.record(error: error, responseType: type)
            throw error
        }
    }

    private func requireMasterKey(_ fence: UserTasksAccountFence) async throws -> SymmetricKey {
        try await fence.check()
        guard let key = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else {
            throw UserTasksError.masterKeyUnavailable
        }
        try await fence.check()
        return key
    }

    private func requirePlanKey(_ record: EncryptedUserPlanRecord,
                                masterKey: SymmetricKey) async throws -> SymmetricKey {
        guard let wrapped = record.keyWrappers?.first(where: { $0.keyType == "master" })?.encryptedPlanKey else {
            throw UserTasksError.taskKeyUnavailable
        }
        return try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: masterKey)
    }

    private func keyWrappers(planKey: SymmetricKey, masterWrapper: String,
                             timestamp: Int, chatID: String?, projectIDs: [String],
                             teamID: String?, fence: UserTasksAccountFence) async throws -> [[String: Any]] {
        var result: [[String: Any]] = [["key_type": "master", "encrypted_plan_key": masterWrapper,
                                        "created_at": timestamp]]
        if let chatID {
            guard let chatKey = ChatKeyManager.shared.key(for: chatID) else {
                throw UserTasksError.missingLinkedKey("chat")
            }
            result.append(["key_type": "chat", "encrypted_plan_key": try ComposerEmbedCrypto.wrapKey(planKey, using: chatKey),
                           "hashed_chat_id": Self.sha256Hex(chatID), "created_at": timestamp])
        }
        let available = try await projects.listProjects(accountID: fence.accountID, teamID: teamID)
        try await fence.check()
        for projectID in projectIDs {
            guard let project = available.first(where: { $0.id == projectID }) else {
                throw UserTasksError.missingLinkedKey("Project")
            }
            result.append(["key_type": "project",
                           "encrypted_plan_key": try ComposerEmbedCrypto.wrapKey(planKey, using: project.key),
                           "hashed_project_id": Self.sha256Hex(projectID), "created_at": timestamp])
        }
        return result
    }

    private static func sha256Hex(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func jsonArray(_ values: [String]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: values)
        guard let string = String(data: data, encoding: .utf8) else { throw UserTasksError.invalidResponse }
        return string
    }

    private func decrypt(_ value: String?, key: SymmetricKey) throws -> String {
        guard let value, !value.isEmpty else { return "" }
        return try ComposerEmbedCrypto.decryptContent(value, using: key)
    }

    private func requestPinned(_ method: HTTPMethod, path: String,
                               body: [String: Any], fence: UserTasksAccountFence) async throws -> Data {
        try await fence.check()
        let data: Data = try await api.request(method, path: path,
            serverProfile: fence.serverProfile,
            body: JSONRawBody(data: try JSONSerialization.data(withJSONObject: body)),
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        return data
    }

    private func requestJSON<T: Decodable>(_ method: HTTPMethod, path: String,
                                            body: [String: Any], fence: UserTasksAccountFence) async throws -> T {
        let data = try await requestPinned(method, path: path, body: body, fence: fence)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            APIResponseDecodingDiagnostics.record(error: error, responseType: T.self)
            throw error
        }
    }
}
