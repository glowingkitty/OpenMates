// Debug fixtures for native embed preview galleries.
// Mirrors the deployed Svelte /dev/preview/embeds app showcase sections so
// Xcode simulator screenshots can be compared against app.dev.openmates.org.
// This file is compiled in Debug builds only.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/dev/preview/embeds/[app=embedApp]/+page.svelte
//          frontend/packages/ui/src/components/embeds/web/*.preview.ts
//          frontend/packages/ui/src/components/embeds/images/*.preview.ts
//          frontend/packages/ui/src/components/embeds/travel/*.preview.ts
//          frontend/packages/ui/src/components/embeds/events/*.preview.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import Foundation

enum DevEmbedPreviewApp: String, CaseIterable, Identifiable {
    case audio
    case business
    case calendar
    case code
    case design
    case diagrams
    case docs
    case electronics
    case fitness
    case finance
    case health
    case home
    case hosting
    case web
    case images
    case mail
    case maps
    case math
    case mindmaps
    case models3d
    case music
    case news
    case nutrition
    case pdf
    case reminder
    case sheets
    case shopping
    case socialMedia = "social_media"
    case tasks
    case travel
    case videos
    case weather
    case events
    case workflows

    var id: String { rawValue }

    var title: String {
        switch self {
        case .audio: return "Audio"
        case .business: return "Business"
        case .calendar: return "Calendar"
        case .code: return "Code"
        case .design: return "Design"
        case .diagrams: return "Diagrams"
        case .docs: return "Docs"
        case .electronics: return "Electronics"
        case .fitness: return "Fitness"
        case .finance: return "Finance"
        case .health: return "Health"
        case .home: return "Home"
        case .hosting: return "Hosting"
        case .web: return "Web"
        case .images: return "Images"
        case .mail: return "Mail"
        case .maps: return "Maps"
        case .math: return "Math"
        case .mindmaps: return "Mind Maps"
        case .models3d: return "3D Models"
        case .music: return "Music"
        case .news: return "News"
        case .nutrition: return "Nutrition"
        case .pdf: return "PDF"
        case .reminder: return "Reminder"
        case .sheets: return "Sheets"
        case .shopping: return "Shopping"
        case .socialMedia: return "Social"
        case .tasks: return "Tasks"
        case .travel: return "Travel"
        case .videos: return "Videos"
        case .weather: return "Weather"
        case .events: return "Events"
        case .workflows: return "Workflows"
        }
    }
}

struct DevEmbedPreviewSkill: Identifiable {
    let id: String
    let label: String
    let primaryEmbed: EmbedRecord
    let childEmbeds: [EmbedRecord]
    let allRecords: [String: EmbedRecord]
}

enum DevEmbedPreviewSurface: String, CaseIterable {
    case preview, fullscreen, inline, quote
    case groupSmall = "group-small"
    case groupLarge = "group-large"
}

/// Canonical capture requests remain separate from the component-preview parser.
/// Named variants belong to each embed renderer, not the legacy gallery route.
struct DevEmbedPreviewRequest: Equatable {
    enum Direction: String { case ltr, rtl }
    let registryKey: String
    let surface: DevEmbedPreviewSurface
    let variant: String
    let direction: Direction

    static func parse(arguments: [String]) -> Self? {
        let flags = ["--embed-registry-key", "--embed-surface", "--embed-variant", "--embed-direction"]
        guard flags.allSatisfy({ flag in arguments.filter { $0 == flag }.count <= 1 }) else { return nil }
        func value(_ flag: String) -> String? {
            guard let index = arguments.firstIndex(of: flag),
                  arguments.indices.contains(index + 1),
                  !arguments[index + 1].hasPrefix("--") else { return nil }
            return arguments[index + 1]
        }
        guard flags.allSatisfy({ !arguments.contains($0) || value($0) != nil }) else { return nil }
        guard let key = value("--embed-registry-key"),
              !key.isEmpty,
              let surface = value("--embed-surface").flatMap(DevEmbedPreviewSurface.init(rawValue:)),
              let direction = Direction(rawValue: value("--embed-direction") ?? "ltr") else { return nil }
        return Self(registryKey: key, surface: surface,
                    variant: value("--embed-variant") ?? "default", direction: direction)
    }
}

struct DevEmbedPreviewVariant: Identifiable {
    let name: String
    let skill: DevEmbedPreviewSkill
    var id: String { name }
    var isDataVariant: Bool { !["error", "mobile", "processing"].contains(name) }
}

enum DevEmbedPreviewFixtures {
    private struct WebVariant: Decodable {
        let name: String
        let props: [String: AnyCodable]
    }
    private struct ShowcaseMetadata: Decodable {
        let inlineLinkText: String
        let quoteText: String
        let isAppSkill: Bool
    }
    private struct WebVariantSnapshot: Decodable {
        let preview: [String: String]
        let fullscreen: [String: String]
        let metadata: [String: ShowcaseMetadata]
        let availableFiles: [String]
        let variants: [String: [WebVariant]]
    }

    private static let webVariants = try! JSONDecoder().decode(
        WebVariantSnapshot.self, from: Data(webVariantJSON.utf8))

    static func variants(for skill: DevEmbedPreviewSkill, fullscreen: Bool = false) -> [DevEmbedPreviewVariant] {
        if HostingEmbedKind.isSearch(skill.primaryEmbed) || HostingEmbedKind.isDomain(skill.primaryEmbed) {
            return DevHostingEmbedFixtures.variants(skill, fullscreen: fullscreen)
        }
        let paths = fullscreen ? webVariants.fullscreen : webVariants.preview
        var component = paths[skill.primaryEmbed.type]
        if fullscreen, let fullscreenPath = component, !webVariants.availableFiles.contains(fullscreenPath) {
            component = webVariants.preview[skill.primaryEmbed.type]
        }
        let web = component.flatMap { webVariants.variants[$0] } ?? []
        var result = [DevEmbedPreviewVariant(name: "default", skill: skill)] + web.map {
            DevEmbedPreviewVariant(name: $0.name, skill: applying($0, to: skill, fullscreen: fullscreen))
        }
        // Supplemental valid preview; keep the web's empty processing default intact.
        if !fullscreen, skill.primaryEmbed.type == EmbedType.mindmapsMindmap.rawValue,
           let finished = fullscreenSkill(forRegistryKey: EmbedType.mindmapsMindmap.rawValue) {
            result.append(DevEmbedPreviewVariant(name: "finished", skill: finished))
        }
        // Supplemental fullscreen regressions exercise the production shared
        // template with both coordinates and an image. Canonical defaults stay
        // unchanged and local data URLs need no provider/server state.
        if fullscreen, skill.primaryEmbed.type == EmbedType.maps.rawValue {
            let staticURL = mapsPlacePreview.primaryEmbed.rawData?["map_image_url"]?.value as? String
            for (name, imageURL) in [
                ("staticWithCoordinates", staticURL),
                ("invalidStaticWithCoordinates", "data:image/svg+xml,%3Csvg%3E%3Cscript%3Ealert(1)%3C/script%3E%3C/svg%3E")
            ] {
                guard let imageURL else { continue }
                var payload = skill.primaryEmbed.rawData?.mapValues(\.value) ?? [:]
                payload["map_image_url"] = imageURL
                let variant = WebVariant(name: name, props: ["data": AnyCodable(["decodedContent": payload])])
                result.append(DevEmbedPreviewVariant(name: name,
                    skill: applying(variant, to: skill, fullscreen: true)))
            }
        }
        if skill.primaryEmbed.type == EmbedType.codeCode.rawValue {
            for (name, filename) in [("markdown-absent-filename", NSNull() as Any),
                                     ("markdown-json-null", NSNull() as Any),
                                     ("markdown-string-null", "null" as Any),
                                     ("markdown-blank-filename", "  " as Any),
                                     ("markdown-real-filename", "docs/null.md" as Any)] {
                var payload: [String: Any] = ["code": "# Notes\n\nA Markdown document.", "language": "markdown"]
                if name != "markdown-absent-filename" { payload["filename"] = filename }
                let embed = record(id: "preview-code-\(name)", type: EmbedType.codeCode.rawValue, appId: "code", data: payload)
                result.append(.init(name: name, skill: self.skill(id: embed.id, label: "Code", primary: embed)))
            }
        }
        if fullscreen, skill.primaryEmbed.type == EmbedType.sheetsSheet.rawValue {
            let rows = (0..<300).map { "| Row \($0) | Value \($0) |" }.joined(separator: "\n")
            let embed = record(id: "preview-sheet-sticky-long", type: EmbedType.sheetsSheet.rawValue, appId: "sheets",
                data: ["title": "Scrollable sheet", "table": "| Name | Value |\n| --- | --- |\n" + rows])
            result.append(.init(name: "sticky-long", skill: self.skill(id: embed.id, label: "Sheet", primary: embed)))
        }
        if TravelSearchPresentation.isSearch(skill.primaryEmbed) {
            for name in ["zero-provider-empty", "zero-provider-grouped", "zero-provider-query"] {
                result.append(.init(name: name, skill: travelZeroProvider(name)))
            }
        }
        return result
    }

    static func dataVariants(for skill: DevEmbedPreviewSkill, fullscreen: Bool = false) -> [DevEmbedPreviewVariant] {
        variants(for: skill, fullscreen: fullscreen).filter(\.isDataVariant)
    }

    static func supportsLargeGroup(_ skill: DevEmbedPreviewSkill) -> Bool {
        let metadata = webVariants.preview[skill.primaryEmbed.type].flatMap { webVariants.metadata[$0] }
        let isAppSkill = metadata?.isAppSkill ?? (skill.primaryEmbed.isAppSkillUse || skill.primaryEmbed.type.hasPrefix("app:"))
        return !isAppSkill && dataVariants(for: skill).count > 1
    }

    static func fixture(for request: DevEmbedPreviewRequest) -> DevEmbedPreviewSkill? {
        let fullscreen = request.surface == .fullscreen
        guard let base = fullscreen ? fullscreenSkill(forRegistryKey: request.registryKey)
            : skill(forRegistryKey: request.registryKey) else { return nil }
        guard request.surface != .groupLarge || supportsLargeGroup(base) else { return nil }
        return variants(for: base, fullscreen: fullscreen).first { $0.name == request.variant }?.skill
    }

    static func inlineText(for skill: DevEmbedPreviewSkill) -> String {
        if let path = webVariants.preview[skill.primaryEmbed.type], let metadata = webVariants.metadata[path] {
            return metadata.inlineLinkText
        }
        return displayText(skill.primaryEmbed, keys: ["title", "name", "filename", "query"])
    }

    static func quoteText(for skill: DevEmbedPreviewSkill) -> String {
        if let path = webVariants.preview[skill.primaryEmbed.type], let metadata = webVariants.metadata[path] {
            return metadata.quoteText
        }
        return displayText(skill.primaryEmbed, keys: ["description", "summary", "title", "name", "query"])
    }

    private static func displayText(_ embed: EmbedRecord, keys: [String]) -> String {
        for key in keys {
            if let value = embed.rawData?[key]?.value as? String, !value.isEmpty { return value }
        }
        return EmbedType(rawValue: embed.type)?.displayName ?? embed.type
    }

    /// Convert the same merged props the web showcase supplies into production
    /// raw records. Keep both spellings for nested provider/artifact contracts.
    private static func applying(_ variant: WebVariant, to base: DevEmbedPreviewSkill, fullscreen: Bool) -> DevEmbedPreviewSkill {
        let props = variant.props.mapValues(\.value)
        var payload = props
        if let data = props["data"] as? [String: Any] {
            payload = data["decodedContent"] as? [String: Any] ?? data
        } else if fullscreen {
            for key in ["product", "component", "recipe"] {
                if let entity = props[key] as? [String: Any] { payload = entity; break }
            }
        }
        var raw = normalizeWebProps(payload)
        let aliases = ["codeContent": "code", "tableContent": "table", "image": "preview_image_url",
                       "favicon": "favicon_url", "transcriptOriginal": "transcript_original"]
        for (source, target) in aliases {
            if let value = raw[source] { raw[target] = value }
        }
        let primary = base.primaryEmbed
        if primary.isAppSkillUse {
            raw["type"] = "app_skill_use"
            raw["app_id"] = primary.appId
            raw["skill_id"] = primary.skillId
        }
        let id = (props["id"] as? String ?? props["embedId"] as? String ?? primary.id) + "-variant-" + variant.name
        let status = (props["status"] as? String ?? payload["status"] as? String).flatMap(EmbedStatus.init(rawValue:)) ?? primary.status
        let rows = raw["results"] as? [[String: Any]]
        let children: [EmbedRecord]
        if let rows, let childType = base.childEmbeds.first?.type {
            children = rows.enumerated().map { index, row in
                let childID = "\(id)-result-\(index + 1)"
                var childData = row
                childData["embed_id"] = childID
                return record(id: childID, type: childType, appId: primary.appId, data: childData, parentEmbedId: id)
            }
        } else {
            children = rows == nil ? base.childEmbeds : []
        }
        let embed = record(id: id, type: primary.type, status: status, appId: primary.appId,
                           skillId: primary.skillId, data: raw,
                           embedIds: children.isEmpty ? nil : children.map(\.id).joined(separator: "|"))
        return skill(id: base.id, label: base.label, primary: embed, children: children)
    }

    private static func normalizeWebProps(_ source: [String: Any]) -> [String: Any] {
        var result: [String: Any] = [:]
        for (key, value) in source where key != "isMobile" {
            let normalized = key.reduce(into: "") { output, character in
                if character.isUppercase { output += "_" + character.lowercased() }
                else { output.append(character) }
            }
            let converted: Any
            if let object = value as? [String: Any] { converted = normalizeWebProps(object) }
            else if let objects = value as? [[String: Any]] { converted = objects.map(normalizeWebProps) }
            else if let url = value as? String, url.hasPrefix("/"),
                    ["url", "image", "thumbnail", "favicon"].contains(where: { normalized.contains($0) }) {
                converted = "https://app.dev.openmates.org" + url
            } else { converted = value }
            result[key] = converted
            result[normalized] = converted
        }
        return result
    }

    // Snapshot of named props from the mapped web *.preview.ts files. Defaults
    // stay in the existing hand-aligned fixtures below; functions are omitted.
    // Freshness: scripts/tests/test_apple_embed_gallery_fixtures.py evaluates the
    // web sources through helpers/apple_embed_gallery_web_variants.mjs.
    private static let webVariantJSON = #"""
    {
    "preview":{"recording":"audio/RecordingEmbedPreview.svelte","app:audio:generate":"audio/AudioGenerateEmbedPreview.svelte","app:audio:speak":"audio/AudioGenerateEmbedPreview.svelte","app:business:company_financials":"business/BusinessCompanyFinancialsEmbedPreview.svelte","business-company-financial-result":"business/BusinessCompanyFinancialResultEmbedPreview.svelte","app:calendar:list-calendars":"calendar/CalendarActionEmbedPreview.svelte","app:calendar:get-events":"calendar/CalendarActionEmbedPreview.svelte","app:calendar:create-event":"calendar/CalendarActionEmbedPreview.svelte","app:calendar:update-event":"calendar/CalendarActionEmbedPreview.svelte","app:calendar:delete-event":"calendar/CalendarActionEmbedPreview.svelte","app:code:search_repos":"code/CodeRepoSearchEmbedPreview.svelte","code-repo":"code/CodeRepoEmbedPreview.svelte","app:code:get_docs":"code/CodeGetDocsEmbedPreview.svelte","code-code":"code/CodeEmbedPreview.svelte","code-notebook":"code/NotebookEmbedPreview.svelte","code-application":"code/ApplicationEmbedPreview.svelte","app:design:search_icons":"design/DesignIconSearchEmbedPreview.svelte","design-icon-result":"design/DesignIconResultEmbedPreview.svelte","docs-doc":"docs/DocsEmbedPreview.svelte","electronics-pcb-schematic":"electronics/PcbSchematicEmbedPreview.svelte","app:electronics:search_components":"electronics/ElectronicsSearchEmbedPreview.svelte","electronics-component":"electronics/ElectronicsComponentEmbedPreview.svelte","app:events:search":"events/EventsSearchEmbedPreview.svelte","events-event":"events/EventEmbedPreview.svelte","file-file":"file/FileEmbedPreview.svelte","app:finance:check_accounts":"finance/FinanceCheckAccountsEmbedPreview.svelte","app:fitness:search_locations":"fitness/FitnessSearchEmbedPreview.svelte","fitness-location":"fitness/FitnessResultEmbedPreview.svelte","app:fitness:search_classes":"fitness/FitnessSearchEmbedPreview.svelte","fitness-class":"fitness/FitnessResultEmbedPreview.svelte","app:health:search_appointments":"health/HealthSearchEmbedPreview.svelte","health-appointment":"health/HealthAppointmentEmbedPreview.svelte","app:home:search":"home/HomeSearchEmbedPreview.svelte","home-listing":"home/HomeListingEmbedPreview.svelte","app:images:generate":"images/ImageGenerateEmbedPreview.svelte","app:images:generate_draft":"images/ImageGenerateEmbedPreview.svelte","image":"images/ImageEmbedPreview.svelte","app:images:search":"images/ImagesSearchEmbedPreview.svelte","images-image-result":"images/ImageResultEmbedPreview.svelte","mail-email":"mail/MailEmbedPreview.svelte","app:mail:search":"mail/MailSearchEmbedPreview.svelte","app:maps:search":"maps/MapsSearchEmbedPreview.svelte","maps-place":"maps/MapsLocationEmbedPreview.svelte","maps":"maps/MapsLocationEmbedPreview.svelte","app:math:calculate":"math/MathCalculateEmbedPreview.svelte","math-plot":"math/MathPlotEmbedPreview.svelte","mindmaps-mindmap":"mindmaps/MindMapEmbedPreview.svelte","app:models3d:search":"models3d/Model3DSearchEmbedPreview.svelte","models3d-model-result":"models3d/Model3DResultEmbedPreview.svelte","app:models3d:generate":"models3d/Model3DGenerateEmbedPreview.svelte","app:music:generate":"music/MusicGenerateEmbedPreview.svelte","app:news:search":"news/NewsSearchEmbedPreview.svelte","web-website":"web/WebsiteEmbedPreview.svelte","app:nutrition:search_recipes":"nutrition/NutritionSearchEmbedPreview.svelte","nutrition-recipe":"nutrition/NutritionRecipeEmbedPreview.svelte","pdf":"pdf/PDFEmbedPreview.svelte","app:reminder:set-reminder":"reminder/ReminderEmbedPreview.svelte","app:reminder:list-reminders":"reminder/ReminderEmbedPreview.svelte","app:reminder:cancel-reminder":"reminder/ReminderEmbedPreview.svelte","app:shopping:search_products":"shopping/ShoppingSearchEmbedPreview.svelte","shopping-product":"shopping/ShoppingResultEmbedPreview.svelte","app:social_media:get-posts":"social_media/SocialMediaGetPostsEmbedPreview.svelte","social-media-post":"social_media/SocialMediaPostEmbedPreview.svelte","app:social_media:search":"social_media/SocialMediaSearchEmbedPreview.svelte","app:tasks:create":"tasks/TaskCreateEmbedPreview.svelte","tasks-task":"tasks/TaskEmbedPreview.svelte","app:tasks:search":"tasks/TaskSearchEmbedPreview.svelte","app:travel:search_connections":"travel/TravelSearchEmbedPreview.svelte","travel-connection":"travel/TravelConnectionEmbedPreview.svelte","app:travel:search_stays":"travel/TravelStaysEmbedPreview.svelte","travel-stay":"travel/TravelStayEmbedPreview.svelte","app:travel:price_calendar":"travel/TravelPriceCalendarEmbedPreview.svelte","app:travel:get_flight":"travel/TravelFlightDetailsEmbedPreview.svelte","app:videos:search":"videos/VideosSearchEmbedPreview.svelte","videos-video":"videos/VideoEmbedPreview.svelte","app:videos:get_transcript":"videos/VideoTranscriptEmbedPreview.svelte","app:videos:generate":"videos/VideoGenerateEmbedPreview.svelte","app:videos:create":"videos/VideoCreateEmbedPreview.svelte","app:weather:forecast":"weather/WeatherForecastEmbedPreview.svelte","weather-day":"weather/WeatherDayEmbedPreview.svelte","app:weather:rain_radar":"weather/WeatherRainRadarEmbedPreview.svelte","app:web:search":"web/WebSearchEmbedPreview.svelte","app:web:read":"web/WebReadEmbedPreview.svelte","app:workflows:create-or-modify":"workflows/WorkflowCreateEmbedPreview.svelte","workflows-workflow":"workflows/WorkflowEmbedPreview.svelte","app:workflows:search":"workflows/WorkflowSearchEmbedPreview.svelte","sheets-sheet":"sheets/SheetEmbedPreview.svelte","focus-mode-activation":"focus_mode/FocusModeActivationEmbed.svelte"},
    "fullscreen":{"recording":"audio/RecordingEmbedFullscreen.svelte","app:audio:generate":"audio/AudioGenerateEmbedFullscreen.svelte","app:audio:speak":"audio/AudioGenerateEmbedFullscreen.svelte","app:business:company_financials":"business/BusinessCompanyFinancialsEmbedFullscreen.svelte","business-company-financial-result":"business/BusinessCompanyFinancialResultEmbedFullscreen.svelte","app:calendar:list-calendars":"calendar/CalendarActionEmbedFullscreen.svelte","app:calendar:get-events":"calendar/CalendarActionEmbedFullscreen.svelte","app:calendar:create-event":"calendar/CalendarActionEmbedFullscreen.svelte","app:calendar:update-event":"calendar/CalendarActionEmbedFullscreen.svelte","app:calendar:delete-event":"calendar/CalendarActionEmbedFullscreen.svelte","app:code:search_repos":"code/CodeRepoSearchEmbedFullscreen.svelte","code-repo":"code/CodeRepoEmbedFullscreen.svelte","app:code:get_docs":"code/CodeGetDocsEmbedFullscreen.svelte","code-code":"code/CodeEmbedFullscreen.svelte","code-notebook":"code/NotebookEmbedFullscreen.svelte","code-application":"code/ApplicationEmbedFullscreen.svelte","app:design:search_icons":"design/DesignIconSearchEmbedFullscreen.svelte","design-icon-result":"design/DesignIconResultEmbedFullscreen.svelte","docs-doc":"docs/DocsEmbedFullscreen.svelte","electronics-pcb-schematic":"electronics/PcbSchematicEmbedFullscreen.svelte","app:electronics:search_components":"electronics/ElectronicsSearchEmbedFullscreen.svelte","electronics-component":"electronics/ElectronicsComponentEmbedFullscreen.svelte","app:events:search":"events/EventsSearchEmbedFullscreen.svelte","events-event":"events/EventEmbedFullscreen.svelte","file-file":"file/FileEmbedFullscreen.svelte","app:finance:check_accounts":"finance/FinanceCheckAccountsEmbedFullscreen.svelte","app:fitness:search_locations":"fitness/FitnessSearchEmbedFullscreen.svelte","fitness-location":"fitness/FitnessResultEmbedFullscreen.svelte","app:fitness:search_classes":"fitness/FitnessSearchEmbedFullscreen.svelte","fitness-class":"fitness/FitnessResultEmbedFullscreen.svelte","app:health:search_appointments":"health/HealthSearchEmbedFullscreen.svelte","health-appointment":"health/HealthAppointmentEmbedFullscreen.svelte","app:home:search":"home/HomeSearchEmbedFullscreen.svelte","home-listing":"home/HomeListingEmbedFullscreen.svelte","app:images:generate":"images/ImageGenerateEmbedFullscreen.svelte","app:images:generate_draft":"images/ImageGenerateEmbedFullscreen.svelte","image":"images/ImageEmbedFullscreen.svelte","app:images:search":"images/ImagesSearchEmbedFullscreen.svelte","images-image-result":"images/ImageResultEmbedFullscreen.svelte","mail-email":"mail/MailEmbedFullscreen.svelte","app:mail:search":"mail/MailSearchEmbedFullscreen.svelte","app:maps:search":"maps/MapsSearchEmbedFullscreen.svelte","maps-place":"maps/MapLocationEmbedFullscreen.svelte","maps":"maps/MapsLocationEmbedFullscreen.svelte","app:math:calculate":"math/MathCalculateEmbedFullscreen.svelte","math-plot":"math/MathPlotEmbedFullscreen.svelte","mindmaps-mindmap":"mindmaps/MindMapEmbedFullscreen.svelte","app:models3d:search":"models3d/Model3DSearchEmbedFullscreen.svelte","models3d-model-result":"models3d/Model3DResultEmbedFullscreen.svelte","app:models3d:generate":"models3d/Model3DGenerateEmbedFullscreen.svelte","app:music:generate":"music/MusicGenerateEmbedFullscreen.svelte","app:news:search":"news/NewsSearchEmbedFullscreen.svelte","web-website":"web/WebsiteEmbedFullscreen.svelte","app:nutrition:search_recipes":"nutrition/NutritionSearchEmbedFullscreen.svelte","nutrition-recipe":"nutrition/NutritionRecipeEmbedFullscreen.svelte","pdf":"pdf/PDFEmbedFullscreen.svelte","app:reminder:set-reminder":"reminder/ReminderEmbedFullscreen.svelte","app:reminder:list-reminders":"reminder/ReminderEmbedFullscreen.svelte","app:reminder:cancel-reminder":"reminder/ReminderEmbedFullscreen.svelte","app:shopping:search_products":"shopping/ShoppingSearchEmbedFullscreen.svelte","shopping-product":"shopping/ShoppingResultEmbedFullscreen.svelte","app:social_media:get-posts":"social_media/SocialMediaGetPostsEmbedFullscreen.svelte","social-media-post":"social_media/SocialMediaPostEmbedFullscreen.svelte","app:social_media:search":"social_media/SocialMediaSearchEmbedFullscreen.svelte","app:tasks:create":"tasks/TaskCreateEmbedFullscreen.svelte","tasks-task":"tasks/TaskEmbedFullscreen.svelte","app:tasks:search":"tasks/TaskSearchEmbedFullscreen.svelte","app:travel:search_connections":"travel/TravelSearchEmbedFullscreen.svelte","travel-connection":"travel/TravelConnectionEmbedFullscreen.svelte","app:travel:search_stays":"travel/TravelStaysEmbedFullscreen.svelte","travel-stay":"travel/TravelStayEmbedFullscreen.svelte","app:travel:price_calendar":"travel/TravelPriceCalendarEmbedFullscreen.svelte","app:travel:get_flight":"travel/TravelFlightDetailsEmbedFullscreen.svelte","app:videos:search":"videos/VideosSearchEmbedFullscreen.svelte","videos-video":"videos/VideoEmbedFullscreen.svelte","app:videos:get_transcript":"videos/VideoTranscriptEmbedFullscreen.svelte","app:videos:generate":"videos/VideoGenerateEmbedFullscreen.svelte","app:videos:create":"videos/VideoCreateEmbedFullscreen.svelte","app:weather:forecast":"weather/WeatherForecastEmbedFullscreen.svelte","weather-day":"weather/WeatherDayEmbedFullscreen.svelte","app:weather:rain_radar":"weather/WeatherRainRadarEmbedFullscreen.svelte","app:web:search":"web/WebSearchEmbedFullscreen.svelte","app:web:read":"web/WebReadEmbedFullscreen.svelte","app:workflows:create-or-modify":"workflows/WorkflowCreateEmbedFullscreen.svelte","workflows-workflow":"workflows/WorkflowEmbedFullscreen.svelte","app:workflows:search":"workflows/WorkflowSearchEmbedFullscreen.svelte","sheets-sheet":"sheets/SheetEmbedFullscreen.svelte","focus-mode-activation":"focus_mode/FocusModeActivationEmbedFullscreen.svelte"},
    "metadata":{"code/CodeEmbedPreview.svelte":{"inlineLinkText":"MyComponent.svelte","quoteText":"let count = $state(0); — Svelte 5 reactive state declaration","isAppSkill":false},"code/CodeGetDocsEmbedPreview.svelte":{"inlineLinkText":"Svelte $state documentation","quoteText":"The $state rune declares reactive state that updates the UI automatically.","isAppSkill":true},"docs/DocsEmbedPreview.svelte":{"inlineLinkText":"architecture.docx","quoteText":"PostgreSQL serves as the primary data store, managed through Directus CMS.","isAppSkill":false},"web/WebSearchEmbedPreview.svelte":{"inlineLinkText":"Best restaurants in Berlin","quoteText":"Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors.","isAppSkill":true},"web/WebReadEmbedPreview.svelte":{"inlineLinkText":"Migrating from Svelte 4 to 5","quoteText":"Svelte 5 introduces runes, a powerful new reactivity system that replaces $: reactive statements.","isAppSkill":true},"web/WebsiteEmbedPreview.svelte":{"inlineLinkText":"svelte.dev","quoteText":"Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM.","isAppSkill":false},"videos/VideoEmbedPreview.svelte":{"inlineLinkText":"Understanding Svelte 5 Runes","quoteText":"Runes are a powerful new reactivity system that simplifies state management.","isAppSkill":false},"videos/VideoTranscriptEmbedPreview.svelte":{"inlineLinkText":"Svelte 5 Runes transcript","quoteText":"Today we are going to learn about Svelte 5 runes.","isAppSkill":true},"videos/VideosSearchEmbedPreview.svelte":{"inlineLinkText":"Svelte 5 tutorial search","quoteText":"Found 24 results for \"svelte 5 tutorial\" — curated from YouTube.","isAppSkill":true},"videos/VideoCreateEmbedPreview.svelte":{"inlineLinkText":"Product launch promo — 15s","quoteText":"Generated a 15s product launch video with title, features, and CTA scenes.","isAppSkill":true},"images/ImageGenerateEmbedPreview.svelte":{"inlineLinkText":"Cat wearing a top hat","quoteText":"Generated image: a quick sketch of a cat wearing a top hat, pencil style.","isAppSkill":true},"images/ImagesSearchEmbedPreview.svelte":{"inlineLinkText":"Golden Gate Bridge photos","quoteText":"Found 24 images of the Golden Gate Bridge via Brave Image Search.","isAppSkill":true},"images/ImageResultEmbedPreview.svelte":{"inlineLinkText":"Golden Gate Bridge at sunset — flickr.com","quoteText":"Golden Gate Bridge at sunset, photographed from Marin Headlands.","isAppSkill":false},"images/ImageEmbedPreview.svelte":{"inlineLinkText":"golden-gate-sunset.jpg","quoteText":"Uploaded image: golden-gate-sunset.jpg (2.4 MB, JPEG)","isAppSkill":false},"images/ImageViewEmbedPreview.svelte":{"inlineLinkText":"View: golden-gate-sunset.jpg","quoteText":"I analyzed the image: a vibrant sunset photograph taken at the Golden Gate Bridge.","isAppSkill":true},"news/NewsEmbedPreview.svelte":{"inlineLinkText":"Svelte 5 officially released","quoteText":"The latest version of the popular frontend framework brings fundamental changes to reactivity.","isAppSkill":false},"news/NewsSearchEmbedPreview.svelte":{"inlineLinkText":"Latest technology news 2026","quoteText":"New AI-powered development tools are changing how developers write, test, and deploy software.","isAppSkill":true},"travel/TravelSearchEmbedPreview.svelte":{"inlineLinkText":"Munich to London, Mar 15","quoteText":"Lufthansa LH2485: Munich to London Heathrow, 2h 10m, from 89 EUR.","isAppSkill":true},"travel/TravelConnectionEmbedPreview.svelte":{"inlineLinkText":"MUC to LHR direct flight","quoteText":"Direct flight Munich to London, 2h 10min, Terminal 2, Gate B22.","isAppSkill":false},"travel/TravelPriceCalendarEmbedPreview.svelte":{"inlineLinkText":"Munich to Barcelona prices, March","quoteText":"Cheapest day: March 18 at 62 EUR. Prices shown for Munich to Barcelona.","isAppSkill":true},"travel/TravelStayEmbedPreview.svelte":{"inlineLinkText":"Hotel Maximilian, Munich","quoteText":"Hotel Maximilian: 4-star hotel in central Munich, from 387 EUR for 3 nights.","isAppSkill":false},"travel/TravelStaysEmbedPreview.svelte":{"inlineLinkText":"Hotels in Barcelona, Mar 15-18","quoteText":"Found 8 hotels in Barcelona for Mar 15-18. Top pick: Hotel Arts Barcelona.","isAppSkill":true},"maps/MapsSearchEmbedPreview.svelte":{"inlineLinkText":"Coffee shops near Marienplatz","quoteText":"Man vs. Machine Coffee Roasters — Rated 4.7, 0.3km from Marienplatz, Munich.","isAppSkill":true},"maps/MapsLocationEmbedPreview.svelte":{"inlineLinkText":"Berlin Hauptbahnhof","quoteText":"Berlin Hauptbahnhof, Europaplatz 1, 10557 Berlin — static map + open-in-maps action.","isAppSkill":false},"math/MathCalculateEmbedPreview.svelte":{"inlineLinkText":"sin(pi/4) + cos(pi/3)","quoteText":"Result: sin(pi/4) + cos(pi/3) = sqrt(2)/2 + 1/2 approx 1.207","isAppSkill":true},"math/MathPlotEmbedPreview.svelte":{"inlineLinkText":"sin(x) and cos(x) plot","quoteText":"Interactive plot of f(x) = sin(x) and f(x) = cos(x) over [-2pi, 2pi].","isAppSkill":false},"music/MusicGenerateEmbedPreview.svelte":{"inlineLinkText":"Ambient synth background loop","quoteText":"Generated music: a 30 second ambient synth background loop with soft pads and no drums.","isAppSkill":true},"events/EventEmbedPreview.svelte":{"inlineLinkText":"AI & ML Berlin Meetup","quoteText":"AI & Machine Learning Berlin Meetup. March 15, 19:00 at Factory Berlin.","isAppSkill":false},"events/EventsSearchEmbedPreview.svelte":{"inlineLinkText":"AI meetups in Berlin","quoteText":"Found 3 upcoming AI & tech events in Berlin this month.","isAppSkill":true},"reminder/ReminderEmbedPreview.svelte":{"inlineLinkText":"Reminder: tomorrow 9:00 AM","quoteText":"Reminder set! I will send a message in this chat tomorrow at 9:00 AM.","isAppSkill":true},"sheets/SheetEmbedPreview.svelte":{"inlineLinkText":"Budget spreadsheet Q1 2026","quoteText":"Spreadsheet: Q1 2026 Budget — 12 rows, 8 columns, last updated today.","isAppSkill":false},"audio/RecordingEmbedPreview.svelte":{"inlineLinkText":"Voice note — 0:42","quoteText":"Voice recording captured: 42 seconds, transcription available.","isAppSkill":false},"health/HealthAppointmentEmbedPreview.svelte":{"inlineLinkText":"Dr. Mueller appointment — Apr 3","quoteText":"Appointment confirmed with Dr. Mueller on April 3 at 10:30 AM.","isAppSkill":false},"health/HealthSearchEmbedPreview.svelte":{"inlineLinkText":"Cardiologists near Munich","quoteText":"Found 5 cardiologists within 5km. Top result: Prof. Weber, rated 4.9.","isAppSkill":true},"mail/MailEmbedPreview.svelte":{"inlineLinkText":"Email: Project update from Anna","quoteText":"The latest sprint review went well. All tickets closed except the auth refactor.","isAppSkill":false},"pdf/PDFEmbedPreview.svelte":{"inlineLinkText":"Q4 2025 Report.pdf","quoteText":"Annual revenue increased 23% YoY. Full analysis on pages 4-7.","isAppSkill":false},"pdf/PdfReadEmbedPreview.svelte":{"inlineLinkText":"Architecture whitepaper — page 12","quoteText":"The microservices architecture enables independent scaling of each service component.","isAppSkill":true},"pdf/PdfSearchEmbedPreview.svelte":{"inlineLinkText":"Search \"authentication\" in docs","quoteText":"Found 7 mentions of \"authentication\" across 3 documents.","isAppSkill":true},"home/HomeSearchEmbedPreview.svelte":{"inlineLinkText":"Apartments in Berlin","quoteText":"Found 12 apartments in Berlin. Top pick: 850 EUR/month, 2-room apartment in Kreuzberg.","isAppSkill":true},"home/HomeListingEmbedPreview.svelte":{"inlineLinkText":"Schöne 2-Zimmer-Wohnung in Kreuzberg","quoteText":"850 EUR/month — 55 m², 2 rooms, Bergmannstr., Berlin-Kreuzberg","isAppSkill":false},"nutrition/NutritionSearchEmbedPreview.svelte":{"inlineLinkText":"Vegetarische Pasta Rezepte","quoteText":"3 Rezepte gefunden: Spaghetti Aglio e Olio, Penne Arrabiata, Tagliatelle mit Pilzrahmsauce.","isAppSkill":true},"nutrition/NutritionRecipeEmbedPreview.svelte":{"inlineLinkText":"Spaghetti Aglio e Olio","quoteText":"Spaghetti Aglio e Olio — 25 min, einfach, 4 Portionen.","isAppSkill":false},"shopping/ShoppingSearchEmbedPreview.svelte":{"inlineLinkText":"Wireless headphones under 100 EUR","quoteText":"Found 12 wireless headphones under 100 EUR. Top pick: Sony WH-1000XM4 at 89 EUR.","isAppSkill":true},"shopping/ShoppingResultEmbedPreview.svelte":{"inlineLinkText":"Bio Vollmilch-Joghurt Naturell","quoteText":"Bio Vollmilch-Joghurt Naturell, 500g, 1,39 EUR.","isAppSkill":false},"fitness/FitnessSearchEmbedPreview.svelte":{"inlineLinkText":"Yoga classes near Sorauer Str. 12","quoteText":"Found 3 Urban Sports classes nearby. Top pick: Morning Yoga Flow at Yoga Studio Kreuzberg.","isAppSkill":true},"electronics/ElectronicsSearchEmbedPreview.svelte":{"inlineLinkText":"12V to 3.3V buck converter","quoteText":"Found 10 TI WEBENCH buck converter designs. Top pick: TPS564257DRLR.","isAppSkill":true},"electronics/ElectronicsComponentEmbedPreview.svelte":{"inlineLinkText":"TPS564257DRLR","quoteText":"TPS564257DRLR - Buck converter, 92.4% efficiency, 0.47 USD BOM.","isAppSkill":false},"social_media/SocialMediaGetPostsEmbedPreview.svelte":{"inlineLinkText":"@samplegarden.example","quoteText":"Recent posts from Sample Garden Log about balcony herbs, compost, and seedlings.","isAppSkill":true},"social_media/SocialMediaSearchEmbedPreview.svelte":{"inlineLinkText":"Indie coffee setup inspiration","quoteText":"Found posts about compact espresso bars, home pourover stations, and menu photography.","isAppSkill":true},"social_media/SocialMediaPostEmbedPreview.svelte":{"inlineLinkText":"Small cafe bar layout notes","quoteText":"A compact espresso bar can still feel calm with warm task lighting and a narrow handoff shelf.","isAppSkill":false},"weather/WeatherForecastEmbedPreview.svelte":{"inlineLinkText":"Berlin weather forecast","quoteText":"Berlin forecast: dry Tuesday, rain Wednesday, light rain Thursday.","isAppSkill":true},"weather/WeatherDayEmbedPreview.svelte":{"inlineLinkText":"Berlin rain on June 3","quoteText":"Rain expected in Berlin, 14-19 C, 5.8 mm total precipitation, 13 rain hours.","isAppSkill":false},"tasks/TaskCreateEmbedPreview.svelte":{"inlineLinkText":"Balcony herb garden checklist","quoteText":"Created tasks for buying starter soil, clearing planter boxes, and preparing basil seeds.","isAppSkill":true},"tasks/TaskSearchEmbedPreview.svelte":{"inlineLinkText":"Packing list tasks","quoteText":"Found packing tasks for travel documents, camera batteries, and charger preparation.","isAppSkill":true},"finance/FinanceCheckAccountsEmbedPreview.svelte":{"inlineLinkText":"Cash flow overview","quoteText":"Checked 2 accounts and 5 transactions: income 8000 EUR, expenses 2291.25 EUR.","isAppSkill":true},"workflows/WorkflowCreateEmbedPreview.svelte":{"inlineLinkText":"Weekly garden check-in workflow","quoteText":"Created a simple manual workflow for a weekly balcony garden check-in.","isAppSkill":true},"workflows/WorkflowSearchEmbedPreview.svelte":{"inlineLinkText":"Travel packing workflows","quoteText":"Found reusable workflows for packing reminders and departure day weather checks.","isAppSkill":true}},
    "availableFiles":["audio/RecordingEmbedPreview.svelte","business/BusinessCompanyFinancialsEmbedPreview.svelte","business/BusinessCompanyFinancialResultEmbedPreview.svelte","code/CodeRepoSearchEmbedPreview.svelte","code/CodeRepoEmbedPreview.svelte","code/CodeGetDocsEmbedPreview.svelte","code/CodeEmbedPreview.svelte","code/ApplicationEmbedPreview.svelte","docs/DocsEmbedPreview.svelte","electronics/ElectronicsSearchEmbedPreview.svelte","electronics/ElectronicsComponentEmbedPreview.svelte","events/EventsSearchEmbedPreview.svelte","events/EventEmbedPreview.svelte","finance/FinanceCheckAccountsEmbedPreview.svelte","fitness/FitnessSearchEmbedPreview.svelte","fitness/FitnessResultEmbedPreview.svelte","health/HealthSearchEmbedPreview.svelte","health/HealthAppointmentEmbedPreview.svelte","home/HomeSearchEmbedPreview.svelte","home/HomeListingEmbedPreview.svelte","images/ImageGenerateEmbedPreview.svelte","images/ImageEmbedPreview.svelte","images/ImagesSearchEmbedPreview.svelte","images/ImageResultEmbedPreview.svelte","mail/MailEmbedPreview.svelte","mail/MailSearchEmbedPreview.svelte","maps/MapsSearchEmbedPreview.svelte","maps/MapsLocationEmbedPreview.svelte","math/MathCalculateEmbedPreview.svelte","math/MathPlotEmbedPreview.svelte","music/MusicGenerateEmbedPreview.svelte","news/NewsSearchEmbedPreview.svelte","web/WebsiteEmbedPreview.svelte","nutrition/NutritionSearchEmbedPreview.svelte","nutrition/NutritionRecipeEmbedPreview.svelte","pdf/PDFEmbedPreview.svelte","reminder/ReminderEmbedPreview.svelte","shopping/ShoppingSearchEmbedPreview.svelte","shopping/ShoppingResultEmbedPreview.svelte","social_media/SocialMediaGetPostsEmbedPreview.svelte","social_media/SocialMediaPostEmbedPreview.svelte","social_media/SocialMediaSearchEmbedPreview.svelte","tasks/TaskCreateEmbedPreview.svelte","tasks/TaskEmbedPreview.svelte","tasks/TaskSearchEmbedPreview.svelte","travel/TravelSearchEmbedPreview.svelte","travel/TravelConnectionEmbedPreview.svelte","travel/TravelStaysEmbedPreview.svelte","travel/TravelStayEmbedPreview.svelte","travel/TravelPriceCalendarEmbedPreview.svelte","videos/VideosSearchEmbedPreview.svelte","videos/VideoEmbedPreview.svelte","videos/VideoTranscriptEmbedPreview.svelte","videos/VideoCreateEmbedPreview.svelte","weather/WeatherForecastEmbedPreview.svelte","weather/WeatherDayEmbedPreview.svelte","weather/WeatherRainRadarEmbedPreview.svelte","web/WebSearchEmbedPreview.svelte","web/WebReadEmbedPreview.svelte","workflows/WorkflowCreateEmbedPreview.svelte","workflows/WorkflowEmbedPreview.svelte","workflows/WorkflowSearchEmbedPreview.svelte","sheets/SheetEmbedPreview.svelte","focus_mode/FocusModeActivationEmbed.svelte","audio/RecordingEmbedFullscreen.svelte","business/BusinessCompanyFinancialsEmbedFullscreen.svelte","business/BusinessCompanyFinancialResultEmbedFullscreen.svelte","code/CodeRepoSearchEmbedFullscreen.svelte","code/CodeRepoEmbedFullscreen.svelte","code/CodeGetDocsEmbedFullscreen.svelte","code/CodeEmbedFullscreen.svelte","code/ApplicationEmbedFullscreen.svelte","docs/DocsEmbedFullscreen.svelte","electronics/ElectronicsSearchEmbedFullscreen.svelte","electronics/ElectronicsComponentEmbedFullscreen.svelte","events/EventsSearchEmbedFullscreen.svelte","events/EventEmbedFullscreen.svelte","finance/FinanceCheckAccountsEmbedFullscreen.svelte","fitness/FitnessSearchEmbedFullscreen.svelte","health/HealthSearchEmbedFullscreen.svelte","health/HealthAppointmentEmbedFullscreen.svelte","home/HomeSearchEmbedFullscreen.svelte","home/HomeListingEmbedFullscreen.svelte","images/ImageGenerateEmbedFullscreen.svelte","images/ImageEmbedFullscreen.svelte","images/ImagesSearchEmbedFullscreen.svelte","images/ImageResultEmbedFullscreen.svelte","mail/MailEmbedFullscreen.svelte","maps/MapsSearchEmbedFullscreen.svelte","maps/MapLocationEmbedFullscreen.svelte","maps/MapsLocationEmbedFullscreen.svelte","math/MathCalculateEmbedFullscreen.svelte","math/MathPlotEmbedFullscreen.svelte","mindmaps/MindMapEmbedFullscreen.svelte","music/MusicGenerateEmbedFullscreen.svelte","news/NewsSearchEmbedFullscreen.svelte","web/WebsiteEmbedFullscreen.svelte","nutrition/NutritionSearchEmbedFullscreen.svelte","nutrition/NutritionRecipeEmbedFullscreen.svelte","pdf/PDFEmbedFullscreen.svelte","reminder/ReminderEmbedFullscreen.svelte","shopping/ShoppingSearchEmbedFullscreen.svelte","shopping/ShoppingResultEmbedFullscreen.svelte","travel/TravelSearchEmbedFullscreen.svelte","travel/TravelConnectionEmbedFullscreen.svelte","travel/TravelStaysEmbedFullscreen.svelte","travel/TravelStayEmbedFullscreen.svelte","travel/TravelPriceCalendarEmbedFullscreen.svelte","videos/VideosSearchEmbedFullscreen.svelte","videos/VideoEmbedFullscreen.svelte","videos/VideoTranscriptEmbedFullscreen.svelte","videos/VideoCreateEmbedFullscreen.svelte","weather/WeatherForecastEmbedFullscreen.svelte","weather/WeatherDayEmbedFullscreen.svelte","weather/WeatherRainRadarEmbedFullscreen.svelte","web/WebSearchEmbedFullscreen.svelte","web/WebReadEmbedFullscreen.svelte","sheets/SheetEmbedFullscreen.svelte","focus_mode/FocusModeActivationEmbedFullscreen.svelte"],
    "variants":{
    "audio/RecordingEmbedPreview.svelte":[{"name":"uploading","props":{"id":"preview-audio-uploading","filename":"voice-memo.webm","status":"uploading","transcript":"This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week.","duration":"1:15","model":"voxtral-mini-2602","isMobile":false,"isAuthenticated":true}},{"name":"transcribing","props":{"id":"preview-audio-transcribing","filename":"voice-memo.webm","status":"transcribing","transcript":"This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week.","duration":"0:42","model":"voxtral-mini-2602","isMobile":false,"isAuthenticated":true}},{"name":"correcting","props":{"id":"preview-audio-correcting","filename":"voice-memo.webm","status":"correcting","transcript":"Please schedule the project review for Thursday afternoon.","duration":"0:42","model":"voxtral-mini-transcribe-realtime-2602","isMobile":false,"isAuthenticated":true,"transcriptOriginal":"Please schedule the project review for Thursday afternoon."}},{"name":"error","props":{"id":"preview-audio-error","filename":"voice-memo.webm","status":"error","transcript":"This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week.","duration":"0:42","model":"voxtral-mini-2602","isMobile":false,"isAuthenticated":true,"uploadError":"Transcription failed. Please try again."}},{"name":"mobile","props":{"id":"preview-audio-mobile","filename":"voice-memo-2026-03-10.webm","status":"finished","transcript":"This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week.","duration":"0:42","model":"voxtral-mini-2602","isMobile":true,"isAuthenticated":true}}],
    "audio/AudioGenerateEmbedPreview.svelte":[],
    "business/BusinessCompanyFinancialsEmbedPreview.svelte":[{"name":"quarterly","props":{"id":"preview-business-company-financials-quarterly","query":"Show VITL latest quarter financials","provider":"SEC EDGAR","period":"latest_quarter","metricGroup":"income","status":"finished","results":[{"embed_id":"legacy-business-financial-vitl-quarter","company":"Vital Farms, Inc.","ticker":"VITL","cik":"0001579733","country":"US","exchange":"NASDAQ","period_type":"quarter","fiscal_year":2026,"period_start":"2025-12-29","period_end":"2026-03-28","filed":"2026-05-07","form":"10-K","currency":"USD","revenue":187155000,"gross_profit":1799800000,"operating_income":1446200000,"net_income":-1522000,"operating_cash_flow":1260000000,"assets":3451000000,"liabilities":602000000,"equity":2849000000,"source_url":"https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/1579733/000157973326000042/vitl-20260328.htm","accession_number":"0001579733-26-000042","fiscal_quarter":"Q1"}],"resultCount":1,"childEmbedIds":["legacy-business-financial-vitl-quarter"],"isMobile":false}},{"name":"noResults","props":{"id":"preview-business-company-financials-empty","query":"Private company with no SEC filing","provider":"SEC EDGAR","period":"latest_annual","metricGroup":"summary","status":"finished","results":[],"resultCount":0,"childEmbedIds":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-business-company-financials-mobile","query":"Compare CALM and MU latest annual financials","provider":"SEC EDGAR","period":"latest_annual","metricGroup":"summary","status":"finished","results":[{"embed_id":"legacy-business-financial-calm","company":"Cal-Maine Foods, Inc.","ticker":"CALM","cik":"0000016160","country":"US","exchange":"NASDAQ","period_type":"annual","fiscal_year":2025,"period_start":"2024-06-02","period_end":"2025-05-31","filed":"2025-07-18","form":"10-K","currency":"USD","revenue":4261885000,"gross_profit":1799800000,"operating_income":1446200000,"net_income":1220048000,"operating_cash_flow":1260000000,"assets":3451000000,"liabilities":602000000,"equity":2849000000,"source_url":"https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/16160/000001616025000050/calm-20250531.htm","accession_number":"0000016160-25-000050"},{"embed_id":"legacy-business-financial-mu","company":"Micron Technology, Inc.","ticker":"MU","cik":"0000723125","country":"US","exchange":"NASDAQ","period_type":"annual","fiscal_year":2025,"period_start":"2024-08-30","period_end":"2025-08-28","filed":"2025-10-03","form":"10-K","currency":"USD","revenue":37378000000,"gross_profit":14212000000,"operating_income":9411000000,"net_income":8539000000,"operating_cash_flow":15840000000,"assets":82120000000,"liabilities":26300000000,"equity":55820000000,"source_url":"https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/723125/000072312525000120/mu-20250828.htm","accession_number":"0000723125-25-000120"}],"resultCount":2,"childEmbedIds":["legacy-business-financial-calm","legacy-business-financial-mu"],"isMobile":true}}],
    "business/BusinessCompanyFinancialResultEmbedPreview.svelte":[{"name":"quarterly","props":{"id":"preview-business-financial-vitl-quarter","company":"Vital Farms, Inc.","ticker":"VITL","fiscalYear":2026,"periodType":"quarter","currency":"USD","revenue":187155000,"netIncome":-1522000,"filed":"2026-05-07","form":"10-Q","status":"finished","isMobile":false,"fiscalQuarter":"Q1"}},{"name":"mobile","props":{"id":"preview-business-financial-calm-mobile","company":"Cal-Maine Foods, Inc.","ticker":"CALM","fiscalYear":2025,"periodType":"annual","currency":"USD","revenue":4261885000,"netIncome":1220048000,"filed":"2025-07-18","form":"10-K","status":"finished","isMobile":true}}],
    "calendar/CalendarActionEmbedPreview.svelte":[],
    "code/CodeRepoSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-code-search-repos-processing","query":"python cli framework","provider":"GitHub","status":"processing","results":[],"isMobile":false}},{"name":"empty","props":{"id":"preview-code-search-repos-empty","query":"nonexistent repo topic","provider":"GitHub","status":"finished","results":[],"isMobile":false}}],
    "code/CodeRepoEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-code-repo-processing","url":"https://github.com/lemmingDev/ESP32-BLE-Gamepad","fullName":"lemmingDev/ESP32-BLE-Gamepad","name":"ESP32-BLE-Gamepad","ownerLogin":"lemmingDev","ownerAvatarUrl":"https://avatars.githubusercontent.com/u/15526971?v=4","description":"Bluetooth LE Gamepad library for the ESP32","primaryLanguage":"C++","licenseName":"MIT License","licenseSpdxId":"MIT","stars":1516,"forks":250,"openIssues":35,"updatedAt":"2026-05-08T09:02:54Z","status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-code-repo-error","url":"https://github.com/lemmingDev/ESP32-BLE-Gamepad","fullName":"lemmingDev/ESP32-BLE-Gamepad","name":"ESP32-BLE-Gamepad","ownerLogin":"lemmingDev","ownerAvatarUrl":"https://avatars.githubusercontent.com/u/15526971?v=4","description":"Bluetooth LE Gamepad library for the ESP32","primaryLanguage":"C++","licenseName":"MIT License","licenseSpdxId":"MIT","stars":1516,"forks":250,"openIssues":35,"updatedAt":"2026-05-08T09:02:54Z","status":"error","isMobile":false}},{"name":"cancelled","props":{"id":"preview-code-repo-cancelled","url":"https://github.com/lemmingDev/ESP32-BLE-Gamepad","fullName":"lemmingDev/ESP32-BLE-Gamepad","name":"ESP32-BLE-Gamepad","ownerLogin":"lemmingDev","ownerAvatarUrl":"https://avatars.githubusercontent.com/u/15526971?v=4","description":"Bluetooth LE Gamepad library for the ESP32","primaryLanguage":"C++","licenseName":"MIT License","licenseSpdxId":"MIT","stars":1516,"forks":250,"openIssues":35,"updatedAt":"2026-05-08T09:02:54Z","status":"cancelled","isMobile":false}},{"name":"mobile","props":{"id":"preview-code-repo-mobile","url":"https://github.com/lemmingDev/ESP32-BLE-Gamepad","fullName":"lemmingDev/ESP32-BLE-Gamepad","name":"ESP32-BLE-Gamepad","ownerLogin":"lemmingDev","ownerAvatarUrl":"https://avatars.githubusercontent.com/u/15526971?v=4","description":"Bluetooth LE Gamepad library for the ESP32","primaryLanguage":"C++","licenseName":"MIT License","licenseSpdxId":"MIT","stars":1516,"forks":250,"openIssues":35,"updatedAt":"2026-05-08T09:02:54Z","status":"finished","isMobile":true}}],
    "code/CodeGetDocsEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-code-getdocs-processing","status":"processing","library":"react","question":"How to use useEffect hook?","results":[],"isMobile":false}},{"name":"fastapi","props":{"id":"preview-code-getdocs-fastapi","status":"finished","library":"fastapi","question":"How to define path parameters?","results":[{"library":{"id":"/tiangolo/fastapi","title":"FastAPI"},"documentation":"Path parameters are defined using Python type hints in the function signature.","word_count":62,"source":"context7"}],"isMobile":false}},{"name":"error","props":{"id":"preview-code-getdocs-error","status":"error","library":"unknown-lib","question":"How to use unknown feature?","results":[],"isMobile":false}}],
    "code/CodeEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-code-processing","language":"python","filename":"main.py","lineCount":0,"status":"processing","codeContent":"","isMobile":false}},{"name":"bash","props":{"id":"preview-code-bash","language":"bash","filename":"deploy.sh","lineCount":18,"status":"finished","codeContent":"#!/usr/bin/env bash\nset -euo pipefail\n\nAPP_NAME=\"openmates-api\"\nREGISTRY=\"registry.example.com\"\nTAG=\"$(git rev-parse --short HEAD)\"\n\necho \"Building $APP_NAME:$TAG...\"\ndocker build -t \"$REGISTRY/$APP_NAME:$TAG\" .\n\necho \"Pushing to registry...\"\ndocker push \"$REGISTRY/$APP_NAME:$TAG\"\ndocker tag \"$REGISTRY/$APP_NAME:$TAG\" \"$REGISTRY/$APP_NAME:latest\"\ndocker push \"$REGISTRY/$APP_NAME:latest\"\n\necho \"Deploying to production...\"\nssh deploy@prod \"docker pull $REGISTRY/$APP_NAME:$TAG && docker-compose up -d\"\necho \"Deployment complete: $APP_NAME @ $TAG\"","isMobile":false}},{"name":"python","props":{"id":"preview-code-python","language":"python","filename":"embed_service.py","lineCount":42,"status":"finished","codeContent":"\"\"\"\nEmbed resolution service — resolves embed references in AI responses.\nSee docs/architecture/embeds.md for the full pipeline description.\n\"\"\"\nfrom __future__ import annotations\nimport asyncio\nfrom typing import Any\nfrom pydantic import BaseModel\nfrom backend.shared.providers.redis import redis_client\nfrom .embed_store import EmbedStore\nfrom .embed_types import EmbedStatus\n\nEMBED_TTL_SECONDS = 3600 * 24  # 24 hours\n\n\nclass EmbedContent(BaseModel):\n    embed_id: str\n    skill_id: str\n    status: EmbedStatus\n    content: dict[str, Any] | None = None\n\n\nasync def resolve_embed(embed_id: str) -> EmbedContent | None:\n    \"\"\"Resolve an embed by ID, checking Redis cache first.\"\"\"\n    cache_key = f\"embed:{embed_id}\"\n\n    # 1. Try Redis cache (fast path)\n    cached = await redis_client.get(cache_key)\n    if cached:\n        return EmbedContent.model_validate_json(cached)\n\n    # 2. Fall back to persistent embed store\n    store = EmbedStore()\n    embed = await store.get(embed_id)\n    if not embed:\n        return None\n\n    # 3. Warm the cache for subsequent requests\n    await redis_client.setex(\n        cache_key,\n        EMBED_TTL_SECONDS,\n        embed.model_dump_json()\n    )\n    return embed\n\n\nasync def resolve_embed_batch(\n    embed_ids: list[str],\n    concurrency: int = 10\n) -> dict[str, EmbedContent | None]:\n    \"\"\"Resolve multiple embeds concurrently with a semaphore.\"\"\"\n    sem = asyncio.Semaphore(concurrency)\n\n    async def _fetch(eid: str) -> tuple[str, EmbedContent | None]:\n        async with sem:\n            return eid, await resolve_embed(eid)\n\n    results = await asyncio.gather(*[_fetch(eid) for eid in embed_ids])\n    return dict(results)","isMobile":false}},{"name":"svelte","props":{"id":"preview-code-svelte","language":"svelte","filename":"EmbedCard.svelte","lineCount":35,"status":"finished","codeContent":"<!--\n  EmbedCard.svelte — Reusable card component for embed previews.\n  Uses container queries for responsive layout.\n-->\n<script lang=\"ts\">\n  import { fade } from 'svelte/transition';\n\n  interface Props {\n    title: string;\n    subtitle?: string;\n    status: 'loading' | 'ready' | 'error';\n    appId: string;\n    onOpen?: () => void;\n  }\n\n  let { title, subtitle = '', status, appId, onOpen }: Props = $props();\n\n  let isHovered = $state(false);\n  let gradientStyle = $derived(`background: var(--color-app-${appId})`);\n</script>\n\n<div\n  class=\"embed-card\"\n  class:hovered={isHovered}\n  onmouseenter={() => (isHovered = true)}\n  onmouseleave={() => (isHovered = false)}\n  role=\"button\"\n  tabindex=\"0\"\n  onclick={onOpen}\n>\n  <div class=\"app-icon\" style={gradientStyle}></div>\n  <div class=\"card-content\">\n    <p class=\"title\">{title}</p>\n    {#if subtitle}\n      <p class=\"subtitle\" transition:fade={{ duration: 150 }}>{subtitle}</p>\n    {/if}\n  </div>\n</div>","isMobile":false}},{"name":"html","props":{"id":"preview-code-html","language":"html","filename":"landing.html","lineCount":48,"status":"finished","codeContent":"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\" />\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n  <title>OpenMates — AI Assistant</title>\n  <style>\n    *, *::before, *::after { box-sizing: border-box; margin: 0; }\n    body {\n      font-family: 'Inter', system-ui, sans-serif;\n      background: #0d0d0d;\n      color: #f0f0f0;\n      min-height: 100vh;\n      display: grid;\n      place-items: center;\n    }\n    .hero {\n      text-align: center;\n      padding: 4rem 2rem;\n    }\n    .hero h1 {\n      font-size: clamp(2rem, 6vw, 5rem);\n      font-weight: 800;\n      background: linear-gradient(135deg, #7c6eff, #a78bfa);\n      -webkit-background-clip: text;\n      -webkit-text-fill-color: transparent;\n    }\n    .cta {\n      margin-top: 2rem;\n      padding: 0.75rem 2.5rem;\n      border-radius: 9999px;\n      background: #7c6eff;\n      color: #fff;\n      font-size: 1.125rem;\n      font-weight: 600;\n      border: none;\n      cursor: pointer;\n      transition: transform 0.15s;\n    }\n    .cta:hover { transform: scale(1.05); }\n  </style>\n</head>\n<body>\n  <section class=\"hero\">\n    <h1>Your AI Companion</h1>\n    <p>Research, code, create — all in one place.</p>\n    <button class=\"cta\" id=\"startBtn\">Get started free</button>\n  </section>\n  <script>\n    document.getElementById('startBtn').addEventListener('click', () => {\n      window.location.href = '/signup';\n    });\n  </script>\n</body>\n</html>","isMobile":false}},{"name":"javascript","props":{"id":"preview-code-js","language":"javascript","filename":"eventBus.js","lineCount":28,"status":"finished","codeContent":"/**\n * Lightweight typed event bus for cross-component communication.\n * Usage: import { eventBus } from './eventBus';\n *        eventBus.on('embed:updated', handler);\n *        eventBus.emit('embed:updated', { id: '123' });\n */\n\nclass EventBus {\n  #listeners = new Map();\n\n  on(event, handler) {\n    if (!this.#listeners.has(event)) {\n      this.#listeners.set(event, new Set());\n    }\n    this.#listeners.get(event).add(handler);\n    // Return unsubscribe function\n    return () => this.#listeners.get(event)?.delete(handler);\n  }\n\n  emit(event, payload) {\n    const handlers = this.#listeners.get(event);\n    if (!handlers?.size) return;\n    for (const h of handlers) {\n      try { h(payload); }\n      catch (e) { console.error(`[EventBus] Error in \"${event}\" handler:`, e); }\n    }\n  }\n\n  once(event, handler) {\n    const unsub = this.on(event, (payload) => {\n      unsub();\n      handler(payload);\n    });\n    return unsub;\n  }\n}\n\nexport const eventBus = new EventBus();","isMobile":false}},{"name":"css","props":{"id":"preview-code-css","language":"css","filename":"embed-card.css","lineCount":30,"status":"finished","codeContent":"/* Embed card design system tokens and component styles */\n:root {\n  --card-radius: 1.875rem;\n  --card-shadow-rest: 0 4px 16px rgba(0, 0, 0, 0.08);\n  --card-shadow-hover: 0 12px 32px rgba(0, 0, 0, 0.16);\n  --card-transition: transform 0.2s ease, box-shadow 0.2s ease;\n}\n\n.embed-card {\n  position: relative;\n  border-radius: var(--card-radius);\n  background-color: var(--color-grey-0);\n  box-shadow: var(--card-shadow-rest);\n  transition: var(--card-transition);\n  overflow: hidden;\n  cursor: pointer;\n  container-type: inline-size;\n}\n\n.embed-card:hover {\n  transform: scale(1.015) translateY(-2px);\n  box-shadow: var(--card-shadow-hover);\n}\n\n.embed-card:active {\n  transform: scale(0.99);\n  box-shadow: var(--card-shadow-rest);\n}\n\n@container (min-width: 300px) {\n  .embed-card .card-title {\n    font-size: 1rem;\n    -webkit-line-clamp: 2;\n  }\n}","isMobile":false}},{"name":"error","props":{"id":"preview-code-error","language":"javascript","filename":"MyComponent.svelte","lineCount":14,"status":"error","codeContent":"","isMobile":false}}],
    "code/NotebookEmbedPreview.svelte":[],
    "code/ApplicationEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-application-processing","name":"Recipe Manager","framework":"Svelte","runtime":"Node","file_refs":[{"path":"package.json","embed_id":"file-package","role":"dependency_manifest"},{"path":"src/App.svelte","embed_id":"file-app","role":"source"},{"path":"src/main.ts","embed_id":"file-main","role":"source"}],"entrypoints":[{"name":"frontend","command":"npm run dev","port":5173}],"status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-application-error","name":"Recipe Manager","framework":"Svelte","runtime":"Node","file_refs":[{"path":"package.json","embed_id":"file-package","role":"dependency_manifest"},{"path":"src/App.svelte","embed_id":"file-app","role":"source"},{"path":"src/main.ts","embed_id":"file-main","role":"source"}],"entrypoints":[{"name":"frontend","command":"npm run dev","port":5173}],"status":"error","isMobile":false}},{"name":"mobile","props":{"id":"preview-application-mobile","name":"Recipe Manager","framework":"Svelte","runtime":"Node","file_refs":[{"path":"package.json","embed_id":"file-package","role":"dependency_manifest"},{"path":"src/App.svelte","embed_id":"file-app","role":"source"},{"path":"src/main.ts","embed_id":"file-main","role":"source"}],"entrypoints":[{"name":"frontend","command":"npm run dev","port":5173}],"status":"finished","isMobile":true}}],
    "design/DesignIconSearchEmbedPreview.svelte":[],
    "design/DesignIconResultEmbedPreview.svelte":[],
    "docs/DocsEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-docs-processing","title":"Project Architecture Overview","filename":"architecture.docx","wordCount":156,"status":"processing","htmlContent":"<h1>Project Architecture Overview</h1>\n<p>This document outlines the architecture decisions for the OpenMates platform.</p>\n<h2>Frontend</h2>\n<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity.</p>\n<h2>Backend</h2>\n<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services.</p>\n<h2>Database</h2>\n<p>PostgreSQL serves as the primary data store, managed through Directus CMS.</p>","previewPageUrls":{"1":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2234%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EProject%20Architecture%20Overview%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22206%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EGenerated%20as%20a%20real%20DOCX%20artifact%2C%20then%20converted%20server-side%20to%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22252%22%20width%3D%22570%22%20height%3D%221%22%20fill%3D%22%23d1d5db%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22314%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EFrontend%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22356%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ESvelteKit%20and%20Svelte%205%20render%20the%20encrypted%20document%20preview%20after%20decrypting%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22382%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3Ethe%20generated%20screenshot%20artifact%20in%20the%20browser.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22456%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EBackend%20Pipeline%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22498%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E1.%20The%20model%20emits%20structured%20docx_model%20JSON.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22526%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E2.%20The%20Docs%20worker%20creates%20a%20canonical%20.docx%20file.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22554%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E3.%20LibreOffice%20converts%20it%20to%20PDF%3B%20PyMuPDF%20renders%20page%20screenshots.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22582%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E4.%20DOCX%20and%20screenshots%20are%20AES-GCM%20encrypted%20before%20upload.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22660%22%20width%3D%22570%22%20height%3D%22132%22%20rx%3D%2214%22%20fill%3D%22%23eef2ff%22%20stroke%3D%22%23c7d2fe%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22711%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%233730a3%22%3EDownload%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22750%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%234338ca%22%3EThe%20download%20button%20returns%20the%20real%20generated%20DOCX%2C%20not%20browser%20HTML.%3C%2Ftext%3E%0A%3C%2Fsvg%3E"},"isMobile":false}},{"name":"error","props":{"id":"preview-docs-error","title":"Project Architecture Overview","filename":"architecture.docx","wordCount":156,"status":"error","htmlContent":"<h1>Project Architecture Overview</h1>\n<p>This document outlines the architecture decisions for the OpenMates platform.</p>\n<h2>Frontend</h2>\n<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity.</p>\n<h2>Backend</h2>\n<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services.</p>\n<h2>Database</h2>\n<p>PostgreSQL serves as the primary data store, managed through Directus CMS.</p>","previewPageUrls":{"1":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2234%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EProject%20Architecture%20Overview%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22206%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EGenerated%20as%20a%20real%20DOCX%20artifact%2C%20then%20converted%20server-side%20to%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22252%22%20width%3D%22570%22%20height%3D%221%22%20fill%3D%22%23d1d5db%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22314%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EFrontend%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22356%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ESvelteKit%20and%20Svelte%205%20render%20the%20encrypted%20document%20preview%20after%20decrypting%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22382%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3Ethe%20generated%20screenshot%20artifact%20in%20the%20browser.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22456%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EBackend%20Pipeline%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22498%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E1.%20The%20model%20emits%20structured%20docx_model%20JSON.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22526%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E2.%20The%20Docs%20worker%20creates%20a%20canonical%20.docx%20file.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22554%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E3.%20LibreOffice%20converts%20it%20to%20PDF%3B%20PyMuPDF%20renders%20page%20screenshots.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22582%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E4.%20DOCX%20and%20screenshots%20are%20AES-GCM%20encrypted%20before%20upload.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22660%22%20width%3D%22570%22%20height%3D%22132%22%20rx%3D%2214%22%20fill%3D%22%23eef2ff%22%20stroke%3D%22%23c7d2fe%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22711%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%233730a3%22%3EDownload%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22750%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%234338ca%22%3EThe%20download%20button%20returns%20the%20real%20generated%20DOCX%2C%20not%20browser%20HTML.%3C%2Ftext%3E%0A%3C%2Fsvg%3E"},"isMobile":false}},{"name":"longDocument","props":{"id":"preview-docs-long","title":"Complete API Reference Manual","filename":"api-reference.docx","wordCount":12450,"status":"finished","htmlContent":"<h1>Project Architecture Overview</h1>\n<p>This document outlines the architecture decisions for the OpenMates platform.</p>\n<h2>Frontend</h2>\n<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity.</p>\n<h2>Backend</h2>\n<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services.</p>\n<h2>Database</h2>\n<p>PostgreSQL serves as the primary data store, managed through Directus CMS.</p>","previewPageUrls":{"1":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2234%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EProject%20Architecture%20Overview%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22206%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EGenerated%20as%20a%20real%20DOCX%20artifact%2C%20then%20converted%20server-side%20to%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22252%22%20width%3D%22570%22%20height%3D%221%22%20fill%3D%22%23d1d5db%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22314%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EFrontend%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22356%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ESvelteKit%20and%20Svelte%205%20render%20the%20encrypted%20document%20preview%20after%20decrypting%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22382%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3Ethe%20generated%20screenshot%20artifact%20in%20the%20browser.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22456%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EBackend%20Pipeline%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22498%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E1.%20The%20model%20emits%20structured%20docx_model%20JSON.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22526%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E2.%20The%20Docs%20worker%20creates%20a%20canonical%20.docx%20file.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22554%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E3.%20LibreOffice%20converts%20it%20to%20PDF%3B%20PyMuPDF%20renders%20page%20screenshots.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22582%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E4.%20DOCX%20and%20screenshots%20are%20AES-GCM%20encrypted%20before%20upload.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22660%22%20width%3D%22570%22%20height%3D%22132%22%20rx%3D%2214%22%20fill%3D%22%23eef2ff%22%20stroke%3D%22%23c7d2fe%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22711%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%233730a3%22%3EDownload%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22750%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%234338ca%22%3EThe%20download%20button%20returns%20the%20real%20generated%20DOCX%2C%20not%20browser%20HTML.%3C%2Ftext%3E%0A%3C%2Fsvg%3E"},"isMobile":false}},{"name":"generatedDocxArtifact","props":{"id":"preview-docs-generated-artifact","title":"Generated DOCX Artifact","filename":"generated-artifact.docx","wordCount":91,"status":"finished","htmlContent":"<h1>Project Architecture Overview</h1>\n<p>This document outlines the architecture decisions for the OpenMates platform.</p>\n<h2>Frontend</h2>\n<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity.</p>\n<h2>Backend</h2>\n<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services.</p>\n<h2>Database</h2>\n<p>PostgreSQL serves as the primary data store, managed through Directus CMS.</p>","previewPageUrls":{"1":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2234%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EProject%20Architecture%20Overview%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22206%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EGenerated%20as%20a%20real%20DOCX%20artifact%2C%20then%20converted%20server-side%20to%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22252%22%20width%3D%22570%22%20height%3D%221%22%20fill%3D%22%23d1d5db%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22314%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EFrontend%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22356%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ESvelteKit%20and%20Svelte%205%20render%20the%20encrypted%20document%20preview%20after%20decrypting%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22382%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3Ethe%20generated%20screenshot%20artifact%20in%20the%20browser.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22456%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EBackend%20Pipeline%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22498%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E1.%20The%20model%20emits%20structured%20docx_model%20JSON.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22526%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E2.%20The%20Docs%20worker%20creates%20a%20canonical%20.docx%20file.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22554%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E3.%20LibreOffice%20converts%20it%20to%20PDF%3B%20PyMuPDF%20renders%20page%20screenshots.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22582%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E4.%20DOCX%20and%20screenshots%20are%20AES-GCM%20encrypted%20before%20upload.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22660%22%20width%3D%22570%22%20height%3D%22132%22%20rx%3D%2214%22%20fill%3D%22%23eef2ff%22%20stroke%3D%22%23c7d2fe%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22711%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%233730a3%22%3EDownload%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22750%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%234338ca%22%3EThe%20download%20button%20returns%20the%20real%20generated%20DOCX%2C%20not%20browser%20HTML.%3C%2Ftext%3E%0A%3C%2Fsvg%3E"},"isMobile":false}},{"name":"mobile","props":{"id":"preview-docs-mobile","title":"Project Architecture Overview","filename":"architecture.docx","wordCount":156,"status":"finished","htmlContent":"<h1>Project Architecture Overview</h1>\n<p>This document outlines the architecture decisions for the OpenMates platform.</p>\n<h2>Frontend</h2>\n<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity.</p>\n<h2>Backend</h2>\n<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services.</p>\n<h2>Database</h2>\n<p>PostgreSQL serves as the primary data store, managed through Directus CMS.</p>","previewPageUrls":{"1":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2234%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EProject%20Architecture%20Overview%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22206%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EGenerated%20as%20a%20real%20DOCX%20artifact%2C%20then%20converted%20server-side%20to%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22252%22%20width%3D%22570%22%20height%3D%221%22%20fill%3D%22%23d1d5db%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22314%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EFrontend%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22356%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ESvelteKit%20and%20Svelte%205%20render%20the%20encrypted%20document%20preview%20after%20decrypting%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22382%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3Ethe%20generated%20screenshot%20artifact%20in%20the%20browser.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22456%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EBackend%20Pipeline%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22498%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E1.%20The%20model%20emits%20structured%20docx_model%20JSON.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22526%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E2.%20The%20Docs%20worker%20creates%20a%20canonical%20.docx%20file.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22554%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E3.%20LibreOffice%20converts%20it%20to%20PDF%3B%20PyMuPDF%20renders%20page%20screenshots.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22582%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E4.%20DOCX%20and%20screenshots%20are%20AES-GCM%20encrypted%20before%20upload.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22660%22%20width%3D%22570%22%20height%3D%22132%22%20rx%3D%2214%22%20fill%3D%22%23eef2ff%22%20stroke%3D%22%23c7d2fe%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22711%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%233730a3%22%3EDownload%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22750%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%234338ca%22%3EThe%20download%20button%20returns%20the%20real%20generated%20DOCX%2C%20not%20browser%20HTML.%3C%2Ftext%3E%0A%3C%2Fsvg%3E"},"isMobile":true}}],
    "electronics/PcbSchematicEmbedPreview.svelte":[],
    "electronics/ElectronicsSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-electronics-search-processing","query":"24V to 5V isolated converter","provider":"TI WEBENCH","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-electronics-search-error","query":"invalid converter search","provider":"TI WEBENCH","status":"error","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-electronics-search-mobile","query":"12V to 3.3V buck converter at 3A","provider":"TI WEBENCH","status":"finished","results":[{"type":"power_converter","provider":"TI WEBENCH","part_number":"TPS564257DRLR","base_part_number":"TPS564257","title":"TPS564257DRLR Buck converter","topology":"Buck","package":"SOT-563","regulator_type":"Converter","product_url":"https://www.ti.com/product/TPS564257","datasheet_url":"https://www.ti.com/lit/gpn/tps564257","bom_cost_usd":0.47,"bom_count":11,"efficiency_percent":92.4,"footprint_mm2":89.6},{"type":"power_converter","provider":"TI WEBENCH","part_number":"TPS563257DRLR","base_part_number":"TPS563257","title":"TPS563257DRLR Buck converter","topology":"Buck","package":"SOT-563","regulator_type":"Converter","product_url":"https://www.ti.com/product/TPS563257","datasheet_url":"https://www.ti.com/lit/gpn/tps563257","bom_cost_usd":0.43,"bom_count":10,"efficiency_percent":91.8,"footprint_mm2":84.2}],"isMobile":true}}],
    "electronics/ElectronicsComponentEmbedPreview.svelte":[{"name":"compact","props":{"id":"preview-electronics-component-compact","provider":"TI WEBENCH","part_number":"TPS563257DRLR","base_part_number":"TPS564257","title":"TPS564257DRLR Buck converter","topology":"Buck","package":"SOT-563","regulator_type":"Converter","bom_cost_usd":0.43,"bom_count":11,"efficiency_percent":91.8,"footprint_mm2":84.2,"status":"finished","isMobile":false}},{"name":"mobile","props":{"id":"preview-electronics-component-mobile","provider":"TI WEBENCH","part_number":"TPS564257DRLR","base_part_number":"TPS564257","title":"TPS564257DRLR Buck converter","topology":"Buck","package":"SOT-563","regulator_type":"Converter","bom_cost_usd":0.47,"bom_count":11,"efficiency_percent":92.4,"footprint_mm2":89.6,"status":"finished","isMobile":true}}],
    "events/EventsSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-events-search-processing","query":"searching for events...","provider":"Meetup","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-events-search-error","query":"failed events search","provider":"Meetup","status":"error","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-events-search-mobile","query":"AI meetups in Berlin","provider":"Meetup","status":"finished","results":[{"id":"evt-1","provider":"Meetup","title":"AI & Machine Learning Berlin Meetup – Spring Edition","description":"Join us for an evening of talks on LLMs, RAG architectures, and production AI.","url":"https://www.meetup.com/example-ai-berlin","date_start":"2026-03-15T19:00:00","date_end":"2026-03-15T22:00:00","timezone":"Europe/Berlin","event_type":"PHYSICAL","venue":{"name":"Factory Berlin","city":"Berlin","country":"Germany"},"organizer":{"name":"AI Berlin Community"},"rsvp_count":142,"is_paid":false},{"id":"evt-2","provider":"Meetup","title":"Web Dev Online: TypeScript Deep Dive","description":"A live online session covering advanced TypeScript patterns for scalable apps.","url":"https://www.meetup.com/example-webdev-online","date_start":"2026-03-20T18:00:00","date_end":"2026-03-20T20:00:00","timezone":"UTC","event_type":"ONLINE","venue":null,"organizer":{"name":"Web Dev Community"},"rsvp_count":87,"is_paid":false},{"id":"evt-3","provider":"Meetup","title":"Product Management Summit – London","description":"Two-day conference covering product strategy, user research, and growth tactics.","url":"https://www.meetup.com/example-pm-london","date_start":"2026-04-05T09:00:00","date_end":"2026-04-06T17:00:00","timezone":"Europe/London","event_type":"PHYSICAL","venue":{"name":"The Barbican","city":"London","country":"United Kingdom"},"organizer":{"name":"PM London"},"rsvp_count":320,"is_paid":true,"fee":{"amount":25,"currency":"GBP"}}],"isMobile":true}}],
    "events/EventEmbedPreview.svelte":[{"name":"online","props":{"id":"preview-event-embed-online","event":{"embed_id":"preview-event-embed-online","id":"evt-preview-online","provider":"meetup","title":"TypeScript Deep Dive: Advanced Patterns for Scalable Apps","description":"A live online session covering generic constraints, conditional types, and module augmentation.","url":"https://www.meetup.com/example-webdev-online/events/preview","date_start":"2026-03-20T18:00:00Z","date_end":"2026-03-20T20:00:00Z","timezone":"UTC","event_type":"ONLINE","venue":null,"organizer":{"id":"org-webdev","name":"Web Dev Community","slug":"webdev"},"rsvp_count":87,"is_paid":false,"fee":null,"image_url":null},"isMobile":false}},{"name":"paid","props":{"id":"preview-event-embed-paid","event":{"embed_id":"preview-event-embed-paid","id":"evt-preview-paid","provider":"meetup","title":"Product Management Summit – London 2026","description":"Two-day conference covering product strategy, user research, and growth tactics.","url":"https://www.meetup.com/example-pm-london/events/preview","date_start":"2026-04-05T09:00:00+01:00","date_end":"2026-04-06T17:00:00+01:00","timezone":"Europe/London","event_type":"PHYSICAL","venue":{"name":"The Barbican","address":"Silk St","city":"London","state":null,"country":"United Kingdom","lat":51.521,"lon":-0.093},"organizer":{"id":"org-pm-london","name":"PM London","slug":"pm-london"},"rsvp_count":320,"is_paid":true,"fee":{"amount":25,"currency":"GBP"},"image_url":null},"isMobile":false}},{"name":"mobile","props":{"id":"preview-event-embed-mobile","event":{"embed_id":"preview-event-embed-1","id":"evt-preview-1","provider":"meetup","title":"AI & Machine Learning Berlin Meetup – Spring Edition","description":"Join us for an evening of talks on large language models, RAG architectures, and deploying AI to production. Speakers from leading Berlin AI companies.\n\nSchedule:\n- 18:30 Doors open\n- 19:00 Talk 1: LLMs in Production\n- 19:45 Talk 2: RAG Architectures\n- 20:30 Networking","url":"https://www.meetup.com/example-ai-berlin/events/preview","date_start":"2026-03-15T19:00:00+01:00","date_end":"2026-03-15T22:00:00+01:00","timezone":"Europe/Berlin","event_type":"PHYSICAL","venue":{"name":"Factory Berlin","address":"Rheinsberger Str. 76-77","city":"Berlin","state":null,"country":"Germany","lat":52.5393,"lon":13.4028},"organizer":{"id":"org-ai-berlin","name":"AI Berlin Community","slug":"ai-berlin"},"rsvp_count":142,"is_paid":false,"fee":null,"image_url":null},"isMobile":true}}],
    "file/FileEmbedPreview.svelte":[],
    "finance/FinanceCheckAccountsEmbedPreview.svelte":[{"name":"mobile","props":{"id":"preview-finance-check-accounts-mobile","status":"finished","period":"monthly","accountCount":2,"transactionCount":5,"overview":{"accounts":[{"account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","display_label":"Operating EUR","currency":"EUR","balance":8450.25,"balance_as_of":"2026-07-15"},{"account_ref":"acct-savings-eur","source_ref":"revolut_business:connected-account","display_label":"Savings EUR","currency":"EUR","balance":12500,"balance_as_of":"2026-07-15"}],"transactions":[{"transaction_ref":"revolut_business:tx-001","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-05-05","amount":4200,"currency":"EUR","direction":"income","category":"revenue","counterparty_placeholder":"[PAYER_REVENUE_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-002","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-05-08","amount":-760.8,"currency":"EUR","direction":"expense","category":"software","counterparty_placeholder":"[MERCHANT_SOFTWARE_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-003","account_ref":"acct-savings-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-06-03","amount":3800,"currency":"EUR","direction":"income","category":"revenue","counterparty_placeholder":"[PAYER_REVENUE_002]","state":"completed"},{"transaction_ref":"revolut_business:tx-004","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-06-12","amount":-1180.45,"currency":"EUR","direction":"expense","category":"travel","counterparty_placeholder":"[MERCHANT_TRAVEL_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-005","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-07-02","amount":-350,"currency":"EUR","direction":"expense","category":"meals","counterparty_placeholder":"[MERCHANT_MEALS_001]","state":"completed"}],"summaries":{"period":"monthly","income_total":8000,"expense_total":2291.25,"net_total":5708.75,"by_category":{"revenue":{"income":8000,"expense":0,"net":8000},"software":{"income":0,"expense":760.8,"net":-760.8},"travel":{"income":0,"expense":1180.45,"net":-1180.45},"meals":{"income":0,"expense":350,"net":-350}},"time_series":[{"bucket":"2026-05","income":4200,"expense":760.8,"net":3439.2,"transaction_count":2},{"bucket":"2026-06","income":3800,"expense":1180.45,"net":2619.55,"transaction_count":2},{"bucket":"2026-07","income":0,"expense":350,"net":-350,"transaction_count":1}],"filters_applied":{}},"filter_options":{"accounts":["acct-main-eur","acct-savings-eur"],"sources":["revolut_business:connected-account"],"categories":["meals","revenue","software","travel"],"directions":["expense","income"],"states":["completed"],"placeholders":["[MERCHANT_MEALS_001]","[MERCHANT_SOFTWARE_001]","[MERCHANT_TRAVEL_001]","[PAYER_REVENUE_001]","[PAYER_REVENUE_002]"]}},"provider":"Revolut Business","summary":"Finance overview for 2 accounts and 5 transactions: income 8000, expenses 2291.25.","isMobile":true}},{"name":"processing","props":{"id":"preview-finance-check-accounts-processing","status":"processing","period":"monthly","accountCount":0,"transactionCount":0,"overview":null,"provider":"Revolut Business","summary":"Checking connected accounts and statements...","isMobile":false}}],
    "fitness/FitnessSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-fitness-search-processing","skillId":"search_classes","query":"yoga near Sorauer Str. 12","provider":"Urban Sports Club","summary":"Found 2 Urban Sports classes in onsite mode. Searched all Urban Sports plans.","filters":{"query":"yoga","address":"Sorauer Str. 12, Berlin","radius_km":3,"plan":"all","attendance_mode":"onsite"},"status":"processing","results":[],"result_count":0,"isMobile":false}},{"name":"locations","props":{"id":"preview-fitness-search-locations","skillId":"search_locations","query":"HIIT near Sorauer Str. 12","provider":"Urban Sports Club","summary":"Found 1 Urban Sports locations. Searched all Urban Sports plans.","filters":{"query":"HIIT","address":"Sorauer Str. 12, Berlin","radius_km":2,"plan":"all"},"status":"finished","results":[{"id":"beat81-paul-lincke-ufer","provider":"Urban Sports Club","venue_id":"beat81-paul-lincke-ufer","name":"BEAT81 - Paul-Lincke-Ufer","address":"Paul-Lincke-Ufer 19, 10999 Berlin","distance_km":0.7,"disciplines":["HIIT","Strength"],"plans_required":["Premium","Max"],"url":"https://urbansportsclub.com/en/venues/beat81-paul-lincke-ufer"}],"result_count":1,"isMobile":false}},{"name":"mobile","props":{"id":"preview-fitness-search-mobile","skillId":"search_classes","query":"yoga near Sorauer Str. 12","provider":"Urban Sports Club","summary":"Found 2 Urban Sports classes in onsite mode. Searched all Urban Sports plans.","filters":{"query":"yoga","address":"Sorauer Str. 12, Berlin","radius_km":3,"plan":"all","attendance_mode":"onsite"},"status":"finished","results":[{"id":"appointment-1","provider":"Urban Sports Club","appointment_id":"appointment-1","name":"Morning Yoga Flow","category":"Yoga","attendance_mode":"onsite","date":"2026-07-10","time_range":"07:30 - 08:30","venue_name":"Yoga Studio Kreuzberg","venue_address":"Oranienstr. 1, 10997 Berlin","distance_km":0.9,"spots_display":"5 spots left","plans_required":["Classic","Premium","Max"],"detail_url":"https://urbansportsclub.com/en/class-details/appointment-1"},{"id":"appointment-2","provider":"Urban Sports Club","appointment_id":"appointment-2","name":"HIIT Strength","category":"HIIT","attendance_mode":"onsite","date":"2026-07-10","time_range":"18:00 - 19:00","venue_name":"BEAT81 - Paul-Lincke-Ufer","venue_address":"Paul-Lincke-Ufer 19, 10999 Berlin","distance_km":0.7,"spots_display":"3 spots left","plans_required":["Premium","Max"],"detail_url":"https://urbansportsclub.com/en/class-details/appointment-2"}],"result_count":2,"isMobile":true}}],
    "fitness/FitnessResultEmbedPreview.svelte":[{"name":"location","props":{"id":"fitness-result-preview","result":{"id":"location-1","name":"Yoga Studio Kreuzberg","address":"Oranienstr. 1, 10997 Berlin","distance_km":0.9,"disciplines":["Yoga","Pilates"]},"skillId":"search_locations"}}],
    "health/HealthSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-health-search-processing","query":"Ophthalmologist in Munich","provider":"Doctolib, Jameda","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-health-search-error","query":"Ophthalmologist in Munich","provider":"Doctolib, Jameda","status":"error","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-health-search-mobile","query":"Ophthalmologist in Munich","provider":"Doctolib, Jameda","status":"finished","results":[{"type":"appointment","slot_datetime":"2026-04-03T08:00:00","name":"Dr. Markus Reinholz","speciality":"Hautarzt / Dermatologe","address":"Frauenplatz 11, 80331 München","insurance":"","telehealth":false},{"type":"appointment","slot_datetime":"2026-04-03T10:30:00","name":"Dr. Sophie Müller","speciality":"Ophthalmologist","address":"Maximilianstraße 12, 80539 Munich","insurance":"public","telehealth":false},{"type":"appointment","slot_datetime":"2026-04-05T14:00:00","name":"Prof. Dr. Klaus Weber","speciality":"Ophthalmologist","address":"Leopoldstraße 45, 80802 Munich","insurance":"private","telehealth":true}],"isMobile":true}},{"name":"singleResult","props":{"id":"preview-health-search-single","query":"Neurologist in Hamburg","provider":"Doctolib, Jameda","status":"finished","results":[{"type":"appointment","slot_datetime":"2026-04-03T10:00:00","name":"Jan Philipp Buschmann","speciality":"Neurologe","address":"Hoheluftchaussee 2, 20253 Hamburg"}],"isMobile":false}}],
    "health/HealthAppointmentEmbedPreview.svelte":[{"name":"telehealth","props":{"id":"preview-health-appointment-telehealth","slotDatetime":"2026-04-05T14:00:00","name":"Prof. Dr. Klaus Weber","speciality":"Cardiologist","address":"Leopoldstraße 45\n80802 Munich","insurance":"private","telehealth":true,"status":"finished","isMobile":false,"providerPlatform":"Doctolib"}},{"name":"jameda","props":{"id":"preview-health-appointment-jameda","slotDatetime":"2026-04-03T08:00:00","name":"Dr. Markus Reinholz","speciality":"Hautarzt / Dermatologe","address":"Frauenplatz 11, 80331 München","insurance":"","telehealth":false,"status":"finished","isMobile":false,"rating":5,"price":120,"providerPlatform":"Jameda"}},{"name":"jamedaNoPrice","props":{"id":"preview-health-appointment-jameda-no-price","slotDatetime":"2026-04-03T09:30:00","name":"Konrad Witkowski","speciality":"Zahnarzt","address":"Hoheluftchaussee 2, 20253 Hamburg","insurance":"public","telehealth":false,"status":"finished","isMobile":false,"rating":4.8,"providerPlatform":"Jameda"}},{"name":"mobile","props":{"id":"preview-health-appointment-mobile","slotDatetime":"2026-04-03T10:30:00","name":"Dr. Sophie Müller","speciality":"Ophthalmologist","address":"Maximilianstraße 12\n80539 Munich","insurance":"public","telehealth":false,"status":"finished","isMobile":true}},{"name":"mobileJameda","props":{"id":"preview-health-appointment-mobile-jameda","slotDatetime":"2026-04-03T10:30:00","name":"Beatrice Kochanek","speciality":"Frauenärztin / Gynäkologin","address":"Aachener Str. 56, 50674 Köln","insurance":"public","telehealth":false,"status":"finished","isMobile":true,"rating":5,"price":80,"providerPlatform":"Jameda"}}],
    "home/HomeSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-home-search-processing","query":"Berlin","provider":"Multi","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-home-search-error","query":"invalid city","provider":"Multi","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-home-search-cancelled","query":"Berlin","provider":"Multi","status":"cancelled","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-home-search-mobile","query":"Berlin","provider":"Multi","status":"finished","results":[{"title":"Schöne 2-Zimmer-Wohnung in Kreuzberg","price_label":"850 EUR/month","size_sqm":55,"rooms":2,"address":"Bergmannstr., 10961 Berlin","image_url":"","url":"https://www.immobilienscout24.de/expose/12345","provider":"ImmoScout24","listing_type":"rent"},{"title":"WG-Zimmer in Prenzlauer Berg","price_label":"500 EUR/month","size_sqm":18,"rooms":1,"address":"Schönhauser Allee, 10439 Berlin","image_url":"","url":"https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html","provider":"WG-Gesucht","listing_type":"rent"},{"title":"Helle 3-Zimmer-Altbauwohnung mit Balkon","price_label":"1.200 EUR/month","size_sqm":85,"rooms":3,"address":"Friedrichshain, 10245 Berlin","image_url":"","url":"https://www.kleinanzeigen.de/s-anzeige/67890","provider":"Kleinanzeigen","listing_type":"rent"}],"isMobile":true}}],
    "home/HomeListingEmbedPreview.svelte":[{"name":"wgRoom","props":{"embed_id":"preview-listing-wg","title":"Gemütliches WG-Zimmer in Prenzlauer Berg","price_label":"500 EUR/month","size_sqm":18,"rooms":1,"address":"Schönhauser Allee, 10439 Berlin","image_url":"","url":"https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html","provider":"WG-Gesucht","listing_type":"rent"}},{"name":"kleinanzeigen","props":{"embed_id":"preview-listing-ka","title":"Helle 3-Zimmer-Altbauwohnung mit Balkon und EBK","price_label":"1.200 EUR/month","size_sqm":85,"rooms":3,"address":"Friedrichshain, 10245 Berlin","image_url":"","url":"https://www.kleinanzeigen.de/s-anzeige/67890","provider":"Kleinanzeigen","listing_type":"rent"}},{"name":"buyListing","props":{"embed_id":"preview-listing-buy","title":"Eigentumswohnung in München-Schwabing","price_label":"450.000 EUR","size_sqm":75,"rooms":3,"address":"Leopoldstr., 80802 München","image_url":"","url":"https://www.immobilienscout24.de/expose/99999","provider":"ImmoScout24","listing_type":"buy"}},{"name":"minimal","props":{"embed_id":"preview-listing-minimal","title":"Wohnung zur Miete","price_label":"Price on request","size_sqm":55,"rooms":2,"address":"Berlin","image_url":"","url":"https://www.kleinanzeigen.de/s-anzeige/00000","provider":"Kleinanzeigen","listing_type":"rent"}}],
    "images/ImageGenerateEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-image-gen-processing","skillId":"generate","prompt":"A futuristic cityscape with flying cars and neon lights","model":"flux-schnell","status":"processing","isMobile":false}},{"name":"draft","props":{"id":"preview-image-gen-draft","skillId":"generate_draft","prompt":"Quick sketch of a cat wearing a top hat","model":"flux-schnell","status":"finished","isMobile":false}},{"name":"error","props":{"id":"preview-image-gen-error","skillId":"generate","prompt":"Something that caused an error","model":"flux-schnell","status":"error","isMobile":false,"error":"Image generation failed: content policy violation"}},{"name":"mobile","props":{"id":"preview-image-gen-mobile","skillId":"generate","prompt":"A serene mountain landscape at sunset with vibrant orange and purple skies","model":"flux-schnell","status":"finished","isMobile":true}}],
    "images/ImageEmbedPreview.svelte":[{"name":"legacyEncrypted","props":{"id":"preview-image-embed-legacy-encrypted","filename":"legacy-encrypted.png","status":"finished","isMobile":false,"s3BaseUrl":"https://fixture.invalid","s3Files":{"preview":{"width":64,"height":64,"size_bytes":0,"format":"png","s3_key":"e2e/media-encryption/legacy.png"}},"aesKey":"AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=","aesNonce":"AAECAwQFBgcICQoL"}},{"name":"v2Encrypted","props":{"id":"preview-image-embed-v2-encrypted","filename":"v2-encrypted.png","status":"finished","isMobile":false,"s3BaseUrl":"https://fixture.invalid","s3Files":{"preview":{"width":64,"height":64,"size_bytes":0,"format":"png","s3_key":"e2e/media-encryption/v2.png","encryption":"aes-gcm-nonce-prefixed-v1"}},"aesKey":"AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="}},{"name":"uploading","props":{"id":"preview-image-embed-uploading","filename":"golden-gate-sunset.jpg","status":"uploading","isMobile":false}},{"name":"error","props":{"id":"preview-image-embed-error","filename":"golden-gate-sunset.jpg","status":"error","isMobile":false,"uploadError":"Upload failed: file too large (max 10 MB)"}},{"name":"longFilename","props":{"id":"preview-image-embed-long-name","filename":"my-very-long-vacation-photo-at-the-golden-gate-bridge-2026.jpg","status":"finished","isMobile":false}},{"name":"mobile","props":{"id":"preview-image-embed-mobile","filename":"golden-gate-sunset.jpg","status":"finished","isMobile":true}}],
    "images/ImagesSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-images-search-processing","query":"Golden Gate Bridge","provider":"Brave","status":"processing","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-images-search-mobile","query":"Golden Gate Bridge","provider":"Brave","status":"finished","results":[{"title":"Golden Gate Bridge at dusk","source":"unsplash.com","thumbnail_url":"https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200","image_url":"https://images.unsplash.com/photo-1501594907352-04cda38ebc29","source_page_url":"https://unsplash.com/photos/Cs99I6PYLlk"},{"title":"Aerial view of Golden Gate","source":"unsplash.com","thumbnail_url":"https://images.unsplash.com/photo-1506146332389-18140dc7b2fb?w=200","image_url":"https://images.unsplash.com/photo-1506146332389-18140dc7b2fb","source_page_url":"https://unsplash.com/photos/golden-gate-aerial"},{"title":"Golden Gate Bridge towers in fog","source":"unsplash.com","thumbnail_url":"https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=200","image_url":"https://images.unsplash.com/photo-1558618666-fcd25c85cd64","source_page_url":"https://unsplash.com/photos/golden-gate-bridge"}],"isMobile":true}}],
    "images/ImageResultEmbedPreview.svelte":[{"name":"alternate","props":{"id":"preview-image-result-alternate","title":"Golden Gate Bridge from Baker Beach","sourceDomain":"unsplash.com","thumbnailUrl":"https://images.unsplash.com/photo-1449034446853-66c86144b0ad?w=200","imageUrl":"https://images.unsplash.com/photo-1449034446853-66c86144b0ad","status":"finished","isMobile":false}},{"name":"processing","props":{"id":"preview-image-result-processing","title":"Golden Gate Bridge at dusk","sourceDomain":"unsplash.com","status":"processing","isMobile":false}},{"name":"mobile","props":{"id":"preview-image-result-mobile","title":"Golden Gate Bridge at dusk","sourceDomain":"unsplash.com","thumbnailUrl":"https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200","imageUrl":"https://images.unsplash.com/photo-1501594907352-04cda38ebc29","status":"finished","isMobile":true}}],
    "mail/MailEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-mail-processing","receiver":"anna@openmates.dev","subject":"Project Update — Sprint 12 Review","content":"Hi Anna,\n\nThe latest sprint review went well. All tickets were closed except the auth refactor, which is carried over to Sprint 13.\n\nKey highlights:\n- Login flow redesigned (done)\n- API rate limiting added (done)\n- Auth refactor (carried over)\n\nLet me know if you have any questions.\n\nBest,\nMax","status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-mail-error","receiver":"anna@openmates.dev","subject":"Project Update — Sprint 12 Review","content":"Hi Anna,\n\nThe latest sprint review went well. All tickets were closed except the auth refactor, which is carried over to Sprint 13.\n\nKey highlights:\n- Login flow redesigned (done)\n- API rate limiting added (done)\n- Auth refactor (carried over)\n\nLet me know if you have any questions.\n\nBest,\nMax","status":"error","isMobile":false}},{"name":"short","props":{"id":"preview-mail-short","receiver":"team@openmates.dev","subject":"Quick update","content":"All systems nominal. Deploy scheduled for 18:00.","status":"finished","isMobile":false}},{"name":"mobile","props":{"id":"preview-mail-mobile","receiver":"anna@openmates.dev","subject":"Project Update — Sprint 12 Review","content":"Hi Anna,\n\nThe latest sprint review went well. All tickets were closed except the auth refactor, which is carried over to Sprint 13.\n\nKey highlights:\n- Login flow redesigned (done)\n- API rate limiting added (done)\n- Auth refactor (carried over)\n\nLet me know if you have any questions.\n\nBest,\nMax","status":"finished","isMobile":true}}],
    "mail/MailSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-mail-search-processing","query":"invoice","provider":"Proton Mail","status":"processing","results":[],"isMobile":false}},{"name":"recent","props":{"id":"preview-mail-search-recent","query":"Recent emails","provider":"Proton Mail","status":"finished","results":[{"uid":"1","subject":"Invoice #1042 - OpenMates B.V.","from":"billing@acme.com","to":"admin@openmates.org","snippet":"Please find attached invoice #1042 for services rendered in February 2026.","date":"Thu, 28 Feb 2026 10:00:00 +0100","timestamp":1740733200,"is_unread":true},{"uid":"2","subject":"Server maintenance scheduled","from":"ops@provider.com","to":"admin@openmates.org","snippet":"Scheduled maintenance window: Saturday 22:00-02:00 UTC.","date":"Wed, 27 Feb 2026 14:30:00 +0100","timestamp":1740659400,"is_unread":false},{"uid":"3","subject":"New contributor joined","from":"github-noreply@github.com","to":"admin@openmates.org","snippet":"A new contributor has opened a pull request in OpenMates/OpenMates.","date":"Mon, 25 Feb 2026 08:00:00 +0100","timestamp":1740470400,"is_unread":false}],"isMobile":false}},{"name":"empty","props":{"id":"preview-mail-search-empty","query":"proton bridge xyz","provider":"Proton Mail","status":"finished","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-mail-search-mobile","query":"invoice","provider":"Proton Mail","status":"finished","results":[{"uid":"1","subject":"Invoice #1042 - OpenMates B.V.","from":"billing@acme.com","to":"admin@openmates.org","snippet":"Please find attached invoice #1042 for services rendered in February 2026.","date":"Thu, 28 Feb 2026 10:00:00 +0100","timestamp":1740733200,"is_unread":true},{"uid":"2","subject":"Server maintenance scheduled","from":"ops@provider.com","to":"admin@openmates.org","snippet":"Scheduled maintenance window: Saturday 22:00-02:00 UTC.","date":"Wed, 27 Feb 2026 14:30:00 +0100","timestamp":1740659400,"is_unread":false},{"uid":"3","subject":"New contributor joined","from":"github-noreply@github.com","to":"admin@openmates.org","snippet":"A new contributor has opened a pull request in OpenMates/OpenMates.","date":"Mon, 25 Feb 2026 08:00:00 +0100","timestamp":1740470400,"is_unread":false}],"isMobile":true}}],
    "maps/MapsSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-maps-search-processing","query":"restaurants near Brandenburg Gate","provider":"Google","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-maps-search-error","query":"invalid location search","provider":"Google","status":"error","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-maps-search-mobile","query":"coffee shops near Marienplatz Munich","provider":"Google","status":"finished","results":[{"name":"Man vs. Machine Coffee Roasters","address":"Müllerstraße 23, 80469 Munich","rating":4.7,"reviews":1832,"type":"Coffee shop","latitude":48.1321,"longitude":11.5718},{"name":"Lost Weekend","address":"Schellingstraße 3, 80799 Munich","rating":4.5,"reviews":2456,"type":"Coffee shop & bookstore","latitude":48.1523,"longitude":11.5784},{"name":"Café Frischhut","address":"Prälat-Zistl-Straße 8, 80331 Munich","rating":4.6,"reviews":3210,"type":"Traditional café","latitude":48.1354,"longitude":11.5762}],"isMobile":true}}],
    "maps/MapsLocationEmbedPreview.svelte":[{"name":"nearbyArea","props":{"id":"preview-maps-location-area","name":"Nearby location","address":"Near Potsdamer Platz, Berlin","locationType":"area","placeType":"","status":"finished","isMobile":false}},{"name":"noImage","props":{"id":"preview-maps-location-no-image","name":"Berlin Hauptbahnhof","address":"Europaplatz 1, 10557 Berlin","locationType":"precise_location","placeType":"airport","status":"finished","isMobile":false}},{"name":"processing","props":{"id":"preview-maps-location-processing","name":"Berlin Hauptbahnhof","address":"Europaplatz 1, 10557 Berlin","locationType":"precise_location","placeType":"railway","status":"processing","isMobile":false}},{"name":"mobile","props":{"id":"preview-maps-location-mobile","name":"Berlin Hauptbahnhof","address":"Europaplatz 1, 10557 Berlin","locationType":"precise_location","placeType":"railway","mapImageUrl":"data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20640%20360%22%3E%3Crect%20width%3D%22640%22%20height%3D%22360%22%20fill%3D%22%23e5e7eb%22%2F%3E%3Ctext%20x%3D%22320%22%20y%3D%22180%22%20text-anchor%3D%22middle%22%20dominant-baseline%3D%22middle%22%20font-family%3D%22sans-serif%22%20font-size%3D%2232%22%20fill%3D%22%236b7280%22%3EMap%20preview%3C%2Ftext%3E%3C%2Fsvg%3E","status":"finished","isMobile":true}}],
    "math/MathCalculateEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-math-calculate-processing","title":"Trigonometry sanity check","query":"integrate(x^2, x, 0, 1)","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-math-calculate-error","title":"Trigonometry sanity check","query":"1/0","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-math-calculate-cancelled","title":"Trigonometry sanity check","query":"cancelled","status":"cancelled","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-math-calculate-mobile","title":"Trigonometry sanity check","query":"sin(pi/4) + cos(pi/3)","status":"finished","results":[{"expression":"sin(pi/4) + cos(pi/3)","result":"1.20710678118655","result_type":"float","mode":"numeric"}],"isMobile":true}}],
    "math/MathPlotEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-math-plot-processing","plotSpec":"","status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-math-plot-error","plotSpec":"invalid_func(","status":"error","isMobile":false}},{"name":"cancelled","props":{"id":"preview-math-plot-cancelled","plotSpec":"","status":"cancelled","isMobile":false}},{"name":"mobile","props":{"id":"preview-math-plot-mobile","plotSpec":"f(x) = sin(x)\nf(x) = cos(x)","status":"finished","isMobile":true}}],
    "mindmaps/MindMapEmbedPreview.svelte":[],
    "models3d/Model3DSearchEmbedPreview.svelte":[],
    "models3d/Model3DResultEmbedPreview.svelte":[],
    "models3d/Model3DGenerateEmbedPreview.svelte":[],
    "music/MusicGenerateEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-music-generate-processing","prompt":"A cinematic intro sting with gentle strings and warm piano","mode":"background","model":"lyria-3-clip-preview","durationSeconds":30,"status":"processing","isMobile":false}},{"name":"jingle","props":{"id":"preview-music-generate-jingle","prompt":"An upbeat electronic product jingle with warm synth bass","mode":"jingle","model":"lyria-3-pro-preview","durationSeconds":45,"status":"finished","isMobile":false}},{"name":"error","props":{"id":"preview-music-generate-error","prompt":"A 30 second ambient synth background loop with soft pads and no drums","mode":"background","model":"lyria-3-clip-preview","durationSeconds":30,"status":"error","isMobile":false,"error":"Music generation failed: provider returned no audio output"}},{"name":"mobile","props":{"id":"preview-music-generate-mobile","prompt":"A 30 second ambient synth background loop with soft pads and no drums","mode":"background","model":"lyria-3-clip-preview","durationSeconds":30,"status":"finished","isMobile":true}}],
    "news/NewsSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-news-search-processing","query":"searching for news...","provider":"Brave Search","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-news-search-error","query":"failed news search","provider":"Brave Search","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-news-search-cancelled","query":"cancelled news search","provider":"Brave Search","status":"cancelled","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-news-search-mobile","query":"latest technology news 2026","provider":"Brave Search","status":"finished","results":[{"title":"AI Advances Continue to Transform Software Development","url":"https://techcrunch.com/2026/ai-advances","description":"New AI-powered development tools are changing how developers write, test, and deploy software.","favicon":"/favicon.png","thumbnail":{"original":"/images/og-image.jpg"},"publishedAt":"2026-02-15T08:00:00Z"},{"title":"WebAssembly 3.0 Specification Finalized","url":"https://theverge.com/2026/wasm-3","description":"The W3C has finalized the WebAssembly 3.0 specification, bringing garbage collection and improved threading.","favicon":"/favicon.png","thumbnail":{"original":"/images/og-image.jpg"},"publishedAt":"2026-02-10T12:00:00Z"},{"title":"European Tech Scene Sees Record Venture Capital Investment","url":"https://bbc.com/news/eu-vc","description":"European startups raised a record €45 billion in venture capital funding in Q4 2025.","favicon":"/favicon.png","thumbnail":{"original":"/images/og-image.jpg"},"publishedAt":"2026-01-28T09:00:00Z"}],"isMobile":true}}],
    "web/WebsiteEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-website-processing","url":"https://svelte.dev/loading-page","title":"Svelte — Cybernetically enhanced web apps","description":"Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.","favicon":"https://svelte.dev/favicon.png","image":"","status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-website-error","url":"https://svelte.dev/broken-link","title":"Svelte — Cybernetically enhanced web apps","description":"Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.","favicon":"https://svelte.dev/favicon.png","image":"","status":"error","isMobile":false}},{"name":"richMetadata","props":{"id":"preview-website-rich","url":"https://github.com/sveltejs/svelte","title":"sveltejs/svelte: Cybernetically enhanced web apps","description":"The official Svelte repository on GitHub. Contribute to the future of frontend development.","favicon":"https://github.githubassets.com/favicons/favicon.svg","image":"","status":"finished","isMobile":false}},{"name":"mobile","props":{"id":"preview-website-mobile","url":"https://svelte.dev","title":"Svelte — Cybernetically enhanced web apps","description":"Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.","favicon":"https://svelte.dev/favicon.png","image":"","status":"finished","isMobile":true}}],
    "nutrition/NutritionSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-nutrition-search-processing","query":"schnelle Abendessen Rezepte","provider":"Edamam","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-nutrition-search-error","query":"vegane Kuchen","provider":"Edamam","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-nutrition-search-cancelled","query":"low carb Rezepte","provider":"Edamam","status":"cancelled","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-nutrition-search-mobile","query":"vegetarische Pasta","provider":"Edamam","status":"finished","results":[{"uid":"edamam-recipe-001","title":"Spaghetti Aglio e Olio","description":"Klassisches italienisches Knoblauch-Pasta-Gericht","image_url":null,"total_time_minutes":25,"difficulty":"einfach","rating":4.7,"rating_count":342,"dietary_tags":["vegetarisch"],"servings":4},{"uid":"edamam-recipe-002","title":"Penne Arrabiata mit frischen Tomaten","description":"Scharfe Tomatensoße mit Penne","image_url":null,"total_time_minutes":30,"difficulty":"einfach","rating":4.5,"rating_count":218,"dietary_tags":["vegan"],"servings":4},{"uid":"edamam-recipe-003","title":"Tagliatelle mit Pilzrahmsauce","description":"Cremige Pilzsauce mit frischen Kräutern","image_url":null,"total_time_minutes":35,"difficulty":"mittel","rating":4.8,"rating_count":156,"dietary_tags":["vegetarisch"],"servings":2}],"isMobile":true}}],
    "nutrition/NutritionRecipeEmbedPreview.svelte":[{"name":"multiTag","props":{"id":"preview-nutrition-recipe-multi-tag","title":"Vegane Gemüse-Lasagne ohne Gluten","description":"Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl und Chili","image_url":null,"total_time_minutes":60,"difficulty":"mittel","rating":4.3,"rating_count":89,"dietary_tags":["vegan","glutenfrei","laktosefrei"],"servings":4,"status":"finished","isMobile":false}},{"name":"hardRecipe","props":{"id":"preview-nutrition-recipe-hard","title":"Beef Wellington mit Trüffel-Duxelles","description":"Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl und Chili","image_url":null,"total_time_minutes":180,"difficulty":"schwer","rating":4.9,"rating_count":56,"dietary_tags":[],"servings":6,"status":"finished","isMobile":false}},{"name":"minimal","props":{"id":"preview-nutrition-recipe-minimal","title":"Einfacher Gurkensalat","description":"Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl und Chili","image_url":null,"total_time_minutes":25,"difficulty":"einfach","rating":4.7,"rating_count":342,"dietary_tags":["vegetarisch"],"servings":4,"status":"finished","isMobile":false}},{"name":"mobile","props":{"id":"preview-nutrition-recipe-mobile","title":"Spaghetti Aglio e Olio","description":"Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl und Chili","image_url":null,"total_time_minutes":25,"difficulty":"einfach","rating":4.7,"rating_count":342,"dietary_tags":["vegetarisch"],"servings":4,"status":"finished","isMobile":true}}],
    "pdf/PDFEmbedPreview.svelte":[{"name":"uploading","props":{"id":"preview-pdf-uploading","filename":"Q4-2025-Annual-Report.pdf","status":"uploading","pageCount":42,"isMobile":false}},{"name":"processing","props":{"id":"preview-pdf-processing","filename":"architecture-whitepaper.pdf","status":"processing","pageCount":12,"isMobile":false}},{"name":"error","props":{"id":"preview-pdf-error","filename":"corrupted-file.pdf","status":"error","pageCount":42,"isMobile":false,"uploadError":"Upload failed: file may be corrupted"}},{"name":"singlePage","props":{"id":"preview-pdf-single","filename":"invoice.pdf","status":"finished","pageCount":1,"isMobile":false}},{"name":"mobile","props":{"id":"preview-pdf-mobile","filename":"Q4-2025-Annual-Report.pdf","status":"finished","pageCount":42,"isMobile":true}}],
    "reminder/ReminderEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-reminder-processing","reminderId":"rem-abc-123","triggerAtFormatted":"Tomorrow at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":false,"prompt":"Setting up your reminder...","message":"Reminder set successfully! I will remind you tomorrow at 9:00 AM.","status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-reminder-error","reminderId":"rem-abc-123","triggerAtFormatted":"Tomorrow at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":false,"prompt":"Remind me about the meeting","message":"Reminder set successfully! I will remind you tomorrow at 9:00 AM.","status":"error","isMobile":false,"error":"Could not create reminder: invalid trigger time."}},{"name":"repeating","props":{"id":"preview-reminder-repeating","reminderId":"rem-abc-123","triggerAtFormatted":"Every Monday at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":true,"prompt":"Weekly standup meeting preparation","message":"Repeating reminder set! I will remind you every Monday at 9:00 AM.","status":"finished","isMobile":false}},{"name":"existingChat","props":{"id":"preview-reminder-existing-chat","reminderId":"rem-abc-123","triggerAtFormatted":"Tomorrow at 9:00 AM","triggerAt":1773649800,"targetType":"existing_chat","isRepeating":false,"prompt":"Follow up on the design review feedback","message":"Reminder set! I will send a message in this chat tomorrow at 9:00 AM.","status":"finished","isMobile":false}},{"name":"withEmailWarning","props":{"id":"preview-reminder-email-warning","reminderId":"rem-abc-123","triggerAtFormatted":"Tomorrow at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":false,"prompt":"Review the pull request for the new authentication module","message":"Reminder set successfully! I will remind you tomorrow at 9:00 AM.","status":"finished","isMobile":false,"emailNotificationWarning":"Email notifications are not enabled. You will only receive in-app notifications."}},{"name":"mobile","props":{"id":"preview-reminder-mobile","reminderId":"rem-abc-123","triggerAtFormatted":"Tomorrow at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":false,"prompt":"Review the pull request for the new authentication module","message":"Reminder set successfully! I will remind you tomorrow at 9:00 AM.","status":"finished","isMobile":true}}],
    "shopping/ShoppingSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-shopping-search-processing","query":"wireless headphones","provider":"Amazon","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-shopping-search-error","query":"bio joghurt","provider":"REWE","status":"error","results":[],"isMobile":false}},{"name":"amazon","props":{"id":"preview-shopping-search-amazon","query":"noise cancelling headphones","provider":"Amazon","status":"finished","results":[{"asin":"B0CH7DL6JW","title":"Sony WH-1000XM5 Wireless Noise Cancelling Headphones","brand":"Sony","price":"279.00","price_amount":279,"currency_symbol":"€","rating":4.7,"reviews":3842,"prime":true,"image_url":null,"purchase_url":"https://www.amazon.de/dp/B0CH7DL6JW"},{"asin":"B09JQS53RZ","title":"Bose QuietComfort 45 Bluetooth Wireless Headphones","brand":"Bose","price":"249.00","price_amount":249,"currency_symbol":"€","rating":4.6,"reviews":2156,"prime":true,"image_url":null,"purchase_url":"https://www.amazon.de/dp/B09JQS53RZ"}],"isMobile":false}},{"name":"mobile","props":{"id":"preview-shopping-search-mobile","query":"bio joghurt","provider":"REWE","status":"finished","results":[{"product_id":"rewe-12345","title":"Bio Vollmilch-Joghurt Naturell","brand":"Weihenstephan","price_cents":139,"price_eur":"1,39 €","grammage":"500g (0,28 €/100g)","purchase_url":"https://shop.rewe.de/p/weihenstephan-bio-joghurt/12345","image_url":null,"attributes":{"is_organic":true}},{"product_id":"rewe-12346","title":"Demeter Bio-Joghurt mild","brand":"Andechser Natur","price_cents":249,"price_eur":"2,49 €","grammage":"500g (0,50 €/100g)","purchase_url":"https://shop.rewe.de/p/andechser-demeter-joghurt/12346","image_url":null,"attributes":{"is_organic":true,"is_vegetarian":true}},{"product_id":"rewe-12347","title":"Griechischer Joghurt 10% Fett","brand":"REWE Bio","price_cents":189,"price_eur":"1,89 €","grammage":"400g (0,47 €/100g)","purchase_url":"https://shop.rewe.de/p/rewe-bio-griechischer-joghurt/12347","image_url":null,"attributes":{"is_organic":true,"is_vegetarian":true}}],"isMobile":true}}],
    "shopping/ShoppingResultEmbedPreview.svelte":[{"name":"amazon","props":{"id":"preview-shopping-result-amazon","title":"Sony WH-1000XM5 Wireless Noise Cancelling Headphones","brand":"Sony","price_cents":139,"price_eur":"1,39 €","was_price_cents":179,"grammage":"500g (0,28 €/100g)","image_url":null,"attributes":{"is_new":true},"rating":4.7,"reviews":3842,"prime":true,"status":"finished","isMobile":false,"price":"€279.00","price_amount":279,"old_price_amount":329,"currency_symbol":"€"}},{"name":"stoffe","props":{"id":"preview-shopping-result-stoffe","title":"Baumwoll-Musselin - Double Gauze Bestickt Zitronen Weiß","brand":"Snaply","price_cents":139,"price_eur":"15,19 €","was_price_cents":179,"grammage":"500g (0,28 €/100g)","image_url":null,"attributes":{"Baumwolle %":"100","Stoffbreite (cm)":"130","Motiv":"Zitronen"},"rating":4.6,"reviews":832,"prime":false,"status":"finished","isMobile":false,"price":"15,19 €","price_amount":15.19,"base_price":"15,19 € / Meter","stock":20.5,"availability":"Sofort versandfertig, Lieferzeit 2-4 Werktage","color_child_item_ids":["68087513","68087514"]}},{"name":"noPrice","props":{"id":"preview-shopping-result-no-price","title":"Bio Vollmilch-Joghurt Naturell","brand":"Weihenstephan","price_cents":null,"price_eur":null,"was_price_cents":null,"grammage":"500g (0,28 €/100g)","image_url":null,"attributes":{"is_organic":true,"is_vegetarian":true},"rating":4.6,"reviews":832,"prime":false,"status":"finished","isMobile":false,"price":null,"price_amount":null,"old_price_amount":null}},{"name":"mobile","props":{"id":"preview-shopping-result-mobile","title":"Bio Vollmilch-Joghurt Naturell","brand":"Weihenstephan","price_cents":139,"price_eur":"1,39 €","was_price_cents":179,"grammage":"500g (0,28 €/100g)","image_url":null,"attributes":{"is_organic":true,"is_vegetarian":true},"rating":4.6,"reviews":832,"prime":false,"status":"finished","isMobile":true}}],
    "social_media/SocialMediaGetPostsEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-social-media-get-posts-processing","query":"@samplegarden.example","provider":"bluesky_public","result_count":0,"results":[],"status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-social-media-get-posts-error","query":"@samplegarden.example","provider":"bluesky_public","result_count":0,"results":[],"status":"error","isMobile":false}},{"name":"mobile","props":{"id":"preview-social-media-get-posts-mobile","query":"@samplegarden.example","provider":"bluesky_public","result_count":3,"results":[{"platform":"bluesky","page":"@samplegarden.example","posts":[{"platform":"bluesky","page":"@samplegarden.example","title":"Balcony herbs after rain","body":"Mint and basil bounced back fastest after moving the planters closer to the wall. The wind break mattered more than the fertilizer schedule.","author":"samplegarden.example","author_display_name":"Sample Garden Log","published_at":"2026-05-24T08:05:00Z","like_count":129,"reply_count":14,"repost_count":18,"url":"https://bsky.app/profile/samplegarden.example/post/example-1"},{"platform":"bluesky","page":"@samplegarden.example","title":"Compost reminder","body":"The easiest rule I have found: if the bin smells sharp, add dry browns; if nothing changes for a week, add greens and turn once.","author":"samplegarden.example","author_display_name":"Sample Garden Log","published_at":"2026-05-22T11:36:00Z","like_count":88,"reply_count":7,"repost_count":10,"url":"https://bsky.app/profile/samplegarden.example/post/example-2"},{"platform":"bluesky","page":"@samplegarden.example","title":"Seedling notes","body":"Labeling trays with both variety and sowing date made thinning decisions much easier two weeks later.","author":"samplegarden.example","author_display_name":"Sample Garden Log","published_at":"2026-05-19T15:10:00Z","like_count":64,"reply_count":3,"repost_count":6,"url":"https://bsky.app/profile/samplegarden.example/post/example-3"}]}],"status":"finished","isMobile":true}}],
    "social_media/SocialMediaPostEmbedPreview.svelte":[{"name":"textOnly","props":{"id":"preview-social-media-post-text-only","platform":"bluesky","page":"search","title":"Small cafe bar layout notes","body":"A compact espresso bar can still feel calm: warm task lighting, a narrow handoff shelf, and one visible daily special board made this setup feel polished without clutter.","author":"sample.cafe","author_display_name":"Sample Cafe Journal","published_at":"2026-05-24T10:30:00Z","like_count":184,"reply_count":12,"repost_count":27,"url":"https://bsky.app/profile/sample.cafe/post/example-1","status":"finished","isMobile":false}},{"name":"mobile","props":{"id":"preview-social-media-post-mobile","platform":"bluesky","page":"search","title":"Small cafe bar layout notes","body":"A compact espresso bar can still feel calm: warm task lighting, a narrow handoff shelf, and one visible daily special board made this setup feel polished without clutter.","author":"sample.cafe","author_display_name":"Sample Cafe Journal","published_at":"2026-05-24T10:30:00Z","like_count":184,"reply_count":12,"repost_count":27,"url":"https://bsky.app/profile/sample.cafe/post/example-1","status":"finished","isMobile":true}}],
    "social_media/SocialMediaSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-social-media-search-processing","query":"Indie coffee setup inspiration","provider":"bluesky_public","result_count":0,"results":[],"status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-social-media-search-error","query":"Indie coffee setup inspiration","provider":"bluesky_public","result_count":0,"results":[],"status":"error","isMobile":false}},{"name":"mobile","props":{"id":"preview-social-media-search-mobile","query":"Indie coffee setup inspiration","provider":"bluesky_public","result_count":3,"results":[{"platform":"bluesky","page":"search","posts":[{"platform":"bluesky","page":"search","title":"Small cafe bar layout notes","body":"A compact espresso bar can still feel calm: warm task lighting, a narrow handoff shelf, and one visible daily special board made this setup feel polished without clutter.","author":"sample.cafe","author_display_name":"Sample Cafe Journal","published_at":"2026-05-24T10:30:00Z","like_count":184,"reply_count":12,"repost_count":27,"url":"https://bsky.app/profile/sample.cafe/post/example-1"},{"platform":"bluesky","page":"search","title":"Home pourover station","body":"Keeping grinder, scale, filters and kettle on one tray reduced morning friction more than any equipment upgrade.","author":"dailybrew.example","author_display_name":"Daily Brew Notes","published_at":"2026-05-23T18:12:00Z","like_count":96,"reply_count":8,"repost_count":11,"url":"https://bsky.app/profile/dailybrew.example/post/example-2"},{"platform":"bluesky","page":"search","title":"Menu photography tip","body":"Shoot drinks next to the ingredients that define them. Even one citrus peel or spice jar gives people a faster read on flavor.","author":"menu-lab.example","author_display_name":"Menu Lab","published_at":"2026-05-22T14:04:00Z","like_count":73,"reply_count":5,"repost_count":9,"url":"https://bsky.app/profile/menu-lab.example/post/example-3"}]}],"status":"finished","isMobile":true}}],
    "tasks/TaskCreateEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-task-create-processing","instruction":"Create a practical checklist for starting a small balcony herb garden","status":"processing","results":[],"resultCount":0,"isMobile":false}},{"name":"mobile","props":{"id":"preview-task-create-mobile","instruction":"Create a practical checklist for starting a small balcony herb garden","status":"finished","results":[{"embed_id":"legacy-task-garden-1","task_id":"task-garden-1","short_id":"T-104","title":"Buy starter soil and basil seeds","description":"Pick up seed trays, starter soil, and basil seeds before Saturday.","status":"todo","assignee":"user"},{"embed_id":"legacy-task-garden-2","task_id":"task-garden-2","short_id":"T-105","title":"Clear the balcony planter boxes","description":"Remove old roots and rinse the boxes so the spring planting can start.","status":"in_progress","assignee":"user"}],"resultCount":2,"isMobile":true}}],
    "tasks/TaskEmbedPreview.svelte":[{"name":"openmates","props":{"id":"preview-task-openmates","taskId":"task-garden-1","shortId":"T-104","title":"Buy starter soil and basil seeds","description":"Pick up seed trays, starter soil, and basil seeds before Saturday.","status":"in_progress","assignee":"openmates","isMobile":false}},{"name":"mobile","props":{"id":"preview-task-child-mobile","taskId":"task-garden-1","shortId":"T-104","title":"Buy starter soil and basil seeds","description":"Pick up seed trays, starter soil, and basil seeds before Saturday.","status":"todo","assignee":"user","isMobile":true}}],
    "tasks/TaskSearchEmbedPreview.svelte":[{"name":"noResults","props":{"id":"preview-task-search-empty","query":"old tax folder cleanup","status":"finished","results":[],"resultCount":0,"isMobile":false}},{"name":"mobile","props":{"id":"preview-task-search-mobile","query":"packing list tasks","status":"finished","results":[{"embed_id":"legacy-task-packing-1","task_id":"task-packing-1","short_id":"T-221","title":"Pack passport and travel documents","description":"Put passport, train ticket, and hotel confirmation in the front backpack pocket.","status":"todo","assignee":"user"},{"embed_id":"legacy-task-packing-2","task_id":"task-packing-2","short_id":"T-222","title":"Charge camera batteries","description":"Charge both batteries and put the charger in the electronics pouch.","status":"done","assignee":"user"}],"resultCount":2,"isMobile":true}}],
    "travel/TravelSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-travel-search-processing","query":"Munich -> London, 2026-03-15","provider":"Google Flights","status":"processing","results":[],"isMobile":false,"providers":[{"id":"google_flights","name":"Google Flights","icon_url":"https://www.google.com/favicon.ico"}],"legs":[{"origin":"Berlin","destination":"Paris","date":"2026-04-01"}]}},{"name":"empty","props":{"id":"preview-travel-search-empty","query":"Munich -> London, 2026-03-15","provider":"Google Flights","status":"finished","results":[],"isMobile":false,"providers":[{"id":"google_flights","name":"Google Flights","icon_url":"https://www.google.com/favicon.ico"}],"legs":[{"origin":"Hamburg","destination":"Vienna","date":"2026-04-03"}]}},{"name":"error","props":{"id":"preview-travel-search-error","query":"Invalid -> Route","provider":"Google","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-travel-search-cancelled","query":"Munich -> Tokyo","provider":"Google","status":"cancelled","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-travel-search-mobile","query":"Munich -> London, 2026-03-15","provider":"Google","status":"finished","results":[{"price":"189.00","currency":"EUR","transport_method":"airplane","origin":"Munich (MUC)","destination":"London Heathrow (LHR)","departure":"2026-03-15T08:30:00","arrival":"2026-03-15T10:00:00","duration":"2h 30m","stops":0,"carriers":["Lufthansa"]},{"price":"245.50","currency":"EUR","transport_method":"airplane","origin":"Munich (MUC)","destination":"London Gatwick (LGW)","departure":"2026-03-15T14:15:00","arrival":"2026-03-15T17:45:00","duration":"4h 30m","stops":1,"carriers":["British Airways","Eurowings"]}],"isMobile":true}}],
    "travel/TravelConnectionEmbedPreview.svelte":[{"name":"multiStop","props":{"id":"preview-travel-connection-multistop","price":"245.50","currency":"EUR","transportMethod":"airplane","tripType":"one_way","origin":"Munich (MUC)","destination":"London Gatwick (LGW)","departure":"2026-03-15T14:15:00","arrival":"2026-03-15T17:45:00","duration":"4h 30m","stops":1,"carriers":["British Airways","Eurowings"],"bookingProvider":"Lufthansa","carrierCodes":["BA","EW"],"bookableSeats":2,"isCheapest":false,"status":"finished","isMobile":false}},{"name":"roundTrip","props":{"id":"preview-travel-connection-roundtrip","price":"349.00","currency":"EUR","transportMethod":"airplane","tripType":"round_trip","origin":"Munich (MUC)","destination":"London Heathrow (LHR)","departure":"2026-03-15T08:30:00","arrival":"2026-03-15T10:00:00","duration":"2h 30m","stops":0,"carriers":["Lufthansa"],"bookingProvider":"Lufthansa","carrierCodes":["LH"],"bookableSeats":4,"isCheapest":true,"status":"finished","isMobile":false}},{"name":"processing","props":{"id":"preview-travel-connection-processing","price":"189.00","currency":"EUR","transportMethod":"airplane","tripType":"one_way","origin":"Munich (MUC)","destination":"London Heathrow (LHR)","departure":"2026-03-15T08:30:00","arrival":"2026-03-15T10:00:00","duration":"2h 30m","stops":0,"carriers":["Lufthansa"],"bookingProvider":"Lufthansa","carrierCodes":["LH"],"bookableSeats":4,"isCheapest":true,"status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-travel-connection-error","price":"189.00","currency":"EUR","transportMethod":"airplane","tripType":"one_way","origin":"Munich (MUC)","destination":"London Heathrow (LHR)","departure":"2026-03-15T08:30:00","arrival":"2026-03-15T10:00:00","duration":"2h 30m","stops":0,"carriers":["Lufthansa"],"bookingProvider":"Lufthansa","carrierCodes":["LH"],"bookableSeats":4,"isCheapest":true,"status":"error","isMobile":false}},{"name":"mobile","props":{"id":"preview-travel-connection-mobile","price":"189.00","currency":"EUR","transportMethod":"airplane","tripType":"one_way","origin":"Munich (MUC)","destination":"London Heathrow (LHR)","departure":"2026-03-15T08:30:00","arrival":"2026-03-15T10:00:00","duration":"2h 30m","stops":0,"carriers":["Lufthansa"],"bookingProvider":"Lufthansa","carrierCodes":["LH"],"bookableSeats":4,"isCheapest":true,"status":"finished","isMobile":true}},{"name":"deutscheBahn","props":{"id":"preview-travel-connection-db","price":"189.00","currency":"EUR","transportMethod":"train","tripType":"one_way","origin":"Berlin Central Station","destination":"Hamburg Central Station","departure":"2026-03-15T09:04:00+01:00","arrival":"2026-03-15T10:46:00+01:00","duration":"1h 42m","stops":0,"carriers":["Deutsche Bahn"],"bookingProvider":"Deutsche Bahn","carrierCodes":[],"bookableSeats":4,"isCheapest":true,"status":"finished","isMobile":false}},{"name":"flixTrain","props":{"id":"preview-travel-connection-flix","price":"189.00","currency":"EUR","transportMethod":"train","tripType":"one_way","origin":"Berlin Central Station","destination":"Stuttgart Flughafen/Messe","departure":"2026-03-15T07:37:00+01:00","arrival":"2026-03-15T14:22:00+01:00","duration":"6h 45m","stops":1,"carriers":["FlixTrain","FlixBus"],"bookingProvider":"FlixBus / FlixTrain","carrierCodes":[],"bookableSeats":4,"isCheapest":true,"status":"finished","isMobile":false}}],
    "travel/TravelStaysEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-travel-stays-processing","query":"Hotels in Paris, Apr 1-5","provider":"Google","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-travel-stays-error","query":"Hotels in Invalid City","provider":"Google","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-travel-stays-cancelled","query":"Hotels in Tokyo","provider":"Google","status":"cancelled","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-travel-stays-mobile","query":"Hotels in Barcelona, Mar 15-18","provider":"Google","status":"finished","results":[{"name":"Hotel Arts Barcelona","hotel_class":5,"overall_rating":4.7,"reviews":4521,"currency":"EUR","rate_per_night":"320","amenities":["Pool","Spa","Beach access","Fine dining"]},{"name":"Casa Camper Barcelona","hotel_class":4,"overall_rating":4.4,"reviews":1832,"currency":"EUR","rate_per_night":"185","amenities":["Free Wi-Fi","Rooftop terrace","Free snacks"]},{"name":"Generator Barcelona","hotel_class":2,"overall_rating":4,"reviews":3200,"currency":"EUR","rate_per_night":"55","amenities":["Free Wi-Fi","Bar","Shared kitchen"]}],"isMobile":true}}],
    "travel/TravelStayEmbedPreview.svelte":[{"name":"budget","props":{"id":"preview-travel-stay-budget","name":"City Hostel Central","thumbnail":"","hotelClass":2,"overallRating":3.8,"reviews":523,"currency":"EUR","ratePerNight":45,"totalRate":135,"amenities":["Free Wi-Fi","Shared kitchen"],"isCheapest":true,"ecoCertified":false,"freeCancellation":false,"status":"finished","isMobile":false}},{"name":"luxury","props":{"id":"preview-travel-stay-luxury","name":"The Ritz-Carlton Berlin","thumbnail":"","hotelClass":5,"overallRating":4.8,"reviews":3456,"currency":"EUR","ratePerNight":450,"totalRate":1350,"amenities":["Free Wi-Fi","Spa","Pool","Concierge","Michelin restaurant","Valet parking"],"isCheapest":false,"ecoCertified":true,"freeCancellation":true,"status":"finished","isMobile":false}},{"name":"processing","props":{"id":"preview-travel-stay-processing","name":"Hotel Maximilian","thumbnail":"","hotelClass":4,"overallRating":4.3,"reviews":1248,"currency":"EUR","ratePerNight":129,"totalRate":387,"amenities":["Free Wi-Fi","Breakfast included","Spa","Fitness center","Airport shuttle"],"isCheapest":false,"ecoCertified":true,"freeCancellation":true,"status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-travel-stay-error","name":"Hotel Maximilian","thumbnail":"","hotelClass":4,"overallRating":4.3,"reviews":1248,"currency":"EUR","ratePerNight":129,"totalRate":387,"amenities":["Free Wi-Fi","Breakfast included","Spa","Fitness center","Airport shuttle"],"isCheapest":false,"ecoCertified":true,"freeCancellation":true,"status":"error","isMobile":false}},{"name":"mobile","props":{"id":"preview-travel-stay-mobile","name":"Hotel Maximilian","thumbnail":"","hotelClass":4,"overallRating":4.3,"reviews":1248,"currency":"EUR","ratePerNight":129,"totalRate":387,"amenities":["Free Wi-Fi","Breakfast included","Spa","Fitness center","Airport shuttle"],"isCheapest":false,"ecoCertified":true,"freeCancellation":true,"status":"finished","isMobile":true}}],
    "travel/TravelPriceCalendarEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-travel-price-calendar-processing","query":"Berlin -> Rome, April 2026","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-travel-price-calendar-error","query":"Invalid route","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-travel-price-calendar-cancelled","query":"Munich -> Tokyo, May 2026","status":"cancelled","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-travel-price-calendar-mobile","query":"Munich -> Barcelona, March 2026","status":"finished","results":[{"date":"2026-03-01","price":89,"currency":"EUR"},{"date":"2026-03-02","price":95,"currency":"EUR"},{"date":"2026-03-05","price":72,"currency":"EUR"},{"date":"2026-03-08","price":110,"currency":"EUR"},{"date":"2026-03-10","price":65,"currency":"EUR"},{"date":"2026-03-12","price":78,"currency":"EUR"},{"date":"2026-03-15","price":145,"currency":"EUR"},{"date":"2026-03-18","price":82,"currency":"EUR"},{"date":"2026-03-20","price":99,"currency":"EUR"},{"date":"2026-03-22","price":68,"currency":"EUR"},{"date":"2026-03-25","price":120,"currency":"EUR"},{"date":"2026-03-28","price":155,"currency":"EUR"}],"isMobile":true}}],
    "travel/TravelFlightDetailsEmbedPreview.svelte":[],
    "videos/VideosSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-videos-search-processing","query":"searching for videos...","provider":"Brave Search","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-videos-search-error","query":"failed video search","provider":"Brave Search","status":"error","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-videos-search-mobile","query":"svelte 5 tutorial","provider":"Brave Search","status":"finished","results":[{"title":"Svelte 5 Runes — Complete Beginner Guide","url":"https://www.youtube.com/watch?v=example1","thumbnail":"","channelName":"Svelte Society","duration":"17:08","viewCount":245000,"publishedAt":"2025-11-15T10:00:00Z"},{"title":"Migrating from Svelte 4 to 5 — Step by Step","url":"https://www.youtube.com/watch?v=example2","thumbnail":"","channelName":"Frontend Masters","duration":"32:15","viewCount":128000,"publishedAt":"2025-10-20T14:00:00Z"},{"title":"Building a Full App with SvelteKit 2","url":"https://www.youtube.com/watch?v=example3","thumbnail":"","channelName":"Fireship","duration":"12:42","viewCount":890000,"publishedAt":"2025-09-05T08:00:00Z"}],"isMobile":true}}],
    "videos/VideoEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-video-processing","url":"https://www.youtube.com/watch?v=loading","title":"Understanding Svelte 5 Runes — Complete Tutorial","status":"processing","channelName":"Svelte Society","channelId":"UC_abc123","channelThumbnail":"","thumbnail":"","durationSeconds":1028,"durationFormatted":"17:08","viewCount":245000,"likeCount":12400,"publishedAt":"2025-11-15T10:00:00Z","videoId":"dQw4w9WgXcQ","isMobile":false}},{"name":"error","props":{"id":"preview-video-error","url":"https://www.youtube.com/watch?v=invalid","title":"Understanding Svelte 5 Runes — Complete Tutorial","status":"error","channelName":"Svelte Society","channelId":"UC_abc123","channelThumbnail":"","thumbnail":"","durationSeconds":1028,"durationFormatted":"17:08","viewCount":245000,"likeCount":12400,"publishedAt":"2025-11-15T10:00:00Z","videoId":"dQw4w9WgXcQ","isMobile":false}},{"name":"shortVideo","props":{"id":"preview-video-short","url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"Svelte 5 in 60 Seconds","status":"finished","channelName":"Svelte Society","channelId":"UC_abc123","channelThumbnail":"","thumbnail":"","durationSeconds":58,"durationFormatted":"0:58","viewCount":89000,"likeCount":12400,"publishedAt":"2025-11-15T10:00:00Z","videoId":"dQw4w9WgXcQ","isMobile":false}},{"name":"longVideo","props":{"id":"preview-video-long","url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"SvelteKit Deep Dive — Full Conference Talk","status":"finished","channelName":"Frontend Masters","channelId":"UC_abc123","channelThumbnail":"","thumbnail":"","durationSeconds":5420,"durationFormatted":"1:30:20","viewCount":52000,"likeCount":3200,"publishedAt":"2025-11-15T10:00:00Z","videoId":"dQw4w9WgXcQ","isMobile":false}},{"name":"mobile","props":{"id":"preview-video-mobile","url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"Understanding Svelte 5 Runes — Complete Tutorial","status":"finished","channelName":"Svelte Society","channelId":"UC_abc123","channelThumbnail":"","thumbnail":"","durationSeconds":1028,"durationFormatted":"17:08","viewCount":245000,"likeCount":12400,"publishedAt":"2025-11-15T10:00:00Z","videoId":"dQw4w9WgXcQ","isMobile":true}}],
    "videos/VideoTranscriptEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-video-transcript-processing","status":"processing","url":"https://www.youtube.com/watch?v=loading","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-video-transcript-error","status":"error","url":"https://www.youtube.com/watch?v=no-transcript","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-video-transcript-mobile","status":"finished","url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","results":[{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"Understanding Svelte 5 Runes","transcript":"Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system. The $state rune replaces let declarations for reactive variables. The $derived rune replaces $: for computed values. And the $effect rune replaces $: for side effects.","channelName":"Svelte Society","durationFormatted":"17:08"}],"isMobile":true}}],
    "videos/VideoGenerateEmbedPreview.svelte":[],
    "videos/VideoCreateEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-video-create-processing","manifest":{"meta":{"title":"Product-launch","durationInFrames":240,"fps":30,"width":1920,"height":1080,"durationSeconds":8},"tracks":[{"name":"Background","type":"visual","items":[{"id":"item-0","label":"Gradient bg","from":0,"durationInFrames":240,"color":"#3B82F6","details":"<GradientBg />"}]},{"name":"Layer 2","type":"visual","items":[{"id":"item-1","label":"Title card","from":0,"durationInFrames":60,"color":"#8B5CF6","details":"<TitleCard text=\"Introducing OpenMates\" />"},{"id":"item-2","label":"Feature list","from":60,"durationInFrames":60,"color":"#8B5CF6","details":"<FeatureList />"},{"id":"item-3","label":"Client encryption demo","from":120,"durationInFrames":60,"color":"#8B5CF6","details":"<ClientEncryptionDemo />"},{"id":"item-4","label":"Call to action","from":180,"durationInFrames":60,"color":"#8B5CF6","details":"<CallToAction />"}]},{"name":"Audio","type":"audio","items":[{"id":"item-5","label":"background.mp3","from":0,"durationInFrames":240,"color":"#22C55E","details":""}]}]},"status":"processing","videoUrl":"/dev-fixtures/video-creation/product-launch.mp4","thumbnailUrl":"","isMobile":false}},{"name":"dataViz","props":{"id":"preview-video-create-dataviz","manifest":{"meta":{"title":"Data-viz","durationInFrames":270,"fps":30,"width":1920,"height":1080,"durationSeconds":9},"tracks":[{"name":"Background","type":"visual","items":[{"id":"item-0","label":"Dark background","from":0,"durationInFrames":270,"color":"#3B82F6","details":"<DarkBackground />"}]},{"name":"Layer 2","type":"visual","items":[{"id":"item-1","label":"Chart title","from":0,"durationInFrames":210,"color":"#8B5CF6","details":"<ChartTitle />"},{"id":"item-4","label":"Outro card","from":210,"durationInFrames":60,"color":"#8B5CF6","details":"<OutroCard />"}]},{"name":"Layer 3","type":"visual","items":[{"id":"item-2","label":"Bar chart","from":30,"durationInFrames":180,"color":"#EC4899","details":"<BarChart />"}]},{"name":"Layer 4","type":"visual","items":[{"id":"item-3","label":"Growth label","from":120,"durationInFrames":90,"color":"#F59E0B","details":"<GrowthLabel />"}]}]},"status":"finished","videoUrl":"/dev-fixtures/video-creation/data-viz.mp4","thumbnailUrl":"","isMobile":false}},{"name":"dataVizProcessing","props":{"id":"preview-video-create-dataviz-proc","manifest":{"meta":{"title":"Data-viz","durationInFrames":270,"fps":30,"width":1920,"height":1080,"durationSeconds":9},"tracks":[{"name":"Background","type":"visual","items":[{"id":"item-0","label":"Dark background","from":0,"durationInFrames":270,"color":"#3B82F6","details":"<DarkBackground />"}]},{"name":"Layer 2","type":"visual","items":[{"id":"item-1","label":"Chart title","from":0,"durationInFrames":210,"color":"#8B5CF6","details":"<ChartTitle />"},{"id":"item-4","label":"Outro card","from":210,"durationInFrames":60,"color":"#8B5CF6","details":"<OutroCard />"}]},{"name":"Layer 3","type":"visual","items":[{"id":"item-2","label":"Bar chart","from":30,"durationInFrames":180,"color":"#EC4899","details":"<BarChart />"}]},{"name":"Layer 4","type":"visual","items":[{"id":"item-3","label":"Growth label","from":120,"durationInFrames":90,"color":"#F59E0B","details":"<GrowthLabel />"}]}]},"status":"processing","videoUrl":"/dev-fixtures/video-creation/product-launch.mp4","thumbnailUrl":"","isMobile":false}},{"name":"error","props":{"id":"preview-video-create-error","manifest":{"meta":{"title":"Product-launch","durationInFrames":240,"fps":30,"width":1920,"height":1080,"durationSeconds":8},"tracks":[{"name":"Background","type":"visual","items":[{"id":"item-0","label":"Gradient bg","from":0,"durationInFrames":240,"color":"#3B82F6","details":"<GradientBg />"}]},{"name":"Layer 2","type":"visual","items":[{"id":"item-1","label":"Title card","from":0,"durationInFrames":60,"color":"#8B5CF6","details":"<TitleCard text=\"Introducing OpenMates\" />"},{"id":"item-2","label":"Feature list","from":60,"durationInFrames":60,"color":"#8B5CF6","details":"<FeatureList />"},{"id":"item-3","label":"Client encryption demo","from":120,"durationInFrames":60,"color":"#8B5CF6","details":"<ClientEncryptionDemo />"},{"id":"item-4","label":"Call to action","from":180,"durationInFrames":60,"color":"#8B5CF6","details":"<CallToAction />"}]},{"name":"Audio","type":"audio","items":[{"id":"item-5","label":"background.mp3","from":0,"durationInFrames":240,"color":"#22C55E","details":""}]}]},"status":"error","videoUrl":"/dev-fixtures/video-creation/product-launch.mp4","thumbnailUrl":"","isMobile":false,"errorMessage":"Remotion render failed: composition \"product-launch\" not found"}},{"name":"mobile","props":{"id":"preview-video-create-mobile","manifest":{"meta":{"title":"Product-launch","durationInFrames":240,"fps":30,"width":1920,"height":1080,"durationSeconds":8},"tracks":[{"name":"Background","type":"visual","items":[{"id":"item-0","label":"Gradient bg","from":0,"durationInFrames":240,"color":"#3B82F6","details":"<GradientBg />"}]},{"name":"Layer 2","type":"visual","items":[{"id":"item-1","label":"Title card","from":0,"durationInFrames":60,"color":"#8B5CF6","details":"<TitleCard text=\"Introducing OpenMates\" />"},{"id":"item-2","label":"Feature list","from":60,"durationInFrames":60,"color":"#8B5CF6","details":"<FeatureList />"},{"id":"item-3","label":"Client encryption demo","from":120,"durationInFrames":60,"color":"#8B5CF6","details":"<ClientEncryptionDemo />"},{"id":"item-4","label":"Call to action","from":180,"durationInFrames":60,"color":"#8B5CF6","details":"<CallToAction />"}]},{"name":"Audio","type":"audio","items":[{"id":"item-5","label":"background.mp3","from":0,"durationInFrames":240,"color":"#22C55E","details":""}]}]},"status":"finished","videoUrl":"/dev-fixtures/video-creation/product-launch.mp4","thumbnailUrl":"","isMobile":true}}],
    "weather/WeatherForecastEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-weather-forecast-processing","query":"Berlin weather forecast","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-weather-forecast-error","query":"Berlin weather forecast","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-weather-forecast-cancelled","query":"Berlin weather forecast","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","status":"cancelled","results":[{"date":"2026-06-02","condition":"dry","icon":"clear-day","temperature_min_c":15,"temperature_max_c":26,"precipitation_total_mm":0,"precipitation_probability_max_pct":4,"rain_hours":0},{"date":"2026-06-03","condition":"rain","icon":"rain","temperature_min_c":14,"temperature_max_c":19,"precipitation_total_mm":5.8,"precipitation_probability_max_pct":67,"rain_hours":13},{"date":"2026-06-04","condition":"cloudy","icon":"cloudy","temperature_min_c":13,"temperature_max_c":21,"precipitation_total_mm":4.9,"precipitation_probability_max_pct":37,"rain_hours":9},{"date":"2026-06-05","condition":"thunderstorm","icon":"thunderstorms-day-rain","temperature_min_c":16,"temperature_max_c":22,"precipitation_total_mm":12.4,"precipitation_probability_max_pct":82,"rain_hours":6}],"isMobile":false}},{"name":"mobile","props":{"id":"preview-weather-forecast-mobile","query":"Berlin weather forecast","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","status":"finished","results":[{"date":"2026-06-02","condition":"dry","icon":"clear-day","temperature_min_c":15,"temperature_max_c":26,"precipitation_total_mm":0,"precipitation_probability_max_pct":4,"rain_hours":0},{"date":"2026-06-03","condition":"rain","icon":"rain","temperature_min_c":14,"temperature_max_c":19,"precipitation_total_mm":5.8,"precipitation_probability_max_pct":67,"rain_hours":13},{"date":"2026-06-04","condition":"cloudy","icon":"cloudy","temperature_min_c":13,"temperature_max_c":21,"precipitation_total_mm":4.9,"precipitation_probability_max_pct":37,"rain_hours":9},{"date":"2026-06-05","condition":"thunderstorm","icon":"thunderstorms-day-rain","temperature_min_c":16,"temperature_max_c":22,"precipitation_total_mm":12.4,"precipitation_probability_max_pct":82,"rain_hours":6}],"isMobile":true}}],
    "weather/WeatherDayEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-weather-day-processing","date":"2026-06-03","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","condition":"rain","icon":"rain","temperatureMinC":14,"temperatureMaxC":19,"precipitationTotalMm":5.8,"precipitationProbabilityMaxPct":67,"rainHours":13,"status":"processing","isMobile":false}},{"name":"error","props":{"id":"preview-weather-day-error","date":"2026-06-03","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","condition":"rain","icon":"rain","temperatureMinC":14,"temperatureMaxC":19,"precipitationTotalMm":5.8,"precipitationProbabilityMaxPct":67,"rainHours":13,"status":"error","isMobile":false}},{"name":"cancelled","props":{"id":"preview-weather-day-cancelled","date":"2026-06-03","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","condition":"rain","icon":"rain","temperatureMinC":14,"temperatureMaxC":19,"precipitationTotalMm":5.8,"precipitationProbabilityMaxPct":67,"rainHours":13,"status":"cancelled","isMobile":false}},{"name":"mobile","props":{"id":"preview-weather-day-mobile","date":"2026-06-03","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","condition":"rain","icon":"rain","temperatureMinC":14,"temperatureMaxC":19,"precipitationTotalMm":5.8,"precipitationProbabilityMaxPct":67,"rainHours":13,"status":"finished","isMobile":true}},{"name":"sunny","props":{"id":"preview-weather-day-sunny","date":"2026-06-03","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","condition":"dry","icon":"clear-day","temperatureMinC":18,"temperatureMaxC":29,"precipitationTotalMm":0,"precipitationProbabilityMaxPct":3,"rainHours":0,"status":"finished","isMobile":false}},{"name":"snow","props":{"id":"preview-weather-day-snow","date":"2026-06-03","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD)","condition":"snow","icon":"snow","temperatureMinC":-4,"temperatureMaxC":1,"precipitationTotalMm":8.2,"precipitationProbabilityMaxPct":76,"rainHours":10,"status":"finished","isMobile":false}}],
    "weather/WeatherRainRadarEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-weather-rain-radar-processing","query":"Berlin rain radar","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD) via Bright Sky","status":"processing","summary":{"rain_expected":true,"in_10_min":"Light rain visible near Berlin.","next_2_hours":"Light rain appears in the radar timeline near Berlin.","peak_intensity":"light","preview_frame_id":"frame-1"},"timeline":[],"isMobile":false}},{"name":"error","props":{"id":"preview-weather-rain-radar-error","query":"Berlin rain radar","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD) via Bright Sky","status":"error","summary":{"rain_expected":true,"in_10_min":"Light rain visible near Berlin.","next_2_hours":"Light rain appears in the radar timeline near Berlin.","peak_intensity":"light","preview_frame_id":"frame-1"},"timeline":[],"isMobile":false}},{"name":"unavailable","props":{"id":"preview-weather-rain-radar-unavailable","query":"Berlin rain radar","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD) via Bright Sky","status":"finished","summary":{"rain_expected":null,"in_10_min":"Rain radar is unavailable for this location in V1.","next_2_hours":"Germany DWD rain radar is available in V1; global radar coverage is not supported yet.","peak_intensity":"unknown","preview_frame_id":null},"timeline":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-weather-rain-radar-mobile","query":"Berlin rain radar","locationName":"Berlin","provider":"Deutscher Wetterdienst (DWD) via Bright Sky","status":"finished","summary":{"rain_expected":true,"in_10_min":"Light rain visible near Berlin.","next_2_hours":"Light rain appears in the radar timeline near Berlin.","peak_intensity":"light","preview_frame_id":"frame-1"},"timeline":[{"frame_id":"frame-0","timestamp":"2026-06-14T13:00:00Z","kind":"past","label":"-10 min","rain_at_location_mm_5min":0.02,"max_intensity":"light","rain_area_pct":12},{"frame_id":"frame-1","timestamp":"2026-06-14T13:10:00Z","kind":"forecast","label":"+10 min","rain_at_location_mm_5min":0.08,"max_intensity":"light","rain_area_pct":18}],"isMobile":true}}],
    "web/WebSearchEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-web-search-processing","query":"searching for something...","provider":"Brave Search","status":"processing","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-web-search-error","query":"failed search query","provider":"Brave Search","status":"error","results":[],"isMobile":false}},{"name":"cancelled","props":{"id":"preview-web-search-cancelled","query":"cancelled search","provider":"Brave Search","status":"cancelled","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-web-search-mobile","query":"best restaurants in Berlin","provider":"Brave Search","status":"finished","results":[{"title":"Top 10 Restaurants in Berlin - Local Guide","url":"https://www.visitberlin.de/en/restaurants","description":"Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors. Updated for 2026.","favicon":"","preview_image_url":"/images/examples/group1.jpg"},{"title":"Berlin Food Scene: A Complete Guide","url":"https://www.timeout.com/berlin/restaurants","description":"From street food to Michelin-starred restaurants, explore what makes Berlin one of Europe's top food destinations.","favicon":""},{"title":"Where to Eat in Berlin - Travel Blog","url":"https://www.lonelyplanet.com/germany/berlin/restaurants","description":"A curated list of must-visit restaurants, cafes, and food markets in Berlin. Includes budget-friendly options.","favicon":""}],"isMobile":true}}],
    "web/WebReadEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-web-read-processing","status":"processing","url":"https://svelte.dev/blog/loading","results":[],"isMobile":false}},{"name":"error","props":{"id":"preview-web-read-error","status":"error","url":"https://svelte.dev/blog/not-found","results":[],"isMobile":false}},{"name":"mobile","props":{"id":"preview-web-read-mobile","status":"finished","url":"https://svelte.dev/blog/svelte-5-migration-guide","results":[{"url":"https://svelte.dev/blog/svelte-5-migration-guide","title":"Complete Guide to Migrating from Svelte 4 to Svelte 5","content":"Svelte 5 introduces runes, a powerful new reactivity system that replaces the $: reactive statements. This guide walks you through every step of the migration process, from updating your dependencies to converting your components.","favicon":""}],"isMobile":true}}],
    "workflows/WorkflowCreateEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-workflow-create-processing","instruction":"Create a simple manual workflow for a weekly balcony garden check-in","status":"processing","results":[],"resultCount":0,"isMobile":false}},{"name":"mobile","props":{"id":"preview-workflow-create-mobile","instruction":"Create a simple manual workflow for a weekly balcony garden check-in","status":"finished","results":[{"embed_id":"legacy-workflow-garden-1","workflow_id":"workflow-garden-1","title":"Weekly balcony garden reminder","description":"Every Saturday morning, remind me to water herbs and note which plants need trimming.","status":"ready","enabled":true,"trigger_summary":"Manual or weekly Saturday reminder"}],"resultCount":1,"isMobile":true}}],
    "workflows/WorkflowEmbedPreview.svelte":[{"name":"disabled","props":{"id":"preview-workflow-disabled","workflowId":"workflow-garden-1","title":"Weekly balcony garden reminder","description":"Every Saturday morning, remind me to water herbs and note which plants need trimming.","status":"ready","enabled":false,"triggerSummary":"Manual or weekly Saturday reminder","isMobile":false}},{"name":"mobile","props":{"id":"preview-workflow-child-mobile","workflowId":"workflow-garden-1","title":"Weekly balcony garden reminder","description":"Every Saturday morning, remind me to water herbs and note which plants need trimming.","status":"ready","enabled":true,"triggerSummary":"Manual or weekly Saturday reminder","isMobile":true}}],
    "workflows/WorkflowSearchEmbedPreview.svelte":[{"name":"noResults","props":{"id":"preview-workflow-search-empty","query":"invoice approval workflow","status":"finished","results":[],"resultCount":0,"isMobile":false}},{"name":"mobile","props":{"id":"preview-workflow-search-mobile","query":"travel packing workflows","status":"finished","results":[{"embed_id":"legacy-workflow-packing-1","workflow_id":"workflow-packing-1","title":"Trip packing reminder workflow","description":"A manual workflow that creates a short packing checklist and reminder before each trip.","status":"ready","enabled":true,"trigger_summary":"Manual trigger"},{"embed_id":"legacy-workflow-packing-2","workflow_id":"workflow-packing-2","title":"Departure day weather check","description":"Check the forecast on the morning of departure and remind me about rain gear if needed.","status":"ready","enabled":false,"trigger_summary":"Manual trigger"}],"resultCount":2,"isMobile":true}}],
    "sheets/SheetEmbedPreview.svelte":[{"name":"processing","props":{"id":"preview-sheet-processing","title":"Team Directory","rowCount":5,"colCount":4,"status":"processing","tableContent":"| Name | Role | Department | Start Date |\n|------|------|------------|------------|\n| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 |\n| Bob Smith | Product Manager | Product | 2022-06-01 |\n| Carol Williams | Designer | Design | 2024-03-10 |\n| David Brown | DevOps Lead | Engineering | 2021-11-20 |\n| Eva Martinez | QA Engineer | Engineering | 2023-08-05 |","isMobile":false}},{"name":"error","props":{"id":"preview-sheet-error","title":"Team Directory","rowCount":5,"colCount":4,"status":"error","tableContent":"| Name | Role | Department | Start Date |\n|------|------|------------|------------|\n| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 |\n| Bob Smith | Product Manager | Product | 2022-06-01 |\n| Carol Williams | Designer | Design | 2024-03-10 |\n| David Brown | DevOps Lead | Engineering | 2021-11-20 |\n| Eva Martinez | QA Engineer | Engineering | 2023-08-05 |","isMobile":false}},{"name":"largeTable","props":{"id":"preview-sheet-large","title":"Sales Report Q4 2025","rowCount":150,"colCount":8,"status":"finished","tableContent":"| Region | Product | Q1 | Q2 | Q3 | Q4 | Total | Growth |\n|--------|---------|----|----|----|----|-------|--------|\n| North | Widget A | 12400 | 15800 | 18200 | 21500 | 67900 | +14% |\n| North | Widget B | 8900 | 9400 | 11200 | 13600 | 43100 | +18% |\n| South | Widget A | 9200 | 10500 | 12800 | 15400 | 47900 | +22% |\n| South | Widget B | 6700 | 7200 | 8900 | 10100 | 32900 | +12% |\n| East | Widget A | 14200 | 16700 | 19400 | 23100 | 73400 | +8% |\n| East | Widget B | 10400 | 11800 | 13200 | 15900 | 51300 | +16% |\n| West | Widget A | 11600 | 13200 | 15700 | 18900 | 59400 | +20% |\n| West | Widget B | 7800 | 8600 | 10200 | 12400 | 39000 | +11% |","isMobile":false}},{"name":"budget","props":{"id":"preview-sheet-budget","title":"Q4 Budget Overview","rowCount":4,"colCount":4,"status":"finished","tableContent":"| Category | Budget | Spent | Remaining |\n|----------|--------|-------|-----------|\n| Marketing | $50,000 | $32,400 | $17,600 |\n| Engineering | $120,000 | $98,750 | $21,250 |\n| Design | $35,000 | $28,100 | $6,900 |\n| Sales | $80,000 | $71,200 | $8,800 |","isMobile":false}},{"name":"feedback","props":{"id":"preview-sheet-feedback","title":"Performance Reviews","rowCount":4,"colCount":3,"status":"finished","tableContent":"| Reviewer | Score | Summary |\n|----------|-------|---------|\n| Alice Johnson | 9/10 | Outstanding performance this quarter, great leadership |\n| Bob Smith | 7/10 | Solid delivery, could improve cross-team communication |\n| Carol Williams | 8/10 | Excellent design work, very attentive to user feedback |\n| David Brown | 9/10 | Reliable and proactive, keeps infrastructure running smoothly |","isMobile":false}},{"name":"mobile","props":{"id":"preview-sheet-mobile","title":"Team Directory","rowCount":5,"colCount":4,"status":"finished","tableContent":"| Name | Role | Department | Start Date |\n|------|------|------------|------------|\n| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 |\n| Bob Smith | Product Manager | Product | 2022-06-01 |\n| Carol Williams | Designer | Design | 2024-03-10 |\n| David Brown | DevOps Lead | Engineering | 2021-11-20 |\n| Eva Martinez | QA Engineer | Engineering | 2023-08-05 |","isMobile":true}},{"name":"mobileWide","props":{"id":"preview-sheet-mobile-wide","title":"Sales Report Q4 2025","rowCount":8,"colCount":8,"status":"finished","tableContent":"| Region | Product | Q1 | Q2 | Q3 | Q4 | Total | Growth |\n|--------|---------|----|----|----|----|-------|--------|\n| North | Widget A | 12400 | 15800 | 18200 | 21500 | 67900 | +14% |\n| North | Widget B | 8900 | 9400 | 11200 | 13600 | 43100 | +18% |\n| South | Widget A | 9200 | 10500 | 12800 | 15400 | 47900 | +22% |\n| South | Widget B | 6700 | 7200 | 8900 | 10100 | 32900 | +12% |\n| East | Widget A | 14200 | 16700 | 19400 | 23100 | 73400 | +8% |\n| East | Widget B | 10400 | 11800 | 13200 | 15900 | 51300 | +16% |\n| West | Widget A | 11600 | 13200 | 15700 | 18900 | 59400 | +20% |\n| West | Widget B | 7800 | 8600 | 10200 | 12400 | 39000 | +11% |","isMobile":true}}],
    "focus_mode/FocusModeActivationEmbed.svelte":[{"name":"countdown","props":{"id":"preview-focus-mode-countdown","focusId":"jobs-career_insights","appId":"jobs","focusModeName":"Career Insights","alreadyActive":false,"pendingUntil":1773563404000}}],
    "audio/RecordingEmbedFullscreen.svelte":[{"name":"editable","props":{"data":{"decodedContent":{"filename":"voice-memo-2026-03-10.webm","transcript":"This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week. Key highlights include the completion of the authentication refactor and the new API rate limiting feature.","duration":"0:42","model":"voxtral-mini-2602"},"embedData":{"status":"finished","skill_id":"record"},"attrs":{"app_id":"audio"}},"isEditable":true,"embedId":"preview-audio-fullscreen-editable"}},{"name":"longTranscript","props":{"data":{"decodedContent":{"filename":"meeting-notes-2026-03-10.webm","transcript":"Welcome everyone to the quarterly planning session. Today we will cover three main topics: the product roadmap for Q2, the engineering capacity planning, and the customer feedback synthesis from last quarter.\n\nStarting with the product roadmap: the team has identified five key areas of focus. First, we need to improve the onboarding flow based on user research. Second, we are adding collaborative features to the workspace. Third, we are enhancing the AI assistant capabilities. Fourth, we need to address performance improvements in the mobile app. Fifth, we are expanding our API for third-party integrations.\n\nFor engineering capacity, we currently have twelve engineers distributed across four teams. The AI team has three engineers working on model integrations and the skill framework. The platform team has four engineers working on infrastructure and developer tools. The product team has three engineers working on core features. The mobile team has two engineers working on iOS and Android.\n\nRegarding customer feedback, the most requested features are offline mode, better search functionality, and more granular permission controls. We have triaged these into our backlog with priorities set for Q2 delivery.","duration":"12:34","model":"voxtral-mini-2602"},"embedData":{"status":"finished","skill_id":"record"},"attrs":{"app_id":"audio"}},"isEditable":false}},{"name":"mobile","props":{"data":{"decodedContent":{"filename":"voice-memo-2026-03-10.webm","transcript":"This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week. Key highlights include the completion of the authentication refactor and the new API rate limiting feature.","duration":"0:42","model":"voxtral-mini-2602"},"embedData":{"status":"finished","skill_id":"record"},"attrs":{"app_id":"audio"}},"isEditable":false,"isMobile":true}}],
    "audio/AudioGenerateEmbedFullscreen.svelte":[],
    "business/BusinessCompanyFinancialsEmbedFullscreen.svelte":[{"name":"quarterly","props":{"embedId":"preview-business-company-financials-quarterly","data":{"decodedContent":{"query":"Show VITL latest quarter financials","provider":"SEC EDGAR","period":"latest_quarter","metric_group":"income","status":"finished","result_count":1,"results":[{"embed_id":"legacy-business-financial-vitl-quarter","company":"Vital Farms, Inc.","ticker":"VITL","cik":"0001579733","period_type":"quarter","fiscal_year":2026,"period_start":"2025-12-29","period_end":"2026-03-28","filed":"2026-05-07","form":"10-K","currency":"USD","revenue":187155000,"gross_profit":1799800000,"operating_income":1446200000,"net_income":-1522000,"operating_cash_flow":1260000000,"assets":3451000000,"liabilities":602000000,"equity":2849000000,"source_url":"https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/1579733/000157973326000042/vitl-20260328.htm","accession_number":"0001579733-26-000042","notes":["Normalized from SEC companyfacts and filing metadata."],"fiscal_quarter":"Q1"}]},"embedData":{"status":"finished"},"attrs":{"app_id":"business","skill_id":"company_financials"}},"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "business/BusinessCompanyFinancialResultEmbedFullscreen.svelte":[{"name":"quarterly","props":{"embedId":"preview-business-financial-vitl-quarter","data":{"decodedContent":{"company":"Vital Farms, Inc.","ticker":"VITL","cik":"0001579733","period_type":"quarter","fiscal_year":2026,"period_start":"2025-12-29","period_end":"2026-03-28","filed":"2026-05-07","form":"10-Q","currency":"USD","revenue":187155000,"gross_profit":1799800000,"operating_income":1446200000,"net_income":-1522000,"operating_cash_flow":1260000000,"assets":3451000000,"liabilities":602000000,"equity":2849000000,"source_url":"https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/1579733/000157973326000042/vitl-20260328.htm","accession_number":"0001579733-26-000042","notes":["Normalized from SEC companyfacts and filing metadata."],"fiscal_quarter":"Q1"},"embedData":{"status":"finished"},"attrs":{"app_id":"business","skill_id":"company_financial_result"}},"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "calendar/CalendarActionEmbedFullscreen.svelte":[],
    "code/CodeRepoSearchEmbedFullscreen.svelte":[],
    "code/CodeRepoEmbedFullscreen.svelte":[],
    "code/CodeGetDocsEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"library":"svelte","question":"How to use $state rune in Svelte 5?","results":[{"library":{"id":"/sveltejs/svelte","title":"Svelte","description":"Cybernetically enhanced web apps"},"documentation":"# $state — Svelte 5 Runes\n\nThe `$state` rune declares reactive state. When you assign to a `$state` variable, Svelte automatically updates all DOM nodes that depend on it.\n\n## Basic Usage\n\n```svelte\n<script>\nlet count = $state(0);\n</script>\n\n<button onclick={() => count++}>\n  Clicks: {count}\n</button>\n```\n\n## Deep Reactivity\n\n`$state` provides deep reactivity for objects and arrays. Changes to nested properties are tracked automatically.\n\n```svelte\n<script>\nlet user = $state({ name: 'Alice', age: 30 });\n</script>\n\n<input bind:value={user.name} />\n<p>Name: {user.name}</p>\n```\n\n## With TypeScript\n\n```ts\nlet count = $state<number>(0);\nlet items = $state<string[]>([]);\n```\n\n## Differences from Svelte 4\n\nIn Svelte 4, reactive variables were declared at the top level of `<script>` and updated reactively. In Svelte 5, you explicitly mark state with `$state()` — this makes reactivity explicit and works inside functions, classes, and modules.\n\n| Svelte 4 | Svelte 5 |\n|----------|----------|\n| `let count = 0;` (top-level) | `let count = $state(0);` |\n| `$: doubled = count * 2;` | `let doubled = $derived(count * 2);` |\n| `onMount(() => ...)` | Same |\n\n## Related\n\n- [`$derived`](https://svelte.dev/docs/svelte/$derived) — computed values\n- [`$effect`](https://svelte.dev/docs/svelte/$effect) — side effects\n- [`$props`](https://svelte.dev/docs/svelte/$props) — component props","source":"context7","word_count":180}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"fastapi","props":{"library":"fastapi","question":"How to define path parameters in FastAPI?","results":[{"library":{"id":"/tiangolo/fastapi","title":"FastAPI","description":"FastAPI framework, high performance, easy to learn"},"documentation":"# Path Parameters — FastAPI\n\nPath parameters are defined using Python type hints in the function signature. FastAPI automatically converts them to the correct type.\n\n## Basic Example\n\n```python\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get(\"/items/{item_id}\")\nasync def read_item(item_id: int):\n    return {\"item_id\": item_id}\n```\n\n## With Validation\n\nUse `Path()` to add constraints to path parameters.\n\n```python\nfrom fastapi import FastAPI, Path\n\napp = FastAPI()\n\n@app.get(\"/items/{item_id}\")\nasync def read_item(\n    item_id: int = Path(title=\"The ID of the item\", ge=1, le=1000)\n):\n    return {\"item_id\": item_id}\n```","source":"context7","word_count":95}],"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"noResults","props":{"library":"obscure-lib","question":"How to use undocumented feature?","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "code/CodeEmbedFullscreen.svelte":[{"name":"singleEmbed","props":{"data":{"decodedContent":{"code":"import { onMount } from 'svelte';\nimport { browser } from '$app/environment';\n\ninterface Props {\n  title: string;\n  items: string[];\n  onSelect?: (item: string) => void;\n}\n\nlet { title, items, onSelect }: Props = $props();\n\nlet searchQuery = $state('');\nlet isExpanded = $state(false);\n\nlet filteredItems = $derived(\n  items.filter(item =>\n    item.toLowerCase().includes(searchQuery.toLowerCase())\n  )\n);\n\nonMount(() => {\n  if (browser) {\n    console.log('Component mounted in browser');\n  }\n});\n\nfunction handleSelect(item: string) {\n  onSelect?.(item);\n  isExpanded = false;\n}","language":"typescript","filename":"SearchableList.svelte","line_count":32},"attrs":{"type":"code-code"}},"embedId":"preview-code-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"longCode","props":{"data":{"decodedContent":{"code":"line_1 = \"content for line 1\"\nline_2 = \"content for line 2\"\nline_3 = \"content for line 3\"\nline_4 = \"content for line 4\"\nline_5 = \"content for line 5\"\nline_6 = \"content for line 6\"\nline_7 = \"content for line 7\"\nline_8 = \"content for line 8\"\nline_9 = \"content for line 9\"\nline_10 = \"content for line 10\"\nline_11 = \"content for line 11\"\nline_12 = \"content for line 12\"\nline_13 = \"content for line 13\"\nline_14 = \"content for line 14\"\nline_15 = \"content for line 15\"\nline_16 = \"content for line 16\"\nline_17 = \"content for line 17\"\nline_18 = \"content for line 18\"\nline_19 = \"content for line 19\"\nline_20 = \"content for line 20\"\nline_21 = \"content for line 21\"\nline_22 = \"content for line 22\"\nline_23 = \"content for line 23\"\nline_24 = \"content for line 24\"\nline_25 = \"content for line 25\"\nline_26 = \"content for line 26\"\nline_27 = \"content for line 27\"\nline_28 = \"content for line 28\"\nline_29 = \"content for line 29\"\nline_30 = \"content for line 30\"\nline_31 = \"content for line 31\"\nline_32 = \"content for line 32\"\nline_33 = \"content for line 33\"\nline_34 = \"content for line 34\"\nline_35 = \"content for line 35\"\nline_36 = \"content for line 36\"\nline_37 = \"content for line 37\"\nline_38 = \"content for line 38\"\nline_39 = \"content for line 39\"\nline_40 = \"content for line 40\"\nline_41 = \"content for line 41\"\nline_42 = \"content for line 42\"\nline_43 = \"content for line 43\"\nline_44 = \"content for line 44\"\nline_45 = \"content for line 45\"\nline_46 = \"content for line 46\"\nline_47 = \"content for line 47\"\nline_48 = \"content for line 48\"\nline_49 = \"content for line 49\"\nline_50 = \"content for line 50\"\nline_51 = \"content for line 51\"\nline_52 = \"content for line 52\"\nline_53 = \"content for line 53\"\nline_54 = \"content for line 54\"\nline_55 = \"content for line 55\"\nline_56 = \"content for line 56\"\nline_57 = \"content for line 57\"\nline_58 = \"content for line 58\"\nline_59 = \"content for line 59\"\nline_60 = \"content for line 60\"\nline_61 = \"content for line 61\"\nline_62 = \"content for line 62\"\nline_63 = \"content for line 63\"\nline_64 = \"content for line 64\"\nline_65 = \"content for line 65\"\nline_66 = \"content for line 66\"\nline_67 = \"content for line 67\"\nline_68 = \"content for line 68\"\nline_69 = \"content for line 69\"\nline_70 = \"content for line 70\"\nline_71 = \"content for line 71\"\nline_72 = \"content for line 72\"\nline_73 = \"content for line 73\"\nline_74 = \"content for line 74\"\nline_75 = \"content for line 75\"\nline_76 = \"content for line 76\"\nline_77 = \"content for line 77\"\nline_78 = \"content for line 78\"\nline_79 = \"content for line 79\"\nline_80 = \"content for line 80\"\nline_81 = \"content for line 81\"\nline_82 = \"content for line 82\"\nline_83 = \"content for line 83\"\nline_84 = \"content for line 84\"\nline_85 = \"content for line 85\"\nline_86 = \"content for line 86\"\nline_87 = \"content for line 87\"\nline_88 = \"content for line 88\"\nline_89 = \"content for line 89\"\nline_90 = \"content for line 90\"\nline_91 = \"content for line 91\"\nline_92 = \"content for line 92\"\nline_93 = \"content for line 93\"\nline_94 = \"content for line 94\"\nline_95 = \"content for line 95\"\nline_96 = \"content for line 96\"\nline_97 = \"content for line 97\"\nline_98 = \"content for line 98\"\nline_99 = \"content for line 99\"\nline_100 = \"content for line 100\"","language":"python","filename":"long_file.py","line_count":100},"attrs":{"type":"code-code"}},"embedId":"preview-code-fullscreen-1","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"remoteSource","props":{"data":{"decodedContent":{"type":"remote_file_preview","code":"import { onMount } from 'svelte';\nimport { browser } from '$app/environment';\n\ninterface Props {\n  title: string;\n  items: string[];\n  onSelect?: (item: string) => void;\n}\n\nlet { title, items, onSelect }: Props = $props();\n\nlet searchQuery = $state('');\nlet isExpanded = $state(false);\n\nlet filteredItems = $derived(\n  items.filter(item =>\n    item.toLowerCase().includes(searchQuery.toLowerCase())\n  )\n);\n\nonMount(() => {\n  if (browser) {\n    console.log('Component mounted in browser');\n  }\n});\n\nfunction handleSelect(item: string) {\n  onSelect?.(item);\n  isExpanded = false;\n}","filename":"SearchableList.svelte","language":"svelte","line_count":32,"remote_source_label":"Studio Mac"},"attrs":{"type":"code-code","virtual":true}},"embedId":"remote:studio-mac:SearchableList.svelte","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "code/NotebookEmbedFullscreen.svelte":[],
    "code/ApplicationEmbedFullscreen.svelte":[],
    "design/DesignIconSearchEmbedFullscreen.svelte":[],
    "design/DesignIconResultEmbedFullscreen.svelte":[],
    "docs/DocsEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"htmlContent":"<h1>Project Architecture Overview</h1>\n<p>This document outlines the architecture decisions for the OpenMates platform, covering frontend, backend, and infrastructure components.</p>\n<h2>1. Frontend Architecture</h2>\n<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity. Key design decisions include:</p>\n<ul>\n<li>Component-based architecture with shared UI package</li>\n<li>CSS custom properties for theming</li>\n<li>IndexedDB for local data persistence</li>\n<li>Client-side encryption for user data</li>\n</ul>\n<h2>2. Backend Architecture</h2>\n<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services. Core components:</p>\n<ul>\n<li>WebSocket connections for real-time updates</li>\n<li>Redis for caching and task queues</li>\n<li>S3-compatible storage for encrypted files</li>\n</ul>\n<h2>3. Database Layer</h2>\n<p>PostgreSQL serves as the primary data store, managed through <strong>Directus CMS</strong>. The schema is designed for:</p>\n<ul>\n<li>Multi-tenant isolation</li>\n<li>Efficient query patterns for chat history</li>\n<li>JSON columns for flexible metadata storage</li>\n</ul>\n<h2>4. Infrastructure</h2>\n<p>The application is deployed using Docker containers orchestrated with Docker Compose. Each service runs in its own container for isolation and scalability.</p>","title":"Project Architecture Overview","filename":"architecture.docx","wordCount":156,"preview_page_urls":{"1":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2234%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EProject%20Architecture%20Overview%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22206%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EGenerated%20as%20a%20real%20DOCX%20artifact%2C%20then%20converted%20server-side%20to%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22252%22%20width%3D%22570%22%20height%3D%221%22%20fill%3D%22%23d1d5db%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22314%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EFrontend%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22356%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ESvelteKit%20and%20Svelte%205%20render%20the%20encrypted%20document%20preview%20after%20decrypting%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22382%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3Ethe%20generated%20screenshot%20artifact%20in%20the%20browser.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22456%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EBackend%20Pipeline%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22498%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E1.%20The%20model%20emits%20structured%20docx_model%20JSON.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22526%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E2.%20The%20Docs%20worker%20creates%20a%20canonical%20.docx%20file.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22554%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E3.%20LibreOffice%20converts%20it%20to%20PDF%3B%20PyMuPDF%20renders%20page%20screenshots.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22582%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E4.%20DOCX%20and%20screenshots%20are%20AES-GCM%20encrypted%20before%20upload.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22660%22%20width%3D%22570%22%20height%3D%22132%22%20rx%3D%2214%22%20fill%3D%22%23eef2ff%22%20stroke%3D%22%23c7d2fe%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22711%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%233730a3%22%3EDownload%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22750%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%234338ca%22%3EThe%20download%20button%20returns%20the%20real%20generated%20DOCX%2C%20not%20browser%20HTML.%3C%2Ftext%3E%0A%3C%2Fsvg%3E","2":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2230%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3ECompatibility%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22214%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EExisting%20document_html%20embeds%20still%20render%20through%20the%20legacy%20HTML%20fallback.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22242%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ENew%20embeds%20use%20docx_model%2C%20encrypted%20artifacts%2C%20and%20generated%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22318%22%20width%3D%22250%22%20height%3D%22130%22%20rx%3D%2216%22%20fill%3D%22%23ecfdf5%22%20stroke%3D%22%23a7f3d0%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22372%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%23065f46%22%3ELegacy%20HTML%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22410%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2215%22%20fill%3D%22%23047857%22%3EStill%20viewable%20and%20downloadable.%3C%2Ftext%3E%0A%3Crect%20x%3D%22432%22%20y%3D%22318%22%20width%3D%22250%22%20height%3D%22130%22%20rx%3D%2216%22%20fill%3D%22%23fef3c7%22%20stroke%3D%22%23fde68a%22%2F%3E%0A%3Ctext%20x%3D%22462%22%20y%3D%22372%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%2392400e%22%3EDOCX%20Artifact%3C%2Ftext%3E%0A%3Ctext%20x%3D%22462%22%20y%3D%22410%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2215%22%20fill%3D%22%23b45309%22%3ECanonical%20generated%20file.%3C%2Ftext%3E%0A%3C%2Fsvg%3E"},"page_count":2,"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"minimal","props":{"htmlContent":"<p>A simple document with minimal metadata.</p>","title":"Project Architecture Overview","filename":"architecture.docx","wordCount":156,"preview_page_urls":{"1":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2234%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EProject%20Architecture%20Overview%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22206%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EGenerated%20as%20a%20real%20DOCX%20artifact%2C%20then%20converted%20server-side%20to%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22252%22%20width%3D%22570%22%20height%3D%221%22%20fill%3D%22%23d1d5db%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22314%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EFrontend%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22356%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ESvelteKit%20and%20Svelte%205%20render%20the%20encrypted%20document%20preview%20after%20decrypting%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22382%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3Ethe%20generated%20screenshot%20artifact%20in%20the%20browser.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22456%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EBackend%20Pipeline%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22498%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E1.%20The%20model%20emits%20structured%20docx_model%20JSON.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22526%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E2.%20The%20Docs%20worker%20creates%20a%20canonical%20.docx%20file.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22554%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E3.%20LibreOffice%20converts%20it%20to%20PDF%3B%20PyMuPDF%20renders%20page%20screenshots.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22582%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E4.%20DOCX%20and%20screenshots%20are%20AES-GCM%20encrypted%20before%20upload.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22660%22%20width%3D%22570%22%20height%3D%22132%22%20rx%3D%2214%22%20fill%3D%22%23eef2ff%22%20stroke%3D%22%23c7d2fe%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22711%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%233730a3%22%3EDownload%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22750%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%234338ca%22%3EThe%20download%20button%20returns%20the%20real%20generated%20DOCX%2C%20not%20browser%20HTML.%3C%2Ftext%3E%0A%3C%2Fsvg%3E","2":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2230%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3ECompatibility%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22214%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EExisting%20document_html%20embeds%20still%20render%20through%20the%20legacy%20HTML%20fallback.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22242%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ENew%20embeds%20use%20docx_model%2C%20encrypted%20artifacts%2C%20and%20generated%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22318%22%20width%3D%22250%22%20height%3D%22130%22%20rx%3D%2216%22%20fill%3D%22%23ecfdf5%22%20stroke%3D%22%23a7f3d0%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22372%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%23065f46%22%3ELegacy%20HTML%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22410%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2215%22%20fill%3D%22%23047857%22%3EStill%20viewable%20and%20downloadable.%3C%2Ftext%3E%0A%3Crect%20x%3D%22432%22%20y%3D%22318%22%20width%3D%22250%22%20height%3D%22130%22%20rx%3D%2216%22%20fill%3D%22%23fef3c7%22%20stroke%3D%22%23fde68a%22%2F%3E%0A%3Ctext%20x%3D%22462%22%20y%3D%22372%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%2392400e%22%3EDOCX%20Artifact%3C%2Ftext%3E%0A%3Ctext%20x%3D%22462%22%20y%3D%22410%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2215%22%20fill%3D%22%23b45309%22%3ECanonical%20generated%20file.%3C%2Ftext%3E%0A%3C%2Fsvg%3E"},"page_count":2,"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"generatedDocxArtifact","props":{"htmlContent":"<h1>Project Architecture Overview</h1>\n<p>This document outlines the architecture decisions for the OpenMates platform, covering frontend, backend, and infrastructure components.</p>\n<h2>1. Frontend Architecture</h2>\n<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity. Key design decisions include:</p>\n<ul>\n<li>Component-based architecture with shared UI package</li>\n<li>CSS custom properties for theming</li>\n<li>IndexedDB for local data persistence</li>\n<li>Client-side encryption for user data</li>\n</ul>\n<h2>2. Backend Architecture</h2>\n<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services. Core components:</p>\n<ul>\n<li>WebSocket connections for real-time updates</li>\n<li>Redis for caching and task queues</li>\n<li>S3-compatible storage for encrypted files</li>\n</ul>\n<h2>3. Database Layer</h2>\n<p>PostgreSQL serves as the primary data store, managed through <strong>Directus CMS</strong>. The schema is designed for:</p>\n<ul>\n<li>Multi-tenant isolation</li>\n<li>Efficient query patterns for chat history</li>\n<li>JSON columns for flexible metadata storage</li>\n</ul>\n<h2>4. Infrastructure</h2>\n<p>The application is deployed using Docker containers orchestrated with Docker Compose. Each service runs in its own container for isolation and scalability.</p>","title":"Generated DOCX Artifact","filename":"generated-artifact.docx","wordCount":91,"preview_page_urls":{"1":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2234%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EProject%20Architecture%20Overview%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22206%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EGenerated%20as%20a%20real%20DOCX%20artifact%2C%20then%20converted%20server-side%20to%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22252%22%20width%3D%22570%22%20height%3D%221%22%20fill%3D%22%23d1d5db%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22314%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EFrontend%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22356%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ESvelteKit%20and%20Svelte%205%20render%20the%20encrypted%20document%20preview%20after%20decrypting%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22382%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3Ethe%20generated%20screenshot%20artifact%20in%20the%20browser.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22456%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2222%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3EBackend%20Pipeline%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22498%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E1.%20The%20model%20emits%20structured%20docx_model%20JSON.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22526%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E2.%20The%20Docs%20worker%20creates%20a%20canonical%20.docx%20file.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22554%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E3.%20LibreOffice%20converts%20it%20to%20PDF%3B%20PyMuPDF%20renders%20page%20screenshots.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22582%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3E4.%20DOCX%20and%20screenshots%20are%20AES-GCM%20encrypted%20before%20upload.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22660%22%20width%3D%22570%22%20height%3D%22132%22%20rx%3D%2214%22%20fill%3D%22%23eef2ff%22%20stroke%3D%22%23c7d2fe%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22711%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%233730a3%22%3EDownload%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22750%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%234338ca%22%3EThe%20download%20button%20returns%20the%20real%20generated%20DOCX%2C%20not%20browser%20HTML.%3C%2Ftext%3E%0A%3C%2Fsvg%3E","2":"data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22794%22%20height%3D%221123%22%20viewBox%3D%220%200%20794%201123%22%3E%0A%3Crect%20width%3D%22794%22%20height%3D%221123%22%20fill%3D%22%23ffffff%22%2F%3E%0A%3Crect%20x%3D%2276%22%20y%3D%2272%22%20width%3D%22642%22%20height%3D%22979%22%20rx%3D%222%22%20fill%3D%22%23ffffff%22%20stroke%3D%22%23e5e7eb%22%2F%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22148%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2230%22%20font-weight%3D%22700%22%20fill%3D%22%23111827%22%3ECompatibility%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22214%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3EExisting%20document_html%20embeds%20still%20render%20through%20the%20legacy%20HTML%20fallback.%3C%2Ftext%3E%0A%3Ctext%20x%3D%22112%22%20y%3D%22242%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2216%22%20fill%3D%22%23374151%22%3ENew%20embeds%20use%20docx_model%2C%20encrypted%20artifacts%2C%20and%20generated%20preview%20pages.%3C%2Ftext%3E%0A%3Crect%20x%3D%22112%22%20y%3D%22318%22%20width%3D%22250%22%20height%3D%22130%22%20rx%3D%2216%22%20fill%3D%22%23ecfdf5%22%20stroke%3D%22%23a7f3d0%22%2F%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22372%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%23065f46%22%3ELegacy%20HTML%3C%2Ftext%3E%0A%3Ctext%20x%3D%22142%22%20y%3D%22410%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2215%22%20fill%3D%22%23047857%22%3EStill%20viewable%20and%20downloadable.%3C%2Ftext%3E%0A%3Crect%20x%3D%22432%22%20y%3D%22318%22%20width%3D%22250%22%20height%3D%22130%22%20rx%3D%2216%22%20fill%3D%22%23fef3c7%22%20stroke%3D%22%23fde68a%22%2F%3E%0A%3Ctext%20x%3D%22462%22%20y%3D%22372%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2218%22%20font-weight%3D%22700%22%20fill%3D%22%2392400e%22%3EDOCX%20Artifact%3C%2Ftext%3E%0A%3Ctext%20x%3D%22462%22%20y%3D%22410%22%20font-family%3D%22Inter%2C%20Arial%2C%20sans-serif%22%20font-size%3D%2215%22%20fill%3D%22%23b45309%22%3ECanonical%20generated%20file.%3C%2Ftext%3E%0A%3C%2Fsvg%3E"},"page_count":2,"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "electronics/PcbSchematicEmbedFullscreen.svelte":[],
    "electronics/ElectronicsSearchEmbedFullscreen.svelte":[{"name":"processing","props":{"query":"24V to 5V isolated converter","provider":"TI WEBENCH","status":"processing","results":[]}},{"name":"error","props":{"query":"invalid converter search","provider":"TI WEBENCH","status":"error","results":[]}}],
    "electronics/ElectronicsComponentEmbedFullscreen.svelte":[{"name":"alternate","props":{"component":{"embed_id":"preview-electronics-component-fs-2","provider":"TI WEBENCH","part_number":"TPS563257DRLR","base_part_number":"TPS563257","title":"TPS564257DRLR Buck converter","topology":"Buck","package":"SOT-563","regulator_type":"Converter","control_mode":"D-CAP3","product_url":"https://www.ti.com/product/TPS563257","datasheet_url":"https://www.ti.com/lit/gpn/tps563257","description":"Compact synchronous buck converter reference design from TI WEBENCH.","bom_cost_usd":0.43,"bom_count":11,"efficiency_percent":91.8,"footprint_mm2":84.2,"frequency_hz":650000,"max_output_current_a":4,"output_ripple_vpp":0.014,"input_voltage_min_v":4.5,"input_voltage_max_v":17,"output_voltage_min_v":0.6,"output_voltage_max_v":7,"isolated":false},"hasPreviousEmbed":true,"hasNextEmbed":true}}],
    "events/EventsSearchEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"query":"AI meetups in Berlin","provider":"Meetup","results":[{"id":"evt-1","provider":"Meetup","title":"AI & Machine Learning Berlin Meetup – Spring Edition","description":"Join us for an evening of talks on LLMs, RAG architectures, and production AI.","url":"https://www.meetup.com/example-ai-berlin","date_start":"2026-03-15T19:00:00","date_end":"2026-03-15T22:00:00","timezone":"Europe/Berlin","event_type":"PHYSICAL","venue":{"name":"Factory Berlin","city":"Berlin","country":"Germany"},"organizer":{"name":"AI Berlin Community"},"rsvp_count":142,"is_paid":false},{"id":"evt-2","provider":"Meetup","title":"Web Dev Online: TypeScript Deep Dive","description":"A live online session covering advanced TypeScript patterns for scalable apps.","url":"https://www.meetup.com/example-webdev-online","date_start":"2026-03-20T18:00:00","date_end":"2026-03-20T20:00:00","timezone":"UTC","event_type":"ONLINE","venue":null,"organizer":{"name":"Web Dev Community"},"rsvp_count":87,"is_paid":false},{"id":"evt-3","provider":"Meetup","title":"Product Management Summit – London","description":"Two-day conference covering product strategy, user research, and growth tactics.","url":"https://www.meetup.com/example-pm-london","date_start":"2026-04-05T09:00:00","date_end":"2026-04-06T17:00:00","timezone":"Europe/London","event_type":"PHYSICAL","venue":{"name":"The Barbican","city":"London","country":"United Kingdom"},"organizer":{"name":"PM London"},"rsvp_count":320,"is_paid":true,"fee":{"amount":25,"currency":"GBP"}}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"noResults","props":{"query":"extremely rare events","provider":"Meetup","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "events/EventEmbedFullscreen.svelte":[{"name":"online","props":{"data":{"decodedContent":{"embed_id":"preview-event-fullscreen-online","id":"evt-preview-online","provider":"meetup","title":"TypeScript Deep Dive: Advanced Patterns for Scalable Apps","description":"A live online session covering generic constraints, conditional types, mapped types, and module augmentation.\n\nSuitable for developers with 1+ year of TypeScript experience.","url":"https://www.meetup.com/example-webdev-online/events/preview","date_start":"2026-03-20T18:00:00Z","date_end":"2026-03-20T20:00:00Z","timezone":"UTC","event_type":"ONLINE","venue":null,"organizer":{"id":"org-webdev","name":"Web Dev Community","slug":"webdev"},"rsvp_count":87,"is_paid":false,"fee":null,"image_url":null},"embedData":{"status":"finished"},"attrs":{"app_id":"events"}},"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"paid","props":{"data":{"decodedContent":{"embed_id":"preview-event-fullscreen-paid","id":"evt-preview-paid","provider":"meetup","title":"Product Management Summit – London 2026","description":"Two-day conference covering product strategy, user research, and growth tactics.\n\nDay 1: Strategy & Research\nDay 2: Growth & Execution\n\nIncludes workshop sessions, keynote talks, and networking lunch.","url":"https://www.meetup.com/example-pm-london/events/preview","date_start":"2026-04-05T09:00:00+01:00","date_end":"2026-04-06T17:00:00+01:00","timezone":"Europe/London","event_type":"PHYSICAL","venue":{"name":"The Barbican","address":"Silk St","city":"London","state":null,"country":"United Kingdom","lat":51.521,"lon":-0.093},"organizer":{"id":"org-pm-london","name":"PM London","slug":"pm-london"},"rsvp_count":320,"is_paid":true,"fee":{"amount":25,"currency":"GBP"},"image_url":null},"embedData":{"status":"finished"},"attrs":{"app_id":"events"}},"hasPreviousEmbed":true,"hasNextEmbed":false}}],
    "file/FileEmbedFullscreen.svelte":[],
    "finance/FinanceCheckAccountsEmbedFullscreen.svelte":[{"name":"filtered","props":{"embedId":"preview-finance-check-accounts-filtered","data":{"decodedContent":{"app_id":"finance","skill_id":"check_accounts","status":"finished","period":"monthly","account_count":2,"transaction_count":5,"provider":"Revolut Business","overview":{"accounts":[{"account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","display_label":"Operating EUR","currency":"EUR","balance":8450.25,"balance_as_of":"2026-07-15"},{"account_ref":"acct-savings-eur","source_ref":"revolut_business:connected-account","display_label":"Savings EUR","currency":"EUR","balance":12500,"balance_as_of":"2026-07-15"}],"transactions":[{"transaction_ref":"revolut_business:tx-001","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-05-05","amount":4200,"currency":"EUR","direction":"income","category":"revenue","counterparty_placeholder":"[PAYER_REVENUE_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-002","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-05-08","amount":-760.8,"currency":"EUR","direction":"expense","category":"software","counterparty_placeholder":"[MERCHANT_SOFTWARE_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-003","account_ref":"acct-savings-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-06-03","amount":3800,"currency":"EUR","direction":"income","category":"revenue","counterparty_placeholder":"[PAYER_REVENUE_002]","state":"completed"},{"transaction_ref":"revolut_business:tx-004","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-06-12","amount":-1180.45,"currency":"EUR","direction":"expense","category":"travel","counterparty_placeholder":"[MERCHANT_TRAVEL_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-005","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-07-02","amount":-350,"currency":"EUR","direction":"expense","category":"meals","counterparty_placeholder":"[MERCHANT_MEALS_001]","state":"completed"}],"summaries":{"period":"monthly","income_total":8000,"expense_total":2291.25,"net_total":5708.75,"by_category":{"revenue":{"income":8000,"expense":0,"net":8000},"software":{"income":0,"expense":760.8,"net":-760.8},"travel":{"income":0,"expense":1180.45,"net":-1180.45},"meals":{"income":0,"expense":350,"net":-350}},"time_series":[{"bucket":"2026-05","income":4200,"expense":760.8,"net":3439.2,"transaction_count":2},{"bucket":"2026-06","income":3800,"expense":1180.45,"net":2619.55,"transaction_count":2},{"bucket":"2026-07","income":0,"expense":350,"net":-350,"transaction_count":1}],"filters_applied":{}},"filter_options":{"accounts":["acct-main-eur","acct-savings-eur"],"sources":["revolut_business:connected-account"],"categories":["meals","revenue","software","travel"],"directions":["expense","income"],"states":["completed"],"placeholders":["[MERCHANT_MEALS_001]","[MERCHANT_SOFTWARE_001]","[MERCHANT_TRAVEL_001]","[PAYER_REVENUE_001]","[PAYER_REVENUE_002]"]}},"summary":"Finance overview for 2 accounts and 5 transactions: income 8000, expenses 2291.25."},"embedData":{"status":"finished"},"attrs":{"app_id":"finance","skill_id":"check_accounts"}},"hasPreviousEmbed":false,"hasNextEmbed":false,"piiMappings":[],"piiRevealed":false}},{"name":"ownerPiiRevealed","props":{"embedId":"preview-finance-check-accounts-owner-pii","data":{"decodedContent":{"app_id":"finance","skill_id":"check_accounts","status":"finished","period":"monthly","account_count":2,"transaction_count":5,"provider":"Revolut Business","overview":{"accounts":[{"account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","display_label":"Operating EUR","currency":"EUR","balance":8450.25,"balance_as_of":"2026-07-15"},{"account_ref":"acct-savings-eur","source_ref":"revolut_business:connected-account","display_label":"Savings EUR","currency":"EUR","balance":12500,"balance_as_of":"2026-07-15"}],"transactions":[{"transaction_ref":"revolut_business:tx-001","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-05-05","amount":4200,"currency":"EUR","direction":"income","category":"revenue","counterparty_placeholder":"[PAYER_REVENUE_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-002","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-05-08","amount":-760.8,"currency":"EUR","direction":"expense","category":"software","counterparty_placeholder":"[MERCHANT_SOFTWARE_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-003","account_ref":"acct-savings-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-06-03","amount":3800,"currency":"EUR","direction":"income","category":"revenue","counterparty_placeholder":"[PAYER_REVENUE_002]","state":"completed"},{"transaction_ref":"revolut_business:tx-004","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-06-12","amount":-1180.45,"currency":"EUR","direction":"expense","category":"travel","counterparty_placeholder":"[MERCHANT_TRAVEL_001]","state":"completed"},{"transaction_ref":"revolut_business:tx-005","account_ref":"acct-main-eur","source_ref":"revolut_business:connected-account","posted_at":"2026-07-02","amount":-350,"currency":"EUR","direction":"expense","category":"meals","counterparty_placeholder":"[MERCHANT_MEALS_001]","state":"completed"}],"summaries":{"period":"monthly","income_total":8000,"expense_total":2291.25,"net_total":5708.75,"by_category":{"revenue":{"income":8000,"expense":0,"net":8000},"software":{"income":0,"expense":760.8,"net":-760.8},"travel":{"income":0,"expense":1180.45,"net":-1180.45},"meals":{"income":0,"expense":350,"net":-350}},"time_series":[{"bucket":"2026-05","income":4200,"expense":760.8,"net":3439.2,"transaction_count":2},{"bucket":"2026-06","income":3800,"expense":1180.45,"net":2619.55,"transaction_count":2},{"bucket":"2026-07","income":0,"expense":350,"net":-350,"transaction_count":1}],"filters_applied":{}},"filter_options":{"accounts":["acct-main-eur","acct-savings-eur"],"sources":["revolut_business:connected-account"],"categories":["meals","revenue","software","travel"],"directions":["expense","income"],"states":["completed"],"placeholders":["[MERCHANT_MEALS_001]","[MERCHANT_SOFTWARE_001]","[MERCHANT_TRAVEL_001]","[PAYER_REVENUE_001]","[PAYER_REVENUE_002]"]}},"summary":"Finance overview for 2 accounts and 5 transactions: income 8000, expenses 2291.25."},"embedData":{"status":"finished"},"attrs":{"app_id":"finance","skill_id":"check_accounts"}},"hasPreviousEmbed":false,"hasNextEmbed":false,"piiMappings":[{"placeholder":"[MERCHANT_SOFTWARE_001]","original":"Acme Software Ltd","type":"merchant"},{"placeholder":"[PAYER_REVENUE_001]","original":"Northstar Client","type":"payer"}],"piiRevealed":true}}],
    "fitness/FitnessSearchEmbedFullscreen.svelte":[{"name":"empty","props":{"data":{"decodedContent":{"app_id":"fitness","skill_id":"search_classes","provider":"Urban Sports Club","results":[{"id":"empty","provider":"Urban Sports Club","result_count":0,"filters":{"query":"yoga","address":"Sorauer Str. 12, Berlin","radius_km":3,"plan":"all","attendance_mode":"onsite"},"summary":"No Urban Sports classes found.","results":[]}]},"embedData":{"status":"finished","skill_id":"search_classes"},"attrs":{"app_id":"fitness"}}}}],
    "fitness/FitnessResultEmbedFullscreen.svelte":[],
    "health/HealthSearchEmbedFullscreen.svelte":[{"name":"processing","props":{"query":"Cardiologist near me","provider":"Doctolib, Jameda","status":"processing","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"error","props":{"query":"Specialist search failed","provider":"Doctolib, Jameda","status":"error","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"errorMessage":"Could not connect to Doctolib. Please try again."}},{"name":"jamedaOnly","props":{"query":"Hausarzt in Berlin","provider":"Jameda","status":"finished","results":[{"embed_id":"preview-health-fs-jam-1","type":"appointment","slot_datetime":"2026-04-03T09:00:00","name":"Ingmar Frank","speciality":"Allgemeinmediziner","address":"Potsdamer Chaussee 80, Berlin","provider_platform":"Jameda","booking_url":"https://www.jameda.de/booking/datum-auswaehlen/270886/508647/2026-04-03T09:00:00+01:00","rating":5,"rating_count":10,"service_name":"Erstuntersuchung (Neupatient/in)"},{"embed_id":"preview-health-fs-jam-2","type":"appointment","slot_datetime":"2026-04-03T09:10:00","name":"Nikolaus Peter Höllen","speciality":"Allgemeinmediziner","address":"Kyffhäuserstr. 11, Berlin","provider_platform":"Jameda","booking_url":"https://www.jameda.de/booking/datum-auswaehlen/89012/396782/2026-04-03T09:10:00+01:00","rating":5,"rating_count":165,"price":30,"service_name":"Allgemeine Sprechstunde"}],"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "health/HealthAppointmentEmbedFullscreen.svelte":[{"name":"telehealth","props":{"data":{"decodedContent":{"embed_id":"preview-health-appointment-fs-telehealth","slot_datetime":"2026-04-05T14:00:00","name":"Prof. Dr. Klaus Weber","speciality":"Cardiologist","address":"Leopoldstraße 45\n80802 Munich","gps_coordinates":{"latitude":48.1584,"longitude":11.5798},"insurance":"private","telehealth":true,"practice_url":"https://www.doctolib.de/cardiologue/munich/klaus-weber","provider":"Doctolib","provider_platform":"Doctolib"},"embedData":{"status":"finished"},"attrs":{"app_id":"health"}},"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"jameda","props":{"data":{"decodedContent":{"embed_id":"preview-health-appointment-fs-jameda","slot_datetime":"2026-04-03T08:00:00","name":"Dr. Markus Reinholz","speciality":"Hautarzt / Dermatologe","address":"Frauenplatz 11\n80331 München","gps_coordinates":{"latitude":48.1374,"longitude":11.5733},"insurance":"","telehealth":false,"provider":"Jameda","provider_platform":"Jameda","booking_url":"https://www.jameda.de/booking/datum-auswaehlen/12345/67890/2026-04-03T08:00:00+01:00","rating":5,"rating_count":125,"price":120,"service_name":"Erstuntersuchung (Neupatient/in)"},"embedData":{"status":"finished"},"attrs":{"app_id":"health"}},"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"jamedaNoMap","props":{"data":{"decodedContent":{"embed_id":"preview-health-appointment-fs-jameda-nomap","slot_datetime":"2026-04-04T09:30:00","name":"Konrad Witkowski","speciality":"Zahnarzt","address":"Hoheluftchaussee 2, 20253 Hamburg","provider":"Jameda","provider_platform":"Jameda","booking_url":"https://www.jameda.de/booking/datum-auswaehlen/44444/55555/2026-04-04T09:30:00+01:00","rating":4.8,"rating_count":46,"service_name":"Allgemeine Sprechstunde"},"embedData":{"status":"finished"},"attrs":{"app_id":"health"}},"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"noMap","props":{"data":{"decodedContent":{"embed_id":"preview-health-appointment-fs-nomap","slot_datetime":"2026-04-04T08:30:00","name":"Dr. Anna Schmidt","speciality":"General Practitioner","address":"Sendlinger Straße 8, 80331 Munich","insurance":"public","telehealth":false,"practice_url":"https://www.doctolib.de/medecin-generaliste/munich/anna-schmidt","provider":"Doctolib","provider_platform":"Doctolib"},"embedData":{"status":"finished"},"attrs":{"app_id":"health"}},"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "home/HomeSearchEmbedFullscreen.svelte":[{"name":"processing","props":{"query":"Berlin","provider":"Multi","status":"processing","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"withNavigation","props":{"query":"Berlin","provider":"Multi","status":"finished","results":[{"title":"Schöne 2-Zimmer-Wohnung in Kreuzberg","price_label":"850 EUR/month","size_sqm":55,"rooms":2,"address":"Bergmannstr., 10961 Berlin","image_url":"","url":"https://www.immobilienscout24.de/expose/12345","provider":"ImmoScout24","listing_type":"rent"},{"title":"WG-Zimmer in Prenzlauer Berg — möbliert, ab sofort","price_label":"500 EUR/month","size_sqm":18,"rooms":1,"address":"Schönhauser Allee, 10439 Berlin","image_url":"","url":"https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html","provider":"WG-Gesucht","listing_type":"rent"},{"title":"Helle 3-Zimmer-Altbauwohnung mit Balkon","price_label":"1.200 EUR/month","size_sqm":85,"rooms":3,"address":"Friedrichshain, 10245 Berlin","image_url":"","url":"https://www.kleinanzeigen.de/s-anzeige/67890","provider":"Kleinanzeigen","listing_type":"rent"},{"title":"Großzügiges Loft in Mitte mit Dachterrasse","price_label":"2.100 EUR/month","size_sqm":120,"rooms":4,"address":"Rosenthaler Str., 10119 Berlin","image_url":"","url":"https://www.immobilienscout24.de/expose/99999","provider":"ImmoScout24","listing_type":"rent"}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"error","props":{"query":"Berlin","provider":"Multi","status":"error","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"errorMessage":"All providers failed. Please try again."}}],
    "home/HomeListingEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"title":"Schöne 2-Zimmer-Wohnung in Kreuzberg","price_label":"850 EUR/month","size_sqm":55,"rooms":2,"address":"Bergmannstr. 12, 10961 Berlin","image_url":"","url":"https://www.immobilienscout24.de/expose/12345","provider":"ImmoScout24","listing_type":"rent","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"wgRoom","props":{"title":"Gemütliches WG-Zimmer in Prenzlauer Berg — ab sofort, möbliert","price_label":"500 EUR/month","size_sqm":18,"rooms":1,"address":"Schönhauser Allee, 10439 Berlin","image_url":"","url":"https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html","provider":"WG-Gesucht","listing_type":"rent","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"buyListing","props":{"title":"Eigentumswohnung in München-Schwabing — ruhige Lage","price_label":"450.000 EUR","size_sqm":75,"rooms":3,"address":"Leopoldstr., 80802 München","image_url":"","url":"https://www.immobilienscout24.de/expose/99999","provider":"ImmoScout24","listing_type":"buy","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "images/ImageGenerateEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"prompt":"A serene mountain landscape at sunset with vibrant orange and purple skies","model":"flux-schnell","aspectRatio":"16:9","status":"finished","skillId":"generate","generatedAt":"2026-02-17T10:30:00Z","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"draft","props":{"prompt":"Quick sketch of a cat wearing a top hat","model":"flux-schnell","aspectRatio":"16:9","status":"finished","skillId":"generate_draft","generatedAt":"2026-02-17T10:30:00Z","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"error","props":{"prompt":"A serene mountain landscape at sunset with vibrant orange and purple skies","model":"flux-schnell","aspectRatio":"16:9","status":"error","skillId":"generate","generatedAt":"2026-02-17T10:30:00Z","hasPreviousEmbed":false,"hasNextEmbed":false,"error":"Image generation failed: content policy violation"}},{"name":"processing","props":{"prompt":"A serene mountain landscape at sunset with vibrant orange and purple skies","model":"flux-schnell","aspectRatio":"16:9","status":"processing","skillId":"generate","generatedAt":"2026-02-17T10:30:00Z","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"square","props":{"prompt":"A detailed portrait of a robot reading a book in a cozy library","model":"flux-schnell","aspectRatio":"1:1","status":"finished","skillId":"generate","generatedAt":"2026-02-17T10:30:00Z","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "images/ImageEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"filename":"golden-gate-sunset.jpg","fileSize":2411520,"fileType":"image/jpeg","isAuthenticated":true,"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"png","props":{"filename":"screenshot-2026-03-10.png","fileSize":856320,"fileType":"image/png","isAuthenticated":true,"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "images/ImagesSearchEmbedFullscreen.svelte":[{"name":"processing","props":{"query":"Golden Gate Bridge","provider":"Brave","status":"processing","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"withNavigation","props":{"query":"Golden Gate Bridge","provider":"Brave","status":"finished","results":[{"title":"Golden Gate Bridge at dusk","source":"unsplash.com","source_page_url":"https://unsplash.com/photos/Cs99I6PYLlk","thumbnail_url":"https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=300","image_url":"https://images.unsplash.com/photo-1501594907352-04cda38ebc29"},{"title":"Aerial view of Golden Gate Bridge","source":"unsplash.com","source_page_url":"https://unsplash.com/photos/golden-gate-aerial","thumbnail_url":"https://images.unsplash.com/photo-1506146332389-18140dc7b2fb?w=300","image_url":"https://images.unsplash.com/photo-1506146332389-18140dc7b2fb"},{"title":"Golden Gate Bridge towers in fog","source":"unsplash.com","source_page_url":"https://unsplash.com/photos/golden-gate-fog","thumbnail_url":"https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=300","image_url":"https://images.unsplash.com/photo-1558618666-fcd25c85cd64"},{"title":"Golden Gate Bridge from Baker Beach","source":"unsplash.com","source_page_url":"https://unsplash.com/photos/golden-gate-baker-beach","thumbnail_url":"https://images.unsplash.com/photo-1449034446853-66c86144b0ad?w=300","image_url":"https://images.unsplash.com/photo-1449034446853-66c86144b0ad"},{"title":"Golden Gate in evening light","source":"unsplash.com","source_page_url":"https://unsplash.com/photos/golden-gate-evening","thumbnail_url":"https://images.unsplash.com/photo-1534430480872-3498386e7856?w=300","image_url":"https://images.unsplash.com/photo-1534430480872-3498386e7856"},{"title":"Golden Gate Bridge under blue sky","source":"unsplash.com","source_page_url":"https://unsplash.com/photos/golden-gate-marin-headlands","thumbnail_url":"https://images.unsplash.com/photo-1521747116042-5a810fda9664?w=300","image_url":"https://images.unsplash.com/photo-1521747116042-5a810fda9664"}],"hasPreviousEmbed":true,"hasNextEmbed":true}}],
    "images/ImageResultEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"title":"Golden Gate Bridge at dusk","source_domain":"unsplash.com","source_page_url":"https://unsplash.com/photos/Cs99I6PYLlk","image_url":"https://images.unsplash.com/photo-1501594907352-04cda38ebc29","thumbnail_url":"https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"failedImage","props":{"title":"Golden Gate Bridge at dusk","source_domain":"unsplash.com","source_page_url":"https://unsplash.com/photos/Cs99I6PYLlk","image_url":"data:image/png;base64,invalid-image","thumbnail_url":"data:image/png;base64,invalid-thumbnail","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "mail/MailEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"data":{"decodedContent":{"receiver":"anna@example.com","subject":"Project Update — Sprint 12 Review","content":"Hi Anna,\n\nThe latest sprint review went well. All tickets were closed except the auth refactor, which is carried over to Sprint 13.\n\nKey highlights:\n- Login flow redesigned (done)\n- API rate limiting added (done)\n- Auth refactor (carried over)\n\nLet me know if you have any questions.\n\nBest,\nMax","footer":""}},"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"short","props":{"data":{"decodedContent":{"receiver":"team@example.com","subject":"Quick update","content":"All systems nominal. Deploy scheduled for 18:00.","footer":""}},"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "mail/MailSearchEmbedFullscreen.svelte":[],
    "maps/MapsSearchEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"query":"coffee shops near Marienplatz Munich","provider":"Google","results":[{"embed_id":"preview-maps-place-1","displayName":"Man vs. Machine Coffee Roasters","formattedAddress":"Müllerstraße 23, 80469 Munich","rating":4.7,"userRatingCount":1832,"location":{"latitude":48.1321,"longitude":11.5718}},{"embed_id":"preview-maps-place-2","displayName":"Lost Weekend","formattedAddress":"Schellingstraße 3, 80799 Munich","rating":4.5,"userRatingCount":2456,"location":{"latitude":48.1523,"longitude":11.5784}},{"embed_id":"preview-maps-place-3","displayName":"Café Frischhut","formattedAddress":"Prälat-Zistl-Straße 8, 80331 Munich","rating":4.6,"userRatingCount":3210,"location":{"latitude":48.1354,"longitude":11.5762}}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"noResults","props":{"query":"unicorn cafes in Antarctica","provider":"Google","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"noVerifiedAmenityMatches","props":{"query":"restaurants in Berlin with air conditioning and free wifi","provider":"Google Maps + Geoapify","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"warnings":["No Geoapify/OSM-verified matches were found within the enrichment budget; try relaxing the amenity filter."],"filter_summary":{"required":["air_conditioning","internet_access"],"candidate_count":10,"verified_count":0,"status":"no_verified_results"}}}],
    "maps/MapLocationEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"displayName":"Man vs. Machine Coffee Roasters","formattedAddress":"Müllerstraße 23, 80469 Munich, Germany","lat":48.1321,"lon":11.5718,"zoom":16,"rating":4.7,"userRatingCount":1832,"placeType":"Coffee Shop","websiteUri":"https://www.mvsm.coffee","placeId":"ChIJabc123","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"noCoords","props":{"displayName":"Lost Weekend","formattedAddress":"Schellingstraße 3, 80799 Munich","lat":48.1321,"lon":11.5718,"zoom":16,"rating":4.5,"userRatingCount":2456,"placeType":"Coffee Shop & Bookstore","websiteUri":"https://www.mvsm.coffee","placeId":"ChIJabc123"}},{"name":"minimal","props":{"displayName":"Café Frischhut","formattedAddress":"Müllerstraße 23, 80469 Munich, Germany","lat":48.1354,"lon":11.5762,"zoom":16,"rating":4.7,"userRatingCount":1832,"placeType":"Coffee Shop","websiteUri":"https://www.mvsm.coffee","placeId":"ChIJabc123"}}],
    "maps/MapsLocationEmbedFullscreen.svelte":[{"name":"nearbyArea","props":{"lat":52.5251,"lon":13.3694,"zoom":16,"name":"Berlin Hauptbahnhof","address":"Near Potsdamer Platz, Berlin","locationType":"area","status":"finished"}},{"name":"staticImage","props":{"lat":52.5251,"lon":13.3694,"zoom":16,"name":"Berlin Hauptbahnhof","address":"Europaplatz 1, 10557 Berlin","locationType":"precise_location","mapImageUrl":"data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20640%20360%22%3E%3Crect%20width%3D%22640%22%20height%3D%22360%22%20fill%3D%22%23e5e7eb%22%2F%3E%3Ctext%20x%3D%22320%22%20y%3D%22180%22%20text-anchor%3D%22middle%22%20dominant-baseline%3D%22middle%22%20font-family%3D%22sans-serif%22%20font-size%3D%2232%22%20fill%3D%22%236b7280%22%3EMap%20preview%3C%2Ftext%3E%3C%2Fsvg%3E","status":"finished"}},{"name":"noCoordinates","props":{"zoom":16,"name":"Berlin Hauptbahnhof","address":"Europaplatz 1, 10557 Berlin","locationType":"precise_location","mapImageUrl":"data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20640%20360%22%3E%3Crect%20width%3D%22640%22%20height%3D%22360%22%20fill%3D%22%23e5e7eb%22%2F%3E%3Ctext%20x%3D%22320%22%20y%3D%22180%22%20text-anchor%3D%22middle%22%20dominant-baseline%3D%22middle%22%20font-family%3D%22sans-serif%22%20font-size%3D%2232%22%20fill%3D%22%236b7280%22%3EMap%20preview%3C%2Ftext%3E%3C%2Fsvg%3E","status":"finished"}},{"name":"withNavigation","props":{"lat":52.5251,"lon":13.3694,"zoom":16,"name":"Berlin Hauptbahnhof","address":"Europaplatz 1, 10557 Berlin","locationType":"precise_location","status":"finished","hasPreviousEmbed":true,"hasNextEmbed":true}}],
    "math/MathCalculateEmbedFullscreen.svelte":[{"name":"processing","props":{"query":"integrate(x^2, x, 0, 1)","subtitle":"Numeric mode","status":"processing","results":[],"embedId":"preview-math-calculate-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"error","props":{"query":"1/0","subtitle":"Numeric mode","status":"error","results":[],"embedId":"preview-math-calculate-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"with_steps","props":{"query":"solve(x^2 - 4, x)","subtitle":"Numeric mode","status":"finished","results":[{"expression":"solve(x^2 - 4, x)","result":"[-2, 2]","result_type":"list","mode":"solve","steps":["x^2 - 4 = 0","(x-2)(x+2) = 0","x = 2 or x = -2"]}],"embedId":"preview-math-calculate-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "math/MathPlotEmbedFullscreen.svelte":[{"name":"single_function","props":{"plotSpec":"f(x) = x^2 - 2*x + 1","title":"Quadratic: x² - 2x + 1","embedId":"preview-math-plot-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"polynomial","props":{"plotSpec":"f(x) = x^3 - 3*x\nf(x) = 3*x^2 - 3","title":"Cubic and Its Derivative","embedId":"preview-math-plot-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "mindmaps/MindMapEmbedFullscreen.svelte":[{"name":"invalidSource","props":{"data":{"decodedContent":{"source_json":"This is not a valid mindmap document","title":"Invalid map"},"attrs":{}}}}],
    "models3d/Model3DSearchEmbedFullscreen.svelte":[],
    "models3d/Model3DResultEmbedFullscreen.svelte":[],
    "models3d/Model3DGenerateEmbedFullscreen.svelte":[],
    "music/MusicGenerateEmbedFullscreen.svelte":[{"name":"jingle","props":{"data":{"decodedContent":{"prompt":"An upbeat electronic product jingle with warm synth bass","mode":"jingle","model":"lyria-3-pro-preview","duration_seconds":45,"generated_at":"2026-05-21T23:30:00Z","watermarking":"SynthID"},"embedData":{"status":"finished"},"attrs":{"app_id":"music","skill_id":"generate"}},"embedId":"preview-music-generate-1"}},{"name":"error","props":{"data":{"decodedContent":{"prompt":"A 30 second ambient synth background loop with soft pads and no drums","mode":"background","model":"lyria-3-clip-preview","duration_seconds":30,"generated_at":"2026-05-21T23:30:00Z","watermarking":"SynthID","error":"Music generation failed: provider returned no audio output"},"embedData":{"status":"error"},"attrs":{"app_id":"music","skill_id":"generate"}},"embedId":"preview-music-generate-1"}}],
    "news/NewsSearchEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"query":"latest technology news 2026","provider":"Brave Search","results":[{"title":"AI Advances Continue to Transform Software Development","url":"https://techcrunch.com/2026/ai-advances","description":"New AI-powered development tools are changing how developers write, test, and deploy software.","favicon":"/favicon.png","thumbnail":{"original":"/images/og-image.jpg"},"publishedAt":"2026-02-15T08:00:00Z"},{"title":"WebAssembly 3.0 Specification Finalized","url":"https://theverge.com/2026/wasm-3","description":"The W3C has finalized the WebAssembly 3.0 specification, bringing garbage collection and improved threading.","favicon":"/favicon.png","thumbnail":{"original":"/images/og-image.jpg"},"publishedAt":"2026-02-10T12:00:00Z"},{"title":"European Tech Scene Sees Record Venture Capital Investment","url":"https://bbc.com/news/eu-vc","description":"European startups raised a record €45 billion in venture capital funding in Q4 2025.","favicon":"/favicon.png","thumbnail":{"original":"/images/og-image.jpg"},"publishedAt":"2026-01-28T09:00:00Z"}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"noResults","props":{"query":"extremely obscure news topic","provider":"Brave Search","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "web/WebsiteEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"data":{"decodedContent":{"url":"https://svelte.dev","title":"Svelte — Cybernetically enhanced web apps","description":"Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.","favicon":"https://svelte.dev/favicon.png","image":""},"embedData":{"status":"finished"},"attrs":{"app_id":"web","skill_id":"website"}},"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"withSnippets","props":{"data":{"decodedContent":{"url":"https://github.com/sveltejs/svelte","title":"sveltejs/svelte: Cybernetically enhanced web apps","description":"Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.","favicon":"https://svelte.dev/favicon.png","image":"","extra_snippets":["Svelte shifts work from the browser to a compile step that happens when you build your app.","Instead of using techniques like virtual DOM diffing, Svelte writes code that updates the DOM when state changes."]},"embedData":{"status":"finished"},"attrs":{"app_id":"web","skill_id":"website"}},"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"withHighlightedQuote","props":{"data":{"decodedContent":{"url":"https://github.com/sveltejs/svelte","title":"sveltejs/svelte: Cybernetically enhanced web apps","description":"Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.","favicon":"https://svelte.dev/favicon.png","extra_snippets":["Svelte shifts work from the browser to a compile step that happens when you build your app.","Instead of using techniques like virtual DOM diffing, Svelte writes code that updates the DOM when state changes."]},"embedData":{"status":"finished"},"attrs":{"app_id":"web","skill_id":"website"},"highlightQuoteText":"Svelte writes code that updates the DOM when state changes"},"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"minimal","props":{"data":{"decodedContent":{"url":"https://svelte.dev/page"},"embedData":{"status":"finished"},"attrs":{"app_id":"web","skill_id":"website"}},"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "nutrition/NutritionSearchEmbedFullscreen.svelte":[{"name":"processing","props":{"data":{"embedType":"app-skill-use","appId":"nutrition","skillId":"search_recipes","embedData":{"status":"processing"},"decodedContent":{"query":"vegetarische Pasta","provider":"Edamam","status":"processing","results":[]}},"embedId":"preview-nutrition-search-fs"}},{"name":"error","props":{"data":{"embedType":"app-skill-use","appId":"nutrition","skillId":"search_recipes","embedData":{"status":"error"},"decodedContent":{"query":"vegetarische Pasta","provider":"Edamam","status":"error","results":[],"error":"Edamam recipe API returned an error"}},"embedId":"preview-nutrition-search-fs"}}],
    "nutrition/NutritionRecipeEmbedFullscreen.svelte":[{"name":"fullData","props":{"recipe":{"embed_id":"preview-recipe-fs-full","title":"Vegane Gemüse-Lasagne","description":"Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl, Knoblauch und Chili. Einfach, schnell und unglaublich lecker.","image_url":null,"recipe_url":"https://www.edamam.com/results/recipes/?search=spaghetti%20aglio%20e%20olio","prep_time_minutes":10,"cook_time_minutes":15,"total_time_minutes":75,"difficulty":"mittel","servings":6,"rating":4.8,"rating_count":89,"ernaehrwert_score":9,"dietary_tags":["vegan","glutenfrei","laktosefrei"],"categories":["Hauptspeise","Auflauf"],"ingredients":[{"amount":"400","unit":"g","name":"Spaghetti"},{"amount":"6","unit":"Zehen","name":"Knoblauch"},{"amount":"100","unit":"ml","name":"Olivenöl (extra vergine)"},{"amount":"1","unit":"TL","name":"Chiliflocken"},{"amount":"1","unit":"Bund","name":"Petersilie"},{"name":"Salz und Pfeffer"}],"instructions":[{"step":1,"text":"Spaghetti in einem großen Topf mit reichlich Salzwasser al dente kochen. Etwas Kochwasser aufheben."},{"step":2,"text":"Knoblauch schälen und in dünne Scheiben schneiden. Petersilie fein hacken."},{"step":3,"text":"Olivenöl in einer großen Pfanne bei mittlerer Hitze erwärmen. Knoblauch darin goldbraun anbraten (nicht zu dunkel!)."},{"step":4,"text":"Chiliflocken zum Knoblauch geben und kurz mitrösten."},{"step":5,"text":"Abgetropfte Spaghetti in die Pfanne geben, mit etwas Kochwasser vermengen. Mit Petersilie, Salz und Pfeffer abschmecken."}],"nutrition":{"calories_kcal":520,"protein_g":14,"fat_g":22,"carbs_g":68}},"embedId":"preview-recipe-fs-full"}},{"name":"minimal","props":{"recipe":{"embed_id":"preview-recipe-fs-minimal","title":"Einfacher Gurkensalat"},"embedId":"preview-recipe-fs-minimal"}}],
    "pdf/PDFEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"filename":"Q4-2025-Annual-Report.pdf","pageCount":42,"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"singlePage","props":{"filename":"invoice-2025-Q4.pdf","pageCount":1,"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "reminder/ReminderEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"reminderId":"rem-abc-123","triggerAtFormatted":"Tomorrow at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":false,"message":"Reminder set successfully! I will remind you tomorrow at 9:00 AM.","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"repeating","props":{"reminderId":"rem-abc-123","triggerAtFormatted":"Every Monday at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":true,"message":"Repeating reminder set! I will remind you every Monday at 9:00 AM.","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"error","props":{"reminderId":"rem-abc-123","triggerAtFormatted":"Tomorrow at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":false,"hasPreviousEmbed":false,"hasNextEmbed":false,"error":"Could not create reminder: invalid trigger time."}},{"name":"withEmailWarning","props":{"reminderId":"rem-abc-123","triggerAtFormatted":"Tomorrow at 9:00 AM","triggerAt":1773649800,"targetType":"new_chat","isRepeating":false,"message":"Reminder set successfully! I will remind you tomorrow at 9:00 AM.","hasPreviousEmbed":false,"hasNextEmbed":false,"emailNotificationWarning":"Email notifications are not enabled. You will only receive in-app notifications."}}],
    "shopping/ShoppingSearchEmbedFullscreen.svelte":[{"name":"processing","props":{"query":"wireless headphones","provider":"Amazon","status":"processing","results":[]}},{"name":"error","props":{"query":"bio joghurt","provider":"REWE","status":"error","results":[]}},{"name":"amazon","props":{"query":"noise cancelling headphones","provider":"Amazon","status":"finished","results":[{"asin":"B0CH7DL6JW","title":"Sony WH-1000XM5 Wireless Noise Cancelling Headphones","brand":"Sony","price":"279.00","price_amount":279,"currency_symbol":"€","rating":4.7,"reviews":3842,"prime":true,"image_url":null,"purchase_url":"https://www.amazon.de/dp/B0CH7DL6JW"},{"asin":"B09JQS53RZ","title":"Bose QuietComfort 45 Bluetooth Wireless Headphones","brand":"Bose","price":"249.00","price_amount":249,"currency_symbol":"€","rating":4.6,"reviews":2156,"prime":true,"image_url":null,"purchase_url":"https://www.amazon.de/dp/B09JQS53RZ"},{"asin":"B09JQS53RX","title":"Apple AirPods Max Wireless Over-Ear Headphones","brand":"Apple","price":"499.00","price_amount":499,"currency_symbol":"€","rating":4.5,"reviews":1204,"prime":false,"image_url":null,"purchase_url":"https://www.amazon.de/dp/B09JQS53RX"}]}},{"name":"mobile","props":{"query":"bio joghurt","provider":"REWE","status":"finished","results":[{"product_id":"rewe-12345","title":"Bio Vollmilch-Joghurt Naturell","brand":"Weihenstephan","price_cents":139,"price_eur":"1,39 €","grammage":"500g (0,28 €/100g)","purchase_url":"https://shop.rewe.de/p/weihenstephan-bio-joghurt/12345","image_url":null,"attributes":{"is_organic":true}},{"product_id":"rewe-12346","title":"Demeter Bio-Joghurt mild","brand":"Andechser Natur","price_cents":249,"price_eur":"2,49 €","grammage":"500g (0,50 €/100g)","purchase_url":"https://shop.rewe.de/p/andechser-demeter-joghurt/12346","image_url":null,"attributes":{"is_organic":true,"is_vegetarian":true}},{"product_id":"rewe-12347","title":"Griechischer Joghurt 10% Fett","brand":"REWE Bio","price_cents":189,"price_eur":"1,89 €","grammage":"400g (0,47 €/100g)","purchase_url":"https://shop.rewe.de/p/rewe-bio-griechischer-joghurt/12347","image_url":null,"attributes":{"is_organic":true,"is_vegetarian":true}},{"product_id":"rewe-12348","title":"Skyr Natur 0,2% Fett","brand":"REWE Beste Wahl","price_cents":99,"price_eur":"0,99 €","grammage":"450g (0,22 €/100g)","purchase_url":"https://shop.rewe.de/p/rewe-skyr-natur/12348","image_url":null,"attributes":{"is_vegetarian":true}}],"isMobile":true}}],
    "shopping/ShoppingResultEmbedFullscreen.svelte":[{"name":"amazon","props":{"product":{"embed_id":"preview-shopping-result-fs-amazon","asin":"B0CH7DL6JW","title":"Sony WH-1000XM5 Wireless Noise Cancelling Headphones","brand":"Sony","price":"€279.00","price_amount":279,"old_price_amount":329,"currency_symbol":"€","purchase_url":"https://www.amazon.de/dp/B0CH7DL6JW","image_url":null,"rating":4.7,"reviews":3842,"prime":true,"delivery":["KOSTENLOSE Lieferung bis morgen"],"bought_last_month":"2K+ bought in past month","provider":"Amazon","country":"DE","attributes":{"is_new":true}},"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"stoffe","props":{"product":{"embed_id":"preview-shopping-result-fs-stoffe","product_id":"68087512","variation_id":"112466","title":"Baumwoll-Musselin - Double Gauze Bestickt Zitronen Weiß","brand":"Snaply","price":"15,19 €","price_eur":"15,19 €","price_amount":15.19,"base_price":"15,19 € / Meter","unit":"Meter","stock":20.5,"availability":"Sofort versandfertig, Lieferzeit 2-4 Werktage","is_salable":true,"color_child_item_ids":["68087513","68087514"],"purchase_url":"https://www.stoffe.de/zitronen-musselin/a-68087512/","image_url":null,"provider":"Stoffe.de","attributes":{"Material":"Baumwolle","Baumwolle %":"100","Stoffbreite (cm)":"130","Gramm pro Laufmeter":"145","Motiv":"Zitronen","Verwendung":"Kleider, Blusen, Kinderbekleidung"}},"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"noPrice","props":{"product":{"embed_id":"preview-shopping-result-fs-no-price","title":"Produkt ohne Preisangabe","brand":"Unknown Brand","purchase_url":"https://shop.rewe.de/","image_url":null,"provider":"REWE"}}}],
    "social_media/SocialMediaGetPostsEmbedFullscreen.svelte":[],
    "social_media/SocialMediaPostEmbedFullscreen.svelte":[],
    "social_media/SocialMediaSearchEmbedFullscreen.svelte":[],
    "tasks/TaskCreateEmbedFullscreen.svelte":[],
    "tasks/TaskEmbedFullscreen.svelte":[],
    "tasks/TaskSearchEmbedFullscreen.svelte":[],
    "travel/TravelSearchEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"query":"Munich -> London, 2026-03-15","provider":"Google","status":"finished","results":[{"price":"189.00","currency":"EUR","transport_method":"airplane","origin":"Munich (MUC)","destination":"London Heathrow (LHR)","departure":"2026-03-15T08:30:00","arrival":"2026-03-15T10:00:00","duration":"2h 30m","stops":0,"carriers":["Lufthansa"]},{"price":"245.50","currency":"EUR","transport_method":"airplane","origin":"Munich (MUC)","destination":"London Gatwick (LGW)","departure":"2026-03-15T14:15:00","arrival":"2026-03-15T17:45:00","duration":"4h 30m","stops":1,"carriers":["British Airways","Eurowings"]}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"processing","props":{"query":"Munich -> London, 2026-03-15","provider":"Google Flights","status":"processing","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"providers":[{"id":"google_flights","name":"Google Flights","icon_url":"https://www.google.com/favicon.ico"}],"legs":[{"origin":"Berlin","destination":"Paris","date":"2026-04-01"}]}},{"name":"empty","props":{"query":"Munich -> London, 2026-03-15","provider":"Google Flights","status":"finished","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"providers":[{"id":"google_flights","name":"Google Flights","icon_url":"https://www.google.com/favicon.ico"}],"legs":[{"origin":"Hamburg","destination":"Vienna","date":"2026-04-03"}],"result_count":0}},{"name":"error","props":{"query":"Invalid -> Route","provider":"Google","status":"error","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"errorMessage":"No connections found for the selected route."}}],
    "travel/TravelConnectionEmbedFullscreen.svelte":[{"name":"multiLeg","props":{"data":{"decodedContent":{"embed_id":"preview-connection-detail-multi","type":"connection","transport_method":"airplane","trip_type":"one_way","total_price":"245.50","currency":"EUR","bookable_seats":2,"origin":"Munich (MUC)","destination":"London Gatwick (LGW)","departure":"2026-03-15T14:15:00","arrival":"2026-03-15T17:45:00","duration":"4h 30m","stops":1,"carriers":["British Airways","Eurowings"],"carrier_codes":["BA","EW"],"legs":[{"leg_index":0,"origin":"Munich (MUC)","destination":"London Gatwick (LGW)","departure":"2026-03-15T14:15:00","arrival":"2026-03-15T17:45:00","duration":"4h 30m","stops":1,"segments":[{"carrier":"Eurowings","carrier_code":"EW","number":"EW 9542","departure_station":"Munich Airport (MUC)","departure_time":"2026-03-15T14:15:00","arrival_station":"Düsseldorf Airport (DUS)","arrival_time":"2026-03-15T15:30:00","duration":"1h 15m","airplane":"Airbus A319"},{"carrier":"British Airways","carrier_code":"BA","number":"BA 2617","departure_station":"Düsseldorf Airport (DUS)","departure_time":"2026-03-15T16:30:00","arrival_station":"London Gatwick (LGW)","arrival_time":"2026-03-15T17:45:00","duration":"1h 15m","airplane":"Airbus A320"}],"layovers":[{"airport":"Düsseldorf Airport","airport_code":"DUS","duration":"1h 00m","duration_minutes":60}]}]},"embedData":{"status":"finished"},"attrs":{"app_id":"travel"}}}}],
    "travel/TravelStaysEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"query":"Hotels in Barcelona, Mar 15-18","provider":"Google","status":"finished","results":[{"name":"Hotel Arts Barcelona","hotel_class":5,"overall_rating":4.7,"reviews":4521,"currency":"EUR","rate_per_night":"320","amenities":["Pool","Spa","Beach access","Fine dining"]},{"name":"Casa Camper Barcelona","hotel_class":4,"overall_rating":4.4,"reviews":1832,"currency":"EUR","rate_per_night":"185","amenities":["Free Wi-Fi","Rooftop terrace","Free snacks"]},{"name":"Generator Barcelona","hotel_class":2,"overall_rating":4,"reviews":3200,"currency":"EUR","rate_per_night":"55","amenities":["Free Wi-Fi","Bar","Shared kitchen"]}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"processing","props":{"query":"Hotels in Paris, Apr 1-5","provider":"Google","status":"processing","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"error","props":{"query":"Hotels in Invalid City","provider":"Google","status":"error","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"errorMessage":"Could not find stays for the specified location."}}],
    "travel/TravelStayEmbedFullscreen.svelte":[{"name":"budget","props":{"data":{"decodedContent":{"type":"stay","name":"City Hostel Central","description":"A modern hostel in a prime location with shared and private room options.","property_type":"Hostel","hotel_class":2,"overall_rating":3.8,"reviews":523,"rate_per_night":"€45","extracted_rate_per_night":45,"total_rate":"€135","extracted_total_rate":135,"currency":"EUR","amenities":["Free Wi-Fi","Shared kitchen","Luggage storage"],"thumbnail":"","eco_certified":false,"free_cancellation":false},"embedData":{"status":"finished"},"attrs":{"app_id":"travel"}}}},{"name":"luxury","props":{"data":{"decodedContent":{"type":"stay","name":"The Ritz-Carlton Berlin","description":"Experience unparalleled luxury at The Ritz-Carlton Berlin, featuring world-class dining, a stunning rooftop spa, and impeccable service in the heart of Potsdamer Platz.","property_type":"Hotel","hotel_class":5,"overall_rating":4.8,"reviews":3456,"rate_per_night":"€450","extracted_rate_per_night":450,"total_rate":"€1350","extracted_total_rate":1350,"currency":"EUR","amenities":["Free Wi-Fi","Spa","Pool","Concierge","Michelin restaurant","Valet parking","Butler service"],"thumbnail":"","eco_certified":true,"free_cancellation":true},"embedData":{"status":"finished"},"attrs":{"app_id":"travel"}}}}],
    "travel/TravelPriceCalendarEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"query":"Munich -> Barcelona, March 2026","status":"finished","results":[{"type":"price_calendar","origin":"MUC","origin_name":"Munich","destination":"BCN","destination_name":"Barcelona","month":"2026-03","currency":"EUR","cheapest_price":62,"most_expensive_price":155,"days_with_data":12,"entries":[{"date":"2026-03-01","price":89},{"date":"2026-03-02","price":95},{"date":"2026-03-05","price":72},{"date":"2026-03-08","price":110},{"date":"2026-03-10","price":65},{"date":"2026-03-12","price":78},{"date":"2026-03-15","price":145},{"date":"2026-03-18","price":62},{"date":"2026-03-20","price":99},{"date":"2026-03-22","price":68},{"date":"2026-03-25","price":120},{"date":"2026-03-28","price":155}]}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"processing","props":{"query":"Berlin -> Rome, April 2026","status":"processing","results":[{"type":"price_calendar","origin":"MUC","origin_name":"Munich","destination":"BCN","destination_name":"Barcelona","month":"2026-03","currency":"EUR","cheapest_price":62,"most_expensive_price":155,"days_with_data":12,"entries":[{"date":"2026-03-01","price":89},{"date":"2026-03-02","price":95},{"date":"2026-03-05","price":72},{"date":"2026-03-08","price":110},{"date":"2026-03-10","price":65},{"date":"2026-03-12","price":78},{"date":"2026-03-15","price":145},{"date":"2026-03-18","price":62},{"date":"2026-03-20","price":99},{"date":"2026-03-22","price":68},{"date":"2026-03-25","price":120},{"date":"2026-03-28","price":155}]}],"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"error","props":{"query":"Invalid route","status":"error","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"errorMessage":"Could not retrieve price calendar for the selected route."}}],
    "travel/TravelFlightDetailsEmbedFullscreen.svelte":[],
    "videos/VideosSearchEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"query":"svelte 5 tutorial","provider":"Brave Search","results":[{"title":"Svelte 5 Runes — Complete Beginner Guide","url":"https://www.youtube.com/watch?v=example1","thumbnail":"","channelName":"Svelte Society","duration":"17:08","viewCount":245000},{"title":"Migrating from Svelte 4 to 5 — Step by Step","url":"https://www.youtube.com/watch?v=example2","thumbnail":"","channelName":"Frontend Masters","duration":"32:15","viewCount":128000},{"title":"Building a Full App with SvelteKit 2","url":"https://www.youtube.com/watch?v=example3","thumbnail":"","channelName":"Fireship","duration":"12:42","viewCount":890000}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"noResults","props":{"query":"extremely obscure search","provider":"Brave Search","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "videos/VideoEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"Understanding Svelte 5 Runes — Complete Tutorial","videoId":"dQw4w9WgXcQ","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"withMetadata","props":{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"Understanding Svelte 5 Runes — Complete Tutorial","videoId":"dQw4w9WgXcQ","hasPreviousEmbed":false,"hasNextEmbed":false,"metadata":{"videoId":"dQw4w9WgXcQ","title":"Understanding Svelte 5 Runes — Complete Tutorial","channelName":"Svelte Society","channelId":"UC_abc123","thumbnailUrl":"","duration":{"totalSeconds":1028,"formatted":"17:08"},"viewCount":245000,"likeCount":12400,"publishedAt":"2025-11-15T10:00:00Z"}}},{"name":"minimal","props":{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"Understanding Svelte 5 Runes — Complete Tutorial","videoId":"dQw4w9WgXcQ","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "videos/VideoTranscriptEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"results":[{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","title":"Understanding Svelte 5 Runes","transcript":"Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system that replaces the old reactive declarations.\n\nThe $state rune replaces let declarations for reactive variables. When you declare a variable with $state, Svelte automatically tracks all assignments to it.\n\nThe $derived rune replaces $: for computed values. It takes an expression and re-evaluates it whenever its dependencies change.\n\nAnd the $effect rune replaces $: for side effects. It runs whenever any of its reactive dependencies change, similar to useEffect in React.","channelName":"Svelte Society","durationFormatted":"17:08"}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"empty","props":{"results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "videos/VideoGenerateEmbedFullscreen.svelte":[],
    "videos/VideoCreateEmbedFullscreen.svelte":[{"name":"dataViz","props":{"data":{"decodedContent":{"filename":"DataViz.tsx","status":"finished","remotion_source":"import { Sequence, AbsoluteFill } from \"remotion\";\n\nexport const DataViz: React.FC = () => {\n  return (\n    <AbsoluteFill>\n      <Sequence from={0} durationInFrames={270}>\n        <DarkBackground />\n      </Sequence>\n      <Sequence from={0} durationInFrames={210}>\n        <ChartTitle />\n      </Sequence>\n      <Sequence from={30} durationInFrames={180}>\n        <BarChart />\n      </Sequence>\n      <Sequence from={120} durationInFrames={90}>\n        <GrowthLabel />\n      </Sequence>\n      <Sequence from={210} durationInFrames={60}>\n        <OutroCard />\n      </Sequence>\n    </AbsoluteFill>\n  );\n};\n\nexport const Root = () => (\n  <Composition\n    id=\"data-viz\"\n    component={DataViz}\n    durationInFrames={270}\n    fps={30}\n    width={1920}\n    height={1080}\n  />\n);","current_source_version":1,"active_render_version":1},"embedData":{"status":"finished"},"attrs":{"app_id":"videos"}},"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"withNavigation","props":{"data":{"decodedContent":{"filename":"ProductLaunch.tsx","status":"finished","remotion_source":"import { Sequence, AbsoluteFill, Audio } from \"remotion\";\n\nexport const ProductLaunch: React.FC = () => {\n  return (\n    <AbsoluteFill>\n      <Sequence from={0} durationInFrames={240}>\n        <GradientBg />\n      </Sequence>\n      <Sequence from={0} durationInFrames={60}>\n        <TitleCard text=\"Introducing OpenMates\" />\n      </Sequence>\n      <Sequence from={60} durationInFrames={60}>\n        <FeatureList />\n      </Sequence>\n      <Sequence from={120} durationInFrames={60}>\n        <ClientEncryptionDemo />\n      </Sequence>\n      <Sequence from={180} durationInFrames={60}>\n        <CallToAction />\n      </Sequence>\n      <Audio src=\"/static/music/background.mp3\" />\n    </AbsoluteFill>\n  );\n};\n\nexport const Root = () => (\n  <Composition\n    id=\"product-launch\"\n    component={ProductLaunch}\n    durationInFrames={240}\n    fps={30}\n    width={1920}\n    height={1080}\n  />\n);","current_source_version":1,"active_render_version":1,"render_metadata":{"runtime_seconds":12,"charged_credits":0}},"embedData":{"status":"finished"},"attrs":{"app_id":"videos"}},"hasPreviousEmbed":true,"hasNextEmbed":true}}],
    "weather/WeatherForecastEmbedFullscreen.svelte":[],
    "weather/WeatherDayEmbedFullscreen.svelte":[],
    "weather/WeatherRainRadarEmbedFullscreen.svelte":[],
    "web/WebSearchEmbedFullscreen.svelte":[{"name":"processing","props":{"query":"searching...","provider":"Brave Search","status":"processing","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"withNavigation","props":{"query":"best restaurants in Berlin","provider":"Brave Search","status":"finished","results":[{"title":"Top 10 Restaurants in Berlin - Local Guide","url":"https://www.visitberlin.de/en/restaurants","description":"Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors.","favicon":""},{"title":"Berlin Food Scene: A Complete Guide","url":"https://www.timeout.com/berlin/restaurants","description":"From street food to Michelin-starred restaurants, explore what makes Berlin one of Europe's top food destinations.","favicon":""},{"title":"Where to Eat in Berlin - Travel Blog","url":"https://www.lonelyplanet.com/germany/berlin/restaurants","description":"A curated list of must-visit restaurants, cafes, and food markets in Berlin. Includes budget-friendly options.","favicon":""},{"title":"Berlin Restaurant Guide 2026","url":"https://www.thrillist.com/eat/berlin","description":"The most up-to-date guide to dining in Berlin with new openings and seasonal highlights.","favicon":""}],"hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"error","props":{"query":"failed search","provider":"Brave Search","status":"error","results":[],"hasPreviousEmbed":false,"hasNextEmbed":false,"errorMessage":"Search provider returned an error. Please try again."}}],
    "web/WebReadEmbedFullscreen.svelte":[{"name":"withNavigation","props":{"results":[{"url":"https://svelte.dev/blog/svelte-5-migration-guide","title":"Complete Guide to Migrating from Svelte 4 to Svelte 5","content":"Svelte 5 introduces runes, a powerful new reactivity system that replaces the $: reactive statements. This guide walks you through every step of the migration process.\n\n## Step 1: Update Dependencies\n\nFirst, update your package.json to use Svelte 5.\n\n## Step 2: Replace Reactive Declarations\n\nReplace all `$:` statements with `$derived()` or `$effect()` runes.\n\n## Step 3: Update Component Props\n\nUse `$props()` instead of `export let` for component properties.","favicon":""}],"url":"https://svelte.dev/blog/svelte-5-migration-guide","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"processing","props":{"results":[],"url":"https://svelte.dev/blog/loading","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "workflows/WorkflowCreateEmbedFullscreen.svelte":[],
    "workflows/WorkflowEmbedFullscreen.svelte":[],
    "workflows/WorkflowSearchEmbedFullscreen.svelte":[],
    "sheets/SheetEmbedFullscreen.svelte":[{"name":"salesReport","props":{"data":{"decodedContent":{"title":"Sales Report Q4 2025","table":"| Region | Product | Q1 | Q2 | Q3 | Q4 | Total | Growth |\n|--------|---------|----|----|----|----|-------|--------|\n| North | Widget A | $12,400 | $15,800 | $18,200 | $21,500 | $67,900 | +14% |\n| North | Widget B | $8,900 | $9,400 | $11,200 | $13,600 | $43,100 | +18% |\n| South | Widget A | $9,200 | $10,500 | $12,800 | $15,400 | $47,900 | +22% |\n| South | Widget B | $6,700 | $7,200 | $8,900 | $10,100 | $32,900 | +12% |\n| East | Widget A | $14,200 | $16,700 | $19,400 | $23,100 | $73,400 | +8% |\n| East | Widget B | $10,400 | $11,800 | $13,200 | $15,900 | $51,300 | +16% |\n| West | Widget A | $11,600 | $13,200 | $15,700 | $18,900 | $59,400 | +20% |\n| West | Widget B | $7,800 | $8,600 | $10,200 | $12,400 | $39,000 | +11% |\n| Central | Widget A | $10,800 | $12,400 | $14,600 | $17,200 | $55,000 | +17% |\n| Central | Widget B | $5,900 | $6,700 | $8,100 | $9,800 | $30,500 | +15% |","row_count":10,"col_count":8},"attrs":{"type":"sheets-sheet"}},"embedId":"preview-sheet-fullscreen-1","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"inventory","props":{"data":{"decodedContent":{"title":"Inventory Status","table":"| SKU | Product Name | Category | Stock | Unit Price | Reorder Point | Supplier | Last Updated |\n|-----|-------------|----------|-------|------------|---------------|----------|--------------|\n| A001 | Wireless Bluetooth Headphones | Electronics | 245 | $89.99 | 50 | TechSupply Co | 2025-03-01 |\n| A002 | USB-C Charging Cable (2m) | Accessories | 1203 | $12.99 | 200 | CableWorld | 2025-03-10 |\n| A003 | Mechanical Keyboard | Electronics | 87 | $149.00 | 30 | KeyCraft | 2025-02-28 |\n| A004 | Laptop Stand | Accessories | 412 | $45.00 | 100 | DeskPro | 2025-03-05 |\n| A005 | Noise Cancelling Earbuds | Electronics | 156 | $199.00 | 40 | TechSupply Co | 2025-03-12 |\n| A006 | HDMI Cable (1m) | Accessories | 890 | $8.99 | 300 | CableWorld | 2025-03-08 |\n| A007 | Ergonomic Mouse | Electronics | 334 | $59.99 | 80 | KeyCraft | 2025-03-03 |","row_count":7,"col_count":8},"attrs":{"type":"sheets-sheet"}},"embedId":"preview-sheet-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"glossary","props":{"data":{"decodedContent":{"title":"Technical Glossary","table":"| Term | Definition |\n|------|-----------|\n| API | Application Programming Interface — a contract that defines how software components communicate |\n| REST | Representational State Transfer — an architectural style for designing networked applications |\n| JWT | JSON Web Token — a compact, URL-safe means of representing claims to be transferred between parties |\n| OAuth | Open Authorization — an open standard for access delegation commonly used for token-based auth |\n| CORS | Cross-Origin Resource Sharing — a browser mechanism that controls cross-origin HTTP requests |\n| CDN | Content Delivery Network — a geographically distributed network of servers for fast content delivery |\n| SLA | Service Level Agreement — a commitment between a service provider and a client on service quality |","row_count":7,"col_count":2},"attrs":{"type":"sheets-sheet"}},"embedId":"preview-sheet-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}},{"name":"withNavigation","props":{"data":{"decodedContent":{"title":"Team Directory","table":"| Name | Role | Department | Start Date | Location | Salary |\n|------|------|------------|------------|----------|--------|\n| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 | Munich | €85,000 |\n| Bob Smith | Product Manager | Product | 2022-06-01 | Berlin | €92,000 |\n| Carol Williams | Lead Designer | Design | 2024-03-10 | Munich | €78,000 |\n| David Brown | DevOps Lead | Engineering | 2021-11-20 | Remote | €88,000 |\n| Eva Martinez | QA Engineer | Engineering | 2023-08-05 | Barcelona | €72,000 |\n| Frank Lee | Frontend Developer | Engineering | 2024-01-08 | Munich | €76,000 |\n| Grace Kim | Data Analyst | Analytics | 2023-05-22 | Berlin | €68,000 |\n| Henry Davis | Backend Developer | Engineering | 2022-09-15 | Munich | €82,000 |","row_count":8,"col_count":6},"attrs":{"type":"sheets-sheet"}},"embedId":"preview-sheet-fullscreen-1","hasPreviousEmbed":true,"hasNextEmbed":true}},{"name":"minimal","props":{"data":{"decodedContent":{"title":"","table":"| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |","row_count":1,"col_count":3},"attrs":{"type":"sheets-sheet"}},"embedId":"preview-sheet-fullscreen-1","hasPreviousEmbed":false,"hasNextEmbed":false}}],
    "focus_mode/FocusModeActivationEmbedFullscreen.svelte":[]
    }}
    """#

    static func isolatedEmbedSkill(variant: String) -> DevEmbedPreviewSkill {
        switch variant {
        case "news-search": return newsSearch
        case "sheet", "sheet-large": return sheet
        case "sheet-wide": return sheetWide
        case "search-long":
            let source = webSearch
            var data = source.primaryEmbed.rawData ?? [:]
            data["query"] = AnyCodable("best restaurants in Berlin with vegetarian options and outdoor seating near Museum Island")
            let parent = record(id: source.primaryEmbed.id, type: source.primaryEmbed.type, appId: "web", skillId: "search", data: data.mapValues(\.value))
            return skill(id: source.id, label: source.label, primary: parent, children: source.childEmbeds)
        case "search-overflow", "images-search-overflow":
            let isImages = variant == "images-search-overflow"
            let appId = isImages ? "images" : "web"
            let parentID = "preview-\(variant)"
            let children = (1...10).map { index in
                let imageURL = "https://app.dev.openmates.org/images/examples/group1.jpg?search-preview=\(index)"
                return record(id: "\(parentID)-\(index)",
                              type: isImages ? EmbedType.imagesImageResult.rawValue : EmbedType.webWebsite.rawValue,
                              appId: appId,
                              data: ["url": "https://example.org/result-\(index)", "title": "Search result \(index)",
                                     "description": "Synthetic overflow reference", "preview_image_url": imageURL,
                                     "thumbnail_url": imageURL, "image_url": imageURL], parentEmbedId: parentID)
            }
            let parent = appSkill(id: parentID,
                                  type: isImages ? EmbedType.imagesSearch.rawValue : EmbedType.webSearch.rawValue,
                                  appId: appId, skillId: "search",
                                  data: ["query": "Leading search query with ten thumbnails", "provider": "Brave Search",
                                         "result_count": children.count], embedIds: children.map(\.id).joined(separator: "|"))
            return skill(id: variant, label: "Search", primary: parent, children: children)
        case "event-image":
            let source = event.primaryEmbed
            var data = source.rawData ?? [:]
            data["title"] = AnyCodable("Online Poetry Club")
            data["event_type"] = AnyCodable("ONLINE")
            data["image_url"] = AnyCodable("https://app.dev.openmates.org/images/examples/group1.jpg")
            data.removeValue(forKey: "venue")
            let parent = record(id: "preview-event-image", type: source.type, appId: "events",
                                skillId: "search", data: data.mapValues(\.value))
            return skill(id: variant, label: "Event", primary: parent)
        case "search-thumbnail":
            let parent = appSkill(id: "preview-search-thumbnail", type: EmbedType.webSearch.rawValue, appId: "web", skillId: "search",
                                  data: ["query": "best restaurants in Berlin", "provider": "Brave Search", "result_count": 1], embedIds: "preview-search-thumbnail-child")
            let child = record(id: "preview-search-thumbnail-child", type: EmbedType.webWebsite.rawValue, appId: "web",
                               data: ["url": "https://example.org", "title": "Synthetic preview", "description": "Synthetic thumbnail reference",
                                      "preview_image_url": "https://app.dev.openmates.org/favicon.svg"], parentEmbedId: parent.id)
            return skill(id: "search-thumbnail", label: "Search", primary: parent, children: [child])
        default: return webSearch
        }
    }

    static var isolatedSearchGroup: [EmbedRecord] {
        (1...3).map { index in
            appSkill(id: "preview-search-group-\(index)", type: EmbedType.webSearch.rawValue, appId: "web", skillId: "search",
                     data: ["query": "Berlin restaurant search \(index)", "provider": "Brave Search", "result_count": 3])
        }
    }
    /// The generated web registry contains 88 keys. `wiki` and
    /// `diagrams-mermaid` remain native-only legacy types and are excluded.
    static var registryKeys: [String] {
        EmbedType.allCases
            .filter { $0 != .wiki && $0 != .diagramsMermaid }
            .map(\.rawValue)
            .sorted()
    }

    static func skill(forRegistryKey registryKey: String) -> DevEmbedPreviewSkill? {
        if registryKey == EmbedType.travelStay.rawValue { return travelStayFullscreen }
        if registryKey == EmbedType.mapsPlace.rawValue { return mapsPlacePreview }
        if registryKey == EmbedType.fileFile.rawValue {
            let embed = record(id: "preview-file-processing", type: EmbedType.fileFile.rawValue,
                               status: .processing, appId: "file", skillId: "file", data: [:])
            return skill(id: "file-file-processing", label: "File", primary: embed)
        }
        if registryKey == EmbedType.webWebsite.rawValue {
            if ProcessInfo.processInfo.arguments.contains("--dev-website-loaded-preview") {
                return websiteImageVariant(
                    imageURL: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
                    id: "preview-website-loaded")
            }
            if ProcessInfo.processInfo.arguments.contains("--dev-website-failed-preview") {
                return websiteImageVariant(
                    imageURL: "https://app.dev.openmates.org/images/examples/does-not-exist.jpg",
                    id: "preview-website-failed")
            }
        }
        if ProcessInfo.processInfo.arguments.contains("--dev-audio-finished-preview") {
            switch EmbedType(rawValue: registryKey) {
            case .audioGenerate: return audioGenerateFinished
            case .audioSpeak: return audioSpeakFinished
            default: break
            }
        }
        let allSkills = DevEmbedPreviewApp.allCases.flatMap { skills(for: $0) }
        if let exact = allSkills.first(where: { $0.primaryEmbed.type == registryKey }) {
            return exact
        }
        switch EmbedType(rawValue: registryKey) {
        case .imagesGenerateDraft:
            return allSkills.first { $0.primaryEmbed.type == EmbedType.imagesGenerate.rawValue }
        case .focusModeActivation:
            return focusModeActivation
        default:
            return nil
        }
    }

    static func fullscreenSkill(forRegistryKey registryKey: String) -> DevEmbedPreviewSkill? {
        if registryKey == EmbedType.mapsPlace.rawValue { return mapsPlaceFullscreen }
        if registryKey == EmbedType.fileFile.rawValue { return fileArtifact }
        if registryKey == EmbedType.codeCode.rawValue { return codeFullscreen }
        if registryKey == EmbedType.sheetsSheet.rawValue { return sheetFullscreen }
        if registryKey == EmbedType.healthSearch.rawValue { return healthSearchFullscreen }
        if registryKey == EmbedType.healthAppointment.rawValue { return healthAppointmentFullscreen }
        if registryKey == EmbedType.fitnessClass.rawValue { return fitnessClassFullscreen }
        if registryKey == EmbedType.fitnessLocation.rawValue { return fitnessLocationFullscreen }
        if registryKey == EmbedType.electronicsSearch.rawValue { return electronicsSearchFullscreen }
        if registryKey == EmbedType.electronicsComponent.rawValue { return electronicsComponentFullscreen }
        if registryKey == EmbedType.homeSearch.rawValue { return homeSearchFullscreen }
        if registryKey == EmbedType.nutritionSearch.rawValue { return nutritionSearchFullscreen }
        if registryKey == EmbedType.nutritionRecipe.rawValue { return nutritionRecipeFullscreen }
        if registryKey == EmbedType.shoppingSearch.rawValue { return shoppingSearchFullscreen }
        if registryKey == EmbedType.shoppingProduct.rawValue { return shoppingProductFullscreen }
        if registryKey == EmbedType.mailSearch.rawValue { return mailSearchFullscreen }
        if registryKey == EmbedType.mapsSearch.rawValue { return mapsSearchFullscreen }
        if registryKey == EmbedType.tasksCreate.rawValue { return tasksCreateFullscreen }
        if registryKey == EmbedType.tasksSearch.rawValue { return tasksSearchFullscreen }
        if registryKey == EmbedType.workflowsCreateOrModify.rawValue { return workflowsCreateFullscreen }
        if registryKey == EmbedType.workflowsSearch.rawValue { return workflowsSearchFullscreen }
        if registryKey == EmbedType.webRead.rawValue { return webReadFullscreen }
        if registryKey == EmbedType.videosTranscript.rawValue { return videoTranscriptFullscreen }
        if registryKey == EmbedType.videosCreate.rawValue { return videoCreateFullscreen }
        if registryKey == EmbedType.mathCalculate.rawValue {
            let embed = appSkill(id: "preview-math-calculate-fullscreen-1", type: EmbedType.mathCalculate.rawValue,
                                 appId: "math", skillId: "calculate", data: [
                "query": "sin(pi/4) + cos(pi/3)", "subtitle": "Numeric mode",
                "results": [
                    ["expression": "sin(pi/4) + cos(pi/3)", "result": "1.20710678118655", "result_type": "float", "mode": "numeric"],
                    ["expression": "diff(x^3, x)", "result": "3*x**2", "result_type": "symbolic", "mode": "diff"]
                ]
            ])
            return skill(id: "math-calculate-fullscreen", label: "Calculate", primary: embed)
        }
        if registryKey == EmbedType.mathPlot.rawValue {
            let embed = record(id: "preview-math-plot-fullscreen-1", type: EmbedType.mathPlot.rawValue,
                               appId: "math", data: [
                "title": "Trigonometric Functions",
                "plot_spec": "f(x) = sin(x)\nf(x) = cos(x)\nf(x) = tan(x)"
            ])
            return skill(id: "math-plot-fullscreen", label: "Plot", primary: embed)
        }
        if registryKey == EmbedType.electronicsPcbSchematic.rawValue {
            let embed = record(id: "preview-electronics-pcb-fullscreen-1",
                               type: EmbedType.electronicsPcbSchematic.rawValue,
                               appId: "electronics", data: ["filename": "board.ato", "language": "atopile"])
            return skill(id: "electronics-pcb-fullscreen", label: "PCB Schematic", primary: embed)
        }
        if registryKey == EmbedType.mindmapsMindmap.rawValue {
            let nodes: [[String: Any]] = [
                ["id": "launch", "label": "Launch Plan", "description": "Coordinate launch workstreams", "children": ["research", "build", "ship"]],
                ["id": "research", "label": "Audience Research", "children": ["interviews", "survey"]],
                ["id": "interviews", "label": "Customer Interviews"],
                ["id": "survey", "label": "Survey"],
                ["id": "build", "label": "Build", "children": ["copy", "landing"]],
                ["id": "copy", "label": "Messaging"],
                ["id": "landing", "label": "Landing Page"],
                ["id": "ship", "label": "Ship", "children": ["announcement", "followup"]],
                ["id": "announcement", "label": "Announcement"],
                ["id": "followup", "label": "Follow-up"]
            ]
            let model: [String: Any] = [
                "openmatesType": "mindmap", "schemaVersion": 1, "title": "Launch Plan", "rootId": "launch",
                "nodes": nodes,
                "edges": [["source": "research", "target": "copy", "type": "dependency"]],
                "view": ["layout": "radial-tree", "collapsedNodeIds": []]
            ]
            let source = (try? JSONSerialization.data(withJSONObject: model, options: [.sortedKeys]))
                .flatMap { String(data: $0, encoding: .utf8) } ?? ""
            let embed = record(id: "preview-mindmap-fullscreen-1", type: EmbedType.mindmapsMindmap.rawValue,
                               appId: "mindmaps", data: ["source_json": source, "title": "Launch Plan"])
            return skill(id: "mindmap-fullscreen", label: "Mind Map", primary: embed)
        }
        if registryKey == EmbedType.codeGetDocs.rawValue {
            let embed = appSkill(id: "preview-code-get-docs-fullscreen-1", type: EmbedType.codeGetDocs.rawValue,
                                 appId: "code", skillId: "get_docs", data: [
                "library": "svelte", "question": "How to use $state rune in Svelte 5?",
                "results": [["library": ["id": "/sveltejs/svelte", "title": "Svelte",
                                          "description": "Cybernetically enhanced web apps"],
                             "documentation": codeGetDocsFullscreenMarkdown,
                             "source": "context7", "word_count": 180]]
            ])
            return skill(id: "code-get-docs-fullscreen", label: "Get Docs", primary: embed)
        }
        if registryKey == EmbedType.eventsEvent.rawValue {
            let embed = eventRecord(
                id: "preview-event-fullscreen-1",
                title: "AI & Machine Learning Berlin Meetup – Spring Edition",
                dateStart: "2026-03-15T19:00:00+01:00", dateEnd: "2026-03-15T22:00:00+01:00",
                eventType: "PHYSICAL", city: "Berlin", country: "Germany",
                rsvpCount: 142, isPaid: false, feeAmount: nil, imageURL: nil,
                venueName: "Factory Berlin", venueAddress: "Rheinsberger Str. 76-77",
                venueLatitude: 52.5393, venueLongitude: 13.4028, parentId: nil,
                description: "Join us for an evening of talks on large language models, RAG architectures, and deploying AI to production. Speakers from leading Berlin AI companies.\n\nSchedule:\n- 18:30 Doors open\n- 19:00 Talk 1: LLMs in Production\n- 19:45 Talk 2: RAG Architectures\n- 20:30 Networking\n\nThis is a beginner-friendly event — no prior ML experience required. Light refreshments will be provided."
            )
            return skill(id: "events-event-fullscreen", label: "Event", primary: embed)
        }
        if registryKey == EmbedType.pdf.rawValue {
            let embed = record(id: "preview-pdf-fullscreen-1", type: EmbedType.pdf.rawValue,
                               appId: "pdf", data: ["filename": "Q4-2025-Annual-Report.pdf"])
            return skill(id: "pdf-fullscreen", label: "PDF", primary: embed)
        }
        if registryKey == EmbedType.image.rawValue {
            let original: [String: Any] = [
                "s3_key": "ui-test/original-image",
                "aes_nonce": String(repeating: "0", count: 24),
                "format": "jpg"
            ]
            var imageData: [String: Any] = [
                "filename": "golden-gate-sunset.jpg",
                "file_size": 2_411_520,
                "file_type": "image/jpeg"
            ]
            if ProcessInfo.processInfo.arguments.contains("--dev-image-original-header") {
                imageData["aes_key"] = String(repeating: "0", count: 64)
                imageData["files"] = ["original": original]
            }
            let embed = record(id: "preview-image-embed-fullscreen-1", type: EmbedType.image.rawValue,
                               appId: "images", data: imageData)
            return skill(id: "image-fullscreen", label: "Image", primary: embed)
        }
        if registryKey == EmbedType.videosVideo.rawValue {
            let embed = record(id: "preview-videos-video-fullscreen-1",
                               type: EmbedType.videosVideo.rawValue, appId: "videos", data: [
                                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                                "video_id": "dQw4w9WgXcQ",
                                "title": "Understanding Svelte 5 Runes — Complete Tutorial"
                               ])
            return skill(id: "videos-video-fullscreen", label: "Video", primary: embed)
        }
        if registryKey == EmbedType.recording.rawValue {
            let embed = record(id: "preview-audio-1", type: EmbedType.recording.rawValue, appId: "audio", data: [
                "filename": "voice-memo-2026-03-10.webm", "duration": "0:42", "duration_seconds": 42,
                "model": "voxtral-mini-2602",
                "transcript": "This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week. Key highlights include the completion of the authentication refactor and the new API rate limiting feature."
            ])
            return skill(id: "recording-fullscreen", label: "Recording", primary: embed)
        }
        if !ProcessInfo.processInfo.arguments.contains("--dev-audio-finished-preview") {
            switch EmbedType(rawValue: registryKey) {
            case .audioGenerate, .audioSpeak:
                let type = EmbedType(rawValue: registryKey) ?? .audioGenerate
                let embed = generatedAudioRecord(
                    id: "preview-audio-fullscreen-1", type: type,
                    skillId: "generate", prompt: "", mode: "sound_effect",
                    status: .finished, includePlayableMedia: false
                )
                return skill(id: "audio-fullscreen", label: "Generate SFX", primary: embed)
            default: break
            }
        }
        return skill(forRegistryKey: registryKey)
    }

    private static var focusModeActivation: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-focus-mode-activation",
            type: EmbedType.focusModeActivation.rawValue,
            appId: "jobs",
            data: [
                "focus_id": "jobs-career_insights",
                "focus_mode_name": "Career Insights",
                "already_active": true
            ]
        )
        return skill(id: "focus-mode-activation", label: "Career Insights", primary: embed)
    }

    static func skills(for app: DevEmbedPreviewApp) -> [DevEmbedPreviewSkill] {
        switch app {
        case .audio:
            return [audioGenerate, audioSpeak, recording]
        case .business:
            return [businessCompanyFinancials, businessFinancialResult]
        case .calendar:
            return [calendarListCalendars, calendarGetEvents, calendarCreateEvent, calendarUpdateEvent, calendarDeleteEvent]
        case .code:
            return [codeEmbed, codeNotebook, fileArtifact, codeRepoSearch, codeRepo, codeApplication, codeGetDocs]
        case .design:
            return [designSearchIcons, designIconResult]
        case .diagrams:
            return [diagramsMermaid]
        case .docs:
            return [docsDocument]
        case .electronics:
            return [electronicsPcbSchematic, electronicsSearch, electronicsComponent]
        case .fitness:
            return [fitnessSearchLocations, fitnessLocation, fitnessSearchClasses, fitnessClass]
        case .finance:
            return [financeCheckAccounts]
        case .health:
            return [healthAppointment, healthSearch]
        case .home:
            return [homeSearch, homeListing]
        case .hosting:
            return DevHostingEmbedFixtures.skills
        case .web:
            return [webSearch, webSearchYouTube, webRead, website]
        case .images:
            return [imageGenerate, imagesSearch, imageResult, imageUpload, imageView]
        case .mail:
            return [mail, mailSearch]
        case .maps:
            return [mapsSearch, mapsLocation]
        case .math:
            return [mathCalculate, mathPlot]
        case .mindmaps:
            return [mindmapsMindmap]
        case .models3d:
            return [models3dSearch, models3dModelResult, models3dGenerate]
        case .music:
            return [musicGenerate]
        case .news:
            return [newsSearch]
        case .nutrition:
            return [nutritionSearch, nutritionRecipe]
        case .pdf:
            return [pdf]
        case .reminder:
            return [reminderSet, reminderList, reminderCancel]
        case .sheets:
            return [sheet]
        case .shopping:
            return [shoppingSearch, shoppingProduct]
        case .socialMedia:
            return [socialMediaGetPosts, socialMediaSearch, socialMediaPost]
        case .tasks:
            return [tasksCreate, tasksSearch, tasksTask]
        case .travel:
            return [travelSearch, travelConnection, travelPriceCalendar, travelFlight, travelStay, travelStays]
        case .videos:
            return [videosSearch, video, videoTranscript, videoGenerate, videoCreate]
        case .weather:
            return [weatherForecast, weatherDay, weatherRainRadar]
        case .events:
            return [eventsSearch, event]
        case .workflows:
            return [workflowsCreate, workflowsSearch, workflowsWorkflow]
        }
    }

    // MARK: - Code

    private static var codeEmbed: DevEmbedPreviewSkill {
        let hydratedIndexRegression = ProcessInfo.processInfo.arguments.contains("--dev-code-hydrated-index")
        let embed = record(
            id: "preview-code-1",
            type: EmbedType.codeCode.rawValue,
            appId: "code",
            skillId: "code",
            data: [
                "type": "code",
                "app_id": "code",
                "skill_id": "code",
                "decodedContent": [
                    "language": hydratedIndexRegression ? "html" : "typescript",
                    "filename": hydratedIndexRegression ? "index.html" : "MyComponent.svelte",
                    "line_count": hydratedIndexRegression ? 8 : 14,
                    "code": hydratedIndexRegression ? """
                    <!doctype html>
                    <html lang="en">
                    <head><title>OpenMates preview</title></head>
                    <body>
                      <main><h1>Rendered index.html</h1></main>
                    </body>
                    </html>
                    """ : codePreviewSource
                ]
            ],
            versionNumber: hydratedIndexRegression ? 3 : nil,
            versionHistory: hydratedIndexRegression ? [
                EmbedVersionMetadata(versionNumber: 1, createdAt: 1760000000, hasSnapshot: true, hasPatch: false, contentHash: "preview-code-v1"),
                EmbedVersionMetadata(versionNumber: 2, createdAt: 1760000100, hasSnapshot: false, hasPatch: true, contentHash: "preview-code-v2"),
                EmbedVersionMetadata(versionNumber: 3, createdAt: 1760000200, hasSnapshot: false, hasPatch: true, contentHash: "preview-code-v3")
            ] : [],
            versionHistoryReadonly: false
        )
        return skill(id: "code-code", label: "Code", primary: embed)
    }

    private static let codePreviewSource = """
    import { onMount } from 'svelte';

    interface Props {
      title: string;
      count?: number;
    }

    let { title, count = 0 }: Props = $props();
    let isLoading = $state(false);
    let displayTitle = $derived(title.toUpperCase());

    onMount(() => {
      console.log('Component mounted');
    });
    """

    private static let codeFullscreenSource = """
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';

    interface Props {
      title: string;
      items: string[];
      onSelect?: (item: string) => void;
    }

    let { title, items, onSelect }: Props = $props();

    let searchQuery = $state('');
    let isExpanded = $state(false);

    let filteredItems = $derived(
      items.filter(item =>
        item.toLowerCase().includes(searchQuery.toLowerCase())
      )
    );

    onMount(() => {
      if (browser) {
        console.log('Component mounted in browser');
      }
    });

    function handleSelect(item: string) {
      onSelect?.(item);
      isExpanded = false;
    }
    """

    private static var codeFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-fullscreen-1", type: EmbedType.codeCode.rawValue,
                           appId: "code", skillId: "code", data: [
                            "decodedContent": [
                                "code": codeFullscreenSource, "language": "typescript",
                                "filename": "SearchableList.svelte", "line_count": 32
                            ]
                           ])
        return skill(id: "code-code-fullscreen", label: "Code", primary: embed)
    }

    private static var codeNotebook: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-notebook-1", type: EmbedType.codeNotebook.rawValue,
                           appId: "code", skillId: "notebook",
                           data: ["filename": "notebook.ipynb", "notebook": ["nbformat": 4, "cells": []]])
        return skill(id: "code-notebook", label: "Notebook", primary: embed)
    }

    private static var fileArtifact: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-file-file-1",
            type: EmbedType.fileFile.rawValue,
            appId: "file",
            skillId: "file",
            data: [
                "normalized_path": "artifacts/reports/berlin-weather.csv",
                "filename": "berlin-weather.csv",
                "mime_type": "text/csv",
                "size_bytes": 24_576,
                "download_url": "https://example.invalid/download/berlin-weather.csv",
                "download_expires_at": 1_893_456_000
            ]
        )
        return skill(id: "file-file", label: "File", primary: embed)
    }

    private static var codeGetDocs: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-code-get-docs-1",
            type: EmbedType.codeGetDocs.rawValue,
            appId: "code",
            skillId: "get_docs",
            data: [
                "library": "svelte",
                "question": "How to use $state rune in Svelte 5?",
                "results": [[
                    "library": ["id": "/sveltejs/svelte", "title": "Svelte",
                                "description": "Cybernetically enhanced web apps"],
                    "documentation": "The `$state` rune declares reactive state. When you assign to a `$state` variable, Svelte automatically updates all DOM nodes that depend on it.\n\n## Basic Usage\n\n```svelte\n<script>\nlet count = $state(0);\n</script>\n<button onclick={() => count++}>{count}</button>\n```",
                    "word_count": 48, "source": "context7"
                ]]
            ]
        )
        return skill(id: "code-get-docs", label: "Get Docs", primary: embed)
    }

    private static let codeGetDocsFullscreenMarkdown = #"""
    # $state — Svelte 5 Runes

    The `$state` rune declares reactive state. When you assign to a `$state` variable, Svelte automatically updates all DOM nodes that depend on it.

    ## Basic Usage

    ```svelte
    <script>
    let count = $state(0);
    </script>

    <button onclick={() => count++}>
      Clicks: {count}
    </button>
    ```

    ## Deep Reactivity

    `$state` provides deep reactivity for objects and arrays. Changes to nested properties are tracked automatically.

    ```svelte
    <script>
    let user = $state({ name: 'Alice', age: 30 });
    </script>

    <input bind:value={user.name} />
    <p>Name: {user.name}</p>
    ```

    ## With TypeScript

    ```ts
    let count = $state<number>(0);
    let items = $state<string[]>([]);
    ```

    ## Differences from Svelte 4

    In Svelte 4, reactive variables were declared at the top level of `<script>` and updated reactively. In Svelte 5, you explicitly mark state with `$state()` — this makes reactivity explicit and works inside functions, classes, and modules.

    | Svelte 4 | Svelte 5 |
    |----------|----------|
    | `let count = 0;` (top-level) | `let count = $state(0);` |
    | `$: doubled = count * 2;` | `let doubled = $derived(count * 2);` |
    | `onMount(() => ...)` | Same |

    ## Related

    - [`$derived`](https://svelte.dev/docs/svelte/$derived) — computed values
    - [`$effect`](https://svelte.dev/docs/svelte/$effect) — side effects
    - [`$props`](https://svelte.dev/docs/svelte/$props) — component props
    """#

    // MARK: - Web

    private static var webSearch: DevEmbedPreviewSkill {
        let children = [
            record(
                id: "preview-web-search-result-1",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.visitberlin.de/en/restaurants",
                    "title": "Top 10 Restaurants in Berlin - Local Guide",
                    "description": "Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors.",
                    "preview_image_url": ProcessInfo.processInfo.arguments.contains("--dev-web-search-loaded-preview")
                        ? "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200"
                        : "/images/examples/group1.jpg",
                    "age": "2026-07-25T00:00:00Z",
                    "page_age": "2026-07-25T00:00:00Z",
                    "language": "en",
                    "family_friendly": true
                ],
                parentEmbedId: "preview-web-search-1"
            ),
            record(
                id: "preview-web-search-result-2",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.timeout.com/berlin/restaurants",
                    "title": "Berlin Food Scene: A Complete Guide",
                    "description": "From street food to Michelin-starred restaurants, explore what makes Berlin one of Europe's top food destinations.",
                    "age": "2026-07-24T00:00:00Z",
                    "page_age": "2026-07-24T00:00:00Z",
                    "language": "en",
                    "family_friendly": true
                ],
                parentEmbedId: "preview-web-search-1"
            ),
            record(
                id: "preview-web-search-result-3",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.lonelyplanet.com/germany/berlin/restaurants",
                    "title": "Where to Eat in Berlin - Travel Blog",
                    "description": "A curated list of must-visit restaurants, cafes, and food markets in Berlin. Includes budget-friendly options.",
                    "age": "2026-07-23T00:00:00Z",
                    "page_age": "2026-07-23T00:00:00Z",
                    "language": "en",
                    "family_friendly": true
                ],
                parentEmbedId: "preview-web-search-1"
            )
        ]
        let parent = appSkill(
            id: "preview-web-search-1",
            type: EmbedType.webSearch.rawValue,
            appId: "web",
            skillId: "search",
            data: ["query": "best restaurants in Berlin", "provider": "Brave Search", "result_count": children.count],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "web-search", label: "Search", primary: parent, children: children)
    }

    private static var webSearchYouTube: DevEmbedPreviewSkill {
        let parentId = "preview-web-search-youtube-1"
        let child = record(
            id: "preview-web-search-youtube-result-1",
            type: EmbedType.webWebsite.rawValue,
            appId: "web",
            data: [
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "YouTube search result",
                "description": "A video result inside a web search.",
                "channel_name": "Video creator",
                "duration_formatted": "3:32"
            ],
            parentEmbedId: parentId
        )
        let parent = appSkill(
            id: parentId,
            type: EmbedType.webSearch.rawValue,
            appId: "web",
            skillId: "search",
            data: ["query": "video result", "provider": "Brave Search", "result_count": 1],
            embedIds: child.id
        )
        return skill(id: "web-search-youtube", label: "YouTube Search", primary: parent, children: [child])
    }

    private static var webRead: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-web-read-1",
            type: EmbedType.webRead.rawValue,
            appId: "web",
            skillId: "read",
            data: [
                "url": "https://svelte.dev/blog/svelte-5-migration-guide",
                "title": "Complete Guide to Migrating from Svelte 4 to Svelte 5",
                "provider": "Firecrawl",
                "results": [[
                    "url": "https://svelte.dev/blog/svelte-5-migration-guide",
                    "title": "Complete Guide to Migrating from Svelte 4 to Svelte 5",
                    "content": "Svelte 5 introduces runes, a powerful new reactivity system that replaces the $: reactive statements. This guide walks you through every step of the migration process, from updating your dependencies to converting your components.",
                    "favicon": ""
                ]]
            ]
        )
        return skill(id: "web-read", label: "Read", primary: embed)
    }

    private static var webReadFullscreen: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-web-read-fullscreen-1",
            type: EmbedType.webRead.rawValue, appId: "web", skillId: "read",
            data: [
                "url": "https://svelte.dev/blog/svelte-5-migration-guide",
                "title": "Complete Guide to Migrating from Svelte 4 to Svelte 5",
                "results": [] as [[String: Any]]
            ]
        )
        return skill(id: "web-read-fullscreen", label: "Read", primary: embed)
    }

    private static var website: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-website-1",
            type: EmbedType.webWebsite.rawValue,
            appId: "web",
            data: [
                "url": "https://svelte.dev",
                "title": "Svelte — Cybernetically enhanced web apps",
                "description": "Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.",
                "favicon_url": "https://svelte.dev/favicon.png"
            ]
        )
        return skill(id: "web-website", label: "Website", primary: embed)
    }

    private static func websiteImageVariant(imageURL: String, id: String) -> DevEmbedPreviewSkill {
        let embed = record(id: id, type: EmbedType.webWebsite.rawValue,
                           appId: "web", data: [
                            "url": "https://svelte.dev",
                            "title": "Svelte — Cybernetically enhanced web apps",
                            "description": "Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.",
                            "image_url": imageURL
                           ])
        return skill(id: id, label: "Website image", primary: embed)
    }

    // MARK: - Images

    private static var imageGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-image-gen-1",
            type: EmbedType.imagesGenerate.rawValue,
            appId: "images",
            skillId: "generate",
            data: [
                "prompt": "A serene mountain landscape at sunset with vibrant orange and purple skies",
                "model": "flux-schnell"
            ]
        )
        return skill(id: "images-generate", label: "Generate", primary: embed)
    }

    private static var imagesSearch: DevEmbedPreviewSkill {
        let results = imageSearchResults(parentId: "preview-images-search-1")
        let parent = appSkill(
            id: "preview-images-search-1",
            type: EmbedType.imagesSearch.rawValue,
            appId: "images",
            skillId: "search",
            data: ["query": "Golden Gate Bridge", "provider": "Brave"],
            embedIds: results.map(\.id).joined(separator: "|")
        )
        return skill(id: "images-search", label: "Search", primary: parent, children: results)
    }

    private static var imageResult: DevEmbedPreviewSkill {
        let embed = imageResultRecord(
            id: "preview-image-result-1",
            title: "Golden Gate Bridge at dusk",
            thumbnail: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
            image: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
            parentId: nil
        )
        return skill(id: "images-result", label: "Image Result", primary: embed)
    }

    private static var imageUpload: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-image-embed-1",
            type: EmbedType.image.rawValue,
            appId: "images",
            data: ["filename": "golden-gate-sunset.jpg"]
        )
        return skill(id: "images-upload", label: "Upload", primary: embed)
    }

    private static var imageView: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-image-view-1",
            type: "app:images:view",
            appId: "images",
            skillId: "view",
            data: ["filename": "golden-gate-sunset.jpg"]
        )
        return skill(id: "images-view", label: "View", primary: embed)
    }

    // MARK: - Travel

    /// Synthetic persisted parent shapes: no provider calls, account state or child cards.
    private static func travelZeroProvider(_ variant: String) -> DevEmbedPreviewSkill {
        var data: [String: Any] = ["result_count": 0, "providers": [], "results": []]
        switch variant {
        case "zero-provider-grouped":
            data["results"] = [["query": "Oslo to Bergen", "result_count": 0, "providers": [],
                "legs": [["origin": "Oslo", "destination": "Bergen", "date": "2026-10-08T09:00:00"]],
                "results": []]]
        case "zero-provider-query":
            data["query"] = "Night train from Berlin to Prague"
        default:
            data["query"] = "Find a train for Monday morning"
            data["legs_0_origin"] = "Berlin"
            data["legs_0_destination"] = "Prague"
            data["legs_0_date"] = "2026-10-05T09:00:00"
        }
        let parent = appSkill(id: "preview-travel-\(variant)", type: "app-skill-use",
                              appId: "travel", skillId: "search_connections", data: data)
        return skill(id: "travel-search-\(variant)", label: "Search connections", primary: parent)
    }

    private static var travelSearch: DevEmbedPreviewSkill {
        let children = [
            travelConnectionRecord(
                id: "preview-travel-search-result-1",
                price: "189.00",
                destination: "London Heathrow (LHR)",
                departure: "2026-03-15T08:30:00",
                arrival: "2026-03-15T10:00:00",
                duration: "2h 30m",
                stops: 0,
                carrierCodes: ["LH"],
                parentId: "preview-travel-search-1"
            ),
            travelConnectionRecord(
                id: "preview-travel-search-result-2",
                price: "245.50",
                destination: "London Gatwick (LGW)",
                departure: "2026-03-15T14:15:00",
                arrival: "2026-03-15T17:45:00",
                duration: "4h 30m",
                stops: 1,
                carrierCodes: ["BA", "EW"],
                parentId: "preview-travel-search-1"
            )
        ]
        let parent = appSkill(
            id: "preview-travel-search-1",
            type: EmbedType.travelConnections.rawValue,
            appId: "travel",
            skillId: "search_connections",
            data: ["query": "Munich -> London, 2026-03-15", "provider": "Google"],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "travel-search", label: "Search", primary: parent, children: children)
    }

    private static var travelConnection: DevEmbedPreviewSkill {
        let embed = travelConnectionRecord(
            id: "preview-travel-connection-1",
            price: "189.00",
            destination: "London Heathrow (LHR)",
            departure: "2026-03-15T08:30:00",
            arrival: "2026-03-15T10:00:00",
            duration: "2h 30m",
            stops: 0,
            carrierCodes: ["LH"],
            parentId: nil
        )
        return skill(id: "travel-connection", label: "Connection", primary: embed)
    }

    private static var travelPriceCalendar: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-travel-price-calendar-1",
            type: EmbedType.travelPriceCalendar.rawValue,
            appId: "travel",
            skillId: "price_calendar",
            data: [
                "query": "Munich -> Barcelona, March 2026",
                "origin": "Munich",
                "destination": "Barcelona"
            ]
        )
        return skill(id: "travel-price-calendar", label: "Price Calendar", primary: embed)
    }

    private static var travelFlight: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-travel-flight-1",
            type: EmbedType.travelFlight.rawValue,
            appId: "travel",
            skillId: "get_flight",
            data: [
                "tracks": []
            ]
        )
        return skill(id: "travel-get-flight", label: "Flight", primary: embed)
    }

    private static var travelStay: DevEmbedPreviewSkill {
        let embed = travelStayRecord(
            id: "preview-travel-stay-1",
            name: "Hotel Maximilian",
            hotelClass: 4,
            rating: 4.3,
            reviews: 1248,
            ratePerNight: "129",
            totalRate: "387",
            parentId: nil
        )
        return skill(id: "travel-stay", label: "Stay", primary: embed)
    }

    private static var travelStayFullscreen: DevEmbedPreviewSkill {
        let embed = travelStayRecord(id: "preview-travel-stay-1", name: "Hotel Maximilian",
                                     hotelClass: 4, rating: 4.3, reviews: 1248,
                                     ratePerNight: "129", totalRate: "387", parentId: nil,
                                     canonicalRates: true)
        return skill(id: "travel-stay", label: "Stay", primary: embed)
    }

    private static var travelStays: DevEmbedPreviewSkill {
        let children = [
            travelStayRecord(id: "preview-travel-stays-result-1", name: "Hotel Arts Barcelona", hotelClass: 5, rating: 4.7, reviews: 4521, ratePerNight: "320", totalRate: "960", parentId: "preview-travel-stays-1"),
            travelStayRecord(id: "preview-travel-stays-result-2", name: "Casa Camper Barcelona", hotelClass: 4, rating: 4.4, reviews: 1832, ratePerNight: "185", totalRate: "555", parentId: "preview-travel-stays-1"),
            travelStayRecord(id: "preview-travel-stays-result-3", name: "Generator Barcelona", hotelClass: 2, rating: 4.0, reviews: 3200, ratePerNight: "55", totalRate: "165", parentId: "preview-travel-stays-1")
        ]
        let parent = appSkill(
            id: "preview-travel-stays-1",
            type: EmbedType.travelStays.rawValue,
            appId: "travel",
            skillId: "search_stays",
            data: ["query": "Hotels in Barcelona, Mar 15-18", "provider": "Google"],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "travel-stays", label: "Stays Search", primary: parent, children: children)
    }

    // MARK: - Events

    private static var eventsSearch: DevEmbedPreviewSkill {
        let children = eventResults(parentId: "preview-events-search-1")
        let parent = appSkill(
            id: "preview-events-search-1",
            type: EmbedType.eventsSearch.rawValue,
            appId: "events",
            skillId: "search",
            data: [
                "query": "AI meetups in Berlin",
                "provider": "Meetup",
                "providers": ["meetup"]
            ],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "events-search", label: "Search", primary: parent, children: children)
    }

    private static var event: DevEmbedPreviewSkill {
        let embed = eventRecord(
            id: "preview-event-1",
            title: "AI & Machine Learning Berlin Meetup – Spring Edition",
            dateStart: "2026-03-15T19:00:00+01:00",
            dateEnd: "2026-03-15T22:00:00+01:00",
            eventType: "PHYSICAL",
            city: "Berlin",
            country: "Germany",
            rsvpCount: 142,
            isPaid: false,
            feeAmount: nil,
            imageURL: nil,
            venueName: "Factory Berlin",
            venueAddress: "Rheinsberger Str. 76-77",
            venueLatitude: 52.5393,
            venueLongitude: 13.4028,
            parentId: nil,
            description: "Join us for an evening of talks on large language models, RAG architectures, and deploying AI to production. Speakers from leading Berlin AI companies.\n\nSchedule:\n- 18:30 Doors open\n- 19:00 Talk 1: LLMs in Production\n- 19:45 Talk 2: RAG Architectures\n- 20:30 Networking"
        )
        return skill(id: "events-event", label: "Event", primary: embed)
    }

    // MARK: - Additional registry coverage

    private static var recording: DevEmbedPreviewSkill {
        let embed = record(id: "preview-audio-1", type: EmbedType.recording.rawValue, appId: "audio", data: [
            "filename": "voice-memo-2026-03-10.webm", "duration": "0:42", "duration_seconds": 42,
            "model": "voxtral-mini-2602",
            "transcript": "This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week."
        ])
        return skill(id: "recording", label: "Recording", primary: embed)
    }

    private static var audioGenerate: DevEmbedPreviewSkill {
        let embed = generatedAudioRecord(
            id: "preview-audio-generate-1",
            type: .audioGenerate,
            skillId: "generate",
            prompt: "",
            mode: "sound_effect",
            status: .processing
        )
        return skill(id: "audio-generate", label: "Generate audio", primary: embed)
    }

    private static var audioSpeak: DevEmbedPreviewSkill {
        // The deployed registry preview resolves this key to the shared
        // AudioGenerateEmbedPreview default (Generate SFX processing state).
        // The explicit finished fixture below exercises actual speak content.
        let embed = generatedAudioRecord(
            id: "preview-audio-speak-1",
            type: .audioSpeak,
            skillId: "generate",
            prompt: "",
            mode: "sound_effect",
            status: .processing
        )
        return skill(id: "audio-speak", label: "Speak", primary: embed)
    }

    private static var audioGenerateFinished: DevEmbedPreviewSkill {
        let embed = generatedAudioRecord(
            id: "preview-audio-generate-finished-1", type: .audioGenerate,
            skillId: "generate", prompt: "Soft rain on a Berlin courtyard with distant bicycle bells",
            mode: "sound_effect", status: .finished
        )
        return skill(id: "audio-generate-finished", label: "Generate audio", primary: embed)
    }

    private static var audioSpeakFinished: DevEmbedPreviewSkill {
        let embed = generatedAudioRecord(
            id: "preview-audio-speak-finished-1", type: .audioSpeak,
            skillId: "speak", prompt: "Your itinerary is ready for tomorrow morning.",
            mode: "calm", status: .finished
        )
        return skill(id: "audio-speak-finished", label: "Speak", primary: embed)
    }

    private static func generatedAudioRecord(
        id: String,
        type: EmbedType,
        skillId: String,
        prompt: String,
        mode: String,
        status: EmbedStatus,
        includePlayableMedia: Bool = true
    ) -> EmbedRecord {
        appSkill(
            id: id,
            type: type.rawValue,
            appId: "audio",
            skillId: skillId,
            data: [
                "prompt": prompt,
                "text_preview": prompt,
                "mode": mode,
                "voice": mode,
                "preview_audio_url": status == .finished && includePlayableMedia
                    ? "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="
                    : ""
            ],
            status: status
        )
    }

    private static var calendarListCalendars: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-calendar-list-calendars-1",
            type: EmbedType.calendarListCalendars.rawValue,
            appId: "calendar",
            skillId: "list-calendars",
            data: [:],
            status: .processing
        )
        return skill(id: "calendar-list-calendars", label: "List calendars", primary: embed)
    }

    private static var calendarGetEvents: DevEmbedPreviewSkill {
        calendarAction(id: "calendar-get-events", skillId: "get-events", title: "Upcoming events")
    }

    private static var calendarCreateEvent: DevEmbedPreviewSkill {
        calendarAction(id: "calendar-create-event", skillId: "create-event", title: "Project review")
    }

    private static var calendarUpdateEvent: DevEmbedPreviewSkill {
        calendarAction(id: "calendar-update-event", skillId: "update-event", title: "Updated project review")
    }

    private static var calendarDeleteEvent: DevEmbedPreviewSkill {
        calendarAction(id: "calendar-delete-event", skillId: "delete-event", title: "Cancelled project review")
    }

    private static func calendarAction(id: String, skillId: String, title: String) -> DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-\(id)-1",
            type: "app:calendar:\(skillId)",
            appId: "calendar",
            skillId: skillId,
            data: [:],
            status: .processing
        )
        return skill(id: id, label: title, primary: embed)
    }

    private static var codeRepoSearch: DevEmbedPreviewSkill {
        let repos: [[String: Any]] = [
            ["full_name": "sveltejs/svelte", "url": "https://github.com/sveltejs/svelte"],
            ["full_name": "markedjs/marked", "url": "https://github.com/markedjs/marked"]
        ]
        let children = repos.enumerated().map { index, repo in
            record(id: "preview-code-repo-\(index + 1)", type: EmbedType.codeRepo.rawValue,
                   appId: "code", data: repo, parentEmbedId: "preview-code-repo-search-1")
        }
        let parent = appSkill(id: "preview-code-repo-search-1", type: EmbedType.codeRepoSearch.rawValue,
                              appId: "code", skillId: "search_repos", data: [
            "query": "svelte markdown editor", "provider": "GitHub",
            "results": [["id": 0, "results": repos]], "result_count": 2
        ], embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "code-search-repos", label: "Search Repos", primary: parent, children: children)
    }

    private static var codeRepo: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-repo-direct-1", type: EmbedType.codeRepo.rawValue, appId: "code", data: [
            "url": "https://github.com/lemmingDev/ESP32-BLE-Gamepad",
            "full_name": "lemmingDev/ESP32-BLE-Gamepad",
            "name": "ESP32-BLE-Gamepad",
            "owner_login": "lemmingDev",
            "owner_avatar_url": "https://avatars.githubusercontent.com/u/15526971?v=4",
            "description": "Bluetooth LE Gamepad library for the ESP32",
            "primary_language": "C++",
            "license_name": "MIT License",
            "license_spdx_id": "MIT",
            "stars": 1516,
            "forks": 250,
            "open_issues": 35,
            "updated_at": "2026-05-08T09:02:54Z"
        ])
        return skill(id: "code-repo", label: "Repository", primary: embed)
    }

    private static var codeApplication: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-application-1", type: EmbedType.codeApplication.rawValue, appId: "code", data: [
            "name": "Recipe Manager", "framework": "Svelte", "runtime": "Node",
            "file_refs": [
                ["path": "package.json", "embed_id": "file-package", "role": "dependency_manifest"],
                ["path": "src/App.svelte", "embed_id": "file-app", "role": "source"],
                ["path": "src/main.ts", "embed_id": "file-main", "role": "source"]
            ],
            "entrypoints": [["name": "frontend", "command": "npm run dev", "port": 5173]]
        ])
        return skill(id: "code-application", label: "Application", primary: embed)
    }

    private static var businessCompanyFinancials: DevEmbedPreviewSkill {
        let results: [[String: Any]] = [
            ["company": "Cal-Maine Foods, Inc.", "ticker": "CALM", "cik": "0000016160", "country": "US", "exchange": "NASDAQ", "period_type": "annual", "fiscal_year": 2025, "period_start": "2024-06-02", "period_end": "2025-05-31", "filed": "2025-07-18", "form": "10-K", "currency": "USD", "revenue": 4_261_885_000, "gross_profit": 1_799_800_000, "operating_income": 1_446_200_000, "net_income": 1_220_048_000, "operating_cash_flow": 1_260_000_000, "assets": 3_451_000_000, "liabilities": 602_000_000, "equity": 2_849_000_000, "source_url": "https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/16160/000001616025000050/calm-20250531.htm", "accession_number": "0000016160-25-000050"],
            ["company": "Micron Technology, Inc.", "ticker": "MU", "cik": "0000723125", "country": "US", "exchange": "NASDAQ", "period_type": "annual", "fiscal_year": 2025, "period_start": "2024-08-30", "period_end": "2025-08-28", "filed": "2025-10-03", "form": "10-K", "currency": "USD", "revenue": 37_378_000_000, "gross_profit": 14_212_000_000, "operating_income": 9_411_000_000, "net_income": 8_539_000_000, "operating_cash_flow": 15_840_000_000, "assets": 82_120_000_000, "liabilities": 26_300_000_000, "equity": 55_820_000_000, "source_url": "https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/723125/000072312525000120/mu-20250828.htm", "accession_number": "0000723125-25-000120"]
        ]
        let children = results.enumerated().map { index, result in
            record(id: "legacy-business-financial-\(index == 0 ? "calm" : "mu")", type: EmbedType.businessCompanyFinancialResult.rawValue, appId: "business", skillId: "company_financials", data: result, parentEmbedId: "preview-business-financials-1")
        }
        let parent = appSkill(
            id: "preview-business-financials-1",
            type: EmbedType.businessCompanyFinancials.rawValue,
            appId: "business",
            skillId: "company_financials",
            data: [
                "query": "Compare CALM and MU latest annual financials",
                "provider": "SEC EDGAR",
                "period": "latest_annual",
                "metric_group": "summary",
                "result_count": 2,
                "results": results
            ],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "business-company-financials", label: "Company Financials", primary: parent, children: children)
    }

    private static var businessFinancialResult: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-business-financial-calm",
            type: EmbedType.businessCompanyFinancialResult.rawValue,
            appId: "business",
            skillId: "company_financials",
            data: [
                "company": "Cal-Maine Foods, Inc.",
                "ticker": "CALM",
                "cik": "0000016160",
                "period_type": "annual",
                "fiscal_year": 2025,
                "form": "10-K",
                "currency": "USD",
                "revenue": 4_261_885_000,
                "net_income": 1_220_048_000,
                "filed": "2025-07-18"
            ]
        )
        return skill(id: "business-financial-result", label: "Financial Result", primary: embed)
    }

    private static var designSearchIcons: DevEmbedPreviewSkill {
        let child = record(
            id: "preview-design-icon-result-1",
            type: EmbedType.designIconResult.rawValue,
            appId: "design",
            data: [
                "display_name": "Calendar Check",
                "collection_name": "Lucide",
                "license_title": "ISC",
                "svg_path": "M8 2v4M16 2v4M3 10h18"
            ],
            parentEmbedId: "preview-design-search-icons-1"
        )
        let parent = appSkill(id: "preview-design-search-icons-1", type: EmbedType.designSearchIcons.rawValue, appId: "design", skillId: "search_icons", data: ["query": "calendar check icon", "provider": "Iconify", "result_count": 1], embedIds: child.id)
        return skill(id: "design-search-icons", label: "Search Icons", primary: parent, children: [child])
    }

    private static var designIconResult: DevEmbedPreviewSkill {
        // The deployed canonical registry supplies no icon record for this
        // standalone surface; the production fallback shows "Icon"/"SVG icon".
        let embed = record(id: "preview-design-icon-result-direct-1", type: EmbedType.designIconResult.rawValue, appId: "design", data: [:])
        return skill(id: "design-icon-result", label: "Icon Result", primary: embed)
    }

    private static var diagramsMermaid: DevEmbedPreviewSkill {
        // Mirrors MermaidDiagramEmbedPreview.preview.ts for native/browser visual comparison.
        let diagramCode = """
        sequenceDiagram
            participant User
            participant App
            participant API
            participant Email
            User->>App: Enter email address
            App->>API: Request verification code
            API->>Email: Send one-time code
            Email-->>User: Deliver code
            User->>App: Submit code
            App->>API: Verify code
            API-->>App: Create account session
            App-->>User: Show welcome screen
        """
        let embed = record(
            id: "preview-diagrams-mermaid-1",
            type: EmbedType.diagramsMermaid.rawValue,
            appId: "diagrams",
            skillId: "mermaid",
            data: [
                "type": "mermaid",
                "app_id": "diagrams",
                "skill_id": "mermaid",
                "title": "Email Signup Sequence",
                "diagram_kind": "sequenceDiagram",
                "diagram_code": diagramCode,
                "line_count": diagramCode.split(separator: "\n").count,
                "status": "finished"
            ],
            versionNumber: 1
        )
        return skill(id: "diagrams-mermaid", label: "Mermaid", primary: embed)
    }

    // Exact synthetic page art used by the deployed Docs preview fixtures.
    private static func docsPreviewPageURL(_ svg: String) -> String {
        let unreserved = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")
        return "data:image/svg+xml;charset=utf-8," + (svg.addingPercentEncoding(withAllowedCharacters: unreserved) ?? "")
    }

    private static var docsPageOneSVG: String {
        #"""
        <svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
        <rect width="794" height="1123" fill="#ffffff"/>
        <rect x="76" y="72" width="642" height="979" rx="2" fill="#ffffff" stroke="#e5e7eb"/>
        <text x="112" y="148" font-family="Inter, Arial, sans-serif" font-size="34" font-weight="700" fill="#111827">Project Architecture Overview</text>
        <text x="112" y="206" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">Generated as a real DOCX artifact, then converted server-side to preview pages.</text>
        <rect x="112" y="252" width="570" height="1" fill="#d1d5db"/>
        <text x="112" y="314" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700" fill="#111827">Frontend</text>
        <text x="112" y="356" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">SvelteKit and Svelte 5 render the encrypted document preview after decrypting</text>
        <text x="112" y="382" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">the generated screenshot artifact in the browser.</text>
        <text x="112" y="456" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700" fill="#111827">Backend Pipeline</text>
        <text x="112" y="498" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">1. The model emits structured docx_model JSON.</text>
        <text x="112" y="526" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">2. The Docs worker creates a canonical .docx file.</text>
        <text x="112" y="554" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">3. LibreOffice converts it to PDF; PyMuPDF renders page screenshots.</text>
        <text x="112" y="582" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">4. DOCX and screenshots are AES-GCM encrypted before upload.</text>
        <rect x="112" y="660" width="570" height="132" rx="14" fill="#eef2ff" stroke="#c7d2fe"/>
        <text x="142" y="711" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#3730a3">Download</text>
        <text x="142" y="750" font-family="Inter, Arial, sans-serif" font-size="16" fill="#4338ca">The download button returns the real generated DOCX, not browser HTML.</text>
        </svg>
        """#
    }

    private static var docsPageTwoSVG: String {
        #"""
        <svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
        <rect width="794" height="1123" fill="#ffffff"/>
        <rect x="76" y="72" width="642" height="979" rx="2" fill="#ffffff" stroke="#e5e7eb"/>
        <text x="112" y="148" font-family="Inter, Arial, sans-serif" font-size="30" font-weight="700" fill="#111827">Compatibility</text>
        <text x="112" y="214" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">Existing document_html embeds still render through the legacy HTML fallback.</text>
        <text x="112" y="242" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">New embeds use docx_model, encrypted artifacts, and generated preview pages.</text>
        <rect x="112" y="318" width="250" height="130" rx="16" fill="#ecfdf5" stroke="#a7f3d0"/>
        <text x="142" y="372" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#065f46">Legacy HTML</text>
        <text x="142" y="410" font-family="Inter, Arial, sans-serif" font-size="15" fill="#047857">Still viewable and downloadable.</text>
        <rect x="432" y="318" width="250" height="130" rx="16" fill="#fef3c7" stroke="#fde68a"/>
        <text x="462" y="372" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#92400e">DOCX Artifact</text>
        <text x="462" y="410" font-family="Inter, Arial, sans-serif" font-size="15" fill="#b45309">Canonical generated file.</text>
        </svg>
        """#
    }

    private static var docsHTML: String {
        #"""
        <h1>Project Architecture Overview</h1>
        <p>This document outlines the architecture decisions for the OpenMates platform, covering frontend, backend, and infrastructure components.</p>
        <h2>1. Frontend Architecture</h2>
        <p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity. Key design decisions include:</p>
        <ul>
        <li>Component-based architecture with shared UI package</li>
        <li>CSS custom properties for theming</li>
        <li>IndexedDB for local data persistence</li>
        <li>Client-side encryption for user data</li>
        </ul>
        <h2>2. Backend Architecture</h2>
        <p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services. Core components:</p>
        <ul>
        <li>WebSocket connections for real-time updates</li>
        <li>Redis for caching and task queues</li>
        <li>S3-compatible storage for encrypted files</li>
        </ul>
        <h2>3. Database Layer</h2>
        <p>PostgreSQL serves as the primary data store, managed through <strong>Directus CMS</strong>. The schema is designed for:</p>
        <ul>
        <li>Multi-tenant isolation</li>
        <li>Efficient query patterns for chat history</li>
        <li>JSON columns for flexible metadata storage</li>
        </ul>
        <h2>4. Infrastructure</h2>
        <p>The application is deployed using Docker containers orchestrated with Docker Compose. Each service runs in its own container for isolation and scalability.</p>
        """#
    }

    private static var docsDocument: DevEmbedPreviewSkill {
        let embed = record(id: "preview-docs-1", type: EmbedType.docsDoc.rawValue, appId: "docs", data: [
            "title": "Project Architecture Overview", "filename": "architecture.docx",
            "word_count": 156, "page_count": 2, "html": docsHTML, "html_content": docsHTML,
            "preview_page_urls": ["1": docsPreviewPageURL(docsPageOneSVG), "2": docsPreviewPageURL(docsPageTwoSVG)]
        ])
        return skill(id: "docs-doc", label: "Document", primary: embed)
    }

    private static var electronicsSearch: DevEmbedPreviewSkill {
        electronicsSearchSkill(id: "preview-electronics-search-1",
                               results: electronicsPreviewResults)
    }

    private static var electronicsSearchFullscreen: DevEmbedPreviewSkill {
        electronicsSearchSkill(id: "preview-electronics-search-fullscreen",
                               results: electronicsFullscreenResults)
    }

    private static func electronicsSearchSkill(id: String, results: [[String: Any]]) -> DevEmbedPreviewSkill {
        let children = results.enumerated().map { index, data in
            record(id: "\(id)-component-\(index + 1)",
                   type: EmbedType.electronicsComponent.rawValue,
                   appId: "electronics", data: data, parentEmbedId: id)
        }
        let parent = appSkill(id: id, type: EmbedType.electronicsSearch.rawValue,
                              appId: "electronics", skillId: "search_components",
                              data: ["query": "12V to 3.3V buck converter at 3A",
                                     "provider": "TI WEBENCH", "results": results,
                                     "result_count": results.count],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: id, label: "Search Components", primary: parent, children: children)
    }

    private static var electronicsPreviewResults: [[String: Any]] {
        [
            ["type": "power_converter", "provider": "TI WEBENCH",
             "part_number": "TPS564257DRLR", "base_part_number": "TPS564257",
             "title": "TPS564257DRLR Buck converter", "topology": "Buck",
             "package": "SOT-563", "regulator_type": "Converter",
             "product_url": "https://www.ti.com/product/TPS564257",
             "datasheet_url": "https://www.ti.com/lit/gpn/tps564257",
             "bom_cost_usd": 0.47, "bom_count": 11,
             "efficiency_percent": 92.4, "footprint_mm2": 89.6],
            ["type": "power_converter", "provider": "TI WEBENCH",
             "part_number": "TPS563257DRLR", "base_part_number": "TPS563257",
             "title": "TPS563257DRLR Buck converter", "topology": "Buck",
             "package": "SOT-563", "regulator_type": "Converter",
             "product_url": "https://www.ti.com/product/TPS563257",
             "datasheet_url": "https://www.ti.com/lit/gpn/tps563257",
             "bom_cost_usd": 0.43, "bom_count": 10,
             "efficiency_percent": 91.8, "footprint_mm2": 84.2]
        ]
    }

    private static var electronicsFullscreenResults: [[String: Any]] {
        var rows = electronicsPreviewResults
        rows[0]["control_mode"] = "D-CAP3"
        rows[0]["description"] = "Compact synchronous buck converter reference design from TI WEBENCH."
        rows[0]["frequency_hz"] = 650000
        rows[0]["max_output_current_a"] = 4
        rows[0]["input_voltage_min_v"] = 4.5
        rows[0]["input_voltage_max_v"] = 17
        rows[0]["output_voltage_min_v"] = 0.6
        rows[0]["output_voltage_max_v"] = 7
        rows[0]["isolated"] = false
        rows[1]["isolated"] = false
        return rows
    }

    private static var electronicsPcbSchematic: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-electronics-pcb-1",
            type: EmbedType.electronicsPcbSchematic.rawValue,
            status: .processing,
            appId: "electronics",
            data: ["language": "atopile"]
        )
        return skill(id: "electronics-pcb-schematic", label: "PCB Schematic", primary: embed)
    }

    private static var electronicsComponent: DevEmbedPreviewSkill {
        let embed = record(id: "preview-electronics-component-1",
                           type: EmbedType.electronicsComponent.rawValue,
                           appId: "electronics", data: electronicsPreviewResults[0])
        return skill(id: "electronics-component", label: "Component", primary: embed)
    }

    private static var electronicsComponentFullscreen: DevEmbedPreviewSkill {
        var data = electronicsFullscreenResults[0]
        data["output_ripple_vpp"] = 0.014
        let embed = record(id: "preview-electronics-component-fs-1",
                           type: EmbedType.electronicsComponent.rawValue,
                           appId: "electronics", data: data)
        return skill(id: "electronics-component-fullscreen", label: "Component", primary: embed)
    }

    private static var healthAppointment: DevEmbedPreviewSkill {
        let embed = record(id: "preview-health-appointment-1", type: EmbedType.healthAppointment.rawValue, appId: "health", data: [
            "slot_datetime": "2026-04-03T10:30:00", "name": "Dr. Sophie Müller",
            "speciality": "Ophthalmologist", "address": "Maximilianstraße 12\n80539 Munich",
            "insurance": "public", "telehealth": false
        ])
        return skill(id: "health-appointment", label: "Appointment", primary: embed)
    }

    private static var healthAppointmentFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-health-appointment-fs-1", type: EmbedType.healthAppointment.rawValue, appId: "health", data: [
            "slot_datetime": "2026-04-03T10:30:00", "name": "Dr. Sophie Müller",
            "speciality": "Ophthalmologist", "address": "Maximilianstraße 12\n80539 Munich",
            "gps_coordinates": ["latitude": 48.1397, "longitude": 11.5784],
            "insurance": "public", "telehealth": false,
            "practice_url": "https://www.doctolib.de/ophtalmologe/munich/sophie-mueller",
            "provider": "Doctolib", "provider_platform": "Doctolib"
        ])
        return skill(id: "health-appointment-fullscreen", label: "Appointment", primary: embed)
    }

    private static var fitnessLocation: DevEmbedPreviewSkill {
        let embed = record(id: "preview-fitness-location-1", type: EmbedType.fitnessLocation.rawValue,
                           appId: "fitness", data: fitnessStandalonePreviewData)
        return skill(id: "fitness-location", label: "Fitness Location", primary: embed)
    }

    private static var fitnessClass: DevEmbedPreviewSkill {
        let embed = record(id: "preview-fitness-class-1", type: EmbedType.fitnessClass.rawValue,
                           appId: "fitness", data: fitnessStandalonePreviewData)
        return skill(id: "fitness-class", label: "Fitness Class", primary: embed)
    }

    private static var fitnessStandalonePreviewData: [String: Any] {
        ["id": "appointment-1", "provider": "Urban Sports Club",
         "appointment_id": "appointment-1", "name": "Morning Yoga Flow",
         "category": "Yoga", "attendance_mode": "onsite", "date": "2026-07-10",
         "time_range": "07:30 - 08:30", "venue_name": "Yoga Studio Kreuzberg",
         "venue_address": "Oranienstr. 1, 10997 Berlin", "distance_km": 0.9,
         "spots_display": "5 spots left", "plans_required": ["Classic", "Premium", "Max"]]
    }

    private static var fitnessClassFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-fitness-class-fs", type: EmbedType.fitnessClass.rawValue,
                           appId: "fitness", data: [:])
        return skill(id: "fitness-class-fullscreen", label: "Fitness Class", primary: embed)
    }

    private static var fitnessLocationFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-fitness-location-fs", type: EmbedType.fitnessLocation.rawValue,
                           appId: "fitness", data: [:])
        return skill(id: "fitness-location-fullscreen", label: "Fitness Location", primary: embed)
    }

    private static var fitnessSearchLocations: DevEmbedPreviewSkill {
        fitnessSearchSkill(type: .fitnessSearchLocations, id: "preview-fitness-locations-1", key: "fitness-search-locations")
    }

    private static var fitnessSearchClasses: DevEmbedPreviewSkill {
        fitnessSearchSkill(type: .fitnessSearchClasses, id: "preview-fitness-classes-1", key: "fitness-search-classes")
    }

    private static func fitnessSearchSkill(type: EmbedType, id: String, key: String) -> DevEmbedPreviewSkill {
        let results: [[String: Any]] = [
            ["id": "appointment-1", "provider": "Urban Sports Club", "appointment_id": "appointment-1",
             "name": "Morning Yoga Flow", "category": "Yoga", "attendance_mode": "onsite",
             "date": "2026-07-10", "time_range": "07:30 - 08:30", "venue_name": "Yoga Studio Kreuzberg",
             "venue_address": "Oranienstr. 1, 10997 Berlin", "distance_km": 0.9,
             "spots_display": "5 spots left", "plans_required": ["Classic", "Premium", "Max"],
             "detail_url": "https://urbansportsclub.com/en/class-details/appointment-1"],
            ["id": "appointment-2", "provider": "Urban Sports Club", "appointment_id": "appointment-2",
             "name": "HIIT Strength", "category": "HIIT", "attendance_mode": "onsite",
             "date": "2026-07-10", "time_range": "18:00 - 19:00", "venue_name": "BEAT81 - Paul-Lincke-Ufer",
             "venue_address": "Paul-Lincke-Ufer 19, 10999 Berlin", "distance_km": 0.7,
             "spots_display": "3 spots left", "plans_required": ["Premium", "Max"],
             "detail_url": "https://urbansportsclub.com/en/class-details/appointment-2"]
        ]
        let children = results.enumerated().map { index, result in
            record(id: "\(id)-result-\(index + 1)", type: EmbedType.fitnessClass.rawValue,
                   appId: "fitness", data: result, parentEmbedId: id)
        }
        let parent = appSkill(id: id, type: type.rawValue, appId: "fitness", skillId: "search_classes",
                              data: ["provider": "Urban Sports Club", "results": [[
                                "id": "classes", "provider": "Urban Sports Club", "result_count": 2,
                                "filters": ["query": "yoga", "address": "Sorauer Str. 12, Berlin", "radius_km": 3,
                                            "plan": "all", "attendance_mode": "onsite"],
                                "summary": "Found 2 Urban Sports classes in onsite mode. Searched all Urban Sports plans.",
                                "results": results
                              ]]], embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: key, label: "Search classes", primary: parent, children: children)
    }

    private static var healthPreviewResults: [[String: Any]] {
        [
            ["type": "appointment", "slot_datetime": "2026-04-03T08:00:00",
             "name": "Dr. Markus Reinholz", "speciality": "Hautarzt / Dermatologe",
             "address": "Frauenplatz 11, 80331 München", "insurance": "", "telehealth": false],
            ["type": "appointment", "slot_datetime": "2026-04-03T10:30:00",
             "name": "Dr. Sophie Müller", "speciality": "Ophthalmologist",
             "address": "Maximilianstraße 12, 80539 Munich", "insurance": "public", "telehealth": false],
            ["type": "appointment", "slot_datetime": "2026-04-05T14:00:00",
             "name": "Prof. Dr. Klaus Weber", "speciality": "Ophthalmologist",
             "address": "Leopoldstraße 45, 80802 Munich", "insurance": "private", "telehealth": true]
        ]
    }

    private static var healthFullscreenResults: [[String: Any]] {
        [
            ["type": "appointment", "slot_datetime": "2026-04-03T08:00:00",
             "name": "Dr. Markus Reinholz", "speciality": "Hautarzt / Dermatologe",
             "address": "Frauenplatz 11, 80331 München",
             "gps_coordinates": ["latitude": 48.1374, "longitude": 11.5733],
             "insurance": "", "telehealth": false, "provider_platform": "Jameda",
             "booking_url": "https://www.jameda.de/booking/datum-auswaehlen/12345/67890/2026-04-03T08:00:00+01:00",
             "rating": 5.0, "rating_count": 125, "price": 120,
             "service_name": "Erstuntersuchung (Neupatient/in)"],
            ["type": "appointment", "slot_datetime": "2026-04-03T10:30:00",
             "name": "Dr. Sophie Müller", "speciality": "Ophthalmologist",
             "address": "Maximilianstraße 12, 80539 Munich",
             "gps_coordinates": ["latitude": 48.1397, "longitude": 11.5784],
             "insurance": "public", "telehealth": false, "provider_platform": "Doctolib",
             "practice_url": "https://www.doctolib.de/ophtalmologe/munich/sophie-mueller"],
            ["type": "appointment", "slot_datetime": "2026-04-03T14:00:00",
             "name": "Prof. Dr. Klaus Weber", "speciality": "Ophthalmologist",
             "address": "Leopoldstraße 45, 80802 Munich",
             "insurance": "private", "telehealth": true, "provider_platform": "Doctolib",
             "practice_url": "https://www.doctolib.de/cardiologue/munich/klaus-weber"],
            ["type": "appointment", "slot_datetime": "2026-04-04T09:30:00",
             "name": "Konrad Witkowski", "speciality": "Zahnarzt",
             "address": "Hoheluftchaussee 2, 20253 Hamburg", "provider_platform": "Jameda",
             "booking_url": "https://www.jameda.de/booking/datum-auswaehlen/44444/55555/2026-04-04T09:30:00+01:00",
             "rating": 4.8, "rating_count": 46, "service_name": "Allgemeine Sprechstunde"],
            ["type": "appointment", "name": "Dr. Anna Schmidt", "speciality": "Ophthalmologist",
             "address": "Sendlinger Straße 8, 80331 Munich",
             "insurance": "public", "telehealth": false, "provider_platform": "Doctolib",
             "practice_url": "https://www.doctolib.de/ophtalmologe/munich/anna-schmidt"]
        ]
    }

    private static var healthSearch: DevEmbedPreviewSkill {
        domainSearch(id: "preview-health-search-1", skillID: "health-search-appointments",
                     label: "Search", type: .healthSearch, childType: .healthAppointment,
                     appID: "health", action: "search_appointments",
                     query: "Ophthalmologist in Munich", provider: "Doctolib, Jameda",
                     results: healthPreviewResults)
    }

    private static var healthSearchFullscreen: DevEmbedPreviewSkill {
        domainSearch(id: "preview-health-search-fs", skillID: "health-search-fullscreen",
                     label: "Search", type: .healthSearch, childType: .healthAppointment,
                     appID: "health", action: "search_appointments",
                     query: "Ophthalmologist in Munich", provider: "Doctolib, Jameda",
                     results: healthFullscreenResults)
    }

    private static var homeListingData: [String: Any] {
        ["title": "Schöne 2-Zimmer-Wohnung in Kreuzberg", "price_label": "850 EUR/month",
         "size_sqm": 55, "rooms": 2, "address": "Bergmannstr. 12, 10961 Berlin",
         "image_url": "", "url": "https://www.immobilienscout24.de/expose/12345",
         "provider": "ImmoScout24", "listing_type": "rent"]
    }

    private static var homeListing: DevEmbedPreviewSkill {
        let embed = record(id: "preview-listing-1", type: EmbedType.homeListing.rawValue,
                           appId: "home", data: homeListingData)
        return skill(id: "home-listing", label: "Listing", primary: embed)
    }

    private static var homePreviewResults: [[String: Any]] {
        [
            ["title": "Schöne 2-Zimmer-Wohnung in Kreuzberg", "price_label": "850 EUR/month",
             "size_sqm": 55, "rooms": 2, "address": "Bergmannstr., 10961 Berlin",
             "image_url": "", "url": "https://www.immobilienscout24.de/expose/12345",
             "provider": "ImmoScout24", "listing_type": "rent"],
            ["title": "WG-Zimmer in Prenzlauer Berg", "price_label": "500 EUR/month",
             "size_sqm": 18, "rooms": 1, "address": "Schönhauser Allee, 10439 Berlin",
             "image_url": "", "url": "https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html",
             "provider": "WG-Gesucht", "listing_type": "rent"],
            ["title": "Helle 3-Zimmer-Altbauwohnung mit Balkon", "price_label": "1.200 EUR/month",
             "size_sqm": 85, "rooms": 3, "address": "Friedrichshain, 10245 Berlin",
             "image_url": "", "url": "https://www.kleinanzeigen.de/s-anzeige/67890",
             "provider": "Kleinanzeigen", "listing_type": "rent"]
        ]
    }

    private static var homeFullscreenResults: [[String: Any]] {
        var rows = homePreviewResults
        rows[1]["title"] = "WG-Zimmer in Prenzlauer Berg — möbliert, ab sofort"
        rows.append(["title": "Großzügiges Loft in Mitte mit Dachterrasse",
                     "price_label": "2.100 EUR/month", "size_sqm": 120, "rooms": 4,
                     "address": "Rosenthaler Str., 10119 Berlin", "image_url": "",
                     "url": "https://www.immobilienscout24.de/expose/99999",
                     "provider": "ImmoScout24", "listing_type": "rent"])
        return rows
    }

    private static var homeSearch: DevEmbedPreviewSkill {
        domainSearch(id: "preview-home-search-1", skillID: "home-search", label: "Search",
                     type: .homeSearch, childType: .homeListing, appID: "home", action: "search",
                     query: "Berlin", provider: "Multi", results: homePreviewResults)
    }

    private static var homeSearchFullscreen: DevEmbedPreviewSkill {
        domainSearch(id: "preview-home-search-fs", skillID: "home-search-fullscreen", label: "Search",
                     type: .homeSearch, childType: .homeListing, appID: "home", action: "search",
                     query: "Berlin", provider: "Multi", results: homeFullscreenResults)
    }

    private static var mail: DevEmbedPreviewSkill {
        let embed = record(id: "preview-mail-email-1", type: EmbedType.mailEmail.rawValue, appId: "mail", data: [
            "receiver": "[EMAIL_1_com]",
            "subject": "Project Update — Sprint 12 Review",
            "content": "Hi Anna,\n\nThe latest sprint review went well. All tickets were closed except the auth refactor, which is carried over to Sprint 13.\n\nKey highlights:\n- Login flow redesigned (done)\n- API rate limiting added (done)\n- Auth refactor (carried over)\n\nLet me know if you have any questions.\n\nBest,\nMax",
            "footer": ""
        ])
        return skill(id: "mail-email", label: "Mail", primary: embed)
    }

    private static var mailSearch: DevEmbedPreviewSkill {
        let rows: [[String: Any]] = [
            ["uid": "1", "subject": "Invoice #1042 - OpenMates B.V.",
             "from": "billing@acme.com", "to": "admin@openmates.org",
             "snippet": "Please find attached invoice #1042 for services rendered in February 2026.",
             "date": "Thu, 28 Feb 2026 10:00:00 +0100", "timestamp": 1740733200, "is_unread": true],
            ["uid": "2", "subject": "Server maintenance scheduled",
             "from": "ops@provider.com", "to": "admin@openmates.org",
             "snippet": "Scheduled maintenance window: Saturday 22:00-02:00 UTC.",
             "date": "Wed, 27 Feb 2026 14:30:00 +0100", "timestamp": 1740659400, "is_unread": false],
            ["uid": "3", "subject": "New contributor joined",
             "from": "github-noreply@github.com", "to": "admin@openmates.org",
             "snippet": "A new contributor has opened a pull request in OpenMates/OpenMates.",
             "date": "Mon, 25 Feb 2026 08:00:00 +0100", "timestamp": 1740470400, "is_unread": false]
        ]
        let children = rows.enumerated().map { index, row in
            record(id: "preview-mail-search-result-\(index + 1)", type: EmbedType.mailEmail.rawValue,
                   appId: "mail", data: row, parentEmbedId: "preview-mail-search-1")
        }
        let parent = appSkill(id: "preview-mail-search-1", type: EmbedType.mailSearch.rawValue,
                              appId: "mail", skillId: "search",
                              data: ["query": "invoice", "provider": "Proton Mail",
                                     "results": rows, "result_count": 3],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "mail-search", label: "Search", primary: parent, children: children)
    }

    private static var mailSearchFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-mail-search-fullscreen", type: EmbedType.mailSearch.rawValue,
                              appId: "mail", skillId: "search",
                              data: ["query": "Recent emails", "title": "Recent emails",
                                     "time_range": "All time", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "mail-search-fullscreen", label: "Search", primary: parent)
    }

    // Independent defaults mirror the deployed preview and fullscreen fixtures.
    private static var mapsPlacePreview: DevEmbedPreviewSkill {
        let embed = record(id: "preview-maps-place-location", type: EmbedType.mapsPlace.rawValue,
                           appId: "maps", data: normalizeWebProps([
                            "name": "Berlin Hauptbahnhof", "address": "Europaplatz 1, 10557 Berlin",
                            "locationType": "precise_location", "placeType": "railway",
                            "mapImageUrl": "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20640%20360%22%3E%3Crect%20width%3D%22640%22%20height%3D%22360%22%20fill%3D%22%23e5e7eb%22%2F%3E%3Ctext%20x%3D%22320%22%20y%3D%22180%22%20text-anchor%3D%22middle%22%20dominant-baseline%3D%22middle%22%20font-family%3D%22sans-serif%22%20font-size%3D%2232%22%20fill%3D%22%236b7280%22%3EMap%20preview%3C%2Ftext%3E%3C%2Fsvg%3E"
                           ]))
        return skill(id: "maps-place-preview", label: "Location", primary: embed)
    }

    private static var mapsPlaceFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-maps-place-fullscreen", type: EmbedType.mapsPlace.rawValue,
                           appId: "maps", data: normalizeWebProps([
                            "name": "Man vs. Machine Coffee Roasters",
                            "displayName": "Man vs. Machine Coffee Roasters",
                            "address": "Müllerstraße 23, 80469 Munich, Germany",
                            "formattedAddress": "Müllerstraße 23, 80469 Munich, Germany",
                            "lat": 48.1321, "lon": 11.5718, "zoom": 16,
                            "latitude": 48.1321, "longitude": 11.5718,
                            "rating": 4.7, "reviews": 1832, "userRatingCount": 1832,
                            "placeType": "Coffee Shop", "category": "Coffee Shop",
                            "websiteUri": "https://www.mvsm.coffee", "placeId": "ChIJabc123"
                           ]))
        return skill(id: "maps-place-fullscreen", label: "Location", primary: embed)
    }

    private static var mapsLocation: DevEmbedPreviewSkill {
        let embed = record(id: "preview-maps-location-1", type: EmbedType.maps.rawValue, appId: "maps", data: ["title": "Berlin Hauptbahnhof", "address": "Europaplatz 1, Berlin", "latitude": 52.5251, "longitude": 13.3694])
        return skill(id: "maps", label: "Location", primary: embed)
    }

    private static var mapsSearch: DevEmbedPreviewSkill {
        let rows: [[String: Any]] = [
            ["name": "Man vs. Machine Coffee Roasters", "address": "Müllerstraße 23, 80469 Munich",
             "rating": 4.7, "reviews": 1832, "type": "Coffee shop", "latitude": 48.1321, "longitude": 11.5718],
            ["name": "Lost Weekend", "address": "Schellingstraße 3, 80799 Munich",
             "rating": 4.5, "reviews": 2456, "type": "Coffee shop & bookstore", "latitude": 48.1523, "longitude": 11.5784],
            ["name": "Café Frischhut", "address": "Prälat-Zistl-Straße 8, 80331 Munich",
             "rating": 4.6, "reviews": 3210, "type": "Traditional café", "latitude": 48.1354, "longitude": 11.5762]
        ]
        let children = rows.enumerated().map { index, row in
            record(id: "preview-maps-place-\(index + 1)", type: EmbedType.mapsPlace.rawValue,
                   appId: "maps", data: row, parentEmbedId: "preview-maps-search-1")
        }
        let parent = appSkill(id: "preview-maps-search-1", type: EmbedType.mapsSearch.rawValue,
                              appId: "maps", skillId: "search",
                              data: ["query": "coffee shops near Marienplatz Munich",
                                     "provider": "Google", "results": rows, "result_count": 3],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "maps-search", label: "Search", primary: parent, children: children)
    }

    private static var mapsSearchFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-maps-search-fullscreen", type: EmbedType.mapsSearch.rawValue,
                              appId: "maps", skillId: "search",
                              data: ["query": "coffee shops near Marienplatz Munich",
                                     "provider": "Google", "results": [] as [[String: Any]],
                                     "result_count": 0])
        return skill(id: "maps-search-fullscreen", label: "Search", primary: parent)
    }

    private static var mathCalculate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-math-calculate-1", type: EmbedType.mathCalculate.rawValue, appId: "math", skillId: "calculate", data: [
            "title": "Trigonometry sanity check",
            "query": "sin(pi/4) + cos(pi/3)",
            "results": [["expression": "sin(pi/4) + cos(pi/3)", "result": "1.20710678118655", "result_type": "float", "mode": "numeric"]]
        ])
        return skill(id: "math-calculate", label: "Calculate", primary: embed)
    }

    private static var mathPlot: DevEmbedPreviewSkill {
        let embed = record(id: "preview-math-plot-1", type: EmbedType.mathPlot.rawValue, appId: "math", data: ["plot_spec": "f(x) = sin(x)\nf(x) = cos(x)"])
        return skill(id: "math-plot", label: "Plot", primary: embed)
    }

    private static var musicGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-music-generate-1", type: EmbedType.musicGenerate.rawValue, appId: "music", skillId: "generate", data: [
            "prompt": "A 30 second ambient synth background loop with soft pads and no drums",
            "mode": "background", "model": "lyria-3-clip-preview", "duration_seconds": 30,
            "generated_at": "2026-05-21T23:30:00Z", "watermarking": "SynthID"
        ])
        return skill(id: "music-generate", label: "Generate", primary: embed)
    }

    private static var mindmapsMindmap: DevEmbedPreviewSkill {
        let embed = record(id: "preview-mindmap-1", type: EmbedType.mindmapsMindmap.rawValue,
                           status: .processing, appId: "mindmaps", data: ["source_json": ""])
        return skill(id: "mindmaps-mindmap", label: "Mind Map", primary: embed)
    }

    private static var models3dSearch: DevEmbedPreviewSkill {
        let child = record(
            id: "preview-models3d-result-1",
            type: EmbedType.models3dModelResult.rawValue,
            appId: "models3d",
            data: ["title": "Low-poly planter", "model_format": "glb", "source_url": "https://example.com/models/planter"],
            parentEmbedId: "preview-models3d-search-1"
        )
        let parent = appSkill(id: "preview-models3d-search-1", type: EmbedType.models3dSearch.rawValue, appId: "models3d", skillId: "search", data: ["query": "low poly planter", "provider": "Sketchfab", "result_count": 1], embedIds: child.id)
        return skill(id: "models3d-search", label: "Search", primary: parent, children: [child])
    }

    private static var models3dModelResult: DevEmbedPreviewSkill {
        let embed = record(id: "preview-models3d-result-direct-1", type: EmbedType.models3dModelResult.rawValue, appId: "models3d", data: ["title": "Low-poly planter", "model_format": "glb", "source_url": "https://example.com/models/planter"])
        return skill(id: "models3d-model-result", label: "Model Result", primary: embed)
    }

    private static var models3dGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-models3d-generate-1", type: EmbedType.models3dGenerate.rawValue, appId: "models3d", skillId: "generate", data: ["title": "Generated planter", "prompt": "Low-poly balcony herb planter", "status": "finished"])
        return skill(id: "models3d-generate", label: "Generate", primary: embed)
    }

    private static var newsSearch: DevEmbedPreviewSkill {
        let rows: [[String: Any]] = [
            ["title": "AI Advances Continue to Transform Software Development",
             "url": "https://techcrunch.com/2026/ai-advances",
             "description": "New AI-powered development tools are changing how developers write, test, and deploy software.",
             "favicon": "/favicon.png", "thumbnail": ["original": "/images/og-image.jpg"],
             "published_at": "2026-02-15T08:00:00Z"],
            ["title": "WebAssembly 3.0 Specification Finalized",
             "url": "https://theverge.com/2026/wasm-3",
             "description": "The W3C has finalized the WebAssembly 3.0 specification, bringing garbage collection and improved threading.",
             "favicon": "/favicon.png", "thumbnail": ["original": "/images/og-image.jpg"],
             "published_at": "2026-02-10T12:00:00Z"],
            ["title": "European Tech Scene Sees Record Venture Capital Investment",
             "url": "https://bbc.com/news/eu-vc",
             "description": "European startups raised a record €45 billion in venture capital funding in Q4 2025.",
             "favicon": "/favicon.png", "thumbnail": ["original": "/images/og-image.jpg"],
             "published_at": "2026-01-28T09:00:00Z"]
        ]
        let children = rows.enumerated().map { index, row in
            record(id: "preview-news-result-\(index + 1)", type: EmbedType.webWebsite.rawValue,
                   appId: "news", data: row, parentEmbedId: "preview-news-search-1")
        }
        let parent = appSkill(id: "preview-news-search-1", type: EmbedType.newsSearch.rawValue,
                              appId: "news", skillId: "search",
                              data: ["query": "latest technology news 2026",
                                     "provider": "Brave Search", "results": rows,
                                     "result_count": 3],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "news-search", label: "Search", primary: parent, children: children)
    }

    private static var nutritionRecipe: DevEmbedPreviewSkill {
        let embed = record(id: "preview-nutrition-recipe-1", type: EmbedType.nutritionRecipe.rawValue, appId: "nutrition", data: nutritionRecipeData)
        return skill(id: "nutrition-recipe", label: "Recipe", primary: embed)
    }

    private static var nutritionRecipeData: [String: Any] {
        ["title": "Spaghetti Aglio e Olio",
         "description": "Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl und Chili",
         "image_url": "", "total_time_minutes": 25, "difficulty": "einfach",
         "rating": 4.7, "rating_count": 342, "dietary_tags": ["vegetarisch"], "servings": 4]
    }

    private static var nutritionRecipeFullscreen: DevEmbedPreviewSkill {
        var data = nutritionRecipeData
        data["description"] = "Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl, Knoblauch und Chili. Einfach, schnell und unglaublich lecker."
        data["recipe_url"] = "https://www.edamam.com/results/recipes/?search=spaghetti%20aglio%20e%20olio"
        data["prep_time_minutes"] = 10
        data["cook_time_minutes"] = 15
        data["ernaehrwert_score"] = 6
        data["categories"] = ["Hauptspeise", "Pasta", "Italienisch"]
        data["ingredients"] = [
            ["amount": "400", "unit": "g", "name": "Spaghetti"],
            ["amount": "6", "unit": "Zehen", "name": "Knoblauch"],
            ["amount": "100", "unit": "ml", "name": "Olivenöl (extra vergine)"],
            ["amount": "1", "unit": "TL", "name": "Chiliflocken"],
            ["amount": "1", "unit": "Bund", "name": "Petersilie"],
            ["name": "Salz und Pfeffer"]
        ]
        data["instructions"] = [
            ["step": 1, "text": "Spaghetti in einem großen Topf mit reichlich Salzwasser al dente kochen. Etwas Kochwasser aufheben."],
            ["step": 2, "text": "Knoblauch schälen und in dünne Scheiben schneiden. Petersilie fein hacken."],
            ["step": 3, "text": "Olivenöl in einer großen Pfanne bei mittlerer Hitze erwärmen. Knoblauch darin goldbraun anbraten (nicht zu dunkel!)."],
            ["step": 4, "text": "Chiliflocken zum Knoblauch geben und kurz mitrösten."],
            ["step": 5, "text": "Abgetropfte Spaghetti in die Pfanne geben, mit etwas Kochwasser vermengen. Mit Petersilie, Salz und Pfeffer abschmecken."]
        ]
        data["nutrition"] = ["calories_kcal": 520, "protein_g": 14, "fat_g": 22, "carbs_g": 68]
        let embed = record(id: "preview-recipe-fs-001", type: EmbedType.nutritionRecipe.rawValue,
                           appId: "nutrition", data: data)
        return skill(id: "nutrition-recipe-fullscreen", label: "Recipe", primary: embed)
    }

    private static var nutritionPreviewResults: [[String: Any]] {
        [
            ["uid": "edamam-recipe-001", "title": "Spaghetti Aglio e Olio",
             "description": "Klassisches italienisches Knoblauch-Pasta-Gericht",
             "image_url": "", "total_time_minutes": 25, "difficulty": "einfach",
             "rating": 4.7, "rating_count": 342, "dietary_tags": ["vegetarisch"], "servings": 4],
            ["uid": "edamam-recipe-002", "title": "Penne Arrabiata mit frischen Tomaten",
             "description": "Scharfe Tomatensoße mit Penne", "image_url": "",
             "total_time_minutes": 30, "difficulty": "einfach",
             "rating": 4.5, "rating_count": 218, "dietary_tags": ["vegan"], "servings": 4],
            ["uid": "edamam-recipe-003", "title": "Tagliatelle mit Pilzrahmsauce",
             "description": "Cremige Pilzsauce mit frischen Kräutern", "image_url": "",
             "total_time_minutes": 35, "difficulty": "mittel",
             "rating": 4.8, "rating_count": 156, "dietary_tags": ["vegetarisch"], "servings": 2]
        ]
    }

    private static var nutritionFullscreenResults: [[String: Any]] {
        var first = nutritionRecipeFullscreen.primaryEmbed.rawData?.mapValues(\.value) ?? [:]
        first["type"] = "recipe"
        first["uid"] = "recipe-001"
        var second = nutritionPreviewResults[1]
        second["type"] = "recipe"
        second["uid"] = "recipe-002"
        second["title"] = "Penne Arrabiata"
        return [first, second]
    }

    private static var nutritionSearch: DevEmbedPreviewSkill {
        domainSearch(id: "preview-nutrition-search-1", skillID: "nutrition-search-recipes",
                     label: "Search", type: .nutritionSearch, childType: .nutritionRecipe,
                     appID: "nutrition", action: "search_recipes",
                     query: "vegetarische Pasta", provider: "Edamam", results: nutritionPreviewResults)
    }

    private static var nutritionSearchFullscreen: DevEmbedPreviewSkill {
        domainSearch(id: "preview-nutrition-search-fs", skillID: "nutrition-search-fullscreen",
                     label: "Search", type: .nutritionSearch, childType: .nutritionRecipe,
                     appID: "nutrition", action: "search_recipes",
                     query: "vegetarische Pasta", provider: "Edamam", results: nutritionFullscreenResults)
    }

    private static var pdf: DevEmbedPreviewSkill {
        let embed = record(id: "preview-pdf-upload-1", type: EmbedType.pdf.rawValue, appId: "pdf", data: ["filename": "Q4-2025-Annual-Report.pdf", "page_count": 42])
        return skill(id: "pdf", label: "PDF", primary: embed)
    }

    private static var reminderSet: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-set-1", type: EmbedType.reminderSet.rawValue, appId: "reminder", skillId: "set-reminder", data: reminderDefaultData)
        return skill(id: "reminder-set-reminder", label: "Set", primary: embed)
    }

    private static var reminderDefaultData: [String: Any] {
        [
            "reminder_id": "rem-abc-123", "trigger_at_formatted": "Tomorrow at 9:00 AM",
            "target_type": "new_chat", "is_repeating": false,
            "trigger_at": Int(Date().addingTimeInterval(86_400).timeIntervalSince1970),
            "prompt": "Review the pull request for the new authentication module",
            "message": "Reminder set successfully! I will remind you tomorrow at 9:00 AM."
        ]
    }

    private static var reminderList: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-list-1", type: EmbedType.reminderList.rawValue, appId: "reminder", skillId: "set-reminder", data: reminderDefaultData)
        return skill(id: "reminder-list-reminders", label: "List", primary: embed)
    }

    private static var reminderCancel: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-cancel-1", type: EmbedType.reminderCancel.rawValue, appId: "reminder", skillId: "set-reminder", data: reminderDefaultData)
        return skill(id: "reminder-cancel-reminder", label: "Cancel", primary: embed)
    }

    private static var sheet: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-sheet-1",
            type: EmbedType.sheetsSheet.rawValue,
            appId: "sheets",
            data: [
                "title": "Team Directory", "row_count": 5, "col_count": 4,
                "table": "| Name | Role | Department | Start Date |\n|------|------|------------|------------|\n| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 |\n| Bob Smith | Product Manager | Product | 2022-06-01 |\n| Carol Williams | Designer | Design | 2024-03-10 |\n| David Brown | DevOps Lead | Engineering | 2021-11-20 |\n| Eva Martinez | QA Engineer | Engineering | 2023-08-05 |"
            ]
        )
        return skill(id: "sheets-sheet", label: "Sheet", primary: embed)
    }

    private static var sheetWide: DevEmbedPreviewSkill {
        let table = """
        | Region | Product | Q1 | Q2 | Q3 | Q4 | Total | Growth |
        |--------|---------|----|----|----|----|-------|--------|
        | North | Widget A | 12400 | 15800 | 18200 | 21500 | 67900 | +14% |
        | North | Widget B | 8900 | 9400 | 11200 | 13600 | 43100 | +18% |
        | South | Widget A | 9200 | 10500 | 12800 | 15400 | 47900 | +22% |
        | South | Widget B | 6700 | 7200 | 8900 | 10100 | 32900 | +12% |
        | East | Widget A | 14200 | 16700 | 19400 | 23100 | 73400 | +8% |
        | East | Widget B | 10400 | 11800 | 13200 | 15900 | 51300 | +16% |
        | West | Widget A | 11600 | 13200 | 15700 | 18900 | 59400 | +20% |
        | West | Widget B | 7800 | 8600 | 10200 | 12400 | 39000 | +11% |
        """
        let embed = record(id: "preview-sheet-large", type: EmbedType.sheetsSheet.rawValue, appId: "sheets",
                           data: ["title": "Sales Report Q4 2025", "row_count": 150, "col_count": 8, "table": table])
        return skill(id: "sheets-sheet-wide", label: "Sheet", primary: embed)
    }

    private static var sheetFullscreen: DevEmbedPreviewSkill {
        let table = """
        | Name | Role | Department | Start Date | Location | Salary |
        |------|------|------------|------------|----------|--------|
        | Alice Johnson | Senior Engineer | Engineering | 2023-01-15 | Munich | €85,000 |
        | Bob Smith | Product Manager | Product | 2022-06-01 | Berlin | €92,000 |
        | Carol Williams | Lead Designer | Design | 2024-03-10 | Munich | €78,000 |
        | David Brown | DevOps Lead | Engineering | 2021-11-20 | Remote | €88,000 |
        | Eva Martinez | QA Engineer | Engineering | 2023-08-05 | Barcelona | €72,000 |
        | Frank Lee | Frontend Developer | Engineering | 2024-01-08 | Munich | €76,000 |
        | Grace Kim | Data Analyst | Analytics | 2023-05-22 | Berlin | €68,000 |
        | Henry Davis | Backend Developer | Engineering | 2022-09-15 | Munich | €82,000 |
        """
        let embed = record(id: "preview-sheet-fullscreen-1",
                           type: EmbedType.sheetsSheet.rawValue, appId: "sheets",
                           data: ["title": "Team Directory", "table": table,
                                  "row_count": 8, "col_count": 6])
        return skill(id: "sheets-sheet-fullscreen", label: "Sheet", primary: embed)
    }

    private static var shoppingProduct: DevEmbedPreviewSkill {
        let embed = record(id: "preview-shopping-result-1", type: EmbedType.shoppingProduct.rawValue,
                           appId: "shopping", data: shoppingProductData)
        return skill(id: "shopping-product", label: "Product", primary: embed)
    }

    private static var shoppingProductData: [String: Any] {
        ["product_id": "rewe-12345", "title": "Bio Vollmilch-Joghurt Naturell",
         "brand": "Weihenstephan", "price_cents": 139, "price_eur": "1,39 €",
         "was_price_cents": 179, "grammage": "500g (0,28 €/100g)",
         "image_url": "", "rating": 4.6, "reviews": 832, "prime": false,
         "attributes": ["is_organic": true, "is_vegetarian": true]]
    }

    private static var shoppingProductFullscreen: DevEmbedPreviewSkill {
        var data = shoppingProductData
        data["purchase_url"] = "https://shop.rewe.de/p/weihenstephan-bio-joghurt/12345"
        data["category_path"] = "Molkereiprodukte > Joghurt"
        data["delivery"] = ["Lieferung heute"]
        data["bought_last_month"] = "500+ mal im letzten Monat gekauft"
        data["provider"] = "REWE"
        data["attributes"] = ["is_organic": true, "is_vegetarian": true, "is_regional": true]
        let embed = record(id: "preview-shopping-result-fs-1", type: EmbedType.shoppingProduct.rawValue,
                           appId: "shopping", data: data)
        return skill(id: "shopping-product-fullscreen", label: "Product", primary: embed)
    }

    private static var shoppingPreviewResults: [[String: Any]] {
        [
            ["product_id": "rewe-12345", "title": "Bio Vollmilch-Joghurt Naturell",
             "brand": "Weihenstephan", "price_cents": 139, "price_eur": "1,39 €",
             "grammage": "500g (0,28 €/100g)", "image_url": "",
             "purchase_url": "https://shop.rewe.de/p/weihenstephan-bio-joghurt/12345",
             "attributes": ["is_organic": true]],
            ["product_id": "rewe-12346", "title": "Demeter Bio-Joghurt mild",
             "brand": "Andechser Natur", "price_cents": 249, "price_eur": "2,49 €",
             "grammage": "500g (0,50 €/100g)", "image_url": "",
             "purchase_url": "https://shop.rewe.de/p/andechser-demeter-joghurt/12346",
             "attributes": ["is_organic": true, "is_vegetarian": true]],
            ["product_id": "rewe-12347", "title": "Griechischer Joghurt 10% Fett",
             "brand": "REWE Bio", "price_cents": 189, "price_eur": "1,89 €",
             "grammage": "400g (0,47 €/100g)", "image_url": "",
             "purchase_url": "https://shop.rewe.de/p/rewe-bio-griechischer-joghurt/12347",
             "attributes": ["is_organic": true, "is_vegetarian": true]]
        ]
    }

    private static var shoppingFullscreenResults: [[String: Any]] {
        shoppingPreviewResults + [
            ["product_id": "rewe-12348", "title": "Skyr Natur 0,2% Fett",
             "brand": "REWE Beste Wahl", "price_cents": 99, "price_eur": "0,99 €",
             "grammage": "450g (0,22 €/100g)", "image_url": "",
             "purchase_url": "https://shop.rewe.de/p/rewe-skyr-natur/12348",
             "attributes": ["is_vegetarian": true]]
        ]
    }

    private static var shoppingSearch: DevEmbedPreviewSkill {
        domainSearch(id: "preview-shopping-search-1", skillID: "shopping-search-products",
                     label: "Search", type: .shoppingSearch, childType: .shoppingProduct,
                     appID: "shopping", action: "search_products",
                     query: "bio joghurt", provider: "REWE", results: shoppingPreviewResults)
    }

    private static var shoppingSearchFullscreen: DevEmbedPreviewSkill {
        domainSearch(id: "preview-shopping-search-fs", skillID: "shopping-search-fullscreen",
                     label: "Search", type: .shoppingSearch, childType: .shoppingProduct,
                     appID: "shopping", action: "search_products",
                     query: "bio joghurt", provider: "REWE", results: shoppingFullscreenResults)
    }

    private static var socialMediaPost: DevEmbedPreviewSkill {
        let embed = record(id: "preview-social-media-post-1", type: EmbedType.socialMediaPost.rawValue, appId: "social_media", data: [
            "platform": "bluesky", "page": "search", "title": "Small cafe bar layout notes",
            "body": "A compact espresso bar can still feel calm: warm task lighting, a narrow handoff shelf, and one visible daily special board made this setup feel polished without clutter.",
            "author": "sample.cafe", "author_display_name": "Sample Cafe Journal",
            "published_at": "2026-05-24T10:30:00Z", "like_count": 184, "reply_count": 12, "repost_count": 27,
            "url": "https://bsky.app/profile/sample.cafe/post/example-1"
        ])
        return skill(id: "social-media-post", label: "Post", primary: embed)
    }

    private static var socialMediaGetPosts: DevEmbedPreviewSkill {
        let child = socialMediaPost.primaryEmbed
        let parent = appSkill(id: "preview-social-media-get-posts-1", type: EmbedType.socialMediaGetPosts.rawValue, appId: "social_media", skillId: "get-posts", data: ["query": "@samplegarden.example", "provider": "bluesky_public", "result_count": 1], embedIds: child.id)
        return skill(id: "social-media-get-posts", label: "Get Posts", primary: parent, children: [child])
    }

    private static var socialMediaSearch: DevEmbedPreviewSkill {
        let child = socialMediaPost.primaryEmbed
        let parent = appSkill(id: "preview-social-media-search-1", type: EmbedType.socialMediaSearch.rawValue, appId: "social_media", skillId: "search", data: ["query": "Indie coffee setup inspiration", "provider": "bluesky_public", "result_count": 1], embedIds: child.id)
        return skill(id: "social-media-search", label: "Search", primary: parent, children: [child])
    }

    private static var tasksTask: DevEmbedPreviewSkill {
        let embed = record(id: "preview-task-child", type: EmbedType.tasksTask.rawValue, appId: "tasks",
                           data: ["task_id": "task-garden-1", "short_id": "T-104",
                                  "title": "Buy starter soil and basil seeds",
                                  "description": "Pick up seed trays, starter soil, and basil seeds before Saturday.",
                                  "status": "todo", "assignee": "user"])
        return skill(id: "tasks-task", label: "Task", primary: embed)
    }

    private static var tasksCreate: DevEmbedPreviewSkill {
        let results: [[String: Any]] = [
            ["task_id": "task-garden-1", "short_id": "T-104",
             "title": "Buy starter soil and basil seeds",
             "description": "Pick up seed trays, starter soil, and basil seeds before Saturday.",
             "status": "todo", "assignee": "user"],
            ["task_id": "task-garden-2", "short_id": "T-105",
             "title": "Clear the balcony planter boxes",
             "description": "Remove old roots and rinse the boxes so the spring planting can start.",
             "status": "in_progress", "assignee": "user"]
        ]
        let parent = appSkill(id: "preview-task-create", type: EmbedType.tasksCreate.rawValue,
                              appId: "tasks", skillId: "create",
                              data: ["instruction": "Create a practical checklist for starting a small balcony herb garden",
                                     "preview_results": results, "result_count": 2])
        return skill(id: "tasks-create", label: "Create", primary: parent)
    }

    private static var tasksSearch: DevEmbedPreviewSkill {
        let results: [[String: Any]] = [
            ["task_id": "task-packing-1", "short_id": "T-221",
             "title": "Pack passport and travel documents",
             "description": "Put passport, train ticket, and hotel confirmation in the front backpack pocket.",
             "status": "todo", "assignee": "user"],
            ["task_id": "task-packing-2", "short_id": "T-222",
             "title": "Charge camera batteries",
             "description": "Charge both batteries and put the charger in the electronics pouch.",
             "status": "done", "assignee": "user"]
        ]
        let parent = appSkill(id: "preview-task-search", type: EmbedType.tasksSearch.rawValue,
                              appId: "tasks", skillId: "search",
                              data: ["query": "packing list tasks", "preview_results": results,
                                     "result_count": 2])
        return skill(id: "tasks-search", label: "Search", primary: parent)
    }

    private static var tasksCreateFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-task-create-fullscreen", type: EmbedType.tasksCreate.rawValue,
                              appId: "tasks", skillId: "create",
                              data: ["title": "Created tasks", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "tasks-create-fullscreen", label: "Create", primary: parent)
    }

    private static var tasksSearchFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-task-search-fullscreen", type: EmbedType.tasksSearch.rawValue,
                              appId: "tasks", skillId: "search",
                              data: ["title": "Search tasks", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "tasks-search-fullscreen", label: "Search", primary: parent)
    }

    private static var video: DevEmbedPreviewSkill {
        // Match VideoEmbedPreview.preview.ts so card chrome and media pixels
        // compare against the rendered /dev/preview registry entry.
        let embed = record(id: "preview-videos-video-1", type: EmbedType.videosVideo.rawValue, appId: "videos", data: [
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "video_id": "dQw4w9WgXcQ",
            "title": "Understanding Svelte 5 Runes — Complete Tutorial",
            "channel": "Svelte Society",
            "duration_seconds": 1028,
            "duration_formatted": "17:08",
            "published_at": "2025-11-15T10:00:00Z"
        ])
        return skill(id: "videos-video", label: "Video", primary: embed)
    }

    private static var videosSearch: DevEmbedPreviewSkill {
        let rows: [[String: Any]] = [
            ["title": "Svelte 5 Runes — Complete Beginner Guide",
             "url": "https://www.youtube.com/watch?v=example1", "thumbnail_url": "",
             "channel_name": "Svelte Society", "duration_formatted": "17:08",
             "view_count": 245000, "published_at": "2025-11-15T10:00:00Z"],
            ["title": "Migrating from Svelte 4 to 5 — Step by Step",
             "url": "https://www.youtube.com/watch?v=example2", "thumbnail_url": "",
             "channel_name": "Frontend Masters", "duration_formatted": "32:15",
             "view_count": 128000, "published_at": "2025-10-20T14:00:00Z"],
            ["title": "Building a Full App with SvelteKit 2",
             "url": "https://www.youtube.com/watch?v=example3", "thumbnail_url": "",
             "channel_name": "Fireship", "duration_formatted": "12:42",
             "view_count": 890000, "published_at": "2025-09-05T08:00:00Z"]
        ]
        let children = rows.enumerated().map { index, row in
            record(id: "preview-videos-search-result-\(index + 1)",
                   type: EmbedType.videosVideo.rawValue, appId: "videos",
                   data: row, parentEmbedId: "preview-videos-search-1")
        }
        let parent = appSkill(id: "preview-videos-search-1", type: EmbedType.videosSearch.rawValue,
                              appId: "videos", skillId: "search",
                              data: ["query": "svelte 5 tutorial", "provider": "Brave Search",
                                     "results": rows, "result_count": 3],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "videos-search", label: "Search", primary: parent, children: children)
    }

    private static var videoTranscript: DevEmbedPreviewSkill {
        let parentID = "preview-video-transcript-1"
        let child = record(
            id: "preview-video-transcript-result-1",
            type: EmbedType.videosVideo.rawValue,
            appId: "videos",
            skillId: "transcript_result",
            data: [
                "type": "transcript_result",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "Understanding Svelte 5 Runes",
                "transcript": "Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system. The $state rune replaces let declarations for reactive variables. The $derived rune replaces $: for computed values. And the $effect rune replaces $: for side effects.",
                "channel_name": "Svelte Society",
                "duration_formatted": "17:08"
            ],
            parentEmbedId: parentID
        )
        let embed = appSkill(
            id: parentID,
            type: EmbedType.videosTranscript.rawValue,
            appId: "videos",
            skillId: "get_transcript",
            data: [
                "result_count": 1,
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "preview_results": [[
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "title": "Understanding Svelte 5 Runes",
                    "transcript": "Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system. The $state rune replaces let declarations for reactive variables. The $derived rune replaces $: for computed values. And the $effect rune replaces $: for side effects.",
                    "channel_name": "Svelte Society", "duration_formatted": "17:08"
                ]]
            ],
            embedIds: child.id
        )
        return skill(id: "videos-get-transcript", label: "Get Transcript", primary: embed, children: [child])
    }

    private static var videoTranscriptFullscreen: DevEmbedPreviewSkill {
        let parentID = "preview-video-transcript-fs"
        let transcript = """
        Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system that replaces the old reactive declarations.

        The $state rune replaces let declarations for reactive variables. When you declare a variable with $state, Svelte automatically tracks all assignments to it.

        The $derived rune replaces $: for computed values. It takes an expression and re-evaluates it whenever its dependencies change.

        And the $effect rune replaces $: for side effects. It runs whenever any of its reactive dependencies change, similar to useEffect in React.
        """
        let result: [String: Any] = [
            "type": "transcript_result", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "Understanding Svelte 5 Runes", "transcript": transcript,
            "channel_name": "Svelte Society", "duration_formatted": "17:08"
        ]
        let child = record(id: "preview-video-transcript-fs-result", type: EmbedType.videosVideo.rawValue,
                           appId: "videos", skillId: "transcript_result", data: result,
                           parentEmbedId: parentID)
        let parent = appSkill(id: parentID, type: EmbedType.videosTranscript.rawValue,
                              appId: "videos", skillId: "get_transcript",
                              data: ["url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                                     "results": [result], "result_count": 1],
                              embedIds: child.id)
        return skill(id: "videos-get-transcript-fullscreen", label: "Get Transcript",
                     primary: parent, children: [child])
    }

    private static var videoGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-video-generate-1", type: EmbedType.videosGenerate.rawValue,
                             appId: "videos", skillId: "generate", data: ["prompt": ""],
                             status: .processing)
        return skill(id: "videos-generate", label: "Generate", primary: embed)
    }

    private static var videoCreate: DevEmbedPreviewSkill {
        var data = videoCreateData
        data["video_url"] = "/dev-fixtures/video-creation/product-launch.mp4"
        data["thumbnail_url"] = ""
        let embed = appSkill(id: "preview-video-create-1", type: EmbedType.videosCreate.rawValue,
                             appId: "videos", skillId: "create", data: data)
        return skill(id: "videos-create", label: "Create", primary: embed)
    }

    private static var videoCreateFullscreen: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-video-create-fullscreen-1",
                             type: EmbedType.videosCreate.rawValue, appId: "videos",
                             skillId: "create", data: videoCreateData)
        return skill(id: "videos-create-fullscreen", label: "Create", primary: embed)
    }

    private static var videoCreateData: [String: Any] {
        [
            "filename": "ProductLaunch.tsx", "status": "finished",
            "remotion_source": videoCreateSource,
            "current_source_version": 1, "active_render_version": 1,
            "duration_in_frames": 240, "fps": 30,
            "width": 1920, "height": 1080,
            "duration_seconds": 8,
            "render_metadata": ["runtime_seconds": 12, "charged_credits": 0]
        ]
    }

    private static let videoCreateSource = """
    import { Sequence, AbsoluteFill, Audio } from "remotion";

    export const ProductLaunch: React.FC = () => {
      return (
        <AbsoluteFill>
          <Sequence from={0} durationInFrames={240}>
            <GradientBg />
          </Sequence>
          <Sequence from={0} durationInFrames={60}>
            <TitleCard text="Introducing OpenMates" />
          </Sequence>
          <Sequence from={60} durationInFrames={60}>
            <FeatureList />
          </Sequence>
          <Sequence from={120} durationInFrames={60}>
            <ClientEncryptionDemo />
          </Sequence>
          <Sequence from={180} durationInFrames={60}>
            <CallToAction />
          </Sequence>
          <Audio src="/static/music/background.mp3" />
        </AbsoluteFill>
      );
    };

    export const Root = () => (
      <Composition
        id="product-launch"
        component={ProductLaunch}
        durationInFrames={240}
        fps={30}
        width={1920}
        height={1080}
      />
    );
    """

    private static var weatherDay: DevEmbedPreviewSkill {
        let embed = record(id: "preview-weather-day-1", type: EmbedType.weatherDay.rawValue, appId: "weather", data: [
            "date": "2026-06-03", "location_name": "Berlin", "provider": "Deutscher Wetterdienst (DWD)",
            "condition": "rain", "icon": "rain", "temperature_min_c": 14, "temperature_max_c": 19,
            "precipitation_total_mm": 5.8, "precipitation_probability_max_pct": 67, "rain_hours": 13,
            "wind_speed_max_kmh": 24, "cloud_cover_avg_pct": 86, "relative_humidity_avg_pct": 72,
            "hourly": [
                ["time": "06:00", "condition": "cloudy", "icon": "cloudy", "temperature_c": 15, "precipitation_mm": 0.2, "precipitation_probability_pct": 31, "wind_speed_kmh": 12],
                ["time": "07:00", "condition": "rain", "icon": "rain", "temperature_c": 16, "precipitation_mm": 0.4, "precipitation_probability_pct": 48, "wind_speed_kmh": 14],
                ["time": "08:00", "condition": "rain", "icon": "rain", "temperature_c": 16, "precipitation_mm": 0.8, "precipitation_probability_pct": 67, "wind_speed_kmh": 18],
                ["time": "09:00", "condition": "thunderstorm", "icon": "thunderstorms-day-rain", "temperature_c": 17, "precipitation_mm": 1.2, "precipitation_probability_pct": 74, "wind_speed_kmh": 24],
                ["time": "10:00", "condition": "cloudy", "icon": "cloudy", "temperature_c": 18, "precipitation_mm": 0.1, "precipitation_probability_pct": 28, "wind_speed_kmh": 16]
            ]
        ])
        return skill(id: "weather-day", label: "Day", primary: embed)
    }

    private static var weatherForecast: DevEmbedPreviewSkill {
        let previewResults: [[String: Any]] = [
            ["date": "2026-06-02", "condition": "dry", "icon": "clear-day", "temperature_min_c": 15, "temperature_max_c": 26, "precipitation_total_mm": 0, "precipitation_probability_max_pct": 4, "rain_hours": 0],
            ["date": "2026-06-03", "condition": "rain", "icon": "rain", "temperature_min_c": 14, "temperature_max_c": 19, "precipitation_total_mm": 5.8, "precipitation_probability_max_pct": 67, "rain_hours": 13],
            ["date": "2026-06-04", "condition": "cloudy", "icon": "cloudy", "temperature_min_c": 13, "temperature_max_c": 21, "precipitation_total_mm": 4.9, "precipitation_probability_max_pct": 37, "rain_hours": 9],
            ["date": "2026-06-05", "condition": "thunderstorm", "icon": "thunderstorms-day-rain", "temperature_min_c": 16, "temperature_max_c": 22, "precipitation_total_mm": 12.4, "precipitation_probability_max_pct": 82, "rain_hours": 6]
        ]
        let results: [[String: Any]] = [
            ["date": "2026-06-02", "location_name": "Berlin", "provider": "Deutscher Wetterdienst (DWD)", "condition": "dry", "icon": "clear-day", "temperature_min_c": 15, "temperature_max_c": 26, "precipitation_total_mm": 0, "precipitation_probability_max_pct": 4, "rain_hours": 0],
            ["date": "2026-06-03", "location_name": "Berlin", "provider": "Deutscher Wetterdienst (DWD)", "condition": "rain", "icon": "rain", "temperature_min_c": 14, "temperature_max_c": 19, "precipitation_total_mm": 5.8, "precipitation_probability_max_pct": 67, "rain_hours": 13],
            ["date": "2026-06-04", "location_name": "Berlin", "provider": "Deutscher Wetterdienst (DWD)", "condition": "snow", "icon": "snow", "temperature_min_c": -2, "temperature_max_c": 3, "precipitation_total_mm": 4.1, "precipitation_probability_max_pct": 58, "rain_hours": 7]
        ]
        let children = results.enumerated().map { index, day in
            record(id: "preview-weather-forecast-day-\(index + 1)", type: EmbedType.weatherDay.rawValue, appId: "weather", data: day, parentEmbedId: "preview-weather-forecast-1")
        }
        let parent = appSkill(id: "preview-weather-forecast-1", type: EmbedType.weatherForecast.rawValue, appId: "weather", skillId: "forecast", data: [
            "query": "Berlin weather forecast", "provider": "Deutscher Wetterdienst (DWD)",
            "location_name": "Berlin", "location": ["name": "Berlin"],
            "preview_results": previewResults, "results": results
        ], embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "weather-forecast", label: "Forecast", primary: parent, children: children)
    }

    private static var weatherRainRadar: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-weather-radar-1", type: EmbedType.weatherRainRadar.rawValue, appId: "weather", skillId: "rain_radar", data: ["location_name": "Rostock", "summary": "Heavy rain moving east", "status": "finished"])
        return skill(id: "weather-rain-radar", label: "Rain Radar", primary: embed)
    }

    private static var workflowsWorkflow: DevEmbedPreviewSkill {
        let embed = record(id: "preview-workflow-child", type: EmbedType.workflowsWorkflow.rawValue,
                           appId: "workflows", data: [
                            "workflow_id": "workflow-garden-1", "title": "Weekly balcony garden reminder",
                            "description": "Every Saturday morning, remind me to water herbs and note which plants need trimming.",
                            "status": "ready", "enabled": true,
                            "trigger_summary": "Manual or weekly Saturday reminder"])
        return skill(id: "workflows-workflow", label: "Workflow", primary: embed)
    }

    private static var workflowsCreate: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-workflow-create", type: EmbedType.workflowsCreateOrModify.rawValue,
                              appId: "workflows", skillId: "create-or-modify",
                              data: ["instruction": "Create a simple manual workflow for a weekly balcony garden check-in",
                                     "preview_results": [[
                                        "workflow_id": "workflow-garden-1",
                                        "title": "Weekly balcony garden reminder",
                                        "description": "Every Saturday morning, remind me to water herbs and note which plants need trimming.",
                                        "status": "ready", "enabled": true,
                                        "trigger_summary": "Manual or weekly Saturday reminder"
                                     ]], "result_count": 1])
        return skill(id: "workflows-create", label: "Create or Modify", primary: parent)
    }

    private static var workflowsSearch: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-workflow-search", type: EmbedType.workflowsSearch.rawValue,
                              appId: "workflows", skillId: "search",
                              data: ["query": "travel packing workflows",
                                     "preview_results": [
                                        ["workflow_id": "workflow-packing-1",
                                         "title": "Trip packing reminder workflow",
                                         "description": "A manual workflow that creates a short packing checklist and reminder before each trip.",
                                         "status": "ready", "enabled": true, "trigger_summary": "Manual trigger"],
                                        ["workflow_id": "workflow-packing-2",
                                         "title": "Departure day weather check",
                                         "description": "Check the forecast on the morning of departure and remind me about rain gear if needed.",
                                         "status": "ready", "enabled": false, "trigger_summary": "Manual trigger"]
                                     ], "result_count": 2])
        return skill(id: "workflows-search", label: "Search", primary: parent)
    }

    private static var workflowsCreateFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-workflow-create-fullscreen",
                              type: EmbedType.workflowsCreateOrModify.rawValue,
                              appId: "workflows", skillId: "create-or-modify",
                              data: ["title": "Created workflow", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "workflows-create-fullscreen", label: "Create", primary: parent)
    }

    private static var workflowsSearchFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-workflow-search-fullscreen",
                              type: EmbedType.workflowsSearch.rawValue,
                              appId: "workflows", skillId: "search",
                              data: ["title": "Search workflows", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "workflows-search-fullscreen", label: "Search", primary: parent)
    }

    private static var financeCheckAccounts: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-finance-check-accounts-1",
            type: EmbedType.financeCheckAccounts.rawValue,
            appId: "finance",
            skillId: "check_accounts",
            data: [
                "summary": "Finance overview for 2 accounts and 5 transactions: income 8000, expenses 2291.25.",
                "provider": "Revolut Business",
                "period": "monthly",
                "account_count": 2,
                "transaction_count": 5,
                "overview": [
                    "accounts": [
                        ["account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "display_label": "Operating EUR", "currency": "EUR", "balance": 8450.25, "balance_as_of": "2026-07-15"],
                        ["account_ref": "acct-savings-eur", "source_ref": "revolut_business:connected-account", "display_label": "Savings EUR", "currency": "EUR", "balance": 12500, "balance_as_of": "2026-07-15"]
                    ],
                    "transactions": [
                        ["transaction_ref": "revolut_business:tx-001", "account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-05-05", "amount": 4200, "currency": "EUR", "direction": "income", "category": "revenue", "counterparty_placeholder": "[PAYER_REVENUE_001]", "state": "completed"],
                        ["transaction_ref": "revolut_business:tx-002", "account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-05-08", "amount": -760.8, "currency": "EUR", "direction": "expense", "category": "software", "counterparty_placeholder": "[MERCHANT_SOFTWARE_001]", "state": "completed"],
                        ["transaction_ref": "revolut_business:tx-003", "account_ref": "acct-savings-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-06-03", "amount": 3800, "currency": "EUR", "direction": "income", "category": "revenue", "counterparty_placeholder": "[PAYER_REVENUE_002]", "state": "completed"],
                        ["transaction_ref": "revolut_business:tx-004", "account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-06-12", "amount": -1180.45, "currency": "EUR", "direction": "expense", "category": "travel", "counterparty_placeholder": "[MERCHANT_TRAVEL_001]", "state": "completed"],
                        ["transaction_ref": "revolut_business:tx-005", "account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-07-02", "amount": -350, "currency": "EUR", "direction": "expense", "category": "meals", "counterparty_placeholder": "[MERCHANT_MEALS_001]", "state": "completed"]
                    ],
                    "summaries": [
                        "period": "monthly", "income_total": 8000, "expense_total": 2291.25, "net_total": 5708.75,
                        "by_category": [
                            "revenue": ["income": 8000, "expense": 0, "net": 8000],
                            "software": ["income": 0, "expense": 760.8, "net": -760.8],
                            "travel": ["income": 0, "expense": 1180.45, "net": -1180.45],
                            "meals": ["income": 0, "expense": 350, "net": -350]
                        ],
                        "time_series": [
                            ["bucket": "2026-05", "income": 4200, "expense": 760.8, "net": 3439.2, "transaction_count": 2],
                            ["bucket": "2026-06", "income": 3800, "expense": 1180.45, "net": 2619.55, "transaction_count": 2],
                            ["bucket": "2026-07", "income": 0, "expense": 350, "net": -350, "transaction_count": 1]
                        ],
                        "filters_applied": [:] as [String: String]
                    ],
                    "filter_options": [
                        "accounts": ["acct-main-eur", "acct-savings-eur"],
                        "sources": ["revolut_business:connected-account"],
                        "categories": ["meals", "revenue", "software", "travel"],
                        "directions": ["expense", "income"],
                        "states": ["completed"],
                        "placeholders": ["[MERCHANT_MEALS_001]", "[MERCHANT_SOFTWARE_001]", "[MERCHANT_TRAVEL_001]", "[PAYER_REVENUE_001]", "[PAYER_REVENUE_002]"]
                    ]
                ] as [String: Any]
            ]
        )
        return skill(id: "finance-check-accounts", label: "Check accounts", primary: embed)
    }

    // MARK: - Builders

    private static func domainSearch(
        id: String,
        skillID: String,
        label: String,
        type: EmbedType,
        childType: EmbedType,
        appID: String,
        action: String,
        query: String,
        provider: String,
        results: [[String: Any]]
    ) -> DevEmbedPreviewSkill {
        let children = results.enumerated().map { index, source in
            let childID = "\(id)-result-\(index + 1)"
            var data = source
            data["embed_id"] = childID
            return record(id: childID, type: childType.rawValue, appId: appID,
                          data: data, parentEmbedId: id)
        }
        let rows = children.compactMap { child -> [String: Any]? in
            child.rawData?.mapValues(\.value)
        }
        let parent = appSkill(id: id, type: type.rawValue, appId: appID, skillId: action,
                              data: ["query": query, "provider": provider, "results": rows,
                                     "result_count": rows.count],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: skillID, label: label, primary: parent, children: children)
    }

    // These surface overrides are expanded below as their canonical payloads
    // are aligned. Keeping the gallery buildable also lets focused UI tests run.

    private static func skill(
        id: String,
        label: String,
        primary: EmbedRecord,
        children: [EmbedRecord] = []
    ) -> DevEmbedPreviewSkill {
        DevEmbedPreviewSkill(
            id: id,
            label: label,
            primaryEmbed: primary,
            childEmbeds: children,
            allRecords: ([primary] + children).reduce(into: [:]) { records, embed in
                records[embed.id] = embed
            }
        )
    }

    private static func appSkill(
        id: String,
        type: String,
        appId: String,
        skillId: String,
        data: [String: Any],
        status: EmbedStatus = .finished,
        embedIds: String? = nil
    ) -> EmbedRecord {
        var raw = data
        raw["type"] = "app_skill_use"
        raw["app_id"] = appId
        raw["skill_id"] = skillId
        return record(id: id, type: type, status: status, appId: appId, skillId: skillId, data: raw, embedIds: embedIds)
    }

    private static func record(
        id: String,
        type: String,
        status: EmbedStatus = .finished,
        appId: String?,
        skillId: String? = nil,
        data: [String: Any],
        parentEmbedId: String? = nil,
        embedIds: String? = nil,
        versionNumber: Int? = nil,
        versionHistory: [EmbedVersionMetadata] = [],
        versionHistoryReadonly: Bool = false
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
            versionNumber: versionNumber,
            versionHistory: versionHistory,
            versionHistoryReadonly: versionHistoryReadonly,
            createdAt: "2026-03-15T08:30:00Z"
        )
    }

    private static func imageSearchResults(parentId: String) -> [EmbedRecord] {
        [
            imageResultRecord(id: "preview-images-search-result-1", title: "Golden Gate Bridge at dusk", thumbnail: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200", image: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29", parentId: parentId),
            imageResultRecord(id: "preview-images-search-result-2", title: "Aerial view of Golden Gate", thumbnail: "https://images.unsplash.com/photo-1506146332389-18140dc7b2fb?w=200", image: "https://images.unsplash.com/photo-1506146332389-18140dc7b2fb", parentId: parentId),
            imageResultRecord(id: "preview-images-search-result-3", title: "Golden Gate Bridge towers in fog", thumbnail: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=200", image: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64", parentId: parentId)
        ]
    }

    private static func imageResultRecord(id: String, title: String, thumbnail: String, image: String, parentId: String?) -> EmbedRecord {
        return record(
            id: id,
            type: EmbedType.imagesImageResult.rawValue,
            appId: "images",
            data: [
                "title": title,
                "source": "unsplash.com",
                "source_domain": "unsplash.com",
                "thumbnail_url": thumbnail,
                "image_url": image,
                "source_page_url": "https://unsplash.com/photos/Cs99I6PYLlk"
            ],
            parentEmbedId: parentId
        )
    }

    private static func travelConnectionRecord(
        id: String,
        price: String,
        destination: String,
        departure: String,
        arrival: String,
        duration: String,
        stops: Int,
        carrierCodes: [String],
        parentId: String?
    ) -> EmbedRecord {
        let destinationCode = destination.contains("Gatwick") ? "LGW" : "LHR"
        let destinationLatitude = destination.contains("Gatwick") ? 51.1537 : 51.4700
        let destinationLongitude = destination.contains("Gatwick") ? -0.1821 : -0.4543
        return record(
            id: id,
            type: EmbedType.travelConnection.rawValue,
            appId: "travel",
            data: [
                "price": price,
                "total_price": price,
                "currency": "EUR",
                "transport_method": "airplane",
                "trip_type": "one_way",
                "origin": "Munich (MUC)",
                "destination": destination,
                "origin_country_code": "DE",
                "destination_country_code": "GB",
                "departure": departure,
                "arrival": arrival,
                "duration": duration,
                "stops": stops,
                "carrier_codes": carrierCodes,
                "carriers": carrierCodes,
                "booking_url": "https://www.google.com/travel/flights",
                "booking_provider": "Google Flights",
                "legs": [[
                    "leg_index": 0,
                    "origin": "Munich (MUC)",
                    "destination": destination,
                    "departure": departure,
                    "arrival": arrival,
                    "duration": duration,
                    "stops": stops,
                    "segments": [[
                        "carrier": carrierCodes.first ?? "LH",
                        "carrier_code": carrierCodes.first ?? "LH",
                        "number": "\(carrierCodes.first ?? "LH") 123",
                        "departure_station": "MUC",
                        "departure_time": departure,
                        "departure_country_code": "DE",
                        "departure_is_daytime": false,
                        "departure_latitude": 48.3538,
                        "departure_longitude": 11.7861,
                        "arrival_station": destinationCode,
                        "arrival_time": arrival,
                        "arrival_country_code": "GB",
                        "arrival_is_daytime": false,
                        "arrival_latitude": destinationLatitude,
                        "arrival_longitude": destinationLongitude,
                        "duration": duration,
                        "travel_class": "Economy"
                    ]]
                ]]
            ],
            parentEmbedId: parentId
        )
    }

    private static func travelStayRecord(
        id: String,
        name: String,
        hotelClass: Int,
        rating: Double,
        reviews: Int,
        ratePerNight: String,
        totalRate: String,
        parentId: String?,
        canonicalRates: Bool = false
    ) -> EmbedRecord {
        record(
            id: id,
            type: EmbedType.travelStay.rawValue,
            appId: "travel",
            data: [
                "name": name,
                "hotel_class": hotelClass,
                "overall_rating": rating,
                "rating": rating,
                "reviews": reviews,
                "currency": "EUR",
                "rate_per_night": ratePerNight,
                "price_per_night": Double(ratePerNight) ?? 0,
                "total_rate": totalRate,
                "link": "https://www.google.com/travel/hotels",
                "thumbnail": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=1200",
                "gps_coordinates": [
                    "latitude": 41.3874,
                    "longitude": 2.1686
                ],
                "amenities": ["Free Wi-Fi", "Breakfast included", "Spa", "Fitness center"],
                "free_cancellation": true,
                "eco_certified": true
            ].merging(canonicalRates ? [
                "extracted_rate_per_night": Double(ratePerNight) ?? 0,
                "extracted_total_rate": Double(totalRate) ?? 0
            ] : [:], uniquingKeysWith: { _, canonical in canonical }),
            parentEmbedId: parentId
        )
    }

    private static func eventResults(parentId: String) -> [EmbedRecord] {
        [
            eventRecord(
                id: "preview-events-result-1",
                title: "AI & Machine Learning Berlin Meetup – Spring Edition",
                dateStart: "2026-03-15T19:00:00+01:00",
                dateEnd: "2026-03-15T22:00:00+01:00",
                eventType: "PHYSICAL",
                city: "Berlin",
                country: "Germany",
                rsvpCount: 142,
                isPaid: false,
                feeAmount: nil,
                imageURL: nil,
                venueName: "Factory Berlin",
                venueAddress: "Rheinsberger Str. 76-77",
                venueLatitude: 52.5393,
                venueLongitude: 13.4028,
                parentId: parentId,
                description: "Join us for an evening of talks on LLMs, RAG architectures, and production AI."
            ),
            eventRecord(
                id: "preview-events-result-2",
                title: "Web Dev Online: TypeScript Deep Dive",
                dateStart: "2026-03-20T18:00:00Z",
                dateEnd: "2026-03-20T20:00:00Z",
                eventType: "ONLINE",
                city: nil,
                country: nil,
                rsvpCount: 87,
                isPaid: false,
                feeAmount: nil,
                imageURL: nil,
                venueName: nil,
                venueAddress: nil,
                venueLatitude: nil,
                venueLongitude: nil,
                parentId: parentId,
                description: "A live online session covering advanced TypeScript patterns for scalable apps.",
                organizerName: "Web Dev Community"
            ),
            eventRecord(
                id: "preview-events-result-3",
                title: "Product Management Summit – London",
                dateStart: "2026-04-05T09:00:00+01:00",
                dateEnd: "2026-04-06T17:00:00+01:00",
                eventType: "PHYSICAL",
                city: "London",
                country: "United Kingdom",
                rsvpCount: 320,
                isPaid: true,
                feeAmount: 25,
                imageURL: nil,
                venueName: "The Barbican",
                venueAddress: "Silk St",
                venueLatitude: 51.521,
                venueLongitude: -0.093,
                parentId: parentId,
                description: "Two-day conference covering product strategy, user research, and growth tactics.",
                organizerName: "PM London"
            )
        ]
    }

    private static func eventRecord(
        id: String,
        title: String,
        dateStart: String,
        dateEnd: String,
        eventType: String,
        city: String?,
        country: String?,
        rsvpCount: Int,
        isPaid: Bool,
        feeAmount: Double?,
        imageURL: String?,
        venueName: String?,
        venueAddress: String?,
        venueLatitude: Double?,
        venueLongitude: Double?,
        parentId: String?,
        description: String = "Join us for an evening of talks, creative exchange, and community networking.",
        organizerName: String = "AI Berlin Community"
    ) -> EmbedRecord {
        var data: [String: Any] = [
            "type": "event_result",
            "provider": "meetup",
            "title": title,
            "description": description,
            "url": "https://www.meetup.com/example-ai-berlin/events/preview",
            "date_start": dateStart,
            "date_end": dateEnd,
            "timezone": "Europe/Berlin",
            "event_type": eventType,
            "organizer_name": organizerName,
            "organizer": ["name": organizerName],
            "rsvp_count": rsvpCount,
            "is_paid": isPaid,
            "app_id": "events",
            "skill_id": "search"
        ]
        if let imageURL { data["image_url"] = imageURL }
        if let venueName {
            var venue: [String: Any] = ["name": venueName]
            if let venueAddress { venue["address"] = venueAddress }
            if let city { venue["city"] = city }
            if let country { venue["country"] = country }
            if let venueLatitude { venue["lat"] = venueLatitude }
            if let venueLongitude { venue["lon"] = venueLongitude }
            data["venue"] = venue
        }
        if let venueName { data["venue_name"] = venueName }
        if let venueAddress { data["venue_address"] = venueAddress }
        if let venueLatitude { data["venue_lat"] = venueLatitude }
        if let venueLongitude { data["venue_lon"] = venueLongitude }
        if let city { data["venue_city"] = city }
        if let country { data["venue_country"] = country }
        if let feeAmount {
            data["fee_amount"] = feeAmount
            data["fee_currency"] = "GBP"
        }
        return record(
            id: id,
            type: EmbedType.eventsEvent.rawValue,
            appId: "events",
            data: data,
            parentEmbedId: parentId
        )
    }
}
#endif
