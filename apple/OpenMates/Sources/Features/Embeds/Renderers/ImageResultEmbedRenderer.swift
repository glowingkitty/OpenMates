// ImageResultEmbedRenderer — native counterpart for image result embeds.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.layout.responsive-history
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageResultEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct ImageResultEmbedRenderer: View {
    @Environment(\.recipientMediaContext) private var recipientMediaContext
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @Environment(\.openURL) private var openURL
    @State private var previewFailed = false
    @State private var fullImageFailed = false
    @State private var thumbnailFailed = false
    @State private var fullscreenContentWidth: CGFloat = 0

    private var fullscreenImageMaximumHeight: CGFloat {
        #if os(iOS)
        let viewport = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.windows.first(where: { $0.isKeyWindow })?.bounds.size }
            .first ?? UIScreen.main.bounds.size
        #elseif os(macOS)
        let viewport = NSApp.keyWindow?.contentView?.bounds.size
            ?? NSScreen.main?.visibleFrame.size ?? CGSize(width: 900, height: 900)
        #endif
        let contentWidth = fullscreenContentWidth > 0 ? fullscreenContentWidth : viewport.width
        return min(viewport.height * 0.6, contentWidth <= 560 ? 520 : 720)
    }

    private var title: String? { data?["title"]?.value as? String }
    private var rawImageURL: String? {
        data?["image_url"]?.value as? String
            ?? data?["thumbnail_url"]?.value as? String
            ?? data?["thumbnail_original"]?.value as? String
            ?? data?["image"]?.value as? String
    }
    private var rawThumbnailURL: String? {
        data?["thumbnail_url"]?.value as? String
            ?? data?["thumbnail_original"]?.value as? String
    }
    private var previewURL: URL? {
        EmbedFieldReader.proxiedImageURL(rawImageURL, maxWidth: 520).flatMap(URL.init(string:))
    }
    private var fullURL: URL? {
        EmbedFieldReader.proxiedImageURL(rawImageURL, maxWidth: 1024).flatMap(URL.init(string:))
    }
    private var thumbnailURL: URL? {
        EmbedFieldReader.proxiedImageURL(rawThumbnailURL, maxWidth: 520).flatMap(URL.init(string:))
    }
    private var sourcePageUrl: String? { data?["source_page_url"]?.value as? String ?? data?["url"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            GeometryReader { viewport in
                if let previewURL, !previewFailed {
                    CachedRemoteImage(url: previewURL, onFailure: { previewFailed = true }) { image in
                        // Web .result-image: width/height100%, object-fit:contain.
                        // Bound the bitmap to the proposed card viewport so its
                        // aspect ratio cannot widen a 320pt search result card.
                        image.resizable().aspectRatio(contentMode: .fit)
                            .frame(width: viewport.size.width, height: viewport.size.height)
                            .clipped()
                            .overlay(alignment: .topLeading) { previewTitle }
                            .accessibilityIdentifier("image-result-preview-image")
                    } placeholder: {
                        Color(hex: 0xEBEBEB)
                    }
                } else {
                    placeholderIcon(size: 28)
                        .frame(width: viewport.size.width, height: viewport.size.height)
                        .background(Color(hex: 0xEBEBEB))
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipped()
            .background(Color(hex: 0xEBEBEB))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("image-result-preview-content")

        case .fullscreen:
            VStack(alignment: .leading, spacing: 0) {
                ZStack {
                    if let fullURL, !fullImageFailed {
                        CachedRemoteImage(url: fullURL, onFailure: { fullImageFailed = true }) { image in
                            image.resizable().aspectRatio(contentMode: .fit)
                                .frame(maxHeight: fullscreenImageMaximumHeight)
                                .accessibilityIdentifier("image-result-fullscreen-image")
                        } placeholder: {
                            fullscreenThumbnail(blurred: true)
                        }
                    } else {
                        fullscreenThumbnail(blurred: false)
                    }
                }
                .frame(maxWidth: .infinity)
                .frame(minHeight: 200)
                .padding(.spacing8)
                .background(Color(hex: 0xFAFAFA))
                .contentShape(Rectangle())
                .onTapGesture {
                    if recipientMediaContext == nil, let fullURL { NativeImagePreviewer.shared.previewRemoteImage(fullURL, suggestedFilename: title) }
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
                if let rawImageURL, let imageURL = URL(string: rawImageURL) {
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
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { fullscreenContentWidth = $0 }
            .padding(.horizontal, -.spacing8)
            .padding(.top, -.spacing10)
            .accessibilityIdentifier("image-result-fullscreen")
        }
    }

    @ViewBuilder private var previewTitle: some View {
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
                .background(LinearGradient(colors: [.black.opacity(0.5), .clear], startPoint: .top, endPoint: .bottom))
        }
    }

    @ViewBuilder private func fullscreenThumbnail(blurred: Bool) -> some View {
        if let thumbnailURL, !thumbnailFailed {
            CachedRemoteImage(url: thumbnailURL, onFailure: { thumbnailFailed = true }) { image in
                image.resizable().aspectRatio(contentMode: .fit)
                    .blur(radius: blurred ? 4 : 0)
                    .frame(maxHeight: fullscreenImageMaximumHeight)
            } placeholder: {
                placeholderIcon(size: 48)
            }
        } else {
            placeholderIcon(size: 48)
        }
    }

    private func placeholderIcon(size: CGFloat) -> some View {
        Icon("image", size: size)
            .foregroundStyle(Color.grey40)
            .frame(width: size == 48 ? 200 : size, height: size == 48 ? 200 : size)
            .background(size == 48 ? Color(hex: 0xEBEBEB) : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: size == 48 ? .radius7 : 0))
            .accessibilityIdentifier(size == 48 ? "image-result-fullscreen-placeholder" : "image-result-preview-placeholder")
    }
}
