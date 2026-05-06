// Fullscreen embed overlay — slides up from bottom, shows full embed content.
// Mirrors UnifiedEmbedFullscreen.svelte with gradient header, scrollable content,
// child embed carousel for composite types, and action bar.

import SwiftUI

struct EmbedFullscreenView: View {
    let embed: EmbedRecord
    let childEmbeds: [EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    @Environment(\.dismiss) var dismiss
    @Environment(\.openURL) private var openURL

    init(embed: EmbedRecord, childEmbeds: [EmbedRecord], allEmbedRecords: [String: EmbedRecord] = [:]) {
        self.embed = embed
        self.childEmbeds = childEmbeds
        self.allEmbedRecords = allEmbedRecords
    }

    @State private var selectedChildId: String?
    @State private var showChildFullscreen = false

    private var embedType: EmbedType? {
        EmbedType(rawValue: embed.type)
    }

    var body: some View {
        ZStack(alignment: .top) {
            ScrollView {
                VStack(spacing: 0) {
                    headerBanner
                    contentArea
                    if !childEmbeds.isEmpty {
                        childEmbedsSection
                    }
                }
            }
            .background(Color.grey0)

            HStack(spacing: .spacing3) {
                OMIconButton(icon: "close", label: "Close", size: 38, iconSize: 18) {
                    dismiss()
                }

                Spacer()

                OMIconButton(icon: "copy", label: "Copy", size: 38, iconSize: 18) {
                    copyContent()
                }

                OMIconButton(icon: "share", label: "Share", size: 38, iconSize: 18, isProminent: true) {
                    shareEmbed()
                }
            }
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing5)

            if showChildFullscreen,
               let childId = selectedChildId,
               let child = childEmbeds.first(where: { $0.id == childId }) {
                ZStack(alignment: .topTrailing) {
                    Color.black.opacity(0.38)
                        .ignoresSafeArea()
                        .onTapGesture {
                            showChildFullscreen = false
                        }

                    EmbedFullscreenView(embed: child, childEmbeds: [], allEmbedRecords: allEmbedRecords)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        .padding(.spacing8)
                }
            }
        }
    }

    // MARK: - Header banner with gradient

    @ViewBuilder
    private var headerBanner: some View {
        if embedType == .webWebsite {
            websiteHeaderBanner
        } else {
            standardHeaderBanner
        }
    }

    private var standardHeaderBanner: some View {
        ZStack(alignment: .bottomLeading) {
            if let appId = embedType?.appId {
                AppGradientBackground(appId: appId)
                    .frame(height: 120)
                    .accessibilityHidden(true)
            } else {
                LinearGradient.primary
                    .frame(height: 120)
                    .accessibilityHidden(true)
            }

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(embedType?.displayName ?? embed.type)
                    .font(.omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)

                if let subtitle = headerSubtitle {
                    Text(subtitle)
                        .font(.omSmall)
                        .foregroundStyle(.white.opacity(0.8))
                        .lineLimit(2)
                }
            }
            .padding(.horizontal, .spacing6)
            .padding(.bottom, .spacing4)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(embedType?.displayName ?? embed.type)\(headerSubtitle.map { ": \($0)" } ?? "")")
    }

    private var websiteHeaderBanner: some View {
        ZStack(alignment: .center) {
            AppGradientBackground(appId: "web")
                .frame(height: 238)
                .accessibilityHidden(true)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))

            HStack {
                Icon("web", size: 130)
                    .foregroundStyle(.white.opacity(0.22))
                    .rotationEffect(.degrees(-12))
                    .offset(x: -50, y: 45)
                    .accessibilityHidden(true)

                Spacer()

                Icon("web", size: 110)
                    .foregroundStyle(.white.opacity(0.22))
                    .rotationEffect(.degrees(14))
                    .offset(x: 40, y: 38)
                    .accessibilityHidden(true)
            }
            .clipped()

            VStack(spacing: .spacing4) {
                Icon("web", size: 42)
                    .foregroundStyle(Color.fontButton)
                    .accessibilityHidden(true)

                HStack(spacing: .spacing2) {
                    if let faviconURL = websiteFaviconURL, let url = URL(string: faviconURL) {
                        AsyncImage(url: url) { phase in
                            switch phase {
                            case .success(let image):
                                image
                                    .resizable()
                                    .aspectRatio(contentMode: .fill)
                            default:
                                Color.clear
                            }
                        }
                        .frame(width: 19, height: 19)
                        .clipShape(RoundedRectangle(cornerRadius: .radius1))
                    }

                    Text(websiteTitle)
                        .font(.omH3)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontButton)
                        .multilineTextAlignment(.center)
                        .lineLimit(2)
                }

                if let date = websiteDataDate {
                    Text(AppStrings.dataFrom(date))
                        .font(.omP)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontButton.opacity(0.85))
                }

                Button {
                    if let url = URL(string: websiteURL) {
                        openURL(url)
                    }
                } label: {
                    Text(AppStrings.openOnProvider(websiteHost))
                        .font(.omP)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, .spacing10)
                        .padding(.vertical, .spacing5)
                        .background(Color.buttonPrimary)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                }
                .buttonStyle(.plain)
                .offset(y: 18)
            }
            .padding(.horizontal, .spacing20)
        }
        .padding(.horizontal, .spacing5)
        .padding(.top, 68)
        .padding(.bottom, .spacing12)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(websiteTitle)\(websiteDataDate.map { ", \(AppStrings.dataFrom($0))" } ?? "")")
    }

    private var headerSubtitle: String? {
        guard let data = embed.data, case .raw(let dict) = data else { return nil }
        if let query = dict["query"]?.value as? String { return query }
        if let title = dict["title"]?.value as? String { return title }
        if let url = dict["url"]?.value as? String { return url }
        return nil
    }

    // MARK: - Content area

    private var contentArea: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            EmbedContentView(embed: embed, mode: .fullscreen, allEmbedRecords: allEmbedRecords)
        }
        .padding(embedType == .webWebsite ? 0 : .spacing6)
    }

    private var websiteRawData: [String: AnyCodable] {
        guard let data = embed.data, case .raw(let dict) = data else { return [:] }
        return dict
    }

    private var websiteURL: String {
        websiteRawData["url"]?.value as? String ?? ""
    }

    private var websiteTitle: String {
        firstWebsiteString(["title", "site_name"]) ?? websiteHost
    }

    private var websiteHost: String {
        guard let host = URL(string: websiteURL)?.host else { return websiteURL }
        let parts = host.replacingOccurrences(of: "www.", with: "").split(separator: ".")
        guard parts.count > 2 else { return parts.joined(separator: ".") }
        let lastTwo = parts.suffix(2).joined(separator: ".")
        let twoPartTLDs = ["co.uk", "com.au", "co.nz", "org.uk", "com.br", "co.jp", "co.kr", "co.in", "com.mx", "com.cn"]
        if twoPartTLDs.contains(lastTwo), parts.count >= 3 {
            return parts.suffix(3).joined(separator: ".")
        }
        return lastTwo
    }

    private var websiteFaviconURL: String? {
        if let favicon = firstWebsiteString(["meta_url_favicon", "favicon_url", "favicon"]) {
            return proxiedImageURL(favicon, maxWidth: 38)
        }
        return proxiedFaviconURL(websiteURL)
    }

    private var websiteDataDate: String? {
        guard let raw = firstWebsiteString(["page_age", "data_date", "date", "published_date"]) else { return nil }
        if let date = parseWebsiteRelativeDate(raw) {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy/MM/dd"
            return formatter.string(from: date)
        }
        return raw.replacingOccurrences(of: "-", with: "/")
    }

    private func firstWebsiteString(_ keys: [String]) -> String? {
        for key in keys {
            if let value = websiteRawData[key]?.value as? String, !value.isEmpty {
                return value
            }
            if key == "meta_url_favicon",
               let metaURL = websiteRawData["meta_url"]?.value as? [String: Any],
               let favicon = metaURL["favicon"] as? String,
               !favicon.isEmpty {
                return favicon
            }
        }
        return nil
    }

    private func proxiedImageURL(_ rawURL: String, maxWidth: Int) -> String? {
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

    private func proxiedFaviconURL(_ pageURL: String) -> String? {
        guard !pageURL.isEmpty else { return nil }
        var components = URLComponents(string: "https://preview.openmates.org/api/v1/favicon")
        components?.queryItems = [URLQueryItem(name: "url", value: pageURL)]
        return components?.url?.absoluteString
    }

    private func parseWebsiteRelativeDate(_ value: String) -> Date? {
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

    // MARK: - Child embeds (for composite types)

    private var childEmbedsSection: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text("\(LocalizationManager.shared.text("embed.results")) (\(childEmbeds.count))")
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .padding(.horizontal, .spacing6)

            ScrollView(.horizontal, showsIndicators: false) {
                LazyHStack(spacing: .spacing4) {
                    ForEach(childEmbeds) { child in
                        EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords) {
                            selectedChildId = child.id
                            showChildFullscreen = true
                        }
                        .frame(width: 260, height: 180)
                    }
                }
                .padding(.horizontal, .spacing6)
            }
            .accessibilityLabel("Related embeds, \(childEmbeds.count) items. Scroll horizontally to browse")
        }
        .padding(.vertical, .spacing4)
    }

    // MARK: - Actions

    private func shareEmbed() {
        Task {
            let webAppURL = await APIClient.shared.webAppURL
            let shareURL = webAppURL.appendingPathComponent("embed/\(embed.id)")
            #if os(iOS)
            let activityVC = UIActivityViewController(activityItems: [shareURL], applicationActivities: nil)
            if let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
               let rootVC = windowScene.windows.first?.rootViewController {
                rootVC.present(activityVC, animated: true)
            }
            #elseif os(macOS)
            let sharingPicker = NSSharingServicePicker(items: [shareURL])
            if let window = NSApplication.shared.windows.first {
                sharingPicker.show(relativeTo: .zero, of: window.contentView!, preferredEdge: .minY)
            }
            #endif
        }
    }

    private func copyContent() {
        #if os(iOS)
        if let data = embed.data, case .raw(let dict) = data {
            let text = dict.map { "\($0.key): \($0.value.value)" }.joined(separator: "\n")
            UIPasteboard.general.string = text
        }
        #elseif os(macOS)
        if let data = embed.data, case .raw(let dict) = data {
            let text = dict.map { "\($0.key): \($0.value.value)" }.joined(separator: "\n")
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
        }
        #endif
    }
}

// MARK: - Gradient background helper

struct AppGradientBackground: View {
    let appId: String

    var body: some View {
        Rectangle()
            .fill(gradient)
            .overlay(
                LinearGradient(
                    colors: [.clear, .black.opacity(0.3)],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
    }

    private var gradient: AnyShapeStyle {
        switch appId {
        case "web": return AnyShapeStyle(LinearGradient.appWeb)
        case "videos": return AnyShapeStyle(LinearGradient.appVideos)
        case "code": return AnyShapeStyle(LinearGradient.appCode)
        case "maps": return AnyShapeStyle(LinearGradient.appMaps)
        case "travel": return AnyShapeStyle(LinearGradient.appTravel)
        case "news": return AnyShapeStyle(LinearGradient.appNews)
        case "shopping": return AnyShapeStyle(LinearGradient.appShopping)
        case "health": return AnyShapeStyle(LinearGradient.appHealth)
        case "nutrition": return AnyShapeStyle(LinearGradient.appNutrition)
        case "events": return AnyShapeStyle(LinearGradient.appEvents)
        case "photos", "images": return AnyShapeStyle(LinearGradient.appPhotos)
        case "music": return AnyShapeStyle(LinearGradient.appMusic)
        case "mail": return AnyShapeStyle(LinearGradient.appMail)
        case "docs": return AnyShapeStyle(LinearGradient.appDocs)
        case "pdf": return AnyShapeStyle(LinearGradient.appPdf)
        case "home": return AnyShapeStyle(LinearGradient.appHome)
        case "finance": return AnyShapeStyle(LinearGradient.appFinance)
        case "math": return AnyShapeStyle(LinearGradient.appMath)
        case "audio": return AnyShapeStyle(LinearGradient.appAudio)
        default: return AnyShapeStyle(LinearGradient.primary)
        }
    }
}
