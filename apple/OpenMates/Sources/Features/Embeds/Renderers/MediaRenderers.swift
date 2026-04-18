// Media embed renderers — video, image, audio, PDF.
// Downloads and decrypts S3-stored media via S3MediaClient.

import SwiftUI
#if os(iOS)
import PDFKit
#endif
import AVFoundation

// MARK: - Encrypted image loader (shared by image embeds)

struct EncryptedImageView: View {
    let s3Url: String?
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
                        Image(systemName: "photo.badge.exclamationmark")
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
                s3Url: s3Url, aesKeyHex: aesKey, aesNonceHex: aesNonce
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
                    AsyncImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: { Color.grey20 }
                } else {
                    Color.grey20
                }

                // Play button overlay
                Image(systemName: "play.circle.fill")
                    .font(.system(size: 36))
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
                    AsyncImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fit)
                    } placeholder: { ProgressView() }
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
                }

                Text(title).font(.omP).fontWeight(.medium).foregroundStyle(Color.fontPrimary)

                if let channel {
                    Text(channel).font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
                if let duration {
                    Label(duration, systemImage: SFSymbol.clock)
                        .font(.omSmall).foregroundStyle(Color.fontTertiary)
                }
                if let url, let videoURL = URL(string: url) {
                    Link(AppStrings.openInBrowser, destination: videoURL)
                        .font(.omSmall).foregroundStyle(Color.buttonPrimary)
                }
            }
        }
    }
}

// MARK: - Image (uploaded, encrypted on S3)

struct ImageRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var filename: String? { data?["filename"]?.value as? String }
    private var s3Url: String? { data?["s3_url"]?.value as? String }
    private var aesKey: String? { data?["aes_key"]?.value as? String }
    private var aesNonce: String? { data?["aes_nonce"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            if s3Url != nil && aesKey != nil {
                EncryptedImageView(
                    s3Url: s3Url, aesKey: aesKey, aesNonce: aesNonce,
                    contentMode: .fill
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: .spacing3) {
                    Image(systemName: "photo")
                        .font(.system(size: 32)).foregroundStyle(Color.fontTertiary)
                    if let filename {
                        Text(filename).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let filename {
                    Text(filename).font(.omP).foregroundStyle(Color.fontPrimary)
                }
                if s3Url != nil && aesKey != nil {
                    EncryptedImageView(
                        s3Url: s3Url, aesKey: aesKey, aesNonce: aesNonce,
                        contentMode: .fit
                    )
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
                }
            }
        }
    }
}

// MARK: - Image search result (public URL, not encrypted)

struct ImageResultRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var url: String? { data?["url"]?.value as? String ?? data?["thumbnail_url"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            if let url, let imgURL = URL(string: url) {
                AsyncImage(url: imgURL) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: { Color.grey20.overlay(ProgressView()) }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }

        case .fullscreen:
            VStack(spacing: .spacing4) {
                if let url, let imgURL = URL(string: url) {
                    AsyncImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fit)
                    } placeholder: { ProgressView() }
                }
                if let title {
                    Text(title).font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
            }
        }
    }
}

// MARK: - Generated image (encrypted on S3)

struct ImageGenerateRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var prompt: String? { data?["prompt"]?.value as? String }
    private var model: String? { data?["model"]?.value as? String }
    private var s3BaseUrl: String? { data?["s3_base_url"]?.value as? String }
    private var aesKey: String? { data?["aes_key"]?.value as? String }
    private var aesNonce: String? { data?["aes_nonce"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            if let s3BaseUrl, let aesKey {
                EncryptedImageView(
                    s3Url: s3BaseUrl, aesKey: aesKey, aesNonce: aesNonce,
                    contentMode: .fill
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(alignment: .leading, spacing: .spacing3) {
                    Image(systemName: "paintbrush.fill")
                        .font(.system(size: 24)).foregroundStyle(Color.fontTertiary)
                    if let prompt {
                        Text(prompt).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(3)
                    }
                }
                .padding(.spacing4)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let s3BaseUrl, let aesKey {
                    EncryptedImageView(
                        s3Url: s3BaseUrl, aesKey: aesKey, aesNonce: aesNonce,
                        contentMode: .fit
                    )
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
                }
                if let prompt {
                    VStack(alignment: .leading, spacing: .spacing2) {
                        Text(LocalizationManager.shared.text("embed.prompt")).font(.omXs).foregroundStyle(Color.fontTertiary)
                        Text(prompt).font(.omP).foregroundStyle(Color.fontPrimary)
                    }
                }
                if let model {
                    HStack {
                        Text(LocalizationManager.shared.text("embed.model")).font(.omXs).foregroundStyle(Color.fontTertiary)
                        Text(model).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                }
            }
        }
    }
}

// MARK: - Recording (encrypted audio on S3)

struct RecordingRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var duration: Double? { data?["duration"]?.value as? Double }
    private var transcription: String? { data?["transcription"]?.value as? String }
    private var s3Url: String? { data?["s3_url"]?.value as? String }
    private var aesKey: String? { data?["aes_key"]?.value as? String }
    private var aesNonce: String? { data?["aes_nonce"]?.value as? String }

    @State private var isPlaying = false
    @State private var audioData: Data?
    @State private var loadError: String?
    @State private var audioPlayer: AVAudioPlayer?

    var body: some View {
        switch mode {
        case .preview:
            VStack(spacing: .spacing3) {
                Image(systemName: isPlaying ? "waveform.circle.fill" : "waveform")
                    .font(.system(size: 28))
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
                        Image(systemName: isPlaying ? "pause.circle.fill" : "play.circle.fill")
                            .font(.system(size: 48))
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
                    s3Url: s3Url, aesKeyHex: aesKey, aesNonceHex: aesNonce
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
    private var s3Url: String? { data?["s3_url"]?.value as? String }
    private var aesKey: String? { data?["aes_key"]?.value as? String }
    private var aesNonce: String? { data?["aes_nonce"]?.value as? String }

    @State private var pdfData: Data?
    @State private var isLoading = false
    @State private var loadError: String?

    var body: some View {
        switch mode {
        case .preview:
            VStack(spacing: .spacing3) {
                Image(systemName: "doc.richtext")
                    .font(.system(size: 32))
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
                    s3Url: s3Url, aesKeyHex: aesKey, aesNonceHex: aesNonce
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
