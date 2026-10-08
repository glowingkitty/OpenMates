// Display-only counterpart for chats/Chats.svelte and utils/chatGroupUtils.ts.
// Sorting, hidden/subchat filtering and static sections remain with the caller.
import Foundation

enum ChatSidebarDisplayPolicy {
    /// Default web history retains every scoped, visible top-level metadata
    /// row, including untitled shells and legacy archived rows. The caller
    /// separately removes public, organized and running chats.
    static func isRootUserChatEligible(_ chat: Chat, teamID: String?) -> Bool {
        !chat.isRetiredBundledIntro && !chat.isHiddenFromNormalSurfaces &&
            chat.teamId == teamID && chat.parentId == nil && chat.isSubChat != true
    }

    /// The web draft-only row has no title/profile, only its status and preview.
    static func isDraftOnly(_ chat: Chat, preview: String?) -> Bool {
        let title = chat.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let hasTitle = !title.isEmpty && title.lowercased() != "untitled chat"
        let hasDraft = chat.hasNonEmptyDraft == true || (chat.draftV ?? 0) > 0 || preview?.isEmpty == false
        return hasDraft && !hasTitle && (chat.messagesV ?? 0) == 0 && chat.lastVisibleMessageId == nil
    }

    /// Web category badges hide while processing and cap their numeral at 9+.
    static func unreadBadgeText(count: Int, processing: Bool, draftOnly: Bool) -> String? {
        guard count > 0, !processing, !draftOnly else { return nil }
        return count > 9 ? "9+" : String(count)
    }

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

    struct Snapshot {
        let visibleChats: [Chat]
        let groups: [Group]
        let filteredCount: Int
        let shouldShowMore: Bool
    }

    /// The caller supplies one filtered, ordered chat snapshot. Derive every
    /// sidebar consumer from that same input before entering draft observation.
    static func snapshot(sortedUserChats: [Chat], appliesDisplayLimit: Bool,
                         limit: Int, selectedChatID: String?, lastActiveChatID: String?,
                         totalChatCount: Int, serverChatPagesExhausted: Bool,
                         now: Date = Date(), calendar: Calendar = gregorianCalendar) -> Snapshot {
        let visible = appliesDisplayLimit
            ? visibleChats(sortedUserChats: sortedUserChats, limit: limit,
                           selectedChatID: selectedChatID, lastActiveChatID: lastActiveChatID)
            : sortedUserChats
        let count = sortedUserChats.count
        return Snapshot(visibleChats: visible, groups: groups(visible, now: now, calendar: calendar),
            filteredCount: count, shouldShowMore: appliesDisplayLimit &&
                (count > limit || (!serverChatPagesExhausted && totalChatCount > count)))
    }

    static func nextLimit(after limit: Int) -> Int {
        max(0, limit) > Int.max - increment ? Int.max : max(0, limit) + increment
    }

    /// Membership comes from the scoped recent window before organized chats
    /// are removed from the root list. Project workspace contents stay intact.
    static func eligibleProjects(_ projects: [ChatSidebarProject], recentActiveChats: [Chat]) -> [ChatSidebarProject] {
        let activeIDs = Set(recentActiveChats.map(\.id))
        return projects.compactMap { project in
            let foldersByHash = Dictionary(project.contents.folders.map {
                (ChatSidebarProject.hash($0.id), $0)
            }, uniquingKeysWith: { first, _ in first })
            var eligibleFolderIDs: Set<String> = []
            var hasEligibleMember = false
            for item in project.contents.items where item.kind == "chat" && activeIDs.contains(item.targetID) {
                var ancestry: Set<String> = []
                var hash = item.folderHash
                while let current = hash, let folder = foldersByHash[current], ancestry.insert(folder.id).inserted {
                    hash = folder.parentHash
                }
                // Missing parents and cycles do not make an unreachable folder
                // or its project eligible in the chat sidebar.
                guard hash == nil else { continue }
                hasEligibleMember = true
                eligibleFolderIDs.formUnion(ancestry)
            }
            guard hasEligibleMember else { return nil }
            let contents = ProjectWorkspaceContents(
                folders: project.contents.folders.filter { eligibleFolderIDs.contains($0.id) },
                items: project.contents.items, sources: project.contents.sources)
            return ChatSidebarProject(project: project.project, contents: contents)
        }
    }

    static func groups(_ chats: [Chat], now: Date = Date(),
                       calendar: Calendar = gregorianCalendar) -> [Group] {
        var rows: [String: [Chat]] = [:]
        var encountered: [String] = []
        for chat in chats {
            let key = groupKey(for: chat.sidebarActivityDate, now: now, calendar: calendar)
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
