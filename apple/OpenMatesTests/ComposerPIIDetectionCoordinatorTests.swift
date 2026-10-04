// Deterministic production PII scheduling and immutable-send coverage.
// Tiny checksum-valid fixture bytes replace weights; all names/text are synthetic.
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.apple.enhanced-local-detection, pii.composer.detect-redact-exclude
import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class ComposerPIIDetectionCoordinatorTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testHeldRoutingRejectsTightenedPrivacyOrHiddenPaneAndRestoresOnlyItsClearedDraft() async throws {
        for hidePane in [false, true] {
            let owner = ComposerPIIContext(server: "https://example.invalid", accountGeneration: UUID(), routeID: "send-route")
            let capturedOptions = PIIDetectionOptions(disabledCategories: ["generic_secrets"])
            let fence = ComposerPIIDispatchFence(context: owner, options: capturedOptions)
            let session = NativeComposerSession(canonicalMarkdown: "Ada Lovelace ada@example.test")
            let document = session.controller.document
            session.clear()
            let clearedRevision = session.revision
            var currentOptions = capturedOptions
            var foreground = true
            var releaseRouting: CheckedContinuation<Void, Never>?
            var dispatched = 0
            let routingStarted = expectation(description: "routing holds before dispatch")
            let sending = Task { @MainActor in
                await withCheckedContinuation { releaseRouting = $0; routingStarted.fulfill() }
                guard fence.permits(currentContext: owner, currentOptions: currentOptions, foreground: foreground) else {
                    if fence.mayRestoreClearedDraft(currentContext: owner, clearedRevision: clearedRevision, currentRevision: session.revision) {
                        try? session.loadDocument(document)
                    }
                    return
                }
                dispatched += 1
            }
            await fulfillment(of: [routingStarted], timeout: 1)
            if hidePane { foreground = false }
            else { currentOptions = .init() } // Tightening privacy enables person detection.
            releaseRouting?.resume()
            await sending.value
            XCTAssertEqual(dispatched, 0, "A pre-routing verification cannot authorize changed privacy or a hidden composer")
            XCTAssertEqual(session.controller.document, document, "Same-owner abort restores the exact semantic draft")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testRoutingAbortNeverOverwritesLaterTypingOrAReplacementOwner() throws {
        let owner = ComposerPIIContext(server: "https://example.invalid", accountGeneration: UUID(), routeID: "send-route")
        let fence = ComposerPIIDispatchFence(context: owner, options: .init())
        let session = NativeComposerSession(canonicalMarkdown: "Original synthetic draft")
        session.clear()
        let clearedRevision = session.revision
        try session.replaceSelection(with: "Later synthetic draft")
        XCTAssertFalse(fence.mayRestoreClearedDraft(currentContext: owner, clearedRevision: clearedRevision, currentRevision: session.revision))
        XCTAssertEqual(session.canonicalMarkdown, "Later synthetic draft")
        let replacement = ComposerPIIContext(server: owner.server, accountGeneration: UUID(), routeID: owner.routeID)
        XCTAssertFalse(fence.mayRestoreClearedDraft(currentContext: replacement, clearedRevision: session.revision, currentRevision: session.revision))
        XCTAssertFalse(fence.permits(currentContext: owner, currentOptions: .init(), foreground: true, cancelled: true))
        XCTAssertTrue(fence.permits(currentContext: owner, currentOptions: .init(), foreground: true))
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testDebounceCoalescesEditsBeforeStartingNativeInference() async throws {
        let fixture = try await makeFixture()
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 40_000_000)
        coordinator.submit(text: "Ada", options: .init(), context: fixture.context, enabled: true, foreground: true)
        coordinator.submit(text: "Ada Love", options: .init(), context: fixture.context, enabled: true, foreground: true)
        coordinator.submit(text: "Ada Lovelace", options: .init(), context: fixture.context, enabled: true, foreground: true)
        let before = await fixture.runtime.snapshot()
        XCTAssertEqual(before.inputs, [], "Keystrokes must not start an immediate native job")
        await eventually { coordinator.publication?.result.mode == .enhanced }
        let after = await fixture.runtime.snapshot()
        XCTAssertEqual(after.inputs, ["Ada Lovelace"])
        XCTAssertEqual(after.warms, 1)
        coordinator.invalidate()
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testHeldKernelOwnsFlightUntilDrainAndOnlyLatestPendingTextRuns() async throws {
        let fixture = try await makeFixture(holding: true)
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        coordinator.submit(text: "Ada Lovelace first", options: .init(), context: fixture.context, enabled: true, foreground: true)
        await eventually { await fixture.runtime.snapshot().inputs.count == 1 }
        for text in ["Ada Lovelace second", "Ada Lovelace third", "Ada Lovelace latest"] {
            coordinator.submit(text: text, options: .init(), context: fixture.context, enabled: true, foreground: true)
            try await Task.sleep(nanoseconds: 4_000_000)
        }
        let held = await fixture.runtime.snapshot()
        XCTAssertEqual(held.inputs, ["Ada Lovelace first"])
        XCTAssertEqual(held.active, 1, "Cancellation cannot release a still-running native kernel")
        await eventually {
            coordinator.publication?.snapshot.text == "Ada Lovelace latest" && coordinator.publication?.result.mode == .regexOnly
        }
        XCTAssertEqual(coordinator.publication?.snapshot.text, "Ada Lovelace latest")
        XCTAssertEqual(coordinator.publication?.result.mode, .regexOnly)
        await fixture.runtime.release()
        await eventually { coordinator.publication?.result.mode == .enhanced }
        let completed = await fixture.runtime.snapshot()
        XCTAssertEqual(completed.inputs, ["Ada Lovelace first", "Ada Lovelace latest"])
        XCTAssertEqual(completed.maximumActive, 1)
        coordinator.invalidate()
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testStaleTextOptionsAccountAndRouteNeverReplaceCurrentPublication() async throws {
        for change in 0..<4 {
            let fixture = try await makeFixture(holding: true)
            let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
            let originalText = "Ada Lovelace original"
            coordinator.submit(text: originalText, options: .init(), context: fixture.context, enabled: true, foreground: true)
            await eventually { await fixture.runtime.snapshot().inputs.count == 1 }
            let nextText = change == 0 ? "Current synthetic text" : originalText
            let nextOptions = change == 1 ? PIIDetectionOptions(disabledCategories: ["generic_secrets"]) : .init()
            let nextContext = ComposerPIIContext(server: fixture.context.server,
                accountGeneration: change == 2 ? UUID() : fixture.context.accountGeneration,
                routeID: change == 3 ? "new-route" : fixture.context.routeID)
            coordinator.submit(text: nextText, options: nextOptions, context: nextContext, enabled: true, foreground: true)
            let expected = ComposerPIIDetectionSnapshot(text: nextText, options: nextOptions, context: nextContext)
            await eventually { coordinator.publication?.snapshot == expected && coordinator.publication?.result.mode == .regexOnly }
            XCTAssertEqual(coordinator.publication?.snapshot, expected)
            XCTAssertEqual(coordinator.publication?.result.mode, .regexOnly)
            await fixture.runtime.release()
            await eventually { coordinator.publication?.snapshot == expected && coordinator.publication?.result.mode == .enhanced }
            XCTAssertEqual(coordinator.publication?.snapshot, expected)
            if change < 2 { XCTAssertTrue(coordinator.publication?.result.matches.isEmpty == true) }
            let drained = await fixture.runtime.snapshot()
            XCTAssertEqual(drained.maximumActive, 1)
            coordinator.invalidate()
            await eventually { await fixture.runtime.snapshot().unloads > 0 }
            fixture.removeFiles()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testMissingModelKeepsRegexAndCustomEntriesWithoutNativeInference() async throws {
        let fixture = try await makeFixture(installed: false)
        defer { fixture.removeFiles() }
        let options = PIIDetectionOptions(personalDataEntries: [
            .init(id: "custom-fixture", textToHide: "Synthetic project", replaceWith: "PROJECT")
        ])
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        coordinator.submit(text: "Synthetic project contact ada@example.test", options: options,
            context: fixture.context, enabled: true, foreground: true)
        await eventually { coordinator.publication?.result.matches.count == 2 && coordinator.publication?.result.mode == .regexOnly }
        XCTAssertEqual(coordinator.publication?.result.mode, .regexOnly)
        XCTAssertEqual(Set(coordinator.publication?.result.matches.map(\.value) ?? []),
                       ["Synthetic project", "ada@example.test"])
        let counts = await fixture.runtime.snapshot()
        XCTAssertEqual(counts.warms, 0)
        XCTAssertEqual(counts.inputs, [])
        XCTAssertEqual(fixture.store.state(for: .privacyFilter), .notDownloaded)
        coordinator.invalidate()
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testDisableAndForegroundLeaveClearRawPublicationBeforeKernelUnloads() async throws {
        for disable in [true, false] {
            let fixture = try await makeFixture(holding: true)
            let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
            coordinator.submit(text: "Ada Lovelace held", options: .init(), context: fixture.context, enabled: true, foreground: true)
            await eventually { await fixture.runtime.snapshot().active == 1 }
            coordinator.submit(text: "Ada Lovelace held", options: .init(), context: fixture.context,
                               enabled: !disable, foreground: disable)
            XCTAssertNil(coordinator.publication, "Raw detection publication must clear immediately")
            let before = await fixture.runtime.snapshot()
            XCTAssertEqual(before.active, 1)
            XCTAssertEqual(before.unloadsWhileActive, 0)
            await fixture.runtime.release()
            await eventually {
                let state = await fixture.runtime.snapshot()
                return state.active == 0 && state.unloads > before.unloads
            }
            XCTAssertNil(coordinator.publication, "A drained stale success must never republish")
            let after = await fixture.runtime.snapshot()
            XCTAssertEqual(after.active, 0)
            XCTAssertEqual(after.unloadsWhileActive, 0)
            fixture.removeFiles()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testMemoryPressureFallsBackAndFurtherKeystrokesDoNotWarmAgain() async throws {
        let fixture = try await makeFixture(holding: true)
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        coordinator.submit(text: "Ada Lovelace", options: .init(), context: fixture.context, enabled: true, foreground: true)
        await eventually { await fixture.runtime.snapshot().active == 1 }
        let pressure = Task { await fixture.service.handleMemoryPressure() }
        await eventually { fixture.service.status == .regexFallback(.memoryPressure) }
        let duringPressure = await fixture.runtime.snapshot()
        XCTAssertEqual(duringPressure.active, 1)
        XCTAssertEqual(duringPressure.unloadsWhileActive, 0)
        await fixture.runtime.release()
        await pressure.value
        XCTAssertEqual(fixture.service.status, .regexFallback(.memoryPressure))
        for number in 0..<3 {
            coordinator.submit(text: "ada@example.test \(number)", options: .init(), context: fixture.context, enabled: true, foreground: true)
        }
        await eventually { coordinator.publication?.result.mode == .regexFallback(reason: .memoryPressure) }
        XCTAssertEqual(coordinator.publication?.result.mode, .regexFallback(reason: .memoryPressure))
        XCTAssertTrue(coordinator.publication?.result.matches.contains { $0.value == "ada@example.test" } == true)
        let counts = await fixture.runtime.snapshot()
        XCTAssertEqual(counts.warms, 1)
        XCTAssertEqual(counts.inputs, ["Ada Lovelace"])
        XCTAssertGreaterThan(counts.unloads, 0)
        coordinator.invalidate()
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testFinalVerificationRedactsImmutableDocumentAndPreservesExcludedOriginalsAndAtoms() async throws {
        let fixture = try await makeFixture(holding: true)
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        let mention = ComposerNodeV1.mention(id: "opaque-mention", mentionKind: "mate", targetId: "ada@example.test",
            canonicalSyntax: "@ada@example.test", displayLabel: "Ada Lovelace")
        let embed = ComposerNodeV1.embed(id: "opaque-embed", embedType: "web", canonicalSource: "ada@example.test",
            referenceOnly: true, display: .init(title: "Ada Lovelace", mediaKind: "web"))
        let document = ComposerDocumentV1(version: 1, nodes: [
            .text(id: "text", source: "Ada Lovelace ada@example.test keep@example.test skip@example.test"), mention, embed
        ])
        let excludedID = try XCTUnwrap(PIIDetector.detect(in: ComposerPIIDecorations.visibleText(document: document))
            .first { $0.value == "skip@example.test" }?.id)
        let verification = Task {
            await coordinator.verifiedRedaction(document: document, excludedIds: [excludedID], excludedOriginals: ["keep@example.test"],
                options: .init(), context: fixture.context)
        }
        await eventually { await fixture.runtime.snapshot().active == 1 }
        let newlyTypedDocument = ComposerDocumentV1(version: 1, nodes: [.text(id: "new", source: "Text typed while verifying")])
        coordinator.submit(text: ComposerPIIDecorations.visibleText(document: newlyTypedDocument), options: .init(),
                           context: fixture.context, enabled: true, foreground: true)
        await fixture.runtime.release()
        let result = await verification.value
        XCTAssertEqual(document.nodes[0].source, "Ada Lovelace ada@example.test keep@example.test skip@example.test")
        XCTAssertEqual(newlyTypedDocument.nodes[0].source, "Text typed while verifying")
        XCTAssertEqual(result.document.nodes[1], mention)
        XCTAssertEqual(result.document.nodes[2], embed)
        XCTAssertTrue(result.document.nodes[0].source?.contains("keep@example.test") == true)
        XCTAssertTrue(result.document.nodes[0].source?.contains("skip@example.test") == true)
        XCTAssertFalse(result.document.nodes[0].source?.contains("Ada Lovelace") == true)
        XCTAssertFalse(result.document.nodes[0].source?.contains("ada@example.test") == true)
        XCTAssertEqual(Set(result.mappings.map(\.original)), ["Ada Lovelace", "ada@example.test"])
        await eventually { coordinator.publication?.snapshot.text == "Text typed while verifying" && coordinator.publication?.result.mode == .enhanced }
        coordinator.invalidate()
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testFinalVerificationWaitsForColdWarmupWhileTypingContinuesAndLoadsOnlyOnce() async throws {
        let fixture = try await makeFixture(holdingWarm: true)
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        await eventually { await fixture.runtime.snapshot().warms == 1 }
        XCTAssertEqual(fixture.service.status, .warming)
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "send", source: "Ada Lovelace ada@example.test")])
        var completed: ComposerDocumentPIIRedactionResult?
        let verification = Task {
            completed = await coordinator.verifiedRedaction(document: document, excludedIds: [], options: .init(), context: fixture.context)
        }
        // A final send awaits its installed model, but this suspension must not
        // retain the MainActor or stop the next immutable preview snapshot.
        for number in 0..<3 {
            coordinator.submit(text: "new@example.test \(number)", options: .init(), context: fixture.context, enabled: true, foreground: true)
        }
        await eventually { coordinator.publication?.snapshot.text == "new@example.test 2" }
        try await Task.sleep(nanoseconds: 20_000_000)
        XCTAssertNil(completed, "Final enhanced verification must stay pending while the installed model warms")
        XCTAssertEqual(document.nodes[0].source, "Ada Lovelace ada@example.test")
        let held = await fixture.runtime.snapshot()
        XCTAssertEqual(held.warms, 1)
        XCTAssertEqual(held.inputs, [])
        await fixture.runtime.releaseWarm()
        await verification.value
        XCTAssertEqual(Set(completed?.mappings.map(\.original) ?? []), ["Ada Lovelace", "ada@example.test"])
        XCTAssertEqual(document.nodes[0].source, "Ada Lovelace ada@example.test")
        await eventually { coordinator.publication?.snapshot.text == "new@example.test 2" && coordinator.publication?.result.mode == .enhanced }
        coordinator.invalidate()
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testFinalVerificationAwaitsReactivationRefreshAndHeldPreviousKernelDrainBeforeRewarming() async throws {
        let fixture = try await makeFixture(holding: true)
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        coordinator.submit(text: "Ada Lovelace previous route", options: .init(), context: fixture.context, enabled: true, foreground: true)
        await eventually { await fixture.runtime.snapshot().active == 1 }
        coordinator.invalidate()
        XCTAssertNil(coordinator.publication)
        fixture.service.activate(fixture.context, enabled: true)
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "send", source: "Ada Lovelace ada@example.test")])
        var completed: ComposerDocumentPIIRedactionResult?
        let verification = Task {
            completed = await coordinator.verifiedRedaction(document: document, excludedIds: [], options: .init(), context: fixture.context)
        }
        try await Task.sleep(nanoseconds: 20_000_000)
        XCTAssertNil(completed, "An installed final cannot fall back during the transient refresh/drain interval")
        let held = await fixture.runtime.snapshot()
        XCTAssertEqual(held.active, 1)
        XCTAssertEqual(held.warms, 1, "A previous native kernel must finish before a new module can load")
        XCTAssertEqual(held.unloadsWhileActive, 0)
        await fixture.runtime.release()
        await verification.value
        XCTAssertEqual(Set(completed?.mappings.map(\.original) ?? []), ["Ada Lovelace", "ada@example.test"])
        let resumed = await fixture.runtime.snapshot()
        XCTAssertEqual(resumed.warms, 2)
        XCTAssertGreaterThan(resumed.unloads, 0)
        XCTAssertEqual(resumed.maximumActive, 1)
        XCTAssertEqual(resumed.unloadsWhileActive, 0)
        fixture.service.deactivate(fixture.context)
        await eventually { await fixture.runtime.snapshot().unloads > resumed.unloads }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testWarmModelLoadsOnceAndPublishesOnlyNumericColdAndWarmTimings() async throws {
        let fixture = try await makeFixture()
        defer { fixture.removeFiles() }
        for text in ["Ada Lovelace", "Ada Lovelace again"] {
            let result = await fixture.service.detect(text: text, options: .init(), context: fixture.context)
            XCTAssertEqual(result.mode, .enhanced)
        }
        let counts = await fixture.runtime.snapshot()
        XCTAssertEqual(counts.warms, 1)
        XCTAssertEqual(counts.inputs.count, 2)
        XCTAssertEqual(fixture.service.coldLoadSeconds, 0.125)
        XCTAssertEqual(fixture.service.lastTimings?.usedWarmModel, true)
        XCTAssertEqual(fixture.service.lastTimings?.inferenceSeconds, 0.02)
        fixture.service.deactivate(fixture.context)
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
    }

    private func makeFixture(installed: Bool = true, holding: Bool = false, holdingWarm: Bool = false) async throws -> CoordinatorFixture {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("composer-pii-test-" + UUID().uuidString)
        let bytes = Data("tiny disposable PII asset".utf8)
        let revision = String(repeating: "a", count: 40)
        let manifest = LocalModelManifest(id: .privacyFilter, revision: revision, estimatedSizeBytes: Int64(bytes.count), files: [
            LocalModelFile(path: "model.pte", url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/model.pte")!,
                sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), sizeBytes: Int64(bytes.count))
        ])
        let store = LocalModelStore(catalog: try JSONEncoder().encode(LocalModelCatalog(models: [manifest])),
            root: root, downloader: CoordinatorAssetDownloader(bytes: bytes), verifyExisting: false)
        if installed { await store.download(.privacyFilter) }
        let runtime = ControlledProductionPIIRuntime(holding: holding, holdingWarm: holdingWarm)
        let service = EnhancedPIIDetectionService(controller: .init(store: store), runtime: runtime,
            validContext: { _ in true }, observePressure: false)
        let context = ComposerPIIContext(server: "https://example.invalid", accountGeneration: UUID(), routeID: "synthetic-route")
        service.activate(context, enabled: true)
        if installed && !holdingWarm { await eventually { service.status == .ready } }
        return .init(root: root, store: store, runtime: runtime, service: service, context: context)
    }

    private func eventually(file: StaticString = #filePath, line: UInt = #line,
                            _ condition: @MainActor () async -> Bool) async {
        for _ in 0..<500 {
            if await condition() { return }
            try? await Task.sleep(nanoseconds: 2_000_000)
        }
        XCTFail("Expected bounded asynchronous transition did not occur", file: file, line: line)
    }
}

private struct CoordinatorFixture {
    let root: URL
    let store: LocalModelStore
    let runtime: ControlledProductionPIIRuntime
    let service: EnhancedPIIDetectionService
    let context: ComposerPIIContext
    func removeFiles() { try? FileManager.default.removeItem(at: root) }
}

private struct CoordinatorAssetDownloader: LocalModelFileDownloading {
    let bytes: Data
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try bytes.write(to: destination)
        progress(Int64(bytes.count))
    }
}

private actor ControlledProductionPIIRuntime: ProductionPIIRuntimeServing {
    struct Snapshot: Sendable {
        let warms: Int
        let unloads: Int
        let active: Int
        let maximumActive: Int
        let unloadsWhileActive: Int
        let inputs: [String]
    }
    private var holding: Bool
    private var holdingWarm: Bool
    private var warmWaiters: [CheckedContinuation<Void, Never>] = []
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var warms = 0
    private var unloads = 0
    private var active = 0
    private var maximumActive = 0
    private var unloadsWhileActive = 0
    private var inputs: [String] = []
    init(holding: Bool, holdingWarm: Bool) { self.holding = holding; self.holdingWarm = holdingWarm }
    func warm(directory: URL) async throws -> Double {
        warms += 1
        if holdingWarm { await withCheckedContinuation { warmWaiters.append($0) } }
        return 0.125
    }
    func releaseWarm() { holdingWarm = false; let pending = warmWaiters; warmWaiters = []; pending.forEach { $0.resume() } }
    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan] {
        inputs.append(text); active += 1; maximumActive = max(maximumActive, active)
        defer { active -= 1 }
        // Native kernels can ignore task cancellation until their work finishes.
        if holding { await withCheckedContinuation { waiters.append($0) } }
        let range = (text as NSString).range(of: "Ada Lovelace")
        return range.location == NSNotFound ? [] : [.init(label: .privatePerson, range: range, score: 0.99)]
    }
    func release() { holding = false; let pending = waiters; waiters = []; pending.forEach { $0.resume() } }
    func unload() async { if active > 0 { unloadsWhileActive += 1 }; unloads += 1 }
    func timings() async -> LocalPrivacyFilterTimings? {
        .init(loadSeconds: 0, tokenizeSeconds: 0.01, inferenceSeconds: 0.02, decodeSeconds: 0.003,
              totalSeconds: 0.033, usedWarmModel: true)
    }
    func snapshot() -> Snapshot {
        .init(warms: warms, unloads: unloads, active: active, maximumActive: maximumActive,
              unloadsWhileActive: unloadsWhileActive, inputs: inputs)
    }
}
