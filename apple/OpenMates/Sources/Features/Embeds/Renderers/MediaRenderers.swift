// Media embed renderers — video, image, audio, PDF.
// Downloads and decrypts S3-stored media via S3MediaClient.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/music/MusicGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/music/MusicGenerateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/audio/AudioGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/audio/AudioGenerateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoTranscriptEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoTranscriptEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/audio/RecordingEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/audio/RecordingEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, GradientTokens.generated.swift,
//          SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-skills/videos-get-transcript/specification.yml
//                specifications/features/app-skills/audio-generate/specification.yml
//                specifications/features/app-skills/audio-speak/specification.yml
// Assertions: videos.transcript.surface-parity, audio-generate.surface-parity,
//             audio-speak.surface-parity

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

// MARK: - Generated audio app skills

struct GeneratedAudioSkillEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let status: EmbedStatus
    let skillId: String
    let mode: EmbedDisplayMode

    @State private var player: AVAudioPlayer?
    @State private var isPlaying = false
    @State private var isLoading = false
    @State private var elapsed: TimeInterval = 0
    @State private var loadFailed = false

    private var payload: GeneratedAudioSkillPayload { GeneratedAudioSkillPayload(data) }
    private var identifierPrefix: String { skillId == "speak" ? "audio-speak" : "audio-generate" }
    private var skillName: String {
        AppStrings.localized(skillId == "speak" ? "app_skills.audio.speak" : "app_skills.audio.generate")
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing5) {
                HStack(spacing: .spacing4) {
                    playbackButton(compact: true)
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(skillName)
                            .font(.omP)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                        Text(payload.metadata)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(1)
                    }
                }

                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(AppStrings.localized("embeds.music_generate.prompt_label"))
                        .font(.omMicro)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontTertiary)
                    Text(payload.prompt ?? skillName)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(3)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("\(identifierPrefix)-preview")

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing8) {
                HStack(spacing: .spacing8) {
                    playbackButton(compact: false)
                    VStack(alignment: .leading, spacing: .spacing3) {
                        audioProgress
                        Text("\(Self.duration(elapsed)) / \(Self.duration(effectiveDuration))")
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
                .padding(.spacing10)
                .background(Color.grey0)
                .overlay(alignment: .bottom) { Rectangle().fill(Color.grey20).frame(height: 1) }

                VStack(alignment: .leading, spacing: .spacing6) {
                    detail(AppStrings.localized("embeds.music_generate.prompt_label"), payload.prompt ?? skillName)
                    detail(AppStrings.localized("embeds.music_generate.model_label"), payload.model ?? "ElevenLabs")
                    detail(AppStrings.localized("embeds.music_generate.duration"), Self.duration(effectiveDuration))
                }
                .padding(.spacing10)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("\(identifierPrefix)-fullscreen")
        }
    }

    @ViewBuilder
    private func playbackButton(compact: Bool) -> some View {
        if status == .processing {
            ProgressView()
                .tint(Color.buttonPrimary)
                .frame(width: compact ? 40 : 48, height: compact ? 40 : 48)
                .accessibilityIdentifier("\(identifierPrefix)-loading")
        } else if status == .error || loadFailed {
            Icon("warning", size: compact ? 22 : 28)
                .foregroundStyle(Color.error)
                .frame(width: compact ? 40 : 48, height: compact ? 40 : 48)
                .accessibilityIdentifier("\(identifierPrefix)-error")
        } else {
            Button {
                togglePlayback()
            } label: {
                Group {
                    if isLoading {
                        ProgressView().tint(Color.grey0)
                    } else {
                        Icon(isPlaying ? "pause" : "play", size: compact ? 18 : 22)
                            .foregroundStyle(Color.grey0)
                    }
                }
                .frame(width: compact ? 40 : 48, height: compact ? 40 : 48)
                .background(LinearGradient.appAudio)
                .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(isLoading || !payload.hasPlayableMedia)
            .accessibilityLabel(isPlaying ? AppStrings.localized("audio.pause") : AppStrings.localized("audio.play"))
            .accessibilityIdentifier("\(identifierPrefix)-\(compact ? "preview" : "fullscreen")-play-button")
        }
    }

    private var audioProgress: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.grey20)
                Capsule().fill(LinearGradient.appAudio)
                    .frame(width: proxy.size.width * progress)
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                guard proxy.size.width > 0 else { return }
                seek(value.location.x / proxy.size.width)
            })
        }
        .frame(height: 10)
        .accessibilityElement()
        .accessibilityLabel(AppStrings.localized("audio.playback_progress"))
        .accessibilityValue("\(Int(progress * 100))%")
        .accessibilityIdentifier("\(identifierPrefix)-fullscreen-waveform")
        .task(id: isPlaying) {
            while !Task.isCancelled, isPlaying, let player {
                elapsed = player.currentTime
                if !player.isPlaying { isPlaying = false }
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
        }
    }

    private var effectiveDuration: TimeInterval { max(player?.duration ?? 0, payload.duration ?? 0) }
    private var progress: Double { effectiveDuration > 0 ? min(max(elapsed / effectiveDuration, 0), 1) : 0 }

    private func detail(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(label).font(.omXs).fontWeight(.semibold).foregroundStyle(Color.fontSecondary)
            Text(value).font(.omP).foregroundStyle(Color.fontPrimary).textSelection(.enabled)
        }
    }

    private func seek(_ value: Double) {
        let next = min(max(value, 0), 1) * effectiveDuration
        elapsed = next
        player?.currentTime = next
    }

    private func togglePlayback() {
        if let player {
            if player.isPlaying { player.pause() } else { player.play() }
            isPlaying = player.isPlaying
            return
        }
        guard payload.hasPlayableMedia else { return }
        isLoading = true
        loadFailed = false
        Task {
            do {
                let bytes = try await payload.loadAudio()
                #if os(iOS)
                try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
                try AVAudioSession.sharedInstance().setActive(true)
                #endif
                let audioPlayer = try AVAudioPlayer(data: bytes)
                audioPlayer.prepareToPlay()
                audioPlayer.play()
                player = audioPlayer
                isPlaying = true
            } catch {
                loadFailed = true
            }
            isLoading = false
        }
    }

    fileprivate static func duration(_ seconds: TimeInterval) -> String {
        let value = max(0, Int(seconds.rounded(.down)))
        return "\(value / 60):\(String(format: "%02d", value % 60))"
    }
}

private struct GeneratedAudioSkillPayload {
    let prompt: String?
    let model: String?
    let duration: Double?
    let directURL: String?
    let s3BaseURL: String?
    let s3Key: String?
    let aesKey: String?
    let aesNonce: String?
    let encryption: String?

    init(_ data: [String: AnyCodable]?) {
        let raw = Self.flattened(data)
        prompt = Self.string(raw, ["prompt", "text_preview", "text"])
        model = Self.string(raw, ["model"])
        let original = Self.dictionary(Self.dictionary(raw?["files"]?.value)?["original"])
        duration = Self.number(raw?["duration_seconds"]?.value) ?? Self.number(original?["duration_seconds"])
        if let encoded = Self.string(raw, ["audio_base64"]) {
            let mime = Self.string(raw, ["mime_type"]) ?? "audio/mpeg"
            directURL = "data:\(mime);base64,\(encoded)"
        } else {
            directURL = Self.string(raw, ["previewAudioUrl", "preview_audio_url", "audio_url"])
        }
        s3BaseURL = Self.string(raw, ["s3_base_url"])
        s3Key = Self.string(original, ["s3_key"]) ?? Self.string(raw, ["files_original_s3_key"])
        aesKey = Self.string(raw, ["aes_key"])
        aesNonce = Self.string(raw, ["aes_nonce"])
        encryption = Self.string(original, ["encryption"]) ?? Self.string(raw, ["files_original_encryption"])
    }

    var metadata: String {
        [model ?? "ElevenLabs", duration.map { GeneratedAudioSkillEmbedRenderer.duration($0) }]
            .compactMap { $0 }
            .joined(separator: " · ")
    }

    var hasPlayableMedia: Bool { directURL != nil || (s3Key != nil && aesKey != nil) }

    func loadAudio() async throws -> Data {
        if let directURL {
            if directURL.hasPrefix("data:"), let comma = directURL.firstIndex(of: ",") {
                let encoded = String(directURL[directURL.index(after: comma)...])
                guard let data = Data(base64Encoded: encoded) else { throw URLError(.cannotDecodeContentData) }
                return data
            }
            guard let url = URL(string: directURL) else { throw URLError(.badURL) }
            return try await URLSession.shared.data(from: url).0
        }
        guard let s3Key, let aesKey else { throw URLError(.badURL) }
        return try await S3MediaClient.shared.fetchAndDecrypt(
            s3Url: s3BaseURL ?? "",
            aesKeyHex: aesKey,
            aesNonceHex: aesNonce,
            encryption: encryption,
            s3Key: s3Key
        )
    }

    private static func flattened(_ data: [String: AnyCodable]?) -> [String: AnyCodable]? {
        guard var data else { return nil }
        if let results = data["results"]?.value as? [[String: Any]], let first = results.first {
            for (key, value) in first { data[key] = AnyCodable(value) }
        }
        return data
    }

    private static func dictionary(_ value: Any?) -> [String: Any]? {
        if let value = value as? [String: Any] { return value }
        if let value = value as? [String: AnyCodable] { return value.mapValues(\.value) }
        return nil
    }

    private static func string(_ data: [String: AnyCodable]?, _ keys: [String]) -> String? {
        for key in keys {
            if let value = data?[key]?.value as? String, !value.isEmpty { return value }
        }
        return nil
    }

    private static func string(_ data: [String: Any]?, _ keys: [String]) -> String? {
        for key in keys {
            if let value = data?[key] as? String, !value.isEmpty { return value }
        }
        return nil
    }

    private static func number(_ value: Any?) -> Double? {
        if let value = value as? Double { return value }
        if let value = value as? Int { return Double(value) }
        if let value = value as? NSNumber { return value.doubleValue }
        return nil
    }
}

// MARK: - Disk-backed public image loader

struct CachedRemoteImage<Content: View, Placeholder: View>: View {
    let url: URL
    let onFailure: (() -> Void)?
    let content: (Image) -> Content
    let placeholder: () -> Placeholder

    @State private var loadedImage: Image?
    @State private var loadedURL: URL?

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
            if loadedURL == url, let image = loadedImage {
                content(image)
            } else {
                placeholder()
            }
        }
        .task(id: url.absoluteString) {
            guard !Task.isCancelled else { return }
            let requestedURL = url
            guard loadedURL != requestedURL || loadedImage == nil else { return }
            loadedImage = nil
            loadedURL = nil
            do {
                let data = try await RemoteImageCache.shared.fetch(requestedURL.absoluteString)
                guard !Task.isCancelled else { return }
                guard let image = platformImage(from: data) else {
                    onFailure?()
                    return
                }
                // Decode once per URL, not on every chat scroll/body evaluation.
                // A cancelled old task must not publish into a reused image view.
                loadedImage = image
                loadedURL = requestedURL
            } catch {
                if !Task.isCancelled { onFailure?() }
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
    let encryption: String?
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
        guard let s3Url, let aesKey, aesNonce != nil || encryption != nil else {
            error = "Missing encryption keys"
            isLoading = false
            return
        }
        do {
            imageData = try await S3MediaClient.shared.fetchAndDecrypt(
                s3Url: s3Url,
                aesKeyHex: aesKey,
                aesNonceHex: aesNonce,
                encryption: encryption,
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
    let encryption: String?
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
        guard let s3Url, let aesKey, aesNonce != nil || encryption != nil else {
            error = "Missing encryption keys"
            isLoading = false
            return
        }
        do {
            imageData = try await S3MediaClient.shared.fetchAndDecrypt(
                s3Url: s3Url,
                aesKeyHex: aesKey,
                aesNonceHex: aesNonce,
                encryption: encryption,
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
                        s3Url: mediaURL, aesKeyHex: payload.aesKey ?? "", aesNonceHex: payload.aesNonce,
                        encryption: payload.encryption, s3Key: payload.s3Key
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
              let aesKey = payload.aesKey, payload.aesNonce != nil || payload.encryption != nil else { return }
        do {
            let data = try await S3MediaClient.shared.fetchAndDecrypt(
                s3Url: mediaURL, aesKeyHex: aesKey, aesNonceHex: payload.aesNonce,
                encryption: payload.encryption, s3Key: payload.s3Key
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
    let encryption: String?

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
        encryption = EmbedMediaPayload.encryption(from: data)
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

    private var status: String { EmbedMediaPayload.string(data, keys: ["status"]) ?? "finished" }
    private var duration: Double? { Self.normalizedDuration(data) }
    private var transcript: String? { EmbedMediaPayload.string(data, keys: ["transcription", "transcript"]) }
    private var transcriptOriginal: String? { EmbedMediaPayload.string(data, keys: ["transcript_original"]) }
    private var transcriptCorrected: String? { EmbedMediaPayload.string(data, keys: ["transcript_corrected"]) }
    private var model: String? { EmbedMediaPayload.string(data, keys: ["model"]) }
    private var directURL: String? {
        EmbedMediaPayload.string(data, keys: ["blob_url", "previewAudioUrl", "preview_audio_url", "url"])
    }
    private var s3Url: String? { EmbedMediaPayload.s3URL(from: data) }
    private var s3Key: String? { EmbedMediaPayload.s3Key(from: data) }
    private var aesKey: String? { EmbedMediaPayload.string(data, keys: ["aes_key"]) }
    private var aesNonce: String? { EmbedMediaPayload.string(data, keys: ["aes_nonce"]) }
    private var encryption: String? { EmbedMediaPayload.encryption(from: data) }
    private var isProcessing: Bool { ["uploading", "transcribing", "processing"].contains(status) }
    private var isError: Bool { status == "error" }
    private var activeTranscript: String? {
        if let transcriptOriginal, let transcriptCorrected {
            return useCorrected ? transcriptCorrected : transcriptOriginal
        }
        return transcript ?? transcriptCorrected ?? transcriptOriginal
    }

    @State private var isPlaying = false
    @State private var isLoading = false
    @State private var loadError: String?
    @State private var audioPlayer: AVAudioPlayer?
    @State private var elapsed: Double = 0
    @State private var useCorrected: Bool

    init(data: [String: AnyCodable]?, mode: EmbedDisplayMode) {
        self.data = data
        self.mode = mode
        _useCorrected = State(initialValue: data?["use_corrected"]?.value as? Bool ?? true)
    }

    var body: some View {
        Group {
            switch mode {
            case .preview:
                recordingPreview
            case .fullscreen:
                recordingContent(compact: false)
                    .padding(.spacing12)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("recording-fullscreen")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .task(id: isPlaying) { await updatePlaybackProgress() }
        .onDisappear { audioPlayer?.pause() }
    }

    private var recordingPreview: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: .spacing4) {
                if let samples = waveformSamples {
                    RecordingPreviewWaveform(samples: samples, progress: progress)
                }

                if let activeTranscript, !activeTranscript.isEmpty {
                    Text(activeTranscript)
                        .font(.omXs)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(4)
                        .textSelection(.disabled)
                        .accessibilityIdentifier("recording-transcript")
                } else {
                    Text(AppStrings.localized("app_skills.audio.transcribe.no_transcript"))
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .italic()
                        .accessibilityIdentifier("recording-transcript")
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, 14)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .accessibilityIdentifier("recording-preview")

            EmbedBasicInfoBar(
                appId: "audio",
                skillIconName: "microphone",
                title: AppStrings.localized("app_skills.audio.transcribe.audio_recording"),
                subtitle: Self.formatDuration(effectiveDuration),
                faviconURL: nil,
                showSkillIcon: false,
                trailingAction: AnyView(recordingPreviewPlayButton)
            )
            .accessibilityIdentifier("recording-preview-info-bar")
        }
    }

    private var recordingPreviewPlayButton: some View {
        Button(action: togglePlayback) {
            Circle()
                .fill(LinearGradient.appAudio)
                .frame(width: 36, height: 36)
                .overlay {
                    if isLoading {
                        ProgressView().tint(Color.grey0)
                    } else {
                        Icon(isPlaying ? "pause" : "play", size: 16)
                            .foregroundStyle(Color.grey0)
                    }
                }
        }
        .buttonStyle(.plain)
        .disabled(isLoading || !hasPlayableMetadata)
        .accessibilityLabel(isPlaying ? AppStrings.pause : AppStrings.play)
        .accessibilityIdentifier("recording-playback-toggle")
    }

    private var waveformSamples: [Double]? {
        guard let waveform = data?["waveform"]?.value as? [String: Any],
              let rawSamples = waveform["samples"] as? [Any] else { return nil }
        let samples = rawSamples.compactMap { value -> Double? in
            if let value = value as? Double { return value }
            if let value = value as? Int { return Double(value) }
            if let value = value as? NSNumber { return value.doubleValue }
            return nil
        }.map { min(1, max(0.06, $0 / 100)) }
        return samples.isEmpty ? nil : samples
    }

    private func recordingContent(compact: Bool) -> some View {
        VStack(alignment: .leading, spacing: compact ? .spacing4 : .spacing8) {
            HStack(alignment: .center, spacing: .spacing4) {
                AppIconView(appId: "audio", size: compact ? 32 : 48)
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(AppStrings.localized("app_skills.audio.transcribe.audio_recording"))
                        .font(compact ? .omSmall : .omP)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                    Text(statusLabel)
                        .font(.omXs)
                        .foregroundStyle(isError ? Color.error : Color.fontSecondary)
                }
                Spacer(minLength: 0)
            }

            if isProcessing {
                processingState
            } else if isError {
                errorState(message: rawError ?? AppStrings.localized("common.upload_failed"))
            } else {
                playbackControls(compact: compact)
                transcriptContent(compact: compact)
            }

            if let loadError {
                errorState(message: loadError)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var statusLabel: String {
        if isProcessing {
            if status == "transcribing", let model {
                return AppStrings.localized("app_skills.audio.transcribe.transcribing_via")
                    .replacingOccurrences(of: "{model}", with: model)
            }
            return AppStrings.localized("app_skills.audio.transcribe.processing")
        }
        if isError { return rawError ?? AppStrings.localized("common.upload_failed") }
        return Self.formatDuration(duration ?? audioPlayer?.duration ?? 0)
    }

    private var rawError: String? {
        EmbedMediaPayload.string(data, keys: ["upload_error", "error", "error_message"])
    }

    private var processingState: some View {
        HStack(spacing: .spacing3) {
            ProgressView().tint(Color.buttonPrimary)
            Text(statusLabel)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("recording-processing-state")
    }

    private func errorState(message: String) -> some View {
        HStack(spacing: .spacing3) {
            Icon("warning", size: 16).foregroundStyle(Color.error)
            Text(message).font(.omXs).foregroundStyle(Color.error).lineLimit(3)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("recording-error-state")
    }

    private func playbackControls(compact: Bool) -> some View {
        HStack(spacing: compact ? .spacing4 : .spacing8) {
            Button(action: togglePlayback) {
                Circle()
                    .fill(AppIconView.gradient(forAppId: "audio"))
                    .frame(width: compact ? 36 : 48, height: compact ? 36 : 48)
                    .overlay {
                        if isLoading {
                            ProgressView().tint(Color.grey0)
                        } else {
                            Icon(isPlaying ? "pause" : "play", size: compact ? 16 : 20)
                                .foregroundStyle(Color.grey0)
                        }
                    }
            }
            .buttonStyle(.plain)
            .disabled(isLoading || !hasPlayableMetadata)
            .accessibilityLabel(isPlaying ? AppStrings.pause : AppStrings.play)
            .accessibilityIdentifier(compact ? "recording-playback-toggle" : "recording-fullscreen-playback-toggle")

            VStack(alignment: .leading, spacing: .spacing3) {
                RecordingSeekBar(
                    progress: progress,
                    onSeek: seek,
                    accessibilityIdentifier: compact ? "recording-seek" : "recording-fullscreen-seek"
                )
                Text("\(Self.formatDuration(elapsed)) / \(Self.formatDuration(effectiveDuration))")
                    .font(.omMicro)
                    .foregroundStyle(Color.fontSecondary)
                    .monospacedDigit()
                    .accessibilityIdentifier("recording-time")
            }
        }
    }

    @ViewBuilder
    private func transcriptContent(compact: Bool) -> some View {
        if transcriptOriginal != nil, transcriptCorrected != nil {
            Button {
                useCorrected.toggle()
            } label: {
                HStack(spacing: .spacing2) {
                    Icon("ai", size: 12)
                    Text(AppStrings.transcription)
                        .font(.omMicro)
                        .fontWeight(.semibold)
                }
                .foregroundStyle(useCorrected ? AppIconView.gradient(forAppId: "audio") : LinearGradient.primary)
                .padding(.horizontal, .spacing3)
                .padding(.vertical, .spacing2)
                .background(Color.grey10)
                .overlay(Capsule().stroke(Color.grey30, lineWidth: 1))
                .clipShape(Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityValue(useCorrected ? AppStrings.yes : AppStrings.no)
            .accessibilityIdentifier("recording-correction-state")
        }

        if let model {
            Text(AppStrings.localized("app_skills.audio.transcribe.transcribed_by")
                .replacingOccurrences(of: "{model}", with: model))
                .font(.omMicro)
                .fontWeight(.medium)
                .foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("recording-model")
        }

        if let activeTranscript, !activeTranscript.isEmpty {
            let transcript = Text(activeTranscript)
                .font(compact ? .omXs : .omP)
                .foregroundStyle(Color.fontPrimary)
            if compact {
                transcript
                    .lineLimit(4)
                    .textSelection(.disabled)
                    .accessibilityIdentifier("recording-transcript")
            } else {
                transcript
                    .textSelection(.enabled)
                    .accessibilityIdentifier("recording-fullscreen-transcript")
            }
        } else {
            Text(AppStrings.localized("app_skills.audio.transcribe.no_transcript"))
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .italic()
                .accessibilityIdentifier(compact ? "recording-transcript" : "recording-fullscreen-transcript")
        }
    }

    private var hasPlayableMetadata: Bool {
        directURL != nil || (s3Url != nil && aesKey != nil && (aesNonce != nil || encryption != nil))
    }

    private var effectiveDuration: Double {
        let loadedDuration = audioPlayer?.duration ?? 0
        return loadedDuration > 0 ? loadedDuration : duration ?? 0
    }

    private var progress: Double {
        guard effectiveDuration > 0 else { return 0 }
        return min(max(elapsed / effectiveDuration, 0), 1)
    }

    private func seek(_ progress: Double) {
        let nextTime = min(max(progress, 0), 1) * effectiveDuration
        elapsed = nextTime
        audioPlayer?.currentTime = nextTime
    }

    private func togglePlayback() {
        if let player = audioPlayer {
            if player.isPlaying {
                player.pause()
            } else {
                player.play()
            }
            isPlaying = player.isPlaying
            return
        }

        guard hasPlayableMetadata else { return }
        isLoading = true
        loadError = nil
        Task {
            do {
                let audioData: Data
                if let directURL, let url = URL(string: directURL) {
                    audioData = try await URLSession.shared.data(from: url).0
                } else if let s3Url, let aesKey, aesNonce != nil || encryption != nil {
                    audioData = try await S3MediaClient.shared.fetchAndDecrypt(
                        s3Url: s3Url,
                        aesKeyHex: aesKey,
                        aesNonceHex: aesNonce,
                        encryption: encryption,
                        s3Key: s3Key
                    )
                } else {
                    throw URLError(.badURL)
                }
                #if os(iOS)
                try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
                try AVAudioSession.sharedInstance().setActive(true)
                #endif
                let player = try AVAudioPlayer(data: audioData)
                player.prepareToPlay()
                player.play()
                audioPlayer = player
                isPlaying = true
            } catch {
                loadError = AppStrings.localized("common.upload_failed")
            }
            isLoading = false
        }
    }

    private func updatePlaybackProgress() async {
        while !Task.isCancelled, isPlaying, let player = audioPlayer {
            elapsed = player.currentTime
            if !player.isPlaying {
                isPlaying = false
                if player.currentTime >= player.duration { elapsed = 0 }
                return
            }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
    }

    private static func normalizedDuration(_ data: [String: AnyCodable]?) -> Double? {
        for key in ["duration", "duration_seconds"] {
            if let value = data?[key]?.value as? Double { return value }
            if let value = data?[key]?.value as? Int { return Double(value) }
            if let value = data?[key]?.value as? String {
                let parts = value.split(separator: ":").compactMap { Double($0) }
                if parts.count == 2 { return parts[0] * 60 + parts[1] }
                if let seconds = Double(value) { return seconds }
            }
        }
        return nil
    }

    private static func formatDuration(_ seconds: Double) -> String {
        let safeSeconds = max(0, Int(seconds.rounded(.down)))
        return "\(safeSeconds / 60):\(String(format: "%02d", safeSeconds % 60))"
    }
}

private struct RecordingPreviewWaveform: View {
    let samples: [Double]
    let progress: Double

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                HStack(alignment: .center, spacing: 1) {
                    ForEach(Array(samples.enumerated()), id: \.offset) { _, sample in
                        Capsule()
                            .fill(LinearGradient.appAudio)
                            .frame(maxWidth: .infinity)
                            .frame(height: max(2, 30 * sample))
                    }
                }

                Capsule()
                    .fill(LinearGradient.appAudio)
                    .frame(width: 2, height: 30)
                    .offset(x: max(0, min(proxy.size.width - 2, proxy.size.width * progress)))
            }
        }
        .frame(height: 30)
        .accessibilityHidden(true)
        .accessibilityIdentifier("recording-preview-waveform")
    }
}

private struct RecordingSeekBar: View {
    let progress: Double
    let onSeek: (Double) -> Void
    let accessibilityIdentifier: String

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.grey20)
                Capsule()
                    .fill(AppIconView.gradient(forAppId: "audio"))
                    .frame(width: proxy.size.width * progress)
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                guard proxy.size.width > 0 else { return }
                onSeek(value.location.x / proxy.size.width)
            })
        }
        .frame(height: 8)
        .accessibilityElement()
        .accessibilityLabel(AppStrings.localized("audio.playback_progress"))
        .accessibilityValue("\(Int(progress * 100))%")
        .accessibilityAdjustableAction { direction in
            onSeek(progress + (direction == .increment ? 0.1 : -0.1))
        }
        .accessibilityIdentifier(accessibilityIdentifier)
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
    private var encryption: String? { EmbedMediaPayload.encryption(from: data) }

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
        guard let s3Url, let aesKey, aesNonce != nil || encryption != nil else {
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
                    encryption: encryption,
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

struct VideoTranscriptPayload: Equatable {
    let title: String?
    let channelName: String?
    let channelThumbnailURL: URL?
    let videoThumbnailURL: URL?
    let sourceURL: String?
    let videoID: String?
    let transcript: String
    let wordCount: Int
    let language: String?
    let duration: String?

    init(data: [String: AnyCodable]?) {
        let root = data ?? [:]
        let flattenedResults = Self.flattenedResults(in: root)
        let result = flattenedResults.first(where: { Self.string($0, keys: ["transcript", "formatted_transcript", "text", "content"]) != nil })
            ?? flattenedResults.first
            ?? root.mapValues(\.value)
        let metadata = Self.dictionary(result["metadata"])

        title = Self.string(metadata, keys: ["title"])
            ?? Self.string(result, keys: ["title"])
            ?? EmbedFieldReader.string(root, keys: ["title"])
        channelName = Self.string(metadata, keys: ["channel_name", "channel_title"])
            ?? Self.string(result, keys: ["channel_name", "channel_title"])
        let thumbnail = Self.string(metadata, keys: ["channel_thumbnail", "channel_thumbnail_url"])
            ?? Self.string(result, keys: ["channel_thumbnail", "channel_thumbnail_url"])
        channelThumbnailURL = EmbedFieldReader.proxiedImageURL(thumbnail, maxWidth: 58).flatMap(URL.init(string:))
        sourceURL = Self.string(result, keys: ["url"])
            ?? EmbedFieldReader.string(root, keys: ["url"])
        videoID = Self.string(result, keys: ["video_id"])
            ?? EmbedFieldReader.string(root, keys: ["video_id"])
            ?? Self.youtubeVideoID(from: sourceURL)
        let videoThumbnail = Self.string(metadata, keys: ["thumbnail_url", "thumbnail", "thumbnail_original"])
            ?? Self.string(result, keys: ["thumbnail_url", "thumbnail", "thumbnail_original"])
            ?? videoID.map { "https://i.ytimg.com/vi/\($0)/hqdefault.jpg" }
        videoThumbnailURL = EmbedFieldReader.proxiedImageURL(videoThumbnail, maxWidth: 640).flatMap(URL.init(string:))
        transcript = Self.string(result, keys: ["transcript", "formatted_transcript", "text", "content"])
            ?? EmbedFieldReader.string(root, keys: ["transcript", "formatted_transcript", "text", "content"])
            ?? ""
        wordCount = flattenedResults.reduce(0) { partial, item in
            partial + (Self.int(item, keys: ["word_count", "wordCount"]) ?? 0)
        }
        language = Self.string(result, keys: ["language"])
            ?? EmbedFieldReader.string(root, keys: ["language"])
        duration = Self.string(metadata, keys: ["duration", "duration_formatted"])
            ?? Self.string(result, keys: ["duration", "duration_formatted"])
    }

    static func flattenedResults(in data: [String: AnyCodable]) -> [[String: Any]] {
        let candidates = ["results", "preview_results"]
            .lazy
            .map { EmbedFieldReader.dictionaryArray(data, key: $0) }
            .first { !$0.isEmpty } ?? []
        let flattened = candidates.flatMap { candidate -> [[String: Any]] in
            let nested = dictionaryArray(candidate["results"])
            return nested.isEmpty ? [candidate] : nested
        }
        if !flattened.isEmpty { return flattened }
        return EmbedFieldReader.string(data, keys: ["transcript", "formatted_transcript", "text", "content"]) == nil
            ? []
            : [data.mapValues(\.value)]
    }

    /// Reconstitute the web fullscreen payload from its persisted parent and
    /// child records. Parent preview metadata supplies title/thumbnail fields;
    /// the child supplies the full transcript and wins on duplicate keys.
    static func mergedData(
        parent: [String: AnyCodable],
        child: [String: AnyCodable]
    ) -> [String: AnyCodable] {
        var merged = parent
        if let preview = EmbedFieldReader.dictionaryArray(parent, key: "preview_results").first {
            for (key, value) in preview where merged[key] == nil {
                merged[key] = AnyCodable(value)
            }
        }
        for (key, value) in child {
            merged[key] = value
        }
        let normalizedResult = merged.reduce(into: [String: Any]()) { result, field in
            guard field.key != "results", field.key != "preview_results" else { return }
            result[field.key] = field.value.value
        }
        merged["results"] = AnyCodable([normalizedResult])
        return merged
    }

    private static func dictionary(_ value: Any?) -> [String: Any] {
        if let value = value as? [String: Any] { return value }
        if let value = value as? [String: AnyCodable] { return value.mapValues(\.value) }
        return [:]
    }

    private static func dictionaryArray(_ value: Any?) -> [[String: Any]] {
        if let value = value as? [[String: Any]] { return value }
        if let value = value as? [Any] { return value.map(dictionary).filter { !$0.isEmpty } }
        return []
    }

    private static func string(_ data: [String: Any], keys: [String]) -> String? {
        for key in keys {
            if let value = data[key] as? String,
               !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return value
            }
        }
        return nil
    }

    private static func int(_ data: [String: Any], keys: [String]) -> Int? {
        for key in keys {
            if let value = data[key] as? Int { return value }
            if let value = data[key] as? Double { return Int(value) }
            if let value = data[key] as? String, let parsed = Int(value) { return parsed }
        }
        return nil
    }

    private static func youtubeVideoID(from sourceURL: String?) -> String? {
        guard let sourceURL, let components = URLComponents(string: sourceURL) else { return nil }
        if components.host?.lowercased().hasSuffix("youtu.be") == true {
            return components.path.split(separator: "/").first.map(String.init)
        }
        guard components.host?.lowercased().contains("youtube.com") == true else { return nil }
        return components.queryItems?.first(where: { $0.name == "v" })?.value
    }
}

struct VideoTranscriptMetadata: Decodable, Equatable {
    let title: String?
    let channelName: String?
    let channelThumbnail: String?
    let videoId: String?
    let thumbnails: Thumbnails?
    let duration: Duration?

    struct Thumbnails: Decodable, Equatable {
        let `default`: String?
        let medium: String?
        let high: String?
        let standard: String?
        let maxres: String?
    }

    struct Duration: Decodable, Equatable {
        let totalSeconds: Double?
        let formatted: String?

        enum CodingKeys: String, CodingKey {
            case totalSeconds = "total_seconds"
            case formatted
        }
    }

    enum CodingKeys: String, CodingKey {
        case title
        case channelName = "channel_name"
        case channelThumbnail = "channel_thumbnail"
        case videoId = "video_id"
        case thumbnails
        case duration
    }

    var channelThumbnailURL: URL? {
        EmbedFieldReader.proxiedImageURL(channelThumbnail, maxWidth: 58).flatMap(URL.init(string:))
    }

    var videoThumbnailURL: URL? {
        let raw = thumbnails?.maxres ?? thumbnails?.standard ?? thumbnails?.high ?? thumbnails?.medium ?? thumbnails?.default
        return EmbedFieldReader.proxiedImageURL(raw, maxWidth: 640).flatMap(URL.init(string:))
    }
}

enum VideoTranscriptMetadataLoader {
    static func metadataURL(for sourceURL: String) -> URL? {
        guard let source = URL(string: sourceURL),
              source.scheme == "https",
              let host = source.host?.lowercased(),
              host == "youtube.com" || host == "www.youtube.com" || host == "m.youtube.com" || host == "youtu.be" else {
            return nil
        }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/youtube")
        components?.queryItems = [URLQueryItem(name: "url", value: sourceURL)]
        return components?.url
    }

    static func load(sourceURL: String, session: URLSession = .shared) async throws -> VideoTranscriptMetadata {
        guard let url = metadataURL(for: sourceURL) else { throw URLError(.badURL) }
        #if DEBUG
        if let fixture = ProcessInfo.processInfo.environment["DEV_TRANSCRIPT_METADATA_RESPONSE"],
           let fixtureData = fixture.data(using: .utf8) {
            return try JSONDecoder().decode(VideoTranscriptMetadata.self, from: fixtureData)
        }
        #endif
        let (data, response) = try await session.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse,
              (200..<300).contains(httpResponse.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(VideoTranscriptMetadata.self, from: data)
    }
}

struct TranscriptRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    @Environment(\.openURL) private var openURL
    @State private var fetchedMetadata: VideoTranscriptMetadata?

    private var payload: VideoTranscriptPayload { VideoTranscriptPayload(data: data) }
    private var title: String? { fetchedMetadata?.title ?? payload.title }
    private var channelName: String? { fetchedMetadata?.channelName ?? payload.channelName }
    private var channelThumbnailURL: URL? {
        fetchedMetadata?.channelThumbnailURL ?? payload.channelThumbnailURL
    }
    private var videoThumbnailURL: URL? {
        fetchedMetadata?.videoThumbnailURL ?? payload.videoThumbnailURL
    }
    private var duration: String? { fetchedMetadata?.duration?.formatted ?? payload.duration }

    var body: some View {
        Group {
            switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                HStack(alignment: .top, spacing: .spacing4) {
                    if let thumbnailURL = channelThumbnailURL {
                        CachedRemoteImage(url: thumbnailURL) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: {
                            Circle().fill(Color.grey30)
                        }
                        .frame(width: 29, height: 29)
                        .clipShape(Circle())
                        .accessibilityHidden(true)
                    }

                    Text(title ?? AppStrings.transcriptYouTubeVideo)
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.grey100)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                        .accessibilityIdentifier("video-transcript-title")
                }

                VStack(alignment: .leading, spacing: 0) {
                    Text(channelName.map { "\(AppStrings.transcriptVia) YouTube · \($0)" } ?? "\(AppStrings.transcriptVia) YouTube")
                    if payload.wordCount > 0 {
                        Text("\(payload.wordCount.formatted()) \(AppStrings.transcriptWords)")
                    }
                }
                .font(.omSmall)
                .fontWeight(.bold)
                .foregroundStyle(Color.grey70)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("video-transcript-subtitle")
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("video-transcript-preview")

        case .fullscreen:
            VStack(alignment: .center, spacing: .spacing8) {
                if payload.sourceURL != nil {
                    transcriptVideoPreview
                }

                if payload.wordCount > 0 {
                    Text("\(payload.wordCount.formatted()) \(AppStrings.transcriptWords):")
                        .font(.omP)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                        .frame(maxWidth: 722, alignment: .center)
                        .accessibilityIdentifier("video-transcript-fullscreen-metadata")
                }

                if payload.transcript.isEmpty {
                    Text(AppStrings.transcriptNoResults)
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("video-transcript-fullscreen-empty")
                } else {
                    Text(payload.transcript)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.spacing10)
                        .frame(maxWidth: 722, alignment: .leading)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius7))
                        .shadow(color: .black.opacity(0.16), radius: 12, x: 0, y: 8)
                        .accessibilityIdentifier("video-transcript-fullscreen-text")
                }
            }
            .padding(.top, .spacing10)
            .frame(maxWidth: .infinity, alignment: .top)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("video-transcript-fullscreen")
            }
        }
        .task(id: payload.sourceURL) {
            fetchedMetadata = nil
            guard let sourceURL = payload.sourceURL,
                  payload.title == nil || payload.channelName == nil || payload.channelThumbnailURL == nil else { return }
            fetchedMetadata = try? await VideoTranscriptMetadataLoader.load(sourceURL: sourceURL)
        }
    }

    private var transcriptVideoPreview: some View {
        Button {
            guard let sourceURL = payload.sourceURL, let url = URL(string: sourceURL) else { return }
            openURL(url)
        } label: {
            VStack(spacing: 0) {
                ZStack {
                    if let videoThumbnailURL {
                        CachedRemoteImage(url: videoThumbnailURL) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: {
                            LinearGradient.appVideos
                        }
                    } else {
                        LinearGradient.appVideos
                    }

                    Icon("play", size: 36)
                        .foregroundStyle(Color.grey0.opacity(0.9))
                        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                }
                .frame(height: 139)
                .clipped()

                EmbedBasicInfoBar(
                    appId: "videos",
                    skillIconName: "videos",
                    title: title ?? AppStrings.transcriptYouTubeVideo,
                    subtitle: [channelName, duration].compactMap { $0 }.joined(separator: " · ").nonEmpty,
                    faviconURL: nil,
                    showSkillIcon: false
                )
            }
            .frame(width: 300, height: 200)
            .background(Color.grey25)
            .clipShape(RoundedRectangle(cornerRadius: 30))
            .shadow(color: .black.opacity(0.16), radius: 12, x: 0, y: 8)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(AppStrings.openVideo)
        .accessibilityIdentifier("video-transcript-video-preview")
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}
