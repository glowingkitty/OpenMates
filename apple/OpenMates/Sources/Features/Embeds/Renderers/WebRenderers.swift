// Web embed renderers — website preview and full article reading.
// Mirrors WebsiteEmbedPreview.svelte: BasicInfosBar owns title/favicon;
// preview details render description on the left and thumbnail on the right.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/web/WebsiteEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct WebsiteRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    @Environment(\.openURL) private var openURL

    private var title: String { firstString(keys: ["title", "site_name"]) ?? hostFrom(url) }
    private var url: String { data?["url"]?.value as? String ?? "" }
    private var description: String? { stripHTML(firstString(keys: ["description", "meta_description", "summary"])) }
    private var imageURL: String? { firstString(keys: ["thumbnail_original", "image", "image_url", "thumbnail_url", "meta_image", "og_image"]) }
    private var snippets: [String] { snippetValues.compactMap(stripHTML) }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing2) {
                if let description {
                    GeometryReader { proxy in
                        HStack(alignment: .top, spacing: 0) {
                            Text(description)
                                .font(mode == .preview ? .omSmall : .omP)
                                .foregroundStyle(Color.grey70)
                                .lineLimit(6)
                                .multilineTextAlignment(.leading)
                                .frame(width: imageURL == nil ? proxy.size.width : proxy.size.width * 0.4, alignment: .topLeading)
                                .padding(.top, .spacing5)

                            if let imageURL, let url = URL(string: imageURL) {
                                AsyncImage(url: url) { phase in
                                    switch phase {
                                    case .success(let image):
                                        image
                                            .resizable()
                                            .aspectRatio(contentMode: .fill)
                                    default:
                                        Color.grey20
                                    }
                                }
                                .frame(width: proxy.size.width * 0.6)
                                .frame(height: 171)
                                .clipped()
                                .offset(x: 20)
                            }
                        }
                    }
                } else if let imageURL, let url = URL(string: imageURL) {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image
                                .resizable()
                                .aspectRatio(contentMode: .fill)
                        default:
                            Color.grey20
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .clipped()
                } else {
                    Text(hostFrom(url))
                        .font(.omSmall)
                        .foregroundStyle(Color.grey70)
                        .lineLimit(2)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)

        case .fullscreen:
            VStack(alignment: .center, spacing: 0) {
                if let fullscreenImageURL {
                    WebsiteRemoteImage(
                        primaryURLString: fullscreenImageURL,
                        fallbackURLString: imageURL
                    )
                    .frame(maxWidth: 511)
                    .frame(minHeight: 168, maxHeight: 250)
                    .clipShape(RoundedRectangle(cornerRadius: 30))
                    .padding(.bottom, .spacing12)
                }

                if let description {
                    Text(description)
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                        .lineSpacing(4)
                        .frame(maxWidth: 500, alignment: .leading)
                        .padding(.bottom, 32)
                }

                if !snippets.isEmpty {
                    VStack(alignment: .leading, spacing: .spacing8) {
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(AppStrings.snippets)
                                .font(.omXl)
                                .fontWeight(.bold)
                                .foregroundStyle(Color.grey100)

                            Text(AppStrings.viaBraveSearch)
                                .font(.omP)
                                .fontWeight(.bold)
                                .foregroundStyle(Color.grey60)
                        }

                        VStack(spacing: .spacing6) {
                            ForEach(Array(snippets.enumerated()), id: \.offset) { _, snippet in
                                WebsiteSnippetCard(text: snippet)
                            }
                        }
                    }
                    .frame(maxWidth: 500, alignment: .leading)
                }
            }
            .frame(maxWidth: 600, alignment: .center)
            .padding(.horizontal, .spacing20)
            .padding(.top, .spacing12)
            .padding(.bottom, .spacing20)
        }
    }

    var fullscreenHeaderTitle: String {
        title
    }

    var fullscreenHeaderSubtitle: String? {
        guard let formatted = formattedDataDate else { return nil }
        return AppStrings.dataFrom(formatted)
    }

    var fullscreenHeaderFaviconURL: String? {
        proxiedFaviconURL
    }

    var fullscreenHeaderButtonTitle: String {
        AppStrings.openOnProvider(hostFrom(url))
    }

    func openWebsite() {
        guard let url = URL(string: url) else { return }
        openURL(url)
    }

    private var fullscreenImageURL: String? {
        proxyImage(imageURL, maxWidth: 1024)
    }

    private var proxiedFaviconURL: String? {
        if let favicon = firstString(keys: ["meta_url_favicon", "favicon_url", "favicon"]) {
            return proxyImage(favicon, maxWidth: 38)
        }
        return proxyFavicon(url)
    }

    private var snippetValues: [String] {
        if let values = data?["extra_snippets"]?.value as? [String] {
            return values
        }
        if let value = data?["extra_snippets"]?.value as? String {
            return value.split(separator: "|").map(String.init)
        }
        if let value = data?["snippet"]?.value as? String {
            return [value]
        }
        return []
    }

    private var formattedDataDate: String? {
        guard let raw = firstString(keys: ["page_age", "data_date", "date", "published_date"]) else { return nil }
        if let date = parseRelativeDate(raw) {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy/MM/dd"
            return formatter.string(from: date)
        }
        return raw.replacingOccurrences(of: "-", with: "/")
    }

    private func hostFrom(_ urlString: String) -> String {
        guard let host = URL(string: urlString)?.host else { return urlString }
        let parts = host.replacingOccurrences(of: "www.", with: "").split(separator: ".")
        guard parts.count > 2 else { return parts.joined(separator: ".") }
        let lastTwo = parts.suffix(2).joined(separator: ".")
        let twoPartTLDs = ["co.uk", "com.au", "co.nz", "org.uk", "com.br", "co.jp", "co.kr", "co.in", "com.mx", "com.cn"]
        if twoPartTLDs.contains(lastTwo), parts.count >= 3 {
            return parts.suffix(3).joined(separator: ".")
        }
        return lastTwo
    }

    private func firstString(keys: [String]) -> String? {
        for key in keys {
            if let value = data?[key]?.value as? String, !value.isEmpty {
                return value
            }
            if key == "meta_url_favicon",
               let metaURL = data?["meta_url"]?.value as? [String: Any],
               let favicon = metaURL["favicon"] as? String,
               !favicon.isEmpty {
                return favicon
            }
        }
        return nil
    }

    private func stripHTML(_ text: String?) -> String? {
        guard let text, !text.isEmpty else { return nil }
        let withoutTags = text.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        let decoded = withoutTags
            .replacingOccurrences(of: "\\\"", with: "\"")
            .replacingOccurrences(of: "\\'", with: "'")
            .replacingOccurrences(of: "&nbsp;", with: " ")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&#39;", with: "'")
            .replacingOccurrences(of: "&apos;", with: "'")
        let cleaned = decoded.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? nil : cleaned
    }

    private func proxyImage(_ rawURL: String?, maxWidth: Int) -> String? {
        guard let rawURL, !rawURL.isEmpty else { return nil }
        if rawURL.hasPrefix("https://preview.openmates.org/api/v1/image") || rawURL.hasPrefix("data:") || rawURL.hasPrefix("/") {
            return rawURL
        }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/image")
        components?.queryItems = [
            URLQueryItem(name: "url", value: rawURL),
            URLQueryItem(name: "max_width", value: "\(maxWidth)")
        ]
        return components?.url?.absoluteString ?? rawURL
    }

    private func proxyFavicon(_ pageURL: String) -> String? {
        guard !pageURL.isEmpty else { return nil }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/favicon")
        components?.queryItems = [URLQueryItem(name: "url", value: pageURL)]
        return components?.url?.absoluteString
    }

    private func parseRelativeDate(_ value: String) -> Date? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if let date = ISO8601DateFormatter().date(from: value) {
            return date
        }
        if trimmed == "today" || trimmed == "just now" {
            return Date()
        }
        if trimmed == "yesterday" {
            return Calendar.current.date(byAdding: .day, value: -1, to: Date())
        }
        let pattern = #"^(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago$"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: trimmed, range: NSRange(trimmed.startIndex..., in: trimmed)),
              let amountRange = Range(match.range(at: 1), in: trimmed),
              let unitRange = Range(match.range(at: 2), in: trimmed),
              let amount = Int(trimmed[amountRange]) else {
            return nil
        }
        let unit = String(trimmed[unitRange])
        switch unit {
        case "second": return Calendar.current.date(byAdding: .second, value: -amount, to: Date())
        case "minute": return Calendar.current.date(byAdding: .minute, value: -amount, to: Date())
        case "hour": return Calendar.current.date(byAdding: .hour, value: -amount, to: Date())
        case "day": return Calendar.current.date(byAdding: .day, value: -amount, to: Date())
        case "week": return Calendar.current.date(byAdding: .day, value: -(amount * 7), to: Date())
        case "month": return Calendar.current.date(byAdding: .month, value: -amount, to: Date())
        case "year": return Calendar.current.date(byAdding: .year, value: -amount, to: Date())
        default: return nil
        }
    }
}

private struct WebsiteRemoteImage: View {
    let primaryURLString: String
    let fallbackURLString: String?
    @State private var shouldUseFallback = false

    private var activeURL: URL? {
        let activeString = shouldUseFallback ? fallbackURLString : primaryURLString
        guard let activeString else { return nil }
        return URL(string: activeString)
    }

    var body: some View {
        if let activeURL {
            AsyncImage(url: activeURL) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                case .failure:
                    fallbackView
                        .task {
                            if fallbackURLString != nil, fallbackURLString != primaryURLString {
                                shouldUseFallback = true
                            }
                        }
                default:
                    fallbackView
                }
            }
        } else {
            fallbackView
        }
    }

    private var fallbackView: some View {
        Color.grey30
            .overlay(ProgressView())
    }
}

private struct WebsiteSnippetCard: View {
    let text: String

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: DS.SnippetCard.radius)
                .fill(DS.SnippetCard.backgroundColor)

            Icon("quote", size: 20)
                .foregroundStyle(Color.grey100)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                .padding(12)

            Icon("quote", size: 20)
                .foregroundStyle(Color.grey100)
                .rotationEffect(.degrees(180))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .padding(12)

            Text(text)
                .font(.omP)
                .fontWeight(.medium)
                .foregroundStyle(Color.grey100)
                .lineSpacing(4)
                .padding(.vertical, DS.SnippetCard.paddingY)
                .padding(.horizontal, DS.SnippetCard.paddingX)
        }
        .frame(minHeight: DS.SnippetCard.minHeight)
    }
}

struct WebReadRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Article" }
    private var url: String { data?["url"]?.value as? String ?? "" }
    private var content: String? { data?["content"]?.value as? String }
    private var wordCount: Int? { data?["word_count"]?.value as? Int }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(title)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)

                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                }

                if let content {
                    Text(content)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(4)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                Link(destination: URL(string: url) ?? URL(string: "https://openmates.org")!) {
                    Text(url).font(.omSmall).foregroundStyle(Color.buttonPrimary).lineLimit(1)
                }

                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                }

                if let content {
                    Text(content)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                }
            }
        }
    }
}
