// Fullscreen Add memory / Forget uses the existing encrypted memory lifecycle.
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.surface.semantic-parity
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/EmbedHeaderCtaButton.svelte
//         frontend/packages/ui/src/components/embeds/events/EventEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/home/HomeListingEmbedFullscreen.svelte
// Service: frontend/packages/ui/src/services/savedEmbedMemoryService.ts
// CSS: .embed-header-cta.secondary, .embed-header-cta.destructive
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
import SwiftUI

struct NativeEmbedMemoryConfig: Equatable {
    let appID: String
    let categoryID: String
    let itemKey: String
    let fields: [String: SettingsMemoryValue]

    func savedEntry(in entries: [SettingsMemoryEntry]) -> SettingsMemoryEntry? {
        let embedID = fields["embed_id"]?.string ?? ""
        return entries.first {
            !$0.isExample && $0.appId == appID && $0.categoryId == categoryID &&
            ($0.key == itemKey || (!embedID.isEmpty && $0.fields["embed_id"]?.string == embedID))
        }
    }

    @MainActor
    static func config(for embed: EmbedRecord) -> Self? {
        guard embed.status == .finished, !embed.id.isEmpty,
              let type = EmbedType.normalized(rawValue: embed.type), let raw = embed.rawData else { return nil }
        return config(type: type, embedID: embed.id, content: raw.mapValues(\.value))
    }

    // Accept already hydrated selected-child content; never save a search parent.
    @MainActor
    static func config(type: EmbedType, embedID: String, content d: [String: Any]) -> Self? {
        guard !embedID.isEmpty else { return nil }
        func text(_ key: String, in object: [String: Any]? = nil) -> String { (object ?? d)[key] as? String ?? "" }
        func first(_ values: String...) -> String { values.first { !$0.isEmpty } ?? "" }
        func joined(_ values: [String], separator: String = " · ") -> String { values.filter { !$0.isEmpty }.joined(separator: separator) }
        var fields: [String: SettingsMemoryValue] = ["embed_id": .string(embedID)]
        func assign(_ values: [String: String]) { fields.merge(values.mapValues(SettingsMemoryValue.string)) { _, new in new } }
        var app: String, category: String, identity: String
        switch type {
        case .eventsEvent:
            app = "events"; category = "saved_events"
            let title = first(text("title"), AppStrings.localized("embeds.event"))
            identity = first(text("id"), text("url"), title)
            let venue = d["venue"] as? [String: Any] ?? Dictionary(uniqueKeysWithValues: ["name", "address", "city", "state", "country"].map { ($0, d["venue_\($0)"] ?? "") })
            let location = joined([text("name", in: venue), text("address", in: venue),
                                   joined([text("city", in: venue), text("state", in: venue), text("country", in: venue)], separator: ", ")], separator: "\n")
            let providers = ["meetup": "Meetup", "luma": "Luma", "eventbrite": "Eventbrite", "classictic": "Classictic", "berlin_philharmonic": "Berlin Philharmonic", "bachtrack": "Bachtrack"]
            assign(["title": title, "provider": providers[text("provider").lowercased()] ?? text("provider"), "url": text("url"),
                    "date_start": text("date_start"), "date_end": text("date_end"),
                    "location": text("event_type") == "ONLINE" ? AppStrings.localized("embeds.online_event") : location, "notes": ""])
        case .healthAppointment:
            app = "health"; category = "appointments"
            let title = first(text("name"), text("speciality"), AppStrings.domainHealthAppointment)
            let url = first(text("booking_url"), text("practice_url")), slot = text("slot_datetime")
            identity = "\(first(url, title)).\(slot)"
            assign(["title": slot.isEmpty ? title : appointmentTitle(slot), "appointment_type": "doctor_visit",
                    "where": joined([text("name"), text("speciality")]), "date": utcDate(slot), "appointment_time": slot,
                    "notes": joined([text("address"), url], separator: "\n")])
        case .travelConnection:
            app = "travel"; category = "saved_connections"
            let summary = TravelConnectionSummary(embedId: embedID, data: d.mapValues(AnyCodable.init))
            let legs = d["legs"] as? [[String: Any]] ?? [], head = legs.first ?? [:], tail = legs.last ?? [:]
            let origin = first(text("origin"), text("origin", in: head)), destination = first(text("destination"), text("destination", in: tail))
            let title = first(summary.routeFull ?? "", summary.routeHeader ?? "", text("route_display"), text("title"), AppStrings.localized("embeds.travel_connection"))
            let url = first(text("booking_url"), summary.googleFlightsURL ?? "")
            identity = first(text("hash"), url, title)
            assign(["title": title, "transport_method": text("transport_method"), "origin": origin, "destination": destination,
                    "departure": first(text("departure"), text("departure", in: head)), "arrival": first(text("arrival"), text("arrival", in: tail)),
                    "booking_url": url, "provider": first(text("booking_provider"), (d["carriers"] as? [String])?.first ?? "", text("carrier")),
                    "notes": joined([summary.tripTypeLabel, summary.priceText ?? "", text("duration")])])
        case .travelStay:
            app = "travel"; category = "saved_stays"
            let title = first(text("name"), AppStrings.localized("embeds.stay")), url = text("link")
            identity = first(text("hash"), url, title)
            let currency = first(text("currency"), "EUR")
            let total = number(d["extracted_total_rate"]), night = number(d["extracted_rate_per_night"])
            let price = total.map { "\(currency) \(SettingsMemoryValue.number($0.rounded()).display)" } ?? night.map { "\(currency) \(SettingsMemoryValue.number($0.rounded()).display)/night" } ?? ""
            let places = d["nearby_places"] as? [[String: Any]] ?? []
            assign(["name": title, "property_type": text("property_type"), "url": url, "price": price,
                    "location": joined(places.map { text("name", in: $0) }, separator: ", "),
                    "notes": joined(Array((d["amenities"] as? [String] ?? []).prefix(8)), separator: ", ")])
            if let rating = number(d["overall_rating"]), rating != 0 { fields["rating"] = .number(rating) }
        case .homeListing:
            app = "home"; category = "saved_listings"
            let title = first(text("title"), AppStrings.domainListing), url = text("url")
            identity = first(url, title)
            let rooms = number(d["rooms"])
            let roomsLabel = rooms.flatMap { $0 == 0 ? nil : "\(SettingsMemoryValue.number($0).display) \($0 == 1 ? AppStrings.domainRoom : AppStrings.domainRooms)" } ?? ""
            let listingType = text("listing_type")
            assign(["title": title, "url": url, "provider": first(text("provider"), (URL(string: url)?.host ?? "").replacingOccurrences(of: "www.", with: "")),
                    "price_label": text("price_label"), "address": text("address"), "available_from": text("available_from"),
                    "notes": joined([number(d["size_sqm"]).flatMap { $0 == 0 ? nil : "\(SettingsMemoryValue.number($0).display) m²" } ?? "", roomsLabel, listingType.prefix(1).uppercased() + listingType.dropFirst()])])
        default: return nil
        }
        return .init(appID: app, categoryID: category, itemKey: "\(category).\(identity)", fields: fields)
    }

    private static func number(_ raw: Any?) -> Double? {
        let value = (raw as? NSNumber)?.doubleValue ?? (raw as? String).flatMap(Double.init)
        return value.flatMap { $0.isFinite ? $0 : nil }
    }
    private static func parsedDate(_ slot: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: slot) { return date }
        formatter.formatOptions.insert(.withFractionalSeconds)
        return formatter.date(from: slot)
    }
    private static func utcDate(_ slot: String) -> String {
        guard let date = parsedDate(slot) else { return String(slot.split(separator: "T").first ?? Substring(slot)) }
        let formatter = DateFormatter(); formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.timeZone = TimeZone(secondsFromGMT: 0); formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }
    private static func appointmentTitle(_ slot: String) -> String {
        guard let date = parsedDate(slot) else { return slot }
        let day = DateFormatter(); day.setLocalizedDateFormatFromTemplate("EEEE MMMM d")
        let time = DateFormatter(); time.setLocalizedDateFormatFromTemplate("HHmm")
        return "\(day.string(from: date)) · \(time.string(from: date))"
    }
}

/// The service owns pending state and rejects stale results before publishing.
/// No optimistic label change and no second confirmation for explicit Forget.
struct NativeEmbedMemoryButton: View {
    let config: NativeEmbedMemoryConfig
    @StateObject private var service: SettingsMemoryService
    @ObservedObject private var accountScope = OfflineStore.shared
    @ObservedObject private var teamScope = TeamWorkspaceContext.shared

    init(config: NativeEmbedMemoryConfig, service: SettingsMemoryService = SettingsMemoryService()) {
        self.config = config; _service = StateObject(wrappedValue: service)
    }
    private var entry: SettingsMemoryEntry? { config.savedEntry(in: service.entries) }
    private var category: SettingsMemoryCategory? { service.categories.first { $0.appId == config.appID && $0.categoryId == config.categoryID } }
    private var enabled: Bool {
        guard service.isAuthenticated, category != nil else { return false }
        switch service.state { case .loaded, .empty, .conflict, .error: return true; default: return false }
    }
    var body: some View {
        VStack(spacing: .spacing1) {
            Button {
                Task {
                    if let entry { _ = await service.delete(entry) }
                    else if let category { _ = await service.save(entry: nil, category: category, key: config.itemKey, fields: config.fields) }
                }
            } label: {
                Text(entry == nil ? AppStrings.embedAddMemory : AppStrings.embedForgetMemory)
                    .font(.omP).fontWeight(.medium)
                    // Web destructive literal #b91c1c has no generated token.
                    .foregroundStyle(entry == nil ? Color.fontPrimary : Color(hex: 0xB91C1C))
                    .padding(.horizontal, .spacing12).padding(.vertical, .spacing6)
                    // Web secondary/destructive minimum width 120px; radius 15px.
                    .frame(minWidth: 120)
                    .background(entry == nil ? Color.grey20 : Color.fontButton)
                    .clipShape(RoundedRectangle(cornerRadius: 15))
                    .overlay(RoundedRectangle(cornerRadius: 15).stroke(entry == nil ? Color.grey40 : Color.fontButton, lineWidth: entry == nil ? 1 : 2))
                    .shadow(color: .black.opacity(entry == nil ? 0.25 : 0.28), radius: entry == nil ? 4 : 8, x: 0, y: 4)
            }.buttonStyle(.plain).disabled(!enabled)
                .accessibilityIdentifier("save-embed-cta")
            if case .error(let message) = service.state {
                Text(message).font(.omXs).foregroundStyle(Color.error).accessibilityIdentifier("save-embed-error")
            } else if service.state == .conflict {
                Text(AppStrings.error).font(.omXs).foregroundStyle(Color.error).accessibilityIdentifier("save-embed-error")
            }
        }
        .task { await service.load() }
        .onChange(of: accountScope.scopeGeneration) { _, _ in service.cancel(); Task { await service.load() } }
        .onChange(of: teamScope.contextEpoch) { _, _ in service.cancel(); Task { await service.load() } }
        .onDisappear { service.cancel() }
    }
}
