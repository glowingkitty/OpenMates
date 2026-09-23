// Native inline preview surface for atomic composer embed nodes.
// Uses the explicit AppleComposerRendererRegistry and never a generic fallback.
// Finished supported records reuse existing native read renderers inside web-parity chrome.
// Pending and summary-only families use deterministic lifecycle presentation.
// Required callbacks keep host behavior explicit across iOS and macOS.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.embeds.gated-send

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
//          frontend/packages/ui/src/components/embeds/audio/RecordingEmbedPreview.svelte
// CSS:     UnifiedEmbedPreview.svelte — .unified-embed-preview, .desktop-layout
//          RecordingEmbedPreview.svelte — .recording-preview, .waveform-strip
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Foundation
import ImageIO
import SwiftUI
import AVFoundation
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

private enum AppleComposerPreviewMetrics {
    static let width: CGFloat = 300
    static let height: CGFloat = 200
    static let cornerRadius: CGFloat = 30
}

struct AppleComposerEmbedActions: @unchecked Sendable {
    let onOpen: (String) -> Void
    let onRetry: (String) -> Void
    let onRemove: (String) -> Void
}

struct AppleComposerEmbedPreview: View {
    let descriptor: AppleComposerPreviewDescriptor
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let embedRecord: EmbedRecord?
    let allEmbedRecords: [String: EmbedRecord]
    private let localPreviewData: Data?
    private let localPreviewImage: Image?
    let actions: AppleComposerEmbedActions
    let showsActions: Bool

    init(
        descriptor: AppleComposerPreviewDescriptor,
        node: ComposerNodeV1,
        lifecycle: AppleComposerEmbedLifecycleState,
        embedRecord: EmbedRecord?,
        allEmbedRecords: [String: EmbedRecord],
        localPreviewData: Data? = nil,
        actions: AppleComposerEmbedActions,
        showsActions: Bool = true
    ) {
        self.descriptor = descriptor
        self.node = node
        self.lifecycle = lifecycle
        self.embedRecord = embedRecord
        self.allEmbedRecords = allEmbedRecords
        self.localPreviewData = localPreviewData
        self.localPreviewImage = Self.makeLocalPreviewImage(data: localPreviewData)
        self.actions = actions
        self.showsActions = showsActions
    }

    var body: some View {
        ZStack(alignment: .topTrailing) {
            if case .image = descriptor.family,
               let localPreviewImage {
                ComposerLocalImagePreview(
                    image: localPreviewImage,
                    title: title,
                    lifecycleLabel: lifecycle == .finished ? nil : lifecycleLabel
                )
            } else if case .recording = descriptor.family {
                ComposerAudioPreview(
                    title: title,
                    lifecycle: lifecycle,
                    lifecycleLabel: lifecycleLabel,
                    data: embedRecord?.rawData,
                    localAudioData: localPreviewData
                )
                .contentShape(RoundedRectangle(cornerRadius: AppleComposerPreviewMetrics.cornerRadius))
                .onTapGesture {
                    if lifecycle == .finished {
                        actions.onOpen(node.id)
                    }
                }
                .contextMenu {
                    if showsActions {
                        if lifecycle == .finished {
                            Button(openLabel) { actions.onOpen(node.id) }
                        }
                        if lifecycle == .error {
                            Button(AppStrings.retry) { actions.onRetry(node.id) }
                        }
                        Button(AppStrings.remove, role: .destructive) {
                            actions.onRemove(node.id)
                        }
                    }
                }
            } else if case .map = descriptor.family {
                ComposerLocationPreview(
                    title: title,
                    lifecycle: lifecycle,
                    lifecycleLabel: lifecycleLabel,
                    data: embedRecord?.rawData
                )
            } else if case .group(let childType) = descriptor.family,
               let childDescriptor = AppleComposerRendererRegistry.shared.descriptor(for: childType) {
                AppleComposerGroupedEmbedPreview(
                    childDescriptor: childDescriptor,
                    node: node,
                    lifecycle: lifecycle,
                    embedRecord: embedRecord,
                    allEmbedRecords: allEmbedRecords,
                    actions: actions
                )
            } else if lifecycle == .finished, let embedRecord, usesReadRenderer {
                EmbedPreviewCard(embed: embedRecord, allEmbedRecords: allEmbedRecords) {
                    actions.onOpen(node.id)
                }
            } else {
                composerSummaryPreview
            }
            if showsActions && !isRecordingPreview {
                actionBar
                    .padding(.spacing4)
            }
        }
        .frame(width: AppleComposerPreviewMetrics.width, height: AppleComposerPreviewMetrics.height)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("native-composer-preview-\(descriptor.embedType)-\(lifecycle.rawValue)")
        .accessibilityValue(node.contentRef == nil ? "local-preview-no-durable-id" : "durable-preview")
    }

    private static func makeLocalPreviewImage(data: Data?) -> Image? {
        guard let data,
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                  kCGImageSourceCreateThumbnailFromImageAlways: true,
                  kCGImageSourceCreateThumbnailWithTransform: true,
                  kCGImageSourceShouldCacheImmediately: true,
                  kCGImageSourceThumbnailMaxPixelSize: 600,
              ] as CFDictionary) else {
            return nil
        }
        #if canImport(UIKit)
        return Image(uiImage: UIImage(cgImage: thumbnail))
        #elseif canImport(AppKit)
        return Image(nsImage: NSImage(cgImage: thumbnail, size: .zero))
        #endif
    }

    private var summaryPreview: some View {
        AppleComposerSummaryCard(
            appId: appId,
            title: title,
            lifecycle: lifecycle,
            lifecycleLabel: lifecycleLabel
        )
    }

    @ViewBuilder
    private var composerSummaryPreview: some View {
        switch descriptor.family {
        case .appSkillUse:
            AppSkillUseComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        case .repository:
            RepositoryComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        case .pcbSchematic:
            PcbSchematicComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        case .electronicsComponent:
            ElectronicsComponentComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        case .fitnessLocation:
            FitnessLocationComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        case .fitnessClass:
            FitnessClassComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        case .socialPost:
            SocialPostComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        case .weatherDay:
            WeatherDayComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        case .focusActivation:
            FocusModeComposerPreview(node: node, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
        default:
            summaryPreview
        }
    }

    private var actionBar: some View {
        HStack(spacing: .spacing2) {
            if lifecycle == .finished {
                previewAction(icon: "visible", label: openLabel) {
                    actions.onOpen(node.id)
                }
            }
            if lifecycle == .error {
                previewAction(icon: "refresh", label: AppStrings.retry) {
                    actions.onRetry(node.id)
                }
            }
            previewAction(icon: "close", label: AppStrings.remove) {
                actions.onRemove(node.id)
            }
        }
    }

    private var isRecordingPreview: Bool {
        if case .recording = descriptor.family { return true }
        return false
    }

    private func previewAction(
        icon: String,
        label: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Icon(icon, size: 14)
                .foregroundStyle(Color.fontPrimary)
                .frame(width: 30, height: 30)
                .background(Color.grey10)
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityIdentifier("native-composer-preview-action-\(icon)")
    }

    private var title: String {
        node.display?.title ?? AppStrings.uploadProgressProcessing
    }

    private var openLabel: String {
        #if os(macOS)
        AppStrings.embedClickToShowDetails
        #else
        AppStrings.embedTapToShowDetails
        #endif
    }

    private var lifecycleLabel: String {
        switch lifecycle {
        case .draft: AppStrings.waitingForUpload
        case .uploading: AppStrings.uploadProgressUploading(percent: "0")
        case .processing: AppStrings.uploadProgressProcessing
        case .transcribing: AppStrings.uploadProgressTranscribing
        case .correcting: AppStrings.uploadProgressProcessing
        case .finished: openLabel
        case .error: AppStrings.uploadProgressError
        case .cancelled: AppStrings.cancel
        }
    }

    private var usesReadRenderer: Bool {
        switch descriptor.family {
        case .appSkillUse, .repository, .pcbSchematic, .electronicsComponent,
             .fitnessLocation, .fitnessClass, .socialPost, .weatherDay, .group:
            false
        default:
            true
        }
    }

    private var appId: String {
        switch descriptor.family {
        case .recording: "audio"
        case .appSkillUse: "openmates"
        case .repository, .code: "code"
        case .document: "docs"
        case .pcbSchematic, .electronicsComponent: "electronics"
        case .event: "events"
        case .fitnessLocation, .fitnessClass: "fitness"
        case .appointment: "health"
        case .homeListing: "home"
        case .image, .imageResult: "images"
        case .email: "mail"
        case .place, .map: "maps"
        case .mathPlot: "math"
        case .mindMap: "mindmaps"
        case .website: "web"
        case .recipe: "nutrition"
        case .pdf: "pdf"
        case .product: "shopping"
        case .socialPost: "social_media"
        case .travelConnection, .travelStay: "travel"
        case .video: "videos"
        case .weatherDay: "weather"
        case .sheet: "sheets"
        case .focusActivation: "openmates"
        case .group(let childType):
            AppleComposerRendererRegistry.shared.descriptor(for: childType)
                .map { appId(for: $0.family) } ?? "openmates"
        }
    }

    private func appId(for family: AppleComposerPreviewFamily) -> String {
        switch family {
        case .repository, .code: "code"
        case .document: "docs"
        case .pcbSchematic, .electronicsComponent: "electronics"
        case .event: "events"
        case .fitnessLocation, .fitnessClass: "fitness"
        case .appointment: "health"
        case .homeListing: "home"
        case .image, .imageResult: "images"
        case .email: "mail"
        case .place, .map: "maps"
        case .mathPlot: "math"
        case .mindMap: "mindmaps"
        case .website: "web"
        case .recipe: "nutrition"
        case .pdf: "pdf"
        case .product: "shopping"
        case .socialPost: "social_media"
        case .travelConnection, .travelStay: "travel"
        case .video: "videos"
        case .weatherDay: "weather"
        case .sheet: "sheets"
        case .focusActivation: "openmates"
        case .recording: "audio"
        case .appSkillUse, .group: "openmates"
        }
    }
}

private struct ComposerLocalImagePreview: View {
    let image: Image
    let title: String
    let lifecycleLabel: String?

    var body: some View {
        AppleComposerUnifiedCard(
            appId: "images",
            title: title,
            subtitle: lifecycleLabel
        ) {
            image
                .resizable()
                .scaledToFill()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .clipped()
                .accessibilityElement()
                .accessibilityIdentifier("native-composer-image-content")
        }
    }
}

private struct ComposerAudioPreview: View {
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    let content: ComposerAudioPreviewContent
    let localAudioData: Data?
    @StateObject private var player: ComposerAudioPreviewPlayer

    init(
        title: String,
        lifecycle: AppleComposerEmbedLifecycleState,
        lifecycleLabel: String,
        data: [String: AnyCodable]?,
        localAudioData: Data?
    ) {
        self.lifecycle = lifecycle
        self.lifecycleLabel = lifecycleLabel
        self.localAudioData = localAudioData
        let fallbackTitle: String? = switch lifecycle {
        case .transcribing, .correcting, .finished: title
        case .draft, .uploading, .processing, .error, .cancelled: nil
        }
        self.content = ComposerAudioPreviewContent(
            data: data,
            // Resolution can mark the same atom finished before its encrypted
            // record hydrates. Keep the corrected title as a bounded fallback.
            provisionalTranscript: fallbackTitle
        )
        _player = StateObject(wrappedValue: ComposerAudioPreviewPlayer(data: localAudioData))
    }

    var body: some View {
        AppleComposerUnifiedCard(
            appId: "audio",
            title: content.title ?? AppStrings.audioRecording,
            subtitle: subtitle,
            trailingAction: player.isAvailable && lifecycle == .finished
                ? AnyView(audioPlayButton)
                : nil
        ) {
            VStack(alignment: .leading, spacing: .spacing4) {
                if let samples = content.waveformSamples {
                    ComposerAudioWaveform(samples: samples, progress: player.progress)
                }

                if lifecycle == .finished,
                   let modelName = content.modelDisplayName,
                   content.transcript != nil {
                    Text(AppStrings.audioTranscribedBy(model: modelName))
                        .font(.omMicro)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                        .accessibilityIdentifier("native-composer-audio-attribution")
                }

                if let transcript = content.transcript {
                    Text(transcript)
                        .font(.omXs)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(3)
                        .accessibilityIdentifier("native-composer-audio-transcript")
                    if let processingStatus {
                        processingStatusLabel(processingStatus)
                    }
                } else if let processingStatus {
                    HStack(spacing: .spacing3) {
                        ProgressView()
                            .tint(Color.buttonPrimary)
                        processingStatusLabel(processingStatus)
                    }
                } else {
                    Text(AppStrings.audioTranscriptUnavailable)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("native-composer-audio-content")
        }
        .onChange(of: localAudioData) { _, data in
            player.replace(data: data)
        }
    }

    private var audioPlayButton: some View {
        Button(action: player.togglePlayback) {
            Icon(player.isPlaying ? "pause" : "play", size: 16)
                .foregroundStyle(Color.fontButton)
                .frame(width: 36, height: 36)
                .background(LinearGradient.appAudio)
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(player.isPlaying ? AppStrings.pause : AppStrings.play)
        .accessibilityIdentifier("native-composer-audio-play-button")
    }

    private var subtitle: String {
        if let processingStatus { return processingStatus }
        guard lifecycle == .finished else { return lifecycleLabel }
        return content.formattedDuration ?? AppStrings.audioRecordingDescription
    }

    private var processingStatus: String? {
        switch lifecycle {
        case .uploading, .processing:
            return lifecycleLabel
        case .transcribing:
            guard let modelName = content.modelDisplayName else { return lifecycleLabel }
            return AppStrings.localized("app_skills.audio.transcribe.transcribing_via")
                .replacingOccurrences(of: "{model}", with: modelName)
        case .correcting:
            return AppStrings.audioAutoCorrecting
        case .draft, .finished, .error, .cancelled:
            return nil
        }
    }

    private func processingStatusLabel(_ value: String) -> some View {
        Text(value)
            .font(.omMicro)
            .foregroundStyle(Color.fontSecondary)
            .lineLimit(1)
            .accessibilityIdentifier("native-composer-audio-status")
    }
}

struct ComposerAudioPreviewContent: Equatable {
    let title: String?
    let transcript: String?
    let model: String?
    let durationSeconds: Double?
    let waveformSamples: [Double]?

    @MainActor
    init(data: [String: AnyCodable]?, provisionalTranscript: String? = nil) {
        title = Self.nonemptyString(data, key: "title")
        model = Self.nonemptyString(data, key: "model")
        durationSeconds = Self.number(data?["duration"]?.value)
            ?? Self.number(data?["duration_seconds"]?.value)

        let useCorrected = data?["use_corrected"]?.value as? Bool ?? true
        let original = Self.nonemptyString(data, key: "transcript_original")
        let corrected = Self.nonemptyString(data, key: "transcript_corrected")
        let fallback = Self.firstNonemptyString(
            data,
            keys: ["transcription", "transcript", "transcript_preview", "text", "corrected_transcript"]
        )
        if useCorrected, let corrected {
            transcript = corrected
        } else if !useCorrected, let original {
            transcript = original
        } else {
            transcript = fallback ?? corrected ?? original ?? Self.provisionalTranscript(provisionalTranscript)
        }

        if let waveform = data?["waveform"]?.value as? [String: Any],
           let rawSamples = waveform["samples"] as? [Any] {
            let normalized = rawSamples.compactMap(Self.number).map { min(1, max(0.06, $0 / 100)) }
            waveformSamples = normalized.isEmpty ? nil : normalized
        } else {
            waveformSamples = nil
        }
    }

    var formattedDuration: String? {
        guard let durationSeconds, durationSeconds.isFinite, durationSeconds >= 0 else { return nil }
        let total = Int(durationSeconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    var modelDisplayName: String? {
        guard let model else { return nil }
        if let bundledName = Self.bundledModelDisplayNames[model] {
            return bundledName
        }
        // Keep internal routing IDs out of the user-facing card when metadata is
        // absent. These two IDs are also the offline recording defaults.
        switch model {
        case "voxtral-mini-2602":
            return "Voxtral Mini"
        case "voxtral-mini-transcribe-realtime-2602":
            return "Voxtral Mini Realtime"
        default:
            return nil
        }
    }

    private static let bundledModelDisplayNames: [String: String] = {
        guard let catalog = try? NativeModelCatalog.load(bundle: .main) else { return [:] }
        return Dictionary(uniqueKeysWithValues: catalog.models.map { ($0.id, $0.name) })
    }()

    private static func nonemptyString(_ data: [String: AnyCodable]?, key: String) -> String? {
        guard let value = data?[key]?.value as? String,
              !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return value
    }

    private static func firstNonemptyString(_ data: [String: AnyCodable]?, keys: [String]) -> String? {
        keys.lazy.compactMap { nonemptyString(data, key: $0) }.first
    }

    private static func nonemptyString(_ value: String?) -> String? {
        guard let value,
              !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return value
    }

    @MainActor
    private static func provisionalTranscript(_ value: String?) -> String? {
        guard let value = nonemptyString(value) else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.caseInsensitiveCompare(AppStrings.audioRecording) != .orderedSame else { return nil }

        let fileExtension = (trimmed as NSString).pathExtension.lowercased()
        let audioExtensions: Set<String> = ["aac", "flac", "m4a", "mp3", "ogg", "wav", "webm"]
        guard !audioExtensions.contains(fileExtension) else { return nil }
        return trimmed
    }

    private static func number(_ value: Any?) -> Double? {
        if let value = value as? Double { return value }
        if let value = value as? Int { return Double(value) }
        if let value = value as? NSNumber { return value.doubleValue }
        return nil
    }
}

private struct ComposerAudioWaveform: View {
    let samples: [Double]
    let progress: Double

    var body: some View {
        GeometryReader { proxy in
            let width = ComposerAudioWaveformGeometry.barWidth(
                containerWidth: proxy.size.width,
                sampleCount: samples.count
            )
            ZStack(alignment: .leading) {
                HStack(spacing: ComposerAudioWaveformGeometry.gap) {
                    ForEach(Array(samples.enumerated()), id: \.offset) { _, sample in
                        Capsule()
                            .fill(LinearGradient.appAudio)
                            .frame(width: width, height: max(2, proxy.size.height * sample))
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)

                Capsule()
                    .fill(Color.fontPrimary)
                    .frame(width: 2, height: proxy.size.height)
                    .offset(x: max(0, (proxy.size.width - 2) * progress))
            }
        }
        .frame(height: 30)
        .opacity(0.78)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(AppStrings.audioRecording)
        .accessibilityIdentifier("native-composer-audio-waveform")
        .accessibilityValue("\(Int((progress * 100).rounded()))%")
    }
}

enum ComposerAudioWaveformGeometry {
    static let gap: CGFloat = 1

    static func barWidth(containerWidth: CGFloat, sampleCount: Int) -> CGFloat {
        let count = max(1, sampleCount)
        let totalGap = CGFloat(count - 1) * gap
        return max(0, (containerWidth - totalGap) / CGFloat(count))
    }
}

enum ComposerAudioPlaybackProgress {
    static func normalized(currentTime: TimeInterval, duration: TimeInterval) -> Double {
        guard currentTime.isFinite, duration.isFinite, duration > 0 else { return 0 }
        return min(1, max(0, currentTime / duration))
    }
}

@MainActor
private final class ComposerAudioPreviewPlayer: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published private(set) var isPlaying = false
    @Published private(set) var progress = 0.0
    @Published private(set) var isAvailable = false
    private var player: AVAudioPlayer?
    private var progressTask: Task<Void, Never>?

    init(data: Data?) {
        if let data {
            player = try? AVAudioPlayer(data: data)
            player?.prepareToPlay()
        }
        super.init()
        player?.delegate = self
        isAvailable = player != nil
    }

    func replace(data: Data?) {
        stopProgressUpdates()
        player?.stop()
        player = data.flatMap { try? AVAudioPlayer(data: $0) }
        player?.delegate = self
        player?.prepareToPlay()
        isPlaying = false
        progress = 0
        isAvailable = player != nil
    }

    func togglePlayback() {
        guard let player else { return }
        if player.isPlaying {
            player.pause()
            isPlaying = false
            refreshProgress()
            stopProgressUpdates()
        } else {
            player.play()
            isPlaying = true
            startProgressUpdates()
        }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            isPlaying = false
            progress = 0
            stopProgressUpdates()
        }
    }

    private func startProgressUpdates() {
        stopProgressUpdates()
        progressTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                self?.refreshProgress()
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
    }

    private func stopProgressUpdates() {
        progressTask?.cancel()
        progressTask = nil
    }

    private func refreshProgress() {
        guard let player else {
            progress = 0
            return
        }
        progress = ComposerAudioPlaybackProgress.normalized(
            currentTime: player.currentTime,
            duration: player.duration
        )
    }
}

private struct ComposerLocationPreview: View {
    let title: String
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    let data: [String: AnyCodable]?

    var body: some View {
        AppleComposerUnifiedCard(
            appId: "maps",
            title: name,
            subtitle: lifecycleLabel
        ) {
            MapsLocationRenderer(data: data, mode: .preview)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("native-composer-location-content")
        }
    }

    private var name: String {
        let value = data?["name"]?.value as? String
        return value?.isEmpty == false ? value! : title
    }
}

private struct AppleComposerUnifiedCard<Details: View>: View {
    let appId: String
    let title: String
    let subtitle: String?
    let trailingAction: AnyView?
    @ViewBuilder let details: () -> Details

    init(
        appId: String,
        title: String,
        subtitle: String?,
        trailingAction: AnyView? = nil,
        @ViewBuilder details: @escaping () -> Details
    ) {
        self.appId = appId
        self.title = title
        self.subtitle = subtitle
        self.trailingAction = trailingAction
        self.details = details
    }

    var body: some View {
        VStack(spacing: 0) {
            details()
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            EmbedBasicInfoBar(
                appId: appId,
                skillIconName: AppIconView.iconName(forAppId: appId),
                title: title,
                subtitle: subtitle,
                faviconURL: nil,
                showSkillIcon: false,
                trailingAction: trailingAction
            )
        }
        .frame(width: AppleComposerPreviewMetrics.width, height: AppleComposerPreviewMetrics.height)
        .background(Color.grey25)
        .clipShape(RoundedRectangle(cornerRadius: AppleComposerPreviewMetrics.cornerRadius))
        .shadow(color: .black.opacity(0.16), radius: 24, x: 0, y: 8)
        .shadow(color: .black.opacity(0.10), radius: 6, x: 0, y: 2)
    }
}

private struct AppleComposerGroupedEmbedPreview: View {
    let childDescriptor: AppleComposerPreviewDescriptor
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let embedRecord: EmbedRecord?
    let allEmbedRecords: [String: EmbedRecord]
    let actions: AppleComposerEmbedActions

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            LazyHStack(spacing: .spacing4) {
                if childEmbedRecords.isEmpty {
                    childPreview(embedRecord: nil)
                } else {
                    ForEach(childEmbedRecords) { childRecord in
                        childPreview(embedRecord: childRecord)
                    }
                }
            }
        }
    }

    private var childEmbedRecords: [EmbedRecord] {
        guard let embedRecord else { return [] }
        return embedRecord.childEmbedIds
            .compactMap { allEmbedRecords[$0] }
            .filter { $0.type == childDescriptor.embedType }
    }

    private func childPreview(embedRecord: EmbedRecord?) -> some View {
        AnyView(AppleComposerEmbedPreview(
            descriptor: childDescriptor,
            node: node,
            lifecycle: lifecycle,
            embedRecord: embedRecord,
            allEmbedRecords: allEmbedRecords,
            actions: actions,
            showsActions: false
        ))
    }
}

private struct AppSkillUseComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "openmates", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct RepositoryComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "code", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct PcbSchematicComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "electronics", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct ElectronicsComponentComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "electronics", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct FitnessLocationComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "fitness", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct FitnessClassComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "fitness", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct SocialPostComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "social_media", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct WeatherDayComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "weather", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct FocusModeComposerPreview: View {
    let node: ComposerNodeV1
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String
    var body: some View {
        AppleComposerSummaryCard(appId: "openmates", title: title, lifecycle: lifecycle, lifecycleLabel: lifecycleLabel)
    }
    private var title: String { node.display?.title ?? AppStrings.uploadProgressProcessing }
}

private struct AppleComposerSummaryCard: View {
    let appId: String
    let title: String
    let lifecycle: AppleComposerEmbedLifecycleState
    let lifecycleLabel: String

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: .spacing5) {
                AppIconView(appId: appId, size: 60)
                Text(title)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                lifecycleContent
            }
            .padding(.horizontal, .spacing10)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            EmbedBasicInfoBar(
                appId: appId,
                skillIconName: AppIconView.iconName(forAppId: appId),
                title: title,
                subtitle: lifecycleLabel,
                faviconURL: nil,
                showSkillIcon: false
            )
        }
        .frame(width: AppleComposerPreviewMetrics.width, height: AppleComposerPreviewMetrics.height)
        .background(lifecycle == .error ? Color.error.opacity(0.1) : Color.grey25)
        .clipShape(RoundedRectangle(cornerRadius: AppleComposerPreviewMetrics.cornerRadius))
        .overlay {
            if lifecycle == .error {
                RoundedRectangle(cornerRadius: AppleComposerPreviewMetrics.cornerRadius)
                    .stroke(Color.error, lineWidth: 1)
            }
        }
        .shadow(color: .black.opacity(0.16), radius: 24, x: 0, y: 8)
        .shadow(color: .black.opacity(0.10), radius: 6, x: 0, y: 2)
    }

    @ViewBuilder
    private var lifecycleContent: some View {
        switch lifecycle {
        case .draft, .uploading, .processing, .transcribing, .correcting:
            ProgressView()
                .tint(Color.buttonPrimary)
        case .finished:
            Icon("check", size: 22)
                .foregroundStyle(Color.buttonPrimary)
        case .error:
            Icon("warning", size: 22)
                .foregroundStyle(Color.error)
        case .cancelled:
            Icon("close", size: 22)
                .foregroundStyle(Color.fontTertiary)
        }
    }
}
