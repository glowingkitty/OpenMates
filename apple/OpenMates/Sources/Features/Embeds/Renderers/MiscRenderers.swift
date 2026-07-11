// Miscellaneous embed renderers for social posts, weather, mail, math, and utilities.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/social_media/SocialMediaPostEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/weather/WeatherDayEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

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

            HStack(spacing: .spacing10) {
                SocialMediaMetric(icon: "heart", value: post.likeCount.formatted())
                SocialMediaMetric(icon: "chat", value: post.replyCount.formatted())
                if post.repostCount > 0 {
                    SocialMediaMetric(icon: "share", value: post.repostCount.formatted())
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
            .padding(.top, .spacing3)
            .overlay(alignment: .top) {
                Rectangle().fill(Color.grey20).frame(height: 1)
            }
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
                            Text(body)
                                .font(.omP)
                                .foregroundStyle(Color.fontPrimary)
                                .lineSpacing(.spacing2)
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
                                Text(comment.body)
                                    .font(.omSmall)
                                    .foregroundStyle(Color.fontPrimary)
                                    .lineSpacing(.spacing2)
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
        VStack(alignment: .leading, spacing: .spacing5) {
            VStack(alignment: .leading, spacing: .spacing1) {
                Text(weather.date ?? AppStrings.weatherDay)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.grey100)
                    .lineLimit(1)
                Text(weather.displayCondition ?? AppStrings.weatherDay)
                    .font(.omXs)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
            }

            HStack(spacing: .spacing5) {
                WeatherConditionIcon(value: weather.iconAndCondition, size: 58)
                Spacer(minLength: 0)
                Text(weather.temperatureRange)
                    .font(.omXxl.weight(.semibold))
                    .foregroundStyle(Color.grey100)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }

            HStack(spacing: .spacing3) {
                WeatherPill(text: "\(weather.rainChance.formatted())%")
                WeatherPill(text: "\(weather.precipitation.formatted()) mm")
                WeatherPill(text: "\(weather.rainHours.formatted()) h")
            }
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, minHeight: 145, maxHeight: .infinity, alignment: .topLeading)
        .background(LinearGradient.appWeather.opacity(0.14))
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1) }
    }
}

private struct WeatherDayFullscreen: View {
    let weather: WeatherDayValue
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing8) {
                summaryCard

                LazyVGrid(columns: [GridItem(.adaptive(minimum: horizontalSizeClass == .compact ? 135 : 180), spacing: .spacing6)], spacing: .spacing6) {
                    WeatherMetricCard(icon: "weather", value: "\(weather.rainChance.formatted())%", detail: "\(weather.precipitation.formatted()) mm · \(weather.rainHours.formatted()) h")
                    WeatherMetricCard(icon: "weather", value: weather.windText)
                    WeatherMetricCard(icon: "cloud", value: weather.cloudText)
                    WeatherMetricCard(icon: "weather", value: weather.humidityText)
                }

                VStack(alignment: .leading, spacing: .spacing6) {
                    HStack {
                        Text(AppStrings.weatherForecast).font(.omLg.weight(.bold)).foregroundStyle(Color.grey100)
                        Spacer()
                        Text(weather.hourly.count.formatted()).font(.omXs).foregroundStyle(Color.grey60)
                    }
                    if weather.hourly.isEmpty {
                        Text(AppStrings.weatherDay).font(.omXs).foregroundStyle(Color.grey60)
                    } else {
                        ScrollView(.horizontal, showsIndicators: false) {
                            LazyHStack(spacing: .spacing5) {
                                ForEach(weather.hourly) { hour in
                                    VStack(spacing: .spacing3) {
                                        Text(hour.time ?? "—").font(.omXxs.weight(.semibold)).foregroundStyle(Color.grey100)
                                        WeatherConditionIcon(value: "\(hour.icon ?? weather.icon) \(hour.condition ?? weather.condition)", size: 34)
                                        Text(hour.temperature.map { "\($0.formatted())°" } ?? "—")
                                            .font(.omLg.weight(.bold)).foregroundStyle(Color.grey100)
                                        Text("\((hour.rainChance ?? 0).formatted())%")
                                        Text("\((hour.precipitation ?? 0).formatted()) mm")
                                        Text(hour.wind.map { "\($0.formatted()) km/h" } ?? "—")
                                    }
                                    .font(.omXxs)
                                    .foregroundStyle(Color.grey70)
                                    .padding(.horizontal, .spacing5)
                                    .padding(.vertical, .spacing6)
                                    .frame(minWidth: 96)
                                    .background(Color.grey10)
                                    .clipShape(RoundedRectangle(cornerRadius: .radius7))
                                    .overlay { RoundedRectangle(cornerRadius: .radius7).stroke(Color.grey20, lineWidth: 1) }
                                }
                            }
                        }
                    }
                }
                .padding(.spacing8)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1) }
                .shadow(color: .black.opacity(0.07), radius: 16, x: 0, y: 6)
            }
            .padding(.horizontal, horizontalSizeClass == .compact ? .spacing4 : .spacing8)
            .padding(.vertical, .spacing10)
            .frame(maxWidth: 980)
            .frame(maxWidth: .infinity)
        }
    }

    private var summaryCard: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: .spacing12) {
                weatherSummary
                Spacer(minLength: .spacing8)
                WeatherConditionIcon(value: weather.iconAndCondition, size: 142)
            }
            VStack(alignment: .leading, spacing: .spacing3) {
                weatherSummary
                WeatherConditionIcon(value: weather.iconAndCondition, size: 108)
            }
        }
        .padding(horizontalSizeClass == .compact ? .spacing8 : .spacing12)
        .frame(maxWidth: .infinity, minHeight: horizontalSizeClass == .compact ? nil : 245, alignment: .leading)
        .background(LinearGradient.appWeather.opacity(0.28))
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay {
            RoundedRectangle(cornerRadius: .radius8)
                .stroke(Color.grey20, lineWidth: 1)
        }
        .shadow(color: .black.opacity(0.13), radius: 24, x: 0, y: 10)
    }

    private var weatherSummary: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(weather.date ?? AppStrings.weatherDay).font(.omSmall).foregroundStyle(Color.grey70)
            Text(weather.displayCondition ?? AppStrings.weatherDay)
                .font(horizontalSizeClass == .compact ? .omXxxl.weight(.bold) : .omHero.weight(.bold))
                .foregroundStyle(Color.grey100)
                .lineLimit(2)
                .minimumScaleFactor(0.75)
            if !weather.locationProvider.isEmpty {
                Text(weather.locationProvider).font(.omSmall).foregroundStyle(Color.grey70)
            }
            Text(weather.temperatureRange)
                .font(horizontalSizeClass == .compact ? .omXxxl.weight(.bold) : .omHero.weight(.bold))
                .foregroundStyle(Color.grey100)
        }
    }
}

private struct WeatherPill: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.omXxs)
            .foregroundStyle(Color.grey70)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing2)
            .background(Color.grey0.opacity(0.82))
            .clipShape(Capsule())
            .overlay { Capsule().stroke(Color.grey20, lineWidth: 1) }
    }
}

private struct WeatherMetricCard: View {
    let icon: String
    let value: String
    var detail: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Icon(icon, size: .iconSizeSm).foregroundStyle(LinearGradient.appWeather)
            Text(value).font(.omXl.weight(.bold)).foregroundStyle(Color.grey100)
            if let detail { Text(detail).font(.omXs).foregroundStyle(Color.grey70) }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1) }
        .shadow(color: .black.opacity(0.07), radius: 16, x: 0, y: 6)
    }
}

private struct WeatherConditionIcon: View {
    let value: String
    let size: CGFloat

    private var iconName: String {
        let normalized = value.lowercased()
        return normalized.contains("cloud") || normalized.contains("overcast") || normalized.contains("fog") ? "cloud" : "weather"
    }

    var body: some View {
        Icon(iconName, size: size)
            .foregroundStyle(LinearGradient.appWeather)
            .frame(width: size, height: size)
            .shadow(color: .black.opacity(0.16), radius: 9, x: 0, y: 4)
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
        provider = MiscEmbedValue.string(data, "provider") ?? ""
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
    var iconAndCondition: String { "\(icon) \(condition)" }
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

struct MailRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var subject: String? { data?["subject"]?.value as? String }
    private var to: String? { data?["to"]?.value as? String }
    private var body_: String? { data?["body"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let subject {
                Text(subject).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary).lineLimit(mode == .preview ? 1 : nil)
            }
            if let to {
                Label(to, systemImage: "person").font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            if let body_ {
                Text(body_).font(mode == .preview ? .omXs : .omP)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(mode == .preview ? 3 : nil)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct MathPlotRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var svgData: String? { data?["svg_data"]?.value as? String }

    @State private var svgImage: Data?

    var body: some View {
        switch mode {
        case .preview:
            VStack(spacing: .spacing3) {
                if let svgData, let data = svgData.data(using: .utf8) {
                    SVGImageView(svgData: data)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    Icon("diagram", size: 32)
                        .foregroundStyle(Color.fontTertiary)
                }
                if let title {
                    Text(title).font(.omSmall)
                        .foregroundStyle(Color.fontPrimary).lineLimit(1)
                }
            }
            .padding(.spacing3)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let title {
                    Text(title).font(.omH4).fontWeight(.medium).foregroundStyle(Color.fontPrimary)
                }
                if let svgData, let data = svgData.data(using: .utf8) {
                    SVGImageView(svgData: data)
                        .frame(minHeight: 300)
                        .clipShape(RoundedRectangle(cornerRadius: .radius3))
                } else {
                    Icon("diagram", size: 48)
                        .foregroundStyle(Color.fontTertiary)
                        .frame(maxWidth: .infinity)
                }
            }
        }
    }
}

struct MermaidDiagramRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { (data?["title"]?.value as? String) ?? "Mermaid Diagram" }
    private var diagramKind: String { (data?["diagram_kind"]?.value as? String) ?? "mermaid" }
    private var diagramCode: String { (data?["diagram_code"]?.value as? String) ?? "" }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                HStack(spacing: .spacing2) {
                    Icon("diagram", size: 22)
                        .foregroundStyle(Color.buttonPrimary)
                    Text(title)
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(1)
                }
                Text(diagramKind)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                MermaidSourcePreview(source: diagramCode, lineLimit: 5)
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            ScrollView {
                VStack(alignment: .leading, spacing: .spacing5) {
                    HStack(spacing: .spacing3) {
                        Icon("diagram", size: 32)
                            .foregroundStyle(Color.buttonPrimary)
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(title)
                                .font(.omH4)
                                .fontWeight(.medium)
                                .foregroundStyle(Color.fontPrimary)
                            Text(diagramKind)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontSecondary)
                        }
                    }
                    MermaidSourcePreview(source: diagramCode, lineLimit: nil)
                        .textSelection(.enabled)
                }
                .padding(.spacing5)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        }
    }
}

private struct MermaidSourcePreview: View {
    let source: String
    let lineLimit: Int?

    var body: some View {
        Text(displaySource)
            .font(.omMicro)
            .foregroundStyle(Color.fontSecondary)
            .padding(.spacing3)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .lineLimit(lineLimit)
    }

    private var displaySource: String {
        source.isEmpty ? "No Mermaid source available." : source
    }
}

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

    var body: some View {
        VStack(spacing: .spacing3) {
            Icon("select", size: mode == .preview ? 28 : 36)
                .foregroundStyle(Color.buttonPrimary)
            Text(LocalizationManager.shared.text("embed.focus_mode_active"))
                .font(mode == .preview ? .omSmall : .omP)
                .foregroundStyle(Color.fontPrimary)
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil)
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
