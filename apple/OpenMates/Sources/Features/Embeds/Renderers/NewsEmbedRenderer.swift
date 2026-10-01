// Native news article preview; the shared website detail retains source navigation.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/news/NewsEmbedPreview.svelte
//         frontend/packages/ui/src/components/embeds/news/NewsEmbedFullscreen.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

enum NewsPreviewLayout {
    // .news-preview-image is fixed at 150x171, translated 20px to the card edge.
    static let imageWidth: CGFloat = 150
    static let imageHeight: CGFloat = 171
    static func descriptionWidth(containerWidth: CGFloat, hasImage: Bool) -> CGFloat {
        max(0, containerWidth - (hasImage ? imageWidth : 0))
    }
}

struct NewsEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @State private var imageFailed = false
    @State private var imageLoaded = false

    private var description: String? {
        EmbedFieldReader.strippedHTML(EmbedFieldReader.string(data ?? [:], keys: ["description", "snippet", "summary"]))
    }
    private var imageURL: URL? {
        guard !imageFailed else { return nil }
        return EmbedFieldReader.proxiedImageURL(EmbedFieldReader.string(data ?? [:], keys: [
            "thumbnail_original", "thumbnail.original", "thumbnail_url", "preview_image_url", "image", "image_url", "og_image"
        ]), maxWidth: 520).flatMap(URL.init(string:))
    }

    var body: some View {
        if mode == .fullscreen {
            WebsiteEmbedRenderer(data: data, mode: mode)
        } else {
            GeometryReader { bounds in
                HStack(alignment: .top, spacing: 0) {
                    if let description {
                        Text(description).font(.omSmall).fontWeight(.medium).foregroundStyle(Color.grey70)
                            .lineSpacing(2.1).padding(.vertical, 1.05).lineLimit(6)
                            .frame(width: NewsPreviewLayout.descriptionWidth(containerWidth: bounds.size.width,
                                                                          hasImage: imageURL != nil), alignment: .topLeading)
                            .padding(.top, .spacing5)
                            .accessibilityIdentifier("news-preview-description")
                    }
                    if let imageURL {
                        CachedRemoteImage(url: imageURL, onFailure: {
                            imageLoaded = false
                            imageFailed = true
                        }, onSuccess: { imageLoaded = true }) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: { Color.grey20 }
                        .frame(width: description == nil ? bounds.size.width : NewsPreviewLayout.imageWidth,
                               height: description == nil ? bounds.size.height : NewsPreviewLayout.imageHeight)
                        .clipped()
                        .contentShape(Rectangle())
                        .offset(x: description == nil ? 0 : 20)
                        // Publish the clipped viewport, not the aspect-fill
                        // image's larger underlying accessibility bounds.
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(EmbedFieldReader.string(data ?? [:], keys: ["title"]) ?? AppStrings.search)
                        .accessibilityIdentifier("news-preview-image")
                        .accessibilityValue(imageLoaded ? "loaded" : "loading")
                    }
                }
            }
            .task(id: data?["url"]?.value as? String) { imageLoaded = false; imageFailed = false }
        }
    }
}
