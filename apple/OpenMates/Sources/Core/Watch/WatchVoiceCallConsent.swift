// Custom Watch consent presentation state; persistence remains in the real call environment.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy.first-call-warning
import Foundation
import Combine

@MainActor
final class WatchVoiceCallConsent: ObservableObject {
    @Published private(set) var isPresented = false
    private var pending: (id: UUID, continuation: CheckedContinuation<Bool, Never>)?
    func request() async -> Bool {
        guard pending == nil, !Task.isCancelled else { return false }
        let id = UUID()
        return await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { continuation in
                guard !Task.isCancelled else { continuation.resume(returning: false); return }
                pending = (id, continuation); isPresented = true
            }
        }, onCancel: { Task { @MainActor [weak self] in self?.finish(false, id: id) } })
    }
    func finish(_ accepted: Bool) { finish(accepted, id: pending?.id) }
    private func finish(_ accepted: Bool, id: UUID?) {
        guard let pending, pending.id == id else { return }
        self.pending = nil; isPresented = false
        pending.continuation.resume(returning: accepted)
    }
    func cancel() { finish(false) }
}
