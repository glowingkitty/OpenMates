// Code Run API client and state machine for native code embed execution.
// Mirrors frontend/packages/ui/src/services/codeRunService.ts and the web
// CodeEmbedFullscreen run panel. Uses the same /v1/code/run endpoints to start,
// poll, and cancel E2B sandbox executions for code embeds.
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.output.chat-bound-encrypted, code-run.surface-parity

import Combine
import Foundation
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct CodeRunClientFile: Encodable {
    let embedId: String
    let code: String
    let language: String
    let filename: String?
    let isTarget: Bool

    private enum CodingKeys: String, CodingKey {
        case embedId = "embed_id"
        case code
        case language
        case filename
        case isTarget = "is_target"
    }
}

struct CodeRunStartResponse: Decodable {
    let executionId: String
    let status: String
    let targetFilename: String
    let files: [String]
    let creditsPerMinute: Int
}

struct CodeRunEvent: Decodable, Identifiable {
    let id = UUID()
    let kind: Kind
    let text: String
    let timestamp: Double

    init(kind: Kind, text: String, timestamp: Double) {
        self.kind = kind
        self.text = text
        self.timestamp = timestamp
    }

    enum Kind: String, Decodable {
        case status
        case stdout
        case stderr
    }

    private enum CodingKeys: String, CodingKey {
        case kind
        case text
        case timestamp
    }
}

struct CodeRunStatusResponse: Decodable {
    let executionId: String
    let status: CodeRunExecutionStatus
    let targetFilename: String?
    let files: [String]?
    let events: [CodeRunEvent]?
    let artifacts: [[String: AnyCodable]]?
    let skippedArtifacts: [[String: AnyCodable]]?
    let error: String?
}

enum CodeRunExecutionStatus: String, Decodable {
    case idle
    case queued
    case preparingSandbox = "preparing_sandbox"
    case uploadingFiles = "uploading_files"
    case installingDependencies = "installing_dependencies"
    case running
    case cancelling
    case finished
    case failed
    case timeout
    case cancelled

    var isTerminal: Bool {
        switch self {
        case .finished, .failed, .timeout, .cancelled:
            return true
        default:
            return false
        }
    }
}

@MainActor
final class CodeRunViewModel: ObservableObject {
    @Published private(set) var status: CodeRunExecutionStatus = .idle
    @Published private(set) var events: [CodeRunEvent] = []
    @Published private(set) var files: [String] = []
    @Published private(set) var artifacts: [[String: Any]] = []
    @Published private(set) var skippedArtifacts: [[String: Any]] = []
    @Published private(set) var errorMessage: String?
    @Published private(set) var isPanelOpen = false
    @Published private(set) var isCancelling = false

    private var executionId: String?
    private var pollTask: Task<Void, Never>?

    var isActive: Bool {
        !status.isTerminal && status != .idle
    }

    var ctaTitle: String {
        status == .idle && events.isEmpty ? AppStrings.codeRunCode : AppStrings.codeRunShowOutput
    }

    var programOutputText: String {
        events
            .filter { $0.kind == .stdout || $0.kind == .stderr }
            .map(\.text)
            .joined()
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func toggleRun(chatId: String?, embedId: String, file: CodeRunClientFile) {
        if isPanelOpen {
            isPanelOpen = false
            return
        }
        if status != .idle || !events.isEmpty {
            isPanelOpen = true
            return
        }
        Task { await start(chatId: chatId, embedId: embedId, file: file) }
    }

    func closePanel() {
        isPanelOpen = false
    }

    func openSavedOutput() {
        isPanelOpen = true
    }

    func start(chatId: String?, embedId: String, file: CodeRunClientFile) async {
        guard let chatId, !chatId.isEmpty, !isActive else { return }
        pollTask?.cancel()
        isPanelOpen = true
        status = .queued
        errorMessage = nil
        isCancelling = false
        files = []
        artifacts = []
        skippedArtifacts = []
        events = [CodeRunEvent(kind: .status, text: "\(AppStrings.loading)\n", timestamp: Date().timeIntervalSince1970)]

        do {
            let body = try Self.startBody(chatId: chatId, targetEmbedId: embedId, file: file)
            let response: CodeRunStartResponse = try await APIClient.shared.request(.post, path: "/v1/code/run", body: body)
            executionId = response.executionId
            status = CodeRunExecutionStatus(rawValue: response.status) ?? .queued
            files = response.files
            events = [
                CodeRunEvent(
                    kind: .status,
                    text: "\(AppStrings.loading)\n",
                    timestamp: Date().timeIntervalSince1970
                )
            ]
            startPolling(response.executionId)
        } catch {
            errorMessage = error.localizedDescription
            events = [CodeRunEvent(kind: .stderr, text: "\(error.localizedDescription)\n", timestamp: Date().timeIntervalSince1970)]
            status = .failed
        }
    }

    func cancel() {
        guard let executionId, isActive, !isCancelling else { return }
        isCancelling = true
        Task {
            do {
                let response: CodeRunCancelResponse = try await APIClient.shared.request(.post, path: "/v1/code/run/\(executionId)/cancel")
                status = CodeRunExecutionStatus(rawValue: response.status) ?? .cancelling
                events.append(CodeRunEvent(kind: .status, text: "\(AppStrings.codeRunCancelling)\n", timestamp: Date().timeIntervalSince1970))
            } catch {
                isCancelling = false
                errorMessage = error.localizedDescription
                events.append(CodeRunEvent(kind: .stderr, text: "\(error.localizedDescription)\n", timestamp: Date().timeIntervalSince1970))
            }
        }
    }

    func copyOutput() {
        let output = programOutputText
        guard !output.isEmpty else { return }
        #if os(iOS)
        UIPasteboard.general.string = output
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(output, forType: .string)
        #endif
        ToastManager.shared.show(AppStrings.codeRunOutputCopied, type: .success)
    }

    func cleanup() {
        pollTask?.cancel()
        pollTask = nil
    }

    private func startPolling(_ executionId: String) {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                guard let self else { return }
                let isTerminal = await self.fetchStatus(executionId)
                if isTerminal { return }
            }
        }
    }

    private func fetchStatus(_ executionId: String) async -> Bool {
        do {
            let response: CodeRunStatusResponse = try await APIClient.shared.request(.get, path: "/v1/code/run/\(executionId)")
            isCancelling = response.status == .cancelling
            events = response.events ?? events
            files = response.files ?? files
            artifacts = response.artifacts?.map { $0.mapValues(\.value) } ?? artifacts
            skippedArtifacts = response.skippedArtifacts?.map { $0.mapValues(\.value) } ?? skippedArtifacts
            errorMessage = response.error
            // Publish terminal status after the final output snapshot is visible.
            status = response.status
            return response.status.isTerminal
        } catch {
            errorMessage = error.localizedDescription
            events.append(CodeRunEvent(kind: .stderr, text: "\(error.localizedDescription)\n", timestamp: Date().timeIntervalSince1970))
            status = .failed
            return true
        }
    }

    private static func startBody(chatId: String, targetEmbedId: String, file: CodeRunClientFile) throws -> JSONRawBody {
        let encodedFile = try JSONEncoder().encode(file)
        guard let fileObject = try JSONSerialization.jsonObject(with: encodedFile) as? [String: Any] else {
            throw APIError.invalidResponse
        }
        let body: [String: Any] = [
            "chat_id": chatId,
            "target_embed_id": targetEmbedId,
            "enable_internet": true,
            "client_files": [fileObject],
            "selected_embed_ids": [targetEmbedId],
        ]
        return JSONRawBody(data: try JSONSerialization.data(withJSONObject: body))
    }
}

private struct CodeRunCancelResponse: Decodable {
    let executionId: String
    let status: String
}

struct CodeRunOutput {
    let id: String
    let chatId: String
    let embedId: String
    let output: String
    let status: String?
    let files: [String]
    let events: [CodeRunEvent]
    let artifacts: [[String: Any]]
    let skippedArtifacts: [[String: Any]]
    let savedAt: Double // Web contract: milliseconds, unlike row timestamps.
    let createdAt: Double // Unix seconds.
    let updatedAt: Double // Unix seconds.
}

struct CodeRunOutputSyncedPayload: Decodable {
    let id: String
    let chatId: String
    let embedId: String
    let authorUserId: String?
    let keyVersion: Int?
    let encryptedPayload: String
    let createdAt: Double
    let updatedAt: Double

    static func decode(fields: [String: Any]) -> Self? {
        guard JSONSerialization.isValidJSONObject(fields),
              let data = try? JSONSerialization.data(withJSONObject: fields) else { return nil }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try? decoder.decode(Self.self, from: data)
    }
}

@MainActor
struct CodeRunScopeFence: Equatable {
    let scopeId: String?
    let generation: UUID

    init(store: OfflineStore) {
        scopeId = store.activeScopeId
        generation = store.scopeGeneration
    }

    func isCurrent(in store: OfflineStore) -> Bool {
        scopeId != nil && scopeId == store.activeScopeId && generation == store.scopeGeneration
    }
}

@MainActor
struct PendingCodeRunSnapshot {
    let chatId: String
    let embedId: String
    let embed: EmbedRecord
    let output: String
    let status: String
    let files: [String]
    let events: [CodeRunEvent]
    let artifacts: [[String: Any]]
    let skippedArtifacts: [[String: Any]]
}

@MainActor
struct PendingCodeRunRetryQueue {
    private var snapshots: [String: (fence: CodeRunScopeFence, value: PendingCodeRunSnapshot)] = [:]

    mutating func enqueue(_ value: PendingCodeRunSnapshot, fence: CodeRunScopeFence) {
        snapshots["\(value.chatId):\(value.embedId)"] = (fence, value)
    }

    mutating func remove(chatId: String, embedId: String) {
        snapshots.removeValue(forKey: "\(chatId):\(embedId)")
    }

    mutating func remove(chatId: String) {
        snapshots = snapshots.filter { $0.value.value.chatId != chatId }
    }

    mutating func drainCurrent(in store: OfflineStore) -> [PendingCodeRunSnapshot] {
        snapshots = snapshots.filter { $0.value.fence.isCurrent(in: store) }
        return snapshots.values.map(\.value)
    }

    mutating func removeAll() { snapshots.removeAll() }
}

@MainActor
final class CodeRunOutputStore: ObservableObject {
    static let shared = CodeRunOutputStore()

    @Published private(set) var outputsByEmbedId: [String: CodeRunOutput] = [:]
    private var scopeGeneration = OfflineStore.shared.scopeGeneration
    private var pendingHydrations: [String: (chatId: String, embedId: String)] = [:]
    private var pendingCompletedRuns = PendingCodeRunRetryQueue()
    private var sendAttempts: [String: (ciphertext: String, transportGeneration: Int)] = [:]
    private var isFlushing = false
    private init() {}

    private static func cacheKey(chatId: String, embedId: String) -> String {
        "\(chatId):\(embedId)"
    }

    private func resetIfScopeChanged() {
        let current = OfflineStore.shared.scopeGeneration
        guard current != scopeGeneration else { return }
        scopeGeneration = current
        outputsByEmbedId.removeAll()
        pendingHydrations.removeAll()
        pendingCompletedRuns.removeAll()
        sendAttempts.removeAll()
    }

    func output(chatId: String, embedId: String) -> CodeRunOutput? {
        resetIfScopeChanged()
        return outputsByEmbedId[Self.cacheKey(chatId: chatId, embedId: embedId)]
    }

    func remove(chatId: String) {
        resetIfScopeChanged()
        outputsByEmbedId = outputsByEmbedId.filter { $0.value.chatId != chatId }
        pendingHydrations = pendingHydrations.filter { $0.value.chatId != chatId }
        pendingCompletedRuns.remove(chatId: chatId)
    }

    func clearAll() {
        outputsByEmbedId.removeAll()
        pendingHydrations.removeAll()
        pendingCompletedRuns.removeAll()
        sendAttempts.removeAll()
    }

    #if DEBUG
    /// In-memory preview fixture only; never writes a chat row or sends a socket message.
    func seedPreviewOutput(chatId: String, embedId: String, output: String) {
        resetIfScopeChanged()
        let nowMilliseconds = Int(Date().timeIntervalSince1970 * 1000)
        let now = Double(nowMilliseconds / 1000)
        outputsByEmbedId[Self.cacheKey(chatId: chatId, embedId: embedId)] = CodeRunOutput(
            id: "preview-\(embedId)", chatId: chatId, embedId: embedId,
            output: output, status: "exited", files: [], events: [], artifacts: [],
            skippedArtifacts: [], savedAt: now * 1000, createdAt: now, updatedAt: now
        )
    }
    #endif

    func ingest(_ payload: CodeRunOutputSyncedPayload, expectedScope: UUID? = nil) async {
        resetIfScopeChanged()
        let fence = CodeRunScopeFence(store: OfflineStore.shared)
        guard (expectedScope == nil || expectedScope == fence.generation),
              fence.isCurrent(in: OfflineStore.shared),
              !payload.chatId.isEmpty, !payload.embedId.isEmpty,
              !payload.encryptedPayload.isEmpty else { return }
        do {
            let local = OfflineStore.shared.loadCodeRunOutput(chatId: payload.chatId, embedId: payload.embedId)
            if local?.needsSync == true,
               local?.id == payload.id,
               local?.encryptedPayload == payload.encryptedPayload {
                try OfflineStore.shared.acknowledgeCodeRunOutput(
                    id: payload.id, encryptedPayload: payload.encryptedPayload
                )
                sendAttempts.removeValue(forKey: payload.id)
            } else {
                try OfflineStore.shared.persistCodeRunOutput(PersistedCodeRunOutput(
            id: payload.id, chatId: payload.chatId, embedId: payload.embedId,
            authorUserId: payload.authorUserId, encryptedPayload: payload.encryptedPayload,
            keyVersion: payload.keyVersion, createdAt: payload.createdAt,
            updatedAt: payload.updatedAt
                ))
            }
        } catch {
            NativeDiagnostics.warning("Code Run output local write failed: \(type(of: error))", category: "sync")
            return
        }
        guard fence.isCurrent(in: OfflineStore.shared) else { return }
        await hydrate(chatId: payload.chatId, embedId: payload.embedId, requestRemote: false)
    }

    func ingestRows(_ rows: [CodeRunOutputSyncedPayload], chatId: String? = nil,
                    expectedScope: UUID? = nil) async {
        let capturedScope = expectedScope ?? OfflineStore.shared.scopeGeneration
        for row in rows where chatId == nil || row.chatId == chatId {
            guard capturedScope == OfflineStore.shared.scopeGeneration else { return }
            await ingest(row, expectedScope: capturedScope)
        }
    }

    func hydrate(chatId: String, embedId: String, embed: EmbedRecord? = nil,
                 requestRemote: Bool = true) async {
        resetIfScopeChanged()
        let fence = CodeRunScopeFence(store: OfflineStore.shared)
        guard fence.isCurrent(in: OfflineStore.shared) else { return }
        guard let stored = OfflineStore.shared.loadCodeRunOutput(chatId: chatId, embedId: embedId) else {
            if requestRemote { await requestOutput(chatId: chatId, embedId: embedId, fence: fence) }
            return
        }
        let records = OfflineStore.shared.loadEmbeds(chatId: chatId)
        var allEmbeds = EmbedRecord.dictionaryById(records, context: "codeRunOutputHydration")
        if let embed { allEmbeds[embed.id] = embed }
        guard let record = allEmbeds[embedId],
              let key = await EmbedKeyManager.shared.key(for: record, chatId: chatId, allEmbeds: allEmbeds) else {
            guard fence.isCurrent(in: OfflineStore.shared) else { return }
            // Keep ciphertext so a later embed-key arrival can retry decryption.
            pendingHydrations[Self.cacheKey(chatId: chatId, embedId: embedId)] = (chatId, embedId)
            if requestRemote { await requestOutput(chatId: chatId, embedId: embedId, fence: fence) }
            return
        }
        guard fence.isCurrent(in: OfflineStore.shared) else { return }
        guard let plaintext = try? ComposerEmbedCrypto.decryptContent(stored.encryptedPayload, using: key),
              let output = Self.decodeOutput(plaintext, row: stored),
              fence.isCurrent(in: OfflineStore.shared) else {
            if requestRemote { await requestOutput(chatId: chatId, embedId: embedId, fence: fence) }
            return
        }
        pendingHydrations.removeValue(forKey: Self.cacheKey(chatId: chatId, embedId: embedId))
        outputsByEmbedId[Self.cacheKey(chatId: chatId, embedId: embedId)] = output
        if requestRemote { await requestOutput(chatId: chatId, embedId: embedId, fence: fence) }
    }

    func saveCompletedRun(chatId: String, embedId: String, embed: EmbedRecord,
                          output: String, status: String, files: [String],
                          events: [CodeRunEvent], artifacts: [[String: Any]] = [],
                          skippedArtifacts: [[String: Any]] = []) async throws {
        resetIfScopeChanged()
        let fence = CodeRunScopeFence(store: OfflineStore.shared)
        guard fence.isCurrent(in: OfflineStore.shared) else { throw WebSocketError.notConnected }
        var allEmbeds = EmbedRecord.dictionaryById(
            OfflineStore.shared.loadEmbeds(chatId: chatId), context: "codeRunOutputSave"
        )
        allEmbeds[embed.id] = embed
        let availableKey = await EmbedKeyManager.shared.key(for: embed, chatId: chatId, allEmbeds: allEmbeds)
        guard fence.isCurrent(in: OfflineStore.shared) else { throw WebSocketError.notConnected }
        guard let key = availableKey else {
            pendingCompletedRuns.enqueue(PendingCodeRunSnapshot(
                chatId: chatId, embedId: embedId, embed: embed, output: output,
                status: status, files: files, events: events, artifacts: artifacts,
                skippedArtifacts: skippedArtifacts
            ), fence: fence)
            throw CodeRunOutputError.missingEmbedKey
        }
        let nowMilliseconds = Int(Date().timeIntervalSince1970 * 1000)
        let now = Double(nowMilliseconds / 1000)
        let existing = OfflineStore.shared.loadCodeRunOutput(chatId: chatId, embedId: embedId)
        let id = existing?.id ?? UUID().uuidString
        let createdAt = existing?.createdAt ?? now
        let previousArtifacts: [[String: Any]]
        if let existing,
           let priorJSON = try? ComposerEmbedCrypto.decryptContent(existing.encryptedPayload, using: key),
           let prior = Self.decodeOutput(priorJSON, row: existing) {
            previousArtifacts = prior.artifacts
        } else {
            previousArtifacts = []
        }
        let sanitizedArtifacts = Self.mergeArtifactHistory(
            previous: previousArtifacts, latest: artifacts, capturedAt: now
        )
        let sanitizedSkipped = skippedArtifacts.compactMap { item -> [String: String]? in
            guard let path = item["path"] as? String,
                  let reason = item["reason"] as? String else { return nil }
            return ["path": path, "reason": reason]
        }
        let plain: [String: Any] = [
            "output": output, "status": status, "files": files,
            "events": events.map { ["kind": $0.kind.rawValue, "text": $0.text, "timestamp": $0.timestamp] as [String: Any] },
            "artifacts": sanitizedArtifacts, "skipped_artifacts": sanitizedSkipped,
            "saved_at": nowMilliseconds, "created_at": createdAt, "updated_at": now,
        ]
        let data = try JSONSerialization.data(withJSONObject: plain)
        guard let json = String(data: data, encoding: .utf8) else { throw WebSocketError.encodingFailed }
        let encrypted = try ComposerEmbedCrypto.encryptContent(json, using: key)
        guard fence.isCurrent(in: OfflineStore.shared) else { throw WebSocketError.notConnected }
        let authorUserId = await AuthManager.currentUserId()
        guard fence.isCurrent(in: OfflineStore.shared), authorUserId != nil else {
            throw WebSocketError.notConnected
        }
        let stored = PersistedCodeRunOutput(
            id: id, chatId: chatId, embedId: embedId, authorUserId: authorUserId,
            encryptedPayload: encrypted, keyVersion: nil, createdAt: createdAt,
            updatedAt: now, needsSync: true
        )
        try OfflineStore.shared.persistCodeRunOutput(stored)
        guard fence.isCurrent(in: OfflineStore.shared) else { throw WebSocketError.notConnected }
        pendingCompletedRuns.remove(chatId: chatId, embedId: embedId)
        outputsByEmbedId[Self.cacheKey(chatId: chatId, embedId: embedId)] =
            Self.decodeOutput(json, row: stored)
        var inferencePayload = plain
        inferencePayload["artifacts"] = Self.sanitizeArtifacts(sanitizedArtifacts, includeSensitive: false)
        let wsManager = AppSessionCoordinator.shared.webSocketManager
        let transportGeneration = wsManager.transportGeneration
        try await wsManager.send(WSOutboundMessage(
            type: "upsert_code_run_output",
            payload: [
                "chat_id": chatId, "embed_id": embedId, "id": id,
                "key_version": NSNull(),
                "encrypted_payload": encrypted, "inference_payload": inferencePayload,
                "created_at": createdAt, "updated_at": now,
            ]
        ))
        guard fence.isCurrent(in: OfflineStore.shared) else { return }
        sendAttempts[id] = (encrypted, transportGeneration)
    }

    /// Retry locally encrypted writes once per socket generation. A server echo
    /// clears needsSync; successful transport send alone is not an acknowledgment.
    func flushPendingUploads() async {
        resetIfScopeChanged()
        guard !isFlushing else { return }
        let fence = CodeRunScopeFence(store: OfflineStore.shared)
        guard fence.isCurrent(in: OfflineStore.shared) else { return }
        let wsManager = AppSessionCoordinator.shared.webSocketManager
        guard wsManager.isConnected else { return }
        isFlushing = true
        defer { isFlushing = false }
        let rows: [PersistedCodeRunOutput]
        do {
            rows = try OfflineStore.shared.pendingCodeRunOutputs()
        } catch {
            NativeDiagnostics.warning("Code Run pending-output read failed: \(type(of: error))", category: "sync")
            return
        }
        for row in rows.prefix(100) {
            guard fence.isCurrent(in: OfflineStore.shared), wsManager.isConnected else { return }
            let transportGeneration = wsManager.transportGeneration
            if let attempted = sendAttempts[row.id],
               attempted.ciphertext == row.encryptedPayload,
               attempted.transportGeneration == transportGeneration { continue }
            let records = OfflineStore.shared.loadEmbeds(chatId: row.chatId)
            let allEmbeds = EmbedRecord.dictionaryById(records, context: "codeRunOutputRetry")
            guard let embed = allEmbeds[row.embedId],
                  let key = await EmbedKeyManager.shared.key(
                    for: embed, chatId: row.chatId, allEmbeds: allEmbeds
                  ), fence.isCurrent(in: OfflineStore.shared) else { continue }
            guard let plaintext = try? ComposerEmbedCrypto.decryptContent(row.encryptedPayload, using: key),
                  let output = Self.decodeOutput(plaintext, row: row) else { continue }
            let userId = await AuthManager.currentUserId()
            guard fence.isCurrent(in: OfflineStore.shared),
                  let userId, userId == row.authorUserId else { return }
            let inferencePayload: [String: Any] = [
                "output": output.output, "status": output.status ?? "unknown",
                "files": output.files, "saved_at": output.savedAt,
                "created_at": output.createdAt, "updated_at": output.updatedAt,
                "artifacts": Self.sanitizeArtifacts(output.artifacts, includeSensitive: false),
                "skipped_artifacts": output.skippedArtifacts,
            ]
            do {
                try await wsManager.send(WSOutboundMessage(type: "upsert_code_run_output", payload: [
                    "chat_id": row.chatId, "embed_id": row.embedId, "id": row.id,
                    "key_version": row.keyVersion.map { $0 as Any } ?? NSNull(),
                    "encrypted_payload": row.encryptedPayload,
                    "inference_payload": inferencePayload,
                    "created_at": row.createdAt, "updated_at": row.updatedAt,
                ]))
                guard fence.isCurrent(in: OfflineStore.shared) else { return }
                sendAttempts[row.id] = (row.encryptedPayload, transportGeneration)
            } catch {
                NativeDiagnostics.warning("Code Run output resend failed: \(type(of: error))", category: "sync")
                return
            }
        }
    }

    func handleEmbedKeysAvailable() async {
        resetIfScopeChanged()
        let fence = CodeRunScopeFence(store: OfflineStore.shared)
        let completed = pendingCompletedRuns.drainCurrent(in: OfflineStore.shared)
        for snapshot in completed {
            guard fence.isCurrent(in: OfflineStore.shared) else { return }
            try? await saveCompletedRun(
                chatId: snapshot.chatId, embedId: snapshot.embedId, embed: snapshot.embed,
                output: snapshot.output, status: snapshot.status, files: snapshot.files,
                events: snapshot.events, artifacts: snapshot.artifacts,
                skippedArtifacts: snapshot.skippedArtifacts
            )
        }
        guard fence.isCurrent(in: OfflineStore.shared) else { return }
        let pending = Array(pendingHydrations.values)
        for entry in pending {
            guard fence.isCurrent(in: OfflineStore.shared) else { return }
            await hydrate(chatId: entry.chatId, embedId: entry.embedId, requestRemote: false)
        }
        guard fence.isCurrent(in: OfflineStore.shared) else { return }
        await flushPendingUploads()
    }

    private func requestOutput(chatId: String, embedId: String, fence: CodeRunScopeFence) async {
        guard fence.isCurrent(in: OfflineStore.shared) else { return }
        try? await AppSessionCoordinator.shared.webSocketManager.send(WSOutboundMessage(
            type: "request_code_run_output", payload: ["chat_id": chatId, "embed_id": embedId]
        ))
    }

    static func sanitizeArtifacts(_ artifacts: [[String: Any]], includeSensitive: Bool) -> [[String: Any]] {
        let stringFields = ["path", "normalized_path", "mime_type", "kind", "status", "asset_id", "variant"]
        let numberFields = ["size_bytes", "download_expires_at", "captured_at"]
        let forbiddenFields: Set<String> = [
            "aes_key", "aes_nonce", "bytes", "content_base64", "s3_key",
            "sandbox_id", "token", "vault_wrapped_aes_key",
        ]
        return artifacts.compactMap { artifact in
            guard forbiddenFields.isDisjoint(with: artifact.keys),
                  let path = (artifact["path"] as? String) ?? (artifact["normalized_path"] as? String),
                  !path.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            var safe: [String: Any] = [:]
            for field in stringFields {
                if let value = artifact[field] as? String { safe[field] = value }
            }
            for field in numberFields {
                if let value = artifact[field] as? NSNumber { safe[field] = value }
            }
            safe["path"] = path
            safe["normalized_path"] = (artifact["normalized_path"] as? String) ?? path
            if includeSensitive {
                if let url = artifact["download_url"] as? String { safe["download_url"] = url }
                if let native = artifact["native_render_payload"] as? [String: Any] {
                    safe["native_render_payload"] = native
                }
            }
            if let versions = artifact["versions"] as? [[String: Any]] {
                safe["versions"] = sanitizeArtifacts(versions, includeSensitive: includeSensitive)
            }
            return safe
        }
    }

    static func mergeArtifactHistory(previous: [[String: Any]], latest: [[String: Any]],
                                     capturedAt: Double) -> [[String: Any]] {
        let prior = sanitizeArtifacts(previous, includeSensitive: true)
        let priorByPath = Dictionary(prior.map { artifact in
            ((artifact["normalized_path"] as? String) ?? (artifact["path"] as? String) ?? "", artifact)
        }, uniquingKeysWith: { _, last in last })
        return sanitizeArtifacts(latest, includeSensitive: true).map { latestArtifact in
            var current = latestArtifact
            if current["captured_at"] == nil { current["captured_at"] = capturedAt }
            let path = (current["normalized_path"] as? String) ?? (current["path"] as? String) ?? ""
            guard let old = priorByPath[path] else { return current }
            var oldHead = old
            oldHead.removeValue(forKey: "versions")
            oldHead.removeValue(forKey: "native_render_payload")
            let candidates = [oldHead] + ((old["versions"] as? [[String: Any]]) ?? [])
            var seen = Set<String>()
            let versions = candidates.filter { version in
                let identity = ["asset_id", "variant", "normalized_path", "captured_at",
                                "download_expires_at", "size_bytes", "status"]
                    .map { String(describing: version[$0] ?? "") }.joined(separator: "|")
                return seen.insert(identity).inserted
            }.sorted {
                (($0["captured_at"] as? NSNumber)?.doubleValue ?? 0) >
                    (($1["captured_at"] as? NSNumber)?.doubleValue ?? 0)
            }
            if !versions.isEmpty { current["versions"] = versions }
            return current
        }
    }

    private static func decodeOutput(_ json: String, row: PersistedCodeRunOutput) -> CodeRunOutput? {
        guard let data = json.data(using: .utf8),
              let plain = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let output = plain["output"] as? String,
              let savedAt = (plain["saved_at"] as? NSNumber)?.doubleValue else { return nil }
        let events = (plain["events"] as? [[String: Any]] ?? []).compactMap { event -> CodeRunEvent? in
            guard let kindString = event["kind"] as? String,
                  let kind = CodeRunEvent.Kind(rawValue: kindString),
                  let text = event["text"] as? String,
                  let timestamp = (event["timestamp"] as? NSNumber)?.doubleValue else { return nil }
            return CodeRunEvent(kind: kind, text: text, timestamp: timestamp)
        }
        return CodeRunOutput(
            id: row.id, chatId: row.chatId, embedId: row.embedId, output: output,
            status: plain["status"] as? String,
            files: (plain["files"] as? [String]) ?? [], events: events,
            artifacts: (plain["artifacts"] as? [[String: Any]]) ?? [],
            skippedArtifacts: (plain["skipped_artifacts"] as? [[String: Any]]) ?? [],
            savedAt: savedAt,
            createdAt: (plain["created_at"] as? NSNumber)?.doubleValue ?? row.createdAt,
            updatedAt: (plain["updated_at"] as? NSNumber)?.doubleValue ?? row.updatedAt
        )
    }
}

enum CodeRunOutputError: Error {
    case missingEmbedKey
}
