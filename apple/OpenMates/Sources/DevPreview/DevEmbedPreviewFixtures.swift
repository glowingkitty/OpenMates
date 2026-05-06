// Debug fixtures for native embed preview galleries.
// Mirrors the static mock-data idea used by the web /dev/preview/embeds pages.
// Starts with the web and images apps so simulator screenshots can compare
// native SwiftUI renderers against the existing Svelte preview pages.
// This file is compiled in Debug builds only.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/web/WebsiteEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/web/WebReadEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImageGenerateEmbedPreview.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import Foundation

enum DevEmbedPreviewApp: String, CaseIterable, Identifiable {
    case web
    case images

    var id: String { rawValue }

    var title: String {
        switch self {
        case .web: return "Web"
        case .images: return "Images"
        }
    }
}

struct DevEmbedPreviewSkill: Identifiable {
    let id: String
    let label: String
    let primaryEmbed: EmbedRecord
    let childEmbeds: [EmbedRecord]

    var allRecords: [String: EmbedRecord] {
        ([primaryEmbed] + childEmbeds).reduce(into: [:]) { records, embed in
            records[embed.id] = embed
        }
    }
}

enum DevEmbedPreviewFixtures {
    static func skills(for app: DevEmbedPreviewApp) -> [DevEmbedPreviewSkill] {
        switch app {
        case .web:
            return [
                webSearchSkill,
                webReadSkill
            ]
        case .images:
            return [
                imageSearchSkill,
                imageGenerateSkill
            ]
        }
    }

    private static var webSearchSkill: DevEmbedPreviewSkill {
        let children = [
            record(
                id: "dev-web-result-openmates",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://openmates.org",
                    "title": "OpenMates",
                    "description": "Private, useful AI companions with encrypted chat, apps, and skills in one calm workspace.",
                    "image": "https://images.unsplash.com/photo-1497366754035-f200968a6e72?w=900&q=80",
                    "page_age": "2026-04-18",
                    "extra_snippets": [
                        "OpenMates combines chat, apps, and user-owned memory.",
                        "Native and web interfaces share the same design language."
                    ]
                ]
            ),
            record(
                id: "dev-web-result-docs",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://docs.openmates.org/design",
                    "title": "OpenMates Design System",
                    "description": "Generated tokens, shared previews, and component documentation keep the product UI consistent.",
                    "image": "https://images.unsplash.com/photo-1518005020951-eccb494ad742?w=900&q=80",
                    "page_age": "2026-04-21",
                    "extra_snippets": [
                        "Preview pages are the visual source of truth for components.",
                        "Token generation keeps SwiftUI and Svelte aligned."
                    ]
                ]
            )
        ]

        return DevEmbedPreviewSkill(
            id: "web-search",
            label: "Search",
            primaryEmbed: record(
                id: "dev-web-search",
                type: EmbedType.webSearch.rawValue,
                appId: "web",
                skillId: "search",
                data: [
                    "query": "OpenMates design system",
                    "provider": "Brave",
                    "result_count": children.count
                ],
                embedIds: children.map(\.id).joined(separator: "|")
            ),
            childEmbeds: children
        )
    }

    private static var webReadSkill: DevEmbedPreviewSkill {
        DevEmbedPreviewSkill(
            id: "web-read",
            label: "Read",
            primaryEmbed: record(
                id: "dev-web-read",
                type: EmbedType.webRead.rawValue,
                appId: "web",
                skillId: "read",
                data: [
                    "title": "Design tokens as a shared contract",
                    "url": "https://openmates.org/blog/design-tokens",
                    "word_count": 1280,
                    "content": "OpenMates treats the Svelte component previews as the design source of truth. Native renderers consume generated tokens and mirror the same embed data, allowing visual checks in the simulator."
                ]
            ),
            childEmbeds: []
        )
    }

    private static var imageSearchSkill: DevEmbedPreviewSkill {
        let children = [
            record(
                id: "dev-images-result-studio",
                type: EmbedType.imagesImageResult.rawValue,
                appId: "images",
                data: [
                    "title": "Warm desk setup",
                    "image_url": "https://images.unsplash.com/photo-1497366811353-6870744d04b2?w=1000&q=80",
                    "thumbnail_url": "https://images.unsplash.com/photo-1497366811353-6870744d04b2?w=360&q=80",
                    "source_page_url": "https://unsplash.com"
                ]
            ),
            record(
                id: "dev-images-result-workspace",
                type: EmbedType.imagesImageResult.rawValue,
                appId: "images",
                data: [
                    "title": "Colorful workspace",
                    "image_url": "https://images.unsplash.com/photo-1524758631624-e2822e304c36?w=1000&q=80",
                    "thumbnail_url": "https://images.unsplash.com/photo-1524758631624-e2822e304c36?w=360&q=80",
                    "source_page_url": "https://unsplash.com"
                ]
            )
        ]

        return DevEmbedPreviewSkill(
            id: "images-search",
            label: "Search",
            primaryEmbed: record(
                id: "dev-images-search",
                type: EmbedType.imagesSearch.rawValue,
                appId: "images",
                skillId: "search",
                data: [
                    "query": "friendly workspace photography",
                    "provider": "Brave",
                    "result_count": children.count
                ],
                embedIds: children.map(\.id).joined(separator: "|")
            ),
            childEmbeds: children
        )
    }

    private static var imageGenerateSkill: DevEmbedPreviewSkill {
        DevEmbedPreviewSkill(
            id: "images-generate",
            label: "Generate",
            primaryEmbed: record(
                id: "dev-images-generate",
                type: EmbedType.imagesGenerate.rawValue,
                appId: "images",
                skillId: "generate",
                data: [
                    "prompt": "A friendly desktop assistant interface rendered as a polished product mockup, bright and practical.",
                    "model": "gpt-image-1"
                ]
            ),
            childEmbeds: []
        )
    }

    private static func record(
        id: String,
        type: String,
        appId: String?,
        skillId: String? = nil,
        status: EmbedStatus = .finished,
        data: [String: Any],
        parentEmbedId: String? = nil,
        embedIds: String? = nil
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: status,
            data: .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            createdAt: "2026-04-20T12:00:00Z"
        )
    }
}
#endif
