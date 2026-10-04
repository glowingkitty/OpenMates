// DEBUG orchestration fixture; real coordinator/editor, stub spans and tiny assets.
// This proves scheduling and UI wiring, never model quality or real inference.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS: frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.apple.enhanced-local-detection, pii.composer.detect-redact-exclude
// ────────────────────────────────────────────────────────────────────
#if DEBUG
import Combine
import CryptoKit
import SwiftUI

struct DevComposerPIIPreview: View {
    @StateObject private var fixture = DevComposerPIIFixture()
    @State private var focused = false

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text("PII orchestration fixture — stub inference").font(.omSmall)
                    .accessibilityIdentifier("composer-pii-fixture-label")
                HStack {
                    Button(fixture.enabled ? "Disable detection" : "Enable detection") { fixture.toggleEnabled() }
                        .buttonStyle(OMSettingsButtonStyle(secondary: true))
                        .accessibilityIdentifier("composer-pii-fixture-toggle")
                    Button("Release held kernel") { Task { await fixture.runtime.release() } }
                        .buttonStyle(OMSettingsButtonStyle(secondary: true))
                        .accessibilityIdentifier("composer-pii-fixture-release")
                }
                MessageComposerView(session: fixture.session, isFocused: $focused, compact: false,
                    placeholder: AppStrings.typeMessage, maxWidth: nil, isComposerEditable: true,
                    piiDecorations: fixture.decorations, onExcludePII: fixture.exclude,
                    onSubmit: fixture.verify) { EmptyView() } overlayContent: { EmptyView() } actionButtons: {
                    Button(fixture.busy ? AppStrings.enhancedPIIModelVerifying : "Verify immutable snapshot") { fixture.verify() }
                        .buttonStyle(OMSettingsButtonStyle()).disabled(fixture.busy || !fixture.ready)
                        .accessibilityIdentifier("composer-pii-fixture-verify")
                }
                if fixture.busy {
                    Button(AppStrings.cancel) { fixture.cancelVerification() }
                        .buttonStyle(OMSettingsButtonStyle(secondary: true))
                        .accessibilityIdentifier("composer-pii-fixture-cancel")
                }
                Text(fixture.receipt).font(.omMicro).accessibilityIdentifier("composer-pii-fixture-receipt")
                Text(fixture.action).font(.omMicro).accessibilityIdentifier("composer-pii-fixture-action")
                Text(fixture.redacted).font(.omSmall).accessibilityIdentifier("composer-pii-fixture-redacted")
            }.padding(.spacing6)
        }
        .task { await fixture.prepare() }
        .onReceive(fixture.session.$revision.dropFirst()) { _ in fixture.submit() }
        .onDisappear { fixture.leave() }
    }
}

@MainActor
private final class DevComposerPIIFixture: ObservableObject {
    let session = NativeComposerSession(canonicalMarkdown: "Ada Lovelace ada@example.test")
    let runtime = DevComposerPIIStubRuntime()
    let store: LocalModelStore
    let service: EnhancedPIIDetectionService
    let coordinator: ComposerPIIDetectionCoordinator
    let context = ComposerPIIContext(server: "https://example.invalid", accountGeneration: UUID(), routeID: "pii-preview")
    @Published var enabled = true
    @Published var ready = false
    @Published var busy = false
    @Published var action = "preparing"
    @Published var redacted = "not-verified"
    @Published var decorations: [NativeComposerPIIDecoration] = []
    @Published var receipt = "exact=false;matches=0;excluded=0"
    private var excluded: Set<String> = []
    private var verification: Task<Void, Never>?
    private var observation: AnyCancellable?
    private let root: URL

    init() {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("composer-pii-preview-" + UUID().uuidString)
        let bytes = Data("tiny public orchestration fixture".utf8)
        let revision = String(repeating: "a", count: 40)
        let manifest = LocalModelManifest(id: .privacyFilter, revision: revision, estimatedSizeBytes: Int64(bytes.count), files: [
            LocalModelFile(path: "fixture.pte", url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/fixture.pte")!,
                sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), sizeBytes: Int64(bytes.count))
        ])
        store = LocalModelStore(catalog: try? JSONEncoder().encode(LocalModelCatalog(models: [manifest])),
            root: root, downloader: DevComposerPIIAssetDownloader(bytes: bytes), verifyExisting: false)
        service = EnhancedPIIDetectionService(controller: .init(store: store), runtime: runtime,
            validContext: { _ in true }, observePressure: false)
        coordinator = ComposerPIIDetectionCoordinator(service: service, debounceNanoseconds: 50_000_000)
        observation = coordinator.$publication.sink { [weak self] publication in self?.apply(publication) }
    }

    func prepare() async {
        await store.download(.privacyFilter)
        guard store.state(for: .privacyFilter) == .ready else { action = "fixture-failed"; return }
        ready = true; action = "ready"; submit()
    }
    func submit() {
        coordinator.submit(text: ComposerPIIDecorations.visibleText(document: session.controller.document),
            options: .init(excludedIds: excluded), context: context, enabled: enabled, foreground: true)
    }
    private func apply(_ publication: ComposerPIIDetectionPublication?) {
        let text = ComposerPIIDecorations.visibleText(document: session.controller.document)
        guard enabled, let publication, publication.snapshot.text == text,
              publication.snapshot.options.excludedIds == excluded else {
            decorations = []; receipt = "exact=false;matches=0;excluded=\(excluded.count)"; return
        }
        decorations = ComposerPIIDecorations.nativeDecorations(matches: publication.result.matches, visibleText: text)
        receipt = "exact=true;matches=\(decorations.count);excluded=\(excluded.count);\(publication.result.sanitizedStatus)"
    }
    func exclude(_ id: String) { excluded.insert(id); submit() }
    func toggleEnabled() { enabled.toggle(); submit() }
    func verify() {
        guard ready, !busy else { return }
        let document = session.controller.document
        let exclusions = excluded
        busy = true; action = "verifying"
        verification = Task { [weak self] in
            guard let self else { return }
            await runtime.holdNext()
            // This absent ID forces a fresh final scan rather than reusing a
            // completed preview; actual user exclusions remain captured above.
            let result = await coordinator.verifiedRedaction(document: document, excludedIds: exclusions,
                options: .init(excludedIds: ["fixture-force-fresh-final"]), context: context)
            if Task.isCancelled { action = "cancelled" }
            else {
                redacted = (try? ComposerMarkdownAdapter.serialize(result.document)) ?? "fixture-failed"
                action = "completed;mappings=\(result.mappings.count)"
            }
            // The live editor is never replaced by its earlier send snapshot.
            busy = false; verification = nil
        }
    }
    func cancelVerification() { verification?.cancel(); action = "cancelling" }
    func leave() {
        verification?.cancel(); coordinator.invalidate()
        Task { await runtime.release(); await service.invalidateModel(); try? FileManager.default.removeItem(at: root) }
    }
}

private struct DevComposerPIIAssetDownloader: LocalModelFileDownloading {
    let bytes: Data
    func download(_ file: LocalModelFile, to destination: URL, progress: @escaping @Sendable (Int64) -> Void) async throws {
        try bytes.write(to: destination); progress(Int64(bytes.count))
    }
}
private actor DevComposerPIIStubRuntime: ProductionPIIRuntimeServing {
    private var hold = false
    private var continuations: [CheckedContinuation<Void, Never>] = []
    func holdNext() { hold = true }
    func release() { hold = false; let pending = continuations; continuations = []; pending.forEach { $0.resume() } }
    func warm(directory: URL) async throws -> Double { 0.001 }
    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan] {
        if hold { await withCheckedContinuation { continuations.append($0) } }
        let range = (text as NSString).range(of: "Ada Lovelace")
        return range.location == NSNotFound ? [] : [.init(label: .privatePerson, range: range, score: 0.99)]
    }
    func unload() async {}
    func timings() async -> LocalPrivacyFilterTimings? { nil }
}
#endif
