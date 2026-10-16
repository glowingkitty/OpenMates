// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.cold.discoverable-bounded, storage.cold.shared-team-authorized, storage.surface.semantic-parity
import Combine
import Foundation

@MainActor
final class StorageNoticeController: ObservableObject {
    typealias Loader = @MainActor (String?) async throws -> StorageNotice
    @Published private(set) var notice: StorageNotice?
    @Published private(set) var loading = false
    @Published private(set) var failed = false
    private var generation = UUID()
    private var loader: Loader?
    private var limit = 20

    func reset() {
        generation = UUID(); loader = nil; notice = nil; loading = false; failed = false
    }

    func configure(limit: Int, loader: @escaping Loader) async {
        reset(); self.limit = limit; self.loader = loader
        await load()
    }

    func load(more: Bool = false) async {
        guard !loading, let loader else { return }
        let after = more ? notice?.nextAfterUnitId : nil
        if more && (notice?.hasMore != true || after == nil) { return }
        let token = generation
        loading = true; failed = false
        do {
            let page = try await loader(after)
            guard generation == token else { return }
            notice = try StorageNoticePaging.merge(page, previous: notice, after: after, limit: limit)
            loading = false
        } catch StorageStatusError.changedEpisode {
            guard generation == token else { return }
            notice = nil; loading = false
            await load()
        } catch {
            guard generation == token else { return }
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            loading = false; failed = true
        }
    }
}
