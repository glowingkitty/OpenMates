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
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open
import SwiftUI

struct RemotionVideoCreateRenderer: View {
    @Environment(\.recipientMediaContext) private var recipientMediaContext
    let embedId: String?
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    @State private var selectedView: RemotionVideoCreateViewMode = .video
    @State private var actionError: String?
    @State private var videoPlayer: AVPlayer?
    @State private var currentTime: Double = 0

    private let model: RemotionVideoCreateModel
    private var publicVideoURL: URL? {
        guard let raw = model.publicVideoURL else { return nil }
        if let recipientMediaContext { return recipientMediaContext.resolvedPublicURL(raw.relativeString) }
        return URL(string: raw.relativeString, relativeTo: ServerProfile.current().webBaseURL)?.absoluteURL
    }

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
            if model.isFinished, model.hasThumbnail || publicVideoURL != nil {
                ZStack {
                    if model.hasThumbnail {
                        thumbnailView
                    } else {
                        Color.grey10
                    }
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
                .clipShape(RoundedRectangle(cornerRadius: .radius2))
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
        VStack(alignment: .leading, spacing: 16) {
            toolbar

            if let actionError {
                Text(actionError)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
            }

            switch selectedView {
            case .video:
                fullscreenVideo
                controlsBar
                RemotionTimelinePreview(manifest: model.manifest, compact: false, currentTime: currentTime, onSeek: seek)
            case .timeline:
                RemotionTimelinePreview(manifest: model.manifest, compact: false, currentTime: currentTime, onSeek: seek)
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
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .onReceive(Timer.publish(every: 0.25, on: .main, in: .common).autoconnect()) { _ in
            guard let seconds = videoPlayer?.currentTime().seconds, seconds.isFinite else { return }
            currentTime = seconds
        }
        .onDisappear { videoPlayer?.pause(); videoPlayer = nil }
    }

    private var toolbar: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                toolbarTab(.video, title: AppStrings.videoCreateVideo)
                toolbarTab(.timeline, title: AppStrings.videoCreateTimeline)
                Spacer(minLength: 0)
            }
            HStack(spacing: 8) {
                toolbarTab(.code, title: AppStrings.videoCreateCode)
                Spacer(minLength: 0)
                if recipientMediaContext == nil {
                    Button(AppStrings.videoCreateActionRerender) {
                        Task { await postAction(path: "/v1/videos/remotion/\(embedId ?? "")/render", sourceVersion: nil) }
                    }
                    .buttonStyle(RemotionToolbarButtonStyle())
                    .disabled(embedId == nil)
                    .accessibilityIdentifier("video-create-rerender")
                }
            }
            if recipientMediaContext == nil {
                HStack(spacing: 8) {
                if model.status == "rendering" {
                    Button(AppStrings.videoCreateActionStopRender) {
                        Task { await postAction(path: "/v1/videos/remotion/\(embedId ?? "")/render/current/stop", sourceVersion: nil) }
                    }
                    .buttonStyle(RemotionToolbarButtonStyle())
                    .disabled(embedId == nil)
                }
                Button(AppStrings.videoCreateActionRenderThisVersion) {
                    Task { await postAction(path: "/v1/videos/remotion/\(embedId ?? "")/render", sourceVersion: model.sourceVersion) }
                }
                .buttonStyle(RemotionToolbarButtonStyle())
                .disabled(embedId == nil)
                .accessibilityIdentifier("video-create-render-version")
                Spacer(minLength: 0)
                }
            }
        }
    }

    private func toolbarTab(_ tab: RemotionVideoCreateViewMode, title: String) -> some View {
        Button(title) { selectedView = tab }
            .buttonStyle(RemotionToolbarButtonStyle(active: selectedView == tab))
            .accessibilityIdentifier("video-create-tab-\(tab)")
            .accessibilityValue(selectedView == tab ? "selected" : "unselected")
    }

    private var controlsBar: some View {
        HStack(spacing: 12) {
            Button((videoPlayer?.rate ?? 0) > 0 ? "Pause" : "Play") {
                guard let videoPlayer else { return }
                if videoPlayer.rate > 0 { videoPlayer.pause() } else { videoPlayer.play() }
            }
            .buttonStyle(RemotionToolbarButtonStyle())
            .disabled(videoPlayer == nil)
            .accessibilityIdentifier("video-create-playback")
            Text("\(Self.timestamp(currentTime)) / \(Self.timestamp(Double(model.manifest.durationSeconds)))")
                .font(.omP)
                .fontWeight(.semibold)
                .monospacedDigit()
        }
    }

    private func seek(_ seconds: Double) {
        videoPlayer?.seek(to: CMTime(seconds: seconds, preferredTimescale: 600))
        currentTime = seconds
    }

    private static func timestamp(_ seconds: Double) -> String {
        let value = max(0, Int(seconds))
        return String(format: "%d:%02d", value / 60, value % 60)
    }

    @ViewBuilder
    private var fullscreenVideo: some View {
        if let videoS3URL = model.videoS3URL, let aesKey = model.aesKey,
           model.aesNonce != nil || model.videoEncryption != nil {
            EncryptedVideoPlayer(
                s3Url: videoS3URL, aesKey: aesKey, aesNonce: model.aesNonce,
                encryption: model.videoEncryption, filename: model.filename,
                onPlayerReady: { videoPlayer = $0 }
            )
                .frame(minHeight: 240)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
        } else if let publicVideoURL = publicVideoURL {
            RemotionPlayerView(url: publicVideoURL, onPlayerReady: { videoPlayer = $0 })
                .frame(minHeight: 240)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
        } else if model.hasThumbnail {
            thumbnailView
                .frame(minHeight: 240)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
                .overlay(statusOverlay(AppStrings.videoCreateStatusUnavailable))
        } else {
            Color.black
                .frame(minHeight: 240)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
        }
    }

    @ViewBuilder
    private var thumbnailView: some View {
        if let thumbnailS3URL = model.thumbnailS3URL, let aesKey = model.aesKey,
           model.aesNonce != nil || model.thumbnailEncryption != nil {
            EncryptedImageView(
                s3Url: thumbnailS3URL, s3Key: nil, aesKey: aesKey, aesNonce: model.aesNonce,
                encryption: model.thumbnailEncryption, contentMode: .fill
            )
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
            guard recipientMediaContext == nil else { return }
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

private struct RemotionToolbarButtonStyle: ButtonStyle {
    var active = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omP)
            .fontWeight(.semibold)
            .foregroundStyle(active ? Color.grey0 : Color.fontPrimary)
            .padding(.horizontal, 16)
            .frame(minHeight: 40)
            .background(active ? Color.buttonPrimary : Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .contentShape(RoundedRectangle(cornerRadius: 10))
            .overlay {
                RoundedRectangle(cornerRadius: 10)
                    .stroke(Color.grey25, lineWidth: active ? 0 : 1)
                    .allowsHitTesting(false)
            }
            .shadow(color: .black.opacity(0.12), radius: 4, y: 2)
            .opacity(configuration.isPressed ? 0.82 : 1)
    }
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
    let publicVideoURL: URL?
    let thumbnailS3URL: String?
    let videoS3URL: String?
    let thumbnailEncryption: String?
    let videoEncryption: String?
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
        let publicVideo = Self.string(data, ["video_url", "videoUrl"])
        publicVideoURL = publicVideo.flatMap { URL(string: $0) }
        chatId = Self.string(data, ["chat_id"])

        let s3BaseURL = Self.string(data, ["s3_base_url"])
        thumbnailS3URL = Self.mediaS3URL(data: data, baseURL: s3BaseURL, fileKey: "thumbnail")
        videoS3URL = Self.mediaS3URL(data: data, baseURL: s3BaseURL, fileKey: "original")
        thumbnailEncryption = Self.mediaEncryption(data: data, fileKey: "thumbnail")
        videoEncryption = Self.mediaEncryption(data: data, fileKey: "original")
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

    private static func mediaEncryption(data: [String: AnyCodable]?, fileKey: String) -> String? {
        guard let files = data?["files"]?.value as? [String: Any],
              let file = files[fileKey] as? [String: Any] else { return nil }
        return file["encryption"] as? String
    }
}

private struct RemotionTimelineManifest {
    let title: String
    let durationSeconds: Int
    let durationInFrames: Int
    let fps: Int
    let width: Int
    let height: Int
    let tracks: [RemotionTimelineTrack]

    init(source: String) {
        let composition = Self.groups(in: source, pattern: #"<Composition\b([^>]*)>"#).first?.first ?? source
        let parsedFPS = Self.value(in: composition, pattern: #"\bfps=\{?(\d+)"#) ?? 30
        fps = parsedFPS
        let frames = Self.value(in: composition, pattern: #"\bdurationInFrames=\{?(\d+)"#) ?? 300
        durationInFrames = frames
        title = Self.capture(in: composition, pattern: #"\bid=[\"']([^\"']+)[\"']"#) ?? "Untitled"
        durationSeconds = max(1, Int(ceil(Double(frames) / Double(max(1, parsedFPS)))))
        width = Self.value(in: composition, pattern: #"\bwidth=\{?(\d+)"#) ?? 1920
        height = Self.value(in: composition, pattern: #"\bheight=\{?(\d+)"#) ?? 1080

        var visual = Self.groups(in: source, pattern: #"<Sequence\b([^>]*)>([\s\S]*?)</Sequence>"#)
            .compactMap { parts -> RemotionTimelineLayer? in
                guard parts.count == 2 else { return nil }
                let name = Self.capture(in: parts[0], pattern: #"\bname=[\"']([^\"']+)[\"']"#)
                    ?? Self.capture(in: parts[1], pattern: #"<([A-Z][A-Za-z0-9]*)\b"#)
                    ?? "Scene"
                return .init(name: Self.readable(name),
                             start: Self.value(in: parts[0], pattern: #"\bfrom=\{?(\d+)"#) ?? 0,
                             duration: Self.value(in: parts[0], pattern: #"\bdurationInFrames=\{?(\d+)"#) ?? frames,
                             color: Color(hex: 0x3B82F6))
            }
        if visual.isEmpty {
            visual = [.init(name: Self.readable(title), start: 0, duration: frames, color: Color(hex: 0x3B82F6))]
        }
        var groups: [[RemotionTimelineLayer]] = []
        for layer in visual {
            if let index = groups.firstIndex(where: { group in
                group.allSatisfy { layer.start >= $0.start + $0.duration || layer.start + layer.duration <= $0.start }
            }) {
                groups[index].append(layer)
            } else {
                groups.append([layer])
            }
        }
        let colors: [UInt32] = [0x3B82F6, 0x8B5CF6, 0xEC4899, 0xF59E0B]
        var parsed: [RemotionTimelineTrack] = groups.enumerated().map { index, group in
            RemotionTimelineTrack(
                name: index == 0 ? (groups.count == 1 ? "Scenes" : "Background") : "Layer \(index + 1)",
                isAudio: false,
                layers: group.sorted { $0.start < $1.start }.map {
                    .init(name: $0.name, start: $0.start, duration: $0.duration,
                          color: Color(hex: colors[index % colors.count]))
                }
            )
        }
        let audio = Self.groups(in: source, pattern: #"<Audio\b([^>]*)/?>"#).compactMap { parts -> RemotionTimelineLayer? in
            guard let attrs = parts.first,
                  let src = Self.capture(in: attrs, pattern: #"\bsrc=[\"']([^\"']+)[\"']"#) else { return nil }
            return .init(name: src.split(separator: "/").last.map(String.init) ?? "Audio",
                         start: 0, duration: frames, color: Color(hex: 0x22C55E))
        }
        if !audio.isEmpty {
            parsed.append(RemotionTimelineTrack(name: "Audio", isAudio: true, layers: audio))
        }
        tracks = parsed
    }

    private static func readable(_ name: String) -> String {
        let spaced = name.replacingOccurrences(of: "([a-z])([A-Z])", with: "$1 $2", options: .regularExpression)
            .replacingOccurrences(of: "([A-Z])([A-Z][a-z])", with: "$1 $2", options: .regularExpression)
            .lowercased()
        return spaced.prefix(1).uppercased() + String(spaced.dropFirst())
    }

    private static func value(in source: String, pattern: String) -> Int? {
        capture(in: source, pattern: pattern).flatMap(Int.init)
    }

    private static func capture(in source: String, pattern: String) -> String? {
        groups(in: source, pattern: pattern).first?.first
    }

    private static func groups(in source: String, pattern: String) -> [[String]] {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(source.startIndex..<source.endIndex, in: source)
        return regex.matches(in: source, range: range).compactMap { match in
            let values = (1..<match.numberOfRanges).compactMap { index -> String? in
                guard let swiftRange = Range(match.range(at: index), in: source) else { return nil }
                return String(source[swiftRange])
            }
            return values.isEmpty ? nil : values
        }
    }
}

private struct RemotionTimelineTrack: Identifiable {
    var id: String { name }
    let name: String
    let isAudio: Bool
    let layers: [RemotionTimelineLayer]
}

private struct RemotionTimelineLayer: Identifiable {
    var id: String { "\(name)-\(start)-\(duration)" }
    let name: String
    let start: Int
    let duration: Int
    let color: Color
}

private struct RemotionTimelinePreview: View {
    let manifest: RemotionTimelineManifest
    let compact: Bool
    var currentTime: Double = 0
    var onSeek: ((Double) -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 3 : 4) {
            if !compact {
                HStack(spacing: 0) {
                    Color.clear.frame(width: 90, height: 18)
                    GeometryReader { ruler in
                        ForEach(Array(stride(from: 0, through: manifest.durationSeconds,
                                             by: manifest.durationSeconds <= 15 ? 2 : 5)), id: \.self) { second in
                            Text("\(second)s")
                                .font(.system(size: 10))
                                .foregroundStyle(Color.grey50)
                                .position(x: ruler.size.width * CGFloat(second) / CGFloat(max(1, manifest.durationSeconds)), y: 7)
                        }
                    }
                    .frame(height: 18)
                }
            }
            ForEach(manifest.tracks) { track in
                HStack(spacing: 0) {
                    if !compact {
                        HStack(spacing: 5) {
                            Text(track.isAudio ? "♫" : "▪").foregroundStyle(Color.grey40)
                            Text(track.name).lineLimit(1)
                        }
                        .font(.system(size: 11))
                        .foregroundStyle(Color.grey60)
                        .frame(width: 90, alignment: .leading)
                    }
                    GeometryReader { geometry in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 4).fill(Color.grey10)
                            ForEach(track.layers) { layer in
                                let total = CGFloat(max(1, manifest.durationInFrames))
                                let x = geometry.size.width * CGFloat(layer.start) / total
                                let width = max(2, geometry.size.width * CGFloat(layer.duration) / total)
                                HStack(spacing: 2) {
                                    Text(layer.name)
                                        .font(.system(size: compact ? 9 : 10, weight: .medium))
                                        .lineLimit(1)
                                    if !compact && width > 48 {
                                        Spacer(minLength: 0)
                                        Text("\(max(1, layer.duration / max(1, manifest.fps)))s")
                                            .font(.system(size: 9))
                                            .opacity(0.75)
                                    }
                                }
                                .foregroundStyle(.white)
                                .padding(.horizontal, 6)
                                .frame(width: width, height: compact ? 16 : 24)
                                .background(layer.color)
                                .clipShape(RoundedRectangle(cornerRadius: 3))
                                .offset(x: x)
                            }
                            if currentTime > 0 {
                                Rectangle().fill(Color.buttonPrimary).frame(width: 2)
                                    .offset(x: geometry.size.width * CGFloat(currentTime) / CGFloat(max(1, manifest.durationSeconds)))
                            }
                        }
                        .contentShape(Rectangle())
                        .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                            guard let onSeek else { return }
                            let ratio = min(1, max(0, value.location.x / max(1, geometry.size.width)))
                            onSeek(Double(ratio) * Double(manifest.durationSeconds))
                        })
                    }
                    .frame(height: compact ? 20 : 28)
                }
            }
        }
        .padding(.vertical, 8)
    }
}

private struct EncryptedVideoPlayer: View {
    @Environment(\.recipientMediaContext) private var recipientMediaContext
    let s3Url: String
    let aesKey: String
    let aesNonce: String?
    let encryption: String?
    let filename: String
    let onPlayerReady: (AVPlayer) -> Void

    @State private var recipientPlayer: AVPlayer?
    @State private var temporaryURL: URL?
    @State private var loadError: String?

    var body: some View {
        Group {
            if let recipientPlayer {
                VideoPlayer(player: recipientPlayer)
            } else if let temporaryURL {
                RemotionPlayerView(url: temporaryURL, onPlayerReady: onPlayerReady)
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
            let data = try await RecipientMediaContext.fetchAndDecrypt(context: recipientMediaContext,
                s3Url: s3Url, aesKeyHex: aesKey, aesNonceHex: aesNonce, encryption: encryption
            )
            if let recipientMediaContext {
                let player = try recipientMediaContext.player(data: data)
                recipientPlayer = player
                onPlayerReady(player)
                return
            }
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
        recipientPlayer?.pause()
        recipientPlayer = nil
        if let temporaryURL {
            try? FileManager.default.removeItem(at: temporaryURL)
        }
    }
}

private struct RemotionPlayerView: View {
    @Environment(\.recipientMediaContext) private var recipientMediaContext
    let url: URL
    let onPlayerReady: (AVPlayer) -> Void
    @State private var player: AVPlayer?

    var body: some View {
        Group {
            if let player {
                VideoPlayer(player: player)
            } else {
                Color.black
            }
        }
        .task(id: url) {
            guard player == nil else { return }
            if let recipientMediaContext {
                do {
                    let newPlayer = try await recipientMediaContext.player(url: url)
                    try recipientMediaContext.checkCurrent()
                    player = newPlayer
                    onPlayerReady(newPlayer)
                } catch { player = nil }
            } else {
                let newPlayer = AVPlayer(url: url)
                player = newPlayer
                onPlayerReady(newPlayer)
            }
        }
        .onDisappear { player?.pause(); player = nil }
    }
}
