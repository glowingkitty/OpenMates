// Miscellaneous embed renderers for social posts, weather, mail, math, and utilities.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/diagrams/MermaidDiagramEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/diagrams/MermaidDiagramEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/math/MathPlotEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/math/MathPlotEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/specifications/specification.yml
// Assertions: contracts.diagrams.private-rendering, contracts.diagrams.revision-pinned-editing
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity (MathPlot web/native rendering)

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct SocialMediaPostEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var post: SocialMediaPostValue {
        SocialMediaPostValue(data: data ?? [:])
    }

    var body: some View {
        switch mode {
        case .preview:
            SocialMediaPostPreview(post: post)
        case .fullscreen:
            SocialMediaPostFullscreen(post: post)
        }
    }
}

private struct SocialMediaPostPreview: View {
    let post: SocialMediaPostValue

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(alignment: .top, spacing: .spacing4) {
                SocialMediaAvatar(post: post, size: 34)
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(post.title ?? post.displayAuthor ?? AppStrings.socialMedia)
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(2)
                    Text(post.previewMetadata)
                        .font(.omXxs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            Spacer(minLength: 0)

            HStack(spacing: .spacing3) {
                Text("\(post.likeCount.formatted()) likes")
                Text("\(post.replyCount.formatted()) comments")
                if post.repostCount > 0 {
                    Text("\(post.repostCount.formatted()) reposts")
                }
                Spacer(minLength: 0)
                if let mediaURL = post.mediaURL {
                    SocialMediaImage(url: mediaURL, contentMode: .fill)
                        .frame(width: 54, height: 54)
                        .clipShape(RoundedRectangle(cornerRadius: .radius5))
                }
            }
            .font(.omXxs)
            .foregroundStyle(Color.fontSecondary)
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

private struct SocialMediaPostFullscreen: View {
    let post: SocialMediaPostValue

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: .spacing5) {
                        SocialMediaAvatar(post: post, size: 48)
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(post.displayAuthor ?? AppStrings.socialMedia)
                                .font(.omP.weight(.bold))
                                .foregroundStyle(Color.fontPrimary)
                            Text(post.fullMetadata)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontSecondary)
                                .lineLimit(2)
                        }
                    }
                    .padding(.spacing8)

                    VStack(alignment: .leading, spacing: .spacing5) {
                        if let title = post.title, title != post.body {
                            Text(title)
                                .font(.omXl.weight(.bold))
                                .foregroundStyle(Color.fontPrimary)
                        }
                        if let body = post.body {
                            ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(AttributedString(body), lineHeight: 25.6),
                                identifier: "social-post-body-selection")
                        }
                    }
                    .padding(.horizontal, .spacing8)
                    .padding(.bottom, .spacing6)

                    if let mediaURL = post.mediaURL {
                        SocialMediaImage(url: mediaURL, contentMode: .fit)
                            .frame(maxWidth: .infinity, maxHeight: 520)
                            .background(Color.grey10)
                            .overlay(alignment: .top) { Rectangle().fill(Color.grey20).frame(height: 1) }
                            .overlay(alignment: .bottom) { Rectangle().fill(Color.grey20).frame(height: 1) }
                    }

                    if let externalText = post.externalTitle ?? post.externalURL {
                        HStack(spacing: .spacing3) {
                            Icon("share", size: .iconSizeSm)
                            Text(externalText).font(.omSmall).lineLimit(2)
                        }
                        .foregroundStyle(Color.fontPrimary)
                        .padding(.spacing5)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius7))
                        .overlay { RoundedRectangle(cornerRadius: .radius7).stroke(Color.grey20, lineWidth: 1) }
                        .padding(.horizontal, .spacing8)
                        .padding(.bottom, .spacing6)
                    }

                    HStack(spacing: .spacing6) {
                        SocialMediaMetric(icon: "heart", value: post.likeCount.formatted())
                        SocialMediaMetric(icon: "chat", value: post.replyCount.formatted())
                        SocialMediaMetric(icon: "share", value: post.repostCount.formatted())
                    }
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing8)
                    .padding(.vertical, .spacing5)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .overlay(alignment: .top) { Rectangle().fill(Color.grey20).frame(height: 1) }
                }
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1) }
                .shadow(color: .black.opacity(0.10), radius: 20, x: 0, y: 8)

                if !post.comments.isEmpty {
                    VStack(alignment: .leading, spacing: .spacing6) {
                        HStack {
                            Icon("chat", size: .iconSizeSm).foregroundStyle(Color.fontPrimary)
                            Spacer()
                            Text(post.comments.count.formatted()).font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                        ForEach(post.comments) { comment in
                            VStack(alignment: .leading, spacing: .spacing2) {
                                HStack {
                                    Text(comment.author.map { "@\($0)" } ?? AppStrings.socialMedia)
                                    Spacer()
                                    if let points = comment.points {
                                        SocialMediaMetric(icon: "heart", value: points.formatted())
                                    }
                                }
                                .font(.omXs.weight(.semibold))
                                .foregroundStyle(Color.fontSecondary)
                                ReadOnlySelectableText(content: ReadOnlySelectableText.attributed(AttributedString(comment.body),
                                    pointSize: 14, lineHeight: 21), identifier: "social-comment-\(comment.id)-selection")
                            }
                            .padding(.top, .spacing5)
                            .overlay(alignment: .top) { Rectangle().fill(Color.grey20).frame(height: 1) }
                        }
                    }
                    .padding(.spacing8)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1) }
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing12)
            .frame(maxWidth: 820)
            .frame(maxWidth: .infinity)
        }
    }
}

private struct SocialMediaAvatar: View {
    let post: SocialMediaPostValue
    let size: CGFloat

    var body: some View {
        Group {
            if let avatarURL = post.avatarURL {
                SocialMediaImage(url: avatarURL, contentMode: .fill)
            } else if let displayAuthor = post.displayAuthor {
                ZStack {
                    LinearGradient.appSocialmedia
                    Text(String(displayAuthor.prefix(1)).uppercased())
                        .font(.omSmall.weight(.bold))
                        .foregroundStyle(Color.fontButton)
                }
            } else {
                ZStack {
                    LinearGradient.appSocialmedia
                    Icon("socialmedia", size: size * 0.55).foregroundStyle(Color.fontButton)
                }
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
    }
}

private struct SocialMediaImage: View {
    let url: String
    let contentMode: ContentMode

    var body: some View {
        if let proxied = EmbedFieldReader.proxiedImageURL(url, maxWidth: 820), let imageURL = URL(string: proxied) {
            CachedRemoteImage(url: imageURL) { image in
                image.resizable().aspectRatio(contentMode: contentMode)
            } placeholder: {
                Color.grey20
            }
            .clipped()
        }
    }
}

private struct SocialMediaMetric: View {
    let icon: String
    let value: String

    var body: some View {
        HStack(spacing: .spacing2) {
            Icon(icon, size: .iconSizeXs)
            Text(value)
        }
    }
}

struct WeatherDayEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var weather: WeatherDayValue {
        WeatherDayValue(data: data ?? [:])
    }

    var body: some View {
        switch mode {
        case .preview:
            WeatherDayPreview(weather: weather)
        case .fullscreen:
            WeatherDayFullscreen(weather: weather)
        }
    }
}

private struct WeatherDayPreview: View {
    let weather: WeatherDayValue

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(weather.dateTitle ?? AppStrings.weatherDay)
                    .font(.custom("Lexend Deca", size: 15).weight(.semibold))
                    .foregroundStyle(Color.grey100)
                    .lineLimit(1)
                Text(weather.displayCondition ?? "—")
                    .font(.omXs)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
            }

            Spacer(minLength: 0)
            HStack(spacing: 10) {
                WeatherConditionIcon(icon: weather.icon, condition: weather.condition, size: 82)
                Spacer(minLength: 0)
                Text(weather.temperatureRange)
                    .font(.custom("Lexend Deca", size: 25).weight(.semibold))
                    .foregroundStyle(Color.grey100)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }

            Spacer(minLength: 0)
            HStack(spacing: 6) {
                WeatherPill(text: "\(weather.rainChance.formatted())% rain")
                WeatherPill(text: "\(weather.precipitation.formatted()) mm")
                WeatherPill(text: "\(weather.rainHours.formatted())h")
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: 145, maxHeight: .infinity, alignment: .topLeading)
        .background {
            LinearGradient.appWeather.opacity(0.14)
                .overlay {
                    LinearGradient.appWeather.opacity(0.28)
                        .mask {
                            RadialGradient(colors: [.black, .clear], center: UnitPoint(x: 0.18, y: 0.18), startRadius: 0, endRadius: 115)
                        }
                }
                .background(Color.grey0)
        }
        .clipShape(RoundedRectangle(cornerRadius: 20))
        .overlay { RoundedRectangle(cornerRadius: 20).stroke(Color.grey20, lineWidth: 1) }
    }
}

private struct WeatherDayFullscreen: View {
    let weather: WeatherDayValue
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private var compact: Bool { horizontalSizeClass == .compact }

    var body: some View {
        ScrollView {
            VStack(spacing: compact ? 12 : 18) {
                summaryCard
                metricsGrid
                hourlyCard
            }
            .padding(.horizontal, compact ? 8 : 16)
            .padding(.top, compact ? 14 : 20)
            .padding(.bottom, compact ? 96 : 120)
            .frame(maxWidth: 980)
            .frame(maxWidth: .infinity)
        }
    }

    private var metricsGrid: some View {
        LazyVGrid(
            columns: Array(repeating: GridItem(.flexible(), spacing: compact ? 8 : 12), count: compact ? 2 : 4),
            spacing: compact ? 8 : 12
        ) {
            WeatherMetricCard(label: "Rain chance", value: "\(weather.rainChance.formatted())%", detail: "\(weather.precipitation.formatted()) mm · \(weather.rainHours.formatted())h", compact: compact)
            WeatherMetricCard(label: "Wind", value: weather.windText, detail: "Max speed", compact: compact)
            WeatherMetricCard(label: "Clouds", value: weather.cloudText, detail: "Average cover", compact: compact)
            WeatherMetricCard(label: "Humidity", value: weather.humidityText, detail: "Average", compact: compact)
        }
    }

    private var hourlyCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Hourly forecast").font(.omLg.weight(.bold)).foregroundStyle(Color.grey100)
                Spacer()
                Text("\(weather.hourly.count) entries").font(.omXs).foregroundStyle(Color.grey60)
            }
            if weather.hourly.isEmpty {
                Text("No hourly data available.").font(.omXs).foregroundStyle(Color.grey60)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(spacing: 10) {
                        ForEach(weather.hourly) { hour in
                            hourlyRow(hour)
                        }
                    }
                }
            }
        }
        .padding(compact ? 12 : 16)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: compact ? 18 : 22))
        .overlay { RoundedRectangle(cornerRadius: compact ? 18 : 22).stroke(Color.grey20, lineWidth: 1) }
        .shadow(color: Color.grey100.opacity(0.07), radius: 16, x: 0, y: 6)
    }

    private func hourlyRow(_ hour: WeatherHourValue) -> some View {
        VStack(spacing: 5) {
            Text(hour.time ?? "—").font(.omXxs.weight(.semibold)).foregroundStyle(Color.grey100)
            WeatherConditionIcon(icon: hour.icon ?? weather.icon, condition: hour.condition ?? weather.condition, size: 34)
            Text(hour.temperature.map { "\($0.formatted())°" } ?? "—°")
                .font(.custom("Lexend Deca", size: 18).weight(.bold)).foregroundStyle(Color.grey100)
            Text("\((hour.rainChance ?? 0).formatted())% rain")
            Text("\((hour.precipitation ?? 0).formatted()) mm")
            Text(hour.wind.map { "\($0.formatted()) km/h" } ?? "—")
        }
        .font(compact ? .omTiny : .omXxs)
        .foregroundStyle(Color.grey70)
        .padding(.horizontal, compact ? 7 : 9)
        .padding(.vertical, compact ? 9 : 11)
        .frame(minWidth: compact ? 82 : 96)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: compact ? 15 : 18))
        .overlay { RoundedRectangle(cornerRadius: compact ? 15 : 18).stroke(Color.grey20, lineWidth: 1) }
    }

    private var summaryCard: some View {
        summaryLayout
            .padding(compact ? 18 : 28)
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(minHeight: compact ? 0 : 245, alignment: .leading)
            .background(summaryBackground)
            .clipShape(RoundedRectangle(cornerRadius: compact ? 24 : 32))
            .overlay {
                RoundedRectangle(cornerRadius: compact ? 24 : 32)
                    .stroke(Color.grey20, lineWidth: 1)
            }
            .shadow(color: Color.grey100.opacity(0.13), radius: 24, x: 0, y: 10)
    }

    @ViewBuilder
    private var summaryLayout: some View {
        Group {
            if compact {
                VStack(alignment: .leading, spacing: 6) {
                    weatherSummary
                    WeatherConditionIcon(icon: weather.icon, condition: weather.condition, size: 108)
                }
            } else {
                HStack(spacing: 24) {
                    weatherSummary
                    Spacer(minLength: 0)
                    WeatherConditionIcon(icon: weather.icon, condition: weather.condition, size: 142)
                }
            }
        }
    }

    private var summaryBackground: some View {
        LinearGradient.appWeather.opacity(0.28)
            .overlay {
                LinearGradient.appWeather.opacity(0.38)
                    .mask {
                        RadialGradient(
                            colors: [.black, .clear],
                            center: UnitPoint(x: 0.88, y: 0.22),
                            startRadius: 0,
                            endRadius: 145
                        )
                    }
            }
            .background(Color.grey0)
    }

    private var weatherSummary: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(weather.dateFull ?? AppStrings.weatherDay).font(compact ? .omXxs : .omSmall).foregroundStyle(Color.grey70)
            Text(weather.displayCondition ?? AppStrings.weatherDay)
                .font(.custom("Lexend Deca", size: compact ? 38 : 54).weight(.bold))
                .foregroundStyle(Color.grey100)
                .lineLimit(2)
                .minimumScaleFactor(0.75)
                .padding(.top, 8)
            if !weather.locationProvider.isEmpty {
                Text(weather.locationProvider).font(compact ? .omXxs : .omSmall).foregroundStyle(Color.grey70)
            }
            Text(weather.temperatureRange)
                .font(.custom("Lexend Deca", size: compact ? 48 : 64).weight(.bold))
                .foregroundStyle(Color.grey100)
                .padding(.top, compact ? 12 : 18)
        }
    }
}

private struct WeatherPill: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.omXs)
            .foregroundStyle(Color.grey70)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Color.grey0.opacity(0.82))
            .clipShape(Capsule())
            .overlay { Capsule().stroke(Color.grey20, lineWidth: 1) }
            .shadow(color: Color.grey100.opacity(0.06), radius: 7, x: 0, y: 4)
    }
}

private struct WeatherMetricCard: View {
    let label: String
    let value: String
    let detail: String
    let compact: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label.uppercased())
                .font(.custom("Lexend Deca", size: compact ? 10 : 12))
                .foregroundStyle(Color.grey60)
            Text(value)
                .font(.custom("Lexend Deca", size: compact ? 18 : 22).weight(.bold))
                .foregroundStyle(Color.grey100)
            Text(detail)
                .font(compact ? .omXxs : .omXs)
                .foregroundStyle(Color.grey70)
        }
        .padding(compact ? 12 : 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: compact ? 18 : 22))
        .overlay { RoundedRectangle(cornerRadius: compact ? 18 : 22).stroke(Color.grey20, lineWidth: 1) }
        .shadow(color: Color.grey100.opacity(0.07), radius: 16, x: 0, y: 6)
    }
}

private struct WeatherConditionIcon: View {
    let icon: String
    let condition: String
    let size: CGFloat

    var body: some View {
        Image("weather-condition-\(WeatherForecastSkillCard.meteoconSlug(icon: icon, condition: condition))")
            .renderingMode(.original)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .shadow(color: Color.grey100.opacity(size <= 34 ? 0.14 : 0.18), radius: size <= 34 ? 8 : 18, x: 0, y: size <= 34 ? 4 : 8)
            .accessibilityHidden(true)
    }
}

private struct SocialMediaPostValue {
    let platform: String?
    let page: String?
    let title: String?
    let body: String?
    let author: String?
    let displayAuthor: String?
    let avatarURL: String?
    let publishedAt: String?
    let mediaURL: String?
    let externalURL: String?
    let externalTitle: String?
    let likeCount: Double
    let replyCount: Double
    let repostCount: Double
    let comments: [SocialMediaCommentValue]

    init(data: [String: AnyCodable]) {
        platform = MiscEmbedValue.string(data, "platform")
        page = MiscEmbedValue.string(data, "page")
        title = MiscEmbedValue.string(data, "title")
        body = MiscEmbedValue.string(data, "body")
        author = MiscEmbedValue.string(data, "author")
        displayAuthor = MiscEmbedValue.string(data, "author_display_name") ?? author ?? page ?? platform
        avatarURL = MiscEmbedValue.string(data, "author_avatar_url")
        publishedAt = MiscEmbedValue.string(data, "published_at")
        mediaURL = MiscEmbedValue.string(data, "media_url") ?? MiscEmbedValue.string(data, "thumbnail_url")
        externalURL = MiscEmbedValue.string(data, "external_url")
        externalTitle = MiscEmbedValue.string(data, "external_title")
        likeCount = MiscEmbedValue.number(data, "like_count") ?? 0
        replyCount = MiscEmbedValue.number(data, "reply_count") ?? 0
        repostCount = MiscEmbedValue.number(data, "repost_count") ?? 0
        comments = MiscEmbedValue.objects(data, "comments").compactMap(SocialMediaCommentValue.init)
    }

    var source: String { [platform?.capitalized, page].compactMap { $0 }.joined(separator: " / ") }
    var previewMetadata: String { [source.isEmpty ? nil : source, publishedAt].compactMap { $0 }.joined(separator: " · ") }
    var fullMetadata: String { [author.map { "@\($0)" }, publishedAt ?? (source.isEmpty ? nil : source)].compactMap { $0 }.joined(separator: " · ") }
}

private struct SocialMediaCommentValue: Identifiable {
    let id: String
    let author: String?
    let body: String
    let points: Double?

    init?(data: [String: AnyCodable]) {
        guard let body = MiscEmbedValue.string(data, "body") else { return nil }
        let resolvedAuthor = MiscEmbedValue.string(data, "author")
        author = resolvedAuthor
        self.body = body
        id = MiscEmbedValue.string(data, "id") ?? "\(resolvedAuthor ?? "comment")-\(body)"
        points = MiscEmbedValue.number(data, "ups") ?? MiscEmbedValue.number(data, "score")
    }
}

private struct WeatherDayValue {
    let date: String?
    let location: String?
    let provider: String
    let condition: String
    let icon: String
    let minimum: Double?
    let maximum: Double?
    let precipitation: Double
    let rainChance: Double
    let rainHours: Double
    let wind: Double?
    let cloudCover: Double?
    let humidity: Double?
    let hourly: [WeatherHourValue]

    init(data: [String: AnyCodable]) {
        date = MiscEmbedValue.string(data, "date")
        location = MiscEmbedValue.string(data, "location_name")
        provider = MiscEmbedValue.string(data, "provider") ?? "Weather"
        condition = MiscEmbedValue.string(data, "condition") ?? ""
        icon = MiscEmbedValue.string(data, "icon") ?? ""
        minimum = MiscEmbedValue.number(data, "temperature_min_c")
        maximum = MiscEmbedValue.number(data, "temperature_max_c")
        precipitation = MiscEmbedValue.number(data, "precipitation_total_mm") ?? 0
        rainChance = MiscEmbedValue.number(data, "precipitation_probability_max_pct") ?? 0
        rainHours = MiscEmbedValue.number(data, "rain_hours") ?? 0
        wind = MiscEmbedValue.number(data, "wind_speed_max_kmh")
        cloudCover = MiscEmbedValue.number(data, "cloud_cover_avg_pct")
        humidity = MiscEmbedValue.number(data, "relative_humidity_avg_pct")
        hourly = MiscEmbedValue.objects(data, "hourly").map(WeatherHourValue.init)
    }

    var displayCondition: String? {
        condition.isEmpty ? nil : condition.replacingOccurrences(of: "[-_]", with: " ", options: .regularExpression).capitalized
    }
    var dateTitle: String? { formattedDate("EEEE, MMM d") }
    var dateFull: String? { formattedDate("EEEE, MMMM d") }
    var locationProvider: String { [location, provider].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ") }
    var temperatureRange: String {
        if let minimum, let maximum { return "\(minimum.rounded().formatted())° / \(maximum.rounded().formatted())°" }
        if let minimum { return "\(minimum.rounded().formatted())°" }
        if let maximum { return "\(maximum.rounded().formatted())°" }
        return "—"
    }
    var windText: String { wind.map { "\($0.formatted()) km/h" } ?? "—" }
    var cloudText: String { cloudCover.map { "\($0.formatted())%" } ?? "—" }
    var humidityText: String { humidity.map { "\($0.formatted())%" } ?? "—" }

    private func formattedDate(_ format: String) -> String? {
        guard let date else { return nil }
        let parser = DateFormatter()
        parser.dateFormat = "yyyy-MM-dd"
        parser.locale = Locale(identifier: "en_US_POSIX")
        guard let value = parser.date(from: date) else { return date }
        let formatter = DateFormatter()
        formatter.dateFormat = format
        formatter.locale = Locale.current
        return formatter.string(from: value)
    }

}

private struct WeatherHourValue: Identifiable {
    let id: String
    let time: String?
    let condition: String?
    let icon: String?
    let temperature: Double?
    let precipitation: Double?
    let rainChance: Double?
    let wind: Double?

    init(data: [String: AnyCodable]) {
        let resolvedTime = MiscEmbedValue.string(data, "time")
        let resolvedCondition = MiscEmbedValue.string(data, "condition")
        let resolvedIcon = MiscEmbedValue.string(data, "icon")
        time = resolvedTime
        condition = resolvedCondition
        icon = resolvedIcon
        id = "\(resolvedTime ?? "hour")-\(resolvedCondition ?? resolvedIcon ?? "weather")"
        temperature = MiscEmbedValue.number(data, "temperature_c")
        precipitation = MiscEmbedValue.number(data, "precipitation_mm")
        rainChance = MiscEmbedValue.number(data, "precipitation_probability_pct")
        wind = MiscEmbedValue.number(data, "wind_speed_kmh")
    }
}

private enum MiscEmbedValue {
    static func string(_ data: [String: AnyCodable], _ key: String) -> String? {
        guard let value = data[key]?.value as? String else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed == "null" ? nil : trimmed
    }

    static func number(_ data: [String: AnyCodable], _ key: String) -> Double? {
        if let value = data[key]?.value as? Double { return value }
        if let value = data[key]?.value as? Int { return Double(value) }
        if let value = data[key]?.value as? String { return Double(value) }
        return nil
    }

    static func objects(_ data: [String: AnyCodable], _ key: String) -> [[String: AnyCodable]] {
        if let values = data[key]?.value as? [[String: AnyCodable]] { return values }
        if let values = data[key]?.value as? [[String: Any]] {
            return values.map { $0.mapValues(AnyCodable.init) }
        }
        return []
    }
}

// Web: embeds/mail/MailEmbedPreview.svelte, embeds/mail/MailEmbedFullscreen.svelte
struct MailRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @Environment(\.embedPIIMappings) private var mappings
    @Environment(\.embedPIIRevealed) private var revealed

    private var mail: MailEmbedModel { MailEmbedModel(data).applyingPII(mappings: mappings, revealed: revealed) }

    var body: some View {
        switch mode {
        case .preview:
            Text(mail.previewBody.isEmpty ? AppStrings.localized("embeds.mail.empty_content") : mail.previewBody)
                .font(.omXs).foregroundStyle(Color.fontSecondary)
                .lineSpacing(1.8).lineLimit(5)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                .accessibilityIdentifier("mail-body-preview")
        case .fullscreen:
            VStack(alignment: .leading, spacing: 14) {
                mailField("embeds.mail.to", value: mail.receiver.isEmpty ? "—" : mail.receiver, id: "mail-receiver")
                mailField("embeds.mail.subject", value: mail.subject.isEmpty ? "—" : mail.subject, id: "mail-subject")
                mailField("embeds.mail.content", value: mail.content.isEmpty ? AppStrings.localized("embeds.mail.empty_content") : mail.content, id: "mail-content", bordered: true)
                if !mail.footer.isEmpty {
                    mailField("embeds.mail.footer", value: mail.footer, id: "mail-footer", bordered: true, italic: true)
                }
            }
            .padding(.spacing8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius6))
            .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey25, lineWidth: 1))
            .padding(.horizontal, 12)
            .padding(.top, 50)
            .padding(.bottom, 100)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("mail-fullscreen-content")
        }
    }

    private func mailField(_ key: String, value: String, id: String, bordered: Bool = false, italic: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(AppStrings.localized(key).uppercased())
                .font(.omTiny.weight(.bold)).tracking(0.55).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier(id + "-label")
            MailDraftText(value: value, italic: italic)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.vertical, bordered ? .spacing5 : 0)
                .padding(.horizontal, bordered ? .spacing6 : 0)
                .frame(maxWidth: .infinity, minHeight: bordered ? 44 : nil, alignment: .leading)
                .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius4))
                .overlay(RoundedRectangle(cornerRadius: .radius4).stroke(bordered ? Color.grey20 : .clear, lineWidth: 1))
                .accessibilityIdentifier(id)
        }
    }
}

// MathPlotEmbedFullscreen.svelte and function-plot's chart.js define these
// dimensions, domain, tick spacing and graph colors (they are library values).
private struct MathPlotViewportHeightKey: EnvironmentKey {
    static let defaultValue: CGFloat = 0
}

extension EnvironmentValues {
    var mathPlotViewportHeight: CGFloat {
        get { self[MathPlotViewportHeightKey.self] }
        set { self[MathPlotViewportHeightKey.self] = newValue }
    }
}

struct MathPlotGeometry {
    let bounds: CGRect
    let unit: CGFloat
    let origin: CGPoint

    init(size: CGSize, zoom: CGFloat = 1, offset: CGSize = .zero) {
        bounds = CGRect(x: 40, y: 20, width: max(1, size.width - 60), height: max(1, size.height - 40))
        unit = bounds.width / 12 * zoom
        origin = CGPoint(x: bounds.midX + offset.width, y: bounds.midY + offset.height)
    }

    var xRange: ClosedRange<Double> {
        Double((bounds.minX - origin.x) / unit)...Double((bounds.maxX - origin.x) / unit)
    }
    var yRange: ClosedRange<Double> {
        Double((origin.y - bounds.maxY) / unit)...Double((origin.y - bounds.minY) / unit)
    }

    func sample(_ expression: MathPlotExpression, at pixelX: CGFloat) -> CGPoint? {
        let x = Double((pixelX - origin.x) / unit)
        guard let value = expression.value(at: x), value.isFinite else { return nil }
        let point = CGPoint(x: pixelX, y: origin.y - CGFloat(value) * unit)
        // Cull against the visible viewport, which stays fixed while the
        // function origin pans. Retain a bounded margin for edge crossings.
        let margin = bounds.height * 4
        guard point.y >= bounds.minY - margin, point.y <= bounds.maxY + margin else { return nil }
        return point
    }

    // d3's linear tick increment, used by function-plot with the default count10.
    static func ticks(in range: ClosedRange<Double>) -> [Double] {
        let step = (range.upperBound - range.lowerBound) / 10
        guard step.isFinite, step > 0 else { return [] }
        let power = floor(log10(step))
        let error = step / pow(10, power)
        let factor = error >= sqrt(50) ? 10.0 : error >= sqrt(10) ? 5.0 : error >= sqrt(2) ? 2.0 : 1.0
        let increment = pow(10, power) * factor
        let first = Int(ceil(range.lowerBound / increment))
        let last = Int(floor(range.upperBound / increment))
        guard first <= last, last - first < 100 else { return [] }
        return (first...last).map { Double($0) * increment }
    }

    static func graphHeight(viewportHeight: CGFloat, formulaCount: Int) -> CGFloat {
        // Web wrapper: min-height100vh-196-48; includes48px vertical
        // padding,16px gap and the formula card (32px padding +23px rows).
        let card = formulaCount > 0 ? 32 + CGFloat(formulaCount) * 23 + CGFloat(formulaCount - 1) * 8 : 0
        return max(200, viewportHeight - 196 - 96 - card - (formulaCount > 0 ? 16 : 0))
    }
}

struct MathPlotExpression {
    let source: String

    init(_ formula: String) {
        source = (formula.split(separator: "=", maxSplits: 1).last.map(String.init) ?? formula)
            .replacingOccurrences(of: " ", with: "").lowercased()
    }

    var isSupported: Bool { value(at: 0) != nil }

    func value(at x: Double) -> Double? {
        switch source {
        case "sin(x)": return sin(x)
        case "cos(x)": return cos(x)
        case "tan(x)": return tan(x)
        case "x": return x
        case "x^2": return x * x
        case "x^3": return x * x * x
        default: return Double(source)
        }
    }
}

struct MathPlotRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @Environment(\.mathPlotViewportHeight) private var viewportHeight

    private var plotSpec: String {
        (data?["plot_spec"]?.value as? String)
            ?? (data?["expression"]?.value as? String)
            ?? ""
    }

    private var formulas: [String] {
        plotSpec.split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && !$0.hasPrefix("#") }
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                ForEach(Array(formulas.prefix(4).enumerated()), id: \.offset) { _, formula in
                    formulaText(formula, size: 14)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(1)
                        .accessibilityLabel(formula)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .accessibilityIdentifier("math-plot-formulas")

        case .fullscreen:
            VStack(spacing: .spacing8) {
                if !formulas.isEmpty {
                    VStack(spacing: .spacing4) {
                        ForEach(Array(formulas.enumerated()), id: \.offset) { index, formula in
                            ScrollView(.horizontal, showsIndicators: false) {
                                formulaText(formula)
                                    .foregroundStyle(Color.fontPrimary)
                                    .frame(minWidth: 1)
                                    .padding(.horizontal, 1)
                                    .accessibilityLabel(formula)
                            }
                            .defaultScrollAnchor(.center)
                            .frame(height: 23)
                            .accessibilityElement(children: .contain)
                            .accessibilityIdentifier("math-plot-formula-\(index)")
                        }
                    }
                    .padding(.vertical, .spacing8)
                    .padding(.horizontal, .spacing10)
                    .frame(maxWidth: .infinity)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius5))
                    .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20))
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("math-plot-formula-card")
                }

                if formulas.contains(where: { !MathPlotExpression($0).isSupported }) {
                    // Keep the submitted formulas visible and expose failed plotting;
                    // unsupported expressions must never become an empty success graph.
                    Text(AppStrings.error)
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("math-plot-render-error")
                } else {
                    MathPlotGraph(formulas: formulas)
                        .frame(height: MathPlotGeometry.graphHeight(viewportHeight: viewportHeight, formulaCount: formulas.count))
                        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius5))
                        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20))
                }
            }
            .padding(.vertical, .spacing12)
            .padding(.horizontal, .spacing8)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("math-plot-fullscreen")
        }
    }

    // Match KaTeX's18px serif variables and upright function names. Preserve
    // source text for VoiceOver; superscripts only change visual presentation.
    private func formulaText(_ formula: String, size: CGFloat = 18) -> Text {
        let chars = Array(formula)
        var text = Text("")
        var index = 0
        while index < chars.count {
            if chars[index] == "^", index + 1 < chars.count, chars[index + 1].isNumber {
                index += 1
                text = text + Text(String(chars[index])).font(.custom("TimesNewRomanPSMT", size: size * 2 / 3)).baselineOffset(size / 3)
            } else {
                let char = chars[index]
                let isVariable = char.isLetter && (index == 0 || !chars[index - 1].isLetter)
                    && (index + 1 == chars.count || !chars[index + 1].isLetter)
                text = text + Text(String(char)).font(.custom(isVariable ? "TimesNewRomanPS-ItalicMT" : "TimesNewRomanPSMT", size: size))
            }
            index += 1
        }
        return text
    }
}

private struct MathPlotGraph: View {
    let formulas: [String]
    @Environment(\.colorScheme) private var colorScheme
    @State private var zoom: CGFloat = 1
    @State private var zoomOrigin: CGFloat = 1
    @State private var dragOffset: CGSize = .zero
    @State private var dragOrigin: CGSize = .zero

    var body: some View {
        Canvas { context, size in
            let geometry = MathPlotGeometry(size: size, zoom: zoom, offset: dragOffset)
            let rect = geometry.bounds
            let unit = geometry.unit
            let center = geometry.origin
            let labelColor: Color = colorScheme == .dark ? Color(white: 0.8) : Color(white: 0.2)
            let gridColor: Color = colorScheme == .dark ? .grey60 : Color(white: 1.0 / 3)
            var grid = Path()
            for tick in MathPlotGeometry.ticks(in: geometry.xRange) {
                let x = center.x + CGFloat(tick) * unit
                grid.move(to: CGPoint(x: x, y: rect.minY))
                grid.addLine(to: CGPoint(x: x, y: rect.maxY))
                context.draw(Text(tickLabel(tick)).font(.system(size: 11)).foregroundColor(labelColor),
                             at: CGPoint(x: x, y: rect.maxY + 3), anchor: .top)
            }
            for tick in MathPlotGeometry.ticks(in: geometry.yRange) {
                let y = center.y - CGFloat(tick) * unit
                grid.move(to: CGPoint(x: rect.minX, y: y))
                grid.addLine(to: CGPoint(x: rect.maxX, y: y))
                context.draw(Text(tickLabel(tick)).font(.system(size: 11)).foregroundColor(labelColor),
                             at: CGPoint(x: rect.minX - 3, y: y), anchor: .trailing)
            }
            context.stroke(grid, with: .color(gridColor.opacity(0.1)), lineWidth: 1)
            context.stroke(Path(rect), with: .color(gridColor.opacity(0.2)), lineWidth: 1)
            var axes = Path()
            if rect.minX...rect.maxX ~= center.x {
                axes.move(to: CGPoint(x: center.x, y: rect.minY))
                axes.addLine(to: CGPoint(x: center.x, y: rect.maxY))
            }
            if rect.minY...rect.maxY ~= center.y {
                axes.move(to: CGPoint(x: rect.minX, y: center.y))
                axes.addLine(to: CGPoint(x: rect.maxX, y: center.y))
            }
            context.stroke(axes, with: .color(labelColor.opacity(0.2)), lineWidth: 1)

            // function-plot globals.COLORS, independent of system accent colors.
            let colors: [Color] = [Color(red: 70/255, green: 130/255, blue: 180/255),
                                   Color(red: 1, green: 0, blue: 0),
                                   Color(red: 5/255, green: 179/255, blue: 120/255), .orange]
            var curveContext = context
            curveContext.clip(to: Path(rect))
            for (index, formula) in formulas.enumerated() {
                let expression = MathPlotExpression(formula)
                var line = Path()
                var previous: CGPoint?
                for pixel in stride(from: rect.minX, through: rect.maxX, by: 0.5) {
                    guard let point = geometry.sample(expression, at: pixel) else { previous = nil; continue }
                    // Break tangent asymptotes instead of connecting opposite branches.
                    if let previous, abs(point.y - previous.y) < rect.height {
                        line.addLine(to: point)
                    } else { line.move(to: point) }
                    previous = point
                }
                curveContext.stroke(line, with: .color(colors[index % colors.count]), lineWidth: 1)
            }
        }
        .clipped()
        .gesture(DragGesture().onChanged { dragOffset = CGSize(width: dragOrigin.width + $0.translation.width,
                                                              height: dragOrigin.height + $0.translation.height) }
            .onEnded { _ in dragOrigin = dragOffset })
        .simultaneousGesture(MagnificationGesture().onChanged { zoom = min(max(zoomOrigin * $0, 0.5), 4) }
            .onEnded { _ in zoomOrigin = zoom })
        .accessibilityLabel(formulas.joined(separator: "; "))
        .accessibilityValue("\(formulas.count)")
        .accessibilityIdentifier("math-plot-graph")
    }

    private func tickLabel(_ value: Double) -> String {
        let label = value.formatted(.number.precision(.fractionLength(0...4)))
        return label.replacingOccurrences(of: "-", with: "−")
    }
}

struct MermaidDiagramRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    @Environment(\.colorScheme) private var colorScheme
    @State private var renderStatus: MermaidRenderStatus = .loading
    @State private var showSource = false
    @State private var zoom = 1.2
    @State private var resetToken = 0

    private var content: MermaidDiagramContent {
        MermaidDiagramContent(data: data)
    }

    var body: some View {
        switch mode {
        case .preview:
            preview

        case .fullscreen:
            fullscreen
        }
    }

    private var preview: some View {
        ZStack(alignment: .topLeading) {
            if content.status == "processing" {
                MermaidPlaceholder()
            } else if content.code.isEmpty || !MermaidWebDocument.isAvailable || renderStatus == .failed {
                MermaidSourcePreview(source: content.code, kind: content.kind, lineLimit: 5)
                    .accessibilityIdentifier("mermaid-source-fallback")
            } else {
                MermaidCanvas(
                    source: content.code,
                    theme: colorScheme == .dark ? "dark" : "default",
                    isPreview: true,
                    zoom: 1,
                    resetToken: 0,
                    status: $renderStatus
                )
                .opacity(renderStatus == .ready ? 1 : 0)
                .accessibilityLabel(content.title)
                .accessibilityIdentifier("mermaid-rendered-preview")
                if renderStatus == .loading {
                    MermaidPlaceholder()
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .accessibilityIdentifier("mermaid-diagram-preview")
        .onChange(of: content.code) { _, _ in renderStatus = .loading }
    }

    private var fullscreen: some View {
        VStack(spacing: .spacing4) {
            ZStack {
                if content.code.isEmpty || !MermaidWebDocument.isAvailable || renderStatus == .failed {
                    ScrollView([.horizontal, .vertical]) {
                        MermaidSourcePreview(source: content.code, kind: content.kind, lineLimit: nil)
                            .textSelection(.enabled)
                    }
                    .accessibilityIdentifier("mermaid-source-panel")
                } else {
                    // Keep WebKit visible beneath the opaque source panel. Hiding or
                    // recreating its layer left a blank compositor frame on return.
                    MermaidCanvas(
                        source: content.code,
                        theme: colorScheme == .dark ? "dark" : "default",
                        isPreview: false,
                        zoom: zoom,
                        resetToken: resetToken,
                        status: $renderStatus
                    )
                    .allowsHitTesting(renderStatus == .ready && !showSource)
                    .accessibilityHidden(renderStatus != .ready || showSource)
                    .accessibilityIdentifier("mermaid-rendered-panel")
                    if showSource {
                        ScrollView([.horizontal, .vertical]) {
                            MermaidSourcePreview(source: content.code, kind: content.kind, lineLimit: nil)
                                .textSelection(.enabled)
                        }
                        .background(Color.grey20)
                        .accessibilityIdentifier("mermaid-source-panel")
                    } else if renderStatus == .loading {
                        MermaidPlaceholder()
                    }
                }
                if renderStatus == .ready && !showSource {
                    Color.clear.frame(width: 1, height: 1)
                        .accessibilityElement()
                        .accessibilityIdentifier("mermaid-render-ready")
                        .allowsHitTesting(false)
                }
            }
            .frame(maxWidth: .infinity)
            // Web uses min(72vh, 760px). The native embed lives inside a scrollable overlay.
            .frame(height: 480)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius4))

            VStack(spacing: .spacing3) {
                HStack(spacing: .spacing5) {
                    mermaidControl(icon: "minus", label: AppStrings.zoomOut, identifier: "mermaid-zoom-out", disabled: zoom <= 0.25) {
                        zoom = max(0.25, (zoom / 1.2 * 1000).rounded() / 1000)
                    }
                    Button {
                        zoom = 1.2
                        resetToken += 1
                    } label: {
                        Text("\(Int((zoom * 100).rounded()))%")
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing2)
                            .background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius7))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.resetZoom)
                    .accessibilityIdentifier("mermaid-fit")
                    mermaidControl(icon: "plus", label: AppStrings.zoomIn, identifier: "mermaid-zoom-in", disabled: zoom >= 4) {
                        zoom = min(4, (zoom * 1.2 * 1000).rounded() / 1000)
                    }
                }
                Button {
                    showSource.toggle()
                } label: {
                    Text(showSource ? AppStrings.preview : AppStrings.mindMapSource)
                        .font(.omXs.weight(.medium))
                        .foregroundStyle(Color.fontPrimary)
                        .padding(.horizontal, .spacing5)
                        .padding(.vertical, .spacing2)
                        .background(Color.grey0)
                        .clipShape(RoundedRectangle(cornerRadius: .radius7))
                        .overlay(RoundedRectangle(cornerRadius: .radius7).stroke(Color.grey20))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("mermaid-toggle-source")
            }
        }
        .onChange(of: content.code) { _, _ in
            renderStatus = .loading
            showSource = false
            zoom = 1.2
        }
    }

    private func mermaidControl(icon: String, label: String, identifier: String, disabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon(icon, size: 16)
                .foregroundStyle(disabled ? Color.fontTertiary : Color.fontPrimary)
                .frame(width: 34, height: 34)
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel(label)
        .accessibilityIdentifier(identifier)
    }
}

struct MermaidDiagramContent {
    let title: String
    let kind: String
    let code: String
    let status: String

    init(data: [String: AnyCodable]?) {
        let fields = data ?? [:]
        code = Self.string(fields, keys: ["diagram_code", "code", "source"]) ?? ""
        title = Self.string(fields, keys: ["title"]) ?? EmbedType.diagramsMermaid.displayName
        kind = Self.string(fields, keys: ["diagram_kind"]) ?? code.split(separator: "\n").first.map(String.init) ?? "mermaid"
        status = Self.string(fields, keys: ["status"]) ?? "finished"
    }

    private static func string(_ fields: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            if let value = fields[key]?.value as? String, !value.isEmpty { return value }
        }
        return nil
    }
}

private enum MermaidRenderStatus: Equatable {
    case loading, ready, failed
}

private struct MermaidPlaceholder: View {
    var body: some View {
        HStack(spacing: .spacing3) {
            ForEach(0..<3) { _ in
                Rectangle()
                    .fill(Color.grey40)
                    .frame(height: 2)
                    .frame(maxWidth: .infinity)
            }
        }
        .padding(.spacing5)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey20)
        .accessibilityLabel(AppStrings.loading)
    }
}

private struct MermaidSourcePreview: View {
    let source: String
    let kind: String
    let lineLimit: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(kind)
                .font(.omSmall.weight(.semibold))
            Text(source.isEmpty ? AppStrings.error : source)
                .font(Font.omXs.monospaced())
                .lineLimit(lineLimit)
        }
        .foregroundStyle(Color.fontPrimary)
        .padding(.spacing3)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.grey20)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }
}

/// The script is the same self-contained Mermaid distribution used by the web package.
/// Source is base64 encoded before insertion; the document never interpolates source as HTML/JS.
enum MermaidWebDocument {
    static let runtime: String? = {
        guard let url = Bundle.main.url(forResource: "mermaid.min", withExtension: "js", subdirectory: "MermaidRuntime") else {
            return nil
        }
        return try? String(contentsOf: url, encoding: .utf8)
    }()

    static var isAvailable: Bool { runtime != nil }

    static func make(source: String, theme: String, isPreview: Bool, zoom: Double) -> String? {
        guard let runtime else { return nil }
        let encoded = Data(source.utf8).base64EncodedString()
        let safeTheme = theme == "dark" ? "dark" : "default"
        let initialZoom = isPreview ? 0.72 : min(4, max(0.25, zoom))
        let previewClass = isPreview ? "preview" : "fullscreen"
        return """
        <!doctype html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
        <style>
        html,body,#viewport{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}
        #viewport{touch-action:none;position:relative}
        #diagram{width:max-content;min-width:100%;transform-origin:top left;will-change:transform}
        .preview #diagram svg{display:block;max-width:none;min-width:420px}
        .fullscreen #diagram{padding:16px;box-sizing:border-box}
        .fullscreen #diagram svg{display:block;max-width:none}
        </style></head><body class="\(previewClass)"><div id="viewport"><div id="diagram"></div></div>
        <script>\(runtime)</script>
        <script>
        (() => {
          'use strict';
          const viewport = document.getElementById('viewport');
          const diagram = document.getElementById('diagram');
          const source = new TextDecoder().decode(Uint8Array.from(atob('\(encoded)'), c => c.charCodeAt(0)));
          let zoom = \(initialZoom);
          let offsetX = 0, offsetY = 0, dragX = 0, dragY = 0, originX = 0, originY = 0;
          let dragging = false;
          const notify = value => window.webkit.messageHandlers.mermaid.postMessage(value);
          const apply = () => { diagram.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${zoom})`; };
          window.setDiagramZoom = value => { zoom = Math.min(4, Math.max(0.25, Number(value) || 1.2)); apply(); };
          window.resetDiagramView = () => { offsetX = 0; offsetY = 0; apply(); };
          if (document.body.classList.contains('fullscreen')) {
            viewport.addEventListener('pointerdown', event => {
              dragging = true; dragX = event.clientX; dragY = event.clientY;
              originX = offsetX; originY = offsetY;
              viewport.setPointerCapture(event.pointerId);
              event.preventDefault();
            });
            viewport.addEventListener('pointermove', event => {
              if (!dragging) return;
              offsetX = originX + event.clientX - dragX;
              offsetY = originY + event.clientY - dragY;
              apply(); event.preventDefault();
            });
            const endDrag = () => { dragging = false; };
            viewport.addEventListener('pointerup', endDrag);
            viewport.addEventListener('pointercancel', endDrag);
          }
          function sanitize(svg) {
            const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
            const root = doc.documentElement;
            if (root.localName !== 'svg' || doc.querySelector('parsererror')) throw new Error('invalid SVG');
            const forbidden = new Set(['script','foreignobject','iframe','object','embed','link','meta','animate','set']);
            const elements = [root, ...root.querySelectorAll('*')];
            for (const element of elements) {
              if (forbidden.has(element.localName.toLowerCase())) { element.remove(); continue; }
              if (element.localName.toLowerCase() === 'style') {
                element.textContent = element.textContent.replace(/@import[^;]*;?/gi, '').replace(/url\\s*\\([^)]*\\)/gi, 'none');
              }
              for (const attr of [...element.attributes]) {
                const name = attr.name.toLowerCase();
                const value = attr.value.trim();
                if (name.startsWith('on') || name === 'href' || name === 'xlink:href' || name === 'src' ||
                    /(?:javascript:|data:|https?:|url\\s*\\()/i.test(value)) element.removeAttribute(attr.name);
              }
            }
            return new XMLSerializer().serializeToString(root);
          }
          try {
            mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'\(safeTheme)',
              flowchart:{htmlLabels:false},sequence:{useMaxWidth:false}});
            mermaid.render('openmates-mermaid', source).then(result => {
              diagram.innerHTML = sanitize(result.svg);
              apply();
              requestAnimationFrame(() => requestAnimationFrame(() => notify('ready')));
            }).catch(() => notify('failed'));
          } catch (_) { notify('failed'); }
        })();
        </script></body></html>
        """
    }
}

private struct MermaidCanvas {
    let source: String
    let theme: String
    let isPreview: Bool
    let zoom: Double
    let resetToken: Int
    @Binding var status: MermaidRenderStatus

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var status: Binding<MermaidRenderStatus>
        var key = ""
        var lastZoom = 0.0
        var lastResetToken = 0
        var active = true

        init(status: Binding<MermaidRenderStatus>) { self.status = status }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard active, message.name == "mermaid", let value = message.body as? String else { return }
            DispatchQueue.main.async { [weak self] in
                guard let self, self.active else { return }
                self.status.wrappedValue = value == "ready" ? .ready : .failed
            }
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            // The diagram document has no external dependencies or navigation.
            decisionHandler(navigationAction.request.url?.scheme == "about" ? .allow : .cancel)
        }

        func update(_ webView: WKWebView, source: String, theme: String, isPreview: Bool,
                    zoom: Double, resetToken: Int, status: Binding<MermaidRenderStatus>) {
            self.status = status
            let nextKey = "\(source)\u{0}\(theme)\u{0}\(isPreview)"
            if nextKey != key {
                key = nextKey
                lastZoom = zoom
                lastResetToken = resetToken
                if let html = MermaidWebDocument.make(source: source, theme: theme, isPreview: isPreview, zoom: zoom) {
                    webView.loadHTMLString(html, baseURL: nil)
                } else {
                    DispatchQueue.main.async { status.wrappedValue = .failed }
                }
                return
            }
            if zoom != lastZoom {
                lastZoom = zoom
                webView.evaluateJavaScript("window.setDiagramZoom(\(zoom))", completionHandler: nil)
            }
            if resetToken != lastResetToken {
                lastResetToken = resetToken
                webView.evaluateJavaScript("window.resetDiagramView()", completionHandler: nil)
            }
        }
    }

    private func makeWebView(coordinator: Coordinator) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(coordinator, name: "mermaid")
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = coordinator
        #if os(iOS)
        webView.accessibilityIdentifier = isPreview ? "mermaid-rendered-preview" : "mermaid-rendered-panel"
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        #else
        webView.setAccessibilityIdentifier(isPreview ? "mermaid-rendered-preview" : "mermaid-rendered-panel")
        webView.setValue(false, forKey: "drawsBackground")
        #endif
        return webView
    }
}

#if os(iOS)
extension MermaidCanvas: UIViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator(status: $status) }
    func makeUIView(context: Context) -> WKWebView { makeWebView(coordinator: context.coordinator) }
    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.update(webView, source: source, theme: theme, isPreview: isPreview,
                                   zoom: zoom, resetToken: resetToken, status: $status)
    }
    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        coordinator.active = false
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "mermaid")
        webView.stopLoading()
    }
}
#elseif os(macOS)
extension MermaidCanvas: NSViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator(status: $status) }
    func makeNSView(context: Context) -> WKWebView { makeWebView(coordinator: context.coordinator) }
    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.update(webView, source: source, theme: theme, isPreview: isPreview,
                                   zoom: zoom, resetToken: resetToken, status: $status)
    }
    static func dismantleNSView(_ webView: WKWebView, coordinator: Coordinator) {
        coordinator.active = false
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "mermaid")
        webView.stopLoading()
    }
}
#endif

// SVG rendering via WKWebView for plot data
#if os(iOS)
import WebKit

struct SVGImageView: UIViewRepresentable {
    let svgData: Data

    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let html = """
        <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{margin:0;display:flex;justify-content:center;align-items:center;background:transparent}
        svg{max-width:100%;height:auto}</style></head>
        <body>\(String(data: svgData, encoding: .utf8) ?? "")</body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }
}
#elseif os(macOS)
import WebKit

struct SVGImageView: NSViewRepresentable {
    let svgData: Data

    func makeNSView(context: Context) -> WKWebView {
        let webView = WKWebView()
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        let html = """
        <html><head><style>body{margin:0;display:flex;justify-content:center;align-items:center}
        svg{max-width:100%;height:auto}</style></head>
        <body>\(String(data: svgData, encoding: .utf8) ?? "")</body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }
}
#endif

struct MathCalculateRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var expression: String? { data?["expression"]?.value as? String }
    private var result: String? { data?["result"]?.value as? String }
    private var steps: String? { data?["steps"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let expression {
                Text(expression)
                    .font(.system(mode == .preview ? .body : .title3, design: .monospaced))
                    .foregroundStyle(Color.fontSecondary)
            }
            if let result {
                HStack(spacing: .spacing2) {
                    Text("=").foregroundStyle(Color.fontTertiary)
                    Text(result).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                }
                .font(mode == .preview ? .omP : .omH3)
            }
            if mode == .fullscreen, let steps {
                Divider()
                Text(steps)
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(Color.fontSecondary)
                    .textSelection(.enabled)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct ReminderRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var datetime: String? { data?["datetime"]?.value as? String }
    private var recurring: String? { data?["recurring"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Icon("reminder", size: mode == .preview ? 24 : 32)
                .foregroundStyle(Color.buttonPrimary)
            if let title {
                Text(title).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
            }
            if let datetime {
                Label { Text(datetime).font(.omXs) } icon: { Icon("time", size: 12) }
                    .foregroundStyle(Color.fontSecondary)
            }
            if let recurring {
                Label(recurring, systemImage: "repeat").font(.omXs)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct FocusModeRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var focusID: String { data?["focus_id"]?.value as? String ?? "" }
    private var appID: String {
        data?["app_id"]?.value as? String ?? String(focusID.split(separator: "-").first ?? "ai")
    }
    private var focusName: String {
        data?["focus_mode_name"]?.value as? String ?? focusID
    }

    var body: some View {
        Group {
            if mode == .preview {
                HStack(spacing: .spacing5) {
                    Circle()
                        .fill(AppIconView.gradient(forAppId: appID))
                        .frame(width: 61, height: 61)
                        .overlay {
                            Icon(AppIconView.iconName(forAppId: appID), size: 26)
                                .foregroundStyle(.white)
                        }
                    Icon("insight", size: 29)
                        .foregroundStyle(Color(hex: 0x5951D0))
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(focusName)
                            .font(.omP.weight(.semibold))
                            .foregroundStyle(Color.grey100)
                            .lineLimit(1)
                        Text(AppStrings.focusModeActivated)
                            .font(.omP.weight(.medium))
                            .foregroundStyle(Color(hex: 0x34A853))
                            .lineLimit(1)
                    }
                    .padding(.trailing, .spacing8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxWidth: 380, maxHeight: 61)
                .background(Color.grey30)
                .clipShape(RoundedRectangle(cornerRadius: 30))
                .accessibilityIdentifier("focus-mode-bar")
            } else {
                VStack(spacing: .spacing5) {
                    Circle()
                        .fill(AppIconView.gradient(forAppId: "ai"))
                        .frame(width: 72, height: 72)
                        .overlay {
                            Text("✓")
                                .font(.omH2)
                                .foregroundStyle(Color.fontButton)
                        }
                    Text(AppStrings.focusModeActiveBanner)
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                    Text(focusName)
                        .font(.omH2)
                        .foregroundStyle(Color.fontPrimary)
                    if !focusID.isEmpty {
                        Text("\(AppStrings.focusModeFocusOn) \(focusID)")
                            .font(.omP)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
                .frame(maxWidth: 700, minHeight: 320)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                .overlay {
                    RoundedRectangle(cornerRadius: .radius8)
                        .stroke(Color.grey20, lineWidth: 1)
                }
                .accessibilityIdentifier("focus-mode-activation-fullscreen")
            }
        }
    }
}

struct ProductSummaryEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let type: EmbedType?
    let appId: String

    private var title: String {
        firstString(["title", "name", "display_name", "query", "filename"])
            ?? type?.displayName
            ?? appId
    }

    private var subtitle: String? {
        firstString(["description", "summary", "status", "provider", "framework", "runtime"])
    }

    private var secondaryDetail: String? {
        firstString(["url", "source_url", "license_title", "assignee", "trigger", "model_format"])
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(alignment: .center, spacing: .spacing4) {
                AppIconView(appId: appId, size: mode == .preview ? 36 : 48)

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(title)
                        .font(mode == .preview ? .omSmall : .omH4)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(mode == .preview ? 2 : 3)

                    if let subtitle {
                        Text(subtitle)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(mode == .preview ? 1 : 3)
                    }
                }
            }

            if mode == .fullscreen, let secondaryDetail {
                Text(secondaryDetail)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(4)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
        .accessibilityIdentifier("product-summary-embed")
    }

    private func firstString(_ keys: [String]) -> String? {
        guard let data else { return nil }
        for key in keys {
            if let value = data[key]?.value as? String, !value.isEmpty {
                return value
            }
        }
        return nil
    }
}

struct DesignIconResultEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @Environment(\.recipientMediaContext) private var recipient
    @Environment(\.nativeDesignIconExportState) private var sharedExport
    @ObservedObject private var account = OfflineStore.shared
    @StateObject private var actions = NativeEmbedActionController()
    @State private var rawSVG: Data?
    @State private var color = "#111827"
    @State private var pngSize = "256"

    private var preparedSVG: StaticSVGImageSource? {
        guard let rawSVG else { return nil }
        return try? NativeDesignIconActions.prepare(rawSVG, color: color, palette: data?["palette"]?.value as? Bool == true)
    }

    private var title: String {
        for key in ["display_name", "name", "icon_id"] {
            if let value = data?[key]?.value as? String, !value.isEmpty { return value }
        }
        return "Icon"
    }

    private var collection: String {
        for key in ["collection_name", "prefix", "license_title"] {
            if let value = data?[key]?.value as? String, !value.isEmpty { return value }
        }
        return "SVG icon"
    }

    private var sourceURL: URL? {
        NativeDesignIconActions.url(data?["svg_path"]?.value as? String,
            apiBase: recipient?.apiBaseURL ?? ServerProfile.current().apiBaseURL)
    }

    var body: some View {
        switch mode {
        case .preview:
            HStack(spacing: .spacing3) {
                iconArt(size: 58, markSize: 26)
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(title).font(.omSmall).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                    Text(collection).font(.omXxs).foregroundStyle(Color.grey70)
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityIdentifier("design-icon-result-preview")

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing12) {
                iconArt(size: 360, markSize: 56)
                    .frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: .spacing4) {
                    Text(title).font(.omLg).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                    if collection != "SVG icon" {
                        Text(collection).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                    HStack(spacing: .spacing4) {
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text("Color").font(.omSmall).foregroundStyle(Color.fontSecondary)
                            TextField("#111827", text: $color)
                                .textFieldStyle(OMTextFieldStyle())
                                .frame(width: 140)
                                .disabled(data?["palette"]?.value as? Bool == true)
                                .accessibilityIdentifier("design-icon-color-input")
                        }
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text("PNG size").font(.omSmall).foregroundStyle(Color.fontSecondary)
                            TextField("256", text: $pngSize)
                                .textFieldStyle(OMTextFieldStyle())
                                .frame(width: 120)
                                .accessibilityIdentifier("design-icon-png-size-input")
                        }
                    }
                    HStack(spacing: .spacing4) {
                        exportButton("\(AppStrings.copy) SVG", id: "design-icon-copy-svg") { copySVG() }
                        exportButton("\(AppStrings.download) SVG", id: "design-icon-download-svg") { exportSVG() }
                    }
                    exportButton("\(AppStrings.download) PNG", id: "design-icon-download-png") { exportPNG() }
                }
            }
            .padding(.spacing6)
            .accessibilityIdentifier("design-icon-result-fullscreen")
            .task(id: sourceURL) {
                rawSVG = nil
                guard let sourceURL else { return }
                let generation = account.scopeGeneration
                let bytes = try? await NativeDesignIconActions.load(sourceURL, recipient: recipient)
                guard !Task.isCancelled, account.scopeGeneration == generation else { return }
                do { try recipient?.checkCurrent(); rawSVG = bytes } catch { }
            }
            .onChange(of: preparedSVG?.data, initial: true) { _, bytes in sharedExport?.svg = bytes }
            .onChange(of: pngSize, initial: true) { _, value in sharedExport?.size = Int(value) ?? 0 }
            .onDisappear { actions.cancel(); rawSVG = nil; sharedExport?.clear() }
            .onChange(of: account.scopeGeneration) { _, _ in actions.cancel(); rawSVG = nil }
        }
    }

    private func iconArt(size: CGFloat, markSize: CGFloat) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: mode == .preview ? .radius4 : 24)
                .fill(Color.grey10)
            if let preparedSVG {
                StaticSVGRemoteImageView(source: preparedSVG, contentMode: .fit, onSuccess: {}, onFailure: {})
                    .allowsHitTesting(false)
                    .frame(width: markSize, height: markSize)
            } else if let sourceURL {
                CachedRemoteImage(url: sourceURL) { image in image.resizable().scaledToFit() }
                    placeholder: { Rectangle().fill(Color.grey50).frame(width: markSize, height: markSize) }
                    .frame(width: markSize, height: markSize)
            } else {
                Rectangle().fill(Color.grey50).frame(width: markSize, height: markSize)
            }
        }
        .frame(width: mode == .preview ? size : nil, height: size)
        .overlay(RoundedRectangle(cornerRadius: mode == .preview ? .radius4 : 24).stroke(Color.grey20))
    }

    private func exportButton(_ title: String, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Text(title) }
            .buttonStyle(OMSecondaryButtonStyle())
            .disabled(preparedSVG == nil || actions.isDownloading)
            .accessibilityIdentifier(id)
    }
    private func copySVG() {
        guard let source = preparedSVG, let text = String(data: source.data, encoding: .utf8) else { return }
        do { try recipient?.checkCurrent() } catch { return }
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
        #endif
        ToastManager.shared.show(AppStrings.localized("embeds.copied_to_clipboard"), type: .success)
    }
    private func exportSVG() {
        guard let source = preparedSVG else { return }
        actions.export(.init(filename: NativeDesignIconActions.filename(data: data, extension: "svg"), bytes: source.data, mimeType: "image/svg+xml"),
            validate: { try recipient?.checkCurrent() })
    }
    private func exportPNG() {
        guard let source = preparedSVG, let size = Int(pngSize) else { return }
        actions.download(load: {
            .init(filename: NativeDesignIconActions.filename(data: data, extension: "png"), bytes: try await NativeDesignIconActions.png(source, size: size), mimeType: "image/png")
        }, validate: { try recipient?.checkCurrent() })
    }
}

struct GenericEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let type: String

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Icon("text", size: mode == .preview ? 24 : 32)
                .foregroundStyle(Color.fontTertiary)
            Text(type)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            if mode == .fullscreen, let data {
                ForEach(Array(data.keys.sorted()), id: \.self) { key in
                    HStack(alignment: .top) {
                        Text(key).font(.omXs).foregroundStyle(Color.fontTertiary).frame(width: 100, alignment: .leading)
                        Text("\(data[key]?.value ?? "" as Any)").font(.omXs).foregroundStyle(Color.fontPrimary)
                    }
                }
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}
