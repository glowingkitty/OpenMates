// Web: services/continueCarouselService.ts; ActiveChat.loadPriorityContinueItems.
// Specification: specifications/features/continue-carousel/specification.yml
// Assertions: continue-carousel.saved-item.start-time-gated, continue-carousel.chat.reminder-gated
// Decrypted memory content remains in this account-scoped RAM cache only.
import Foundation
import Combine

struct WelcomeContinueReminder: Decodable {
    let triggerAt: Double
    let targetType: String
    let targetChatId: String?
    let targetEmbedId: String?
    let status: String
    enum CodingKeys: String, CodingKey {
        case triggerAt = "trigger_at", targetType = "target_type", targetChatId = "target_chat_id", targetEmbedId = "target_embed_id", status
    }
}

struct WelcomeContinuePriority: Equatable {
    enum Reason: Int { case reminderDue, reminderSoon, ongoing, upcoming }
    let reason: Reason
    let timestamp: Date
    var dateOnly = false
    func label(now: Date) -> String {
        if dateOnly {
            let formatter = DateFormatter(); formatter.dateStyle = .medium
            formatter.doesRelativeDateFormatting = true
            return formatter.string(from: timestamp)
        }
        if reason == .ongoing { return String(localized: "Ongoing", comment: "An ongoing saved event or trip in Continue") }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: reason == .ongoing ? now : timestamp, relativeTo: now)
    }
}

struct WelcomeContinueItem: Identifiable, Equatable {
    let id: String
    let chatID: String?
    let memory: SettingsMemoryEntry?
    let priority: WelcomeContinuePriority
}

enum WelcomeContinuePolicy {
    static func timestamp(_ value: SettingsMemoryValue?) -> Date? {
        guard let raw = value?.string, !raw.isEmpty else { return nil }
        if let precise = UpcomingMemoryActivityPolicy.parseTimestamp(raw) { return precise }
        // Continue follows the web's civil-date eligibility; ActivityKit still
        // requires an explicit timezone timestamp in its separate policy.
        for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd"] {
            let parser = DateFormatter(); parser.locale = Locale(identifier: "en_US_POSIX")
            parser.dateFormat = format; parser.isLenient = false
            if let date = parser.date(from: raw) { return date }
        }
        return nil
    }
    static func reminderPriority(_ reminder: WelcomeContinueReminder, now: Date) -> WelcomeContinuePriority? {
        guard reminder.triggerAt.isFinite, reminder.triggerAt > 0 else { return nil }
        let date = Date(timeIntervalSince1970: reminder.triggerAt), delta = date.timeIntervalSince(now)
        if delta <= 0 {
            guard delta >= -12 * 3600 || reminder.status == "pending" else { return nil }
            return .init(reason: .reminderDue, timestamp: date)
        }
        guard delta <= 24 * 3600 else { return nil }
        return .init(reason: .reminderSoon, timestamp: date)
    }
    static func precedes(_ a: WelcomeContinuePriority, _ b: WelcomeContinuePriority, now: Date) -> Bool {
        if a.reason != b.reason { return a.reason.rawValue < b.reason.rawValue }
        return abs(a.timestamp.timeIntervalSince(now)) < abs(b.timestamp.timeIntervalSince(now))
    }
    static func items(entries: [SettingsMemoryEntry], reminders: [WelcomeContinueReminder], now: Date) -> [WelcomeContinueItem] {
        var best: [String: WelcomeContinueItem] = [:]
        for reminder in reminders {
            guard let priority = reminderPriority(reminder, now: now) else { continue }
            let chat = reminder.targetType == "chat" ? reminder.targetChatId : nil
            let embed = reminder.targetType == "embed" ? reminder.targetEmbedId : nil
            guard let target = chat ?? embed, !target.isEmpty else { continue }
            let id = (chat == nil ? "embed:" : "chat:") + target
            let item = WelcomeContinueItem(id: id, chatID: chat, memory: nil, priority: priority)
            if best[id] == nil || precedes(priority, best[id]!.priority, now: now) { best[id] = item }
        }
        var items = best.values.filter { $0.chatID != nil }
        for entry in entries where !entry.isExample {
            guard let embed = entry.fields["embed_id"]?.string, !embed.isEmpty else { continue }
            let fields = entry.fields
            let start = ["date_start", "departure", "start_time", "starts_at", "datetime", "appointment_time"]
                .compactMap { timestamp(fields[$0]) }.first
                ?? fields["date"].flatMap { value in timestamp(value).map { Calendar.current.date(bySettingHour: 23, minute: 59, second: 59, of: $0)! } }
                ?? timestamp(fields["available_from"])
            let end = ["date_end", "arrival", "end_time", "ends_at", "checkout", "available_until"].compactMap { timestamp(fields[$0]) }.first
            var priority: WelcomeContinuePriority?
            if let end, end >= now, start == nil || start! <= now { priority = .init(reason: .ongoing, timestamp: end) }
            else if let start, start.timeIntervalSince(now) >= -12 * 3600, start.timeIntervalSince(now) <= 24 * 3600 {
                priority = .init(reason: .upcoming, timestamp: start, dateOnly: fields["date"] != nil && !["date_start", "departure", "start_time", "starts_at", "datetime", "appointment_time"].contains(where: { timestamp(fields[$0]) != nil }))
            } else if start == nil && end == nil { priority = best["embed:" + embed]?.priority }
            guard let priority else { continue }
            items.append(.init(id: "embed:" + embed, chatID: nil, memory: entry, priority: priority))
        }
        var seen = Set<String>()
        return items.sorted { precedes($0.priority, $1.priority, now: now) }
            .filter { seen.insert($0.id).inserted }
    }
}

@MainActor
final class WelcomeContinueService: ObservableObject {
    static let shared = WelcomeContinueService()
    @Published private(set) var items: [WelcomeContinueItem] = []
    @Published private(set) var now = Date()
    private var scope: UpcomingMemorySnapshotScope?
    private var entries: [SettingsMemoryEntry] = []
    private var reminders: [WelcomeContinueReminder] = []
    private var revision: UInt64 = 0
    private var foreground = false
    private var loading: Task<Void, Never>?
    private var syncObserver: AnyCancellable?
    private var boundaryTask: Task<Void, Never>?
    private lazy var memories = SettingsMemoryService(observesSync: false, liveActivitySnapshot: { [weak self] snapshot in
        self?.accept(snapshot)
        UpcomingMemoryLiveActivityBridge.shared.accept(snapshot)
    })
    init(observesSync: Bool = true) {
        guard observesSync else { return }
        syncObserver = NotificationCenter.default.publisher(for: .wsSyncEvent).sink { [weak self] _ in
            Task { @MainActor in guard let self, self.foreground else { return }; self.refresh() }
        }
    }
    func configure(accountID: String?, server: ServerProfile, generation: UUID, team: APIRequestTeamContext, authenticated: Bool) {
        let next = authenticated ? accountID.map { UpcomingMemorySnapshotScope(accountID: $0, server: server, scope: generation, team: team) } : nil
        guard next != scope else { return }
        loading?.cancel(); loading = nil; boundaryTask?.cancel(); boundaryTask = nil; memories.cancel()
        entries = []; reminders = []; revision = 0; items = []; scope = next
        if foreground { refresh() }
    }
    func accept(_ snapshot: SettingsMemoryLiveActivitySnapshot) {
        guard UpcomingMemorySnapshotBindingPolicy.accepts(snapshot, currentScope: scope, after: revision) else { return }
        revision = snapshot.revision
        switch snapshot.change {
        case .full: entries = snapshot.entries.filter { !$0.isExample }
        case .upsert(let entry): entries.removeAll { $0.id == entry.id }; if !entry.isExample { entries.append(entry) }
        case .removed(let id): entries.removeAll { $0.id == id }
        }
        project()
    }
    func becameActive() { foreground = true; project(); refresh() }
    func becameInactive() { foreground = false; loading?.cancel(); loading = nil; boundaryTask?.cancel(); boundaryTask = nil; memories.cancel() }
    private func project() {
        now = Date()
        items = WelcomeContinuePolicy.items(entries: scope?.teamID == nil ? entries : [], reminders: reminders, now: now)
        scheduleBoundary()
    }
    private func scheduleBoundary() {
        boundaryTask?.cancel(); boundaryTask = nil
        guard foreground, let expected = scope else { return }
        let boundaryFields: Set<String> = ["date_start", "departure", "start_time", "starts_at", "datetime", "appointment_time", "date_end", "arrival", "end_time", "ends_at", "checkout", "available_until", "available_from", "date"]
        let entryDates: [Date] = entries.flatMap { entry -> [Date] in
            let timestamps: [Date] = entry.fields.filter { boundaryFields.contains($0.key) }
                .compactMap { key, value -> Date? in
                    guard let date = WelcomeContinuePolicy.timestamp(value) else { return nil }
                    return key == "date" ? Calendar.current.date(bySettingHour: 23, minute: 59, second: 59, of: date) : date
                }
            return timestamps.flatMap { date -> [Date] in
                [date.addingTimeInterval(-86400), date.addingTimeInterval(-14400), date, date.addingTimeInterval(43200)]
            }
        }
        let reminderDates: [Date] = reminders.flatMap { reminder -> [Date] in
            let date = Date(timeIntervalSince1970: reminder.triggerAt)
            return [date.addingTimeInterval(-86400), date, date.addingTimeInterval(43200)]
        }
        let dates = entryDates + reminderDates
        guard let next = dates.filter({ $0 > now }).min() else { return }
        // One active-app date-boundary wake, never an inventory poll. Background
        // cancellation leaves OS scheduling/foreground reconciliation in charge.
        let delay = max(0.05, next.timeIntervalSince(now) + 0.05)
        boundaryTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(delay)) } catch { return }
            guard let self, self.foreground, self.scope == expected else { return }
            self.project()
            UpcomingMemoryLiveActivityBridge.shared.reevaluateDates()
        }
    }
    private func refresh() {
        guard let expected = scope, loading == nil else { return }
        loading = Task { [weak self] in
            guard let self else { return }
            await self.memories.load()
            guard !Task.isCancelled, self.scope == expected else { return }
            do {
                let data: Data = try await APIClient.shared.request(.get,
                    path: "/v1/settings/reminders?include_recent_fired=true&upcoming_hours=24&recent_hours=12",
                    serverProfile: expected.server, expectedAccountID: expected.accountID, expectedScope: expected.scope,
                    expectedTeamContext: .init(epoch: expected.teamEpoch, teamID: expected.teamID))
                struct Response: Decodable { let reminders: [WelcomeContinueReminder] }
                let response = try JSONDecoder().decode(Response.self, from: data)
                guard !Task.isCancelled, self.scope == expected else { return }
                self.reminders = response.reminders
            } catch { /* Keep accepted scoped memories when optional reminders are unavailable. */ }
            guard !Task.isCancelled, self.scope == expected else { return }
            self.project(); self.loading = nil
        }
    }
}

extension WelcomeContinuePolicy {
    // Same saved-memory fallback as web: already-decrypted typed fields, never a
    // remote cross-chat fetch or fabricated encrypted record/key.
    static func savedRecord(_ entry: SettingsMemoryEntry) -> EmbedRecord? {
        guard let id = entry.fields["embed_id"]?.string, !id.isEmpty,
              let json = try? SettingsMemoryValue.object(entry.fields).json(),
              let raw = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any] else { return nil }
        let type: String
        switch entry.appId {
        case "events": type = "events-event"
        case "health": type = "health-appointment"
        case "travel": type = entry.categoryId.contains("stay") ? "travel-stay" : "travel-connection"
        case "home": type = "home-listing"
        default: type = "app:" + entry.appId + ":search"
        }
        return EmbedRecord(id: id, type: type, status: .finished, data: .raw(raw.mapValues { AnyCodable($0) }),
            parentEmbedId: nil, appId: entry.appId, skillId: nil, embedIds: nil, createdAt: nil)
    }
}
