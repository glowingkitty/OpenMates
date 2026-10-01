// Encrypted Code Run sidecar contract and account-scoped offline storage.
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.output.chat-bound-encrypted, code-run.surface-parity

import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class CodeRunOutputSyncTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=code-run.output.chat-bound-encrypted
    func testWebCompatibleEmbedCiphertextAndSnakeCaseSidecarPayload() throws {
        let key = SymmetricKey(data: Data(repeating: 0x21, count: 32))
        let plaintext = """
        {"output":"synthetic result\\n","status":"exited","saved_at":1770000000123,"created_at":1770000000,"updated_at":1770000001}
        """
        let encrypted = try ComposerEmbedCrypto.encryptContent(plaintext, using: key)
        XCTAssertFalse(encrypted.contains("synthetic result"))
        XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(encrypted, using: key), plaintext)
        let fields: [String: Any] = [
            "id": UUID().uuidString, "chat_id": "synthetic-chat",
            "embed_id": "synthetic-embed", "author_user_id": "synthetic-owner",
            "encrypted_payload": encrypted, "created_at": 1_770_000_000,
            "updated_at": 1_770_000_001,
        ]
        let decoded = try XCTUnwrap(CodeRunOutputSyncedPayload.decode(fields: fields))
        XCTAssertEqual(decoded.chatId, "synthetic-chat")
        XCTAssertEqual(decoded.embedId, "synthetic-embed")
        XCTAssertEqual(decoded.updatedAt, 1_770_000_001)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.output.chat-bound-encrypted
    func testCiphertextIsScopedByAccountAndRemovedWithChat() throws {
        let root = try testDirectory("CodeRunOutputSync")
        defer { try? FileManager.default.removeItem(at: root) }
        let apiURL = URL(string: "https://fixture.invalid")!
        let owner = try OfflineStore(directory: root, userId: "owner-a", apiBaseURL: apiURL)
        let encrypted = Data("ciphertext-only".utf8).base64EncodedString()
        try owner.persistCodeRunOutput(PersistedCodeRunOutput(
            id: UUID().uuidString, chatId: "chat-a", embedId: "embed-a",
            authorUserId: "owner-a", encryptedPayload: encrypted, keyVersion: nil,
            createdAt: 1_770_000_000, updatedAt: 1_770_000_001
        ))
        XCTAssertEqual(owner.loadCodeRunOutput(chatId: "chat-a", embedId: "embed-a")?.encryptedPayload, encrypted)
        let other = try OfflineStore(directory: root, userId: "owner-b", apiBaseURL: apiURL)
        XCTAssertNil(other.loadCodeRunOutput(chatId: "chat-a", embedId: "embed-a"))
        owner.deleteChat("chat-a")
        XCTAssertNil(owner.loadCodeRunOutput(chatId: "chat-a", embedId: "embed-a"))
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.output.chat-bound-encrypted
    func testCapturedScopeFenceRejectsAccountSwitchAcrossSuspension() throws {
        let root = try testDirectory("CodeRunScopeFence")
        defer { try? FileManager.default.removeItem(at: root) }
        let apiURL = URL(string: "https://fixture.invalid")!
        let store = try OfflineStore(directory: root, userId: "owner-a", apiBaseURL: apiURL)
        let beforeAwait = CodeRunScopeFence(store: store)
        XCTAssertTrue(beforeAwait.isCurrent(in: store))
        try store.activate(userId: "owner-b", apiBaseURL: apiURL)
        XCTAssertFalse(beforeAwait.isCurrent(in: store))
        try store.activate(userId: "owner-a", apiBaseURL: apiURL)
        XCTAssertFalse(beforeAwait.isCurrent(in: store), "A reopened account must not reuse a prior operation")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.output.chat-bound-encrypted
    func testPendingCiphertextSurvivesUntilMatchingServerEcho() throws {
        let root = try testDirectory("CodeRunPending")
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try OfflineStore(directory: root, userId: "owner-a",
            apiBaseURL: URL(string: "https://fixture.invalid")!)
        let id = UUID().uuidString
        try store.persistCodeRunOutput(PersistedCodeRunOutput(
            id: id, chatId: "chat-a", embedId: "embed-a", authorUserId: "owner-a",
            encryptedPayload: "cipher-new", keyVersion: nil,
            createdAt: 1_770_000_000, updatedAt: 1_770_000_001, needsSync: true
        ))
        XCTAssertEqual(try store.pendingCodeRunOutputs().map(\.id), [id])
        try store.persistCodeRunOutput(PersistedCodeRunOutput(
            id: id, chatId: "chat-a", embedId: "embed-a", authorUserId: "owner-a",
            encryptedPayload: "cipher-old", keyVersion: nil,
            createdAt: 1_770_000_000, updatedAt: 1_770_000_001
        ))
        XCTAssertEqual(store.loadCodeRunOutput(chatId: "chat-a", embedId: "embed-a")?.encryptedPayload, "cipher-new")
        try store.acknowledgeCodeRunOutput(id: id, encryptedPayload: "cipher-old")
        XCTAssertEqual(try store.pendingCodeRunOutputs().count, 1)
        try store.acknowledgeCodeRunOutput(id: id, encryptedPayload: "cipher-new")
        XCTAssertTrue(try store.pendingCodeRunOutputs().isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testStatusResponseKeepsArtifactAndSkippedMetadata() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let status = try decoder.decode(CodeRunStatusResponse.self, from: Data("""
        {"execution_id":"synthetic-run","status":"finished","artifacts":[{"path":"outputs/summary.csv","normalized_path":"outputs/summary.csv","size_bytes":12,"download_url":"https://fixture.invalid/file","versions":[{"path":"outputs/summary.csv","asset_id":"asset-1"}]}],"skipped_artifacts":[{"path":"outputs/private.txt","reason":"excluded"}]}
        """.utf8))
        XCTAssertEqual(status.artifacts?.first?["path"]?.value as? String, "outputs/summary.csv")
        XCTAssertEqual(status.artifacts?.first?["download_url"]?.value as? String, "https://fixture.invalid/file")
        XCTAssertEqual(status.skippedArtifacts?.first?["reason"]?.value as? String, "excluded")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.output.chat-bound-encrypted
    func testInferenceArtifactShapeExcludesSignedURLAndNativeSecretPayload() {
        let artifact: [[String: Any]] = [[
            "path": "outputs/summary.csv", "size_bytes": 12,
            "download_url": "https://fixture.invalid/signed",
            "native_render_payload": ["content": ["aes_key": "synthetic-key"]],
            "unexpected_secret": "must-not-cross",
            "versions": [["path": "outputs/summary.csv", "download_url": "https://fixture.invalid/old"]],
        ]]
        let safe = CodeRunOutputStore.sanitizeArtifacts(artifact, includeSensitive: false)
        XCTAssertEqual(safe.first?["path"] as? String, "outputs/summary.csv")
        XCTAssertNil(safe.first?["download_url"])
        XCTAssertNil(safe.first?["native_render_payload"])
        XCTAssertNil(safe.first?["unexpected_secret"])
        XCTAssertNil((safe.first?["versions"] as? [[String: Any]])?.first?["download_url"])
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.output.chat-bound-encrypted,code-run.artifacts.chat-bound-versioned
    func testRerunPreservesEarlierArtifactVersionAndEncryptedDownloadMetadata() {
        let old: [[String: Any]] = [[
            "path": "outputs/report.csv", "normalized_path": "outputs/report.csv",
            "asset_id": "asset-old", "captured_at": 1_770_000_000,
            "download_url": "https://fixture.invalid/old",
        ]]
        let latest: [[String: Any]] = [[
            "path": "outputs/report.csv", "normalized_path": "outputs/report.csv",
            "asset_id": "asset-new", "download_url": "https://fixture.invalid/new",
        ]]
        let merged = CodeRunOutputStore.mergeArtifactHistory(
            previous: old, latest: latest, capturedAt: 1_770_000_100
        )
        XCTAssertEqual(merged.first?["asset_id"] as? String, "asset-new")
        let versions = merged.first?["versions"] as? [[String: Any]]
        XCTAssertEqual(versions?.first?["asset_id"] as? String, "asset-old")
        XCTAssertEqual(versions?.first?["download_url"] as? String, "https://fixture.invalid/old")
        let safe = CodeRunOutputStore.sanitizeArtifacts(merged, includeSensitive: false)
        XCTAssertNil((safe.first?["versions"] as? [[String: Any]])?.first?["download_url"])
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.output.chat-bound-encrypted
    func testMissingKeySnapshotRetainsTerminalOutputUntilKeyArrivalOrScopeSwitch() throws {
        let root = try testDirectory("CodeRunMissingKey")
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try OfflineStore(directory: root, userId: "owner-a",
            apiBaseURL: URL(string: "https://fixture.invalid")!)
        let embed = EmbedRecord(
            id: "embed-a", type: "code", status: .finished, data: nil,
            parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, createdAt: nil
        )
        var queue = PendingCodeRunRetryQueue()
        queue.enqueue(PendingCodeRunSnapshot(
            chatId: "chat-a", embedId: embed.id, embed: embed,
            output: "synthetic final output", status: "finished",
            files: ["main.py"], events: [], artifacts: [], skippedArtifacts: []
        ), fence: CodeRunScopeFence(store: store))
        XCTAssertEqual(queue.drainCurrent(in: store).first?.output, "synthetic final output")
        try store.activate(userId: "owner-b", apiBaseURL: URL(string: "https://fixture.invalid")!)
        XCTAssertTrue(queue.drainCurrent(in: store).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testFileArtifactDisplayMatchesWebFilenamePathAndBinarySizeUnits() {
        let payload = FileEmbedPayload([
            "normalized_path": AnyCodable("artifacts/reports/berlin-weather.csv"),
            "path": AnyCodable("reports/old.csv"),
            "filename": AnyCodable("berlin-weather.csv"),
            "mime_type": AnyCodable("text/csv"),
            "size_bytes": AnyCodable(24_576)
        ])
        XCTAssertEqual(payload.path, "artifacts/reports/berlin-weather.csv")
        XCTAssertEqual(payload.filename, "berlin-weather.csv")
        XCTAssertEqual(payload.metadata, "text/csv · 24.0 KB")
        for (bytes, expected) in [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"),
                                  (1_048_576, "1.0 MB"), (1_073_741_824, "1024.0 MB")] {
            XCTAssertEqual(FileEmbedPayload(["size_bytes": AnyCodable(bytes)]).metadata,
                           "application/octet-stream · \(expected)")
        }
        XCTAssertEqual(FileEmbedPayload(["path": AnyCodable("reports/data.csv")]).filename, "data.csv")
        XCTAssertEqual(FileEmbedPayload(nil).metadata, "application/octet-stream")
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testFileArtifactDownloadAvailabilityRejectsExpiredLinksAtUseTime() {
        let url = "https://example.invalid/artifacts/data.csv"
        let timed = FileEmbedPayload([
            "download_url": AnyCodable(url), "download_expires_at": AnyCodable(2000)
        ])
        XCTAssertEqual(timed.availableDownloadURL(at: 1999)?.absoluteString, url)
        XCTAssertNil(timed.availableDownloadURL(at: 2000))
        XCTAssertNil(timed.availableDownloadURL(at: 2001))
        XCTAssertNil(FileEmbedPayload(nil).availableDownloadURL(at: 1000))
        XCTAssertEqual(FileEmbedPayload(["download_url": AnyCodable(url)])
            .availableDownloadURL(at: 1000)?.absoluteString, url)
        // Web treats a zero expiry as absent, matching captured artifact data.
        XCTAssertEqual(FileEmbedPayload([
            "download_url": AnyCodable(url), "download_expires_at": AnyCodable(0)
        ]).availableDownloadURL(at: 1000)?.absoluteString, url)
    }

    private func testDirectory(_ prefix: String) throws -> URL {
        let repository = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
        let directory = repository.appendingPathComponent(
            ".runtime/code-run-output-tests/\(prefix)-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }
}
