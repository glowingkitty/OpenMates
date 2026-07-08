// App skill use embed renderer — renders parent skill executions and their child
// result previews inside the unified embed shell.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/AppSkillUseRenderer.ts
//          frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// CSS:     frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

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
        } else if isFitnessSearchSkill {
            return AnyView(FitnessSearchEmbedRenderer(embed: embed, data: data, mode: .preview))
        } else if appId == "travel", skillId == "search_connections" {
            return AnyView(TravelSearchEmbedRenderer(embed: embed, data: data, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "travel", skillId == "search_stays" {
            return AnyView(TravelStaysEmbedRenderer(embed: embed, data: data, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "travel", skillId == "price_calendar" {
            return AnyView(TravelPriceCalendarEmbedRenderer(data: data, mode: .preview))
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
        } else if isFitnessSearchSkill {
            FitnessSearchEmbedRenderer(embed: embed, data: data, mode: .fullscreen)
        } else if appId == "travel", skillId == "search_connections" {
            TravelSearchEmbedRenderer(embed: embed, data: data, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "travel", skillId == "search_stays" {
            TravelStaysEmbedRenderer(embed: embed, data: data, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "travel", skillId == "price_calendar" {
            TravelPriceCalendarEmbedRenderer(data: data, mode: .fullscreen)
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

private struct FitnessResultCard: View {
    let result: FitnessResultSummary
    let provider: String

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

            if let plans = result.plansRequired, !plans.isEmpty {
                FitnessChipRow(chips: [plans.joined(separator: ", ")])
            }

            if let url = result.url.flatMap(URL.init(string:)) {
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
        let firstGroup = EmbedFieldReader.dictionaryArray(data, key: "results").first ?? [:]
        provider = firstGroup.string("provider") ?? EmbedFieldReader.string(data, keys: ["provider"]) ?? "Urban Sports Club"
        query = EmbedFieldReader.string(data, keys: ["query", "title"])
        summary = firstGroup.string("summary")
        error = firstGroup.string("error")
        resultCount = firstGroup.int("result_count") ?? firstGroup.dictionaryArray("results").count
        filters = firstGroup.dictionary("filters")
        results = firstGroup.dictionaryArray("results").enumerated().map { index, item in
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
    let url: String?

    init(index: Int, data: [String: Any]) {
        id = data.string("id") ?? "fitness-result-\(index)"
        name = data.string("name") ?? data.string("venue_name") ?? id
        venueName = data.string("venue_name")
        address = data.string("address") ?? data.string("venue_address")
        date = data.string("date")
        timeRange = data.string("time_range")
        distanceKm = data.distance("distance_km")
        spotsDisplay = data.string("spots_display")
        plansRequired = data.stringArray("plans_required")
        url = data.string("url") ?? data.string("detail_url")
    }

    var previewSubtitle: String? {
        venueName ?? dateTimeText ?? distanceKm.map { "\($0) km" }
    }

    var fullSubtitle: String? {
        [venueName, address].compactMap { $0 }.joined(separator: "\n").nilIfEmpty
    }

    var meta: [String] {
        [
            dateTimeText,
            distanceKm.map { "\($0) km" },
            spotsDisplay
        ].compactMap { $0 }
    }

    private var dateTimeText: String? {
        [date, timeRange].compactMap { $0 }.joined(separator: " ").nilIfEmpty
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

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
