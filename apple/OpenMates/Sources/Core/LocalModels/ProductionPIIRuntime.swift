// Local, pinned OpenAI privacy-filter adaptation; no network inference or plaintext diagnostics.
// Specification: specifications/features/pii-protection/specification.yml
// Assertion: pii.apple.enhanced-local-detection
import Combine
import Foundation
import Dispatch
#if os(iOS)
import UIKit
#endif

struct ComposerPIIContext: Hashable, Sendable {
    let server: String
    let accountGeneration: UUID
    let routeID: String
}

protocol ProductionPIIRuntimeServing: PrivacyFilterModelRunning {
    func warm(directory: URL) async throws -> Double
    func unload() async
    func timings() async -> LocalPrivacyFilterTimings?
}

/// One production module stays warm across edits; only lifecycle/availability invalidation unloads it.
actor ProductionPIIRuntime: ProductionPIIRuntimeServing {
    static let shared = ProductionPIIRuntime()
    private let engine = LocalPrivacyFilterRuntime()
    private var directory: URL?
    func warm(directory: URL) async throws -> Double {
        let seconds = try await engine.warm(directory: directory)
        try Task.checkCancellation()
        self.directory = directory
        return seconds
    }
    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan] {
        guard let directory else { throw LocalPrivacyFilterError.unavailableRuntime }
        return try await engine.run(.detectPII(text), directory: directory).piiSpans
    }
    func unload() async { directory = nil; await engine.unload() }
    func timings() async -> LocalPrivacyFilterTimings? { await engine.lastTimings }
}

enum EnhancedPIIRuntimeStatus: Equatable, Sendable {
    case regexOnly, warming, ready
    case regexFallback(EnhancedPIIModelFailureReason)
}

/// Main actor owns lifecycle/publication only. Tokenization and native kernels run on the runtime actor.
@MainActor
final class EnhancedPIIDetectionService: ObservableObject {
    static let shared: EnhancedPIIDetectionService = EnhancedPIIDetectionService(controller: .shared,
        validContext: { $0.accountGeneration == OfflineStore.shared.scopeGeneration })
    @Published private(set) var status: EnhancedPIIRuntimeStatus = .regexOnly
    @Published private(set) var revision: UInt64 = 0
    @Published private(set) var coldLoadSeconds: Double?
    @Published private(set) var lastTimings: LocalPrivacyFilterTimings?
    private let controller: EnhancedPIIModelDownloadController
    private let runtime: any ProductionPIIRuntimeServing
    private let validContext: @MainActor (ComposerPIIContext) -> Bool
    private var contexts: Set<ComposerPIIContext> = []
    private var generation = UUID()
    private var warmTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?
    private var refreshID: UUID?
    private var drainTask: Task<Void, Never>?
    private var drainID: UUID?
    private var detectionTask: Task<EnhancedPIIDetectionResult, Never>?
    private var detectionID: UUID?
    private var warmedDirectory: URL?
    private var draining = false
    private var memorySuppressed = false
    private var availabilitySuppressed = false
    private var failedWarmDirectory: URL?
    private var observations: Set<AnyCancellable> = []
    private var pressureSource: DispatchSourceMemoryPressure?

    init(controller: EnhancedPIIModelDownloadController, runtime: any ProductionPIIRuntimeServing = ProductionPIIRuntime.shared,
         validContext: @escaping @MainActor (ComposerPIIContext) -> Bool = { _ in true },
         observePressure: Bool = true) {
        self.controller = controller; self.runtime = runtime; self.validContext = validContext
        controller.$status.sink { [weak self] _ in
            Task { @MainActor [weak self] in self?.modelAvailabilityChanged() }
        }.store(in: &observations)
        if observePressure {
            #if os(iOS)
            NotificationCenter.default.publisher(for: UIApplication.didReceiveMemoryWarningNotification)
                .sink { [weak self] _ in Task { @MainActor [weak self] in await self?.handleMemoryPressure() } }
                .store(in: &observations)
            #endif
            let source = DispatchSource.makeMemoryPressureSource(eventMask: [.warning, .critical], queue: .main)
            source.setEventHandler { [weak self] in Task { @MainActor [weak self] in await self?.handleMemoryPressure() } }
            source.resume(); pressureSource = source
        }
    }

    func activate(_ context: ComposerPIIContext, enabled: Bool) {
        guard enabled, validContext(context) else { deactivate(context); return }
        guard !contexts.contains(context) else { return }
        if contexts.isEmpty { memorySuppressed = false; failedWarmDirectory = nil }
        contexts.insert(context)
        if refreshTask == nil {
            let identifier = UUID(); refreshID = identifier
            refreshTask = Task { @MainActor [weak self] in
                guard let self else { return }
                await controller.refresh()
                if refreshID == identifier { refreshTask = nil; refreshID = nil }
                guard !Task.isCancelled else { return }
                warmIfNeeded()
            }
        }
        warmIfNeeded()
    }
    func deactivate(_ context: ComposerPIIContext) {
        guard contexts.remove(context) != nil else { return }
        if contexts.isEmpty {
            invalidateImmediately(fallback: false)
            refreshTask?.cancel(); refreshTask = nil; refreshID = nil
            scheduleDrain()
        }
    }
    func invalidateModel() async { availabilitySuppressed = true; invalidateImmediately(fallback: false); await scheduleDrain().value }
    func handleMemoryPressure() async {
        memorySuppressed = true
        invalidateImmediately(fallback: true)
        await scheduleDrain().value
    }

    func detect(text: String, options: PIIDetectionOptions, context: ComposerPIIContext,
                waitForWarm: Bool = false) async -> EnhancedPIIDetectionResult {
        if waitForWarm { await awaitInstalledReadiness(context) }
        let fallbackMode: EnhancedPIIDetectionMode
        switch status {
        case .warming: fallbackMode = .regexFallback(reason: .modelLoading)
        case .regexFallback(let reason): fallbackMode = .regexFallback(reason: reason)
        case .regexOnly, .ready: fallbackMode = .regexOnly
        }
        let scan = Task.detached(priority: .userInitiated) { PIIDetector.detect(in: text, options: options) }
        let regex = await withTaskCancellationHandler { await scan.value } onCancel: { scan.cancel() }
        let fallback = EnhancedPIIDetectionResult(matches: regex, mode: fallbackMode)
        guard !Task.isCancelled, contexts.contains(context), validContext(context),
              !memorySuppressed, !availabilitySuppressed else { return fallback }
        guard contexts.contains(context), validContext(context), !memorySuppressed,
              warmedDirectory != nil, controller.status.isReady else { return fallback }
        // A final send may arrive during a preview. Drain the one native owner;
        // composer coordinators retain only their latest pending snapshot.
        while let active = detectionTask {
            let activeID = detectionID
            _ = await active.value
            if detectionID == activeID { detectionTask = nil; detectionID = nil }
            guard !Task.isCancelled, contexts.contains(context), validContext(context) else { return fallback }
        }
        if waitForWarm { await awaitInstalledReadiness(context) }
        guard !Task.isCancelled, contexts.contains(context), validContext(context),
              !memorySuppressed, !availabilitySuppressed, warmedDirectory != nil,
              controller.status.isReady else { return fallback }
        let requestGeneration = generation
        let requestID = UUID()
        let detector = EnhancedPIIDetector(modelDetector: PrivacyFilterNativeDetector(runner: runtime),
            // Preview watchdog is generous until device timings establish a tighter
            // bound. Final exact verification waits for the installed engine; an
            // arbitrary short deadline must not bypass enhanced anonymization.
            modelTimeoutNanoseconds: waitForWarm ? nil : 30_000_000_000)
        let task = Task.detached(priority: waitForWarm ? .userInitiated : .utility) {
            await detector.detect(in: text, options: options)
        }
        detectionTask = task; detectionID = requestID
        let result = await withTaskCancellationHandler { await task.value } onCancel: { task.cancel() }
        if detectionID == requestID { detectionTask = nil; detectionID = nil }
        guard !Task.isCancelled, generation == requestGeneration, contexts.contains(context), validContext(context) else { return fallback }
        let measured = await runtime.timings()
        guard !Task.isCancelled, generation == requestGeneration, contexts.contains(context), validContext(context) else { return fallback }
        lastTimings = measured
        if case .regexFallback(let reason) = result.mode { status = .regexFallback(reason) }
        else { status = .ready }
        return result
    }

    private func modelAvailabilityChanged() {
        guard controller.status.isReady else {
            invalidateImmediately(fallback: false)
            scheduleDrain()
            return
        }
        availabilitySuppressed = false
        warmIfNeeded()
    }
    private func warmIfNeeded() {
        guard !contexts.isEmpty, contexts.contains(where: validContext), !memorySuppressed, !availabilitySuppressed,
              let directory = controller.installedDirectory,
              warmedDirectory != directory, failedWarmDirectory != directory, warmTask == nil, detectionTask == nil, !draining else { return }
        let expected = generation
        status = .warming
        warmTask = Task(priority: .utility) { [weak self] in
            guard let self else { return }
            defer { if generation == expected { warmTask = nil } }
            do {
                let seconds = try await runtime.warm(directory: directory)
                guard !Task.isCancelled, generation == expected, contexts.contains(where: validContext),
                      controller.installedDirectory == directory else { return }
                coldLoadSeconds = seconds; warmedDirectory = directory; status = .ready; revision &+= 1
            } catch {
                guard generation == expected, !Task.isCancelled else { return }
                failedWarmDirectory = directory; status = .regexFallback(.runtimeFailed); revision &+= 1
            }
        }
    }
    private func invalidateImmediately(fallback: Bool) {
        generation = UUID(); draining = true; warmTask?.cancel(); detectionTask?.cancel()
        warmedDirectory = nil; lastTimings = nil; coldLoadSeconds = nil
        status = fallback ? .regexFallback(.memoryPressure) : .regexOnly
        revision &+= 1
    }
    private func awaitInstalledReadiness(_ context: ComposerPIIContext) async {
        while !Task.isCancelled, contexts.contains(context), validContext(context),
              !memorySuppressed, !availabilitySuppressed {
            if let refreshing = refreshTask { await refreshing.value; continue }
            if let draining = drainTask { await draining.value; continue }
            warmIfNeeded()
            if let warming = warmTask { await warming.value; continue }
            // Missing assets, an unsupported engine or a failed load use the
            // explicit basic fallback. A tracked refresh/drain/load cannot slip
            // through this decision as a transient nil warm task.
            return
        }
    }
    @discardableResult
    private func scheduleDrain() -> Task<Void, Never> {
        let identifier = UUID(); drainID = identifier
        let task = Task { [weak self] in
            guard let self else { return }
            await drainAndUnload()
            if drainID == identifier { drainTask = nil; drainID = nil }
        }
        drainTask = task
        return task
    }
    private func drainAndUnload() async {
        let expected = generation
        let warming = warmTask; let detecting = detectionTask
        if let warming { await warming.value }
        if let detecting { await detecting.value }
        guard generation == expected else { return }
        warmTask = nil; detectionTask = nil; detectionID = nil
        await runtime.unload()
        if generation == expected { draining = false; warmIfNeeded() }
    }
}
