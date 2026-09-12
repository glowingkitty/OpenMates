// Display-only counterpart for chats/Chats.svelte and utils/chatGroupUtils.ts.
// Sorting, hidden/subchat filtering and static sections remain with the caller.
import Foundation

enum ChatSidebarDisplayPolicy {
    static let initialLimit = 11
    static let increment = 20
    static let timeGroupOrder = ["today", "yesterday", "previous_7_days", "previous_30_days"]

    struct Scope: Equatable, Sendable {
        let userID: String?
        let serverOrigin: String
    }
    struct RetainedSelection: Sendable {
        let chatID: String
        let scope: Scope
        func chatID(in current: Scope) -> String? { scope == current ? chatID : nil }
    }
    struct Group {
        let key: String
        let chats: [Chat]
    }

    static func visibleChats(sortedUserChats: [Chat], limit: Int,
                             selectedChatID: String?, lastActiveChatID: String?) -> [Chat] {
        guard limit > 0 else { return [] }
        var visible = Array(sortedUserChats.prefix(limit))
        if let activeID = selectedChatID ?? lastActiveChatID,
           !visible.contains(where: { $0.id == activeID }),
           let active = sortedUserChats.first(where: { $0.id == activeID }) {
            // Keep one bounded window. The active row replaces its final entry;
            // pins count toward the same cap, exactly as the web's userChats.
            if visible.count >= limit { visible[visible.count - 1] = active }
            else { visible.append(active) }
        }
        return visible
    }

    static func nextLimit(after limit: Int) -> Int {
        max(0, limit) > Int.max - increment ? Int.max : max(0, limit) + increment
    }

    static func groups(_ chats: [Chat], now: Date = Date(),
                       calendar: Calendar = gregorianCalendar) -> [Group] {
        var rows: [String: [Chat]] = [:]
        var encountered: [String] = []
        for chat in chats {
            let key = groupKey(for: chat.lastMessageDate, now: now, calendar: calendar)
            if rows[key] == nil { encountered.append(key) }
            rows[key, default: []].append(chat)
        }
        // Standard periods always precede month groups; month groups retain
        // encounter order from the already-sorted input, including pinned rows.
        let ordered = timeGroupOrder + encountered.filter { !timeGroupOrder.contains($0) }
        return ordered.compactMap { key in rows[key].map { Group(key: key, chats: $0) } }
    }

    static func groupKey(for date: Date?, now: Date, calendar: Calendar = gregorianCalendar) -> String {
        let source = date.flatMap { $0.timeIntervalSince1970 == 0 ? nil : $0 } ?? now
        // Web subtracts local midnights then floors 24h periods. Preserve that
        // exact rule (including DST boundaries) instead of using elapsed hours.
        let days = floor(calendar.startOfDay(for: now).timeIntervalSince(calendar.startOfDay(for: source)) / 86_400)
        if days == 0 { return "today" }
        if days == 1 { return "yesterday" }
        if days < 7 { return "previous_7_days" }
        if days < 30 { return "previous_30_days" }
        return "month_\(calendar.component(.year, from: source))_\(calendar.component(.month, from: source))"
    }

    static var gregorianCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        return calendar
    }

    @MainActor
    static func title(for key: String, locale: Locale) -> String {
        switch key {
        case "today": return AppStrings.today
        case "yesterday": return AppStrings.yesterday
        case "previous_7_days": return AppStrings.previous7Days
        case "previous_30_days": return AppStrings.previous30Days
        default:
            let parts = key.split(separator: "_")
            guard parts.count == 3, parts[0] == "month", let year = Int(parts[1]),
                  let month = Int(parts[2]), (1...12).contains(month),
                  let date = gregorianCalendar.date(from: DateComponents(year: year, month: month)) else { return key }
            let formatter = DateFormatter()
            formatter.locale = locale
            formatter.calendar = gregorianCalendar
            formatter.setLocalizedDateFormatFromTemplate("MMMM yyyy")
            return formatter.string(from: date)
        }
    }
}
