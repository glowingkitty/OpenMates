// Deterministic recipient-only sharing tests. Synthetic ciphertext and no networking.
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class SharedChatRecipientTests: XCTestCase {
    private let id = "recipient-fixture"
    private let rawKey = Data(repeating: 7, count: 32)
    // Independently calculated PBKDF2-SHA256 vector (100000 rounds, web salt).
    private let outerKey = SymmetricKey(data: Data([
        0x66, 0xf2, 0x4d, 0x0c, 0xee, 0xd4, 0x64, 0x60, 0xca, 0x3b, 0x8c, 0x26, 0x9f, 0x57, 0x39, 0x72,
        0x5c, 0x25, 0x55, 0x08, 0x52, 0xee, 0x6f, 0xca, 0x9a, 0x47, 0x93, 0x59, 0x4b, 0x19, 0x44, 0x1a]))

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testWebPBKDFAndAESBlobAtExactExpiryBoundary() async throws {
        let blob = try await fixtureBlob(duration: 60)
        let key = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: 1060, password: nil)
        XCTAssertEqual(key.withUnsafeBytes { Data($0) }, rawKey)
        do {
            _ = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: 1061, password: nil)
            XCTFail("Expired shares must not hydrate")
        } catch { XCTAssertEqual(error as? SharedChatRecipientError, .expired) }
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testPasswordRequiredBeforeExpiryAndInvalidPassword() async throws {
        let blob = try await fixtureBlob(duration: 60, password: "fixturePwd")
        do {
            _ = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: 1061, password: nil)
            XCTFail("Password gate required")
        } catch { XCTAssertEqual(error as? SharedChatRecipientError, .passwordRequired) }
        do {
            _ = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: 1000, password: "incorrect")
            XCTFail("Incorrect password accepted")
        } catch { XCTAssertEqual(error as? SharedChatRecipientError, .invalidPassword) }
        let key = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: 1000, password: "fixturePwd")
        XCTAssertEqual(key.withUnsafeBytes { Data($0) }, rawKey)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testRejectsUnsafeURLsAndDuplicateFragments() {
        for value in [
            "http://openmates.org/share/chat/chat#key=abc", "https://evil.example/share/chat/chat#key=abc",
            "https://openmates.org@evil.example/share/chat/chat#key=abc", "https://openmates.org:443/share/chat/chat#key=abc",
            "https://openmates.org/share/chat/chat?key=abc#key=abc", "https://openmates.org/share/embed/chat#key=abc",
            "https://openmates.org/share/chat/chat#key=abc&key=def", "https://openmates.org/s/token123#bad/key",
            "https://openmates.org/share/chat/chat#key=abc&messageid=../other"
        ] { XCTAssertThrowsError(try SharedChatRecipientLink.parse(URL(string: value)!)) }
        XCTAssertNoThrow(try SharedChatRecipientLink.parse(URL(string: "https://app.dev.openmates.org/s/token123#validKey123")!))
        XCTAssertNoThrow(try SharedChatRecipientLink.parse(URL(string: "https://openmates.org/s/#token123-validKey123")!))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open,chat-share-settings.readonly-viewer-controls
    func testHydratesAuthenticatedCiphertextWithoutInstallingOwnerKey() async throws {
        let transport = FixtureTransport()
        let key = SymmetricKey(data: rawKey)
        let title = try content("Synthetic shared title", key: key)
        let body = try content("Synthetic shared message", key: key)
        transport.manifest = ["chat_id": id, "encrypted_title": title, "share_pii": false,
                              "plans": [["id": "opaque-plan", "encrypted_content": "opaque"]]]
        transport.window = ["chat_id": id, "messages": [["message_id": "message1", "role": "user", "created_at": 1000,
                           "encrypted_content": body, "content": "Unauthenticated bypass"]], "has_more": false]
        let ownerGeneration = ChatKeyManager.shared.cacheGeneration
        XCTAssertNil(ChatKeyManager.shared.key(for: id))
        let url = try await fixtureURL()
        let context = try await SharedChatRecipientService(transport: transport, now: { 1000 }).load(url)
        XCTAssertEqual(context.chat.title, "Synthetic shared title")
        XCTAssertEqual(context.messages.first?.content, "Synthetic shared message")
        XCTAssertEqual(context.originalURL, url)
        XCTAssertNil(context.chat.encryptedChatKey)
        XCTAssertFalse(context.sharePII)
        XCTAssertNil(ChatKeyManager.shared.key(for: id))
        XCTAssertEqual(ChatKeyManager.shared.cacheGeneration, ownerGeneration)
        XCTAssertTrue(transport.requests.allSatisfy { $0.fragment == nil && $0.host == "api.openmates.org" })
        XCTAssertTrue(transport.requests.allSatisfy { !$0.absoluteString.contains("key=") })
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testEarlierWindowMergesCanonicalIDsAndStopsAtNonadvancingCursor() async throws {
        let transport = FixtureTransport()
        let key = SymmetricKey(data: rawKey)
        transport.manifest = ["chat_id": id, "encrypted_title": try content("Synthetic title", key: key)]
        transport.window = ["chat_id": id, "messages": [
            ["id": "database-current", "client_message_id": "current", "role": "user", "created_at": 1000,
             "encrypted_content": try content("Current message", key: key)]
        ], "has_more": true, "next_before_timestamp": 1000, "next_before_message_id": "current"]
        let service = SharedChatRecipientService(transport: transport, now: { 1000 })
        let context = try await service.load(fixtureURL())
        transport.window = ["chat_id": id, "messages": [
            ["id": "database-earlier", "client_message_id": "earlier", "role": "user", "created_at": 999,
             "encrypted_content": try content("Earlier message", key: key)],
            ["id": "database-duplicate", "client_message_id": "current", "role": "user", "created_at": 1000,
             "encrypted_content": try content("Current message", key: key)]
        ], "has_more": true, "next_before_timestamp": 1000, "next_before_message_id": "current"]
        let updated = try await service.loadEarlier(context)
        XCTAssertEqual(updated.messages.map(\.id), ["earlier", "current"])
        XCTAssertFalse(updated.hasMoreBefore)
        let request = try XCTUnwrap(transport.requests.last)
        let query = try XCTUnwrap(URLComponents(url: request, resolvingAgainstBaseURL: false)?.queryItems)
        XCTAssertEqual(query.first { $0.name == "before_timestamp" }?.value, "1000")
        XCTAssertEqual(query.first { $0.name == "before_message_id" }?.value, "current")
        XCTAssertNil(ChatKeyManager.shared.key(for: id))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testDummyCiphertextDoesNotProduceReadableContent() async throws {
        let transport = FixtureTransport()
        transport.manifest = ["chat_id": id, "encrypted_title": Data(repeating: 4, count: 16).base64EncodedString()]
        transport.window = ["messages": []]
        do {
            _ = try await SharedChatRecipientService(transport: transport).load(fixtureURL())
            XCTFail("Dummy response accepted")
        } catch { XCTAssertEqual(error as? SharedChatRecipientError, .unavailable) }
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testCanonicalClientIdentityPreservesMessageTargetAndEmbedAssociation() async throws {
        let transport = FixtureTransport()
        let key = SymmetricKey(data: rawKey)
        let body = try content("```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"identity-embed\",\"app_id\":\"web\",\"skill_id\":\"search\"}\n```", key: key)
        transport.manifest = ["chat_id": id, "encrypted_title": try content("Synthetic title", key: key)]
        transport.window = ["chat_id": id, "messages": [
            ["id": "database-row-1", "message_id": "wire-message-1", "client_message_id": "client-message-1",
             "chatId": "unrelated-chat", "role": "assistant", "created_at": 1000, "encrypted_content": body],
            ["id": "database-row-2", "message_id": "wire-message-2", "client_message_id": "",
             "role": "user", "created_at": 1001, "encrypted_content": try content("Second message", key: key)],
            ["id": "database-row-3", "message_id": "", "role": "user", "created_at": 1002,
             "encrypted_content": try content("Third message", key: key)],
            ["id": "duplicate-database-row", "message_id": "other-wire-id", "client_message_id": "client-message-1",
             "role": "assistant", "created_at": 1000, "encrypted_content": body]
        ], "has_more": false]
        let baseURL = try await fixtureURL()
        let url = URL(string: "\(baseURL.absoluteString)&messageid=client-message-1")!
        let context = try await SharedChatRecipientService(transport: transport, now: { 1000 }).load(url)
        XCTAssertEqual(context.messages.map(\.id), ["client-message-1", "wire-message-2", "database-row-3"])
        XCTAssertTrue(context.messages.allSatisfy { $0.chatId == id })
        let target = try XCTUnwrap(context.messages.first { $0.id == context.targetMessageID })
        XCTAssertEqual(target.embedRefs?.map(\.id), ["identity-embed"])
        XCTAssertNotNil(context.embeds["identity-embed"])
        let request = try XCTUnwrap(transport.requests.first { $0.path.hasSuffix("/messages") })
        XCTAssertEqual(URLComponents(url: request, resolvingAgainstBaseURL: false)?.queryItems?
            .first(where: { $0.name == "target_message_id" })?.value, "client-message-1")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testWrappedEmbedAndLegacyChildHydrateInRecipientContext() async throws {
        let transport = FixtureTransport()
        let key = SymmetricKey(data: rawKey), embedKey = SymmetricKey(data: Data(repeating: 8, count: 32))
        let parentID = "parent", childID = "child"
        func hash(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
        transport.manifest = ["chat_id": id, "encrypted_title": try content("Title", key: key), "embeds": [
            ["embed_id": parentID, "embed_type": "app-skill-use", "embed_ids": " | \(childID) | ",
             "encrypted_content": try content("{\"title\":\"Parent\"}", key: embedKey)],
            ["embed_id": childID, "embed_type": "web-website", "encrypted_content": try content("{\"title\":\"Child\"}", key: embedKey)]
        ], "embed_keys": [["key_type": "chat", "hashed_chat_id": hash(id), "hashed_embed_id": hash(parentID),
                          "encrypted_embed_key": try sealed(Data(repeating: 8, count: 32), key: key).base64EncodedString()]]]
        transport.window = ["messages": []]
        let context = try await SharedChatRecipientService(transport: transport).load(fixtureURL())
        XCTAssertEqual(context.embeds[parentID]?.rawData?["title"]?.value as? String, "Parent")
        XCTAssertEqual(context.embeds[childID]?.rawData?["title"]?.value as? String, "Child")
        XCTAssertEqual(context.embeds[parentID]?.childEmbedIds, [childID])
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testCancellationCannotPublishEvenWhenTransportIgnoresCancellation() async throws {
        let transport = FixtureTransport()
        transport.suspendTime = true
        transport.manifest = ["chat_id": id, "encrypted_title": try content("Title", key: SymmetricKey(data: rawKey))]
        transport.window = ["messages": []]
        let model = SharedChatRecipientModel(service: SharedChatRecipientService(transport: transport))
        let loading = model.open(try await fixtureURL())
        await transport.waitUntilSuspended()
        model.cancel()
        transport.resumeTime()
        await loading.value
        XCTAssertNil(model.context)
        guard case .idle = model.state else { return XCTFail("Cancelled operation published state") }
        XCTAssertEqual(transport.requests.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testShortLinkCannotResolveAcrossServerProfiles() async throws {
        let transport = FixtureTransport()
        let production = try await fixtureURL()
        let encrypted = try await ShareLinkCrypto.encryptedShortURL(production)
        transport.shortResponse = ["encrypted_url": encrypted.encryptedURL]
        let short = try ShareLinkCrypto.shortURL(webURL: ServerProfile.development.webBaseURL,
                                               token: encrypted.token, shortKey: encrypted.shortKey)
        do {
            _ = try await SharedChatRecipientService(transport: transport).load(short)
            XCTFail("Cross-profile resolution accepted")
        } catch { XCTAssertEqual(error as? SharedChatRecipientError, .invalidLink) }
        XCTAssertEqual(transport.requests.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testShortLinkDisabledErrorIsPreservedAndDoesNotHydrate() async {
        let transport = FixtureTransport()
        transport.requestError = .shortLinkDisabled
        let model = SharedChatRecipientModel(service: SharedChatRecipientService(transport: transport))
        await model.open(URL(string: "https://openmates.org/s/token123#validKey123")!).value
        XCTAssertNil(model.context)
        guard case .failed(.shortLinkDisabled) = model.state else { return XCTFail("Disabled status lost") }
        XCTAssertEqual(transport.requests.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testCorruptedShareBlobCannotRecoverChatKey() async throws {
        let blob = try await fixtureBlob()
        let replacement = blob.first == "A" ? "B" : "A"
        do {
            _ = try await SharedChatRecipientCrypto.chatKey(id: id, blob: replacement + blob.dropFirst(), serverTime: 1000, password: nil)
            XCTFail("Tampered ciphertext accepted")
        } catch { XCTAssertEqual(error as? SharedChatRecipientError, .invalidLink) }
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testNativeOutgoingShareRoundTripsBase64PlusWithoutFormDecodingLoss() async throws {
        let bytes = Data(repeating: 0xfb, count: 32)
        XCTAssertTrue(bytes.base64EncodedString().contains("+"))
        let blob = try await ShareLinkCrypto.encryptedShareBlob(identifier: id, key: SymmetricKey(data: bytes),
                                                               duration: .noExpiration, password: nil, keyField: "chat_encryption_key")
        let decoded = try await SharedChatRecipientCrypto.chatKey(id: id, blob: blob, serverTime: 1000, password: nil)
        XCTAssertEqual(decoded.withUnsafeBytes { Data($0) }, bytes)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.readonly-viewer-controls
    func testRecipientPlanningDecryptsOnlyChatWrappedRowsWithoutOwnerTaskItems() async throws {
        let transport = FixtureTransport()
        let chatKey = SymmetricKey(data: rawKey)
        let rowBytes = Data(repeating: 9, count: 32), rowKey = SymmetricKey(data: Data(repeating: 9, count: 32))
        let wrapped = try sealed(rowBytes, key: chatKey).base64EncodedString()
        func hash(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
        transport.manifest = ["chat_id": id, "encrypted_title": try content("Synthetic title", key: chatKey),
            "tasks": [["task_id": "shared-task", "status": "todo", "encrypted_title": try content("Shared task", key: rowKey),
                       "encrypted_latest_instruction": try content("Task context", key: rowKey)],
                      ["task_id": "owner-task", "status": "todo", "encrypted_title": try content("Owner task", key: rowKey)]],
            "task_key_wrappers": [["key_type": "chat", "hashed_task_id": hash("shared-task"), "encrypted_task_key": wrapped],
                                  ["key_type": "master", "hashed_task_id": hash("owner-task"), "encrypted_task_key": wrapped]],
            "plans": [["plan_id": "shared-plan", "status": "active", "encrypted_title": try content("Shared plan", key: rowKey),
                       "encrypted_goal": try content("Shared goal", key: rowKey)]],
            "plan_key_wrappers": [["key_type": "chat", "hashed_plan_id": hash("shared-plan"), "encrypted_plan_key": wrapped]]]
        transport.window = ["messages": []]
        let context = try await SharedChatRecipientService(transport: transport).load(fixtureURL())
        let requests = transport.requests.count
        let ownerScope = ChatKeyManager.shared.cacheGeneration
        let snapshot = try await SharedChatRecipientPlanningSnapshot.load(context: context)
        XCTAssertEqual(snapshot.tasks.map(\.id), ["shared-task"])
        XCTAssertEqual(snapshot.tasks.first?.title, "Shared task")
        XCTAssertEqual(snapshot.tasks.first?.detail, "Task context")
        XCTAssertNil(snapshot.tasks.first?.task)
        XCTAssertEqual(snapshot.plans.first?.title, "Shared plan")
        XCTAssertEqual(snapshot.plans.first?.detail, "Shared goal")
        XCTAssertEqual(transport.requests.count, requests)
        XCTAssertEqual(ChatKeyManager.shared.cacheGeneration, ownerScope)
        XCTAssertNil(ChatKeyManager.shared.key(for: id))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.readonly-viewer-controls
    func testCancelledRecipientPlanningDoesNotPublishRows() async throws {
        let transport = FixtureTransport()
        transport.manifest = ["chat_id": id, "encrypted_title": try content("Synthetic title", key: SymmetricKey(data: rawKey))]
        transport.window = ["messages": []]
        let context = try await SharedChatRecipientService(transport: transport).load(fixtureURL())
        let operation = Task { @MainActor in
            withUnsafeCurrentTask { $0?.cancel() }
            return try await SharedChatRecipientPlanningSnapshot.load(context: context)
        }
        do { _ = try await operation.value; XCTFail("Cancelled planning returned rows") }
        catch { XCTAssertTrue(error is CancellationError) }
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testRecipientEmbedNavigationKeepsDeclaredSiblingOrderAndStopsAtGroupEdges() {
        func record(_ id: String, children: String? = nil) -> EmbedRecord {
            .init(id: id, type: "web-website", status: .finished, data: nil,
                  parentEmbedId: nil, appId: "web", skillId: nil, embedIds: children, createdAt: nil)
        }
        let parent = record("parent", children: "second|first")
        let first = record("first"), second = record("second"), unrelated = record("outside-group")
        let graph = [parent.id: parent, first.id: first, second.id: second, unrelated.id: unrelated]
        let siblings = SharedChatRecipientEmbedNavigation.siblings(of: first, in: graph)
        XCTAssertEqual(siblings.map(\.id), ["second", "first"])
        XCTAssertEqual(SharedChatRecipientEmbedNavigation.moved(from: "second", by: 1, in: siblings)?.id, "first")
        XCTAssertNil(SharedChatRecipientEmbedNavigation.moved(from: "second", by: -1, in: siblings))
        XCTAssertNil(SharedChatRecipientEmbedNavigation.moved(from: "first", by: 1, in: siblings))
    }

    #if DEBUG
    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testRecipientEncryptedSiblingFixtureUsesScopedIdentityAndInMemoryTransport() async throws {
        let model = SharedChatRecipientPreviewFixture.model(state: "imageSiblings")
        let context = try XCTUnwrap(model.context)
        let first = try XCTUnwrap(context.embeds["recipient-image-a"])
        let second = try XCTUnwrap(context.embeds["recipient-image-b"])
        let identityA = SharedChatRecipientEmbedNavigation.renderIdentity(scopeID: model.presentationScopeID, embedID: first.id)
        let identityB = SharedChatRecipientEmbedNavigation.renderIdentity(scopeID: model.presentationScopeID, embedID: second.id)
        XCTAssertNotEqual(identityA, identityB)
        XCTAssertEqual(identityA, SharedChatRecipientEmbedNavigation.renderIdentity(scopeID: model.presentationScopeID, embedID: first.id))
        XCTAssertNotEqual(identityA, SharedChatRecipientEmbedNavigation.renderIdentity(scopeID: "replacement", embedID: first.id))
        let loader = try SharedChatRecipientPreviewFixture.imageRequestLoader()
        let media = try RecipientMediaContext(linkURL: context.originalURL, namespace: model.presentationScopeID, requestLoader: loader)
        for (index, record) in [first, second].enumerated() {
            let raw = try XCTUnwrap(record.rawData)
            let bytes = try await media.fetchAndDecrypt(s3Url: try XCTUnwrap(raw["s3_url"]?.value as? String),
                                                       aesKeyHex: try XCTUnwrap(raw["aes_key"]?.value as? String),
                                                       aesNonceHex: nil, encryption: S3MediaClient.noncePrefixedEncryption)
            XCTAssertEqual(bytes, SharedChatRecipientPreviewFixture.imagePNGs[index])
        }
        do {
            _ = try await loader(URLRequest(url: URL(string: "https://example.invalid/not-a-fixture.png")!))
            XCTFail("Synthetic loader accepted an unlisted URL")
        } catch { XCTAssertEqual((error as? URLError)?.code, .resourceUnavailable) }
        XCTAssertNil(ChatKeyManager.shared.key(for: context.chat.id))
        media.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open,chat-share-settings.readonly-viewer-controls
    func testRecipientMediaScopeRejectsReplacementAndCancellationWithoutOwnerKeys() throws {
        let model = SharedChatRecipientPreviewFixture.model(state: "ready")
        let context = try XCTUnwrap(model.context)
        let scope = model.presentationScopeID
        let media = try RecipientMediaContext(linkURL: context.originalURL, namespace: scope, isCurrent: { [weak model] in
            guard let model, model.presentationScopeID == scope,
                  model.context?.chat.id == context.chat.id, case .ready = model.state else { return false }
            return true
        })
        XCTAssertEqual(media.namespace, scope)
        XCTAssertNoThrow(try media.checkCurrent())
        XCTAssertNil(ChatKeyManager.shared.key(for: context.chat.id))
        model.cancel()
        XCTAssertThrowsError(try media.checkCurrent()) { XCTAssertTrue($0 is CancellationError) }
        let separate = try RecipientMediaContext(linkURL: context.originalURL)
        XCTAssertNoThrow(try separate.checkCurrent())
        separate.cancel()
        XCTAssertThrowsError(try separate.checkCurrent()) { XCTAssertTrue($0 is CancellationError) }
        XCTAssertNil(ChatKeyManager.shared.key(for: context.chat.id))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open,chat-share-settings.readonly-viewer-controls
    func testRecipientLaunchFixtureUsesEphemeralScopesAndScopedPlanning() async throws {
        let first = SharedChatRecipientPreviewFixture.model(state: "target")
        let second = SharedChatRecipientPreviewFixture.model(state: "ready")
        XCTAssertNotEqual(first.presentationScopeID, second.presentationScopeID)
        let context = try XCTUnwrap(first.context)
        XCTAssertTrue(context.messages.contains { $0.id == context.targetMessageID })
        XCTAssertEqual(context.originalURL, SharedChatRecipientPreviewFixture.url)
        XCTAssertNil(context.chat.encryptedChatKey)
        let planning = try await SharedChatRecipientPlanningSnapshot.load(context: context)
        XCTAssertEqual(planning.tasks.first?.title, "Review the release checklist")
        XCTAssertNil(planning.tasks.first?.task)
        XCTAssertEqual(planning.plans.first?.title, "Prepare the launch")
        XCTAssertNil(ChatKeyManager.shared.key(for: context.chat.id))
        let embed = try XCTUnwrap(SharedChatRecipientPreviewFixture.model(state: "embed").context)
        XCTAssertEqual(embed.messages.last?.embedRefs?.first?.id, "recipient-file")
        XCTAssertEqual(SharedChatRecipientEmbedNavigation.title(of: try XCTUnwrap(embed.embeds["recipient-file"])), "verification.py")
        let password = SharedChatRecipientPreviewFixture.model(state: "password")
        XCTAssertNil(password.context)
        first.cancel()
        XCTAssertNil(first.context)
        XCTAssertNotEqual(first.presentationScopeID, second.presentationScopeID)
    }
    #endif

    private func fixtureURL() async throws -> URL {
        URL(string: "https://openmates.org/share/chat/\(id)#key=\(try await fixtureBlob())")!
    }

    private func fixtureBlob(duration: Int = 0, password: String? = nil) async throws -> String {
        var encodedKey = rawKey.base64EncodedString()
        if let password {
            let derived = try await CryptoManager.shared.deriveWrappingKeyFromPassword(
                password: password, salt: Data("openmates-pwd-\(id)".utf8))
            encodedKey = urlSafe(try sealed(Data(encodedKey.utf8), key: derived))
        }
        var params = URLComponents()
        params.queryItems = [URLQueryItem(name: "chat_encryption_key", value: encodedKey),
                             .init(name: "generated_at", value: "1000"), .init(name: "duration_seconds", value: String(duration)),
                             .init(name: "pwd", value: password == nil ? "0" : "1")]
        return urlSafe(try sealed(Data(params.percentEncodedQuery!.utf8), key: outerKey))
    }

    private func content(_ text: String, key: SymmetricKey) throws -> String {
        try sealed(Data(text.utf8), key: key).base64EncodedString()
    }
    private func sealed(_ data: Data, key: SymmetricKey) throws -> Data {
        let nonce = try AES.GCM.Nonce(data: Data(repeating: 1, count: 12))
        return try AES.GCM.seal(data, using: key, nonce: nonce).combined!
    }
    private func urlSafe(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
}

@MainActor
private final class FixtureTransport: SharedChatRecipientTransport {
    var manifest: [String: Any] = [:]
    var window: [String: Any] = [:]
    var shortResponse: [String: Any] = [:]
    var requests: [URL] = []
    var suspendTime = false
    var requestError: SharedChatRecipientError?
    private var timeContinuation: CheckedContinuation<Void, Never>?
    private var waitContinuation: CheckedContinuation<Void, Never>?

    func get(_ url: URL) async throws -> Data {
        requests.append(url)
        if let requestError { throw requestError }
        let response: [String: Any]
        if url.path.hasSuffix("/time") {
            if suspendTime {
                await withCheckedContinuation { timeContinuation = $0; waitContinuation?.resume(); waitContinuation = nil }
            }
            response = ["server_time": 1000]
        } else if url.path.contains("/short-url/") { response = shortResponse }
        else if url.path.hasSuffix("/manifest") { response = manifest }
        else { response = window }
        return try JSONSerialization.data(withJSONObject: response)
    }
    func waitUntilSuspended() async {
        if timeContinuation != nil { return }
        await withCheckedContinuation { waitContinuation = $0 }
    }
    func resumeTime() { timeContinuation?.resume(); timeContinuation = nil }
}
