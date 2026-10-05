import XCTest
@testable import OpenMates
final class FocusPhaseTests: XCTestCase {
    private let event = #"{"type":"focus_phase_changed","event_id":"11111111-1111-4111-8111-111111111111","chat_id":"22222222-2222-4222-8222-222222222222","focus_id":"jobs-career_insights","run_id":"33333333-3333-4333-8333-333333333333","version":2,"previous_phase_id":"confirm_profile","phase_id":"explore","phase_title":"Explore career directions","direction":"forward","created_at":1}"#
    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases,focus-modes.history-events
    func testPhaseHistoryLinksToFocusDetailsWithoutReplayingState() throws {
        let parsed = try XCTUnwrap(FocusPhaseEvent.parse(event))
        XCTAssertEqual(parsed.phaseTitle, "Explore career directions")
        XCTAssertEqual(parsed.detailPath, "apps/jobs/focus/career_insights")
        XCTAssertEqual(parsed.direction, "forward")
        XCTAssertNil(FocusPhaseEvent.parse("ordinary system notice"))
    }
    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases
    func testPhaseCiphertextSurvivesChatDecodeAndCopy() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: Data(#"{"id":"chat","created_at":1,"encrypted_focus_phase_state":"opaque","messages_v":2}"#.utf8))
        XCTAssertEqual(chat.encryptedFocusPhaseState, "opaque")
        XCTAssertEqual(chat.withMessagesVersion(3).encryptedFocusPhaseState, "opaque")
    }
    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases
    func testProjectTextUsesPhasesAndNoQuestionCountGate() {
        let instruction = "---\nphases_version: 1\nphases:\n  - id: understand\n    title: Understand\n    instructions: Ask five questions by default and honor skip requests.\n    requirements:\n      - id: enough\n        text: Enough context or explicit request to proceed.\n---\nGlobal instruction"
        let phases = FocusPhaseDefinition.fromInstruction(instruction)
        XCTAssertEqual(phases.count, 1)
        XCTAssertTrue(phases.first?.instructions.contains("honor skip") == true)
        XCTAssertEqual(phases.first?.requirements.first?.id, "enough")
        XCTAssertTrue(FocusPhaseDefinition.fromInstruction("Legacy instruction").isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.countdown,projects.focus.inferred-consent
    @MainActor
    func testProjectCountdownCancelPreventsPrivateActivation() async {
        let store = PendingProjectFocusStore()
        let scope = UUID(), requestID = UUID().uuidString.lowercased()
        var privateLoads = 0
        store.configure(scope: scope, complete: { _ in privateLoads += 1 }, reject: { _ in })
        store.ingest(fields: ["chat_id": "chat", "embed_id": requestID,
            "focus_id": "project-11111111-1111-4111-8111-111111111111",
            "expires_at": Date().timeIntervalSince1970 + 4], scope: scope)
        XCTAssertEqual(store.entry(chatID: "chat", embedID: requestID)?.status, .waiting)
        XCTAssertEqual(privateLoads, 0)
        store.cancel(chatID: "chat", embedID: requestID)
        do { try await store.confirmBeforeContext(chatID: "chat"); XCTFail("Cancelled countdown must reject context") }
        catch {}
        XCTAssertEqual(privateLoads, 0)
        XCTAssertEqual(store.entry(chatID: "chat", embedID: requestID)?.status, .cancelled)
        store.clearAfterNoActiveBase(chatID: "chat")
        do { try await store.confirmBeforeContext(chatID: "chat") }
        catch { XCTFail("Later regular turn with no active base should proceed") }
        XCTAssertEqual(privateLoads, 0)
        store.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.countdown,projects.files.no-server-decryption-authority
    @MainActor
    func testProjectDeadlineRejectionNeverLoadsPrivateSettings() async {
        let store = PendingProjectFocusStore(), scope = UUID()
        let requestID = UUID().uuidString.lowercased()
        var confirmationAttempts = 0
        store.configure(scope: scope, complete: { _ in
            confirmationAttempts += 1
            throw ProjectsWorkspaceError.invalidContext
        }, reject: { _ in })
        store.ingest(fields: ["chat_id": "chat", "embed_id": requestID,
            "focus_id": "project-11111111-1111-4111-8111-111111111111",
            "expires_at": Date().timeIntervalSince1970 - 1], scope: scope)
        do { try await store.confirmBeforeContext(chatID: "chat"); XCTFail("Server rejection must reject context") }
        catch {}
        XCTAssertEqual(confirmationAttempts, 1)
        XCTAssertEqual(store.entry(chatID: "chat", embedID: requestID)?.status, .failed)
        store.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.countdown,projects.focus.inferred-consent
    @MainActor
    func testHistoryAndOldAccountCannotStartProjectCountdown() async throws {
        let store = PendingProjectFocusStore(), scope = UUID()
        let requestID = UUID().uuidString.lowercased()
        var activations = 0
        store.configure(scope: scope, complete: { _ in activations += 1 }, reject: { _ in })
        // Merely querying a historical embed has no activation side effect.
        XCTAssertNil(store.entry(chatID: "chat", embedID: requestID))
        try await store.confirmBeforeContext(chatID: "chat")
        store.ingest(fields: ["chat_id": "chat", "embed_id": requestID,
            "focus_id": "project-11111111-1111-4111-8111-111111111111",
            "expires_at": Date().timeIntervalSince1970 - 1], scope: UUID())
        XCTAssertNil(store.entry(chatID: "chat", embedID: requestID))
        XCTAssertEqual(activations, 0)
        store.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=rules.transparency.applied-set
    func testAppliedRulesRetainOnlyValidatedExactGuides() throws {
        let guide: [String: Any] = ["id": "rule", "title": "Research guide", "source": "project",
            "project_id": "project", "revision": String(repeating: "a", count: 64), "body": "Cite every claim."]
        var payload: [String: Any] = ["type": "rules_loaded", "set_key": "set", "count": 1, "rules": [guide]]
        guard case let .rulesLoaded(key, rules) = try XCTUnwrap(AgentContextEvent.parse(payload)) else { return XCTFail("Expected validated Rules") }
        XCTAssertEqual(key, "set"); XCTAssertEqual(rules.first?.body, "Cite every claim.")
        XCTAssertEqual(rules.first?.revision, String(repeating: "a", count: 64)); XCTAssertEqual(rules.first?.source, "project")
        payload["count"] = 2; XCTAssertNil(AgentContextEvent.parse(payload), "A count without the actual guides is not a receipt")
        payload["rules"] = [guide, guide]; XCTAssertNil(AgentContextEvent.parse(payload), "Duplicate identities cannot inflate the applied set")
        var invalid = guide; invalid["revision"] = "unknown"; payload["count"] = 1; payload["rules"] = [invalid]
        XCTAssertNil(AgentContextEvent.parse(payload))
    }

    // contract-test: supporting surface=gui.apple assertions=rules.transparency.applied-set,chats.direction.reviewed-correction
    func testLiveContextReceiptRequiresMatchingChatAndStableEventIdentity() throws {
        let chatID = "22222222-2222-4222-8222-222222222222", eventID = "11111111-1111-4111-8111-111111111111"
        let notice = "Chat is drifting too far away from the goals. Correction instruction was sent."
        var event: [String: Any] = ["type": "chat_direction_correction", "chat_id": chatID, "event_id": eventID,
            "created_at": 1, "notice": notice, "instruction": "Return to the original goal.", "delivery_id": "delivery"]
        let receipt = try XCTUnwrap(AppliedChatContextReceipt.parse(["chat_id": chatID, "event": event]))
        XCTAssertEqual(receipt.messageID, eventID)
        XCTAssertEqual(AgentContextEvent.parse(receipt.content), .directionCorrection(notice: notice, instruction: "Return to the original goal.", deliveryID: "delivery"))
        XCTAssertNil(AppliedChatContextReceipt.parse(["chat_id": eventID, "event": event]))
        event["event_id"] = "missing-stable-id"; XCTAssertNil(AppliedChatContextReceipt.parse(["chat_id": chatID, "event": event]))
        event["event_id"] = eventID; event["instruction"] = ""; XCTAssertNil(AppliedChatContextReceipt.parse(["chat_id": chatID, "event": event]))
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.project-authoring-click
    @MainActor
    func testHistoricalAuthoringReceiptParsingDoesNotStartAJob() throws {
        let before = NativeProjectAuthoringClient.shared.jobs.count
        let value: [String: Any] = ["type": "project_authoring_recommendation", "recommendation_id": "recommendation",
            "chat_id": "chat", "project_id": "project", "kind": "focus", "action": "create", "expires_at": 1]
        guard case let .authoring(recommendations) = try XCTUnwrap(AgentContextEvent.parse(value)) else { return XCTFail("Expected recommendation") }
        XCTAssertTrue(recommendations[0].isExpired)
        XCTAssertEqual(NativeProjectAuthoringClient.shared.jobs.count, before, "Parsing and replay grant no authoring authority")
        var invalid = value; invalid["kind"] = "arbitrary_file"; XCTAssertNil(AgentContextEvent.parse(invalid))
        invalid = value; invalid["action"] = "run"; XCTAssertNil(AgentContextEvent.parse(invalid))
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.project-authoring-click
    @MainActor
    func testAuthoringHistoryIsBoundedAndKeepsTheOriginalUserGoal() {
        func message(_ id: Int, role: MessageRole, content: String) -> Message {
            Message(id: String(id), chatId: "chat", role: role, content: content, encryptedContent: nil,
                    createdAt: "1", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        }
        var messages = [message(0, role: .system, content: "Private Rules are not authoring conversation"),
                        message(1, role: .user, content: "Original research goal")]
        messages += (2..<65).map { message($0, role: .assistant, content: String(repeating: "x", count: 2000)) }
        let history = NativeProjectAuthoringClient.boundedHistory(messages)
        XCTAssertEqual(history.count, 9); XCTAssertEqual(history.first?["content"], "Original research goal")
        XCTAssertFalse(history.contains { $0["role"] == "system" })
        XCTAssertLessThanOrEqual(history.reduce(0) { $0 + ($1["content"]?.count ?? 0) }, 12_000)
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.project-authoring-persistence,focus-modes.project-authoring-click
    @MainActor
    func testPrivateGuideValidationRejectsDuplicateYamlKeysAndPhases() throws {
        let valid = "---\nname: Research\ndescription: Research carefully\nwhen_to_use: For research\n---\nCite every claim."
        XCTAssertEqual(try NativeProjectAuthoringClient.parseFocusDocument(valid)["instructions"] as? String, "Cite every claim.")
        XCTAssertThrowsError(try NativeProjectAuthoringClient.parseFocusDocument(valid.replacingOccurrences(of: "name: Research", with: "name: First\nname: Second")))
        XCTAssertThrowsError(try NativeProjectAuthoringClient.parseFocusDocument(valid.replacingOccurrences(of: "name: Research", with: "name: &name Research")))
        let phases = valid.replacingOccurrences(of: "when_to_use: For research", with: "when_to_use: For research\nphases:\n - id: one\n   name: One\n   instructions: First\n - id: one\n   name: Two\n   instructions: Second")
        XCTAssertThrowsError(try NativeProjectAuthoringClient.parseFocusDocument(phases))
        let rule = "---\ntitle: Research\ndescription: Research carefully\nwhen_to_use: For research\n---\nCite every claim."
        XCTAssertTrue(NativeProjectAuthoringClient.validRuleDocument(rule))
        XCTAssertFalse(NativeProjectAuthoringClient.validRuleDocument(rule.replacingOccurrences(of: "title: Research", with: "title: First\ntitle: Second")))
        XCTAssertFalse(NativeProjectAuthoringClient.validRuleDocument(rule.replacingOccurrences(of: "\n---\nCite", with: "\n---invalid\nCite")))
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.project-authoring-persistence,projects.files.exact-patch
    @MainActor
    func testAuthoringPatchPreservesExactFileBytesAndOpaqueMetadataRevision() throws {
        let path = ".openmates/focuses/research/SKILL.md"
        for (old, next) in [("previous\n", "next"), ("previous", "next\n"), ("", "first\n"), ("previous\n", "")] {
            let patch = NativeProjectAuthoringClient.replacementPatch(path: path, old: old, next: next)
            XCTAssertEqual(try ProjectHostedPatch.apply(patch, to: old, path: path), next)
        }
        let metadata: [String: Any] = ["updated_at": 1, "encrypted_metadata": "cipher", "target_id_hash": "hash"]
        XCTAssertEqual(NativeProjectAuthoringClient.itemRevision(metadata), "ec4ba0985f8398164278fe7cba967311d6a3e303597f15b82801d2a565e4c045")
        var changed = metadata; changed["encrypted_metadata"] = "other"
        XCTAssertNotEqual(NativeProjectAuthoringClient.itemRevision(metadata), NativeProjectAuthoringClient.itemRevision(changed))
        let mutation = try ProjectFileMutation(operation: "create_file", operationID: "project-authoring:job",
            arguments: ["path": path, "expected_base": NSNull(), "content": "first\n"])
        let descriptor = ProjectFileJob(authoringOperationID: "project-authoring:job", chatID: "chat", projectID: "project", mutation: mutation)
        XCTAssertFalse(descriptor.isLive, "Hosted authoring does not fabricate a source lease")
    }


    // contract-test: supporting surface=gui.apple assertions=chats.direction.reviewed-correction
    @MainActor
    func testAcceptedPlanSnapshotNeedsActualCurrentApprovalAndChatLink() throws {
        let id = "11111111-1111-4111-8111-111111111111"
        let plan: [String: Any] = ["plan_id": id, "version": 3, "primary_chat_id": "chat", "status": "active",
            "approval_state": "approved", "submitted_revision_id": "approved-revision", "approved_revision_id": "approved-revision"]
        XCTAssertEqual(try XCTUnwrap(NativeProjectAuthoringClient.acceptedPlanIdentity(plan, chatID: "chat"))["version"] as? Int, 3)
        XCTAssertEqual(NativeProjectAuthoringClient.specialistItemID(projectID: id, focusID: "project-focus:" + id + ":selected"), "selected")
        XCTAssertNil(NativeProjectAuthoringClient.acceptedPlanIdentity(plan, chatID: "other-chat"))
        for (key, value) in [("approval_state", "unapproved"), ("submitted_revision_id", "new-unapproved-revision"), ("status", "completed"), ("status", "draft")] {
            var stale = plan; stale[key] = value
            XCTAssertNil(NativeProjectAuthoringClient.acceptedPlanIdentity(stale, chatID: "chat"))
        }
        let summary = try XCTUnwrap(NativeProjectAuthoringClient.acceptedPlanSummary(["goal": "Original goal", "scope_in": "Research", "constraints": String(repeating: "x", count: 6000)]))
        XCTAssertTrue(summary.hasPrefix("Goal: Original goal\nScope in: Research")); XCTAssertLessThanOrEqual(summary.count, 4000)
        XCTAssertNil(NativeProjectAuthoringClient.acceptedPlanSummary(["goal": " "]))
    }


    // contract-test: supporting surface=gui.apple assertions=focus-modes.countdown,projects.focus.inferred-consent
    @MainActor
    func testCancellationDuringPrivateLoadingPreventsDecisionCommit() async {
        let store = PendingProjectFocusStore(), scope = UUID(), requestID = UUID().uuidString.lowercased()
        let loading = expectation(description: "Private loading reached"), projectID = "11111111-1111-4111-8111-111111111111"
        var suspended: CheckedContinuation<Void, Never>?, acceptedDecisions = 0
        store.configure(scope: scope, complete: { record in
            await withCheckedContinuation { continuation in suspended = continuation; loading.fulfill() }
            try store.beginCommit(record)
            acceptedDecisions += 1
        }, reject: { _ in })
        store.ingest(fields: ["chat_id": "chat", "embed_id": requestID, "focus_id": "project-" + projectID,
                              "expires_at": Date().timeIntervalSince1970 - 1], scope: scope)
        await fulfillment(of: [loading], timeout: 2)
        XCTAssertEqual(store.entry(chatID: "chat", embedID: requestID)?.status, .confirming)
        store.cancel(chatID: "chat", embedID: requestID)
        suspended?.resume(); suspended = nil
        do { try await store.confirmBeforeContext(chatID: "chat"); XCTFail("Cancelled loading must not grant context") } catch {}
        XCTAssertEqual(acceptedDecisions, 0)
        XCTAssertEqual(store.entry(chatID: "chat", embedID: requestID)?.status, .cancelled)
        store.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.countdown,projects.focus.inferred-consent
    @MainActor
    func testCommittedDecisionWaitsForAckAndCannotPretendCancellation() async throws {
        let store = PendingProjectFocusStore(), scope = UUID(), requestID = UUID().uuidString.lowercased()
        let committed = expectation(description: "Decision committed")
        var suspended: CheckedContinuation<Void, Never>?, rejections = 0
        store.configure(scope: scope, complete: { record in
            try store.beginCommit(record)
            await withCheckedContinuation { continuation in suspended = continuation; committed.fulfill() }
        }, reject: { _ in rejections += 1 })
        store.ingest(fields: ["chat_id": "chat", "embed_id": requestID,
                              "focus_id": "project-11111111-1111-4111-8111-111111111111",
                              "expires_at": Date().timeIntervalSince1970 - 1], scope: scope)
        await fulfillment(of: [committed], timeout: 2)
        let entry = try XCTUnwrap(store.entry(chatID: "chat", embedID: requestID))
        XCTAssertEqual(entry.status, .committing); XCTAssertTrue(store.isCurrent(entry.record))
        XCTAssertThrowsError(try store.beginCommit(entry.record), "A decision cannot commit twice")
        store.cancel(chatID: "chat", embedID: requestID)
        XCTAssertEqual(store.entry(chatID: "chat", embedID: requestID)?.status, .committing)
        XCTAssertEqual(rejections, 0, "A sent accepted decision cannot claim a successful late cancel")
        suspended?.resume(); suspended = nil
        try await store.confirmBeforeContext(chatID: "chat")
        XCTAssertEqual(store.entry(chatID: "chat", embedID: requestID)?.status, .activated)
        store.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.countdown,projects.focus.inferred-consent
    @MainActor
    func testSupersededCommittedDecisionCannotRestoreAnOldBinding() async throws {
        for change in ["new-proposal", "manual-activation", "scope-change"] {
            let store = PendingProjectFocusStore(), scope = UUID(), oldID = UUID().uuidString.lowercased(), newID = UUID().uuidString.lowercased()
            let committed = expectation(description: "Committed " + change), returned = expectation(description: "Old callback returned " + change)
            var suspended: CheckedContinuation<Void, Never>?
            store.configure(scope: scope, complete: { record in
                try store.beginCommit(record)
                await withCheckedContinuation { continuation in suspended = continuation; committed.fulfill() }
                returned.fulfill()
            }, reject: { _ in XCTFail("Supersession must preserve the newer authoritative binding") })
            store.ingest(fields: ["chat_id": "chat", "embed_id": oldID,
                "focus_id": "project-11111111-1111-4111-8111-111111111111", "expires_at": Date().timeIntervalSince1970 - 1], scope: scope)
            await fulfillment(of: [committed], timeout: 2)
            let old = try XCTUnwrap(store.entry(chatID: "chat", embedID: oldID))
            if change == "new-proposal" {
                store.ingest(fields: ["chat_id": "chat", "embed_id": newID,
                    "focus_id": "project-22222222-2222-4222-8222-222222222222", "expires_at": Date().timeIntervalSince1970 + 60], scope: scope)
            } else if change == "manual-activation" { store.clearForExplicitActivation(chatID: "chat") }
            else { store.configure(scope: UUID(), complete: { _ in }, reject: { _ in }) }
            XCTAssertFalse(store.isCurrent(old.record))
            suspended?.resume(); suspended = nil
            await fulfillment(of: [returned], timeout: 2)
            XCTAssertNotEqual(store.entry(chatID: "chat", embedID: oldID)?.status, .activated)
            if change == "new-proposal" {
                let current = try XCTUnwrap(store.entry(chatID: "chat", embedID: newID))
                XCTAssertEqual(current.status, .waiting); XCTAssertTrue(store.isCurrent(current.record))
            }
            store.reset()
        }
    }

}
