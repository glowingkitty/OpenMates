// TravelSearchEmbedRenderer — native counterpart for travel search embeds.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.assistant-document-convergence
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte
// CSS:     TravelSearchEmbedPreview.svelte (.travel-search-details, .search-date, .provider-row)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

/// Request metadata survives a finished search with no providers or child results.
/// Persisted parents may contain nested JSON or flattened TOON fields.
@MainActor
struct TravelSearchPresentation {
    struct Provider: Identifiable {
        let id: String
        let name: String
        let iconURL: String?
    }

    let childEmbeds: [EmbedRecord]
    let connections: [TravelConnectionSummary]
    let route: String
    let previewDate: String?
    let fullscreenDate: String?
    let providers: [Provider]
    let legacyProvider: String?
    let resultCount: Int
    let status: EmbedStatus

    nonisolated static func isSearch(_ embed: EmbedRecord) -> Bool {
        if EmbedType.normalized(rawValue: embed.type) == .travelConnections { return true }
        return (embed.appId ?? TravelValue.string(embed.rawData, ["app_id"])) == "travel"
            && (embed.skillId ?? TravelValue.string(embed.rawData, ["skill_id"])) == "search_connections"
    }

    init(embed: EmbedRecord, data: [String: AnyCodable]? = nil,
         allEmbedRecords: [String: EmbedRecord] = [:],
         locale: Locale = .current, timeZone: TimeZone = .current) {
        let raw = data ?? embed.rawData ?? [:]
        status = embed.status
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        let parented = allEmbedRecords.values.filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        var seen = Set<String>()
        childEmbeds = (explicit.isEmpty ? parented : explicit).filter { seen.insert($0.id).inserted }
        var rows = Self.rows(raw, key: "results")
        if rows.isEmpty, let toon = TravelValue.string(raw, ["results_toon"]) {
            rows = Self.rows(EmbedRecord.parseContent(toon).mapValues(AnyCodable.init), key: "results")
        }
        let groups = rows.filter { !$0.keys.filter({ $0 == "results" || $0 == "legs" || $0 == "query"
            || $0.hasPrefix("results_") || $0.hasPrefix("legs_") }).isEmpty }
        let resultRows = groups.isEmpty ? rows : groups.flatMap { Self.rows($0, key: "results") }
        connections = childEmbeds.isEmpty
            ? resultRows.enumerated().map { TravelConnectionSummary(embedId: "\(embed.id)-result-\($0.offset)", data: $0.element) }
            : childEmbeds.map { TravelConnectionSummary(embedId: $0.id, data: $0.rawData ?? [:]) }
        let groupLegs = groups.first.map { Self.rows($0, key: "legs") } ?? []
        let legs = groupLegs.isEmpty ? Self.rows(raw, key: "legs") : groupLegs
        if let resultRoute = connections.first?.routeFull {
            route = resultRoute
        } else if let origin = TravelValue.string(legs.first, ["origin"]),
                  let destination = TravelValue.string(legs.last, ["destination"]) {
            route = "\(origin) → \(destination)"
        } else if let query = TravelValue.string(groups.first, ["query"]) {
            route = query
        } else if let origin = TravelValue.string(raw, ["origin"]),
                  let destination = TravelValue.string(raw, ["destination"]) {
            route = "\(origin) → \(destination)"
        } else {
            route = TravelValue.string(raw, ["query"]) ?? ""
        }
        let date = connections.first?.departure ?? TravelValue.string(legs.first, ["date"])
            ?? TravelValue.string(raw, ["date"])
        previewDate = date.map { TravelValue.formatDate($0, locale: locale, timeZone: timeZone) }
        fullscreenDate = date.map { TravelValue.formatDate($0, locale: locale, timeZone: timeZone, includesYear: true) }
        let topProviders = Self.rows(raw, key: "providers")
        let providerRows = topProviders.isEmpty ? groups.flatMap { Self.rows($0, key: "providers") } : topProviders
        var providerIDs = Set<String>()
        providers = providerRows.compactMap { provider in
            guard let name = TravelValue.string(provider, ["name", "id"]) else { return nil }
            let id = TravelValue.string(provider, ["id"]) ?? name
            guard providerIDs.insert(id).inserted else { return nil }
            return Provider(id: id, name: name, iconURL: EmbedFieldReader.proxiedFaviconImageURL(directURL: TravelValue.string(provider, ["icon_url"]), pageURL: nil))
        }
        legacyProvider = TravelValue.string(raw, ["provider"])
        let groupedCount = groups.reduce(0) { $0 + (TravelValue.int($1, ["result_count"]) ?? 0) }
        resultCount = !connections.isEmpty ? connections.count : groupedCount > 0 ? groupedCount
            : TravelValue.int(raw, ["result_count"]) ?? embed.childEmbedIds.count
    }

    /// Reads both `legs: [{...}]` and persisted `legs_0_origin` fields without
    /// assuming zero-provider metadata arrays contain a result card.
    private static func rows(_ raw: [String: AnyCodable], key: String) -> [[String: AnyCodable]] {
        let nested = EmbedFieldReader.dictionaryArray(raw, key: key)
        if !nested.isEmpty { return nested.map { $0.mapValues(AnyCodable.init) } }
        var indexed: [Int: [String: AnyCodable]] = [:]
        for (field, value) in raw where field.hasPrefix(key + "_") {
            let tail = field.dropFirst(key.count + 1)
            guard let split = tail.firstIndex(of: "_"), let index = Int(tail[..<split]) else { continue }
            indexed[index, default: [:]][String(tail[tail.index(after: split)...])] = value
        }
        return indexed.keys.sorted().compactMap { indexed[$0] }
    }

    var countText: String {
        "\(resultCount) \(AppStrings.localized(resultCount == 1 ? "embeds.connection" : "embeds.connections"))"
    }
    var previewProviderText: String? {
        guard providers.isEmpty, !connections.isEmpty, let legacyProvider else { return nil }
        return "\(AppStrings.localized("embeds.via")) \(legacyProvider)"
    }
    var fullscreenTitle: String {
        [route, fullscreenDate].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: "  ·  ")
    }
    var fullscreenSubtitle: String {
        let provider = providers.isEmpty ? legacyProvider : providers.map(\.name).joined(separator: ", ")
        let attribution = provider.map { "\(AppStrings.localized("embeds.via")) \($0)" }
        return [countText, attribution, priceText(fullscreen: true)].compactMap { $0 }.joined(separator: "  ·  ")
    }
    func priceText(fullscreen: Bool = false) -> String? {
        let priced = connections.filter { $0.priceNumber != nil }
        guard let first = priced.first, let minimum = priced.compactMap(\.priceNumber).min() else { return nil }
        let price = "\(first.currency) \(String(format: "%.0f", minimum))"
        return fullscreen || priced.count > 1 ? "\(AppStrings.localized("embeds.from")) \(price)" : price
    }
}

struct TravelSearchEmbedRenderer: View {
    let mode: EmbedDisplayMode
    let onOpenEmbed: (EmbedRecord) -> Void
    private let model: TravelSearchPresentation

    init(embed: EmbedRecord, data: [String: AnyCodable]?, mode: EmbedDisplayMode,
         allEmbedRecords: [String: EmbedRecord], onOpenEmbed: @escaping (EmbedRecord) -> Void) {
        self.mode = mode
        self.onOpenEmbed = onOpenEmbed
        model = TravelSearchPresentation(embed: embed, data: data, allEmbedRecords: allEmbedRecords)
    }

    var body: some View {
        switch mode {
        case .preview:
            TravelSearchPreview(model: model)
        case .fullscreen:
            TravelSearchFullscreen(model: model, onOpenEmbed: onOpenEmbed)
        }
    }
}

private struct TravelSearchPreview: View {
    let model: TravelSearchPresentation

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(model.route)
                .font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary).lineLimit(3)
                .accessibilityIdentifier("travel-search-route")
            if let departure = model.previewDate {
                Text(departure).font(.omSmall).fontWeight(.medium).foregroundStyle(Color.grey80)
                    .accessibilityIdentifier("travel-search-date")
            }
            if !model.providers.isEmpty {
                HStack(spacing: .spacing2) {
                    Text(AppStrings.localized("embeds.via")).foregroundStyle(Color.grey60)
                    ForEach(model.providers) { provider in
                        if let iconURL = provider.iconURL, let url = URL(string: iconURL) {
                            AsyncImage(url: url) { image in image.resizable().scaledToFit() } placeholder: { Color.clear }
                                .frame(width: 16, height: 16).clipShape(Circle()).accessibilityHidden(true)
                        }
                        Text(provider.name).fontWeight(.semibold).foregroundStyle(Color.grey80)
                    }
                }
                .font(.omSmall)
                .accessibilityIdentifier("travel-search-provider")
            } else if let provider = model.previewProviderText {
                Text(provider).font(.omSmall).fontWeight(.medium).foregroundStyle(Color.grey70)
                    .accessibilityIdentifier("travel-search-provider")
            }
            if model.status == .finished {
                HStack(spacing: .spacing2) {
                    Text(model.countText).fontWeight(.medium).foregroundStyle(Color.grey70)
                        .accessibilityIdentifier("travel-search-count")
                    if let price = model.priceText() {
                        Text(price).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                    }
                }
                .font(.omSmall)
            }
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

private struct TravelSearchFullscreen: View {
    let model: TravelSearchPresentation
    let onOpenEmbed: (EmbedRecord) -> Void

    var body: some View {
        LazyVStack(spacing: .spacing8) {
            if model.connections.isEmpty {
                Text(AppStrings.localized("embeds.search_no_results"))
                    .font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, minHeight: 200)
                    .accessibilityIdentifier("search-no-results-message")
            } else {
                ForEach(Array(model.connections.enumerated()), id: \.element.id) { index, connection in
                    if let child = model.childEmbeds.first(where: { $0.id == connection.embedId }) {
                        Button { onOpenEmbed(child) } label: { TravelConnectionResultCard(connection: connection) }
                            .buttonStyle(.plain)
                    } else {
                        TravelConnectionResultCard(connection: connection)
                    }
                    if index < model.connections.count - 1 { Color.clear.frame(height: .spacing1) }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }
}
