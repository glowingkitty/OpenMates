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

    private var filename: String? { data?["filename"]?.value as? String }
    private var s3Url: String? { EmbedMediaPayload.s3URL(from: data) }
    private var s3Key: String? { EmbedMediaPayload.s3Key(from: data) }
    private var aesKey: String? { EmbedMediaPayload.string(data, keys: ["aes_key"]) }
    private var aesNonce: String? { EmbedMediaPayload.string(data, keys: ["aes_nonce"]) }

    var body: some View {
        switch mode {
        case .preview:
            if s3Url != nil && aesKey != nil {
                EncryptedImageView(
                    s3Url: s3Url, s3Key: s3Key, aesKey: aesKey, aesNonce: aesNonce,
                    contentMode: .fill
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: .spacing3) {
                    Icon("image", size: 32).foregroundStyle(Color.fontTertiary)
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
                    TappableEncryptedImageView(
                        s3Url: s3Url,
                        s3Key: s3Key,
                        aesKey: aesKey,
                        aesNonce: aesNonce,
                        filename: filename
                    )
                }
            }
        }
    }
}
