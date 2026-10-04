// Shared production row rendering for WidgetKit and detached UI previews.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/chats/Chat.svelte
//         frontend/packages/ui/src/components/ChatHistory.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Native difference: WidgetKit medium/large row limits and per-chat deep links.
// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.activity.global-running
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.processing.widget, apple-live-activities.lifecycle.isolation
import SwiftUI
import WidgetKit

struct WidgetActiveChatsLabels {
    let title: String
    let total: String
    let empty: String
    let openApp: String
    let viewAll: String
    let stale: String
}
struct WidgetActiveChatsContentView: View {
    let snapshot: WidgetActiveChatsSnapshot?
    let date: Date
    let rowLimit: Int
    let labels: WidgetActiveChatsLabels
    private var projection: WidgetActiveChatsProjection { .init(snapshot: snapshot, date: date, limit: rowLimit) }
    private var allURL: URL {
        snapshot.flatMap { WidgetActiveChatsLinks.all(owner: $0.owner, teamID: $0.teamID) } ?? WidgetActiveChatsLinks.openApp
    }
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing2) {
                Text(labels.title).font(.omSmall.bold())
                Spacer(minLength: .spacing2)
                Text(labels.total).font(.omMicro).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("active-chats-widget-total")
            }
            if projection.rows.contains(where: { $0.staleAt <= date }) {
                Text(labels.stale).font(.omMicro).foregroundStyle(Color.fontSecondary).lineLimit(1)
                    .accessibilityIdentifier("active-chats-widget-stale")
            }
            if projection.rows.isEmpty {
                Link(destination: allURL) {
                    Text(snapshot == nil ? labels.openApp : labels.empty)
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                }.accessibilityIdentifier("active-chats-widget-empty")
            } else if let snapshot {
                ForEach(projection.rows) { chat in
                    if let url = WidgetActiveChatsLinks.chat(chat.id, owner: snapshot.owner, teamID: snapshot.teamID) {
                        Link(destination: url) {
                            HStack(spacing: .spacing3) {
                                Image(systemName: "hourglass").font(.omMicro).foregroundStyle(Color.buttonPrimary)
                                Text(chat.title).font(.omSmall).lineLimit(1)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .foregroundStyle(Color.fontPrimary)
                            .privacySensitive()
                        }.accessibilityIdentifier("active-chats-widget-chat-\(chat.id)")
                    }
                }
                Spacer(minLength: 0)
            }
            if projection.total > 0 {
                Link(destination: allURL) {
                    Text(labels.viewAll).font(.omSmall.weight(.semibold)).foregroundStyle(Color.buttonPrimary)
                }.accessibilityIdentifier("active-chats-widget-view-all")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("active-chats-widget")
        .accessibilityValue("total=\(projection.total);visible=\(projection.rows.count);overflow=\(projection.overflow)")
    }
}

#if os(iOS)
/// OS-owned accessory sizing uses a count in the circle and one title in the wide slot.
struct WidgetActiveChatsAccessoryView: View {
    let snapshot: WidgetActiveChatsSnapshot?
    let date: Date
    let family: WidgetFamily
    let labels: WidgetActiveChatsLabels
    private var projection: WidgetActiveChatsProjection {
        .init(snapshot: snapshot, date: date, limit: WidgetActiveChatsProjection.rowLimit(for: family))
    }
    private var allURL: URL {
        snapshot.flatMap { WidgetActiveChatsLinks.all(owner: $0.owner, teamID: $0.teamID) } ?? WidgetActiveChatsLinks.openApp
    }
    var body: some View {
        Group {
            if family == .accessoryCircular {
                Link(destination: allURL) {
                    ZStack {
                        AccessoryWidgetBackground()
                        VStack(spacing: .spacing1) {
                            Image(systemName: snapshot == nil ? "lock" :
                                (snapshot?.active(at: date).contains { $0.staleAt <= date } == true ? "clock" : "hourglass"))
                                .font(.omSmall)
                            Text(snapshot == nil ? "—" : String(projection.total)).font(.omSmall.bold())
                                .privacySensitive()
                        }
                    }
                }
                .accessibilityLabel(snapshot == nil ? labels.openApp : labels.total)
                .accessibilityIdentifier("active-chats-widget-circular")
            } else {
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(snapshot == nil ? labels.title : labels.total).font(.omMicro.bold()).lineLimit(1).privacySensitive()
                        .accessibilityIdentifier("active-chats-widget-total")
                    if let snapshot, let chat = projection.rows.first,
                       let url = WidgetActiveChatsLinks.chat(chat.id, owner: snapshot.owner, teamID: snapshot.teamID) {
                        Link(destination: url) {
                            Text(chat.title).font(.omSmall).lineLimit(1).privacySensitive()
                        }.accessibilityIdentifier("active-chats-widget-chat-\(chat.id)")
                    } else {
                        Link(destination: allURL) {
                            Text(snapshot == nil ? labels.openApp : labels.empty).font(.omMicro).lineLimit(1)
                        }.accessibilityIdentifier("active-chats-widget-empty")
                    }
                    if projection.total > 0 {
                        Link(destination: allURL) {
                            Text(projection.rows.contains { $0.staleAt <= date } ? labels.stale : labels.viewAll)
                                .font(.omMicro).lineLimit(1)
                        }.accessibilityIdentifier("active-chats-widget-view-all")
                    }
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("active-chats-widget")
        .accessibilityValue("total=\(projection.total);visible=\(projection.rows.count);overflow=\(projection.overflow)")
    }
}
#endif
