// ImageResultEmbedRenderer — native counterpart for image result embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageResultEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ImageResultEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @Environment(\.openURL) private var openURL

    private var title: String? { data?["title"]?.value as? String }
    private var url: String? {
        data?["image_url"]?.value as? String
            ?? data?["thumbnail_url"]?.value as? String
            ?? data?["thumbnail_original"]?.value as? String
            ?? data?["image"]?.value as? String
            ?? data?["url"]?.value as? String
    }
    private var thumbnailUrl: String? {
        data?["thumbnail_url"]?.value as? String
            ?? data?["thumbnail_original"]?.value as? String
    }
    private var sourcePageUrl: String? { data?["source_page_url"]?.value as? String ?? data?["url"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            if let url, let imgURL = URL(string: url) {
                ZStack(alignment: .topLeading) {
                    CachedRemoteImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fit)
                    } placeholder: {
                        Color.grey20.overlay(ProgressView())
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                    if let title, !title.isEmpty {
                        Text(title)
                            .font(.omXxs)
                            .fontWeight(.medium)
                            .foregroundStyle(.white.opacity(0.95))
                            .lineLimit(2)
                            .padding(.horizontal, 14)
                            .padding(.top, 12)
                            .padding(.bottom, 32)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                LinearGradient(
                                    colors: [.black.opacity(0.5), .clear],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.grey20)
            }

        case .fullscreen:
            VStack(alignment: .leading, spacing: 0) {
                if let url, let imgURL = URL(string: url) {
                    ZStack {
                        if let thumbnailUrl, let thumbURL = URL(string: thumbnailUrl) {
                            CachedRemoteImage(url: thumbURL) { image in
                                image.resizable().aspectRatio(contentMode: .fit).blur(radius: 2)
                            } placeholder: { Color.grey20 }
                        }
                        CachedRemoteImage(url: imgURL) { image in
                            image.resizable().aspectRatio(contentMode: .fit)
                        } placeholder: { ProgressView() }
                    }
                    .contentShape(Rectangle())
                    .onTapGesture {
                        NativeImagePreviewer.shared.previewRemoteImage(imgURL, suggestedFilename: title)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.spacing8)
                    .background(Color.grey10)
                }
                if let title {
                    Text(title)
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey100)
                        .padding(.horizontal, .spacing8)
                        .padding(.top, .spacing6)
                }
                if let sourcePageUrl, let sourceURL = URL(string: sourcePageUrl) {
                    Button { openURL(sourceURL) } label: {
                        HStack(spacing: .spacing3) {
                            Icon("web", size: 16)
                            Text(LocalizationManager.shared.text("embeds.image_search.view_source"))
                        }
                        .font(.omXs)
                        .fontWeight(.medium)
                        .foregroundStyle(LinearGradient.primary)
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, .spacing8)
                    .padding(.top, .spacing6)
                }
                if let url, let imageURL = URL(string: url) {
                    Button { openURL(imageURL) } label: {
                        HStack(spacing: .spacing3) {
                            Icon("image", size: 16)
                            Text(LocalizationManager.shared.text("embeds.image_search.open_image"))
                        }
                        .font(.omXs)
                        .fontWeight(.medium)
                        .foregroundStyle(LinearGradient.primary)
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, .spacing8)
                    .padding(.top, .spacing6)
                }
            }
        }
    }
}

