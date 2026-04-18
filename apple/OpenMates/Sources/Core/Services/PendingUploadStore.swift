// Pending upload store — manages file uploads and deferred message sends.
// Mirrors the web app's pendingUploadStore.ts: when a user sends a message while
// file uploads are in-flight, the send is queued and auto-dispatched when all
// blocking uploads finish.

import Foundation
import SwiftUI

@MainActor
final class PendingUploadStore: ObservableObject {
    static let shared = PendingUploadStore()

    @Published private(set) var activeUploads: [String: EmbedUploadProgress] = [:]
    @Published private(set) var pendingSends: [String: [PendingSendContext]] = [:]

    private init() {}

    // MARK: - Upload progress tracking

    struct EmbedUploadProgress: Identifiable {
        let id: String
        let chatId: String
        let filename: String
        var progress: Double  // 0.0 - 1.0
        var status: UploadStatus

        enum UploadStatus: Equatable {
            case uploading
            case processing
            case transcribing
            case finished
            case error(String)

            var isComplete: Bool {
                if case .finished = self { return true }
                return false
            }

            var isError: Bool {
                if case .error = self { return true }
                return false
            }
        }
    }

    struct PendingSendContext: Identifiable {
        let id = UUID().uuidString
        let chatId: String
        let messageContent: String
        let blockingUploadIds: Set<String>
        let createdAt: Date
    }

    // MARK: - Start tracking an upload

    func startUpload(id: String, chatId: String, filename: String) {
        activeUploads[id] = EmbedUploadProgress(
            id: id, chatId: chatId, filename: filename,
            progress: 0, status: .uploading
        )
    }

    // MARK: - Update progress

    func updateProgress(id: String, progress: Double) {
        activeUploads[id]?.progress = progress
    }

    func updateStatus(id: String, status: EmbedUploadProgress.UploadStatus) {
        activeUploads[id]?.status = status

        if status.isComplete || status.isError {
            checkAndDispatchPendingSends(uploadId: id)
        }
    }

    // MARK: - Mark upload finished

    func markFinished(id: String) {
        activeUploads[id]?.status = .finished
        activeUploads[id]?.progress = 1.0
        checkAndDispatchPendingSends(uploadId: id)

        // Clean up after a delay
        Task {
            try? await Task.sleep(for: .seconds(2))
            activeUploads.removeValue(forKey: id)
        }
    }

    func markError(id: String, message: String) {
        activeUploads[id]?.status = .error(message)
        checkAndDispatchPendingSends(uploadId: id)
    }

    // MARK: - Queue a deferred send

    func addPendingSend(chatId: String, content: String, blockingUploadIds: Set<String>) {
        let context = PendingSendContext(
            chatId: chatId, messageContent: content,
            blockingUploadIds: blockingUploadIds, createdAt: Date()
        )
        pendingSends[chatId, default: []].append(context)
    }

    // MARK: - Check if pending sends can be dispatched

    private func checkAndDispatchPendingSends(uploadId: String) {
        for (chatId, contexts) in pendingSends {
            for context in contexts {
                if context.blockingUploadIds.contains(uploadId) {
                    let remainingBlocking = context.blockingUploadIds.filter { id in
                        guard let upload = activeUploads[id] else { return false }
                        return !upload.status.isComplete && !upload.status.isError
                    }

                    if remainingBlocking.isEmpty {
                        dispatchPendingSend(context)
                        pendingSends[chatId]?.removeAll { $0.id == context.id }
                        if pendingSends[chatId]?.isEmpty == true {
                            pendingSends.removeValue(forKey: chatId)
                        }
                    }
                }
            }
        }
    }

    private func dispatchPendingSend(_ context: PendingSendContext) {
        Task {
            let body: [String: Any] = [
                "chat_id": context.chatId,
                "message": [
                    "message_id": UUID().uuidString,
                    "role": "user",
                    "content": context.messageContent,
                    "created_at": Int(Date().timeIntervalSince1970),
                    "chat_has_title": true,
                ] as [String: Any],
            ]
            do {
                let _: Data = try await APIClient.shared.request(.post, path: "/v1/chat/message", body: body)
            } catch {
                print("[PendingUpload] Deferred send failed for chat \(context.chatId): \(error)")
            }
        }
    }

    // MARK: - Query

    func hasActiveUploads(chatId: String) -> Bool {
        activeUploads.values.contains { $0.chatId == chatId && !$0.status.isComplete && !$0.status.isError }
    }

    func hasPendingSends(chatId: String) -> Bool {
        !(pendingSends[chatId]?.isEmpty ?? true)
    }

    func uploadsForChat(_ chatId: String) -> [EmbedUploadProgress] {
        activeUploads.values.filter { $0.chatId == chatId }.sorted { $0.filename < $1.filename }
    }

    // MARK: - Clear (on logout or chat delete)

    func clearForChat(_ chatId: String) {
        activeUploads = activeUploads.filter { $0.value.chatId != chatId }
        pendingSends.removeValue(forKey: chatId)
    }

    func clearAll() {
        activeUploads.removeAll()
        pendingSends.removeAll()
    }
}

// MARK: - Upload progress bar view

struct UploadProgressBar: View {
    let uploads: [PendingUploadStore.EmbedUploadProgress]

    var body: some View {
        if !uploads.isEmpty {
            VStack(spacing: .spacing2) {
                ForEach(uploads) { upload in
                    HStack(spacing: .spacing3) {
                        Image(systemName: iconForStatus(upload.status))
                            .font(.system(size: 12))
                            .foregroundStyle(colorForStatus(upload.status))

                        Text(upload.filename)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(1)

                        Spacer()

                        if case .error(let msg) = upload.status {
                            Text(msg)
                                .font(.omTiny)
                                .foregroundStyle(Color.error)
                        } else if !upload.status.isComplete {
                            Text("\(Int(upload.progress * 100))%")
                                .font(.omTiny).monospacedDigit()
                                .foregroundStyle(Color.fontTertiary)
                        }
                    }

                    if !upload.status.isComplete && !upload.status.isError {
                        ProgressView(value: upload.progress)
                            .tint(Color.buttonPrimary)
                    }
                }
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing2)
            .background(Color.grey10.opacity(0.5))
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Uploading \(uploads.count) file\(uploads.count == 1 ? "" : "s")")
        }
    }

    private func iconForStatus(_ status: PendingUploadStore.EmbedUploadProgress.UploadStatus) -> String {
        switch status {
        case .uploading: return "arrow.up.circle"
        case .processing, .transcribing: return "gearshape"
        case .finished: return "checkmark.circle.fill"
        case .error: return "exclamationmark.circle"
        }
    }

    private func colorForStatus(_ status: PendingUploadStore.EmbedUploadProgress.UploadStatus) -> Color {
        switch status {
        case .uploading, .processing, .transcribing: return Color.buttonPrimary
        case .finished: return .green
        case .error: return Color.error
        }
    }
}
