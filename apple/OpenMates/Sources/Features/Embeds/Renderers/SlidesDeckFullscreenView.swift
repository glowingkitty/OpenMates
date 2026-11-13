// SlidesDeckFullscreenView — read-only fullscreen viewer of a slides deck: the
// current slide scaled to fit, previous/next buttons, "n / total" position and a
// strip of slide thumbnails. Present mode, presenter view and the editor are not
// part of this view yet.
// Specification: specifications/features/slides/specification.yml
// Assertions: slides.render.preview-and-fullscreen

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/slides/SlidesDeckEmbedFullscreen.svelte
// CSS:     frontend/packages/ui/src/components/embeds/slides/SlidesDeckEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

/// Slide index and build step of the viewer (mirrors `next`/`previous`/`select`
/// of `SlidesDeckEmbedFullscreen.svelte`).
struct SlidesDeckNavigation: Equatable {
    private(set) var index = 0
    private(set) var step = 0
    let stepCounts: [Int]

    init(deck: SlideDeckRecord?) {
        stepCounts = (deck?.slides ?? []).map { slide in
            slide.elements.map { Int($0.step) }.max() ?? 0
        }
    }

    var total: Int { stepCounts.count }
    var canGoPrevious: Bool { index > 0 || step > 0 }
    var canGoNext: Bool { index < total - 1 || (index < total && step < stepCounts[index]) }
    var positionLabel: String { "\(index + 1) / \(total)" }

    mutating func next() {
        guard index < total else { return }
        if step < stepCounts[index] {
            step += 1
        } else if index < total - 1 {
            index += 1
            step = 0
        }
    }

    mutating func previous() {
        if step > 0 {
            step -= 1
        } else if index > 0 {
            index -= 1
            step = stepCounts[index]
        }
    }

    mutating func select(_ target: Int) {
        guard target >= 0, target < total else { return }
        index = target
        step = 0
    }
}

@MainActor struct SlidesDeckFullscreenView: View {
    let deck: SlideDeckRecord?
    let title: String
    @State private var navigation: SlidesDeckNavigation

    init(deck: SlideDeckRecord?, title: String) {
        self.deck = deck
        self.title = title
        _navigation = State(initialValue: SlidesDeckNavigation(deck: deck))
    }

    var body: some View {
        Group {
            if let deck, navigation.total > 0 {
                viewer(deck: deck)
            } else {
                Text(AppStrings.slidesNoContent)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, minHeight: 120)
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("slides-deck-fullscreen")
    }

    private func viewer(deck: SlideDeckRecord) -> some View {
        let slide = deck.slides[min(navigation.index, deck.slides.count - 1)]
        return VStack(spacing: .spacing8) {
            SlideCanvasView(
                slide: slide, width: CGFloat(deck.width), height: CGFloat(deck.height),
                step: navigation.step
            )
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            controls
            strip(deck: deck)
        }
    }

    private var controls: some View {
        HStack(spacing: .spacing8) {
            OMIconButton(icon: "back", label: AppStrings.slidesPrevious) { navigation.previous() }
                .disabled(!navigation.canGoPrevious)
                .opacity(navigation.canGoPrevious ? 1 : 0.4)
                .accessibilityIdentifier("slide-prev")
            Text(navigation.positionLabel)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("slide-position")
            OMIconButton(icon: "back", label: AppStrings.slidesNext) { navigation.next() }
                .rotationEffect(.degrees(180))
                .disabled(!navigation.canGoNext)
                .opacity(navigation.canGoNext ? 1 : 0.4)
                .accessibilityIdentifier("slide-next")
        }
    }

    private func strip(deck: SlideDeckRecord) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spacing4) {
                ForEach(Array(deck.slides.enumerated()), id: \.offset) { position, slide in
                    Button { navigation.select(position) } label: {
                        SlideCanvasView(slide: slide, width: CGFloat(deck.width), height: CGFloat(deck.height))
                            .frame(width: 120)
                            .clipShape(RoundedRectangle(cornerRadius: .radius2))
                            .overlay(
                                RoundedRectangle(cornerRadius: .radius2)
                                    .stroke(position == navigation.index ? Color.buttonPrimary : Color.clear, lineWidth: 2)
                            )
                            .allowsHitTesting(false)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(AppStrings.slidesSlideLabel) \(position + 1)")
                    .accessibilityIdentifier("slide-strip-item")
                }
            }
        }
        .accessibilityLabel(AppStrings.slidesStripLabel)
    }
}
