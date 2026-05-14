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
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return explicit }
        return allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id || EmbedType(rawValue: $0.type) == .eventsEvent }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
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

private struct EventsSearchPreview: View {
    let data: [String: AnyCodable]?
    let events: [EventResultSummary]

    private var query: String {
        EventValue.string(data ?? [:], ["query", "title"]) ?? events.first?.title ?? "Events"
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
        guard let raw = data?["results"]?.value as? [[String: Any]] else { return [] }
        return raw.enumerated().map { index, dict in
            EventResultSummary(embedId: "legacy-event-\(index)", data: dict.mapValues(AnyCodable.init))
        }
    }
}
