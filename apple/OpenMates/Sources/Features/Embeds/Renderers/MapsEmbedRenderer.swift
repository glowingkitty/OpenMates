// Standalone Maps location and place cards share the cached static-image preview.
// Fullscreen uses the shared native map; MapKit is mounted only on fullscreen.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedPreview.svelte
//         frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/maps/MapLocationEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/EntryWithMapTemplate.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

private struct MapsMapViewportHeightKey: EnvironmentKey {
    static let defaultValue: CGFloat = 540
}
extension EnvironmentValues {
    var mapsMapViewportHeight: CGFloat {
        get { self[MapsMapViewportHeightKey.self] }
        set { self[MapsMapViewportHeightKey.self] = newValue }
    }
}

struct MapsEmbedRenderer: View {
    let model: MapsEmbedModel
    let mode: EmbedDisplayMode
    let isPlace: Bool
    @Environment(\.mapsMapViewportHeight) private var mapHeight

    init(data: [String: AnyCodable]?, mode: EmbedDisplayMode, isPlace: Bool) {
        model = MapsEmbedModel(data)
        self.mode = mode
        self.isPlace = isPlace
    }

    var body: some View {
        if mode == .preview {
            MapsLocationPreview(model: model)
        } else {
            EmbedMapDetailTemplate(mapConfiguration: model.mapConfiguration,
                wideMapHeight: max(150, mapHeight), narrowDetailInset: .spacing8,
                staticMapImageURL: model.mapImageURL) {
                MapsLocationDetails(model: model, isPlace: isPlace)
            }
        }
    }
}

private struct MapsLocationPreview: View {
    let model: MapsEmbedModel
    @State private var failedImageURL: URL?
    @State private var loadedImageURL: URL?

    var body: some View {
        Group {
            if let url = model.mapImageURL, failedImageURL != url {
                GeometryReader { viewport in
                    CachedRemoteImage(url: url,
                        onFailure: { failedImageURL = url },
                        onSuccess: { loadedImageURL = url }, svgContentMode: .fill) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: { Color.grey25 }
                    .frame(width: viewport.size.width, height: viewport.size.height)
                    .clipped()
                    .overlay(alignment: .bottomLeading) {
                        if let name = model.name {
                            Text(name)
                                .font(.omSmall.weight(.semibold))
                                .foregroundStyle(Color.grey0)
                                .lineLimit(1)
                                .padding(.horizontal, .spacing6)
                                .padding(.vertical, .spacing4)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(LinearGradient(colors: [.black.opacity(0.55), .clear], startPoint: .bottom, endPoint: .top))
                                // The footer overlays the bottom 61 points, as on web.
                                .accessibilityHidden(true)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .accessibilityElement(children: .ignore)
                .accessibilityIdentifier("maps-preview-image")
                .accessibilityValue(loadedImageURL == url ? "loaded" : "loading")
                .accessibilityLabel(model.name ?? AppStrings.domainLocation)
            } else {
                VStack(alignment: .leading, spacing: .spacing2) {
                    if model.locationType == nil || model.isNearby {
                        Text(AppStrings.locationNearby.uppercased())
                            .font(.omTiny.weight(.medium)).foregroundStyle(Color.grey60)
                    }
                    HStack(spacing: .spacing3) {
                        Icon(model.isTransit ? "travel" : "maps", size: 18)
                            .foregroundStyle(AppGradientPalette.colors(for: model.isTransit ? "travel" : "maps").start)
                        if let text = model.primaryName ?? model.address {
                            Text(text).font(.omSmall.weight(model.primaryName == nil ? .regular : .semibold))
                                .foregroundStyle(Color.grey100).lineLimit(1)
                                .accessibilityIdentifier("maps-preview-name")
                        }
                    }
                    if let placeType = model.placeType {
                        Text(placeType.uppercased()).font(.omXxs.weight(.medium))
                            .foregroundStyle(Color.grey60).lineLimit(1)
                    }
                    if model.primaryName != nil, let address = model.address {
                        Text(address).font(.omXs).foregroundStyle(Color.grey70).lineLimit(2)
                    }
                }
                .padding(.spacing4)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            }
        }
    }
}

// Exact web values where generated Swift typography/color tokens have no match.
// MapLocationEmbedFullscreen.svelte .place-title = 1.5rem (24px),
// .place-rating = 0.9375rem (15px) / 5px gap, .rating-star = #f5a623.
// MapsLocationEmbedFullscreen.svelte .location-title uses font-size-h2-mobile;
// tokens/sources/typography.yml resolves that distinct contract to 24pt too.
private enum MapsFullscreenWebStyle {
    static let placeTitle = Font.custom("Lexend Deca", size: 24).weight(.bold)
    static let locationTitle = Font.custom("Lexend Deca", size: 24).weight(.bold)
    static let ratingValue = Font.custom("Lexend Deca", size: 15).weight(.bold)
    static let ratingStar = Color(hex: 0xF5A623)
    static let ratingGap: CGFloat = 5
}

private struct MapsLocationDetails: View {
    let model: MapsEmbedModel
    let isPlace: Bool
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            if isPlace, let url = model.imageURL {
                GeometryReader { viewport in
                    CachedRemoteImage(url: url, svgContentMode: .fill) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: { Color.grey25 }
                    .frame(width: viewport.size.width, height: 160)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                }
                .frame(height: 160)
            }
            if let name = model.name {
                Text(name).font(isPlace ? MapsFullscreenWebStyle.placeTitle : MapsFullscreenWebStyle.locationTitle)
                    .foregroundStyle(Color.fontPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("maps-location-title")
            }
            if isPlace, let ratingText = model.ratingText {
                HStack(spacing: MapsFullscreenWebStyle.ratingGap) {
                    Icon("rating", size: 16).foregroundStyle(MapsFullscreenWebStyle.ratingStar)
                    Text(ratingText).font(MapsFullscreenWebStyle.ratingValue).foregroundStyle(Color.fontPrimary)
                    if let count = model.reviewCount {
                        Text("\(count.formatted()) \(AppStrings.localized("embeds.reviews"))")
                            // .rating-count is 14px and inherits body font-weight-p (500).
                            .font(.omSmall.weight(.medium)).foregroundStyle(Color.fontSecondary)
                    }
                }
                .accessibilityIdentifier("maps-place-rating")
            }
            if isPlace, let placeType = model.placeType {
                Text(placeType.uppercased()).font(.omXs.weight(.medium))
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("maps-place-type")
            }
            if let address = model.address {
                VStack(alignment: .leading, spacing: .spacing2) {
                    if model.isNearby {
                        Text(AppStrings.locationNearby.uppercased()).font(.omTiny.weight(.semibold))
                            .foregroundStyle(Color.fontSecondary)
                    }
                    Text(address).font(.omSmall).foregroundStyle(Color.fontPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("maps-location-address")
                }
            }
            if isPlace, let url = model.websiteURL, let label = model.websiteLabel {
                Button { openURL(url) } label: {
                    Text(label).font(.omSmall).underline().foregroundStyle(Color.fontPrimary)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("maps-place-website")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("map-location-fullscreen")
    }
}
