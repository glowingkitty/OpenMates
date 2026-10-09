// Optional, consent-based sequence over the existing pinned model store.
// Production speech adapters resolve verified assets independently; this coordinator
// changes no route preferences and never activates Enhanced PII.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.optional-downloads
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.download.progress, apple-live-activities.download.completion
import Combine
import Foundation

enum OfflineAIModelPackPhase: String, Codable, Sendable {
    case offered, deferred, downloading, paused, cancelled, failed, complete
}

struct OfflineAIModelPackSnapshot: Codable, Equatable, Sendable {
    var phase: OfflineAIModelPackPhase = .deferred
    var currentModel: LocalModelID?
    var transferredBytes: Int64 = 0
    var verifiedBytes: Int64 = 0
    var totalBytes: Int64 = 0
    var modelFraction: Double = 0
    var modelPhase: LocalModelInstallPhase?
    var completedModels: Int = 0
    var failureMessage: String?
    var nextOfferDate: Date?
}

/// Device-local public asset consent and byte counts. No account/chat/audio/text
/// data is persisted here. The store consults this before recovering paused work.
enum OfflineAIModelPackPersistence {
    static let key = "openmates.offline-ai-pack.v1"
    static func read(_ defaults: UserDefaults = .standard) -> OfflineAIModelPackSnapshot? {
        guard let data = defaults.data(forKey: key) else { return nil }
        return try? JSONDecoder().decode(OfflineAIModelPackSnapshot.self, from: data)
    }
    static func allowsRecovery(_ id: LocalModelID, defaults: UserDefaults = .standard) -> Bool {
        guard let saved = read(defaults), saved.currentModel == id else { return true }
        return saved.phase == .downloading
    }
}

@MainActor
final class OfflineAIModelPack: ObservableObject {
    static let shared = OfflineAIModelPack(store: .shared,
        packActivity: { LocalModelLiveActivityCoordinator.shared.setPackActive($0) })
    /// The order is product behavior, independent of catalog serialization order.
    static let order: [LocalModelID] = [.whisper, .supertonic3, .privacyFilter]
    @Published private(set) var snapshot: OfflineAIModelPackSnapshot
    private let store: LocalModelStore
    private let defaults: UserDefaults
    private let clock: () -> Date
    private let packActivity: @MainActor (Bool) -> Void
    private var observers: Set<AnyCancellable> = []
    private var bootstrap: Task<Void, Never>?
    private var job: Task<Void, Never>?
    private var generation = UUID()
    private var offerRequested = false
    private var restored = false

    init(store: LocalModelStore, defaults: UserDefaults = .standard, clock: @escaping () -> Date = Date.init,
         packActivity: @escaping @MainActor (Bool) -> Void = { _ in }) {
        self.store = store; self.defaults = defaults; self.clock = clock; self.packActivity = packActivity
        var saved = OfflineAIModelPackPersistence.read(defaults) ?? OfflineAIModelPackSnapshot()
        // A persisted offer needs another eligible activation. A completed
        // receipt also needs fresh local validation before claiming readiness.
        if saved.phase == .offered || saved.phase == .complete { saved.phase = .deferred }
        saved.totalBytes = Self.order.reduce(0) { $0 + (store.manifest(for: $1)?.estimatedSizeBytes ?? 0) }
        snapshot = saved
        store.$states.sink { [weak self] _ in
            Task { @MainActor [weak self] in self?.refreshProgress() }
        }.store(in: &observers)
        store.$progressByModel.sink { [weak self] _ in
            Task { @MainActor [weak self] in self?.refreshProgress() }
        }.store(in: &observers)
        if saved.phase == .downloading { beginBootstrap() }
    }

    private func beginBootstrap() {
        guard bootstrap == nil, !restored else { return }
        bootstrap = Task { [weak self] in
            guard let self else { return }
            await store.waitUntilRestored()
            // Installed receipts alone never imply usable models. Hash existing
            // files off the main actor before skipping a model in this pack.
            await store.restoreExisting(validateInstalled: true)
            restored = true
            if snapshot.phase == .downloading { startDownload() }
            else if Self.order.allSatisfy({ store.state(for: $0) == .ready }) {
                snapshot.phase = .complete; snapshot.currentModel = nil
                refreshProgress(); persist()
            } else {
                if snapshot.phase == .complete {
                    snapshot.phase = .deferred
                    snapshot.transferredBytes = 0; snapshot.verifiedBytes = 0
                    snapshot.modelFraction = 0; snapshot.modelPhase = nil
                    persist()
                }
                if offerRequested { showOfferIfDue() }
            }
        }
    }

    func waitUntilRestored() async { beginBootstrap(); await bootstrap?.value }

    /// Call from an eligible composer activation. Timers alone never show a prompt.
    func offerIfNeeded() {
        offerRequested = true
        if restored { showOfferIfDue() } else { beginBootstrap() }
    }
    private func showOfferIfDue() {
        guard snapshot.phase == .deferred,
              snapshot.nextOfferDate.map({ $0 <= clock() }) ?? true else { return }
        snapshot.phase = .offered
        persist()
    }
    func deferDownload() {
        guard snapshot.phase == .offered || snapshot.phase == .deferred else { return }
        snapshot.phase = .deferred
        snapshot.nextOfferDate = clock().addingTimeInterval(24 * 60 * 60)
        persist()
    }
    /// The only initial transfer entry point. Resuming a persisted downloading
    /// phase follows the previous explicit consent; Later never grants it.
    func download() {
        guard job == nil else { return }
        if snapshot.phase == .cancelled || snapshot.phase == .failed {
            snapshot.transferredBytes = 0; snapshot.verifiedBytes = 0; snapshot.modelFraction = 0
        }
        snapshot.phase = .downloading; snapshot.failureMessage = nil; snapshot.nextOfferDate = nil
        persist()
        if restored { startDownload() } else { beginBootstrap() }
    }
    func pause() { stop(as: .paused) }
    func cancel() { stop(as: .cancelled) }
    private func stop(as phase: OfflineAIModelPackPhase) {
        guard snapshot.phase == .downloading || snapshot.phase == .paused || snapshot.phase == .failed else { return }
        generation = UUID()
        snapshot.phase = phase
        if phase == .cancelled {
            let bytes = Self.order.filter { store.state(for: $0) == .ready }
                .reduce(Int64(0)) { $0 + (store.manifest(for: $1)?.estimatedSizeBytes ?? 0) }
            snapshot.transferredBytes = bytes; snapshot.verifiedBytes = bytes; snapshot.modelFraction = 0
            snapshot.modelPhase = nil
        }
        // Persist before cancellation so a process interruption cannot requeue.
        persist()
        if let id = snapshot.currentModel {
            if phase == .paused { store.pause(id) } else { store.cancel(id) }
        }
        job?.cancel(); job = nil
        store.setSequentialPackActive(false)
        packActivity(false)
    }
    private func startDownload() {
        guard job == nil, snapshot.phase == .downloading else { return }
        do { try store.checkSpaceForDownloads(Self.order) }
        catch { fail(AppStrings.localLabNotEnoughSpace); return }
        store.setSequentialPackActive(true)
        packActivity(true)
        let token = UUID(); generation = token
        job = Task { [weak self] in
            guard let self else { return }
            for id in Self.order {
                guard !Task.isCancelled, generation == token, snapshot.phase == .downloading else { return }
                guard store.manifest(for: id) != nil else {
                    fail(store.catalogError ?? AppStrings.localLabDownloadFailed); return
                }
                if store.state(for: id) == .ready { continue }
                snapshot.currentModel = id
                refreshProgress(); persist()
                // Existing lab/recovered ownership is joined, never duplicated.
                await store.download(id)
                guard !Task.isCancelled, generation == token, snapshot.phase == .downloading else { return }
                guard store.state(for: id) == .ready else {
                    if case .failed(let message) = store.state(for: id) { fail(message) }
                    else { fail(AppStrings.localLabDownloadFailed) }
                    return
                }
                refreshProgress(); persist()
            }
            guard generation == token else { return }
            snapshot.phase = .complete; snapshot.currentModel = nil
            refreshProgress(); persist(); job = nil
            store.setSequentialPackActive(false); packActivity(false)
        }
    }
    private func fail(_ message: String) {
        snapshot.phase = .failed; snapshot.failureMessage = message
        persist(); job = nil
        if let id = snapshot.currentModel { store.cancel(id) }
        store.setSequentialPackActive(false); packActivity(false)
    }
    private func refreshProgress() {
        let ready = Self.order.filter { store.state(for: $0) == .ready }
        let completed = ready.reduce(Int64(0)) { $0 + (store.manifest(for: $1)?.estimatedSizeBytes ?? 0) }
        let progress = snapshot.currentModel.flatMap { store.progress(for: $0) }
        snapshot.completedModels = ready.count
        if snapshot.phase == .downloading || snapshot.phase == .complete {
            snapshot.transferredBytes = min(snapshot.totalBytes,
                max(snapshot.transferredBytes, completed + (progress?.transferredBytes ?? 0)))
            snapshot.verifiedBytes = min(snapshot.totalBytes,
                max(snapshot.verifiedBytes, completed + (progress?.verifiedBytes ?? 0)))
            snapshot.modelPhase = progress?.phase
            snapshot.modelFraction = progress?.fraction ?? (snapshot.phase == .complete ? 1 : 0)
            // A ready current model is already included in the completed sum.
            if let id = snapshot.currentModel, ready.contains(id) {
                snapshot.transferredBytes = max(snapshot.transferredBytes, completed)
                snapshot.verifiedBytes = max(snapshot.verifiedBytes, completed)
                snapshot.modelFraction = 1
            }
            persist()
        }
    }
    private func persist() {
        if let data = try? JSONEncoder().encode(snapshot) { defaults.set(data, forKey: OfflineAIModelPackPersistence.key) }
    }
}
