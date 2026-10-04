// contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted,message-input.send.ownership
import CryptoKit
import XCTest
@testable import OpenMates
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

@MainActor
final class MessageTextSelectionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testActualRangeKeepsUnicodeAndQuoteContextRatherThanWholeMessage() throws {
        let text = "Before 🦋 Svelte 5 runes after", range = (text as NSString).range(of: "Svelte 5 runes")
        let value = try XCTUnwrap(MessageTextSelectionSnapshot.capture(messageID: "m", segmentID: text, text: text, range: range))
        XCTAssertEqual(value.anchor.exact, "Svelte 5 runes"); XCTAssertEqual(value.anchor.prefix, "Before 🦋 ")
        XCTAssertEqual(value.anchor.suffix, " after"); XCTAssertEqual(value.anchor.resolve(in: text), range)
        XCTAssertNil(MessageTextSelectionSnapshot.capture(messageID: "m", segmentID: text, text: text, range: NSRange(location: 0, length: 0)))
        XCTAssertNil(MessageTextSelectionSnapshot.capture(messageID: "m", segmentID: text, text: text, range: NSRange(location: 900, length: 2)))
        let split = (text as NSString).range(of: "🦋")
        XCTAssertNil(MessageTextSelectionSnapshot.capture(messageID: "m", segmentID: text, text: text, range: NSRange(location: split.location, length: 1)))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testRepeatedQuoteUsesContextAndExplanationHasNoSourceHistory() throws {
        let anchor = MessageHighlightAnchor(exact: "runes", prefix: "second ", suffix: " end")
        let text = "first runes; second runes end"
        XCTAssertEqual(anchor.resolve(in: text), (text as NSString).range(of: "runes", options: .backwards))
        let raw = "  Tell\n\t me   more  " + String(repeating: "🦋", count: 300)
        let value = try XCTUnwrap(MessageTextSelectionSnapshot.capture(messageID: "m", segmentID: raw, text: raw, range: NSRange(location: 0, length: raw.utf16.count)))
        XCTAssertTrue(value.explanationTerm.hasPrefix("Tell me more ")); XCTAssertLessThanOrEqual(value.explanationTerm.utf16.count, 500)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testActionPolicyFencesPublicSharedStreamingUserAndIncognito() {
        func policy(_ auth: Bool = true, _ read: Bool = false, _ privateChat: Bool = false, _ assistant: Bool = true, _ stream: Bool = false) -> MessageSelectionActionPolicy {
            .init(authenticated: auth, readOnly: read, incognito: privateChat, assistant: assistant, streaming: stream)
        }
        XCTAssertTrue(policy().canHighlight); XCTAssertTrue(policy().canExplain)
        XCTAssertFalse(policy(false).canHighlight); XCTAssertFalse(policy(true, true).canExplain)
        XCTAssertFalse(policy(true, false, false, true, true).canHighlight)
        XCTAssertTrue(policy(true, false, false, false).canHighlight); XCTAssertFalse(policy(true, false, false, false).canExplain)
        XCTAssertFalse(policy(true, false, true).canExplain)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testEntityGroupingPreservesLinkWikiEmbedCodeAndSearchTokenIndices() {
        let tokens: [InlineMarkdownToken] = [.text("before ", isBold: false), .text("bold", isBold: true),
            .link(displayText: "citation", url: "https://example.invalid", isInternal: false, isBold: false),
            .text(" after", isBold: false), .wiki(displayText: "Svelte", wikiTitle: "Svelte", isBold: false),
            .embed(displayText: "Result", embedRef: "embed-id", isBold: false), .inlineCode("let value = 1")]
        let groups = MessageSelectableInlineGroup.group(tokens)
        XCTAssertEqual(groups.flatMap(\.tokens), tokens)
        XCTAssertEqual(groups.map(\.id), [0, 2, 3, 4, 5, 6]); XCTAssertEqual(groups.filter(\.isProse).count, 2)
    }
    #if os(iOS)
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testPlatformSelectionDelegateUsesNativeRangeAndSurvivesHighlightUpdate() async throws {
        let view = PlatformMessageSelectableText.makeTextView(), captured = expectation(description: "native selection")
        var snapshot: MessageTextSelectionSnapshot?
        let context = MessageTextSelectionContext(messageID: "m", onSelection: { value in
            if let value { snapshot = value; captured.fulfill() }
        }, onContextMenu: { _ in })
        let coordinator = PlatformMessageSelectableText.Coordinator(context)
        view.text = "Svelte runes and ordinary words"; view.selectedRange = NSRange(location: 7, length: 5)
        coordinator.textViewDidChangeSelection(view)
        await fulfillment(of: [captured], timeout: 1)
        XCTAssertEqual(snapshot?.anchor.exact, "runes")
        let attributed = MessageSelectableText.attributed(AttributedString(view.text), monospace: false,
            highlights: [.init(exact: "runes", prefix: "Svelte ", suffix: " and")])
        PlatformMessageSelectableText.update(attributed, in: view)
        XCTAssertEqual(view.selectedRange, NSRange(location: 7, length: 5)); XCTAssertFalse(view.isEditable); XCTAssertTrue(view.isSelectable)
        XCTAssertNotNil(view.attributedText.attribute(.backgroundColor, at: 7, effectiveRange: nil))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testNativeContextMenuRoutesExactRangeAndSelectRestoresIt() throws {
        let view = PlatformMessageSelectableText.makeTextView(); view.text = "Svelte runes"
        var contextSelection: MessageTextSelectionSnapshot?, select: MessageTextSelectionTarget?
        let coordinator = PlatformMessageSelectableText.Coordinator(.init(messageID: "m", onSelectTarget: { select = $0 },
            onSelection: { contextSelection = $0 }, onContextMenu: { _ in XCTFail("Touch selection must not block native range handles with the context overlay") }))
        let range = NSRange(location: 7, length: 5)
        let menu = coordinator.textView(view, editMenuForTextIn: range, suggestedActions: [])
        XCTAssertEqual(contextSelection?.anchor.exact, "runes"); XCTAssertEqual(menu?.children.count, 0)
        XCTAssertEqual(select?.messageID, "m")
        view.selectedRange = NSRange(location: 0, length: 0); select?.select(); XCTAssertEqual(view.selectedRange, range)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testEditMenuProposalCannotExpandAnActualNativeWordSelection() throws {
        let view = PlatformMessageSelectableText.makeTextView(); view.text = "Svelte runes make state explicit"
        let word = NSRange(location: 7, length: 5)
        view.selectedRange = word
        var selection: MessageTextSelectionSnapshot?, target: MessageTextSelectionTarget?
        let coordinator = PlatformMessageSelectableText.Coordinator(.init(messageID: "m", onSelectTarget: { target = $0 },
            onSelection: { selection = $0 }, onContextMenu: { _ in XCTFail("Word selection must retain native handles") }))
        _ = coordinator.textView(view, editMenuForTextIn: NSRange(location: 0, length: view.text.utf16.count), suggestedActions: [])
        XCTAssertEqual(selection?.copyText, "runes")
        XCTAssertEqual(selection?.range, word)
        view.selectedRange = NSRange(location: 0, length: 0)
        target?.select()
        XCTAssertEqual(view.selectedRange, word)
    }
    #endif
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testEncryptedHighlightAddCommentColdRestoreAndMessageDeletion() async throws {
        let suite = "selection-tests-" + UUID().uuidString, storage = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { storage.removePersistentDomain(forName: suite) }
        let key = SymmetricKey(size: .bits256), scope = runtime("owner")
        var sent: [(String, [String: Any])] = []
        let manager = HighlightsManager(storage: storage, key: { _ in key }, transport: { sent.append(($0, $1)) }, validate: { $0 == scope })
        await manager.configure(scope)
        let id = try await manager.add(chatID: "c", messageID: "m", anchor: .init(exact: "private quote", prefix: "before ", suffix: " after"))
        XCTAssertEqual(sent.first?.0, "add_message_highlight"); XCTAssertEqual(sent.first?.1["author_user_id"] as? String, "owner")
        let cipher = try XCTUnwrap(sent.first?.1["encrypted_payload"] as? String)
        XCTAssertFalse(cipher.contains("private quote"))
        let plaintext = try await CryptoManager.shared.decryptContent(base64String: cipher, key: key)
        XCTAssertTrue(plaintext.contains("private quote"))
        try await manager.updateComment(id: id, comment: " private comment ")
        XCTAssertEqual(sent.last?.0, "update_message_highlight")
        let persisted = storage.dictionaryRepresentation().values.compactMap { $0 as? Data }.map { String(decoding: $0, as: UTF8.self) }.joined()
        XCTAssertFalse(persisted.contains("private quote")); XCTAssertFalse(persisted.contains("private comment"))
        let restored = HighlightsManager(storage: storage, key: { _ in key }, transport: { _, _ in }, validate: { $0 == scope })
        await restored.configure(scope); XCTAssertEqual(restored.highlights[id]?.comment, "private comment")
        await restored.consume(type: "message_deleted", fields: ["chat_id": "c", "message_id": "m"], scope: UUID())
        XCTAssertNotNil(restored.highlights[id], "A different account scope must not mutate this cache")
        await restored.consume(type: "message_deleted", fields: ["chat_id": "c", "message_id": "m"], scope: scope.scope)
        XCTAssertNil(restored.highlights[id])
        await restored.configure(runtime("another-owner")); XCTAssertTrue(restored.highlights.isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testEncryptedRetryAndAuthorFenceSurviveUnavailableKey() async throws {
        let key = SymmetricKey(size: .bits256), scope = runtime("owner")
        var available = true, online = false, sent = 0
        var activeScope = scope
        var deliveredFields: [String: Any] = [:]
        let manager = HighlightsManager(storage: nil, key: { _ in available ? key : nil }, transport: { _, fields in
            guard online else { throw MessageContextActionError.unavailable }; sent += 1; deliveredFields = fields
        }, validate: { $0 == activeScope })
        await manager.configure(scope)
        let id = try await manager.add(chatID: "c", messageID: "m", anchor: .init(exact: "quote", prefix: "", suffix: ""))
        XCTAssertEqual(sent, 0); online = true; await manager.flush(); XCTAssertEqual(sent, 1)
        available = false
        do { try await manager.updateComment(id: id, comment: "comment"); XCTFail("Missing key must prevent plaintext fallback") } catch { }
        available = true
        let foreign = runtime("other-author")
        activeScope = foreign
        await manager.configure(foreign)
        XCTAssertNil(manager.highlights[id], "Account switching must clear the previous annotation cache")
        // A shared chat can deliver an annotation written by another author.
        // Keep the ciphertext/author identity while validating the new account.
        await manager.consume(type: "message_highlight_added", fields: deliveredFields, scope: foreign.scope)
        XCTAssertEqual(manager.highlights[id]?.authorID, "owner")
        do { try await manager.remove(id: id); XCTFail("Another author cannot remove this annotation") } catch { }
        XCTAssertEqual(sent, 1)
        XCTAssertEqual(manager.highlights[id]?.authorID, "owner", "Rejected removal must preserve the foreign annotation")
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testRememberQuotesMultilineCanonicalContentWithoutSendingOrChangingBoundary() {
        let content = " first\r\n[[embed:opaque-id]]\n\nlast "
        XCTAssertEqual(RememberMessageDraft.format(content), "Remember my earlier message:\n\n> first\n> [[embed:opaque-id]]\n> \n> last")
        XCTAssertTrue(RememberMessageDraft.append(content, to: "Existing draft").hasPrefix("Existing draft\n\nRemember"))
        let old = message("old", second: 0), recent = message("recent", second: 10)
        XCTAssertTrue(RememberMessageDraft.isForgotten(old, messages: [old, recent], checkpoint: 1_789_214_400))
        XCTAssertFalse(RememberMessageDraft.isForgotten(recent, messages: [old, recent], checkpoint: 1_789_214_400))
        XCTAssertFalse(RememberMessageDraft.isForgotten(old, messages: [old, recent], checkpoint: nil))
        let fractional = Message(id: "fractional", chatId: "c", role: .user, content: "quote", encryptedContent: nil,
            createdAt: "2026-09-12T12:00:00.500Z", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        XCTAssertTrue(RememberMessageDraft.isForgotten(fractional, messages: [fractional], checkpoint: 1_789_214_400))
        let invalid = Message(id: "invalid", chatId: "c", role: .user, content: "quote", encryptedContent: nil,
            createdAt: "invalid-date", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        XCTAssertFalse(RememberMessageDraft.isForgotten(invalid, messages: [invalid], checkpoint: Int.max))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testEditSuffixPreservesPrefixAndStopsOnChangedScope() async throws {
        let rows = [message("a", second: 0), message("b", second: 1), message("c", second: 2)]
        let plan = try MessageEditPlan.make(messages: rows, chatID: "c", messageID: "b")
        XCTAssertEqual(plan.retained.map(\.id), ["a"]); XCTAssertEqual(plan.removed.map(\.id), ["b", "c"])
        var valid = true, removed: [String] = []
        do {
            try await MessageEditExecutor.removeSuffix(plan, validate: { if !valid { throw MessageContextActionError.staleContext } },
                remove: { removed.append($0); valid = false })
            XCTFail("Account cancellation must stop remaining deletion")
        } catch { }
        XCTAssertEqual(removed, ["c"], "The edited boundary stays available after a partial failure")
        XCTAssertThrowsError(try MessageEditPlan.make(messages: rows, chatID: "wrong", messageID: "b"))
        XCTAssertThrowsError(try MessageEditPlan.make(messages: rows, chatID: "c", messageID: "missing"))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testForkUsesFreshKeyEncryptedHistoryAndOmitsSensitiveMappings() async throws {
        let key = SymmetricKey(size: .bits256), source = DevHistoryWelcomeData.chat("c", title: "Source")
        var row = message("m", second: 0); row.content = "private content [[embed:opaque-id]]"; row.thinkingContent = "private thinking"
        let result = try await MessageForkPayloadBuilder.prepare(source: source, messages: [row], id: "new-chat", now: Date(), key: key, wrappedKey: "wrapped-key", validate: {})
        XCTAssertEqual(result.chat.teamId, nil); XCTAssertNotEqual(result.messages[0].id, row.id)
        let wire = try XCTUnwrap((result.payload["message_history"] as? [[String: Any]])?.first)
        XCTAssertNil(wire["content"]); XCTAssertNil(wire["thinking_content"]); XCTAssertNil(wire["pii_mappings"])
        let clear = try await CryptoManager.shared.decryptContent(base64String: try XCTUnwrap(wire["encrypted_content"] as? String), key: key)
        XCTAssertEqual(clear, row.content); XCTAssertNil(result.messages[0].thinkingContent)
        let json = String(decoding: try JSONSerialization.data(withJSONObject: result.payload), as: UTF8.self)
        XCTAssertFalse(json.contains("private content")); XCTAssertFalse(json.contains("private thinking"))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testRemoteHighlightBuffersCiphertextUntilKeyAndRejectsStaleScope() async throws {
        let key = SymmetricKey(size: .bits256), scope = runtime("owner")
        var available = false
        let manager = HighlightsManager(storage: nil, key: { _ in available ? key : nil }, transport: { _, _ in }, validate: { $0 == scope })
        await manager.configure(scope)
        let plaintext = "{\"kind\":\"text\",\"anchor\":{\"exact\":\"remote quote\",\"prefix\":\"before \" ,\"suffix\":\" after\"},\"created_at\":10}"
        let ciphertext = try await CryptoManager.shared.encryptContent(plaintext, key: key)
        let fields: [String: Any] = ["id": "remote", "chat_id": "c", "message_id": "m", "author_user_id": "owner",
            "encrypted_payload": ciphertext, "created_at": 10]
        await manager.consume(type: "message_highlight_added", fields: fields, scope: scope.scope)
        XCTAssertNil(manager.highlights["remote"])
        available = true; await manager.restore()
        XCTAssertEqual(manager.highlights["remote"]?.anchor.exact, "remote quote")
        await manager.consume(type: "message_highlight_removed", fields: fields, scope: UUID())
        XCTAssertNotNil(manager.highlights["remote"])
        await manager.consume(type: "message_highlight_removed", fields: fields, scope: scope.scope)
        XCTAssertNil(manager.highlights["remote"])
        manager.reset(); XCTAssertTrue(manager.highlights.isEmpty)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testOnlyStoredEncryptedCheckpointChangesRememberEligibility() {
        let completed: [String: Any] = ["chat_id": "c", "compressed_up_to_timestamp": 123, "summary_content": "summary"]
        XCTAssertNil(RememberMessageDraft.latestBoundary(completed, chatID: "c"))
        let checkpoint: [String: Any] = ["id": "checkpoint", "encrypted_summary": "ciphertext", "created_at": 456, "compressed_up_to_timestamp": 123]
        XCTAssertEqual(RememberMessageDraft.latestBoundary(["chat_id": "c", "checkpoint": checkpoint], chatID: "c"), 123)
        XCTAssertNil(RememberMessageDraft.latestBoundary(["chat_id": "other", "checkpoint": checkpoint], chatID: "c"))
        let summary = Message(id: "summary", chatId: "c", role: .system, content: "summary", encryptedContent: nil,
            createdAt: "2026-09-12T12:00:01Z", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil, category: "compression_summary")
        XCTAssertFalse(RememberMessageDraft.isForgotten(message("old", second: 0), messages: [message("old", second: 0), summary], checkpoint: nil))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testWhitespaceSelectionAnchorsTheExactTrimmedRange() throws {
        let text = "before   quote   after", range = (text as NSString).range(of: "  quote  ")
        let selection = try XCTUnwrap(MessageTextSelectionSnapshot.capture(messageID: "m", segmentID: text, text: text, range: range))
        XCTAssertEqual(selection.anchor.exact, "quote")
        XCTAssertEqual(selection.range, (text as NSString).range(of: "quote"))
        XCTAssertEqual(selection.anchor.resolve(in: text), selection.range)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testClipboardPreservesIndentationNewlinesAndReadonlyWhitespaceRanges() throws {
        let code = "before\n    let 🦋 = 1\n\nafter"
        let selected = "    let 🦋 = 1\n"
        let range = (code as NSString).range(of: selected)
        let snapshot = try XCTUnwrap(MessageTextSelectionSnapshot.capture(messageID: "code", segmentID: code, text: code, range: range))
        XCTAssertEqual(snapshot.copyText, selected)
        XCTAssertEqual(snapshot.anchor.exact, "let 🦋 = 1")
        let whitespace = NSRange(location: 7, length: 3)
        XCTAssertNil(MessageTextSelectionSnapshot.capture(messageID: "code", segmentID: code, text: code, range: whitespace))
        let readonly = try XCTUnwrap(MessageTextSelectionSnapshot.capture(messageID: "code", segmentID: code, text: code, range: whitespace, preserveWhitespace: true))
        XCTAssertEqual(readonly.copyText, "   ")
        XCTAssertEqual(readonly.range, whitespace)
    }
    private func runtime(_ owner: String) -> MessageHighlightRuntimeScope {
        .init(accountID: owner, scope: UUID(), server: .development,
              team: .init(accountID: owner, server: .development, scope: nil, teamID: nil, epoch: 0))
    }
    private func message(_ id: String, second: Int) -> Message {
        Message(id: id, chatId: "c", role: .user, content: id, encryptedContent: nil,
                createdAt: String(format: "2026-09-12T12:00:%02dZ", second), updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
    }
}
