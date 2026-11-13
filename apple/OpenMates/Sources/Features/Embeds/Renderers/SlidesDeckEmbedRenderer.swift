// SlidesDeckEmbedRenderer — slides deck embed: first-slide thumbnail card in
// preview mode, SlidesDeckFullscreenView in fullscreen mode. The deck markup is
// parsed by the Rust core (`slideDeckFromMarkup`); Swift only draws the records.
// Specification: specifications/features/slides/specification.yml
// Assertions: slides.render.preview-and-fullscreen

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/slides/SlidesDeckEmbedPreview.svelte
// CSS:     frontend/packages/ui/src/components/embeds/slides/SlidesDeckEmbedPreview.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

/// Parsed deck of an embed's `slides_markup` field; nil while the markup is not
/// yet normalised (streaming) or empty.
enum SlidesDeckContent {
    static func markup(data: [String: AnyCodable]?) -> String {
        (data?["slides_markup"]?.value as? String) ?? ""
    }

    static func deck(data: [String: AnyCodable]?) -> SlideDeckRecord? {
        let source = markup(data: data)
        guard !source.isEmpty else { return nil }
        return try? slideDeckFromMarkup(markup: source)
    }

    /// Deck title: embed `title`, else the markup title, else "Presentation".
    @MainActor static func title(data: [String: AnyCodable]?, deck: SlideDeckRecord?) -> String {
        if let title = data?["title"]?.value as? String, !title.isEmpty { return title }
        if let title = deck?.title, !title.isEmpty { return title }
        return AppStrings.slidesDeckDefaultTitle
    }

    @MainActor static func countLabel(_ count: Int) -> String {
        count > 0 ? "\(count) \(count == 1 ? AppStrings.slidesCountSingular : AppStrings.slidesCountPlural)" : ""
    }
}

@MainActor struct SlidesDeckEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let embedID: String

    var body: some View {
        let deck = SlidesDeckContent.deck(data: data)
        switch mode {
        case .preview:
            preview(deck: deck)
        case .fullscreen:
            SlidesDeckFullscreenView(deck: deck, title: SlidesDeckContent.title(data: data, deck: deck))
        }
    }

    private func preview(deck: SlideDeckRecord?) -> some View {
        Group {
            if let deck, let first = deck.slides.first {
                SlideCanvasView(slide: first, width: CGFloat(deck.width), height: CGFloat(deck.height))
                    .clipShape(RoundedRectangle(cornerRadius: .radius2))
                    .allowsHitTesting(false)
                    .padding(.spacing4)
            } else {
                Icon("slides", size: 48).foregroundStyle(Color.grey50)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey20)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("slides-deck-preview")
    }
}
