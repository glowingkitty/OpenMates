// ImageEmbedRenderer — native counterpart for uploaded image embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

/// The fullscreen Download action exports only an explicit original variant.
/// Preview/full variants must never be substituted for an absent original.
struct ImageOriginalDownloadPayload: Sendable {
    let s3Key: String
    let aesKey: String
    let aesNonce: String?
    let encryption: String?
    let filename: String

    init?(data: [String: AnyCodable]?) {
        guard let data,
              let files = data["files"]?.value as? [String: Any],
              let original = files["original"] as? [String: Any],
              let key = original["s3_key"] as? String, !key.isEmpty,
              let aesKey = EmbedMediaPayload.string(data, keys: ["aes_key", "aesKey"]),
              !aesKey.isEmpty else { return nil }
        let nonce = (original["aes_nonce"] as? String)
            ?? (data["aes_nonce"]?.value as? String)
            ?? (data["aesNonce"]?.value as? String)
        let marker = (original["encryption"] as? String)
            ?? EmbedMediaPayload.string(data, keys: ["encryption"])
        guard (nonce?.isEmpty == false) || marker == S3MediaClient.noncePrefixedEncryption else { return nil }
        s3Key = key
        self.aesKey = aesKey
        aesNonce = nonce
        encryption = marker

        let rawName = EmbedMediaPayload.string(data, keys: ["filename"]) ?? "image"
        let lastComponent = rawName.replacingOccurrences(of: "\\", with: "/")
            .split(separator: "/").last.map(String.init) ?? "image"
        let safeName = String(lastComponent.unicodeScalars.filter {
            !CharacterSet.controlCharacters.contains($0) && $0 != ":"
        })
        let baseName = safeName.isEmpty || safeName == "." || safeName == ".." ? "image" : safeName
        let rawFormat = (original["format"] as? String) ?? "bin"
        let format = rawFormat.lowercased().filter { $0.isASCII && $0.isLetter || $0.isNumber }
        filename = URL(fileURLWithPath: baseName).pathExtension.isEmpty
            ? "\(baseName).\(format.isEmpty ? "bin" : String(format.prefix(8)))"
            : baseName
    }

    func load(using client: S3MediaClient, scope: String) async throws -> Data {
        try await client.fetchAndDecrypt(
            s3Url: "", aesKeyHex: aesKey, aesNonceHex: aesNonce,
            encryption: encryption, s3Key: s3Key, cacheNamespace: scope,
            cachePolicy: .memoryOnly
        )
    }
}

struct ImageOriginalDownloadFence: Equatable {
    let scope: String
    let scopeGeneration: UUID
    let selectionGeneration: UUID

    func permits(scope currentScope: String?, scopeGeneration currentScopeGeneration: UUID,
                 selectionGeneration currentSelectionGeneration: UUID) -> Bool {
        scope == currentScope && scopeGeneration == currentScopeGeneration
            && selectionGeneration == currentSelectionGeneration
    }
}

@MainActor
final class ImageOriginalDownloadController: ObservableObject {
    @Published private(set) var isDownloading = false
    private var task: Task<Void, Never>?
    private var selectionGeneration = UUID()
    #if os(iOS)
    private var activityController: UIActivityViewController?
    private var temporaryURL: URL?
    #endif

    nonisolated static func canDownload(data: [String: AnyCodable]?) -> Bool {
        ImageOriginalDownloadPayload(data: data) != nil
    }

    func download(data: [String: AnyCodable]?) {
        guard !isDownloading,
              let payload = ImageOriginalDownloadPayload(data: data),
              let scope = OfflineStore.shared.activeScopeId else { return }
        #if os(iOS)
        guard activityController == nil else { return }
        #endif
        let selection = selectionGeneration
        let fence = ImageOriginalDownloadFence(
            scope: scope, scopeGeneration: OfflineStore.shared.scopeGeneration,
            selectionGeneration: selection
        )
        isDownloading = true
        task = Task { [weak self] in
            guard let self else { return }
            guard let owner = await AuthManager.currentUserId() else {
                self.finishDownload(for: selection); return
            }
            guard !Task.isCancelled,
                  fence.permits(scope: OfflineStore.shared.activeScopeId,
                                scopeGeneration: OfflineStore.shared.scopeGeneration,
                                selectionGeneration: self.selectionGeneration) else {
                self.finishDownload(for: selection); return
            }
            do {
                let bytes = try await payload.load(using: .shared, scope: scope)
                guard !Task.isCancelled,
                      fence.permits(scope: OfflineStore.shared.activeScopeId,
                                    scopeGeneration: OfflineStore.shared.scopeGeneration,
                                    selectionGeneration: self.selectionGeneration),
                      await AuthManager.currentUserId() == owner else {
                    self.finishDownload(for: selection); return
                }
                // Owner lookup suspends. Check the local scope and selected
                // embed again before handing plaintext to the OS export UI.
                guard !Task.isCancelled,
                      fence.permits(scope: OfflineStore.shared.activeScopeId,
                                    scopeGeneration: OfflineStore.shared.scopeGeneration,
                                    selectionGeneration: self.selectionGeneration) else {
                    self.finishDownload(for: selection); return
                }
                self.presentExport(bytes, filename: payload.filename, fence: fence, owner: owner)
            } catch {
                if !Task.isCancelled {
                    ToastManager.shared.show("Failed to download image", type: .error)
                }
            }
            self.finishDownload(for: selection)
        }
    }

    func cancel() {
        selectionGeneration = UUID()
        task?.cancel()
        task = nil
        isDownloading = false
        #if os(iOS)
        if let activityController {
            activityController.dismiss(animated: false)
            self.activityController = nil
            cleanupTemporaryFile()
        }
        #endif
    }

    private func finishDownload(for selection: UUID) {
        guard selectionGeneration == selection else { return }
        task = nil
        isDownloading = false
    }

    private func presentExport(_ bytes: Data, filename: String,
                               fence: ImageOriginalDownloadFence, owner: String) {
        #if os(iOS)
        do {
            let directory = FileManager.default.temporaryDirectory
                .appendingPathComponent("openmates-image-export", isDirectory: true)
                .appendingPathComponent(UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            var url = directory.appendingPathComponent(filename)
            temporaryURL = url
            try bytes.write(to: url, options: [.atomic, .completeFileProtection])
            try FileManager.default.setAttributes([
                .protectionKey: FileProtectionType.complete,
                .posixPermissions: 0o600,
            ], ofItemAtPath: url.path)
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            try url.setResourceValues(values)
            try NativeImagePreviewFile.requireCompleteProtectionOnDevice(at: url)
            guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
                  let root = scene.windows.first(where: { $0.isKeyWindow })?.rootViewController else {
                try? FileManager.default.removeItem(at: directory)
                return
            }
            var presenter = root
            while let presented = presenter.presentedViewController { presenter = presented }
            let activity = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            activity.completionWithItemsHandler = { [weak self, url] _, _, _, _ in
                Task { @MainActor in
                    try? FileManager.default.removeItem(at: directory)
                    guard self?.temporaryURL == url else { return }
                    self?.activityController = nil
                    self?.temporaryURL = nil
                }
            }
            if let popover = activity.popoverPresentationController {
                popover.sourceView = presenter.view
                popover.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.maxY, width: 1, height: 1)
            }
            activityController = activity
            presenter.present(activity, animated: true)
        } catch {
            cleanupTemporaryFile()
            ToastManager.shared.show("Failed to download image", type: .error)
        }
        #elseif os(macOS)
        let panel = NSSavePanel()
        panel.nameFieldStringValue = filename
        panel.canCreateDirectories = true
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            Task { @MainActor in
                guard let self,
                      fence.permits(scope: OfflineStore.shared.activeScopeId,
                                    scopeGeneration: OfflineStore.shared.scopeGeneration,
                                    selectionGeneration: self.selectionGeneration),
                      await AuthManager.currentUserId() == owner else { return }
                guard fence.permits(scope: OfflineStore.shared.activeScopeId,
                                    scopeGeneration: OfflineStore.shared.scopeGeneration,
                                    selectionGeneration: self.selectionGeneration) else { return }
            do {
                try bytes.write(to: url, options: .atomic)
            } catch {
                ToastManager.shared.show("Failed to download image", type: .error)
            }
            }
        }
        #endif
    }

    #if os(iOS)
    private func cleanupTemporaryFile() {
        if let temporaryURL {
            try? FileManager.default.removeItem(at: temporaryURL.deletingLastPathComponent())
        }
        temporaryURL = nil
    }
    #endif
}

struct ImageEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    var accessibilityPrefix: String = "sent-image"

    private var filename: String? { data?["filename"]?.value as? String }
    private var s3Url: String? { EmbedMediaPayload.s3URL(from: data) }
    private var s3Key: String? { EmbedMediaPayload.s3Key(from: data) }
    private var aesKey: String? { EmbedMediaPayload.string(data, keys: ["aes_key"]) }
    private var aesNonce: String? { EmbedMediaPayload.string(data, keys: ["aes_nonce"]) }
    private var encryption: String? { EmbedMediaPayload.encryption(from: data) }

    private var renderedS3Url: String? {
        switch mode {
        case .preview: EmbedMediaPayload.previewS3URL(from: data)
        case .fullscreen: s3Url
        }
    }

    private var renderedS3Key: String? {
        switch mode {
        case .preview: EmbedMediaPayload.previewS3Key(from: data)
        case .fullscreen: s3Key
        }
    }

    var body: some View {
        switch mode {
        case .preview:
            if renderedS3Url != nil && aesKey != nil {
                EncryptedImageView(
                    s3Url: renderedS3Url, s3Key: renderedS3Key, aesKey: aesKey, aesNonce: aesNonce, encryption: encryption,
                    contentMode: .fill
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .clipped()
                .accessibilityIdentifier("\(accessibilityPrefix)-thumbnail")
            } else {
                GeometryReader { proxy in
                    VStack(alignment: .leading, spacing: .spacing3) {
                        Capsule().fill(Color.grey20).frame(width: proxy.size.width * 0.8, height: 12)
                        Capsule().fill(Color.grey20).frame(width: proxy.size.width * 0.5, height: 12)
                    }
                }
                .padding(.horizontal, .spacing10)
                .padding(.vertical, .spacing8)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("\(accessibilityPrefix)-thumbnail")
            }

        case .fullscreen:
            Group {
                if s3Url != nil && aesKey != nil {
                    TappableEncryptedImageView(
                        s3Url: s3Url,
                        s3Key: s3Key,
                        aesKey: aesKey,
                        aesNonce: aesNonce,
                        encryption: encryption,
                        filename: filename
                    )
                    .accessibilityIdentifier("\(accessibilityPrefix)-fullscreen-image")
                } else {
                    ProgressView()
                        .tint(Color(hex: 0x5B8DD9))
                        .scaleEffect(1.45)
                        .accessibilityIdentifier("image-loading")
                }
            }
            .frame(maxWidth: .infinity)
            .frame(minHeight: 560)
            .accessibilityIdentifier("\(accessibilityPrefix)-fullscreen")
        }
    }
}

/// Resolves an images/view skill result back to the uploaded image whose media
/// payload is encrypted and stored separately. The web renderer performs the
/// same lookup before mounting ImageViewEmbedPreview.
struct ImageViewSkillModel {
    let skillEmbed: EmbedRecord
    let originalEmbed: EmbedRecord?

    init(embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        skillEmbed = embed
        let raw = embed.rawData ?? [:]
        let candidates = ["embed_id", "original_embed_id", "input_embed_id"]
            .compactMap { raw[$0]?.value as? String }
            .filter { !$0.isEmpty && $0 != embed.id }
        originalEmbed = candidates.lazy.compactMap { allEmbedRecords[$0] }.first
    }

    var resolvedData: [String: AnyCodable]? {
        var resolved = skillEmbed.rawData ?? [:]
        if let originalData = originalEmbed?.rawData {
            for (key, value) in originalData {
                resolved[key] = value
            }
        }
        return resolved.isEmpty ? nil : resolved
    }

    var originalEmbedId: String? { originalEmbed?.id }
}
