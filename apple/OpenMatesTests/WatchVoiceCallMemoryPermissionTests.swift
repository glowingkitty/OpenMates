// Transient permission policy evidence, using synthetic data and injected authority.
import Combine
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class WatchVoiceCallMemoryPermissionTests: XCTestCase {
    private typealias Policy = NativeVoiceCallMemoryPolicy
    private let category = Policy.Category(appID: "travel", categoryID: "trips", title: "Synthetic trips")
    private func scope() -> NativeVoiceCallScope {
        .init(accountID: "synthetic-account", profileID: ServerProfile.current().id,
            workspaceGeneration: UUID(), chatID: "synthetic-chat", mateCategory: "general_knowledge")
    }
    private func context(validate: @escaping @MainActor @Sendable () throws -> Void = {}) -> WatchChatRequestContext {
        .init(accountID: "synthetic-account", profile: ServerProfile.current(),
            accountGeneration: WatchChatAccountLifecycle.generation, deadline: { _ in nil }, validate: validate)
    }
    private func frame(keys: [String] = ["travel:trips"]) -> NativeVoiceCallFrame {
        ["type": .string("voice_memory"), "call_id": .string("call-sentinel"),
            "function_call_id": .string("function-sentinel"), "assistant_message_id": .string("assistant-sentinel"),
            "user_message_id": .string("user-sentinel"), "payload": .object([
                "chat_id": .string("synthetic-chat"), "request_id": .string("request-sentinel"),
                "requested_keys": .array(keys.map { .string($0) })])]
    }
    private func snapshot() -> Policy.Snapshot {
        let unrelated = Policy.Category(appID: "travel", categoryID: "airlines", title: "Unrequested")
        return .init(availableKeys: [category.key, unrelated.key], categories: [category, unrelated], choices: [
            .init(id: "first", category: category, title: "First", value: "Synthetic first entry",
                content: .object(["name": .string("first"), "_original_item_key": .string("original-first"), "settings_group": .string("trips")])),
            .init(id: "second", category: category, title: "Second", value: "Synthetic second entry", content: .object(["name": .string("second")])),
            .init(id: "unrelated", category: unrelated, title: "Other", value: "Synthetic other entry", content: .object([:]))])
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy
    func testRequestRejectsWrongCallChatAndMissingBrokerIdentity() throws {
        let owner = scope()
        XCTAssertEqual(try Policy.Request(scope: owner, callID: "call-sentinel", frame: frame()).keys, ["travel-trips"])
        for key in ["call_id", "function_call_id", "assistant_message_id", "user_message_id"] {
            var invalid = frame(); invalid[key] = .string("")
            XCTAssertThrowsError(try Policy.Request(scope: owner, callID: "call-sentinel", frame: invalid))
        }
        var invalid = frame(); invalid["payload"] = .object(["request_id": .string("request"),
            "chat_id": .string("other-chat"), "requested_keys": .array([.string("travel:trips")])])
        XCTAssertThrowsError(try Policy.Request(scope: owner, callID: "call-sentinel", frame: invalid))
        invalid = frame(); invalid["payload"] = .object(["request_id": .string(""), "requested_keys": .array([.string("travel:trips")])])
        XCTAssertThrowsError(try Policy.Request(scope: owner, callID: "call-sentinel", frame: invalid))
        XCTAssertThrowsError(try Policy.Request(scope: owner, callID: "call-sentinel", frame: frame(keys: Array(repeating: "travel:trips", count: 65))))
        XCTAssertThrowsError(try Policy.Request(scope: owner, callID: "call-sentinel", frame: frame(keys: [String(repeating: "x", count: 257)])))
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy
    func testSelectionEnforcesExactAvailableCategoryAndPayloadBounds() throws {
        let request = try Policy.Request(scope: scope(), callID: "call-sentinel", frame: frame())
        let requested = try snapshot().requested(request)
        XCTAssertEqual(requested.categories.map(\.key), ["travel-trips"])
        XCTAssertEqual(requested.choices.map(\.id), ["first", "second"])
        XCTAssertThrowsError(try Policy.response(request, snapshot: requested, selectedIDs: ["unrelated"], includeSelected: true))
        XCTAssertThrowsError(try Policy.response(request, snapshot: requested, selectedIDs: [], includeSelected: true))
        XCTAssertThrowsError(try Policy.Snapshot(availableKeys: [], categories: requested.categories, choices: requested.choices).requested(request))
        XCTAssertThrowsError(try Policy.validateBounds(Array(repeating: "entry", count: 257)))
        XCTAssertThrowsError(try Policy.validateBounds([String(repeating: "x", count: 256 * 1_024 + 1)]))
        let oversized = Policy.Choice(id: "large", category: category, title: "Small label", value: "small",
            content: .object(["body": .string(String(repeating: "x", count: 256 * 1_024))]))
        XCTAssertThrowsError(try Policy.Snapshot(availableKeys: [category.key], categories: [category], choices: [oversized]).requested(request))
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy
    func testExplicitIncludeReturnsOnlySelectedEntryWithOriginalRequestIdentity() async throws {
        let sample = snapshot()
        let permission = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in sample }))
        let (task, subscription) = await present(permission)
        defer { subscription.cancel() }
        let prompt = try XCTUnwrap(permission.prompt)
        XCTAssertTrue(prompt.selectedIDs.isEmpty)
        XCTAssertEqual(prompt.categories.count, 1)
        permission.setSelected(true, choiceID: "unrelated", promptID: prompt.id)
        XCTAssertTrue(permission.prompt?.selectedIDs.isEmpty == true)
        permission.setSelected(true, choiceID: "first", promptID: prompt.id)
        await permission.decide(promptID: prompt.id, includeSelected: true)
        guard case .response(let reply) = try await task.value else { return XCTFail("Expected explicit response") }
        XCTAssertEqual(reply["call_id"], .string("call-sentinel"))
        XCTAssertEqual(reply["function_call_id"], .string("function-sentinel"))
        XCTAssertEqual(reply["request_id"], .string("request-sentinel"))
        XCTAssertEqual(reply["approved"], .bool(true))
        guard case .array(let entries)? = reply["settings_memories"] else { return XCTFail("Missing entries") }
        XCTAssertEqual(entries.count, 1)
        XCTAssertEqual(entries[0].object?["content"]?.object?["_original_item_key"], .string("original-first"))
        XCTAssertNil(permission.prompt)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy
    func testRejectAllAfterSelectionDisclosesNoEntry() async throws {
        let sample = snapshot()
        let permission = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in sample }))
        let (task, subscription) = await present(permission)
        defer { subscription.cancel() }
        let prompt = try XCTUnwrap(permission.prompt)
        permission.setSelected(true, choiceID: "first", promptID: prompt.id)
        await permission.decide(promptID: prompt.id, includeSelected: false)
        guard case .response(let reply) = try await task.value else { return XCTFail("Expected explicit rejection") }
        XCTAssertEqual(reply["approved"], .bool(false)); XCTAssertEqual(reply["settings_memories"], .array([]))
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy,video-call.chat.fixed-binding
    func testOwnerChangeAndExpiryCannotApproveOrRetainPlaintext() async throws {
        let sample = snapshot()
        var current = true
        var now = Date()
        let permission = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in sample }, now: { now }))
        let (task, subscription) = await present(permission, context: context { if !current { throw CancellationError() } })
        defer { subscription.cancel() }
        let first = try XCTUnwrap(permission.prompt)
        permission.setSelected(true, choiceID: "first", promptID: first.id)
        current = false
        await permission.decide(promptID: first.id, includeSelected: true)
        do { _ = try await task.value; XCTFail("Stale owner must cancel") } catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertNil(permission.prompt)
        current = true
        let (expired, nextSubscription) = await present(permission)
        defer { nextSubscription.cancel() }
        let second = try XCTUnwrap(permission.prompt)
        permission.setSelected(true, choiceID: "first", promptID: second.id)
        now = second.expiresAt
        await permission.decide(promptID: second.id, includeSelected: true)
        do { _ = try await expired.value; XCTFail("Expired decision must cancel") } catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertNil(permission.prompt)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy
    func testCancellationAndTeardownNeverCreateBrokerResponse() async throws {
        let sample = snapshot()
        let permission = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in sample }))
        let (task, subscription) = await present(permission)
        defer { subscription.cancel() }
        task.cancel()
        do { _ = try await task.value; XCTFail("Cancelled request must throw") } catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertNil(permission.prompt)
        let (replacement, nextSubscription) = await present(permission)
        defer { nextSubscription.cancel() }
        permission.invalidate()
        do { _ = try await replacement.value; XCTFail("Dismissal must throw") } catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertNil(permission.prompt)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy
    func testUnsupportedLiveCapabilityAndDocumentsNeverFabricateRejection() async throws {
        let permission = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in
            throw NativeVoiceCallError.unsupportedTransport
        }))
        let result = try await permission.request(scope: scope(), callID: "call-sentinel", frame: frame(), context: context(), validate: {})
        guard case .unsupported = result else { return XCTFail("Missing capability must be explicit") }
        XCTAssertNil(permission.prompt)
        let documents = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in
            XCTFail("Personal documents must not use an app memory loader")
            throw NativeVoiceCallError.contextUnavailable
        }))
        let documentResult = try await documents.request(scope: scope(), callID: "call-sentinel",
            frame: frame(keys: ["openmates:memories"]), context: context(), validate: {})
        guard case .unsupported = documentResult else { return XCTFail("Document boundary must remain explicit") }
        XCTAssertNil(documents.prompt)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy,video-call.chat.memories-and-focus
    func testFreshSnapshotAloneDeterminesAvailableMetadataAndOriginalSelectedContent() async throws {
        let loader = try loader()
        let keys = try await loader.availableMetadata(context: context())
        XCTAssertEqual(keys, ["openmates-memories", "privacy-pii_detection_settings", "travel-trips"])
        let loaded = try await loader.load(scope: scope(), context: context(), keys: ["travel-trips"])
        XCTAssertEqual(loaded.categories.map(\.key), ["travel-trips"])
        XCTAssertEqual(loaded.choices.count, 1)
        XCTAssertEqual(loaded.choices[0].title, "Synthetic journey")
        XCTAssertEqual(loaded.choices[0].content.object?["_original_item_key"], .string("original-trip"))
        XCTAssertNotNil(loaded.privacyFingerprint)
        do {
            _ = try await loader.load(scope: scope(), context: context(), keys: ["travel-airlines"])
            XCTFail("Public catalog examples cannot create availability")
        } catch { XCTAssertEqual(error as? NativeVoiceCallError, .unsupportedTransport) }
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy,video-call.chat.fixed-binding
    func testFreshLoaderRejectsWrongOwnerMalformedPrivacyAndOwnerChangeDuringDecryption() async throws {
        let wrongOwner = try loader(accountID: "other-account")
        do { _ = try await wrongOwner.availableMetadata(context: context()); XCTFail("Cross-owner response admitted") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .scopeChanged) }
        let malformed = try loader(malformedPrivacy: true)
        do { _ = try await malformed.availableMetadata(context: context()); XCTFail("Unreadable privacy policy dropped") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .invalidResponse) }
        var current = true
        var dependencies = try loader().dependencies
        dependencies.decrypt = { text, _ in current = false; return text }
        let rotated = WatchVoiceCallMemoryLoader(dependencies: dependencies)
        do {
            _ = try await rotated.availableMetadata(context: context { if !current { throw CancellationError() } })
            XCTFail("Owner rotation during decrypt admitted")
        } catch { XCTAssertTrue(error is CancellationError) }
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy
    func testChangedFreshPrivacySnapshotCannotReleasePreviouslySelectedEntry() async throws {
        let sample = snapshot()
        var reads = 0
        let permission = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in
            reads += 1
            var fresh = sample
            fresh.privacyFingerprint = reads == 1 ? "policy-before" : "policy-after"
            return fresh
        }))
        let (task, subscription) = await present(permission)
        defer { subscription.cancel() }
        let prompt = try XCTUnwrap(permission.prompt)
        permission.setSelected(true, choiceID: "first", promptID: prompt.id)
        await permission.decide(promptID: prompt.id, includeSelected: true)
        do { _ = try await task.value; XCTFail("Changed policy must cancel selection") } catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertEqual(reads, 2)
        XCTAssertNil(permission.prompt)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy,video-call.chat.fixed-binding
    func testTeardownCancelsInFlightConfirmationRefresh() async throws {
        let sample = snapshot()
        let refreshing = expectation(description: "Fresh approval snapshot started")
        var reads = 0
        let permission = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in
            reads += 1
            if reads == 2 {
                refreshing.fulfill()
                try await Task.sleep(for: .seconds(60))
            }
            return sample
        }))
        let (request, subscription) = await present(permission)
        defer { subscription.cancel() }
        let prompt = try XCTUnwrap(permission.prompt)
        permission.setSelected(true, choiceID: "first", promptID: prompt.id)
        let decision = Task { await permission.decide(promptID: prompt.id, includeSelected: true) }
        await fulfillment(of: [refreshing], timeout: 2)
        permission.invalidate()
        await decision.value
        do { _ = try await request.value; XCTFail("Teardown must cancel the pending broker response") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertNil(permission.prompt)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy,video-call.chat.fixed-binding
    func testCancelledOldRefreshCannotInvalidateReplacementPrompt() async throws {
        let sample = snapshot()
        let refreshing = expectation(description: "Old approval refresh suspended")
        var releaseApproval: CheckedContinuation<Void, Never>?
        var reads = 0
        let permission = WatchVoiceCallMemoryPermission(dependencies: .init(load: { _, _, _ in
            reads += 1
            if reads == 2 {
                await withCheckedContinuation { waiting in
                    releaseApproval = waiting
                    refreshing.fulfill()
                }
            }
            return sample
        }))
        let (oldRequest, oldSubscription) = await present(permission)
        defer { oldSubscription.cancel() }
        let old = try XCTUnwrap(permission.prompt)
        permission.setSelected(true, choiceID: "first", promptID: old.id)
        let oldDecision = Task { await permission.decide(promptID: old.id, includeSelected: true) }
        await fulfillment(of: [refreshing], timeout: 2)
        permission.invalidate()
        do { _ = try await oldRequest.value; XCTFail("Old request must cancel") }
        catch { XCTAssertTrue(error is CancellationError) }

        let (replacement, replacementSubscription) = await present(permission)
        defer { replacementSubscription.cancel() }
        let newPrompt = try XCTUnwrap(permission.prompt)
        releaseApproval?.resume()
        releaseApproval = nil
        await oldDecision.value

        XCTAssertEqual(permission.prompt?.id, newPrompt.id)
        XCTAssertFalse(permission.prompt?.deciding ?? true)
        await permission.decide(promptID: newPrompt.id, includeSelected: false)
        guard case .response(let reply) = try await replacement.value else {
            return XCTFail("Replacement must remain actionable")
        }
        XCTAssertEqual(reply["approved"], .bool(false))
        XCTAssertNil(permission.prompt)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.memories-and-focus,video-call.privacy
    func testMemoryMetadataDoesNotAuthorizeProjectFocusOrPrivateReads() async throws {
        let chatID = "00000000-0000-4000-8000-000000000001"
        let owner = NativeVoiceCallScope(accountID: "synthetic-account", profileID: ServerProfile.current().id,
            workspaceGeneration: UUID(), chatID: chatID, mateCategory: "general_knowledge")
        var loader = NativeVoiceCallCanonicalContextLoader(request: { _, path in
            if path.contains("/compression-checkpoints?") {
                return try JSONEncoder().encode(["checkpoints": NativeVoiceCallJSON.array([])])
            }
            guard path.contains("/messages/window?") else { XCTFail("Unexpected private reader"); throw NativeVoiceCallError.contextUnavailable }
            return try JSONEncoder().encode(["messages": NativeVoiceCallJSON.array([]), "has_more_before": .bool(false)])
        }, decrypt: { _, _ in "project-focus:private-project" }, metadata: { _ in
            ["id": .string(chatID), "team_id": .null, "encrypted_active_focus_id": .string("cipher-focus")]
        }, isCurrent: { _ in true })
        loader.memoryMetadata = { _ in
            XCTFail("Project focus must be denied before memory availability is loaded")
            return ["travel-trips"]
        }
        do { _ = try await loader.load(scope: owner); XCTFail("Memory metadata granted Project authority") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .contextUnavailable) }
        XCTAssertNil(loader.projectContext)
    }

    private func loader(accountID: String = "synthetic-account", malformedPrivacy: Bool = false) throws -> WatchVoiceCallMemoryLoader {
        func text(_ fields: NativeVoiceCallFrame) throws -> String { String(decoding: try JSONEncoder().encode(fields), as: UTF8.self) }
        let settings = try text(["memory_documents": .array([.object(["id": .string("document-metadata-only")])])])
        let trip = try text(["name": .string("Synthetic journey"), "_original_item_key": .string("original-trip")])
        let privacy = try text(["masterEnabled": .bool(true), "categories": malformedPrivacy ? .string("invalid") : .object(["email": .bool(false)])])
        let response: NativeVoiceCallFrame = ["success": .bool(true), "user": .object(["id": .string(accountID)]),
            "personal_memories": .object(["encrypted_settings": .string(settings), "memories": .array([
                .object(["id": .string("row-trip"), "app_id": .string("travel"), "item_type": .string("trips"),
                    "item_key": .string("hashed-trip-key"), "encrypted_item_json": .string(trip)]),
                .object(["id": .string("row-policy"), "app_id": .string("privacy"), "item_type": .string("pii_detection_settings"),
                    "item_key": .string("policy"), "encrypted_item_json": .string(privacy)])])])]
        let catalog: NativeVoiceCallFrame = ["apps": .object(["travel": .object(["name": .string("Travel"),
            "settings_and_memories": .array([.object(["id": .string("trips"), "name": .string("Trips"),
                "schema_definition": .object(["properties": .object(["name": .object(["is_title": .bool(true)])])])]),
                .object(["id": .string("airlines"), "name": .string("Airlines")])])])])]
        let sessionBytes = try JSONEncoder().encode(response), catalogBytes = try JSONEncoder().encode(catalog)
        return WatchVoiceCallMemoryLoader(dependencies: .init(request: { method, path, body, context in
            try context.check()
            if path == "/v1/auth/session" {
                XCTAssertEqual(method, .post)
                let sent = try JSONDecoder().decode(NativeVoiceCallFrame.self, from: XCTUnwrap(body))
                XCTAssertEqual(sent["session_id"], .string("synthetic-session"))
                XCTAssertEqual(sent["include_personal_memories"], .bool(true))
                return sessionBytes
            }
            XCTAssertEqual(path, "/v1/apps/metadata?include_unavailable=true")
            return catalogBytes
        }, masterKey: { _ in SymmetricKey(data: Data(repeating: 1, count: 32)) },
            decrypt: { text, _ in text }, sessionID: { "synthetic-session" }, localize: { $0 }))
    }

    private func present(_ permission: WatchVoiceCallMemoryPermission, context requestContext: WatchChatRequestContext? = nil)
        async -> (Task<NativeVoiceCallArtifactDisposition, any Error>, AnyCancellable) {
        let presented = expectation(description: "Explicit permission presented")
        let subscription = permission.$prompt.dropFirst().compactMap { $0 }.prefix(1).sink { _ in presented.fulfill() }
        let owner = scope(), request = frame(), requestContext = requestContext ?? context()
        let task = Task { try await permission.request(scope: owner, callID: "call-sentinel", frame: request, context: requestContext, validate: {}) }
        await fulfillment(of: [presented], timeout: 2)
        return (task, subscription)
    }
}
