// Daily Inspiration home screen widget — shows the current daily inspiration phrase.
// Tapping the widget opens the main app and starts a new chat with that inspiration.
// Uses the public /v1/default-inspirations endpoint (no auth required).
// Data is refreshed every 4 hours via WidgetKit timeline, with a fallback to
// shared App Group data written by the main app.

import WidgetKit
import SwiftUI

// MARK: - Data model

struct WidgetInspiration: Codable {
    let phrase: String
    let title: String
    let category: String
    let inspirationId: String
    let videoTitle: String?
    let channelName: String?
    let thumbnailUrl: String?
    let updatedAt: Date

    /// Fallback inspiration shown when no data is available yet.
    static let placeholder = WidgetInspiration(
        phrase: "Cats always land on their feet. But how do they do it mid-air?",
        title: "Cat Physics",
        category: "science",
        inspirationId: "placeholder",
        videoTitle: nil,
        channelName: nil,
        thumbnailUrl: nil,
        updatedAt: Date()
    )
}

// MARK: - Shared storage (App Group)

enum WidgetStorage {
    static let suiteName = "group.org.openmates.app"
    static let inspirationKey = "widget_daily_inspiration"

    static func save(_ inspiration: WidgetInspiration) {
        guard let defaults = UserDefaults(suiteName: suiteName) else { return }
        if let data = try? JSONEncoder().encode(inspiration) {
            defaults.set(data, forKey: inspirationKey)
        }
    }

    static func load() -> WidgetInspiration? {
        guard let defaults = UserDefaults(suiteName: suiteName),
              let data = defaults.data(forKey: inspirationKey) else { return nil }
        return try? JSONDecoder().decode(WidgetInspiration.self, from: data)
    }
}

// MARK: - API response decoding

/// Matches the /v1/default-inspirations JSON shape.
private struct DefaultInspirationsResponse: Decodable {
    let inspirations: [InspirationItem]

    struct InspirationItem: Decodable {
        let inspirationId: String
        let phrase: String
        let title: String
        let category: String
        let video: VideoInfo?

        struct VideoInfo: Decodable {
            let title: String?
            let channelName: String?
            let thumbnailUrl: String?
        }

        enum CodingKeys: String, CodingKey {
            case inspirationId = "inspiration_id"
            case phrase, title, category, video
        }
    }
}

private extension DefaultInspirationsResponse.InspirationItem.VideoInfo {
    enum CodingKeys: String, CodingKey {
        case title
        case channelName = "channel_name"
        case thumbnailUrl = "thumbnail_url"
    }
}

// MARK: - Timeline provider

struct InspirationTimelineProvider: TimelineProvider {
    typealias Entry = InspirationEntry

    func placeholder(in context: Context) -> InspirationEntry {
        InspirationEntry(date: Date(), inspiration: .placeholder, isPlaceholder: true)
    }

    func getSnapshot(in context: Context, completion: @escaping (InspirationEntry) -> Void) {
        if let cached = WidgetStorage.load() {
            completion(InspirationEntry(date: Date(), inspiration: cached))
        } else {
            completion(placeholder(in: context))
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<InspirationEntry>) -> Void) {
        Task {
            let inspiration = await fetchInspiration()
            let entry = InspirationEntry(date: Date(), inspiration: inspiration)

            // Refresh every 4 hours — aligns with the daily inspiration cadence
            let nextRefresh = Calendar.current.date(byAdding: .hour, value: 4, to: Date()) ?? Date()
            let timeline = Timeline(entries: [entry], policy: .after(nextRefresh))
            completion(timeline)
        }
    }

    private func fetchInspiration() async -> WidgetInspiration {
        // Try fetching from API first
        let baseURL: String = {
            #if DEBUG
            return "https://dev.openmates.org/api"
            #else
            return "https://api.openmates.org"
            #endif
        }()

        guard let url = URL(string: "\(baseURL)/v1/default-inspirations?lang=en") else {
            return WidgetStorage.load() ?? .placeholder
        }

        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoder = JSONDecoder()
            let response = try decoder.decode(DefaultInspirationsResponse.self, from: data)

            if let first = response.inspirations.first {
                let widget = WidgetInspiration(
                    phrase: first.phrase,
                    title: first.title,
                    category: first.category,
                    inspirationId: first.inspirationId,
                    videoTitle: first.video?.title,
                    channelName: first.video?.channelName,
                    thumbnailUrl: first.video?.thumbnailUrl,
                    updatedAt: Date()
                )
                WidgetStorage.save(widget)
                return widget
            }
        } catch {
            // Fall through to cached data
        }

        return WidgetStorage.load() ?? .placeholder
    }
}

// MARK: - Timeline entry

struct InspirationEntry: TimelineEntry {
    let date: Date
    let inspiration: WidgetInspiration
    var isPlaceholder: Bool = false
}

// MARK: - Category icon mapping

private func categoryIcon(for category: String) -> String {
    switch category.lowercased() {
    case "science": return "atom"
    case "technology": return "cpu"
    case "history": return "building.columns"
    case "nature": return "leaf"
    case "art", "music": return "paintpalette"
    case "food", "cooking": return "fork.knife"
    case "travel": return "airplane"
    case "sports", "fitness": return "figure.run"
    case "health": return "heart"
    case "business", "finance": return "chart.line.uptrend.xyaxis"
    case "psychology": return "brain.head.profile"
    case "space", "astronomy": return "sparkles"
    case "engineering": return "gearshape.2"
    case "philosophy": return "book.closed"
    default: return "lightbulb"
    }
}

// MARK: - Small widget view

struct SmallInspirationView: View {
    let entry: InspirationEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                Image(systemName: categoryIcon(for: entry.inspiration.category))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text("Daily Inspiration")
                    .font(.caption2)
                    .fontWeight(.semibold)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Text(entry.inspiration.phrase)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.primary)
                .lineLimit(4)
                .multilineTextAlignment(.leading)

            Spacer()

            HStack {
                Spacer()
                Image(systemName: "arrow.right.circle.fill")
                    .font(.system(size: 16))
                    .foregroundStyle(.blue)
            }
        }
        .padding(12)
    }
}

// MARK: - Medium widget view

struct MediumInspirationView: View {
    let entry: InspirationEntry

    var body: some View {
        HStack(spacing: 12) {
            // Left: inspiration content
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 4) {
                    Image(systemName: categoryIcon(for: entry.inspiration.category))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text("Daily Inspiration")
                        .font(.caption2)
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Text(entry.inspiration.phrase)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.primary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)

                Spacer()

                if let videoTitle = entry.inspiration.videoTitle {
                    HStack(spacing: 4) {
                        Image(systemName: "play.rectangle.fill")
                            .font(.caption2)
                            .foregroundStyle(.red)
                        Text(videoTitle)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // Right: category icon badge + tap indicator
            VStack {
                ZStack {
                    Circle()
                        .fill(.ultraThinMaterial)
                        .frame(width: 44, height: 44)
                    Image(systemName: categoryIcon(for: entry.inspiration.category))
                        .font(.system(size: 20))
                        .foregroundStyle(.blue)
                }

                Spacer()

                Text("Tap to explore")
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
            }
            .frame(width: 60)
        }
        .padding(14)
    }
}

// MARK: - Entry view (family-aware)

struct InspirationWidgetEntryView: View {
    @Environment(\.widgetFamily) var family
    let entry: InspirationEntry

    var body: some View {
        switch family {
        case .systemSmall:
            SmallInspirationView(entry: entry)
        case .systemMedium:
            MediumInspirationView(entry: entry)
        default:
            MediumInspirationView(entry: entry)
        }
    }
}

// MARK: - Widget configuration

struct DailyInspirationWidget: Widget {
    let kind: String = "DailyInspirationWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: InspirationTimelineProvider()) { entry in
            Group {
                if #available(iOS 17.0, macOS 14.0, *) {
                    widgetView(for: entry)
                        .containerBackground(.fill.tertiary, for: .widget)
                } else {
                    widgetView(for: entry)
                        .background()
                }
            }
            .widgetURL(widgetURL(for: entry))
        }
        .configurationDisplayName("Daily Inspiration")
        .description("A new curiosity question every day. Tap to explore with AI.")
        .supportedFamilies([.systemSmall, .systemMedium])
        #if os(iOS)
        .contentMarginsDisabled()
        #endif
    }

    @ViewBuilder
    private func widgetView(for entry: InspirationEntry) -> some View {
        // WidgetKit selects the right family at render time via the view hierarchy
        InspirationWidgetEntryView(entry: entry)
    }

    private func widgetURL(for entry: InspirationEntry) -> URL {
        // Deep link: openmates://inspiration/{id} — handled by the main app's onOpenURL
        URL(string: "openmates://inspiration/\(entry.inspiration.inspirationId)")
            ?? URL(string: "openmates://")!
    }
}

// MARK: - Widget bundle

@main
struct OpenMatesWidgetBundle: WidgetBundle {
    var body: some Widget {
        DailyInspirationWidget()
    }
}

// MARK: - Previews

#if DEBUG
#Preview("Small", as: .systemSmall) {
    DailyInspirationWidget()
} timeline: {
    InspirationEntry(date: Date(), inspiration: .placeholder)
    InspirationEntry(
        date: Date(),
        inspiration: WidgetInspiration(
            phrase: "Roman roads lasted 2,000 years. Modern ones barely survive 20 — why?",
            title: "Roman Engineering",
            category: "history",
            inspirationId: "preview-1",
            videoTitle: "The Secret of Roman Concrete",
            channelName: "Veritasium",
            thumbnailUrl: nil,
            updatedAt: Date()
        )
    )
}

#Preview("Medium", as: .systemMedium) {
    DailyInspirationWidget()
} timeline: {
    InspirationEntry(date: Date(), inspiration: .placeholder)
}
#endif
