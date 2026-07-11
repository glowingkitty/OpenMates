// Media embed renderers — video, image, audio, PDF.
// Downloads and decrypts S3-stored media via S3MediaClient.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/music/MusicGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/music/MusicGenerateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, GradientTokens.generated.swift,
//          SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import PDFKit
import UIKit
import QuickLook
#elseif os(macOS)
import AppKit
import QuickLookUI
#endif
import AVFoundation

// MARK: - Disk-backed public image loader

struct CachedRemoteImage<Content: View, Placeholder: View>: View {
    let url: URL
    let onFailure: (() -> Void)?
    let content: (Image) -> Content
    let placeholder: () -> Placeholder

    @State private var imageData: Data?

    init(
        url: URL,
        onFailure: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Image) -> Content,
        @ViewBuilder placeholder: @escaping () -> Placeholder
    ) {
        self.url = url
        self.onFailure = onFailure
        self.content = content
        self.placeholder = placeholder
    }

    var body: some View {
        Group {
            if let image = platformImage(from: imageData) {
                content(image)
            } else {
                placeholder()
            }
        }
        .task(id: url.absoluteString) {
            if let cached = await RemoteImageCache.shared.data(for: url.absoluteString) {
                imageData = cached
                return
            }
            do {
                imageData = try await RemoteImageCache.shared.fetch(url.absoluteString)
            } catch {
                onFailure?()
            }
        }
    }

    #if os(iOS)
    private func platformImage(from data: Data?) -> Image? {
        guard let data, let uiImage = UIImage(data: data) else { return nil }
        return Image(uiImage: uiImage)
    }
    #elseif os(macOS)
    private func platformImage(from data: Data?) -> Image? {
        guard let data, let nsImage = NSImage(data: data) else { return nil }
        return Image(nsImage: nsImage)
    }
    #endif
}

// MARK: - Encrypted image loader (shared by image embeds)

struct EncryptedImageView: View {
    let s3Url: String?
    let s3Key: String?
    let aesKey: String?
    let aesNonce: String?
    let contentMode: ContentMode

    @State private var imageData: Data?
    @State private var isLoading = true
    @State private var error: String?

    var body: some View {
        Group {
            if let imageData, let uiImage = platformImage(from: imageData) {
                Image(decorative: uiImage, scale: 1.0)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
            } else if isLoading {
                Color.grey20.overlay(ProgressView())
            } else if let error {
                Color.grey20.overlay(
                    VStack(spacing: .spacing2) {
                        Icon("image", size: 24)
                            .foregroundStyle(Color.error)
                        Text(error)
                            .font(.omTiny).foregroundStyle(Color.error)
                    }
                )
            }
        }
        .task { await loadImage() }
    }

    private func loadImage() async {
        guard let s3Url, let aesKey, let aesNonce else {
            error = "Missing encryption keys"
            isLoading = false
            return
        }
        do {
            imageData = try await S3MediaClient.shared.fetchAndDecrypt(
                s3Url: s3Url,
                aesKeyHex: aesKey,
                aesNonceHex: aesNonce,
                s3Key: s3Key
            )
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    #if os(iOS)
    private func platformImage(from data: Data) -> CGImage? {
        UIImage(data: data)?.cgImage
    }
    #elseif os(macOS)
    private func platformImage(from data: Data) -> CGImage? {
        NSImage(data: data)?.cgImage(forProposedRect: nil, context: nil, hints: nil)
    }
    #endif
}

@MainActor
final class NativeImagePreviewer: NSObject {
    static let shared = NativeImagePreviewer()

    private var previewURL: URL?

    func previewRemoteImage(_ url: URL, suggestedFilename: String? = nil) {
        Task {
            do {
                let (data, _) = try await URLSession.shared.data(from: url)
                previewImageData(data, suggestedFilename: suggestedFilename ?? url.lastPathComponent)
            } catch {
                ToastManager.shared.show(error.localizedDescription, type: .error)
            }
        }
    }

    func previewImageData(_ data: Data, suggestedFilename: String? = nil) {
        do {
            let fileURL = try writeTemporaryImage(data, suggestedFilename: suggestedFilename)
            previewURL = fileURL
            openPreview()
        } catch {
            ToastManager.shared.show(error.localizedDescription, type: .error)
        }
    }

    private func writeTemporaryImage(_ data: Data, suggestedFilename: String?) throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("openmates-image-preview", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let sanitizedName = (suggestedFilename?.isEmpty == false ? suggestedFilename! : "image")
            .replacingOccurrences(of: "/", with: "-")
        let hasExtension = URL(fileURLWithPath: sanitizedName).pathExtension.isEmpty == false
        let filename = hasExtension ? sanitizedName : "\(sanitizedName).jpg"
        let fileURL = directory.appendingPathComponent("\(UUID().uuidString)-\(filename)")
        try data.write(to: fileURL, options: .atomic)
        return fileURL
    }

    private func openPreview() {
        #if os(iOS)
        let controller = QLPreviewController()
        controller.dataSource = self
        controller.modalPresentationStyle = .fullScreen
        if let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
           let root = windowScene.windows.first(where: { $0.isKeyWindow })?.rootViewController {
            var presenter = root
            while let presented = presenter.presentedViewController {
                presenter = presented
            }
            presenter.present(controller, animated: true)
        }
        #elseif os(macOS)
        if let panel = QLPreviewPanel.shared() {
            panel.dataSource = self
            panel.delegate = self
            panel.reloadData()
            panel.makeKeyAndOrderFront(nil)
        } else if let previewURL {
            NSWorkspace.shared.open(previewURL)
        }
        #endif
    }
}

#if os(iOS)
extension NativeImagePreviewer: QLPreviewControllerDataSource {
    nonisolated func numberOfPreviewItems(in controller: QLPreviewController) -> Int {
        MainActor.assumeIsolated { previewURL == nil ? 0 : 1 }
    }

    nonisolated func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem {
        MainActor.assumeIsolated { previewURL! as NSURL }
    }
}
#elseif os(macOS)
extension NativeImagePreviewer: QLPreviewPanelDataSource, QLPreviewPanelDelegate {
    nonisolated func numberOfPreviewItems(in panel: QLPreviewPanel!) -> Int {
        MainActor.assumeIsolated { previewURL == nil ? 0 : 1 }
    }

    nonisolated func previewPanel(_ panel: QLPreviewPanel!, previewItemAt index: Int) -> QLPreviewItem! {
        MainActor.assumeIsolated { previewURL! as NSURL }
    }
}
#endif

struct TappableEncryptedImageView: View {
    let s3Url: String?
    let s3Key: String?
    let aesKey: String?
    let aesNonce: String?
    let filename: String?

    @State private var imageData: Data?
    @State private var isLoading = true
    @State private var error: String?

    var body: some View {
        Group {
            if let imageData, let image = platformImage(from: imageData) {
                Image(decorative: image, scale: 1.0)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
                    .contentShape(Rectangle())
                    .onTapGesture {
                        NativeImagePreviewer.shared.previewImageData(imageData, suggestedFilename: filename)
                    }
            } else if isLoading {
                Color.grey20.overlay(ProgressView())
            } else if let error {
                Color.grey20.overlay(
                    VStack(spacing: .spacing2) {
                        Icon("image", size: 24)
                            .foregroundStyle(Color.error)
                        Text(error)
                            .font(.omTiny).foregroundStyle(Color.error)
                    }
                )
            }
        }
        .task { await loadImage() }
        .help(Text(LocalizationManager.shared.text("embeds.image_search.open_image")))
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel(LocalizationManager.shared.text("embeds.image_search.open_image"))
    }

    private func loadImage() async {
        guard let s3Url, let aesKey, let aesNonce else {
            error = "Missing encryption keys"
            isLoading = false
            return
        }
        do {
            imageData = try await S3MediaClient.shared.fetchAndDecrypt(
                s3Url: s3Url,
                aesKeyHex: aesKey,
                aesNonceHex: aesNonce,
                s3Key: s3Key
            )
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    #if os(iOS)
    private func platformImage(from data: Data) -> CGImage? {
        UIImage(data: data)?.cgImage
    }
    #elseif os(macOS)
    private func platformImage(from data: Data) -> CGImage? {
        NSImage(data: data)?.cgImage(forProposedRect: nil, context: nil, hints: nil)
    }
    #endif
}

// MARK: - Video

struct VideoRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Video" }
    private var thumbnailUrl: String? { data?["thumbnail_url"]?.value as? String }
    private var channel: String? { data?["channel"]?.value as? String }
    private var duration: String? { data?["duration"]?.value as? String }
    private var url: String? { data?["url"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            ZStack {
                if let thumbnailUrl, let imgURL = URL(string: thumbnailUrl) {
                    CachedRemoteImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: { Color.grey20 }
                } else {
                    Color.grey20
                }

                // Play button overlay
                Icon("play", size: 36)
                    .foregroundStyle(.white.opacity(0.9))
                    .shadow(radius: 4)

                VStack {
                    Spacer()
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(title)
                                .font(.omXs).fontWeight(.medium)
                                .foregroundStyle(.white).lineLimit(2)
                            if let channel {
                                Text(channel)
                                    .font(.omTiny).foregroundStyle(.white.opacity(0.8))
                            }
                        }
                        Spacer()
                        if let duration {
                            Text(duration)
                                .font(.omTiny).fontWeight(.medium).foregroundStyle(.white)
                                .padding(.horizontal, .spacing2).padding(.vertical, 2)
                                .background(.black.opacity(0.6))
                                .clipShape(RoundedRectangle(cornerRadius: .radius1))
                        }
                    }
                    .padding(.spacing3)
                    .background(.linearGradient(colors: [.clear, .black.opacity(0.7)], startPoint: .top, endPoint: .bottom))
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                // In-app video player for direct URLs
                if let url, let videoURL = URL(string: url) {
                    VideoPlayerView(url: videoURL)
                        .frame(minHeight: 220)
                        .clipShape(RoundedRectangle(cornerRadius: .radius3))
                } else if let thumbnailUrl, let imgURL = URL(string: thumbnailUrl) {
                    CachedRemoteImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fit)
                    } placeholder: { ProgressView() }
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
                }

                Text(title).font(.omP).fontWeight(.medium).foregroundStyle(Color.fontPrimary)

                if let channel {
                    Text(channel).font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
                if let duration {
                    Label { Text(duration).font(.omSmall) } icon: { Icon("time", size: 14) }
                        .foregroundStyle(Color.fontTertiary)
                }
                if let url, let videoURL = URL(string: url) {
                    Link(AppStrings.openInBrowser, destination: videoURL)
                        .font(.omSmall).foregroundStyle(Color.buttonPrimary)
                }
            }
        }
    }
}

// MARK: - Generated music

struct MusicGenerateEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var payload: GeneratedMediaPayload { GeneratedMediaPayload(data) }

    var body: some View {
        switch mode {
        case .preview:
            HStack(spacing: .spacing6) {
                musicCover(size: 70)
                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(payload.modeLabel ?? GeneratedMediaText.generatedMusic)
                        .font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                        .lineLimit(1)
                    Text(payload.prompt ?? GeneratedMediaText.generatingMusic)
                        .font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(2)
                    mediaState
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.spacing6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .accessibilityIdentifier("music-generate-preview")

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing8) {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: .spacing10) { musicCover(size: 180); musicPlayer }
                    VStack(spacing: .spacing8) { musicCover(size: 180); musicPlayer }
                }
                .padding(.spacing10)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                .shadow(color: .black.opacity(0.12), radius: 15, x: 0, y: 8)

                VStack(alignment: .leading, spacing: .spacing6) {
                    if let prompt = payload.prompt { detail(GeneratedMediaText.prompt, prompt) }
                    detail(GeneratedMediaText.model, payload.model ?? "Lyria")
                    if let duration = payload.duration { detail(GeneratedMediaText.duration, Self.duration(duration)) }
                    if let generatedAt = payload.generatedAt { detail(GeneratedMediaText.generated, generatedAt) }
                    if let watermarking = payload.watermarking { detail(GeneratedMediaText.watermarking, watermarking) }
                }
                .padding(.spacing10)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                .shadow(color: .black.opacity(0.12), radius: 15, x: 0, y: 8)
            }
            .padding(.spacing10)
            .frame(maxWidth: 980, alignment: .leading)
            .accessibilityIdentifier("music-generate-fullscreen")
        }
    }

    @ViewBuilder private var mediaState: some View {
        if payload.status == "error" {
            Text(payload.error ?? GeneratedMediaText.musicError).font(.omXs).foregroundStyle(Color.error)
        } else if payload.status == "finished" {
            GeneratedAudioControl(payload: payload, compact: true)
        } else {
            Capsule().fill(Color.grey20).frame(maxWidth: .infinity).frame(height: 8)
        }
    }

    private var musicPlayer: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            Text(payload.modeLabel ?? GeneratedMediaText.generatedMusic)
                .font(.omH3).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
            if payload.status == "error" {
                Text(payload.error ?? GeneratedMediaText.musicError).font(.omSmall).foregroundStyle(Color.error)
            } else if payload.status == "finished" {
                GeneratedAudioControl(payload: payload, compact: false)
            } else {
                HStack(spacing: .spacing3) {
                    ProgressView().tint(Color.buttonPrimary)
                    Text(GeneratedMediaText.loadingAudio).font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func musicCover(size: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: .radius6)
            .fill(LinearGradient.appMusic)
            .frame(width: size, height: size)
            .overlay(Icon("music", size: size > 100 ? 72 : 34).foregroundStyle(Color.grey0))
            .shadow(color: .black.opacity(0.18), radius: 11, x: 0, y: 8)
    }

    private func detail(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(label).font(.omXs).fontWeight(.semibold).foregroundStyle(Color.fontSecondary)
            Text(value).font(.omP).foregroundStyle(Color.fontPrimary).textSelection(.enabled)
        }
    }

    fileprivate static func duration(_ seconds: Double) -> String {
        "\(Int(seconds) / 60):\(String(format: "%02d", Int(seconds) % 60))"
    }
}

// MARK: - Generated video

struct VideoGenerateEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var payload: GeneratedMediaPayload { GeneratedMediaPayload(data) }

    var body: some View {
        switch mode {
        case .preview:
            Group {
                if payload.status == "finished" {
                    GeneratedVideoPlayer(payload: payload)
                } else {
                    statusPlaceholder
                }
            }
            .padding(.spacing6)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityIdentifier("video-generate-preview")

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing8) {
                Group {
                    if payload.status == "finished" {
                        GeneratedVideoPlayer(payload: payload)
                    } else {
                        statusPlaceholder
                    }
                }
                .frame(minHeight: 240)
                .background(Color.grey100)
                .clipShape(RoundedRectangle(cornerRadius: .radius7))

                VStack(alignment: .leading, spacing: .spacing6) {
                    if let prompt = payload.prompt { detail(GeneratedMediaText.prompt, prompt) }
                    HStack(alignment: .top, spacing: .spacing10) {
                        if let model = payload.model { detail(GeneratedMediaText.model, model) }
                        if let resolution = payload.resolution { detail(GeneratedMediaText.resolution, resolution) }
                        if let duration = payload.duration { detail(GeneratedMediaText.duration, MusicGenerateEmbedRenderer.duration(duration)) }
                    }
                }
                .padding(.spacing8)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius7))
            }
            .padding(.spacing12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityIdentifier("video-generate-fullscreen")
        }
    }

    private var statusPlaceholder: some View {
        VStack(spacing: .spacing4) {
            Icon("videos", size: 34)
                .foregroundStyle(payload.status == "error" ? Color.error : Color.fontTertiary)
            Text(payload.status == "error" ? payload.error ?? GeneratedMediaText.videoError : payload.prompt ?? GeneratedMediaText.generatingVideo)
                .font(.omSmall).fontWeight(.medium)
                .foregroundStyle(payload.status == "error" ? Color.error : Color.fontPrimary)
                .multilineTextAlignment(.center).lineLimit(3)
            if payload.status != "error" { ProgressView().tint(Color.buttonPrimary) }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func detail(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(label).font(.omXs).fontWeight(.bold).foregroundStyle(Color.fontSecondary)
            Text(value).font(.omP).foregroundStyle(Color.fontPrimary).textSelection(.enabled)
        }
    }
}

private struct GeneratedAudioControl: View {
    let payload: GeneratedMediaPayload
    let compact: Bool

    @State private var player: AVAudioPlayer?
    @State private var isPlaying = false
    @State private var isLoading = false
    @State private var loadError: String?

    var body: some View {
        HStack(spacing: .spacing4) {
            Button {
                togglePlayback()
            } label: {
                HStack(spacing: .spacing3) {
                    if isLoading { ProgressView().tint(Color.fontPrimary) }
                    else { Icon(isPlaying ? "pause" : "play", size: compact ? 16 : 20) }
                    if let duration = payload.duration { Text(MusicGenerateEmbedRenderer.duration(duration)) }
                }
            }
            .buttonStyle(OMSecondaryButtonStyle())
            .disabled(isLoading || payload.mediaURL == nil)
            .accessibilityIdentifier(compact ? "music-generate-audio" : "music-generate-fullscreen-audio")

            if let loadError {
                Text(loadError).font(.omTiny).foregroundStyle(Color.error).lineLimit(2)
            }
        }
    }

    private func togglePlayback() {
        if let player {
            if player.isPlaying {
                player.pause()
            } else {
                _ = player.play()
            }
            isPlaying = player.isPlaying
            return
        }
        guard let mediaURL = payload.mediaURL else { return }
        isLoading = true
        Task {
            do {
                let data: Data
                if payload.directURL != nil {
                    guard let url = URL(string: mediaURL) else { throw URLError(.badURL) }
                    data = try await URLSession.shared.data(from: url).0
                } else {
                    data = try await S3MediaClient.shared.fetchAndDecrypt(
                        s3Url: mediaURL, aesKeyHex: payload.aesKey ?? "", aesNonceHex: payload.aesNonce ?? "", s3Key: payload.s3Key
                    )
                }
                #if os(iOS)
                try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
                try AVAudioSession.sharedInstance().setActive(true)
                #endif
                let loadedPlayer = try AVAudioPlayer(data: data)
                loadedPlayer.prepareToPlay()
                loadedPlayer.play()
                player = loadedPlayer
                isPlaying = true
            } catch {
                loadError = error.localizedDescription
            }
            isLoading = false
        }
    }
}

private struct GeneratedVideoPlayer: View {
    let payload: GeneratedMediaPayload

    @State private var localURL: URL?
    @State private var loadError: String?

    var body: some View {
        Group {
            if let directURL = payload.directURL.flatMap(URL.init(string:)) {
                VideoPlayerView(url: directURL)
            } else if let localURL {
                VideoPlayerView(url: localURL)
            } else if let loadError {
                Text(loadError).font(.omSmall).foregroundStyle(Color.error).padding(.spacing8)
            } else {
                ProgressView().tint(Color.grey0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task(id: payload.mediaURL) { await loadEncryptedVideo() }
        .onDisappear { if let localURL { try? FileManager.default.removeItem(at: localURL) } }
    }

    private func loadEncryptedVideo() async {
        guard payload.directURL == nil, let mediaURL = payload.mediaURL,
              let aesKey = payload.aesKey, let aesNonce = payload.aesNonce else { return }
        do {
            let data = try await S3MediaClient.shared.fetchAndDecrypt(
                s3Url: mediaURL, aesKeyHex: aesKey, aesNonceHex: aesNonce, s3Key: payload.s3Key
            )
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent("openmates-generated-video", isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let url = directory.appendingPathComponent("\(UUID().uuidString).mp4")
            try data.write(to: url, options: .atomic)
            localURL = url
        } catch {
            loadError = error.localizedDescription
        }
    }
}

private struct GeneratedMediaPayload {
    let prompt: String?
    let model: String?
    let status: String
    let error: String?
    let mode: String?
    let duration: Double?
    let resolution: String?
    let generatedAt: String?
    let watermarking: String?
    let directURL: String?
    let mediaURL: String?
    let s3Key: String?
    let aesKey: String?
    let aesNonce: String?

    init(_ data: [String: AnyCodable]?) {
        prompt = EmbedMediaPayload.string(data, keys: ["prompt"])
        model = EmbedMediaPayload.string(data, keys: ["model"])
        status = EmbedMediaPayload.string(data, keys: ["status"]) ?? "processing"
        error = EmbedMediaPayload.string(data, keys: ["error", "error_message"])
        mode = EmbedMediaPayload.string(data, keys: ["mode"])
        duration = Self.number(data?["duration_seconds"]?.value) ?? Self.originalNumber(data, key: "duration_seconds")
        resolution = EmbedMediaPayload.string(data, keys: ["resolution"])
        generatedAt = EmbedMediaPayload.string(data, keys: ["generated_at"])
        watermarking = EmbedMediaPayload.string(data, keys: ["watermarking"])
        directURL = EmbedMediaPayload.string(data, keys: ["previewAudioUrl", "preview_audio_url", "previewVideoUrl", "preview_video_url"])
        s3Key = EmbedMediaPayload.s3Key(from: data)
        mediaURL = directURL ?? EmbedMediaPayload.s3URL(from: data)
        aesKey = EmbedMediaPayload.string(data, keys: ["aes_key"])
        aesNonce = EmbedMediaPayload.string(data, keys: ["aes_nonce"])
    }

    var modeLabel: String? {
        guard let mode, !mode.isEmpty else { return nil }
        return mode.replacingOccurrences(of: "_", with: " ").capitalized
    }

    private static func number(_ value: Any?) -> Double? {
        if let value = value as? Double { return value }
        if let value = value as? Int { return Double(value) }
        return nil
    }

    private static func originalNumber(_ data: [String: AnyCodable]?, key: String) -> Double? {
        guard let files = data?["files"]?.value as? [String: Any],
              let original = files["original"] as? [String: Any] else { return nil }
        return number(original[key])
    }
}

@MainActor
private enum GeneratedMediaText {
    static var generatingMusic: String { LocalizationManager.shared.text("embeds.music_generate.generating") }
    static var loadingAudio: String { LocalizationManager.shared.text("embeds.music_generate.loading") }
    static var musicError: String { LocalizationManager.shared.text("embeds.music_generate.error") }
    static var prompt: String { LocalizationManager.shared.text("embeds.music_generate.prompt_label") }
    static var model: String { LocalizationManager.shared.text("embeds.music_generate.model_label") }
    static var duration: String { LocalizationManager.shared.text("embeds.music_generate.duration") }
    static var generated: String { LocalizationManager.shared.text("embeds.music_generate.generated_at") }
    static var watermarking: String { LocalizationManager.shared.text("embeds.music_generate.watermarking") }
    static var resolution: String { LocalizationManager.shared.text("embeds.image_generate.resolution") }
    static var generatingVideo: String { LocalizationManager.shared.text("app_skills.videos.generate") }
    static var videoError: String { AppStrings.error }
    static var generatedMusic: String { LocalizationManager.shared.text("app_skills.music.generate") }
}

// MARK: - Recording (encrypted audio on S3)

struct RecordingRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var duration: Double? { data?["duration"]?.value as? Double }
    private var transcription: String? {
        EmbedMediaPayload.string(data, keys: ["transcription", "transcript_corrected", "transcript"])
    }
    private var s3Url: String? { EmbedMediaPayload.s3URL(from: data) }
    private var s3Key: String? { EmbedMediaPayload.s3Key(from: data) }
    private var aesKey: String? { EmbedMediaPayload.string(data, keys: ["aes_key"]) }
    private var aesNonce: String? { EmbedMediaPayload.string(data, keys: ["aes_nonce"]) }

    @State private var isPlaying = false
    @State private var audioData: Data?
    @State private var loadError: String?
    @State private var audioPlayer: AVAudioPlayer?

    var body: some View {
        switch mode {
        case .preview:
            VStack(spacing: .spacing3) {
                Icon(isPlaying ? "play" : "audio", size: 28)
                    .foregroundStyle(isPlaying ? Color.buttonPrimary : Color.fontTertiary)
                if let duration {
                    Text(formatDuration(duration))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                HStack(spacing: .spacing4) {
                    Button {
                        togglePlayback()
                    } label: {
                        Icon(isPlaying ? "pause" : "play", size: 48)
                            .foregroundStyle(Color.buttonPrimary)
                    }

                    VStack(alignment: .leading) {
                        Text(AppStrings.voiceRecording)
                            .font(.omP).fontWeight(.medium)
                        if let duration {
                            Text(formatDuration(duration))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }

                if let loadError {
                    Text(loadError)
                        .font(.omXs).foregroundStyle(Color.error)
                }

                if let transcription {
                    Divider()
                    Text(AppStrings.transcription)
                        .font(.omSmall).fontWeight(.medium).foregroundStyle(Color.fontTertiary)
                    Text(transcription)
                        .font(.omP).foregroundStyle(Color.fontPrimary)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func formatDuration(_ seconds: Double) -> String {
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return "\(mins):\(String(format: "%02d", secs))"
    }

    private func togglePlayback() {
        guard let s3Url, let aesKey, let aesNonce else {
            loadError = "Missing audio encryption keys"
            return
        }

        if let player = audioPlayer {
            // Already loaded — toggle play/pause
            if player.isPlaying {
                player.pause()
                isPlaying = false
            } else {
                player.play()
                isPlaying = true
            }
            return
        }

        // First play — fetch, decrypt, and start
        Task {
            do {
                let data = try await S3MediaClient.shared.fetchAndDecrypt(
                    s3Url: s3Url,
                    aesKeyHex: aesKey,
                    aesNonceHex: aesNonce,
                    s3Key: s3Key
                )
                audioData = data

                #if os(iOS)
                try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
                try AVAudioSession.sharedInstance().setActive(true)
                #endif

                let player = try AVAudioPlayer(data: data)
                player.prepareToPlay()
                player.play()
                audioPlayer = player
                isPlaying = true
            } catch {
                loadError = error.localizedDescription
            }
        }
    }
}

// MARK: - PDF (encrypted on S3)

struct PDFRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var filename: String? { data?["filename"]?.value as? String }
    private var pageCount: Int? { data?["page_count"]?.value as? Int }
    private var s3Url: String? { EmbedMediaPayload.s3URL(from: data) }
    private var s3Key: String? { EmbedMediaPayload.s3Key(from: data) }
    private var aesKey: String? { EmbedMediaPayload.string(data, keys: ["aes_key"]) }
    private var aesNonce: String? { EmbedMediaPayload.string(data, keys: ["aes_nonce"]) }

    @State private var pdfData: Data?
    @State private var isLoading = false
    @State private var loadError: String?

    var body: some View {
        switch mode {
        case .preview:
            VStack(spacing: .spacing3) {
                Icon("pdf", size: 32)
                    .foregroundStyle(Color(hex: 0xE84545))
                if let filename {
                    Text(filename).font(.omXs).foregroundStyle(Color.fontPrimary).lineLimit(1)
                }
                if let pageCount {
                    Text("\(pageCount) pages").font(.omTiny).foregroundStyle(Color.fontTertiary)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                HStack {
                    if let filename {
                        Label(filename, systemImage: "doc.richtext")
                            .font(.omP).foregroundStyle(Color.fontPrimary)
                    }
                    Spacer()
                    if let pageCount {
                        Text("\(pageCount) pages").font(.omSmall).foregroundStyle(Color.fontTertiary)
                    }
                }

                if isLoading {
                    ProgressView(AppStrings.decryptingPDF)
                } else if let loadError {
                    Text(loadError).font(.omSmall).foregroundStyle(Color.error)
                } else if pdfData != nil {
                    #if os(iOS)
                    PDFKitView(data: pdfData!)
                        .frame(minHeight: 500)
                        .clipShape(RoundedRectangle(cornerRadius: .radius3))
                    #else
                    Text(LocalizationManager.shared.text("embed.pdf_ios_only"))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    #endif
                } else {
                    Button(AppStrings.loadPDF) { loadPDF() }
                        .buttonStyle(OMPrimaryButtonStyle())
                }
            }
        }
    }

    private func loadPDF() {
        guard let s3Url, let aesKey, let aesNonce else {
            loadError = "Missing encryption keys"
            return
        }
        isLoading = true
        Task {
            do {
                pdfData = try await S3MediaClient.shared.fetchAndDecrypt(
                    s3Url: s3Url,
                    aesKeyHex: aesKey,
                    aesNonceHex: aesNonce,
                    s3Key: s3Key
                )
            } catch {
                loadError = error.localizedDescription
            }
            isLoading = false
        }
    }
}

#if os(iOS)
struct PDFKitView: UIViewRepresentable {
    let data: Data

    func makeUIView(context: Context) -> PDFView {
        let pdfView = PDFView()
        pdfView.autoScales = true
        pdfView.document = PDFDocument(data: data)
        return pdfView
    }

    func updateUIView(_ uiView: PDFView, context: Context) {}
}
#endif

// MARK: - In-app video player (AVKit)

import AVKit

struct VideoPlayerView: View {
    let url: URL
    @State private var player: AVPlayer?

    var body: some View {
        Group {
            if let player {
                VideoPlayer(player: player)
            } else {
                Color.grey20.overlay(ProgressView())
            }
        }
        .onAppear {
            let avPlayer = AVPlayer(url: url)
            player = avPlayer
        }
        .onDisappear {
            player?.pause()
            player = nil
        }
    }
}

// MARK: - Transcript

struct TranscriptRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var transcript: String? { data?["transcript"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                if let title {
                    Text(title).font(.omSmall).fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary).lineLimit(1)
                }
                if let transcript {
                    Text(transcript).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(5)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let transcript {
                    Text(transcript).font(.omP).foregroundStyle(Color.fontPrimary).textSelection(.enabled)
                }
            }
        }
    }
}
