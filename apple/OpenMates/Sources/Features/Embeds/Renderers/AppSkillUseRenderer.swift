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
        embed.appId ?? data["app_id"]?.value as? String ?? "web"
    }

    private var skillId: String {
        embed.skillId ?? data["skill_id"]?.value as? String ?? "search"
    }

    private var skillTitle: String {
        switch (appId, skillId) {
        case ("web", "search"), ("news", "search"): return "Search"
        case ("images", "search"), ("videos", "search"): return "Search"
        case ("code", "get_docs"): return "Docs"
        case ("web", "read"): return "Read"
        case ("math", "calculate"): return "Calculate"
        case ("reminder", "set-reminder"): return "Reminder"
        default:
            return EmbedType(rawValue: embed.type)?.displayName ?? skillId.replacingOccurrences(of: "_", with: " ")
        }
    }

    private var childEmbeds: [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return uniqueEmbeds(explicit) }
        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { $0.id < $1.id }
        if !parented.isEmpty { return uniqueEmbeds(parented) }

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
                default:
                    return child.appId == appId
                }
            }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) })
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
        if appId == "images", !childEmbeds.isEmpty {
            AnyView(imagesSearchPreview)
        } else {
            AnyView(textSearchPreview)
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

    private var fullscreen: some View {
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
                Text(childEmbeds.isEmpty ? "" : "\(childEmbeds.count) results")
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

                let remaining = max(0, childEmbeds.count - min(3, faviconEmbeds.count))
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
            return firstString(in: raw, keys: ["favicon", "favicon_url", "meta_url_favicon"]) != nil
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
        let favicon = firstString(in: raw, keys: ["favicon", "favicon_url", "meta_url_favicon"])
        return ZStack {
            Circle().fill(Color.grey0)
            if let favicon, let url = URL(string: favicon) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().aspectRatio(contentMode: .fill)
                    default:
                        AppIconView(appId: "web", size: 13)
                    }
                }
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
        let imageURL = firstString(in: raw, keys: [
            "thumbnail_url", "thumbnail", "image_url", "image", "thumbnail_original", "meta_url_favicon", "favicon"
        ])
        if let imageURL, let url = URL(string: imageURL) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().aspectRatio(contentMode: .fill)
                default:
                    fallbackThumb(for: child)
                }
            }
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
        firstString(["thumbnail_original", "thumbnail_url", "preview_image_url", "image_url", "image", "url"])
    }
    private var favicon: String? {
        firstString(["meta_url_favicon", "favicon", "favicon_url"])
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
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().aspectRatio(contentMode: .fill)
                    default:
                        Icon(appId == "images" ? "image" : "web", size: 20)
                            .foregroundStyle(Color.grey70)
                    }
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
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().aspectRatio(contentMode: .fill)
                    default:
                        Color.grey25
                    }
                }
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
        firstString(["image_url", "thumbnail_url", "thumbnail_original", "image"])
    }
    private var favicon: String? { firstString(["favicon_url", "favicon", "meta_url_favicon"]) }

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 0) {
                ZStack(alignment: .topLeading) {
                    if let imageURL, let url = URL(string: imageURL) {
                        AsyncImage(url: url) { phase in
                            switch phase {
                            case .success(let image):
                                image.resizable().aspectRatio(contentMode: .fill)
                            default:
                                Color.grey20.overlay(Icon("image", size: 28).foregroundStyle(Color.grey40))
                            }
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
                        AsyncImage(url: url) { phase in
                            switch phase {
                            case .success(let image):
                                image.resizable().aspectRatio(contentMode: .fill)
                            default:
                                EmptyView()
                            }
                        }
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
