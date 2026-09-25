// ImageEmbedRenderer — native counterpart for uploaded image embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

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
                VStack(spacing: .spacing2) {
                    EncryptedImageView(
                        s3Url: renderedS3Url, s3Key: renderedS3Key, aesKey: aesKey, aesNonce: aesNonce, encryption: encryption,
                        contentMode: .fill
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    if let filename {
                        Text(filename)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(1)
                    }
                }
                .accessibilityIdentifier("\(accessibilityPrefix)-thumbnail")
            } else {
                VStack(spacing: .spacing3) {
                    Icon("image", size: 32).foregroundStyle(Color.fontTertiary)
                    if let filename {
                        Text(filename).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("\(accessibilityPrefix)-thumbnail")
            }

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let filename {
                    Text(filename).font(.omP).foregroundStyle(Color.fontPrimary)
                }
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
                }
            }
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
