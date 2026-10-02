// Web sources: utils/calendarDownload.ts, health/HealthAppointmentEmbedFullscreen.svelte,
// travel/TravelConnectionEmbedFullscreen.svelte.
// Calendar exports are files; they never write Calendar data or request permissions.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
import Foundation

struct EmbedCalendarFile: Equatable, Sendable {
    let filename: String
    let content: String

    static func build(title: String, start: String, end explicitEnd: String? = nil,
                      location: String?, description: String?, url: String?, filename: String? = nil,
                      now: Date = Date(), timeZone: TimeZone = .current) -> Self? {
        guard let date = parse(start, timeZone: timeZone) else { return nil }
        let allDay = start.count == 10
        let parsedEnd = explicitEnd.flatMap { parse($0, timeZone: timeZone) }
        let end = parsedEnd.flatMap { $0 > date ? $0 : nil }
            ?? date.addingTimeInterval(allDay ? 86_400 : 3_600)
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
        let format = { formatter.string(from: $0) }
        let safeTitle = title.isEmpty ? "Calendar event" : title
        var lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OpenMates//Embeds//EN",
                     "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT",
                     "UID:\(Int64((date.timeIntervalSince1970 * 1_000).rounded()))-\(sanitizeFilename(safeTitle))@openmates",
                     "DTSTAMP:\(format(now))",
                     allDay ? "DTSTART;VALUE=DATE:\(format(date).prefix(8))" : "DTSTART:\(format(date))",
                     allDay ? "DTEND;VALUE=DATE:\(format(end).prefix(8))" : "DTEND:\(format(end))",
                     "SUMMARY:\(escape(safeTitle))"]
        if let location, !location.isEmpty { lines.append("LOCATION:\(escape(location))") }
        if let description, !description.isEmpty { lines.append("DESCRIPTION:\(escape(description))") }
        if let url, !url.isEmpty { lines.append("URL:\(escape(url))") }
        lines += ["END:VEVENT", "END:VCALENDAR"]
        return .init(filename: sanitizeFilename(filename ?? "\(safeTitle)-\(start.prefix(10))") + ".ics",
                     content: lines.map(fold).joined(separator: "\r\n") + "\r\n")
    }

    private static func parse(_ value: String, timeZone: TimeZone) -> Date? {
        let pattern = #"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})?)?$"#
        guard value.range(of: pattern, options: .regularExpression) != nil else { return nil }
        // ISO8601DateFormatter normalizes out-of-range offsets on Apple platforms.
        // Validate the numeric offset before parsing so malformed slots cannot export an event.
        if let offsetRange = value.range(of: #"[+-]\d{2}:\d{2}$"#, options: .regularExpression) {
            let offset = value[offsetRange].dropFirst().split(separator: ":")
            guard let hours = Int(offset[0]), let minutes = Int(offset[1]),
                  hours < 24, minutes < 60 else { return nil }
        }
        let allDay = value.count == 10
        let zoned = value.range(of: #"(?:Z|[+-]\d{2}:\d{2})$"#, options: .regularExpression) != nil
        let civil = allDay ? value + "T00:00:00" : String(value.prefix(19))
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = allDay || zoned ? TimeZone(secondsFromGMT: 0) : timeZone
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        formatter.isLenient = false
        guard let wallTime = formatter.date(from: civil), formatter.string(from: wallTime) == civil else { return nil }
        if allDay { return wallTime }
        if !zoned {
            let fraction = String(value.dropFirst(19))
            return wallTime.addingTimeInterval(fraction.isEmpty ? 0 : Double("0" + fraction) ?? 0)
        }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return iso.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }

    private static func sanitizeFilename(_ value: String) -> String {
        let value = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return value.isEmpty ? "calendar-event" : String(value.prefix(80))
    }

    private static func escape(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: ";", with: "\\;").replacingOccurrences(of: ",", with: "\\,")
            .replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
            .replacingOccurrences(of: "\n", with: "\\n")
    }

    private static func fold(_ line: String) -> String {
        var output = "", length = 0
        for scalar in line.unicodeScalars {
            let value = String(scalar), bytes = value.utf8.count
            if length + bytes > 75 { output += "\r\n "; length = 1 }
            output += value; length += bytes
        }
        return output
    }
}

@MainActor
enum HealthAppointmentCalendarFile {
    static func make(_ data: [String: AnyCodable], now: Date = Date(), timeZone: TimeZone = .current,
                     renderText: (String) -> String = { $0 }) -> EmbedCalendarFile? {
        let model = HealthAppointmentModel(data), fields = model.fields
        guard let slot = fields.string("slot_datetime") else { return nil }
        let title = [model.name, model.speciality].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " - ")
        var description: [String] = []
        for (key, label) in [("speciality", "Speciality"), ("service_name", "Service"), ("provider_platform", "Provider")] {
            if let value = fields.string(key), !value.isEmpty { description.append("\(label): \(value)") }
        }
        if let price = fields.double("price"), price.isFinite {
            let value = String(price)
            description.append("Price: \(value.hasSuffix(".0") ? String(value.dropLast(2)) : value) EUR")
        }
        let url = model.bookingURL?.absoluteString
        if let url { description.append(url) }
        return EmbedCalendarFile.build(title: renderText(title.isEmpty ? "Health appointment" : title), start: slot,
            location: fields.string("address").map(renderText), description: renderText(description.joined(separator: "\n")),
            url: url.map(renderText), now: now, timeZone: timeZone)
    }
}
