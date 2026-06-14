// Code Run API client and state machine for native code embed execution.
// Mirrors frontend/packages/ui/src/services/codeRunService.ts and the web
// CodeEmbedFullscreen run panel. Uses the same /v1/code/run endpoints to start,
// poll, and cancel E2B sandbox executions for code embeds.

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

    func start(chatId: String?, embedId: String, file: CodeRunClientFile) async {
        guard let chatId, !chatId.isEmpty, !isActive else { return }
        pollTask?.cancel()
        isPanelOpen = true
        status = .queued
        errorMessage = nil
        isCancelling = false
        files = []
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
            status = .failed
            errorMessage = error.localizedDescription
            events = [CodeRunEvent(kind: .stderr, text: "\(error.localizedDescription)\n", timestamp: Date().timeIntervalSince1970)]
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
            status = response.status
            isCancelling = response.status == .cancelling
            events = response.events ?? events
            files = response.files ?? files
            errorMessage = response.error
            return response.status.isTerminal
        } catch {
            status = .failed
            errorMessage = error.localizedDescription
            events.append(CodeRunEvent(kind: .stderr, text: "\(error.localizedDescription)\n", timestamp: Date().timeIntervalSince1970))
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
