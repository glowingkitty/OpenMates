// Recorded test-run embed (`code-test-result`): preview card and fullscreen.
// Browser runs play the recorded video beside a step timeline (tapping a step
// seeks the video), cli runs show a terminal-styled step list, unit runs list
// the tests. Evidence URLs come from the Code Run artifact child embeds already
// present in the decrypted embed store; no transport logic lives here.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/code/TestResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/code/TestResultEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/code/TestResultStatusBadge.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.tests.recorded-evidence, code-run.tests.project-snapshot
import AVKit
import SwiftUI

/// Resolves an evidence asset id to a playable/displayable URL, or nil when the
/// artifact is missing or its signed URL expired.
typealias TestResultEvidenceURLResolver = (String) -> URL?

struct TestResultEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let resolveEvidenceURL: TestResultEvidenceURLResolver

    private var view: TestResultView { TestResultView(data: data) }

    var body: some View {
        switch mode {
        case .preview: TestResultPreviewBody(view: view, resolveEvidenceURL: resolveEvidenceURL)
        case .fullscreen: TestResultFullscreenBody(view: view, resolveEvidenceURL: resolveEvidenceURL)
        }
    }
}

struct TestResultStatusBadge: View {
    enum Tone { case passed, failed, stale, neutral }
    let tone: Tone
    let label: String

    var body: some View {
        HStack(spacing: .spacing2) {
            Circle().fill(dotStyle).frame(width: 8, height: 8)
            Text(label).font(.omSmall).fontWeight(.semibold)
        }
        .padding(.horizontal, .spacing3)
        .padding(.vertical, .spacing1)
        .foregroundStyle(tone == .failed ? Color.error : tone == .stale ? Color.warning : Color.fontPrimary)
        .background(Color.grey10, in: Capsule())
        .fixedSize()
        .accessibilityElement(children: .combine)
    }

    private var dotStyle: AnyShapeStyle {
        switch tone {
        case .passed: AnyShapeStyle(LinearGradient.appCode)
        case .failed: AnyShapeStyle(Color.error)
        case .stale: AnyShapeStyle(Color.warning)
        case .neutral: AnyShapeStyle(Color.grey30)
        }
    }

    static func tone(for status: TestResultRunStatus) -> Tone {
        switch status {
        case .passed: .passed
        case .failed, .error, .timedOut: .failed
        case .cancelled: .neutral
        }
    }
}

private struct TestResultPreviewBody: View {
    let view: TestResultView
    let resolveEvidenceURL: TestResultEvidenceURLResolver

    var body: some View {
        let statusLabel = AppStrings.localized(view.runStatus.labelKey)
        // `.tr-info` of TestResultEmbedPreview.svelte: title, status row and counts,
        // kept clear of the BasicInfosBar painted over the card's bottom 61pt.
        VStack(spacing: 0) {
            if view.kind == .browser { frameArea(statusLabel: statusLabel) }
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(view.title)
                    .font(.omP).fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1).truncationMode(.tail)
                    .accessibilityIdentifier("test-result-preview-title")
                HStack(spacing: .spacing3) {
                    TestResultStatusBadge(tone: TestResultStatusBadge.tone(for: view.runStatus), label: statusLabel)
                        .accessibilityIdentifier("test-result-preview-status")
                    if !view.isCurrent {
                        TestResultStatusBadge(tone: .stale, label: AppStrings.localized("embeds.code.test_result.stale"))
                            .accessibilityIdentifier("test-result-preview-stale")
                    }
                }
                // `.tr-counts` wraps whole items (flex-wrap), never inside one.
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: .spacing4) { countItems; durationItem }
                    VStack(alignment: .leading, spacing: .spacing2) {
                        HStack(spacing: .spacing4) { countItems }
                        durationItem
                    }
                }
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("test-result-preview-counts")
            }
            .padding(.horizontal, .spacing12)
            .padding(.vertical, .spacing6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(maxHeight: view.kind == .browser ? nil : .infinity, alignment: .center)
        }
        .padding(.bottom, EmbedPreviewFooterLayout.height)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("test-result-preview")
    }

    @ViewBuilder
    private var countItems: some View {
        Text("\(view.passed) \(AppStrings.localized("embeds.code.test_result.status_passed"))").fixedSize()
        Text("\(view.failed) \(AppStrings.localized("embeds.code.test_result.status_failed"))")
            .foregroundStyle(Color.error).fixedSize()
        if view.skipped > 0 {
            Text("\(view.skipped) \(AppStrings.localized("embeds.code.test_result.status_skipped"))").fixedSize()
        }
    }

    @ViewBuilder
    private var durationItem: some View {
        if view.durationMs != nil { Text(TestResultView.formatDuration(view.durationMs)).fixedSize() }
    }

    @ViewBuilder
    private func frameArea(statusLabel: String) -> some View {
        let url = view.evidence(kind: "preview_frame")?.assetId.flatMap(resolveEvidenceURL)
        ZStack {
            Color.grey10
            if let url {
                AsyncImage(url: url) { phase in
                    if let image = phase.image { image.resizable().scaledToFit() } else { placeholder(statusLabel) }
                }
                .accessibilityIdentifier("test-result-preview-frame")
            } else {
                placeholder(statusLabel)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("test-result-preview-frame-area")
    }

    private func placeholder(_ statusLabel: String) -> some View {
        Text(statusLabel).font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontSecondary)
            .accessibilityIdentifier("test-result-preview-placeholder")
    }
}

/// Owns the AVPlayer of a recorded run and publishes the playback time so the
/// timeline can highlight the playing step.
@MainActor
private final class TestResultPlayback: ObservableObject {
    @Published var currentMs: Double = 0
    private(set) var player: AVPlayer?
    private var observer: Any?

    func load(_ url: URL?) {
        tearDown()
        guard let url else { return }
        let player = AVPlayer(url: url)
        observer = player.addPeriodicTimeObserver(
            forInterval: CMTime(value: 1, timescale: 10), queue: .main
        ) { [weak self] time in
            Task { @MainActor in self?.currentMs = time.seconds * 1000 }
        }
        self.player = player
        objectWillChange.send()
    }

    func seek(toMs ms: Double) {
        currentMs = ms
        player?.seek(to: CMTime(seconds: ms / 1000, preferredTimescale: 600))
    }

    func tearDown() {
        if let observer { player?.removeTimeObserver(observer) }
        observer = nil
        player?.pause()
        player = nil
    }
}

private struct TestResultFullscreenBody: View {
    let view: TestResultView
    let resolveEvidenceURL: TestResultEvidenceURLResolver
    @StateObject private var playback = TestResultPlayback()

    var body: some View {
        let statusLabel = AppStrings.localized(view.runStatus.labelKey)
        VStack(alignment: .leading, spacing: .spacing4) {
            summary(statusLabel: statusLabel)
            if let error = view.error {
                Text(error).font(.omSmall).foregroundStyle(Color.error)
                    .accessibilityIdentifier("test-result-error")
            }
            switch view.kind {
            case .browser: browser
            case .cli: terminal
            case .unit: tests
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .padding(.spacing2)
        .onAppear { playback.load(videoURL) }
        .onDisappear { playback.tearDown() }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("test-result-fullscreen-body")
    }

    private var videoURL: URL? { view.evidence(kind: "video")?.assetId.flatMap(resolveEvidenceURL) }

    private func summary(statusLabel: String) -> some View {
        HStack(spacing: .spacing3) {
            TestResultStatusBadge(tone: TestResultStatusBadge.tone(for: view.runStatus), label: statusLabel)
                .accessibilityIdentifier("test-result-status")
            if !view.isCurrent {
                let stale = AppStrings.localized("embeds.code.test_result.stale")
                TestResultStatusBadge(tone: .stale, label: view.staleReason.map { "\(stale): \($0)" } ?? stale)
                    .accessibilityIdentifier("test-result-stale")
            }
            Text("\(view.passed) \(AppStrings.localized("embeds.code.test_result.status_passed"))")
                .accessibilityIdentifier("test-result-count-passed")
            Text("\(view.failed) \(AppStrings.localized("embeds.code.test_result.status_failed"))")
                .foregroundStyle(Color.error)
                .accessibilityIdentifier("test-result-count-failed")
            Text("\(view.skipped) \(AppStrings.localized("embeds.code.test_result.status_skipped"))")
                .accessibilityIdentifier("test-result-count-skipped")
        }
        .font(.omSmall).foregroundStyle(Color.fontSecondary)
    }

    private var browser: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Group {
                if let player = playback.player {
                    VideoPlayer(player: player).accessibilityIdentifier("test-result-video")
                } else if let frame = view.evidence(kind: "preview_frame")?.assetId.flatMap(resolveEvidenceURL) {
                    AsyncImage(url: frame) { $0.resizable().scaledToFit() } placeholder: { Color.grey10 }
                        .accessibilityIdentifier("test-result-video-fallback")
                } else {
                    Text(AppStrings.localized("embeds.code.test_result.no_video"))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .frame(maxWidth: .infinity, minHeight: 160)
                        .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
                        .accessibilityIdentifier("test-result-video-missing")
                }
            }
            .frame(maxWidth: .infinity, minHeight: 200)
            .clipShape(RoundedRectangle(cornerRadius: .radius3))

            VStack(alignment: .leading, spacing: .spacing2) {
                ForEach(Array(view.steps.enumerated()), id: \.offset) { index, step in
                    stepRow(index: index, step: step)
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel(AppStrings.localized("embeds.code.test_result.steps"))
            .accessibilityIdentifier("test-result-timeline")
        }
    }

    private func stepRow(index: Int, step: TestResultStep) -> some View {
        let active = index == view.activeStepIndex(at: playback.currentMs)
        return Button { playback.seek(toMs: step.startMs) } label: {
            HStack(alignment: .top, spacing: .spacing3) {
                Circle().fill(rowStyle(step.rowStatus)).frame(width: 8, height: 8).padding(.top, 5)
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(step.name).font(.omSmall).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                    Text(AppStrings.localized(step.rowStatus.labelKey)).font(.omXs).foregroundStyle(Color.fontSecondary)
                    if let error = step.error { Text(error).font(.omXs).foregroundStyle(Color.error) }
                }
                Spacer(minLength: 0)
            }
            .padding(.spacing3)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(active ? Color.grey20 : Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("test-result-step-\(index)")
        .accessibilityAddTraits(active ? .isSelected : [])
    }

    private var terminal: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            ForEach(Array(view.steps.enumerated()), id: \.offset) { index, step in
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(step.command.map { "$ \($0)" } ?? step.name)
                        .font(.omSmall).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                        .accessibilityIdentifier("test-result-term-command-\(index)")
                    if let output = step.output, !output.isEmpty {
                        Text(output).font(.omXs).foregroundStyle(Color.fontSecondary)
                            .accessibilityIdentifier("test-result-term-output-\(index)")
                    }
                    if let error = step.error { Text(error).font(.omXs).foregroundStyle(Color.error) }
                    Text(AppStrings.localized(step.rowStatus.labelKey)).font(.omXs)
                        .foregroundStyle(step.rowStatus == .passed ? Color.fontSecondary : Color.error)
                        .accessibilityIdentifier("test-result-term-status-\(index)")
                }
                .padding(.spacing3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
            }
        }
        .accessibilityIdentifier("test-result-terminal")
    }

    private var tests: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            ForEach(Array(view.tests.enumerated()), id: \.offset) { index, test in
                VStack(alignment: .leading, spacing: .spacing1) {
                    HStack(spacing: .spacing3) {
                        Circle().fill(rowStyle(test.rowStatus)).frame(width: 8, height: 8)
                        Text(test.name).font(.omSmall).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                        Spacer(minLength: 0)
                        Text(AppStrings.localized(test.rowStatus.labelKey)).font(.omXs).foregroundStyle(Color.fontSecondary)
                        if test.durationMs != nil {
                            Text(TestResultView.formatDuration(test.durationMs)).font(.omXs).foregroundStyle(Color.fontSecondary)
                        }
                    }
                    if let error = test.error { Text(error).font(.omXs).foregroundStyle(Color.error) }
                }
                .padding(.spacing3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
                .accessibilityIdentifier("test-result-test-\(index)")
            }
        }
        .accessibilityIdentifier("test-result-tests")
    }

    private func rowStyle(_ status: TestResultRowStatus) -> AnyShapeStyle {
        switch status {
        case .passed: AnyShapeStyle(LinearGradient.appCode)
        case .failed, .error: AnyShapeStyle(Color.error)
        case .skipped: AnyShapeStyle(Color.grey30)
        }
    }
}
