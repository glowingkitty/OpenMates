// Specification: specifications/features/video-call/specification.yml
// Supporting deterministic canonical-admission evidence; no device/network claim.
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class NativeVoiceCallCanonicalAdmissionTests: XCTestCase {
    private let chatID = "00000000-0000-4000-8000-000000000001"
    private var scope: NativeVoiceCallScope {
        .init(accountID: "fixture-owner", profileID: "development", workspaceGeneration: UUID(),
              chatID: chatID, mateCategory: "general_knowledge")
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.compressed-context,video-call.chat.transcripts
    func testCheckpointBoundaryDoesNotOmitCorrectionOnThirdCanonicalPage() async throws {
        let correctedID = messageID(4)
        let checkpoint = checkpoint(covered: [messageID(2), messageID(3), correctedID], timestamp: 100)
        let pages = CanonicalVoicePages(checkpoints: [checkpoint], pages: [
            page([row(1, timestamp: 150, text: "cipher-recent"), row(2, timestamp: 100)], more: true),
            page([row(3, timestamp: 75)], more: true),
            page([row(4, timestamp: 50, role: "assistant", revision: 2, text: "cipher-correction")], more: false)
        ])
        let context = try await loader(pages).load(scope: scope)
        guard case .array(let messages)? = context.fields["messages"] else { return XCTFail("Missing canonical context") }
        XCTAssertEqual(messages.compactMap { $0.object?["message_id"]?.string }, [correctedID, messageID(1)])
        XCTAssertEqual(messages.first?.object?["text"]?.string, "late corrected transcript")
        XCTAssertEqual(context.fields["summary"]?.string, "canonical summary")
        let requests = await pages.paths
        XCTAssertEqual(requests.filter { $0.contains("/messages/window?") }.count, 3)
        XCTAssertTrue(requests.contains { $0.contains("before_timestamp=100") })
        XCTAssertTrue(requests.contains { $0.contains("before_timestamp=75") })
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.compressed-context,video-call.lifecycle.recovery-and-billing
    func testUnknownOlderCorrectionsFailClosedAtCanonicalScanBound() async throws {
        let checkpoint = checkpoint(covered: [], timestamp: 2_000)
        let pages = CanonicalVoicePages(checkpoints: [checkpoint], pages: (0..<6).map { pageIndex in
            page((0..<20).map { offset in
                let index = pageIndex * 20 + offset
                return row(index + 1, timestamp: 1_000 - index)
            }, more: true)
        })
        do {
            _ = try await loader(pages).load(scope: scope)
            XCTFail("A checkpoint cursor cannot prove unknown older corrected rows complete")
        } catch { XCTAssertEqual(error as? NativeVoiceCallError, .contextTooLarge) }
        let paths = await pages.paths
        XCTAssertEqual(paths.filter { $0.contains("/messages/window?") }.count, 6)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.lifecycle.recovery-and-billing
    func testQueueReceiptWaitsForExactDurableWrapperAndVersionReadback() async throws {
        let expected = expected()
        let fixture = CanonicalVoiceReadback(responses: [[], [validReadback()]])
        let proof = NativeVoiceCallChatAdmissionProof(readAuthoritative: { await fixture.read() },
            checkCurrent: { try await fixture.check() }, sleep: { _ in await fixture.slept() })
        let confirmed = try await proof.confirm(queueReceipt: queued(), expected: expected)
        XCTAssertEqual(confirmed["encrypted_chat_key"]?.string, expected.encryptedChatKey)
        let reads = await fixture.reads, sleeps = await fixture.sleeps
        XCTAssertEqual(reads, 2)
        XCTAssertEqual(sleeps, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.lifecycle.recovery-and-billing
    func testQueuedButMissingCanonicalChatNeverAdmitsProvider() async throws {
        let fixture = CanonicalVoiceReadback(responses: [[]])
        let proof = NativeVoiceCallChatAdmissionProof(readAuthoritative: { await fixture.read() },
            checkCurrent: { try await fixture.check() }, sleep: { _ in await fixture.slept() })
        do { _ = try await proof.confirm(queueReceipt: queued(), expected: expected()); XCTFail("Queue ACK is not durability") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .persistenceFailed) }
        let reads = await fixture.reads
        XCTAssertEqual(reads, 4)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy
    func testMissingMalformedStaleOrWrongCanonicalMetadataFailsImmediately() async throws {
        var missingKey = validReadback(); missingKey.removeValue(forKey: "encrypted_chat_key")
        var missingVersion = validReadback(); missingVersion.removeValue(forKey: "metadata_v")
        var malformedVersion = validReadback(); malformedVersion["messages_v"] = .string("2")
        var stale = validReadback(); stale["metadata_v"] = .number(3)
        var changedKey = validReadback(); changedKey["encrypted_chat_key"] = .string("different-wrapper")
        var ambiguous = validReadback(); ambiguous["metadata_v"] = .number(4.5)
        for record in [missingKey, missingVersion, malformedVersion, stale, changedKey, ambiguous] {
            let fixture = CanonicalVoiceReadback(responses: [[record]])
            let proof = NativeVoiceCallChatAdmissionProof(readAuthoritative: { await fixture.read() },
                checkCurrent: { try await fixture.check() }, sleep: { _ in XCTFail("Malformed/stale metadata must not be retried as missing") })
            do { _ = try await proof.confirm(queueReceipt: queued(), expected: expected()); XCTFail("Invalid proof admitted") }
            catch { XCTAssertEqual(error as? NativeVoiceCallError, .persistenceFailed) }
            let reads = await fixture.reads
            XCTAssertEqual(reads, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy
    func testScopeRevokedDuringAuthoritativeReadCannotConfirmAdmission() async throws {
        let fixture = CanonicalVoiceReadback(responses: [[validReadback()]], revokeDuringRead: true)
        let proof = NativeVoiceCallChatAdmissionProof(readAuthoritative: { await fixture.read() },
            checkCurrent: { try await fixture.check() })
        do { _ = try await proof.confirm(queueReceipt: queued(), expected: expected()); XCTFail("Revoked owner admitted") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .scopeChanged) }
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy
    func testMalformedQueueReceiptCannotAuthorizeEvenAValidReadback() async throws {
        var receipt = queued()
        receipt.removeValue(forKey: "versions")
        let fixture = CanonicalVoiceReadback(responses: [[validReadback()]])
        let proof = NativeVoiceCallChatAdmissionProof(readAuthoritative: { await fixture.read() },
            checkCurrent: { try await fixture.check() })
        do { _ = try await proof.confirm(queueReceipt: receipt, expected: expected()); XCTFail("Missing accepted version tuple admitted") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .persistenceFailed) }
        let reads = await fixture.reads
        XCTAssertEqual(reads, 0)
    }

    private func expected() -> NativeVoiceCallChatAdmissionProof.Expected {
        .init(chatID: chatID, encryptedChatKey: "fixture-encrypted-wrapper", versions: .init(messages: 2, title: 3, metadata: 4))
    }
    private func queued() -> NativeVoiceCallFrame {
        ["type": .string("encrypted_metadata_stored"), "chat_id": .string(chatID), "status": .string("queued_for_storage"),
         "versions": .object(["messages_v": .number(2), "title_v": .number(3), "metadata_v": .number(4)])]
    }
    private func validReadback() -> NativeVoiceCallFrame {
        ["id": .string(chatID), "encrypted_chat_key": .string("fixture-encrypted-wrapper"),
         "messages_v": .number(2), "title_v": .number(3), "metadata_v": .number(4), "team_id": .null]
    }
    private func messageID(_ number: Int) -> String { String(format: "00000000-0000-4000-8000-%012d", number) }
    private func row(_ number: Int, timestamp: Int, role: String = "user", revision: Int = 1,
                     text: String = "cipher-covered") -> NativeVoiceCallFrame {
        ["id": .string(messageID(number)), "chat_id": .string(chatID), "role": .string(role),
         "created_at": .number(Double(timestamp)), "encrypted_content": .string(text), "queue_revision": .number(Double(revision))]
    }
    private func page(_ rows: [NativeVoiceCallFrame], more: Bool) -> NativeVoiceCallFrame {
        let first = rows.last!
        return ["messages": .array(rows.map { .object($0) }), "has_more_before": .bool(more),
            "start_cursor": .object(["created_at": first["created_at"]!, "message_id": first["id"]!])]
    }
    private func checkpoint(covered: [String], timestamp: Int) -> NativeVoiceCallFrame {
        ["id": .string(messageID(999)), "chat_id": .string(chatID), "created_at": .number(200),
         "encrypted_summary": .string("cipher-summary"), "compressed_up_to_timestamp": .number(Double(timestamp)),
         "compressed_up_to_message_id": .string(messageID(2)), "compressed_message_count": .number(20),
         "covered_message_ids": .array(covered.map { .string($0) })]
    }
    private func loader(_ pages: CanonicalVoicePages) -> NativeVoiceCallCanonicalContextLoader {
        let chatID = chatID
        return .init(request: { _, path in try await pages.request(path) }, decrypt: { text, _ in
            switch text {
            case "cipher-summary": return "canonical summary"
            case "cipher-correction": return "late corrected transcript"
            case "cipher-recent": return "recent user"
            default: throw NativeVoiceCallError.contextUnavailable
            }
        }, metadata: { _ in ["id": .string(chatID), "team_id": .null] }, isCurrent: { _ in true })
    }
}

private actor CanonicalVoicePages {
    let checkpoints: [NativeVoiceCallFrame]
    let pages: [NativeVoiceCallFrame]
    private var index = 0
    private(set) var paths: [String] = []
    init(checkpoints: [NativeVoiceCallFrame], pages: [NativeVoiceCallFrame]) { self.checkpoints = checkpoints; self.pages = pages }
    func request(_ path: String) throws -> Data {
        paths.append(path)
        if path.contains("/compression-checkpoints?") {
            return try JSONEncoder().encode(["checkpoints": NativeVoiceCallJSON.array(checkpoints.map { .object($0) })])
        }
        guard path.contains("/messages/window?"), index < pages.count else { throw NativeVoiceCallError.contextUnavailable }
        let page = pages[index]; index += 1
        return try JSONEncoder().encode(page)
    }
}
private actor CanonicalVoiceReadback {
    let responses: [[NativeVoiceCallFrame]]
    let revokeDuringRead: Bool
    private var revoked = false
    private(set) var reads = 0
    private(set) var sleeps = 0
    init(responses: [[NativeVoiceCallFrame]], revokeDuringRead: Bool = false) {
        self.responses = responses; self.revokeDuringRead = revokeDuringRead
    }
    func read() -> [NativeVoiceCallFrame] {
        let result = responses[min(reads, responses.count - 1)]
        reads += 1; if revokeDuringRead { revoked = true }
        return result
    }
    func check() throws { if revoked { throw NativeVoiceCallError.scopeChanged } }
    func slept() { sleeps += 1 }
}
