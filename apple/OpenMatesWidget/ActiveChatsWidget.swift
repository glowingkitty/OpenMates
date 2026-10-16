// Native Active chats widget using only the main app's encrypted local census.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/chats/Chat.svelte
//         frontend/packages/ui/src/components/ChatHistory.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.activity.global-running
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.processing.widget, apple-live-activities.lifecycle.isolation
import SwiftUI
import WidgetKit

struct ActiveChatsWidgetEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetActiveChatsSnapshot?
}
struct ActiveChatsWidgetProvider: TimelineProvider {
    func placeholder(in context: Context) -> ActiveChatsWidgetEntry { ActiveChatsWidgetFixtures.entry }
    func getSnapshot(in context: Context, completion: @escaping (ActiveChatsWidgetEntry) -> Void) {
        if context.isPreview { completion(ActiveChatsWidgetFixtures.entry); return }
        nonisolated(unsafe) let completion = completion
        Task { @MainActor in completion(ActiveChatsWidgetEntry(date: Date(), snapshot: WidgetActiveChatsStorage.shared.load())) }
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<ActiveChatsWidgetEntry>) -> Void) {
        nonisolated(unsafe) let completion = completion
        Task { @MainActor in
            let now = Date(), snapshot = WidgetActiveChatsStorage.shared.load()
            let changes = Set(snapshot?.chats.flatMap { [$0.staleAt, $0.expiresAt] }.filter { $0 > now } ?? []).sorted()
            let entries = [ActiveChatsWidgetEntry(date: now, snapshot: snapshot)]
                + changes.map { ActiveChatsWidgetEntry(date: $0, snapshot: snapshot) }
            completion(Timeline(entries: entries, policy: .after(now.addingTimeInterval(15 * 60))))
        }
    }
}
struct ActiveChatsWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: ActiveChatsWidgetEntry
    private var limit: Int { WidgetActiveChatsProjection.rowLimit(for: family) }
    private var total: Int { entry.snapshot?.active(at: entry.date).count ?? 0 }
    private var labels: WidgetActiveChatsLabels {
        .init(title: ActiveChatsWidgetStrings.title, total: ActiveChatsWidgetStrings.total(total),
            empty: ActiveChatsWidgetStrings.empty, openApp: ActiveChatsWidgetStrings.openApp,
            viewAll: ActiveChatsWidgetStrings.viewAll, stale: ActiveChatsWidgetStrings.stale)
    }
    var body: some View {
        Group {
            #if os(iOS)
            if family == .accessoryCircular || family == .accessoryRectangular {
                WidgetActiveChatsAccessoryView(snapshot: entry.snapshot, date: entry.date, family: family, labels: labels)
            } else {
                WidgetActiveChatsContentView(snapshot: entry.snapshot, date: entry.date, rowLimit: limit, labels: labels)
            }
            #else
            WidgetActiveChatsContentView(snapshot: entry.snapshot, date: entry.date, rowLimit: limit, labels: labels)
            #endif
        }
        .widgetURL(WidgetActiveChatsProjection.primaryURL(for: family, snapshot: entry.snapshot, date: entry.date))
    }
}
struct ActiveChatsWidget: Widget {
    let kind = "ActiveChatsWidget"
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: ActiveChatsWidgetProvider()) { entry in
            ActiveChatsWidgetView(entry: entry).containerBackground(Color.grey0, for: .widget)
        }
        .configurationDisplayName(ActiveChatsWidgetStrings.title)
        .description(ActiveChatsWidgetStrings.description)
        #if os(iOS)
        .supportedFamilies([.systemMedium, .systemLarge, .accessoryCircular, .accessoryRectangular])
        #else
        .supportedFamilies([.systemMedium, .systemLarge])
        #endif
    }
}
enum ActiveChatsWidgetStrings {
    static var title: String { WidgetStrings.text("chats.activity.heading", languageKey: "widget_active_chats_language") }
    static var description: String { WidgetStrings.text("apple.active_chats_widget.description", languageKey: "widget_active_chats_language") }
    static var empty: String { WidgetStrings.text("apple.active_chats_widget.empty", languageKey: "widget_active_chats_language") }
    static var openApp: String { WidgetStrings.text("apple.active_chats_widget.open_app", languageKey: "widget_active_chats_language") }
    static var stale: String { WidgetStrings.text("apple.active_chats_widget.stale", languageKey: "widget_active_chats_language") }
    static var viewAll: String { WidgetStrings.text("apple.active_chats_widget.view_all", languageKey: "widget_active_chats_language") }
    static func total(_ count: Int) -> String {
        WidgetStrings.text(count == 1 ? "apple.active_chats_widget.total_one" : "apple.active_chats_widget.total", languageKey: "widget_active_chats_language")
            .replacingOccurrences(of: "{count}", with: String(count))
    }
}
enum ActiveChatsWidgetFixtures {
    static var entry: ActiveChatsWidgetEntry {
        let now = Date()
        return ActiveChatsWidgetEntry(date: now, snapshot: WidgetActiveChatsSnapshot(owner: String(repeating: "a", count: 64),
            teamID: nil, updatedAt: now, chats: (1...9).map {
                WidgetActiveChatSummary(id: "widget-preview-\($0)", title: "Preview chat \($0)", expiresAt: now.addingTimeInterval(900))
            }))
    }
}
#if DEBUG
#if os(iOS)
#Preview("Active chats — Lock Screen circular", as: .accessoryCircular) { ActiveChatsWidget() } timeline: {
    ActiveChatsWidgetFixtures.entry
    ActiveChatsWidgetEntry(date: Date(), snapshot: nil)
}
#Preview("Active chats — Lock Screen rectangular", as: .accessoryRectangular) { ActiveChatsWidget() } timeline: {
    ActiveChatsWidgetFixtures.entry
    ActiveChatsWidgetEntry(date: Date().addingTimeInterval(120), snapshot: ActiveChatsWidgetFixtures.entry.snapshot)
    ActiveChatsWidgetEntry(date: Date(), snapshot: nil)
}
#endif
#Preview("Active chats — medium", as: .systemMedium) { ActiveChatsWidget() } timeline: { ActiveChatsWidgetFixtures.entry }
#Preview("Active chats — large", as: .systemLarge) { ActiveChatsWidget() } timeline: { ActiveChatsWidgetFixtures.entry }
#endif
