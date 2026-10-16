// Deterministic production PII scheduling and immutable-send coverage.
// Tiny checksum-valid fixture bytes replace weights; all names/text are synthetic.
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.apple.enhanced-local-detection, pii.composer.detect-redact-exclude
import Combine
import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class ComposerPIIDetectionCoordinatorTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testDefaultSendOnlyPublishesRegexWhileTypingAndEnhancesExactFinalDocument() async throws {
        let fixture = try await makeFixture()
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        for text in ["Ada", "Ada Lovelace ", "Ada Lovelace ada@example.test"] {
            coordinator.submit(text: text, options: .init(), context: fixture.context, enabled: true, foreground: true)
        }
        await eventually { coordinator.publication?.snapshot.text == "Ada Lovelace ada@example.test" }
        XCTAssertEqual(coordinator.publication?.result.mode, .regexOnly)
        XCTAssertTrue(coordinator.publication?.result.matches.contains { $0.value == "ada@example.test" } == true)
        try await Task.sleep(nanoseconds: 20_000_000) // Beyond the injected debounce; still no enhanced preview.
        let typing = await fixture.runtime.snapshot()
        XCTAssertEqual(typing.inputs, [])
        XCTAssertEqual(typing.warms, 1, "Cadence does not alter the existing active-composer model lifetime")
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "send", source: "Ada Lovelace final@example.test")])
        let result = await coordinator.verifiedRedaction(document: document, excludedIds: [], options: .init(), context: fixture.context)
        XCTAssertEqual(Set(result.mappings.map(\.original)), ["Ada Lovelace", "final@example.test"])
        let sent = await fixture.runtime.snapshot()
        XCTAssertEqual(sent.inputs, ["Ada Lovelace final@example.test"], "Send must detect its immutable document, not the visible preview")
        XCTAssertEqual(coordinator.publication?.snapshot.text, "Ada Lovelace ada@example.test")
        coordinator.invalidate()
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
    }

    // contract-test: direct surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testSendOnlySettingsAndReplacementContextKeepLatestRegexAndExactFinalOptions() async throws {
        let fixture = try await makeFixture()
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        let text = "Ada Lovelace ada@example.test Synthetic project"
        coordinator.submit(text: text, options: .init(), context: fixture.context, enabled: true, foreground: true)
        await eventually { coordinator.publication?.snapshot.context == fixture.context }
        let replacement = ComposerPIIContext(server: fixture.context.server, accountGeneration: UUID(), routeID: "replacement-route")
        let options = PIIDetectionOptions(personalDataEntries: [.init(id: "synthetic", textToHide: "Synthetic project", replaceWith: "PROJECT")])
        coordinator.submit(text: text, options: options, context: replacement, enabled: true, foreground: true)
        await eventually { coordinator.publication?.snapshot.context == replacement && coordinator.publication?.snapshot.options == options }
        XCTAssertEqual(coordinator.publication?.result.mode, .regexOnly)
        XCTAssertTrue(coordinator.publication?.result.matches.contains { $0.value == "Synthetic project" } == true)
        let before = await fixture.runtime.snapshot()
        XCTAssertEqual(before.inputs, [])
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "send", source: text)])
        let result = await coordinator.verifiedRedaction(document: document, excludedIds: [], excludedOriginals: ["ada@example.test"],
                                                          options: options, context: replacement)
        XCTAssertEqual(Set(result.mappings.map(\.original)), ["Ada Lovelace", "Synthetic project"])
        XCTAssertTrue(result.document.nodes[0].source?.contains("ada@example.test") == true)
        let after = await fixture.runtime.snapshot()
        XCTAssertEqual(after.inputs, [text])
        coordinator.submit(text: text, options: options, context: replacement, enabled: true, foreground: false)
        XCTAssertNil(coordinator.publication)
        await eventually { await fixture.runtime.snapshot().unloads > after.unloads }
    }

    // contract-test: direct surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testSendOnlyUnicodeAndIMEStyleDraftReplacementsAlwaysPublishExactRegexSnapshot() async throws {
        let fixture = try await makeFixture()
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000)
        // The coordinator receives visible snapshots, not marked-text state. Intermediate
        // composition replacements and mixed graphemes must never wait for a separator.
        for text in ["に", "日本語 ada@example.test", "日本語、ada@example.test", "e\u{301} 👩🏽‍💻 ada@example.test", "ada@example.test\n"] {
            coordinator.submit(text: text, options: .init(), context: fixture.context, enabled: true, foreground: true)
            await eventually { coordinator.publication?.snapshot.text == text }
            XCTAssertEqual(coordinator.publication?.result.mode, .regexOnly)
            XCTAssertEqual(coordinator.publication?.result.matches, PIIDetector.detect(in: text))
        }
        try await Task.sleep(nanoseconds: 20_000_000)
        let counts = await fixture.runtime.snapshot()
        XCTAssertEqual(counts.inputs, [])
        coordinator.invalidate()
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
    }

    // contract-test: direct surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testSendOnlyCapabilityOffKeepsRegexAtSendAndOnRestoresExactEnhancedVerification() async throws {
        let suite = "pii-send-capability-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let fixture = try await makeFixture(capabilityPreferences: defaults)
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service)
        let text = "Ada Lovelace ada@example.test"
        coordinator.submit(text: text, options: .init(), context: fixture.context, enabled: true, foreground: true)
        await eventually { coordinator.publication?.snapshot.text == text }
        await fixture.store.setCapabilityEnabled(.privacyFilter, enabled: false)
        let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "send", source: text)])
        let disabled = await coordinator.verifiedRedaction(document: document, excludedIds: [], options: .init(), context: fixture.context)
        XCTAssertEqual(Set(disabled.mappings.map(\.original)), ["ada@example.test"])
        let whileOff = await fixture.runtime.snapshot()
        XCTAssertEqual(whileOff.inputs, [])
        await fixture.store.setCapabilityEnabled(.privacyFilter, enabled: true)
        await eventually { fixture.service.status == .ready }
        let enabled = await coordinator.verifiedRedaction(document: document, excludedIds: [], options: .init(), context: fixture.context)
        XCTAssertEqual(Set(enabled.mappings.map(\.original)), ["Ada Lovelace", "ada@example.test"])
        let whileOn = await fixture.runtime.snapshot()
        XCTAssertEqual(whileOn.inputs, [text])
        coordinator.invalidate()
        await eventually { await fixture.runtime.snapshot().unloads > whileOff.unloads }
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testSeparatorPreviewPolicyUsesUnicodeBoundaryAndKeepsRegexInsideWord() async throws {
        XCTAssertTrue(ComposerEnhancedPreviewCadence.separators.permits("日本語、"))
        XCTAssertTrue(ComposerEnhancedPreviewCadence.separators.permits("word\n"))
        XCTAssertTrue(ComposerEnhancedPreviewCadence.separators.permits("word\u{2003}"))
        XCTAssertFalse(ComposerEnhancedPreviewCadence.separators.permits("e\u{301}"))
        XCTAssertFalse(ComposerEnhancedPreviewCadence.separators.permits("👩🏽‍💻"))
        let fixture = try await makeFixture()
        defer { fixture.removeFiles() }
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .separators)
        coordinator.submit(text: "ada@example.test compos", options: .init(), context: fixture.context, enabled: true, foreground: true)
        await eventually { coordinator.publication?.result.mode == .regexOnly }
        try await Task.sleep(nanoseconds: 20_000_000)
        let insideWord = await fixture.runtime.snapshot()
        XCTAssertEqual(insideWord.inputs, [])
        coordinator.submit(text: "Ada Lovelace、", options: .init(), context: fixture.context, enabled: true, foreground: true)
        await eventually { coordinator.publication?.result.mode == .enhanced }
        let boundary = await fixture.runtime.snapshot()
        XCTAssertEqual(boundary.inputs, ["Ada Lovelace、"])
        coordinator.invalidate()
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
    }

    // contract-test: direct surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testExplicitPIIRemovalWaitsForHeldNativeInferenceBeforeDeletingAssets() async throws {
        let suite = "pii-removal-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let fixture = try await makeFixture(holding: true, capabilityPreferences: defaults)
        defer { fixture.removeFiles() }
        let directory = try fixture.store.installedDirectory(.privacyFilter)
        let detection = Task {
            await fixture.service.detect(text: "Ada Lovelace", options: .init(), context: fixture.context, waitForWarm: true)
        }
        await eventually { await fixture.runtime.snapshot().active == 1 }
        let removal = Task { await fixture.store.remove(.privacyFilter) }
        await eventually { fixture.store.removingModels.contains(.privacyFilter) }
        XCTAssertTrue(FileManager.default.fileExists(atPath: directory.path))
        let held = await fixture.runtime.snapshot()
        XCTAssertEqual(held.unloadsWhileActive, 0)
        await fixture.runtime.release()
        _ = await detection.value
        await removal.value
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
        XCTAssertEqual(fixture.store.state(for: .privacyFilter), .notDownloaded)
        let drained = await fixture.runtime.snapshot()
        XCTAssertEqual(drained.unloadsWhileActive, 0)
        XCTAssertGreaterThan(drained.unloads, held.unloads)
        fixture.service.deactivate(fixture.context)
    }

    // contract-test: direct surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testPIIRemovalJoinsConcurrentInvalidationThroughActualUnload() async throws {
        let suite = "pii-removal-invalidation-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let fixture = try await makeFixture(holding: true, capabilityPreferences: defaults)
        defer { fixture.removeFiles() }
        let directory = try fixture.store.installedDirectory(.privacyFilter)
        let before = await fixture.runtime.snapshot()
        await fixture.runtime.holdUnload()
        let detection = Task {
            await fixture.service.detect(text: "Ada Lovelace", options: .init(), context: fixture.context, waitForWarm: true)
        }
        await eventually { await fixture.runtime.snapshot().active == 1 }
        let removedBeforeUnload = expectation(description: "removal cannot complete while unload is held")
        removedBeforeUnload.isInverted = true
        var holdingUnload = true
        let removal = Task { @MainActor in
            await fixture.store.remove(.privacyFilter)
            if holdingUnload { removedBeforeUnload.fulfill() }
        }
        await eventually { fixture.store.removingModels.contains(.privacyFilter) && fixture.service.status == .regexOnly }
        // A second lifecycle invalidation must join the removal's actual drain,
        // even though it changes the publication generation again.
        fixture.service.deactivate(fixture.context)
        await fixture.runtime.release()
        _ = await detection.value
        await eventually { await fixture.runtime.snapshot().unloads > before.unloads }
        await fulfillment(of: [removedBeforeUnload], timeout: 0.1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: directory.path))
        XCTAssertTrue(fixture.store.removingModels.contains(.privacyFilter))
        let held = await fixture.runtime.snapshot()
        XCTAssertEqual(held.unloads, before.unloads + 1, "Concurrent invalidators share one actual cleanup")
        XCTAssertEqual(held.unloadsWhileActive, 0)
        holdingUnload = false
        await fixture.runtime.releaseUnload()
        await removal.value
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
        XCTAssertEqual(fixture.store.state(for: .privacyFilter), .notDownloaded)
    }

    // contract-test: direct surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testDisabledEnhancedCapabilityPreservesRegexAndDrainsBeforeReenabling() async throws {
        let suite = "pii-capability-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let fixture = try await makeFixture(capabilityPreferences: defaults)
        defer { fixture.removeFiles() }
        let before = await fixture.runtime.snapshot()
        await fixture.store.setCapabilityEnabled(.privacyFilter, enabled: false)
        let disabled = await fixture.service.detect(text: "ada@example.test", options: .init(), context: fixture.context, waitForWarm: true)
        XCTAssertEqual(disabled.mode, .regexOnly)
        XCTAssertTrue(disabled.matches.contains { $0.value == "ada@example.test" })
        let after = await fixture.runtime.snapshot()
        XCTAssertEqual(after.inputs.count, before.inputs.count)
        XCTAssertGreaterThan(after.unloads, before.unloads)
        XCTAssertEqual(fixture.store.state(for: .privacyFilter), .ready)
        await fixture.store.setCapabilityEnabled(.privacyFilter, enabled: true)
        await eventually { fixture.service.status == .ready }
        let enabled = await fixture.service.detect(text: "Ada Lovelace", options: .init(), context: fixture.context, waitForWarm: true)
        XCTAssertEqual(enabled.mode, .enhanced)
        fixture.service.deactivate(fixture.context)
        await eventually { await fixture.runtime.snapshot().unloads > after.unloads }
    }

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
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 40_000_000, previewCadence: .baseline)
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
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .baseline)
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
            let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .baseline)
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
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .baseline)
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
            let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .baseline)
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
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .baseline)
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
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .baseline)
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
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .baseline)
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
        let coordinator = ComposerPIIDetectionCoordinator(service: fixture.service, debounceNanoseconds: 1_000_000, previewCadence: .baseline)
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

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testOptInProductionCoordinatorCadenceBenchmark() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard environment["OPENMATES_PII_CADENCE_BENCHMARK"] == "1" else {
            throw XCTSkip("Native cadence benchmark requires an explicit opt-in")
        }
        #if !arch(arm64) || !os(macOS)
        throw XCTSkip("Native cadence benchmark is scoped to the approved Apple Silicon Mac")
        #else
        guard environment["OPENMATES_PII_CADENCE_ASSETS_VERIFIED"] == "1",
              let modelPath = environment["OPENMATES_PII_CADENCE_MODEL_DIRECTORY"] else {
            throw XCTSkip("Root must supply the already verified retained model assets")
        }
        let modelDirectory = URL(fileURLWithPath: modelPath, isDirectory: true)
        guard FileManager.default.fileExists(atPath: modelDirectory.appendingPathComponent("model.pte").path) else {
            throw XCTSkip("Retained local model is unavailable; this benchmark never downloads")
        }
        // Exactly the public fixtures measured as 22/101 tokens and one native
        // window each in results243. Never accept draft text from the environment.
        let short = "Ada Lovelace can be reached at ada@example.com or +1 415 555 0123."
        let medium = short + " " + String(repeating: "This synthetic planning note describes a public demonstration with a simple agenda and no private account records. ", count: 4) + "The closing sentence is still being compos"
        let fixture = try await makeFixture()
        defer { fixture.removeFiles() }
        fixture.service.deactivate(fixture.context)
        await eventually { await fixture.runtime.snapshot().unloads > 0 }
        // A tiny installed-controller fixture supplies lifecycle state. The adapter
        // forwards every actual warm/detect/unload to a fresh ProductionPIIRuntime
        // at the retained directory, without copying or changing those assets.
        let runtime = CadenceMeasuredProductionRuntime(directory: modelDirectory, allowedTexts: [short, medium])
        let service = EnhancedPIIDetectionService(controller: .init(store: fixture.store), runtime: runtime,
                                                 validContext: { _ in true }, observePressure: false)
        let retention = ComposerPIIContext(server: "https://example.invalid", accountGeneration: UUID(), routeID: "benchmark-active-composer")
        service.activate(retention, enabled: true)
        let readinessDeadline = ProcessInfo.processInfo.systemUptime + 30
        while service.status != .ready && ProcessInfo.processInfo.systemUptime < readinessDeadline {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        guard service.status == .ready else {
            await service.invalidateModel()
            XCTFail("Verified production runtime did not become ready within the bounded setup interval")
            return
        }
        var rows: [[String: Any]] = [["event": "cold_load", "seconds": service.coldLoadSeconds ?? 0]]
        var heartbeatMaximum = 0.0
        let heartbeat = Task { @MainActor in
            var last = ProcessInfo.processInfo.systemUptime
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 20_000_000) } catch { break }
                let now = ProcessInfo.processInfo.systemUptime
                heartbeatMaximum = max(heartbeatMaximum, max(0, now - last - 0.020)); last = now
            }
        }
        var completedCases: [String] = []
        let plannedCases = ["short", "medium"].flatMap { fixture in ComposerEnhancedPreviewCadence.allCases.map { "\($0.rawValue)/\(fixture)" } }
        for (name, text) in [("short", short), ("medium", medium)] {
            for policy in ComposerEnhancedPreviewCadence.allCases {
                guard await runtime.acceptsMore else { continue }
                let coordinator = ComposerPIIDetectionCoordinator(service: service, previewCadence: policy)
                var regexSeconds: Double?
                let submitted = ProcessInfo.processInfo.systemUptime
                let observation = coordinator.$publication.sink { publication in
                    guard regexSeconds == nil, publication?.snapshot.text == text,
                          publication?.result.mode == .regexOnly else { return }
                    regexSeconds = ProcessInfo.processInfo.systemUptime - submitted
                }
                let before = await runtime.admittedJobs
                coordinator.submit(text: text, options: .init(), context: fixture.context, enabled: true, foreground: true)
                try? await Task.sleep(nanoseconds: 650_000_000)
                let typing = await runtime.admittedJobs
                let document = ComposerDocumentV1(version: 1, nodes: [.text(id: "synthetic-send", source: text)])
                let sendStarted = ProcessInfo.processInfo.systemUptime
                let result = await coordinator.verifiedRedaction(document: document, excludedIds: [], options: .init(), context: fixture.context)
                let sendSeconds = ProcessInfo.processInfo.systemUptime - sendStarted
                let complete = result.mappings.contains { $0.original == "Ada Lovelace" }
                let timing = await runtime.timings()
                let after = await runtime.admittedJobs
                rows.append(["event": "case", "policy": policy.rawValue, "fixture": name,
                             "regex_seconds": regexSeconds.map { $0 as Any } ?? NSNull(), "send_verification_seconds": sendSeconds,
                             "typing_detector_jobs": typing - before, "total_detector_jobs": after - before,
                             "used_warm_model": timing?.usedWarmModel ?? false, "complete": complete,
                             "main_actor_max_delay_seconds": heartbeatMaximum])
                if complete { completedCases.append("\(policy.rawValue)/\(name)") }
                XCTAssertNotNil(regexSeconds, "Every policy must publish regex without waiting for native detection")
                if policy == .sendOnly { XCTAssertEqual(typing, before, "Typing cannot admit an enhanced detector job") }
                observation.cancel()
                coordinator.invalidate()
            }
        }
        service.deactivate(retention)
        await service.invalidateModel() // Join actual owner/kernel drain before returning.
        heartbeat.cancel(); await heartbeat.value
        let admittedJobs = await runtime.admittedJobs
        let stopReason = await runtime.stopReason
        rows.append(["event": "summary", "admitted_detector_jobs": admittedJobs,
                     "main_actor_max_delay_seconds": heartbeatMaximum, "completed_cases": completedCases,
                     "missing_cases": plannedCases.filter { !completedCases.contains($0) },
                     "stop_reason": stopReason ?? "none", "proof_scope": "headless-production-coordinator-not-app-rendering"])
        let data = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
        let output = String(decoding: data, as: UTF8.self)
        let attachment = XCTAttachment(string: output)
        attachment.name = "production-coordinator-cadence-synthetic-metrics"
        attachment.lifetime = .keepAlways
        add(attachment)
        print("PII_CADENCE_BENCHMARK " + output)
        #endif
    }

    private func makeFixture(installed: Bool = true, holding: Bool = false, holdingWarm: Bool = false,
                             capabilityPreferences: UserDefaults? = nil) async throws -> CoordinatorFixture {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("composer-pii-test-" + UUID().uuidString)
        let bytes = Data("tiny disposable PII asset".utf8)
        let revision = String(repeating: "a", count: 40)
        let manifest = LocalModelManifest(id: .privacyFilter, revision: revision, estimatedSizeBytes: Int64(bytes.count), files: [
            LocalModelFile(path: "model.pte", url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/model.pte")!,
                sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), sizeBytes: Int64(bytes.count))
        ])
        let store = LocalModelStore(catalog: try JSONEncoder().encode(LocalModelCatalog(models: [manifest])),
            root: root, downloader: CoordinatorAssetDownloader(bytes: bytes), verifyExisting: false,
            preferences: capabilityPreferences)
        if installed { await store.download(.privacyFilter) }
        let runtime = ControlledProductionPIIRuntime(holding: holding, holdingWarm: holdingWarm)
        let service = EnhancedPIIDetectionService(controller: .init(store: store), runtime: runtime,
            validContext: { _ in true }, observePressure: false, capabilityStore: capabilityPreferences == nil ? nil : store)
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

/// Test-only admission accounting around the actual production actor. Only the
/// two fixed, previously tokenized single-window fixtures are permitted.
private actor CadenceMeasuredProductionRuntime: ProductionPIIRuntimeServing {
    private let production = ProductionPIIRuntime()
    private let directory: URL
    private let allowedTexts: Set<String>
    private let started = ProcessInfo.processInfo.systemUptime
    private(set) var admittedJobs = 0
    private(set) var stopReason: String?
    init(directory: URL, allowedTexts: Set<String>) { self.directory = directory; self.allowedTexts = allowedTexts }
    var acceptsMore: Bool {
        if ProcessInfo.processInfo.systemUptime - started >= 120 { stopReason = stopReason ?? "wall_budget" }
        if admittedJobs >= 12 { stopReason = stopReason ?? "detector_job_budget" }
        return stopReason == nil
    }
    func warm(directory: URL) async throws -> Double { try await production.warm(directory: self.directory) }
    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan] {
        guard allowedTexts.contains(text), acceptsMore else { throw LocalPrivacyFilterError.busy }
        admittedJobs += 1
        let began = ProcessInfo.processInfo.systemUptime
        defer {
            if ProcessInfo.processInfo.systemUptime - began > 10 { stopReason = stopReason ?? "slow_detector_job" }
        }
        return try await production.detectedSpans(in: text)
    }
    func unload() async { await production.unload() }
    func timings() async -> LocalPrivacyFilterTimings? { await production.timings() }
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
    private var holdingUnload = false
    private var unloadWaiters: [CheckedContinuation<Void, Never>] = []
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
    func holdUnload() { holdingUnload = true }
    func releaseUnload() {
        holdingUnload = false
        let pending = unloadWaiters; unloadWaiters = []
        pending.forEach { $0.resume() }
    }
    func unload() async {
        if active > 0 { unloadsWhileActive += 1 }; unloads += 1
        if holdingUnload { await withCheckedContinuation { unloadWaiters.append($0) } }
    }
    func timings() async -> LocalPrivacyFilterTimings? {
        .init(loadSeconds: 0, tokenizeSeconds: 0.01, inferenceSeconds: 0.02, decodeSeconds: 0.003,
              totalSeconds: 0.033, usedWarmModel: true)
    }
    func snapshot() -> Snapshot {
        .init(warms: warms, unloads: unloads, active: active, maximumActive: maximumActive,
              unloadsWhileActive: unloadsWhileActive, inputs: inputs)
    }
}
