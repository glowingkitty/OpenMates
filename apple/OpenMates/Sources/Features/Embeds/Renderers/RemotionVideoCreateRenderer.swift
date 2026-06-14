// Remotion videos.create renderer - displays generated video artifacts, timeline,
// and editable source code for code-backed video embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/videos/VideoCreateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoCreateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoTimeline.svelte
// CSS:     frontend/packages/ui/src/components/embeds/videos/VideoCreateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoCreateEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import AVKit
import Foundation
import SwiftUI

struct RemotionVideoCreateRenderer: View {
    let embedId: String?
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    @State private var selectedView: RemotionVideoCreateViewMode = .video
    @State private var actionError: String?

    private let model: RemotionVideoCreateModel

    private var currentStatusText: String {
        switch model.status {
        case "rendering": return AppStrings.videoCreateStatusRendering
        case "processing": return AppStrings.videoCreateStatusProcessing
        case "cancelled": return AppStrings.videoCreateStatusCancelled
        case "needs_rerender": return AppStrings.videoCreateStatusNeedsRerender
        case "error": return model.errorMessage ?? AppStrings.videoCreateStatusError
        default: return "\(model.durationLabel) · \(model.resolutionLabel)"
        }
    }

    init(embedId: String? = nil, data: [String: AnyCodable]?, mode: EmbedDisplayMode) {
        self.embedId = embedId
        self.data = data
        self.mode = mode
        self.model = RemotionVideoCreateModel(data: data)
    }

    var body: some View {
        switch mode {
        case .preview:
            preview
        case .fullscreen:
            fullscreen
        }
    }

    private var preview: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if model.isFinished, model.hasThumbnail {
                ZStack {
                    thumbnailView
                    Icon("play", size: 34)
                        .foregroundStyle(.white.opacity(0.92))
                        .shadow(color: .black.opacity(0.35), radius: 4, x: 0, y: 2)
                    VStack {
                        Spacer()
                        HStack {
                            Spacer()
                            Text(model.durationLabel)
                                .font(.omTiny)
                                .fontWeight(.medium)
                                .foregroundStyle(.white)
                                .padding(.horizontal, .spacing3)
                                .padding(.vertical, .spacing1)
                                .background(.black.opacity(0.68))
                                .clipShape(RoundedRectangle(cornerRadius: .radius2))
                        }
                        .padding(.spacing3)
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
            } else if model.status == "error" {
                statusPlaceholder(icon: "videos", text: model.errorMessage ?? AppStrings.videoCreateStatusError, color: Color.error)
            } else {
                VStack(alignment: .leading, spacing: .spacing3) {
                    HStack(alignment: .center, spacing: .spacing3) {
                        Text(model.filename)
                            .font(.omSmall)
                            .fontWeight(.medium)
                            .foregroundStyle(Color.fontPrimary)
                            .lineLimit(1)
                        Spacer(minLength: 0)
                        Text(currentStatusText)
                            .font(.omTiny)
                            .fontWeight(.medium)
                            .foregroundStyle(Color.fontTertiary)
                            .lineLimit(1)
                    }
                    RemotionTimelinePreview(manifest: model.manifest, compact: true)
                }
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var fullscreen: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            VStack(alignment: .leading, spacing: .spacing2) {
                Text(model.filename)
                    .font(.omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                Text(AppStrings.videoCreateHeaderSubtitle(version: String(model.sourceVersion), status: currentStatusText))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }

            OMSegmentedControl(
                items: [
                    .init(id: .video, title: AppStrings.videoCreateVideo),
                    .init(id: .timeline, title: AppStrings.videoCreateTimeline),
                    .init(id: .code, title: AppStrings.videoCreateCode),
                ],
                selection: $selectedView
            )

            actionBar

            if let actionError {
                Text(actionError)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
            }

            switch selectedView {
            case .video:
                fullscreenVideo
                RemotionTimelinePreview(manifest: model.manifest, compact: false)
            case .timeline:
                RemotionTimelinePreview(manifest: model.manifest, compact: false)
            case .code:
                ScrollView([.vertical, .horizontal]) {
                    Text(model.source.isEmpty ? AppStrings.videoCreateStatusProcessing : model.source)
                        .font(.omXs)
                        .foregroundStyle(Color.fontPrimary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.spacing5)
                }
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
                .overlay(
                    RoundedRectangle(cornerRadius: .radius6)
                        .stroke(Color.grey20, lineWidth: 1)
                )
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var actionBar: some View {
        HStack(spacing: .spacing3) {
            if model.status == "rendering" {
                Button(AppStrings.videoCreateActionStopRender) {
                    Task { await postAction(path: "/v1/videos/remotion/\(embedId ?? "")/render/current/stop", sourceVersion: nil) }
                }
                .buttonStyle(OMSecondaryButtonStyle())
                .disabled(embedId == nil)
            }

            Button(AppStrings.videoCreateActionRerender) {
                Task { await postAction(path: "/v1/videos/remotion/\(embedId ?? "")/render", sourceVersion: nil) }
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(embedId == nil)

            Button(AppStrings.videoCreateActionRenderThisVersion) {
                Task { await postAction(path: "/v1/videos/remotion/\(embedId ?? "")/render", sourceVersion: model.sourceVersion) }
            }
            .buttonStyle(OMSecondaryButtonStyle())
            .disabled(embedId == nil)

            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private var fullscreenVideo: some View {
        if let videoS3URL = model.videoS3URL, let aesKey = model.aesKey, let aesNonce = model.aesNonce {
            EncryptedVideoPlayer(s3Url: videoS3URL, aesKey: aesKey, aesNonce: aesNonce, filename: model.filename)
                .frame(minHeight: 240)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
        } else if model.hasThumbnail {
            thumbnailView
                .frame(minHeight: 240)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
                .overlay(statusOverlay(AppStrings.videoCreateStatusUnavailable))
        } else {
            statusPlaceholder(icon: "videos", text: currentStatusText, color: Color.fontTertiary)
                .frame(minHeight: 240)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
        }
    }

    @ViewBuilder
    private var thumbnailView: some View {
        if let thumbnailS3URL = model.thumbnailS3URL, let aesKey = model.aesKey, let aesNonce = model.aesNonce {
            EncryptedImageView(s3Url: thumbnailS3URL, aesKey: aesKey, aesNonce: aesNonce, contentMode: .fill)
        } else if let thumbnailURL = model.thumbnailURL, let url = URL(string: thumbnailURL) {
            CachedRemoteImage(url: url) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: { Color.grey20 }
        } else {
            Color.grey20.overlay(Icon("videos", size: 32).foregroundStyle(Color.grey60))
        }
    }

    private func statusPlaceholder(icon: String, text: String, color: Color) -> some View {
        VStack(spacing: .spacing3) {
            Icon(icon, size: 30)
                .foregroundStyle(color)
            Text(text)
                .font(.omSmall)
                .fontWeight(.medium)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func statusOverlay(_ text: String) -> some View {
        Text(text)
            .font(.omSmall)
            .fontWeight(.medium)
            .foregroundStyle(.white)
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(.black.opacity(0.38))
    }

    @MainActor
    private func postAction(path: String, sourceVersion: Int?) async {
        guard embedId != nil else { return }
        do {
            var body: [String: Any] = [:]
            if let chatId = model.chatId { body["chat_id"] = chatId }
            if let sourceVersion { body["source_version"] = sourceVersion }
            let _: Data = try await APIClient.shared.request(.post, path: path, body: body)
            actionError = nil
        } catch {
            actionError = error.localizedDescription
        }
    }
}

private enum RemotionVideoCreateViewMode: Hashable {
    case video
    case timeline
    case code
}

private struct RemotionVideoCreateModel {
    let filename: String
    let status: String
    let source: String
    let sourceVersion: Int
    let errorMessage: String?
    let aesKey: String?
    let aesNonce: String?
    let thumbnailURL: String?
    let thumbnailS3URL: String?
    let videoS3URL: String?
    let chatId: String?
    let manifest: RemotionTimelineManifest

    init(data: [String: AnyCodable]?) {
        filename = Self.string(data, ["filename", "title"]) ?? "Composition.tsx"
        status = Self.string(data, ["status"]) ?? "processing"
        source = Self.string(data, ["remotion_source", "source"]) ?? ""
        sourceVersion = Self.int(data, ["current_source_version", "source_version"]) ?? 1
        errorMessage = Self.string(data, ["error", "error_message"])
        aesKey = Self.string(data, ["aes_key"])
        aesNonce = Self.string(data, ["aes_nonce"])
        thumbnailURL = Self.string(data, ["thumbnail_url"])
        chatId = Self.string(data, ["chat_id"])

        let s3BaseURL = Self.string(data, ["s3_base_url"])
        thumbnailS3URL = Self.mediaS3URL(data: data, baseURL: s3BaseURL, fileKey: "thumbnail")
        videoS3URL = Self.mediaS3URL(data: data, baseURL: s3BaseURL, fileKey: "original")
        manifest = RemotionTimelineManifest(source: source)
    }

    var isFinished: Bool { status == "finished" }
    var hasThumbnail: Bool { thumbnailS3URL != nil || thumbnailURL != nil }
    var durationLabel: String { "\(manifest.durationSeconds)s" }
    var resolutionLabel: String { "\(manifest.width)x\(manifest.height)" }

    private static func string(_ data: [String: AnyCodable]?, _ keys: [String]) -> String? {
        for key in keys {
            if let value = data?[key]?.value as? String, !value.isEmpty { return value }
        }
        return nil
    }

    private static func int(_ data: [String: AnyCodable]?, _ keys: [String]) -> Int? {
        for key in keys {
            if let value = data?[key]?.value as? Int { return value }
            if let value = data?[key]?.value as? Double { return Int(value) }
            if let value = data?[key]?.value as? String, let intValue = Int(value) { return intValue }
        }
        return nil
    }

    private static func mediaS3URL(data: [String: AnyCodable]?, baseURL: String?, fileKey: String) -> String? {
        guard let files = data?["files"]?.value as? [String: Any],
              let file = files[fileKey] as? [String: Any],
              let s3Key = file["s3_key"] as? String,
              !s3Key.isEmpty else { return nil }
        guard !s3Key.hasPrefix("http://"), !s3Key.hasPrefix("https://") else { return s3Key }
        guard let baseURL, !baseURL.isEmpty else { return nil }
        return baseURL.hasSuffix("/") ? "\(baseURL)\(s3Key)" : "\(baseURL)/\(s3Key)"
    }
}

private struct RemotionTimelineManifest {
    let title: String
    let durationSeconds: Int
    let width: Int
    let height: Int
    let layers: [RemotionTimelineLayer]

    init(source: String) {
        let fps = Self.firstInt(in: source, pattern: #"fps\s*[:=]\s*(\d+)"#) ?? 30
        let frames = Self.firstInt(in: source, pattern: #"durationInFrames\s*[:=]\s*(\d+)"#) ?? 150
        title = Self.firstString(in: source, pattern: #"title\s*[:=]\s*[\"']([^\"']+)[\"']"#) ?? "Remotion"
        durationSeconds = max(1, Int(ceil(Double(frames) / Double(max(1, fps)))))
        width = Self.firstInt(in: source, pattern: #"width\s*[:=]\s*(\d+)"#) ?? 1920
        height = Self.firstInt(in: source, pattern: #"height\s*[:=]\s*(\d+)"#) ?? 1080
        layers = Self.componentLayers(from: source, durationSeconds: durationSeconds)
    }

    private static func componentLayers(from source: String, durationSeconds: Int) -> [RemotionTimelineLayer] {
        let names = matches(in: source, pattern: #"<([A-Z][A-Za-z0-9]*)\b"#)
            .filter { !["AbsoluteFill", "Sequence", "Img", "Audio", "Video"].contains($0) }
        let uniqueNames = Array(NSOrderedSet(array: names)).compactMap { $0 as? String }.prefix(6)
        guard !uniqueNames.isEmpty else {
            return [RemotionTimelineLayer(name: "Composition", start: 0, duration: durationSeconds)]
        }
        let segment = max(1, durationSeconds / max(1, uniqueNames.count))
        return uniqueNames.enumerated().map { index, name in
            RemotionTimelineLayer(name: name, start: index * segment, duration: index == uniqueNames.count - 1 ? max(1, durationSeconds - index * segment) : segment)
        }
    }

    private static func firstInt(in source: String, pattern: String) -> Int? {
        guard let match = matches(in: source, pattern: pattern).first else { return nil }
        return Int(match)
    }

    private static func firstString(in source: String, pattern: String) -> String? {
        matches(in: source, pattern: pattern).first
    }

    private static func matches(in source: String, pattern: String) -> [String] {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(source.startIndex..<source.endIndex, in: source)
        return regex.matches(in: source, range: range).compactMap { match in
            guard match.numberOfRanges > 1,
                  let swiftRange = Range(match.range(at: 1), in: source) else { return nil }
            return String(source[swiftRange])
        }
    }
}

private struct RemotionTimelineLayer: Identifiable {
    var id: String { "\(name)-\(start)-\(duration)" }
    let name: String
    let start: Int
    let duration: Int
}

private struct RemotionTimelinePreview: View {
    let manifest: RemotionTimelineManifest
    let compact: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? .spacing2 : .spacing4) {
            HStack(spacing: .spacing3) {
                Text(manifest.title)
                    .font(compact ? .omXs : .omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
                Spacer(minLength: 0)
                Text("\(manifest.durationSeconds)s · \(manifest.width)x\(manifest.height)")
                    .font(.omTiny)
                    .foregroundStyle(Color.fontTertiary)
            }

            VStack(alignment: .leading, spacing: compact ? .spacing1 : .spacing2) {
                ForEach(manifest.layers) { layer in
                    HStack(spacing: .spacing3) {
                        Text(layer.name)
                            .font(.omTiny)
                            .fontWeight(.medium)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(1)
                            .frame(width: compact ? 72 : 120, alignment: .leading)
                        GeometryReader { geometry in
                            let total = max(1, manifest.durationSeconds)
                            let x = geometry.size.width * CGFloat(layer.start) / CGFloat(total)
                            let width = max(8, geometry.size.width * CGFloat(layer.duration) / CGFloat(total))
                            ZStack(alignment: .leading) {
                                Capsule().fill(Color.grey20)
                                Capsule()
                                    .fill(Color.buttonPrimary.opacity(0.78))
                                    .frame(width: width)
                                    .offset(x: x)
                            }
                        }
                        .frame(height: compact ? 8 : 14)
                    }
                }
            }
        }
        .padding(compact ? .spacing3 : .spacing5)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: compact ? .radius3 : .radius6))
    }
}

private struct EncryptedVideoPlayer: View {
    let s3Url: String
    let aesKey: String
    let aesNonce: String
    let filename: String

    @State private var temporaryURL: URL?
    @State private var loadError: String?

    var body: some View {
        Group {
            if let temporaryURL {
                VideoPlayerView(url: temporaryURL)
            } else if let loadError {
                Color.grey100.overlay(
                    Text(loadError)
                        .font(.omSmall)
                        .foregroundStyle(Color.error)
                        .padding(.spacing5)
                )
            } else {
                Color.grey100.overlay(ProgressView())
            }
        }
        .task(id: s3Url) { await loadVideo() }
        .onDisappear { cleanup() }
    }

    private func loadVideo() async {
        do {
            let data = try await S3MediaClient.shared.fetchAndDecrypt(s3Url: s3Url, aesKeyHex: aesKey, aesNonceHex: aesNonce)
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent("openmates-remotion-video", isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let sanitized = filename.replacingOccurrences(of: "/", with: "-")
            let outputName = URL(fileURLWithPath: sanitized).pathExtension.isEmpty ? "\(sanitized).mp4" : sanitized
            let url = directory.appendingPathComponent("\(UUID().uuidString)-\(outputName)")
            try data.write(to: url, options: .atomic)
            temporaryURL = url
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func cleanup() {
        if let temporaryURL {
            try? FileManager.default.removeItem(at: temporaryURL)
        }
    }
}
