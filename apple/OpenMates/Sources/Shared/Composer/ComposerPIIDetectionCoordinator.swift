// Latest-only foreground composer detection; snapshots and originals are memory-only.
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.apple.enhanced-local-detection, pii.composer.detect-redact-exclude
import Combine
import Foundation

struct ComposerPIIDetectionSnapshot: Equatable, Sendable {
    let text: String
    let options: PIIDetectionOptions
    let context: ComposerPIIContext
}
struct ComposerPIIDetectionPublication: Equatable, Sendable {
    let snapshot: ComposerPIIDetectionSnapshot
    let result: EnhancedPIIDetectionResult
    let runtimeRevision: UInt64
}

/// Revalidate immediately after the final asynchronous routing step and before
/// dispatch. A verified snapshot cannot authorize changed settings or a hidden
/// composer merely because its account still matches.
struct ComposerPIIDispatchFence: Sendable {
    let context: ComposerPIIContext
    let options: PIIDetectionOptions
    func permits(currentContext: ComposerPIIContext, currentOptions: PIIDetectionOptions,
                 foreground: Bool, cancelled: Bool = false) -> Bool {
        !cancelled && foreground && context == currentContext && options == currentOptions
    }
    func mayRestoreClearedDraft(currentContext: ComposerPIIContext, clearedRevision: Int?, currentRevision: Int) -> Bool {
        context == currentContext && clearedRevision == currentRevision
    }
}

@MainActor
final class ComposerPIIDetectionCoordinator: ObservableObject {
    @Published private(set) var publication: ComposerPIIDetectionPublication?
    private let service: EnhancedPIIDetectionService
    private let debounceNanoseconds: UInt64
    private var current: ComposerPIIDetectionSnapshot?
    private var pending: ComposerPIIDetectionSnapshot?
    private var epoch = UUID()
    private var debounce: Task<Void, Never>?
    private var inFlight: Task<Void, Never>?
    private var flightID: UUID?
    private var regexFlight: Task<Void, Never>?
    private var regexFlightID: UUID?
    private var regexPending: ComposerPIIDetectionSnapshot?
    private var enabled = false
    private var foreground = false
    private var verifying = 0
    private var observation: AnyCancellable?

    init(service: EnhancedPIIDetectionService = .shared, debounceNanoseconds: UInt64 = 500_000_000) {
        self.service = service; self.debounceNanoseconds = debounceNanoseconds
        observation = service.$revision.dropFirst().sink { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, let current else { return }
                submit(text: current.text, options: current.options, context: current.context,
                       enabled: enabled, foreground: foreground)
            }
        }
    }

    func submit(text: String, options: PIIDetectionOptions, context: ComposerPIIContext,
                enabled: Bool, foreground: Bool) {
        guard foreground, enabled else { invalidate(); return }
        if let old = current?.context, old != context { invalidate() }
        self.enabled = enabled; self.foreground = foreground
        let snapshot = ComposerPIIDetectionSnapshot(text: text, options: options, context: context)
        current = snapshot
        epoch = UUID()
        debounce?.cancel(); debounce = nil; pending = nil
        inFlight?.cancel() // Retain ownership until the native operation actually drains.
        publication = nil // Never display highlights belonging to a previous exact text.
        regexFlight?.cancel(); regexPending = snapshot; startRegexPending()
        guard foreground, enabled else { service.deactivate(context); return }
        service.activate(context, enabled: true)
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let expected = epoch
        debounce = Task { [weak self] in
            guard let self else { return }
            do { try await Task.sleep(nanoseconds: debounceNanoseconds) } catch { return }
            guard !Task.isCancelled, epoch == expected, current == snapshot else { return }
            pending = snapshot
            startPending()
        }
    }

    func invalidate() {
        let old = current?.context
        epoch = UUID(); current = nil; pending = nil; publication = nil
        debounce?.cancel(); debounce = nil; inFlight?.cancel()
        regexPending = nil; regexFlight?.cancel()
        enabled = false; foreground = false
        if let old { service.deactivate(old) }
    }

    /// The send path verifies exactly its immutable document/settings/exclusion snapshot.
    /// Preview results are reusable only while their exact identity and runtime generation remain current.
    func verifiedRedaction(document: ComposerDocumentV1, excludedIds: Set<String>, excludedOriginals: Set<String> = [], options: PIIDetectionOptions,
                           context: ComposerPIIContext) async -> ComposerDocumentPIIRedactionResult {
        let effective = PIIDetectionOptions(excludedIds: options.excludedIds.union(excludedIds),
            disabledCategories: options.disabledCategories, personalDataEntries: options.personalDataEntries)
        let text = ComposerPIIDecorations.visibleText(document: document)
        let snapshot = ComposerPIIDetectionSnapshot(text: text, options: effective, context: context)
        let cached = publication
        verifying += 1
        defer { verifying -= 1; startPending() }
        epoch = UUID(); debounce?.cancel(); debounce = nil; pending = nil; inFlight?.cancel()
        if let inFlight { await inFlight.value }
        let result: EnhancedPIIDetectionResult
        if let cached, cached.snapshot == snapshot, cached.runtimeRevision == service.revision,
           service.status == .ready, cached.result.mode == .enhanced {
            result = cached.result
        } else {
            result = await service.detect(text: text, options: effective, context: context, waitForWarm: true)
        }
        return ComposerPIIDecorations.redactedDocument(document: document, excludedIds: excludedIds,
            options: options, detectedMatches: result.matches.filter { !excludedOriginals.contains($0.value) })
    }

    private func startRegexPending() {
        guard regexFlight == nil, let snapshot = regexPending, current == snapshot, enabled, foreground else { return }
        regexPending = nil
        let id = UUID(); regexFlightID = id
        regexFlight = Task { [weak self] in
            guard let self else { return }
            let scan = Task.detached(priority: .userInitiated) { () -> [PIIMatch]? in
                guard !Task.isCancelled else { return nil }
                let matches = PIIDetector.detect(in: snapshot.text, options: snapshot.options)
                return Task.isCancelled ? nil : matches
            }
            let matches = await withTaskCancellationHandler { await scan.value } onCancel: { scan.cancel() }
            guard regexFlightID == id else { return }
            regexFlight = nil; regexFlightID = nil
            if !Task.isCancelled, let matches, current == snapshot, enabled, foreground,
               !(publication?.snapshot == snapshot && publication?.result.mode == .enhanced) {
                publication = .init(snapshot: snapshot, result: .init(matches: matches, mode: .regexOnly),
                    runtimeRevision: service.revision)
            }
            startRegexPending()
        }
    }

    private func startPending() {
        guard verifying == 0, inFlight == nil, let snapshot = pending,
              current == snapshot, enabled, foreground else { return }
        pending = nil
        let id = UUID(); flightID = id
        let expected = epoch
        inFlight = Task { [weak self] in
            guard let self else { return }
            let result = await service.detect(text: snapshot.text, options: snapshot.options, context: snapshot.context)
            guard flightID == id else { return }
            inFlight = nil; flightID = nil
            if !Task.isCancelled, epoch == expected, current == snapshot, foreground, enabled {
                publication = .init(snapshot: snapshot, result: result, runtimeRevision: service.revision)
            }
            startPending()
        }
    }
}
