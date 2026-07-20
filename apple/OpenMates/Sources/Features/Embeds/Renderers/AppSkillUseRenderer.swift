// App skill use embed renderer — renders parent skill executions and their child
// result previews inside the unified embed shell.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/AppSkillUseRenderer.ts
//          frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/calendar/CalendarActionEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/calendar/CalendarActionEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/fitness/FitnessSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/fitness/FitnessSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/fitness/FitnessResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/fitness/FitnessResultEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/weather/WeatherRainRadarEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/weather/WeatherRainRadarEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialsEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialsEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialResultEmbedFullscreen.svelte
// CSS:     frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Combine
import SwiftUI

struct AppSkillUseRenderer: View {
    let embed: EmbedRecord
    let allEmbedRecords: [String: EmbedRecord]
    let mode: EmbedDisplayMode
    var onOpenEmbed: (EmbedRecord) -> Void = { _ in }

    private var data: [String: AnyCodable] {
        embed.rawData ?? [:]
    }

    private var query: String {
        (data["query"]?.value as? String) ?? (data["title"]?.value as? String) ?? skillTitle
    }

    private var provider: String? {
        data["provider"]?.value as? String
    }

    private var providerDisplayName: String? {
        guard let provider, !provider.isEmpty else { return nil }
        if provider == "Brave" {
            return "Brave Search"
        }
        return provider
    }

    private var appId: String {
        embed.appId ?? data["app_id"]?.value as? String ?? EmbedType(rawValue: embed.type)?.appId ?? "web"
    }

    private var skillId: String {
        embed.skillId ?? data["skill_id"]?.value as? String ?? skillIdFromType ?? "search"
    }

    private var skillIdFromType: String? {
        let parts = embed.type.split(separator: ":")
        guard parts.count >= 3, parts[0] == "app" else { return nil }
        return String(parts[2])
    }

    private var skillTitle: String {
        switch (appId, skillId) {
        case ("web", "search"), ("news", "search"): return "Search"
        case ("events", "search"), ("images", "search"), ("videos", "search"): return "Search"
        case ("code", "get_docs"): return "Docs"
        case ("web", "read"): return "Read"
        case ("math", "calculate"): return "Calculate"
        case ("reminder", "set-reminder"): return "Reminder"
        default:
            return EmbedType(rawValue: embed.type)?.displayName ?? skillId.replacingOccurrences(of: "_", with: " ")
        }
    }

    private var isFitnessSearchSkill: Bool {
        appId == "fitness" && (skillId == "search_locations" || skillId == "search_classes")
    }

    private var isCalendarActionSkill: Bool {
        appId == "calendar" && ["get-events", "create-event", "update-event", "delete-event"].contains(skillId)
    }

    private var childEmbeds: [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return uniqueEmbeds(explicit) }
        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { $0.id < $1.id }
        if !parented.isEmpty { return uniqueEmbeds(parented) }

        let preview = previewChildEmbeds
        if !preview.isEmpty { return preview }

        return uniqueEmbeds(allEmbedRecords.values
            .filter { child in
                guard child.id != embed.id else { return false }
                let type = EmbedType(rawValue: child.type)
                switch appId {
                case "web", "news":
                    return type == .webWebsite
                case "images", "photos":
                    return type == .imagesImageResult || type == .image
                case "videos":
                    return type == .videosVideo
                case "events":
                    return type == .eventsEvent
                default:
                    return child.appId == appId
                }
            }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) })
    }

    private var parentResultCount: Int {
        EmbedFieldReader.int(data, keys: ["result_count"]) ?? childEmbeds.count
    }

    private var previewChildEmbeds: [EmbedRecord] {
        let previewResults = EmbedFieldReader.dictionaryArray(data, key: "preview_results")
        guard !previewResults.isEmpty else { return [] }

        return previewResults.enumerated().map { index, result in
            var recordData = result.mapValues { AnyCodable($0) }
            recordData["app_id"] = recordData["app_id"] ?? AnyCodable(appId)
            return EmbedRecord(
                id: "\(embed.id)-preview-\(index)",
                type: previewChildType,
                status: .finished,
                data: .raw(recordData),
                parentEmbedId: embed.id,
                appId: appId,
                skillId: nil,
                embedIds: nil,
                createdAt: embed.createdAt
            )
        }
    }

    private var previewChildType: String {
        switch appId {
        case "images", "photos": return EmbedType.imagesImageResult.rawValue
        case "videos": return EmbedType.videosVideo.rawValue
        case "business": return EmbedType.businessCompanyFinancialResult.rawValue
        default: return EmbedType.webWebsite.rawValue
        }
    }

    var body: some View {
        switch mode {
        case .preview:
            preview
        case .fullscreen:
            fullscreen
        }
    }

    private var preview: AnyView {
        let model = SearchSkillPreviewModel(embed: embed, allEmbedRecords: allEmbedRecords)
        if appId == "web", skillId == "search" {
            return AnyView(WebSearchEmbedRenderer(model: model, mode: .preview, onOpenEmbed: onOpenEmbed))
        } else if appId == "web", skillId == "read" {
            return AnyView(WebReadEmbedRenderer(data: data, mode: .preview))
        } else if appId == "images", skillId == "search" {
            return AnyView(ImagesSearchEmbedRenderer(model: model, mode: .preview, onOpenEmbed: onOpenEmbed))
        } else if appId == "images", skillId == "generate" || skillId == "generate_draft" {
            return AnyView(ImageGenerateEmbedRenderer(data: data, mode: .preview))
        } else if appId == "images", skillId == "view" {
            return AnyView(ImageEmbedRenderer(data: data, mode: .preview))
        } else if appId == "videos", skillId == "create" {
            return AnyView(RemotionVideoCreateRenderer(embedId: embed.id, data: data, mode: .preview))
        } else if appId == "code", skillId == "get_docs" {
            return AnyView(CodeGetDocsEmbedRenderer(data: data, mode: .preview))
        } else if appId == "events", skillId == "search" {
            return AnyView(EventsSearchEmbedRenderer(embed: embed, data: data, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if isCalendarActionSkill {
            return AnyView(CalendarActionEmbedRenderer(embed: embed, data: data, skillId: skillId, mode: .preview))
        } else if isFitnessSearchSkill {
            return AnyView(FitnessSearchEmbedRenderer(embed: embed, data: data, mode: .preview))
        } else if appId == "weather", skillId == "rain_radar" {
            return AnyView(WeatherRainRadarEmbedRenderer(embed: embed, data: data, mode: .preview))
        } else if appId == "travel", skillId == "search_connections" {
            return AnyView(TravelSearchEmbedRenderer(embed: embed, data: data, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "travel", skillId == "search_stays" {
            return AnyView(TravelStaysEmbedRenderer(embed: embed, data: data, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "travel", skillId == "price_calendar" {
            return AnyView(TravelPriceCalendarEmbedRenderer(data: data, mode: .preview))
        } else if appId == "business", skillId == "company_financials" {
            return AnyView(BusinessCompanyFinancialsEmbedRenderer(embed: embed, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "images", !childEmbeds.isEmpty {
            return AnyView(imagesSearchPreview)
        } else {
            return AnyView(textSearchPreview)
        }
    }

    private var imagesSearchPreview: some View {
        VStack(alignment: .leading, spacing: 0) {
            childStrip

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(query)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey100)
                    .lineLimit(2)

                if let providerDisplayName {
                    Text("via \(providerDisplayName)")
                        .font(.omTiny)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey70)
                        .lineLimit(1)
                }

                webSearchResultsInfo
                    .padding(.top, .spacing1)
            }
            .padding(.top, .spacing5)
            .padding(.horizontal, .spacing10)
            .padding(.bottom, .spacing4)

            Spacer(minLength: 61)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    private var textSearchPreview: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(query)
                .font(.omP)
                .fontWeight(.bold)
                .foregroundStyle(Color.grey100)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let providerDisplayName {
                Text("via \(providerDisplayName)")
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
            }

            if skillId == "search", !childEmbeds.isEmpty {
                webSearchResultsInfo
                    .padding(.top, .spacing1)
            } else if appId != "images", !childEmbeds.isEmpty {
                childStrip
                    .padding(.top, .spacing2)
            }

            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    @ViewBuilder
    private var fullscreen: some View {
        let model = SearchSkillPreviewModel(embed: embed, allEmbedRecords: allEmbedRecords)
        if appId == "web", skillId == "search" {
            WebSearchEmbedRenderer(model: model, mode: .fullscreen, onOpenEmbed: onOpenEmbed)
        } else if appId == "web", skillId == "read" {
            WebReadEmbedRenderer(data: data, mode: .fullscreen)
        } else if appId == "images", skillId == "search" {
            ImagesSearchEmbedRenderer(model: model, mode: .fullscreen, onOpenEmbed: onOpenEmbed)
        } else if appId == "images", skillId == "generate" || skillId == "generate_draft" {
            ImageGenerateEmbedRenderer(data: data, mode: .fullscreen)
        } else if appId == "images", skillId == "view" {
            ImageEmbedRenderer(data: data, mode: .fullscreen)
        } else if appId == "videos", skillId == "create" {
            RemotionVideoCreateRenderer(embedId: embed.id, data: data, mode: .fullscreen)
        } else if appId == "code", skillId == "get_docs" {
            CodeGetDocsEmbedRenderer(data: data, mode: .fullscreen)
        } else if appId == "events", skillId == "search" {
            EventsSearchEmbedRenderer(embed: embed, data: data, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if isCalendarActionSkill {
            CalendarActionEmbedRenderer(embed: embed, data: data, skillId: skillId, mode: .fullscreen)
        } else if isFitnessSearchSkill {
            FitnessSearchEmbedRenderer(embed: embed, data: data, mode: .fullscreen)
        } else if appId == "weather", skillId == "rain_radar" {
            WeatherRainRadarEmbedRenderer(embed: embed, data: data, mode: .fullscreen)
        } else if appId == "travel", skillId == "search_connections" {
            TravelSearchEmbedRenderer(embed: embed, data: data, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "travel", skillId == "search_stays" {
            TravelStaysEmbedRenderer(embed: embed, data: data, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "travel", skillId == "price_calendar" {
            TravelPriceCalendarEmbedRenderer(data: data, mode: .fullscreen)
        } else if appId == "business", skillId == "company_financials" {
            BusinessCompanyFinancialsEmbedRenderer(embed: embed, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else {
            VStack(alignment: .leading, spacing: .spacing6) {
                if !childEmbeds.isEmpty {
                    if appId == "images" {
                        LazyVGrid(columns: [GridItem(.flexible())], spacing: .spacing5) {
                            ForEach(childEmbeds) { child in
                                ImageResultFullscreenCard(embed: child) {
                                    onOpenEmbed(child)
                                }
                            }
                        }
                    } else {
                        LazyVStack(spacing: .spacing4) {
                            ForEach(childEmbeds) { child in
                                SearchResultFullscreenRow(embed: child, appId: appId) {
                                    onOpenEmbed(child)
                                }
                            }
                        }
                    }
                } else {
                    Text(LocalizationManager.shared.text("embeds.search_no_results"))
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontSecondary)
                }
            }
        }
    }

    private var childStrip: some View {
        HStack(spacing: 0) {
            ForEach(Array(childEmbeds.prefix(10).enumerated()), id: \.element.id) { _, child in
                childThumbnail(for: child)
                    .frame(width: appId == "images" ? 44 : 62, height: appId == "images" ? 30 : 46)
                    .clipped()
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .overlay(
            RoundedRectangle(cornerRadius: .radius3)
                .stroke(Color.grey30.opacity(appId == "images" ? 0 : 1), lineWidth: 1)
        )
    }

    private var webSearchResultsInfo: some View {
        HStack(spacing: .spacing3) {
            if faviconEmbeds.isEmpty {
                Text(parentResultCount > 0 ? "\(parentResultCount) results" : "")
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.grey60)
            } else {
                HStack(spacing: -6) {
                    ForEach(Array(faviconEmbeds.prefix(3).enumerated()), id: \.element.id) { index, child in
                        faviconView(for: child)
                            .zIndex(Double(faviconEmbeds.count - index))
                    }
                }
                .frame(height: 19)

                let remaining = max(0, parentResultCount - min(3, faviconEmbeds.count))
                if remaining > 0 {
                    Text("+ \(remaining) more")
                        .font(.omXs)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey70)
                }
            }
        }
        .frame(height: 22, alignment: .leading)
    }

    private var faviconEmbeds: [EmbedRecord] {
        uniqueEmbedsBySource(childEmbeds.filter { child in
            let raw = child.rawData ?? [:]
            return faviconURL(for: raw) != nil
        })
    }

    private func uniqueEmbeds(_ embeds: [EmbedRecord]) -> [EmbedRecord] {
        var seen = Set<String>()
        return embeds.filter { seen.insert($0.id).inserted }
    }

    private func uniqueEmbedsBySource(_ embeds: [EmbedRecord]) -> [EmbedRecord] {
        var seen = Set<String>()
        return embeds.filter { child in
            let raw = child.rawData ?? [:]
            let key = firstString(in: raw, keys: ["source", "source_domain", "source_page_url", "url"])
                ?? firstString(in: raw, keys: ["favicon", "favicon_url", "meta_url_favicon"])
                ?? child.id
            return seen.insert(key).inserted
        }
    }

    private func faviconView(for child: EmbedRecord) -> some View {
        let raw = child.rawData ?? [:]
        let favicon = faviconURL(for: raw)
        return ZStack {
            Circle().fill(Color.grey0)
            if let favicon, let url = URL(string: favicon) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: { AppIconView(appId: "web", size: 13) }
                .clipShape(Circle())
            } else {
                AppIconView(appId: "web", size: 13)
            }
        }
        .frame(width: 19, height: 19)
        .overlay(Circle().stroke(Color.grey0, lineWidth: 1))
    }

    @ViewBuilder
    private func childThumbnail(for child: EmbedRecord) -> some View {
        let raw = child.rawData ?? [:]
        let imageURL = imageURL(for: raw, keys: [
            "thumbnail_url", "thumbnail", "image_url", "image", "thumbnail_original", "meta_url_favicon", "favicon"
        ])
        if let imageURL, let url = URL(string: imageURL) {
            CachedRemoteImage(url: url) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: { fallbackThumb(for: child) }
        } else {
            fallbackThumb(for: child)
        }
    }

    private func fallbackThumb(for child: EmbedRecord) -> some View {
        ZStack {
            Color.grey20
            AppIconView(appId: child.appId ?? EmbedType(rawValue: child.type)?.appId ?? appId, size: 28)
        }
    }

    private var skillPlaceholder: some View {
        ZStack {
            AppGradientBackground(appId: appId)
            Icon(AppIconView.iconName(forAppId: appId), size: 38)
                .foregroundStyle(.white)
        }
        .frame(height: 54)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }

    private func firstString(in data: [String: AnyCodable], keys: [String]) -> String? {
        for key in keys {
            if let value = data[key]?.value as? String, !value.isEmpty {
                return value
            }
            if key == "meta_url_favicon",
               let metaURL = data["meta_url"]?.value as? [String: Any],
               let favicon = metaURL["favicon"] as? String,
               !favicon.isEmpty {
                return favicon
            }
        }
        return nil
    }

    private func imageURL(for data: [String: AnyCodable], keys: [String], maxWidth: Int = 520) -> String? {
        guard let raw = firstString(in: data, keys: keys) else { return nil }
        return EmbedFieldReader.proxiedImageURL(raw, maxWidth: maxWidth)
    }

    private func faviconURL(for data: [String: AnyCodable]) -> String? {
        EmbedFieldReader.proxiedImageURL(
            firstString(in: data, keys: ["favicon", "favicon_url", "meta_url_favicon"]),
            maxWidth: 64
        ) ?? EmbedFieldReader.proxiedFaviconURL(pageURL: firstString(in: data, keys: ["source_page_url", "url"]))
    }
}

private struct SearchResultFullscreenRow: View {
    let embed: EmbedRecord
    let appId: String
    let onTap: () -> Void

    private var raw: [String: AnyCodable] { embed.rawData ?? [:] }
    private var title: String {
        firstString(["title", "name", "filename"]) ?? EmbedType(rawValue: embed.type)?.displayName ?? embed.type
    }
    private var description: String? {
        firstString(["description", "snippet", "text", "content"])
    }
    private var imageURL: String? {
        EmbedFieldReader.proxiedImageURL(
            firstString(["thumbnail_original", "thumbnail_url", "preview_image_url", "image_url", "image", "url"]),
            maxWidth: 520
        )
    }
    private var favicon: String? {
        EmbedFieldReader.proxiedImageURL(firstString(["meta_url_favicon", "favicon", "favicon_url"]), maxWidth: 64)
            ?? EmbedFieldReader.proxiedFaviconURL(pageURL: firstString(["source_page_url", "url"]))
    }

    var body: some View {
        Button(action: onTap) {
            rowContent
        }
        .buttonStyle(.plain)
    }

    private var rowContent: some View {
        HStack(alignment: .center, spacing: .spacing4) {
            AppIconView(appId: appId, size: 61)

            if let favicon, let url = URL(string: favicon) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Icon(appId == "images" ? "image" : "web", size: 20)
                        .foregroundStyle(Color.grey70)
                }
                .frame(width: 25, height: 25)
                .clipShape(RoundedRectangle(cornerRadius: .radius1))
            }

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(title)
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey100)
                    .lineLimit(2)
                if let description {
                    Text(description)
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.grey70)
                        .lineLimit(3)
                }
            }

            Spacer(minLength: 0)

            if let imageURL, let url = URL(string: imageURL) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: { Color.grey25 }
                .frame(width: 120, height: 82)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
            }
        }
        .padding(.spacing4)
        .background(Color.grey25)
        .clipShape(RoundedRectangle(cornerRadius: 30))
    }

    private func firstString(_ keys: [String]) -> String? {
        for key in keys {
            if let value = raw[key]?.value as? String, !value.isEmpty {
                return value
            }
            if key == "meta_url_favicon",
               let metaURL = raw["meta_url"]?.value as? [String: Any],
               let favicon = metaURL["favicon"] as? String,
               !favicon.isEmpty {
                return favicon
            }
        }
        return nil
    }
}

private struct ImageResultFullscreenCard: View {
    let embed: EmbedRecord
    let onTap: () -> Void

    private var raw: [String: AnyCodable] { embed.rawData ?? [:] }
    private var title: String? { firstString(["title", "name"]) }
    private var sourceDomain: String {
        firstString(["source", "source_domain"]) ?? host(from: firstString(["source_page_url", "url"])) ?? "Image"
    }
    private var imageURL: String? {
        EmbedFieldReader.proxiedImageURL(firstString(["image_url", "thumbnail_url", "thumbnail_original", "image"]), maxWidth: 520)
    }
    private var favicon: String? {
        EmbedFieldReader.proxiedImageURL(firstString(["favicon_url", "favicon", "meta_url_favicon"]), maxWidth: 64)
            ?? EmbedFieldReader.proxiedFaviconURL(pageURL: firstString(["source_page_url", "url"]))
    }

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 0) {
                ZStack(alignment: .topLeading) {
                    if let imageURL, let url = URL(string: imageURL) {
                        CachedRemoteImage(url: url) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: {
                            Color.grey20.overlay(Icon("image", size: 28).foregroundStyle(Color.grey40))
                        }
                    } else {
                        Color.grey20.overlay(Icon("image", size: 28).foregroundStyle(Color.grey40))
                    }

                    if let title {
                        Text(title)
                            .font(.omTiny)
                            .fontWeight(.medium)
                            .foregroundStyle(.white)
                            .lineLimit(2)
                            .padding(.horizontal, 14)
                            .padding(.top, 12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                LinearGradient(
                                    colors: [.black.opacity(0.5), .clear],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                    }
                }
                .frame(height: 170)
                .clipped()

                HStack(spacing: .spacing5) {
                    AppIconView(appId: "images", size: 61)

                    if let favicon, let url = URL(string: favicon) {
                        CachedRemoteImage(url: url) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: { EmptyView() }
                        .frame(width: 20, height: 20)
                        .clipShape(RoundedRectangle(cornerRadius: .radius1))
                    }

                    Text(sourceDomain)
                        .font(.omP)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.grey100)
                        .lineLimit(2)

                    Spacer(minLength: 0)
                }
                .frame(height: 61)
                .background(Color.grey30)
                .clipShape(RoundedRectangle(cornerRadius: 30))
            }
            .background(Color.grey25)
            .clipShape(RoundedRectangle(cornerRadius: 30))
        }
        .buttonStyle(.plain)
    }

    private func firstString(_ keys: [String]) -> String? {
        for key in keys {
            if let value = raw[key]?.value as? String, !value.isEmpty {
                return value
            }
            if key == "meta_url_favicon",
               let metaURL = raw["meta_url"]?.value as? [String: Any],
               let favicon = metaURL["favicon"] as? String,
               !favicon.isEmpty {
                return favicon
            }
        }
        return nil
    }

    private func host(from value: String?) -> String? {
        guard let value, let url = URL(string: value), let host = url.host else { return nil }
        return host.replacingOccurrences(of: "www.", with: "")
    }
}

private struct BusinessCompanyFinancialsEmbedRenderer: View {
    let embed: EmbedRecord
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private var model: BusinessCompanyFinancialsModel {
        BusinessCompanyFinancialsModel(embed: embed, allEmbedRecords: allEmbedRecords)
    }

    var body: some View {
        switch mode {
        case .preview:
            BusinessCompanyFinancialsPreview(model: model)
        case .fullscreen:
            BusinessCompanyFinancialsFullscreen(model: model, onOpenEmbed: onOpenEmbed)
        }
    }
}

private struct BusinessCompanyFinancialsPreview: View {
    let model: BusinessCompanyFinancialsModel

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(model.query)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(model.resultSummary)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .lineLimit(2)

            HStack(spacing: .spacing2) {
                BusinessFinancialChip(label: model.periodLabel)
                BusinessFinancialChip(label: model.metricGroupLabel)
            }
            .padding(.top, .spacing1)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .accessibilityIdentifier("business-financials-preview")
    }
}

private struct BusinessCompanyFinancialsFullscreen: View {
    let model: BusinessCompanyFinancialsModel
    let onOpenEmbed: (EmbedRecord) -> Void

    private let columns = [GridItem(.adaptive(minimum: 260, maximum: 320), spacing: .spacing6, alignment: .top)]

    var body: some View {
        let results = model.financialResults
        Group {
            if model.status == .error {
                Text(AppStrings.genericProcessingError)
                    .font(.omP)
                    .foregroundStyle(Color.error)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else if results.isEmpty {
                Text(model.resultSummary)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else {
                LazyVGrid(columns: columns, alignment: .center, spacing: .spacing6) {
                    ForEach(results) { result in
                        BusinessCompanyFinancialResultCard(model: result) {
                            onOpenEmbed(result.embed)
                        }
                        .frame(maxWidth: 320)
                    }
                }
                .frame(maxWidth: 1040)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing8)
                .padding(.bottom, 120)
            }
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .accessibilityIdentifier("business-financials-fullscreen")
    }
}

struct BusinessCompanyFinancialResultEmbedRenderer: View {
    let embed: EmbedRecord
    let mode: EmbedDisplayMode

    private var model: BusinessCompanyFinancialResultModel {
        BusinessCompanyFinancialResultModel(embed: embed)
    }

    var body: some View {
        switch mode {
        case .preview:
            BusinessCompanyFinancialResultCard(model: model) {}
        case .fullscreen:
            BusinessCompanyFinancialResultFullscreen(model: model)
        }
    }
}

private struct BusinessCompanyFinancialResultCard: View {
    let model: BusinessCompanyFinancialResultModel
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: .spacing4) {
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(model.company)
                        .font(.omSmall)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(1)
                    Text(model.subtitle ?? model.periodLabel)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                }

                HStack(spacing: .spacing3) {
                    BusinessFinancialMetricTile(label: AppStrings.businessFinancialRevenue, value: model.revenue)
                    BusinessFinancialMetricTile(label: AppStrings.businessFinancialNetIncome, value: model.netIncome)
                }

                if let filed = model.filed {
                    Text("\(AppStrings.businessFinancialFiled) \(filed)")
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, minHeight: 148, alignment: .topLeading)
            .background(
                RoundedRectangle(cornerRadius: 22)
                    .fill(Color.grey0)
                    .overlay(alignment: .topTrailing) {
                        AppGradientBackground(appId: "business")
                            .frame(width: 92, height: 92)
                            .opacity(0.16)
                            .clipShape(RoundedRectangle(cornerRadius: 22))
                    }
            )
            .overlay {
                RoundedRectangle(cornerRadius: 22)
                    .stroke(Color.grey20, lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("business-financial-result-preview")
    }
}

private struct BusinessCompanyFinancialResultFullscreen: View {
    let model: BusinessCompanyFinancialResultModel

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: .spacing6) {
                heroCard.frame(maxWidth: 560)
                sideColumn.frame(maxWidth: 420)
            }
            VStack(alignment: .leading, spacing: .spacing6) {
                heroCard
                sideColumn
            }
        }
        .frame(maxWidth: 1040)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing6)
        .padding(.bottom, 120)
        .accessibilityIdentifier("business-financial-result-fullscreen")
    }

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(AppStrings.businessFinancialSecFiling)
                    .font(.omXs)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontSecondary)
                    .textCase(.uppercase)
                Text(model.company)
                    .font(.omH1)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(3)
                Text([model.periodLabel, model.periodRange].compactMap { $0 }.joined(separator: " · "))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }

            HStack(spacing: .spacing4) {
                BusinessFinancialMetricTile(label: AppStrings.businessFinancialRevenue, value: model.revenue, prominent: true)
                BusinessFinancialMetricTile(label: AppStrings.businessFinancialNetIncome, value: model.netIncome, prominent: true)
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, minHeight: 300, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: 28)
                .fill(Color.grey0)
                .overlay(alignment: .topTrailing) {
                    AppGradientBackground(appId: "business")
                        .frame(width: 190, height: 190)
                        .opacity(0.18)
                        .clipShape(RoundedRectangle(cornerRadius: 28))
                }
        )
        .overlay { RoundedRectangle(cornerRadius: 28).stroke(Color.grey20, lineWidth: 1) }
    }

    private var sideColumn: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            metricsCard
            sourceCard
            if !model.notes.isEmpty { notesCard }
        }
    }

    private var metricsCard: some View {
        BusinessFinancialPanel(title: AppStrings.businessFinancialMetrics) {
            if model.metricRows.isEmpty {
                Text(AppStrings.businessFinancialNoMetrics)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(model.metricRows.enumerated()), id: \.offset) { _, row in
                        HStack(alignment: .firstTextBaseline, spacing: .spacing4) {
                            Text(row.label)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontSecondary)
                            Spacer(minLength: .spacing4)
                            Text(row.value)
                                .font(.omSmall)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.fontPrimary)
                                .lineLimit(1)
                        }
                        .padding(.vertical, .spacing3)
                        .overlay(alignment: .top) { Divider().opacity(0.4) }
                    }
                }
            }
        }
    }

    private var sourceCard: some View {
        BusinessFinancialPanel(title: AppStrings.businessFinancialSource) {
            if let sourceMetadata = model.sourceMetadata {
                Text(sourceMetadata)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }
            if model.sourceURL != nil {
                Text(AppStrings.businessFinancialOpenFiling)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.buttonPrimary)
            }
        }
    }

    private var notesCard: some View {
        BusinessFinancialPanel(title: AppStrings.businessFinancialNotes) {
            VStack(alignment: .leading, spacing: .spacing2) {
                ForEach(Array(model.notes.enumerated()), id: \.offset) { _, note in
                    Text(note)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                }
            }
        }
    }
}

private struct BusinessFinancialPanel<Content: View>: View {
    let title: String
    let content: Content

    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(title)
                .font(.omP)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
            content
        }
        .padding(.spacing5)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .overlay { RoundedRectangle(cornerRadius: 24).stroke(Color.grey20, lineWidth: 1) }
    }
}

private struct BusinessFinancialMetricTile: View {
    let label: String
    let value: String
    var prominent = false

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(label)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .lineLimit(1)
            Text(value)
                .font(prominent ? .omH3 : .omSmall)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
        .padding(prominent ? .spacing5 : .spacing3)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10.opacity(0.82))
        .clipShape(RoundedRectangle(cornerRadius: prominent ? 20 : 16))
        .overlay {
            RoundedRectangle(cornerRadius: prominent ? 20 : 16)
                .stroke(Color.grey20, lineWidth: 1)
        }
    }
}

private struct BusinessFinancialChip: View {
    let label: String

    var body: some View {
        Text(label.capitalized)
            .font(.omXxs)
            .foregroundStyle(Color.fontSecondary)
            .padding(.horizontal, .spacing2)
            .padding(.vertical, .spacing1)
            .background(Color.grey10)
            .clipShape(Capsule())
    }
}

private struct CalendarActionEmbedRenderer: View {
    let embed: EmbedRecord
    let data: [String: AnyCodable]
    let skillId: String
    let mode: EmbedDisplayMode

    private var model: CalendarActionValue {
        CalendarActionValue(data: data, skillId: skillId)
    }

    var body: some View {
        switch mode {
        case .preview:
            CalendarActionPreview(model: model, isError: embed.status == .error, isProcessing: embed.status == .processing)
        case .fullscreen:
            CalendarActionFullscreen(model: model, isError: embed.status == .error, isProcessing: embed.status == .processing)
        }
    }
}

private struct CalendarActionPreview: View {
    let model: CalendarActionValue
    let isError: Bool
    let isProcessing: Bool

    private var detail: String? {
        if isError { return model.error ?? AppStrings.genericProcessingError }
        if let summary = model.summary { return summary }
        return isProcessing ? AppStrings.loading : nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing3) {
                Icon("calendar", size: .iconSizeSm)
                    .foregroundStyle(LinearGradient.appCalendar)
                Text(model.title)
                    .font(.omP.weight(.bold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
            }

            if let detail {
                Text(detail)
                    .font(.omSmall)
                    .foregroundStyle(isError ? Color.error : Color.fontSecondary)
                    .lineLimit(3)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

private struct CalendarActionFullscreen: View {
    let model: CalendarActionValue
    let isError: Bool
    let isProcessing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            if isError {
                Text(model.error ?? AppStrings.genericProcessingError)
                    .font(.omP)
                    .foregroundStyle(Color.error)
            } else if !model.items.isEmpty {
                LazyVStack(spacing: .spacing3) {
                    ForEach(model.items) { item in
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text(item.title)
                                .font(.omP.weight(.bold))
                                .foregroundStyle(Color.fontPrimary)
                            if let detail = item.detail {
                                Text(detail)
                                    .font(.omP)
                                    .foregroundStyle(Color.fontSecondary)
                            }
                        }
                        .padding(.spacing4)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.grey0)
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                        .overlay {
                            RoundedRectangle(cornerRadius: .radius4)
                                .stroke(Color.grey20, lineWidth: 1)
                        }
                    }
                }
            } else {
                Text(model.summary ?? (isProcessing ? AppStrings.loading : model.title))
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

@MainActor
private struct CalendarActionValue {
    let title: String
    let summary: String?
    let error: String?
    let items: [CalendarActionItem]

    init(data: [String: AnyCodable], skillId: String) {
        let fallbackTitle = AppStrings.calendarSkillTitle(skillId)
        title = EmbedFieldReader.string(data, keys: ["title"]) ?? fallbackTitle
        summary = EmbedFieldReader.string(data, keys: ["summary", "message"])
        error = EmbedFieldReader.string(data, keys: ["error"])
        let values = EmbedFieldReader.dictionaryArray(data, key: "events").isEmpty
            ? EmbedFieldReader.dictionaryArray(data, key: "results")
            : EmbedFieldReader.dictionaryArray(data, key: "events")
        items = values.enumerated().map { index, value in
            CalendarActionItem(index: index, data: value, fallbackTitle: fallbackTitle)
        }
    }
}

private struct CalendarActionItem: Identifiable {
    let id: String
    let title: String
    let detail: String?

    init(index: Int, data: [String: Any], fallbackTitle: String) {
        id = data.string("event_id") ?? "calendar-item-\(index)"
        title = data.string("summary") ?? data.string("title") ?? data.string("event_id") ?? fallbackTitle
        detail = data.string("start") ?? data.string("start_time") ?? data.string("status") ?? data.string("html_link")
    }
}

private struct WeatherRainRadarEmbedRenderer: View {
    let embed: EmbedRecord
    let data: [String: AnyCodable]
    let mode: EmbedDisplayMode

    private var model: RainRadarValue { RainRadarValue(data: data) }

    var body: some View {
        switch mode {
        case .preview:
            RainRadarPreview(model: model, status: embed.status)
        case .fullscreen:
            RainRadarFullscreen(model: model)
        }
    }
}

private struct RainRadarPreview: View {
    let model: RainRadarValue
    let status: EmbedStatus

    var body: some View {
        if status == .error {
            Text(AppStrings.genericProcessingError)
                .font(.omSmall)
                .foregroundStyle(Color.error)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        } else if status == .processing {
            Text(AppStrings.loading)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        } else {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: .spacing6) { radar; copy }
                VStack(alignment: .leading, spacing: .spacing4) { radar; copy }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
    }

    private var radar: some View {
        RainRadarMap(frame: model.previewFrame, compact: true)
            .frame(minWidth: 120, maxWidth: .infinity, minHeight: 96)
    }

    private var copy: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(model.locationName ?? AppStrings.rainRadar)
                .font(.omSmall.weight(.bold))
                .foregroundStyle(Color.grey100)
                .lineLimit(2)
            Text(model.summaryInTenMinutes ?? AppStrings.rainRadarNoRain)
                .font(.omXs)
                .foregroundStyle(Color.grey70)
                .lineLimit(3)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct RainRadarFullscreen: View {
    let model: RainRadarValue

    @State private var selectedIndex = 0
    @State private var isPlaying = false
    private let playbackTimer = Timer.publish(every: 0.85, on: .main, in: .common).autoconnect()

    private var selectedFrame: RainRadarFrame? {
        guard model.timeline.indices.contains(selectedIndex) else { return model.timeline.first }
        return model.timeline[selectedIndex]
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing10) {
                if model.isUnavailable {
                    summaryCard(unavailable: true)
                } else {
                    radarStage
                    summaryCard(unavailable: false)
                    timelineCard
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing12)
            .padding(.bottom, .spacing20 * 3)
            .frame(maxWidth: 1040)
            .frame(maxWidth: .infinity)
        }
        .onReceive(playbackTimer) { _ in
            guard isPlaying, model.timeline.count > 1 else { return }
            selectedIndex = (selectedIndex + 1) % model.timeline.count
        }
        .onAppear {
            selectedIndex = model.previewIndex
        }
        .onChange(of: model.previewIndex) { _, previewIndex in
            selectedIndex = previewIndex
        }
    }

    private var radarStage: some View {
        RainRadarMap(frame: selectedFrame, compact: false)
            .frame(minHeight: 320)
            .padding(.spacing6)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1) }
            .shadow(color: .black.opacity(0.10), radius: .spacing10, x: 0, y: .spacing4)
    }

    private func summaryCard(unavailable: Bool) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: .spacing10) {
                summaryCopy(unavailable: unavailable)
                Spacer(minLength: .spacing8)
                metrics
            }
            VStack(alignment: .leading, spacing: .spacing8) {
                summaryCopy(unavailable: unavailable)
                metrics
            }
        }
        .padding(.spacing10)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1) }
        .shadow(color: .black.opacity(0.10), radius: .spacing10, x: 0, y: .spacing4)
    }

    private func summaryCopy(unavailable: Bool) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let locationName = model.locationName {
                Text(locationName).font(.omSmall).foregroundStyle(Color.grey70)
            }
            Text(model.summaryInTenMinutes ?? (unavailable ? AppStrings.rainRadarUnavailable : AppStrings.rainRadarNoRain))
                .font(.omH1.weight(.bold))
                .foregroundStyle(Color.grey100)
            if let nextTwoHours = model.summaryNextTwoHours {
                Text(nextTwoHours).font(.omSmall).foregroundStyle(Color.grey70)
            }
        }
    }

    @ViewBuilder
    private var metrics: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            if let peakIntensity = model.peakIntensity {
                Text("\(AppStrings.rainRadarPeak): \(peakIntensity)")
            }
            if let rain = selectedFrame?.rainAtLocation {
                Text("\(AppStrings.rainRadarAtLocation): \(rain.formatted())")
            }
        }
        .font(.omSmall)
        .foregroundStyle(Color.grey70)
    }

    private var timelineCard: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            HStack(spacing: .spacing6) {
                Button {
                    isPlaying.toggle()
                } label: {
                    HStack(spacing: .spacing2) {
                        Icon(isPlaying ? "pause" : "play", size: .iconSizeXs)
                        Text(isPlaying ? AppStrings.rainRadarPause : AppStrings.rainRadarPlay)
                    }
                    .font(.omSmall.weight(.bold))
                    .foregroundStyle(Color.grey100)
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing4)
                    .background(LinearGradient.appWeather.opacity(0.16))
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)

                Spacer(minLength: 0)
                Text(AppStrings.rainRadarFrameCount(model.timeline.count))
                    .font(.omSmall)
                    .foregroundStyle(Color.grey70)
            }

            ScrollView(.horizontal, showsIndicators: false) {
                LazyHStack(spacing: .spacing4) {
                    ForEach(Array(model.timeline.enumerated()), id: \.element.id) { index, frame in
                        Button {
                            selectedIndex = index
                            isPlaying = false
                        } label: {
                            VStack(alignment: .leading, spacing: .spacing1) {
                                if let label = frame.label {
                                    Text(label).lineLimit(1)
                                }
                                if let intensity = frame.maxIntensity {
                                    Text(intensity).fontWeight(.bold).lineLimit(1)
                                }
                            }
                            .font(.omXs)
                            .foregroundStyle(index == selectedIndex ? Color.grey0 : Color.grey100)
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing4)
                            .frame(minWidth: 76, alignment: .leading)
                            .background {
                                Capsule()
                                    .fill(LinearGradient.appWeather)
                                    .opacity(index == selectedIndex ? 1 : 0.16)
                            }
                            .clipShape(Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .padding(.spacing8)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay { RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1) }
        .shadow(color: .black.opacity(0.10), radius: .spacing10, x: 0, y: .spacing4)
    }
}

private struct RainRadarMap: View {
    let frame: RainRadarFrame?
    let compact: Bool

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                LinearGradient.appWeather.opacity(0.18)
                grid(size: geometry.size)
                Capsule()
                    .fill(LinearGradient.appWeather)
                    .opacity(rainOpacity(base: 0.20, contribution: (frame?.rainAreaPercent ?? 0) / 100))
                    .frame(width: geometry.size.width * 0.54, height: geometry.size.height * 0.48)
                    .offset(x: -geometry.size.width * 0.12, y: -geometry.size.height * 0.10)
                Capsule()
                    .fill(LinearGradient.appWeather)
                    .opacity(rainOpacity(base: 0.15, contribution: frame?.rainAtLocation ?? 0))
                    .frame(width: geometry.size.width * 0.34, height: geometry.size.height * 0.34)
                    .offset(x: geometry.size.width * 0.20, y: geometry.size.height * 0.18)
                Circle()
                    .fill(Color.grey100)
                    .frame(width: compact ? 12 : 16, height: compact ? 12 : 16)
                    .overlay(Circle().stroke(Color.grey0, lineWidth: compact ? 2 : 3))
                    .shadow(color: .black.opacity(0.12), radius: compact ? 4 : 6)

                if !compact, let frame {
                    VStack(alignment: .trailing, spacing: .spacing1) {
                        if let label = frame.label { Text(label) }
                        if let timestamp = frame.formattedTimestamp { Text(timestamp).fontWeight(.bold) }
                    }
                    .font(.omXs)
                    .foregroundStyle(Color.grey100)
                    .padding(.spacing5)
                    .background(Color.grey0.opacity(0.86))
                    .clipShape(RoundedRectangle(cornerRadius: .radius7))
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
                    .padding(.spacing8)
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay {
            RoundedRectangle(cornerRadius: .radius8)
                .stroke(Color.grey20, lineWidth: 1)
        }
    }

    private func grid(size: CGSize) -> some View {
        Canvas { context, _ in
            let step: CGFloat = compact ? 18 : 28
            var path = Path()
            stride(from: CGFloat.zero, through: size.width, by: step).forEach {
                path.move(to: CGPoint(x: $0, y: 0))
                path.addLine(to: CGPoint(x: $0, y: size.height))
            }
            stride(from: CGFloat.zero, through: size.height, by: step).forEach {
                path.move(to: CGPoint(x: 0, y: $0))
                path.addLine(to: CGPoint(x: size.width, y: $0))
            }
            context.stroke(path, with: .color(Color.grey100.opacity(0.08)), lineWidth: 1)
        }
    }

    private func rainOpacity(base: Double, contribution: Double) -> Double {
        guard frame?.normalizedIntensity != "none" else { return 0.05 }
        return min(compact ? 0.85 : 0.90, base + contribution)
    }
}

private struct RainRadarValue {
    let locationName: String?
    let summaryInTenMinutes: String?
    let summaryNextTwoHours: String?
    let peakIntensity: String?
    let previewFrameId: String?
    let timeline: [RainRadarFrame]
    let isUnavailable: Bool

    init(data: [String: AnyCodable]) {
        let location = data.dictionary("location")
        let summary = data.dictionary("summary")
        let coverage = data.dictionary("coverage")
        locationName = location.string("name") ?? EmbedFieldReader.string(data, keys: ["location_name"])
        summaryInTenMinutes = summary.string("in_10_min")
        summaryNextTwoHours = summary.string("next_2_hours")
        peakIntensity = summary.string("peak_intensity")
        previewFrameId = summary.string("preview_frame_id")
        timeline = EmbedFieldReader.dictionaryArray(data, key: "timeline").enumerated().map { index, frame in
            RainRadarFrame(index: index, data: frame)
        }
        isUnavailable = coverage.string("status") == "unavailable"
    }

    var previewIndex: Int {
        if let previewFrameId, let index = timeline.firstIndex(where: { $0.id == previewFrameId }) { return index }
        if let index = timeline.firstIndex(where: { $0.kind == "forecast" }) { return index }
        return 0
    }

    var previewFrame: RainRadarFrame? {
        timeline.indices.contains(previewIndex) ? timeline[previewIndex] : timeline.first
    }
}

private struct RainRadarFrame: Identifiable {
    let id: String
    let timestamp: String?
    let kind: String?
    let label: String?
    let rainAtLocation: Double?
    let maxIntensity: String?
    let rainAreaPercent: Double?

    init(index: Int, data: [String: Any]) {
        id = data.string("frame_id") ?? "radar-frame-\(index)"
        timestamp = data.string("timestamp")
        kind = data.string("kind")
        label = data.string("label")
        rainAtLocation = data.double("rain_at_location_mm_5min")
        maxIntensity = data.string("max_intensity")
        rainAreaPercent = data.double("rain_area_pct")
    }

    var normalizedIntensity: String {
        maxIntensity?.lowercased() ?? "none"
    }

    var formattedTimestamp: String? {
        guard let timestamp else { return nil }
        guard let date = ISO8601DateFormatter().date(from: timestamp) else { return timestamp }
        return date.formatted(date: .omitted, time: .shortened)
    }
}

private struct FitnessSearchEmbedRenderer: View {
    let embed: EmbedRecord
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var raw: [String: AnyCodable] { data ?? [:] }
    private var group: FitnessSearchGroup { FitnessSearchGroup(data: raw) }
    private var skillId: String {
        embed.skillId ?? EmbedFieldReader.string(raw, keys: ["skill_id"]) ?? skillIdFromType ?? "search_classes"
    }

    private var skillIdFromType: String? {
        let parts = embed.type.split(separator: ":")
        guard parts.count >= 3, parts[0] == "app" else { return nil }
        return String(parts[2])
    }

    var body: some View {
        switch mode {
        case .preview:
            FitnessSearchPreview(skillId: skillId, group: group)
        case .fullscreen:
            FitnessSearchFullscreen(skillId: skillId, group: group)
        }
    }
}

private struct FitnessSearchPreview: View {
    let skillId: String
    let group: FitnessSearchGroup

    private var title: String {
        skillId == "search_locations" ? AppStrings.fitnessSearchLocations : AppStrings.fitnessSearchClasses
    }

    private var locationLabel: String {
        group.filters.string("address") ?? group.filters.string("city") ?? group.query ?? group.provider
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(group.provider)
                .font(.omXs)
                .fontWeight(.medium)
                .foregroundStyle(Color.grey70)
                .lineLimit(1)

            Text(title)
                .font(.omP)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(2)

            Text(locationLabel)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .lineLimit(1)

            if let summary = group.summary {
                Text(summary)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
            } else if group.resultCount > 0 {
                Text(AppStrings.moreResults(group.resultCount))
                    .font(.omXs)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
            }

            ForEach(group.results.prefix(2)) { result in
                VStack(alignment: .leading, spacing: 1) {
                    Text(result.name)
                        .font(.omXs)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(1)
                    if let subtitle = result.previewSubtitle {
                        Text(subtitle)
                            .font(.omTiny)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(1)
                    }
                }
            }

            if !group.chips.isEmpty {
                FitnessChipRow(chips: group.chips)
                    .padding(.top, .spacing1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

private struct FitnessSearchFullscreen: View {
    let skillId: String
    let group: FitnessSearchGroup

    private let columns = [GridItem(.adaptive(minimum: 240, maximum: 320), spacing: .spacing5)]

    private var title: String {
        skillId == "search_locations" ? AppStrings.fitnessSearchLocations : AppStrings.fitnessSearchClasses
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            VStack(alignment: .leading, spacing: .spacing2) {
                Text(group.provider)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)

                Text(title)
                    .font(.omH2)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)

                if let summary = group.summary {
                    Text(summary)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(3)
                }
            }

            if !group.chips.isEmpty {
                FitnessChipRow(chips: group.chips)
            }

            if group.results.isEmpty {
                Text(group.error ?? AppStrings.searchNoResults)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(group.error == nil ? Color.fontSecondary : Color.error)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else {
                LazyVGrid(columns: columns, alignment: .leading, spacing: .spacing5) {
                    ForEach(group.results) { result in
                        FitnessResultCard(result: result, provider: group.provider)
                    }
                }
                .frame(maxWidth: 1000, alignment: .leading)
            }
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing8)
        .padding(.bottom, 120)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

struct FitnessResultEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var raw: [String: Any] {
        (data ?? [:]).mapValues(\.value)
    }

    private var result: FitnessResultSummary {
        FitnessResultSummary(index: 0, data: raw)
    }

    private var provider: String? {
        raw.string("provider")
    }

    var body: some View {
        switch mode {
        case .preview:
            FitnessResultPreview(result: result)
        case .fullscreen:
            FitnessResultCard(result: result, provider: provider)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing8)
                .frame(maxWidth: 1000, alignment: .topLeading)
                .frame(maxWidth: .infinity, alignment: .top)
        }
    }
}

private struct FitnessResultPreview: View {
    let result: FitnessResultSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(result.name)
                .font(.omSmall)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(1)

            if let subtitle = result.previewSubtitle {
                Text(subtitle)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
            }

            ForEach(result.previewMeta, id: \.self) { item in
                Text(item)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
            }

            if !result.tags.isEmpty {
                FitnessChipRow(chips: result.tags)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

private struct FitnessResultCard: View {
    let result: FitnessResultSummary
    let provider: String?

    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(result.name)
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(3)

            if let subtitle = result.fullSubtitle {
                Text(subtitle)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(3)
            }

            if !result.meta.isEmpty {
                VStack(alignment: .leading, spacing: .spacing1) {
                    ForEach(result.meta, id: \.self) { item in
                        Text(item)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(1)
                    }
                }
            }

            if !result.tags.isEmpty {
                FitnessChipRow(chips: result.tags)
            }

            if let provider, let url = result.url.flatMap(URL.init(string:)) {
                Button {
                    openURL(url)
                } label: {
                    Text(AppStrings.openOnProvider(provider))
                        .font(.omSmall)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.buttonPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
                .padding(.top, .spacing2)
            }
        }
        .padding(.spacing5)
        .frame(maxWidth: .infinity, minHeight: 160, alignment: .topLeading)
        .background(Color.grey0)
        .overlay(
            RoundedRectangle(cornerRadius: .radius5)
                .stroke(Color.grey20, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .shadow(color: .black.opacity(0.08), radius: 16, x: 0, y: 4)
    }
}

private struct FitnessChipRow: View {
    let chips: [String]

    var body: some View {
        HStack(spacing: .spacing2) {
            ForEach(chips, id: \.self) { chip in
                Text(chip)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
                    .padding(.horizontal, .spacing3)
                    .padding(.vertical, .spacing1)
                    .overlay(Capsule().stroke(Color.grey30, lineWidth: 1))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct FitnessSearchGroup {
    let provider: String
    let query: String?
    let summary: String?
    let error: String?
    let resultCount: Int
    let filters: [String: Any]
    let results: [FitnessResultSummary]

    init(data: [String: AnyCodable]) {
        let rawResults = EmbedFieldReader.dictionaryArray(data, key: "results")
        let firstGroup = rawResults.first ?? [:]
        let hasGroupedResults = firstGroup["results"] is [Any]
        let normalizedResults = hasGroupedResults
            ? firstGroup.dictionaryArray("results")
            : (rawResults.isEmpty ? EmbedFieldReader.dictionaryArray(data, key: "preview_results") : rawResults)
        let explicitFilters = hasGroupedResults ? firstGroup.dictionary("filters") : data.dictionary("filters")
        var fallbackFilters: [String: Any] = [:]
        for (key, sourceKeys) in [
            ("address", ["address", "location"]),
            ("city", ["city"]),
            ("radius_km", ["radius_km"]),
            ("plan", ["plan"]),
            ("attendance_mode", ["attendance_mode"])
        ] {
            if let value = EmbedFieldReader.string(data, keys: sourceKeys) {
                fallbackFilters[key] = value
            }
        }

        provider = (hasGroupedResults ? firstGroup.string("provider") : nil)
            ?? EmbedFieldReader.string(data, keys: ["provider"])
            ?? "Urban Sports Club"
        query = EmbedFieldReader.string(data, keys: ["query", "location", "address", "city", "title"])
        summary = (hasGroupedResults ? firstGroup.string("summary") : nil)
            ?? EmbedFieldReader.string(data, keys: ["summary"])
        error = (hasGroupedResults ? firstGroup.string("error") : nil)
            ?? EmbedFieldReader.string(data, keys: ["error"])
        resultCount = (hasGroupedResults ? firstGroup.int("result_count") : nil)
            ?? EmbedFieldReader.int(data, keys: ["result_count"])
            ?? normalizedResults.count
        filters = explicitFilters.isEmpty ? fallbackFilters : explicitFilters
        results = normalizedResults.enumerated().map { index, item in
            FitnessResultSummary(index: index, data: item)
        }
    }

    var chips: [String] {
        [
            filters.chip("radius_km", suffix: " km"),
            filters.chip("plan"),
            filters.chip("attendance_mode")
        ].compactMap { $0 }
    }
}

private struct FitnessResultSummary: Identifiable {
    let id: String
    let name: String
    let venueName: String?
    let address: String?
    let date: String?
    let timeRange: String?
    let distanceKm: String?
    let spotsDisplay: String?
    let plansRequired: [String]?
    let disciplines: [String]?
    let url: String?
    let skillId: String?

    init(index: Int, data: [String: Any]) {
        id = data.string("id") ?? "fitness-result-\(index)"
        name = data.string("name") ?? data.string("venue_name") ?? id
        venueName = data.string("venue_name")
        address = data.string("address")
            ?? data.string("venue_address")
            ?? [data.string("street"), data.string("postal_code"), data.string("city")]
                .compactMap { $0 }
                .joined(separator: ", ")
                .nilIfEmpty
        date = data.string("date")
        timeRange = data.string("time_range")
        distanceKm = data.distance("distance_km")
        spotsDisplay = data.string("spots_display")
        plansRequired = data.stringArray("plans_required")
        disciplines = data.stringArray("disciplines")
        url = data.string("detail_url") ?? data.string("url") ?? data.string("venue_url")
        skillId = data.string("skill_id") ?? data.string("app_skill_id")
    }

    var previewSubtitle: String? {
        if skillId == "search_classes" {
            return [dateTimeText, venueName].compactMap { $0 }.joined(separator: " · ").nilIfEmpty
        }
        return address ?? venueName
    }

    var fullSubtitle: String? {
        [venueName, address].compactMap { $0 }.joined(separator: "\n").nilIfEmpty
    }

    var meta: [String] {
        [
            dateTimeText,
            distanceText,
            spotsDisplay
        ].compactMap { $0 }
    }

    var previewMeta: [String] {
        [distanceText, spotsDisplay].compactMap { $0 }
    }

    var tags: [String] {
        (disciplines ?? []) + (plansRequired ?? [])
    }

    private var dateTimeText: String? {
        [date, timeRange].compactMap { $0 }.joined(separator: " ").nilIfEmpty
    }

    private var distanceText: String? {
        guard let distanceKm, let value = Double(distanceKm) else { return distanceKm }
        return Measurement(value: value, unit: UnitLength.kilometers).formatted(
            .measurement(width: .abbreviated, usage: .road)
        )
    }
}

private extension Dictionary where Key == String, Value == Any {
    func string(_ key: String) -> String? {
        if let value = self[key] as? String, !value.isEmpty { return value }
        if let value = self[key] as? Int { return String(value) }
        if let value = self[key] as? Double { return String(value) }
        return nil
    }

    func int(_ key: String) -> Int? {
        if let value = self[key] as? Int { return value }
        if let value = self[key] as? String { return Int(value) }
        return nil
    }

    func double(_ key: String) -> Double? {
        if let value = self[key] as? Double { return value }
        if let value = self[key] as? Int { return Double(value) }
        if let value = self[key] as? String { return Double(value) }
        return nil
    }

    func dictionary(_ key: String) -> [String: Any] {
        if let value = self[key] as? [String: Any] { return value }
        if let value = self[key] as? [String: AnyCodable] { return value.mapValues(\.value) }
        return [:]
    }

    func dictionaryArray(_ key: String) -> [[String: Any]] {
        if let value = self[key] as? [[String: Any]] { return value }
        if let value = self[key] as? [Any] { return value.compactMap { $0 as? [String: Any] } }
        return []
    }

    func stringArray(_ key: String) -> [String]? {
        if let value = self[key] as? [String] { return value }
        if let value = self[key] as? String {
            let strings = value.split(separator: "|").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            return strings.isEmpty ? nil : strings
        }
        if let value = self[key] as? [Any] {
            let strings = value.compactMap { $0 as? String }
            return strings.isEmpty ? nil : strings
        }
        return nil
    }

    func distance(_ key: String) -> String? {
        if let value = self[key] as? Double { return String(format: "%.1f", value) }
        if let value = self[key] as? Int { return String(value) }
        return string(key)
    }

    func chip(_ key: String, prefix: String = "", suffix: String = "") -> String? {
        guard let value = string(key), !value.isEmpty else { return nil }
        return "\(prefix)\(value)\(suffix)"
    }
}

private extension Dictionary where Key == String, Value == AnyCodable {
    func dictionary(_ key: String) -> [String: Any] {
        if let value = self[key]?.value as? [String: Any] { return value }
        if let value = self[key]?.value as? [String: AnyCodable] { return value.mapValues(\.value) }
        return [:]
    }
}

private extension AppStrings {
    static func calendarSkillTitle(_ skillId: String) -> String {
        let key: String
        switch skillId {
        case "create-event": key = "app_skills.calendar.create_event"
        case "update-event": key = "app_skills.calendar.update_event"
        case "delete-event": key = "app_skills.calendar.delete_event"
        default: key = "app_skills.calendar.get_events"
        }
        return LocalizationManager.shared.text(key)
    }

    static var rainRadar: String { LocalizationManager.shared.text("apps.weather.rain_radar") }
    static var rainRadarNoRain: String { LocalizationManager.shared.text("embeds.weather.rain_radar.no_rain") }
    static var rainRadarUnavailable: String { LocalizationManager.shared.text("embeds.weather.rain_radar.unavailable") }
    static var rainRadarPeak: String { LocalizationManager.shared.text("embeds.weather.rain_radar.peak") }
    static var rainRadarAtLocation: String { LocalizationManager.shared.text("embeds.weather.rain_radar.at_location") }
    static var rainRadarPlay: String { LocalizationManager.shared.text("embeds.weather.rain_radar.play") }
    static var rainRadarPause: String { LocalizationManager.shared.text("embeds.weather.rain_radar.pause") }

    static func rainRadarFrameCount(_ count: Int) -> String {
        "\(count) \(LocalizationManager.shared.text("embeds.weather.rain_radar.frames"))"
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
