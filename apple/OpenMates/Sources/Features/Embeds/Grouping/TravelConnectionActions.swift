// Web source: travel/TravelConnectionEmbedFullscreen.svelte (handleCopy/buildCalendarDescription)
// and utils/calendarDownload.ts.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
import Foundation

@MainActor
struct TravelConnectionActions {
    let data: [String: AnyCodable]
    var locale: Locale = .current
    var timeZone: TimeZone = .current

    private var connection: TravelConnectionSummary { .init(embedId: nil, data: data) }
    private var legs: [[String: AnyCodable]] {
        (data["legs"]?.value as? [[String: Any]] ?? []).map { $0.mapValues(AnyCodable.init) }
    }
    private var carriers: String { TravelValue.stringArray(data, "carriers").joined(separator: ", ") }
    private var header: [String] { [connection.routeFull, connection.tripTypeLabel, connection.priceText].compactMap { $0 }.filter { !$0.isEmpty } }
    private var bookingURL: String? { connection.bookingURL ?? connection.googleFlightsURL }
    private func string(_ fields: [String: AnyCodable], _ key: String) -> String? { TravelValue.string(fields, [key]) }
    private func time(_ value: String?) -> String { value.map { TravelValue.formatTime($0, locale: locale, timeZone: timeZone) } ?? "" }
    private func date(_ value: String?) -> String { value.map { TravelValue.formatDate($0, locale: locale, timeZone: timeZone) } ?? "" }
    private func stops(_ count: Int) -> String { count == 0 ? "Direct" : count == 1 ? "1 stop" : "\(count) stops" }
    private func label(_ leg: [String: AnyCodable]) -> String? {
        guard legs.count > 1 else { return nil }
        let index = TravelValue.int(leg, ["leg_index"]) ?? 0
        return legs.count == 2 ? (index == 0 ? "Outbound" : "Return") : "Leg \(index + 1)"
    }
    private func segments(_ leg: [String: AnyCodable]) -> [[String: AnyCodable]] {
        (leg["segments"]?.value as? [[String: Any]] ?? []).map { $0.mapValues(AnyCodable.init) }
    }
    private func route(_ leg: [String: AnyCodable], arrow: String) -> String {
        "\(string(leg, "origin") ?? "") \(arrow) \(string(leg, "destination") ?? "")"
    }

    var copyText: String {
        var lines = [header.joined(separator: " · ")]
        if !carriers.isEmpty { lines.append(carriers) }
        lines.append("")
        for leg in legs {
            lines.append([label(leg), route(leg, arrow: "→")].compactMap { $0 }.joined(separator: ": "))
            let meta = [date(string(leg, "departure")), string(leg, "duration") ?? "", stops(TravelValue.int(leg, ["stops"]) ?? 0)].filter { !$0.isEmpty }
            lines.append(meta.joined(separator: " · "))
            lines.append("")
            for segment in segments(leg) {
                lines.append("  \(time(string(segment, "departure_time")))  \(string(segment, "departure_station") ?? "")")
                let info = ["carrier", "number", "duration"].compactMap { string(segment, $0) }.joined(separator: " · ")
                if !info.isEmpty { lines.append("  " + info) }
                lines.append("  \(time(string(segment, "arrival_time")))  \(string(segment, "arrival_station") ?? "")")
                lines.append("")
            }
        }
        if legs.isEmpty {
            if connection.departure != nil && connection.arrival != nil { lines.append("\(time(connection.departure)) → \(time(connection.arrival))") }
            if let duration = connection.duration { lines.append(duration) }
            if let count = TravelValue.int(data, ["stops"]) { lines.append(stops(count)) }
            lines.append("")
        }
        if let seats = TravelValue.int(data, ["bookable_seats"]), seats > 0 { lines.append("\(seats) seat(s) remaining") }
        if let deadline = string(data, "last_ticketing_date") { lines.append("Book by " + deadline) }
        return lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func calendarFile(now: Date = Date(), renderText: (String) -> String = { $0 }) -> EmbedCalendarFile? {
        guard let start = connection.departure ?? legs.first.flatMap({ string($0, "departure") }) else { return nil }
        let end = connection.arrival ?? legs.last.flatMap({ string($0, "arrival") })
        let title = connection.routeFull ?? connection.routeHeader ?? "Travel connection"
        var lines = [header.joined(separator: " | ")]
        if !carriers.isEmpty { lines.append(carriers) }
        if let duration = connection.duration { lines.append("Duration: " + duration) }
        if let count = TravelValue.int(data, ["stops"]) { lines.append("Stops: " + stops(count)) }
        if !legs.isEmpty { lines.append("") }
        for leg in legs {
            lines.append([label(leg), route(leg, arrow: "->")].compactMap { $0 }.joined(separator: ": "))
            for segment in segments(leg) {
                lines.append("\(time(string(segment, "departure_time"))) \(string(segment, "departure_station") ?? "") -> \(time(string(segment, "arrival_time"))) \(string(segment, "arrival_station") ?? "")")
                lines.append(["carrier", "number", "duration"].compactMap { string(segment, $0) }.joined(separator: " | "))
            }
        }
        if let bookingURL { lines += ["", bookingURL] }
        let location = [connection.origin, connection.destination].compactMap { $0 }.joined(separator: " to ")
        let filename = [connection.origin ?? "travel", connection.destination ?? "connection", String(start.prefix(10))].joined(separator: "-")
        return EmbedCalendarFile.build(title: renderText(title), start: calendarTimestamp(start),
            end: end.map(calendarTimestamp),
            location: renderText(location), description: renderText(lines.joined(separator: "\n")),
            url: bookingURL.map(renderText), filename: renderText(filename), now: now, timeZone: timeZone)
    }
    // Travel providers also supply ISO minute precision, accepted by browser Date.
    // Normalize only this input; the shared Health calendar parser stays strict.
    private func calendarTimestamp(_ value: String) -> String {
        guard value.range(of: #"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?$"#,
                          options: .regularExpression) != nil else { return value }
        return String(value.prefix(16)) + ":00" + String(value.dropFirst(16))
    }

}
