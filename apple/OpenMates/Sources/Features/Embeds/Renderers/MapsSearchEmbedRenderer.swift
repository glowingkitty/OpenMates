// Maps search parent preview and map/list fullscreen.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/maps/MapsSearchEmbedPreview.svelte
//         frontend/packages/ui/src/components/embeds/maps/MapsSearchEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.assistant-document-convergence
import SwiftUI

struct MapsSearchEmbedRenderer: View {
    let embed: EmbedRecord
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void
    let model: MapsSearchEmbedModel
    @Environment(\.mapsMapViewportHeight) private var mapHeight
    @State private var containerWidth: CGFloat = 0

    init(embed: EmbedRecord, mode: EmbedDisplayMode, allEmbedRecords: [String: EmbedRecord],
         onOpenEmbed: @escaping (EmbedRecord) -> Void) {
        self.embed = embed
        self.mode = mode
        self.allEmbedRecords = allEmbedRecords
        self.onOpenEmbed = onOpenEmbed
        model = MapsSearchEmbedModel(embed: embed, allEmbedRecords: allEmbedRecords)
    }
    private var countLabel: String {
        "\(model.resultCount) \(AppStrings.localized(model.resultCount == 1 ? "embeds.place" : "embeds.places"))"
    }
    var body: some View {
        Group {
            if mode == .preview {
                SearchPreviewIdentityLayout(horizontalInset: .spacing6) {
                    Color.clear
                } inputs: {
                    VStack(alignment: .leading, spacing: .spacing2) {
                        Text(AppSkillInputPreviewModel(embed: embed).text ?? model.query)
                            .font(.omSmall.weight(.semibold)).lineLimit(3)
                            .accessibilityIdentifier("maps-search-query")
                        Text("\(AppStrings.via) \(model.provider)").font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                } summary: {
                    if let error = model.error {
                        Text(error).font(.omXs).foregroundStyle(Color.error).lineLimit(1)
                            .accessibilityIdentifier("maps-search-preview-error")
                    } else if model.state == .results {
                        Text(countLabel).font(.omXs.weight(.semibold))
                            .accessibilityIdentifier("maps-search-result-count")
                    } else if model.state == .empty || model.state == .filtered {
                        Text(AppStrings.localized(model.state == .filtered
                            ? "embeds.maps.search.no_verified_amenities" : "embeds.no_results"))
                            .font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                    }
                }
                .accessibilityIdentifier("maps-search-preview")
            } else {
                VStack(alignment: .leading, spacing: .spacing4) {
                    Text("\(AppStrings.via) \(model.provider)").font(.omXs).foregroundStyle(Color.fontSecondary)
                    statusDetails
                    if model.resultCount > 0 {
                        Text(countLabel).font(.omSmall.weight(.semibold))
                            .accessibilityIdentifier("maps-search-result-count")
                        #if canImport(MapKit)
                        if let configuration = model.mapConfiguration {
                            if containerWidth >= 721 {
                                HStack(alignment: .top, spacing: 0) {
                                    ScrollView { resultCards }.frame(width: max(180, containerWidth * 0.34))
                                    EmbedFullscreenMapView(configuration: configuration, onMarkerSelection: openMarker)
                                        .id(model.mapIdentity)
                                        .frame(maxWidth: .infinity)
                                }
                                .frame(height: max(240, mapHeight))
                            } else {
                                ScrollView(.horizontal) {
                                    HStack(spacing: .spacing3) {
                                        ForEach(model.results) { child in
                                            placeCard(child).frame(width: min(300, max(1, containerWidth - 28)), height: 200)
                                        }
                                    }
                                    .padding(.horizontal, .spacing4)
                                }
                                .accessibilityIdentifier("embeds-map-view-carousel")
                                EmbedFullscreenMapView(configuration: configuration, onMarkerSelection: openMarker)
                                    .id(model.mapIdentity).frame(height: min(520, max(320, (mapHeight + 190) * 0.52)))
                            }
                        } else { resultCards }
                        #else
                        resultCards
                        #endif
                    }
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .background {
                    GeometryReader { proxy in
                        Color.clear.onAppear { containerWidth = proxy.size.width }
                            .onChange(of: proxy.size.width) { _, value in containerWidth = value }
                    }
                }
                .accessibilityIdentifier("maps-search-fullscreen")
            }
        }
        .foregroundStyle(Color.fontPrimary)
    }

    private func openMarker(_ id: String) {
        if let child = model.child(forMarkerID: id) { onOpenEmbed(child) }
    }

    private var resultCards: some View {
        LazyVStack(alignment: .leading, spacing: .spacing4) {
            ForEach(model.results) { child in
                placeCard(child)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("maps-search-results")
    }

    private func placeCard(_ child: EmbedRecord) -> some View {
        EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords, variant: .compact) {
            onOpenEmbed(child)
        }
        .environment(\.embedPreviewFillsGridCell, true)
        .accessibilityIdentifier("embed-preview-\(child.id)")
    }

    @ViewBuilder private var statusDetails: some View {
        if let error = model.error {
            Text(error).font(.omSmall).foregroundStyle(Color.error)
                .fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("maps-search-error")
        } else if model.state == .empty {
            Text(AppStrings.localized("embeds.no_results")).font(.omSmall)
                .accessibilityIdentifier("maps-no-results")
        }
        if model.state == .filtered {
            Text(AppStrings.localized("embeds.maps.search.no_verified_amenities"))
                .font(.omSmall.weight(.semibold)).accessibilityIdentifier("maps-no-verified-results-title")
        }
        if let verified = model.verifiedCount {
            Text("\(verified) \(AppStrings.localized("embeds.maps.search.verified_matches"))"
                + (model.candidateCount.map { " " + LocalizationManager.shared.text("embeds.maps.search.out_of_candidates", replacements: ["count": "\($0)"]) } ?? ""))
                .font(.omXs).accessibilityIdentifier("maps-filter-summary")
        }
        if !model.requiredAmenities.isEmpty {
            Text("\(AppStrings.localized("embeds.maps.search.required_amenities")): "
                + model.requiredAmenities.map { $0.replacingOccurrences(of: "_", with: " ") }.joined(separator: ", "))
                .font(.omXs).accessibilityIdentifier("maps-required-amenities")
        }
        ForEach(Array(model.warnings.enumerated()), id: \.offset) { _, warning in
            Text(warning).font(.omXs).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("maps-enrichment-warning")
        }
        if let coverage = model.coverage {
            Text(coverage).font(.omXs).foregroundStyle(Color.fontSecondary)
                .fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("maps-search-coverage")
        }
    }
}
