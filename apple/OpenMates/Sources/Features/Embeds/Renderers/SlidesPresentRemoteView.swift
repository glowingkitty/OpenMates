// SlidesPresentRemoteView — phone remote for a deck presented on another device:
// "Being presented on another device" bar with a Remote button, and the inline
// remote panel (position, Previous, Next, slide list, local-only notes).
// Specification: specifications/features/slides/specification.yml
// Assertions: slides.present.remote-control

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/slides/SlidesPresentRemote.svelte
//          frontend/packages/ui/src/components/embeds/slides/SlidesDeckEmbedFullscreen.svelte (.elsewhere bar)
// CSS:     same files
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

extension AppStrings {
    static var slidesRemoteOpen: String { LocalizationManager.shared.text("embeds.slides_remote_open") }
    static var slidesPresentingElsewhere: String { LocalizationManager.shared.text("embeds.slides_presenting_elsewhere") }
    static var slidesRemoteNotPresenting: String { LocalizationManager.shared.text("embeds.slides_remote_not_presenting") }
    static var slidesRemoteShowNotes: String { LocalizationManager.shared.text("embeds.slides_remote_show_notes") }
    static var slidesRemoteHideNotes: String { LocalizationManager.shared.text("embeds.slides_remote_hide_notes") }
    static var slidesRemoteSlides: String { LocalizationManager.shared.text("embeds.slides_remote_slides") }
    static var slidesRemoteClose: String { LocalizationManager.shared.text("embeds.slides_remote_close") }
}

/// Bar plus remote panel of one deck; renders nothing while the deck is not presented elsewhere
/// and the panel is closed.
@MainActor struct SlidesPresentingElsewhereBar: View {
    @StateObject private var model: SlidesPresentRemoteModel
    @State private var panelOpen = false
    private let tick = Timer.publish(every: 5, on: .main, in: .common).autoconnect()

    init(embedId: String, deck: SlideDeckRecord?, client: SlidesRemoteCoreClient) {
        _model = StateObject(wrappedValue: SlidesPresentRemoteModel(embedId: embedId, deck: deck, client: client))
    }

    var body: some View {
        VStack(spacing: .spacing4) {
            if model.isPresenting {
                HStack(spacing: .spacing8) {
                    Text(AppStrings.slidesPresentingElsewhere)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontPrimary)
                        .accessibilityIdentifier("slides-presenting-elsewhere")
                    Spacer(minLength: 0)
                    Button { panelOpen.toggle() } label: {
                        Text(panelOpen ? AppStrings.slidesRemoteClose : AppStrings.slidesRemoteOpen)
                            .font(.omSmall)
                            .foregroundStyle(Color.buttonPrimary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("slides-remote-open")
                }
            }
            if panelOpen { SlidesPresentRemoteView(model: model) }
        }
        .onReceive(tick) { _ in model.expireIfStale() }
    }
}

@MainActor struct SlidesPresentRemoteView: View {
    @ObservedObject var model: SlidesPresentRemoteModel

    var body: some View {
        VStack(spacing: .spacing8) {
            if model.isPresenting {
                controls
                notesBlock
                slideList
            } else {
                Text(AppStrings.slidesRemoteNotPresenting)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("slides-remote-not-presenting")
            }
        }
        .padding(.spacing8)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("slides-remote-panel")
    }

    private var controls: some View {
        HStack(spacing: .spacing8) {
            OMIconButton(icon: "back", label: AppStrings.slidesPrevious) { Task { await model.previous() } }
                .disabled(!model.canGoPrevious)
                .opacity(model.canGoPrevious ? 1 : 0.4)
                .accessibilityIdentifier("slides-remote-prev")
            Text(model.positionLabel)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("slides-remote-position")
            OMIconButton(icon: "back", label: AppStrings.slidesNext) { Task { await model.next() } }
                .rotationEffect(.degrees(180))
                .disabled(!model.canGoNext)
                .opacity(model.canGoNext ? 1 : 0.4)
                .accessibilityIdentifier("slides-remote-next")
        }
    }

    private var notesBlock: some View {
        VStack(spacing: .spacing4) {
            Button { model.toggleNotes() } label: {
                Text(model.notesVisible ? AppStrings.slidesRemoteHideNotes : AppStrings.slidesRemoteShowNotes)
                    .font(.omSmall)
                    .foregroundStyle(Color.buttonPrimary)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("slides-remote-notes-toggle")
            if model.notesVisible {
                Text(model.notes)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier("slides-remote-notes")
            }
        }
    }

    private var slideList: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spacing4) {
                ForEach(Array(0..<model.total), id: \.self) { offset in
                    let position = offset + 1
                    Button { Task { await model.jump(toSlide: position) } } label: {
                        Text("\(position)")
                            .font(.omSmall)
                            .foregroundStyle(position == model.index + 1 ? Color.buttonPrimary : Color.fontSecondary)
                            .padding(.spacing4)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(AppStrings.slidesSlideLabel) \(position)")
                    .accessibilityIdentifier("slides-remote-slide-\(position)")
                }
            }
        }
        .accessibilityLabel(AppStrings.slidesRemoteSlides)
    }
}
