// EventsSearchEmbedRenderer — native counterpart for events search embeds.
// Renders the parent search preview and fullscreen grid using child event
// records, matching the Svelte events search and event child preview flow.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/events/EventEmbedPreview.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct EventsSearchEmbedRenderer: View {
    let embed: EmbedRecord
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private var childEmbeds: [EmbedRecord] {
        EventsSearchEmbedModel.childEmbeds(for: embed, in: allEmbedRecords)
    }

    private var events: [EventResultSummary] {
        let children = childEmbeds.map { EventResultSummary(embedId: $0.id, data: $0.rawData ?? [:]) }
        if !children.isEmpty { return children }
        return EventResultSummary.list(from: data)
    }

    var body: some View {
        switch mode {
        case .preview:
            EventsSearchPreview(data: data, events: events)
        case .fullscreen:
            EventsSearchFullscreen(
                events: events,
                childEmbeds: childEmbeds,
                allEmbedRecords: allEmbedRecords,
                onOpenEmbed: onOpenEmbed
            )
        }
    }
}

enum EventsSearchEmbedModel {
    static func query(
        from data: [String: AnyCodable]?,
        events: [EventResultSummary]
    ) -> String {
        EventValue.string(data ?? [:], ["query", "title"])
            ?? events.first?.title
            ?? "Events"
    }

    static func childEmbeds(
        for parent: EmbedRecord,
        in records: [String: EmbedRecord]
    ) -> [EmbedRecord] {
        let explicit = parent.childEmbedIds.compactMap { records[$0] }
        if !explicit.isEmpty { return explicit }
        return records.values
            .filter { $0.parentEmbedId == parent.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
    }
}

private struct EventsSearchPreview: View {
    let data: [String: AnyCodable]?
    let events: [EventResultSummary]

    private var query: String {
        EventsSearchEmbedModel.query(from: data, events: events)
    }

    private var providerText: String? {
        if let providers = data?["providers"]?.value as? [String], !providers.isEmpty {
            let labels = providers.map(providerLabel)
            if labels.count <= 2 { return "via \(labels.joined(separator: ", "))" }
            return "via \(labels[0]), \(labels[1]) +\(labels.count - 2)"
        }
        guard let provider = EventValue.string(data ?? [:], ["provider"]),
              !["auto", "none"].contains(provider)
        else { return nil }
        return "via \(providerLabel(provider))"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(query)
                .font(.omP)
                .fontWeight(.bold)
                .foregroundStyle(Color.grey100)
                .lineLimit(2)

            if let providerText {
                Text(providerText)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
            }

            if !events.isEmpty {
                HStack(spacing: .spacing3) {
                    Text("+ \(events.count) \(events.count == 1 ? "event" : "events")")
                        .font(.omXs)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.grey70)
                }
                .padding(.top, .spacing1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    private func providerLabel(_ provider: String) -> String {
        switch provider.lowercased() {
        case "meetup": return "Meetup"
        case "luma": return "Luma"
        case "google_events": return "Google"
        case "resident_advisor": return "Resident Advisor"
        case "siegessaeule": return "Siegessäule"
        case "classictic": return "Classictic"
        case "berlin_philharmonic": return "Berlin Philharmonic"
        case "bachtrack": return "Bachtrack"
        default: return provider
        }
    }
}

private struct EventsSearchFullscreen: View {
    let events: [EventResultSummary]
    let childEmbeds: [EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private let columns = [GridItem(.adaptive(minimum: 300), spacing: .spacing5)]

    var body: some View {
        if events.isEmpty {
            Text(LocalizationManager.shared.text("embeds.search_no_results"))
                .font(.omP)
                .fontWeight(.medium)
                .foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity, minHeight: 200)
        } else {
            LazyVGrid(columns: columns, spacing: .spacing5) {
                ForEach(events) { event in
                    if let child = childEmbeds.first(where: { $0.id == event.embedId }) {
                        EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords) {
                            onOpenEmbed(child)
                        }
                        .frame(width: 300, height: 200)
                    } else {
                        EventResultCard(event: event)
                            .frame(width: 300, height: 200)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

extension EventResultSummary {
    static func list(from data: [String: AnyCodable]?) -> [EventResultSummary] {
        guard let data else { return [] }
        let raw: [[String: Any]]
        if let direct = dictionaries(from: data["results"]?.value) {
            raw = direct
        } else if let preview = dictionaries(from: data["preview_results"]?.value) {
            raw = preview
        } else if let encoded = data["results_toon"]?.value as? String {
            raw = dictionaries(from: EmbedRecord.parseContent(encoded)["results"]) ?? []
        } else {
            raw = []
        }
        return raw.enumerated().map { index, dict in
            EventResultSummary(embedId: "legacy-event-\(index)", data: dict.mapValues(AnyCodable.init))
        }
    }

    private static func dictionaries(from value: Any?) -> [[String: Any]]? {
        if let value = value as? [[String: Any]] { return value }
        if let value = value as? [[String: AnyCodable]] {
            return value.map { $0.mapValues(\.value) }
        }
        return nil
    }
}
