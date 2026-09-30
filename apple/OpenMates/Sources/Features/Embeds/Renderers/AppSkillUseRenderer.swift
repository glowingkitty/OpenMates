// App skill use embed renderer — renders parent skill executions and their child
// result previews inside the unified embed shell.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/AppSkillUseRenderer.ts
//          frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/weather/WeatherForecastEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/weather/WeatherForecastEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/finance/FinanceCheckAccountsEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/finance/FinanceCheckAccountsEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/music/MusicGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/math/MathCalculateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/math/MathCalculateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelFlightDetailsEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelFlightDetailsEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/reminder/ReminderEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/reminder/ReminderEmbedFullscreen.svelte
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
//          frontend/packages/ui/src/components/embeds/models3d/Model3DSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/models3d/Model3DSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/models3d/Model3DResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/models3d/Model3DResultEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/models3d/Model3DGenerateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/models3d/Model3DGenerateEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/tasks/TaskCreateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/tasks/TaskSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/tasks/TaskEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/tasks/TaskEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/workflows/WorkflowCreateEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/workflows/WorkflowSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/workflows/WorkflowEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/workflows/WorkflowEmbedFullscreen.svelte
// CSS:     frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-skills/videos-get-transcript/specification.yml
//                specifications/features/app-skills/web-search/specification.yml
//                specifications/features/chats/specification.yml
// Assertions: videos.transcript.surface-parity, web-search.surface-parity,
//             chats.surface.semantic-parity

import Combine
import SwiftUI
#if canImport(MapKit)
import MapKit
#endif

struct AppSkillUseRenderer: View {
    enum SpecializedKind: Equatable {
        case weatherForecast, financeCheckAccounts, musicGenerate, videoGenerate
        case mathCalculate, travelFlight, reminder
    }

    static func specializedKind(appId: String, skillId: String) -> SpecializedKind? {
        switch (appId, skillId) {
        case ("weather", "forecast"): return .weatherForecast
        case ("finance", "check_accounts"): return .financeCheckAccounts
        case ("music", "generate"): return .musicGenerate
        case ("videos", "generate"): return .videoGenerate
        case ("math", "calculate"): return .mathCalculate
        case ("travel", "get_flight"): return .travelFlight
        case ("reminder", "set-reminder"), ("reminder", "list-reminders"),
             ("reminder", "cancel-reminder"): return .reminder
        default: return nil
        }
    }

    let embed: EmbedRecord
    let allEmbedRecords: [String: EmbedRecord]
    let mode: EmbedDisplayMode
    var hasPIIMappings = false
    var piiMappings: [PIIMapping] = []
    var isPIIRevealed = false
    var onTogglePII: () -> Void = {}
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
        case ("videos", "get_transcript"), ("videos", "get-transcript"): return AppStrings.videoGetTranscript
        default:
            return EmbedType(rawValue: embed.type)?.displayName ?? skillId.replacingOccurrences(of: "_", with: " ")
        }
    }

    private var isFitnessSearchSkill: Bool {
        appId == "fitness" && (skillId == "search_locations" || skillId == "search_classes")
    }

    private var isCalendarActionSkill: Bool {
        appId == "calendar" && ["list-calendars", "get-events", "create-event", "update-event", "delete-event"].contains(skillId)
    }

    private var childEmbeds: [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { $0.id < $1.id }
        let preview = previewChildEmbeds
        let hydrated = uniqueEmbeds(explicit + parented)
        if !preview.isEmpty || !hydrated.isEmpty {
            return SearchSkillPreviewModel.mergedRecords(
                parentOrder: embed.childEmbedIds,
                inlineRecords: preview,
                hydratedRecords: hydrated
            )
        }

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

    private var linkedChildEmbeds: [EmbedRecord] {
        Self.linkedChildren(parent: embed, allRecords: allEmbedRecords)
    }

    static func linkedChildren(parent: EmbedRecord, allRecords: [String: EmbedRecord]) -> [EmbedRecord] {
        let explicit = parent.childEmbedIds.compactMap { allRecords[$0] }
        let parented = allRecords.values.filter { $0.parentEmbedId == parent.id }
        var seen = Set<String>()
        return (explicit + parented).filter { seen.insert($0.id).inserted }
    }

    /// Finished authenticated app-skill embeds persist their full result in a
    /// child record and keep only lightweight preview metadata on the parent.
    /// Prefer that child for transcript rendering while retaining inline data
    /// for legacy/demo payloads and processing placeholders.
    private var videoTranscriptData: [String: AnyCodable] {
        Self.videoTranscriptData(embed: embed, parentData: data, allEmbedRecords: allEmbedRecords)
    }

    static func videoTranscriptData(
        embed: EmbedRecord,
        parentData: [String: AnyCodable],
        allEmbedRecords: [String: EmbedRecord]
    ) -> [String: AnyCodable] {
        if !VideoTranscriptPayload(data: parentData).transcript.isEmpty {
            return parentData
        }
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        let linked = explicit.isEmpty
            ? allEmbedRecords.values.filter { $0.parentEmbedId == embed.id }
            : explicit
        guard let childData = linked.compactMap(\.rawData).first(where: {
            !VideoTranscriptPayload(data: $0).transcript.isEmpty
        }) else { return parentData }
        return VideoTranscriptPayload.mergedData(parent: parentData, child: childData)
    }

    private var parentResultCount: Int {
        EmbedFieldReader.int(data, keys: ["result_count"]) ?? childEmbeds.count
    }

    private var previewChildEmbeds: [EmbedRecord] {
        let previewResults = ["preview_results", "results", "preview_thumbnails"]
            .lazy
            .map { EmbedFieldReader.dictionaryArray(data, key: $0) }
            .first { !$0.isEmpty } ?? []
        guard !previewResults.isEmpty else { return [] }

        return previewResults.enumerated().map { index, result in
            var recordData = result.mapValues { AnyCodable($0) }
            recordData["app_id"] = recordData["app_id"] ?? AnyCodable(appId)
            return EmbedRecord(
                id: EmbedFieldReader.string(recordData, keys: ["embed_id", "id"])
                    ?? (embed.childEmbedIds.indices.contains(index) ? embed.childEmbedIds[index] : nil)
                    ?? "\(embed.id)-preview-\(index)",
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
        EmbedType.normalized(rawValue: embed.type)?.childType?.rawValue
            ?? {
                switch appId {
                case "images", "photos": return EmbedType.imagesImageResult.rawValue
                case "videos": return EmbedType.videosVideo.rawValue
                case "business": return EmbedType.businessCompanyFinancialResult.rawValue
                case "models3d": return EmbedType.models3dModelResult.rawValue
                case "tasks": return EmbedType.tasksTask.rawValue
                case "workflows": return EmbedType.workflowsWorkflow.rawValue
                default: return EmbedType.webWebsite.rawValue
                }
            }()
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
        if let specialized = Self.specializedKind(appId: appId, skillId: skillId) {
            return specializedPreview(specialized)
        }
        if appId == "web", skillId == "search" {
            return AnyView(WebSearchEmbedRenderer(model: model, mode: .preview, onOpenEmbed: onOpenEmbed))
        } else if appId == "code", skillId == "search_repos" {
            return AnyView(CodeRepoSearchEmbedRenderer(
                model: CodeRepoSearchModel(embed: embed, allEmbedRecords: allEmbedRecords),
                mode: .preview,
                onOpenEmbed: onOpenEmbed
            ))
        } else if appId == "audio", skillId == "generate" || skillId == "speak" {
            return AnyView(GeneratedAudioSkillEmbedRenderer(data: data, status: embed.status, skillId: skillId, mode: .preview))
        } else if appId == "web", skillId == "read" {
            return AnyView(WebReadEmbedRenderer(data: data, mode: .preview))
        } else if appId == "images", skillId == "search" {
            return AnyView(ImagesSearchEmbedRenderer(model: model, mode: .preview, onOpenEmbed: onOpenEmbed))
        } else if appId == "videos", skillId == "search" {
            return AnyView(VideosSearchEmbedRenderer(model: model, mode: .preview, onOpenEmbed: onOpenEmbed))
        } else if appId == "images", skillId == "generate" || skillId == "generate_draft" {
            return AnyView(ImageGenerateEmbedRenderer(data: data, mode: .preview))
        } else if appId == "images", skillId == "view" {
            let model = ImageViewSkillModel(embed: embed, allEmbedRecords: allEmbedRecords)
            return AnyView(ImageEmbedRenderer(
                data: model.resolvedData,
                mode: .preview,
                accessibilityPrefix: "image-view-skill"
            ))
        } else if appId == "videos", skillId == "get_transcript" || skillId == "get-transcript" {
            return AnyView(TranscriptRenderer(data: videoTranscriptData, mode: .preview))
        } else if appId == "videos", skillId == "create" {
            return AnyView(RemotionVideoCreateRenderer(embedId: embed.id, data: data, mode: .preview))
        } else if appId == "code", skillId == "get_docs" {
            return AnyView(CodeGetDocsEmbedRenderer(data: data, mode: .preview))
        } else if appId == "events", skillId == "search" {
            return AnyView(EventsSearchEmbedRenderer(embed: embed, data: data, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "health", skillId == "search_appointments" {
            return AnyView(SearchDomainParentRenderer(embed: embed, kind: .health, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "home", skillId == "search" {
            return AnyView(SearchDomainParentRenderer(embed: embed, kind: .home, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "nutrition", skillId == "search_recipes" {
            return AnyView(SearchDomainParentRenderer(embed: embed, kind: .nutrition, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "shopping", skillId == "search_products" {
            return AnyView(SearchDomainParentRenderer(embed: embed, kind: .shopping, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if isCalendarActionSkill {
            return AnyView(CalendarActionEmbedRenderer(embed: embed, data: data, skillId: skillId, mode: .preview))
        } else if isFitnessSearchSkill {
            return AnyView(FitnessSearchEmbedRenderer(embed: embed, data: data, mode: .preview, childEmbeds: childEmbeds, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
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
        } else if appId == "models3d", skillId == "search" {
            return AnyView(Models3DSearchParentRenderer(embed: embed, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "models3d", skillId == "generate" {
            return AnyView(Models3DGenerateEmbedRenderer(embed: embed, mode: .preview))
        } else if appId == "tasks", skillId == "create" || skillId == "search" {
            return AnyView(TaskWorkflowParentRenderer(embed: embed, kind: .task, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "workflows", skillId == "create-or-modify" || skillId == "search" {
            return AnyView(TaskWorkflowParentRenderer(embed: embed, kind: .workflow, mode: .preview, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed))
        } else if appId == "images", !childEmbeds.isEmpty {
            return AnyView(imagesSearchPreview)
        } else {
            return AnyView(textSearchPreview)
        }
    }

    private func specializedPreview(_ kind: SpecializedKind) -> AnyView {
        switch kind {
        case .weatherForecast:
            return AnyView(WeatherForecastSkillCard(data: data, childEmbeds: linkedChildEmbeds, status: embed.status, mode: .preview, onOpenEmbed: onOpenEmbed))
        case .financeCheckAccounts:
            return AnyView(FinanceCheckAccountsSkillCard(
                data: data, status: embed.status, mode: .preview,
                piiMappings: piiMappings, hasPIIMappings: hasPIIMappings,
                isPIIRevealed: isPIIRevealed, onTogglePII: onTogglePII
            ))
        case .musicGenerate:
            return AnyView(MusicGenerateEmbedRenderer(data: data, mode: .preview))
        case .videoGenerate:
            return AnyView(VideoGenerateEmbedRenderer(data: data, mode: .preview))
        case .mathCalculate:
            return AnyView(MathCalculateSkillCard(data: data, status: embed.status, mode: .preview))
        case .travelFlight:
            return AnyView(TravelFlightSkillCard(data: data, mode: .preview))
        case .reminder:
            return AnyView(ReminderSkillCard(data: data, status: embed.status, mode: .preview))
        }
    }

    @ViewBuilder
    private func specializedFullscreen(_ kind: SpecializedKind) -> some View {
        switch kind {
        case .weatherForecast:
            WeatherForecastSkillCard(data: data, childEmbeds: linkedChildEmbeds, status: embed.status, mode: .fullscreen, onOpenEmbed: onOpenEmbed)
        case .financeCheckAccounts:
            FinanceCheckAccountsSkillCard(
                data: data, status: embed.status, mode: .fullscreen,
                piiMappings: piiMappings, hasPIIMappings: hasPIIMappings,
                isPIIRevealed: isPIIRevealed, onTogglePII: onTogglePII
            )
        case .musicGenerate:
            MusicGenerateEmbedRenderer(data: data, mode: .fullscreen)
        case .videoGenerate:
            VideoGenerateEmbedRenderer(data: data, mode: .fullscreen)
        case .mathCalculate:
            MathCalculateSkillCard(data: data, status: embed.status, mode: .fullscreen)
        case .travelFlight:
            TravelFlightSkillCard(data: data, mode: .fullscreen)
        case .reminder:
            ReminderSkillCard(data: data, status: embed.status, mode: .fullscreen)
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
        if let specialized = Self.specializedKind(appId: appId, skillId: skillId) {
            specializedFullscreen(specialized)
        } else if appId == "web", skillId == "search" {
            WebSearchEmbedRenderer(model: model, mode: .fullscreen, onOpenEmbed: onOpenEmbed)
        } else if appId == "code", skillId == "search_repos" {
            CodeRepoSearchEmbedRenderer(
                model: CodeRepoSearchModel(embed: embed, allEmbedRecords: allEmbedRecords),
                mode: .fullscreen,
                onOpenEmbed: onOpenEmbed
            )
        } else if appId == "audio", skillId == "generate" || skillId == "speak" {
            GeneratedAudioSkillEmbedRenderer(data: data, status: embed.status, skillId: skillId, mode: .fullscreen)
        } else if appId == "web", skillId == "read" {
            WebReadEmbedRenderer(data: data, mode: .fullscreen)
        } else if appId == "images", skillId == "search" {
            ImagesSearchEmbedRenderer(model: model, mode: .fullscreen, onOpenEmbed: onOpenEmbed)
        } else if appId == "videos", skillId == "search" {
            VideosSearchEmbedRenderer(model: model, mode: .fullscreen, onOpenEmbed: onOpenEmbed)
        } else if appId == "images", skillId == "generate" || skillId == "generate_draft" {
            ImageGenerateEmbedRenderer(data: data, mode: .fullscreen)
        } else if appId == "images", skillId == "view" {
            let model = ImageViewSkillModel(embed: embed, allEmbedRecords: allEmbedRecords)
            ImageEmbedRenderer(
                data: model.resolvedData,
                mode: .fullscreen,
                accessibilityPrefix: "image-view-skill"
            )
        } else if appId == "videos", skillId == "get_transcript" || skillId == "get-transcript" {
            TranscriptRenderer(data: videoTranscriptData, mode: .fullscreen)
        } else if appId == "videos", skillId == "create" {
            RemotionVideoCreateRenderer(embedId: embed.id, data: data, mode: .fullscreen)
        } else if appId == "code", skillId == "get_docs" {
            CodeGetDocsEmbedRenderer(data: data, mode: .fullscreen)
        } else if appId == "events", skillId == "search" {
            EventsSearchEmbedRenderer(embed: embed, data: data, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "health", skillId == "search_appointments" {
            SearchDomainParentRenderer(embed: embed, kind: .health, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "home", skillId == "search" {
            SearchDomainParentRenderer(embed: embed, kind: .home, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "nutrition", skillId == "search_recipes" {
            SearchDomainParentRenderer(embed: embed, kind: .nutrition, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "shopping", skillId == "search_products" {
            SearchDomainParentRenderer(embed: embed, kind: .shopping, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if isCalendarActionSkill {
            CalendarActionEmbedRenderer(embed: embed, data: data, skillId: skillId, mode: .fullscreen)
        } else if isFitnessSearchSkill {
            FitnessSearchEmbedRenderer(embed: embed, data: data, mode: .fullscreen, childEmbeds: childEmbeds, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
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
        } else if appId == "models3d", skillId == "search" {
            Models3DSearchParentRenderer(embed: embed, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "models3d", skillId == "generate" {
            Models3DGenerateEmbedRenderer(embed: embed, mode: .fullscreen)
        } else if appId == "tasks", skillId == "create" || skillId == "search" {
            TaskWorkflowParentRenderer(embed: embed, kind: .task, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        } else if appId == "workflows", skillId == "create-or-modify" || skillId == "search" {
            TaskWorkflowParentRenderer(embed: embed, kind: .workflow, mode: .fullscreen, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
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

enum TaskWorkflowEmbedKind {
    case task
    case workflow

    var appId: String {
        switch self {
        case .task: return "tasks"
        case .workflow: return "workflows"
        }
    }

    var iconName: String {
        switch self {
        case .task: return "task"
        case .workflow: return "workflow"
        }
    }

    @MainActor var singularTitle: String {
        switch self {
        case .task: return AppStrings.tasks
        case .workflow: return AppStrings.workflows
        }
    }

    var cardIdentifier: String {
        switch self {
        case .task: return "task-embed-card"
        case .workflow: return "workflow-embed-card"
        }
    }

    var fullscreenIdentifier: String {
        switch self {
        case .task: return "task-embed-fullscreen"
        case .workflow: return "workflow-embed-fullscreen"
        }
    }

    var fullscreenContentIdentifier: String {
        switch self {
        case .task: return "task-embed-fullscreen-content"
        case .workflow: return "workflow-embed-fullscreen-content"
        }
    }

    @MainActor func title(from raw: [String: AnyCodable]) -> String {
        EmbedFieldReader.string(raw, keys: ["title", "name"]) ?? singularTitle
    }

    @MainActor func subtitle(from raw: [String: AnyCodable]) -> String? {
        switch self {
        case .task:
            return EmbedFieldReader.string(raw, keys: ["short_id", "task_id"])
                ?? statusLabel(from: raw)
        case .workflow:
            return EmbedFieldReader.string(raw, keys: ["trigger_summary", "workflow_id"])
                ?? statusLabel(from: raw)
        }
    }

    func description(from raw: [String: AnyCodable]) -> String? {
        EmbedFieldReader.string(raw, keys: ["description", "summary"])
    }

    @MainActor func statusLabel(from raw: [String: AnyCodable]) -> String {
        let rawStatus = EmbedFieldReader.string(raw, keys: ["status"]) ?? ""
        let normalized = rawStatus.replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: "-", with: " ")
        let status = normalized.isEmpty ? singularTitle : normalized.capitalized
        guard self == .workflow, let enabled = raw["enabled"]?.value as? Bool else { return status }
        return enabled ? status : AppStrings.disabled
    }

    func secondaryPill(from raw: [String: AnyCodable]) -> String? {
        switch self {
        case .task:
            return EmbedFieldReader.string(raw, keys: ["assignee", "assignee_type"])
        case .workflow:
            return nil
        }
    }
}

struct TaskWorkflowParentRenderer: View {
    let embed: EmbedRecord
    let kind: TaskWorkflowEmbedKind
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private var data: [String: AnyCodable] { embed.rawData ?? [:] }
    private var children: [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return explicit }

        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id || $0.appId == kind.appId }
            .filter { $0.id != embed.id }
            .sorted { $0.id < $1.id }
        if !parented.isEmpty { return parented }

        return previewChildren
    }

    private var previewChildren: [EmbedRecord] {
        let previewResults = ["preview_results", "results"]
            .lazy
            .map { EmbedFieldReader.dictionaryArray(data, key: $0) }
            .first { !$0.isEmpty } ?? []
        return previewResults.enumerated().map { index, result in
            var recordData = result.mapValues { AnyCodable($0) }
            recordData["app_id"] = recordData["app_id"] ?? AnyCodable(kind.appId)
            return EmbedRecord(
                id: "\(embed.id)-\(kind.appId)-preview-\(index)",
                type: kind == .task ? EmbedType.tasksTask.rawValue : EmbedType.workflowsWorkflow.rawValue,
                status: .finished,
                data: .raw(recordData),
                parentEmbedId: embed.id,
                appId: kind.appId,
                skillId: nil,
                embedIds: nil,
                createdAt: embed.createdAt
            )
        }
    }

    private var displayTitle: String {
        EmbedFieldReader.string(data, keys: ["instruction", "query", "title"])
            ?? EmbedType.normalized(rawValue: embed.type)?.displayName
            ?? kind.singularTitle
    }

    private var resultCount: Int {
        EmbedFieldReader.int(data, keys: ["result_count"]) ?? children.count
    }

    var body: some View {
        switch mode {
        case .preview:
            parentPreview
        case .fullscreen:
            parentFullscreen
        }
    }

    private var parentPreview: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(displayTitle)
                .font(.omSmall)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(summary)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .accessibilityIdentifier(parentPreviewIdentifier)
    }

    private var parentFullscreen: some View {
        Group {
            if children.isEmpty {
                Text(summary)
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260, maximum: 320), spacing: .spacing6, alignment: .top)], spacing: .spacing6) {
                    ForEach(children) { child in
                        TaskWorkflowEmbedRenderer(embed: child, kind: kind, mode: .preview) {
                            onOpenEmbed(child)
                        }
                    }
                }
                .frame(maxWidth: 1040)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing8)
                .padding(.bottom, 120)
            }
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .accessibilityIdentifier(kind == .task ? "task-parent-fullscreen" : "workflow-parent-fullscreen")
    }

    private var parentPreviewIdentifier: String {
        switch (kind, embed.skillId) {
        case (.task, "create"):
            return "task-create-embed-preview"
        case (.task, "search"):
            return "task-search-embed-preview"
        case (.workflow, "create-or-modify"):
            return "workflow-create-embed-preview"
        case (.workflow, "search"):
            return "workflow-search-embed-preview"
        default:
            return kind == .task ? "task-parent-preview" : "workflow-parent-preview"
        }
    }

    private var summary: String {
        if embed.status != .finished { return AppStrings.loading }
        guard resultCount > 0 else { return AppStrings.searchNoResults }
        return "\(resultCount) \(kind.singularTitle)"
    }
}

struct TaskWorkflowEmbedRenderer: View {
    let embed: EmbedRecord
    let kind: TaskWorkflowEmbedKind
    let mode: EmbedDisplayMode
    var onTap: () -> Void = {}

    private var raw: [String: AnyCodable] { embed.rawData ?? [:] }

    var body: some View {
        switch mode {
        case .preview:
            Button(action: onTap) { previewCard }
                .buttonStyle(.plain)
                .accessibilityIdentifier(kind.cardIdentifier)
        case .fullscreen:
            fullscreen
        }
    }

    private var previewCard: some View {
        HStack(alignment: .center, spacing: .spacing5) {
            iconShell
                .frame(width: 56)

            VStack(alignment: .leading, spacing: .spacing3) {
                if let subtitle = kind.subtitle(from: raw) {
                    Text(subtitle)
                        .font(.omXs)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                }

                Text(kind.title(from: raw))
                    .font(.omSmall)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)

                if let description = kind.description(from: raw) {
                    Text(description)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(2)
                }

                HStack(spacing: 6) {
                    pill(kind.statusLabel(from: raw))
                    if let assignee = kind.secondaryPill(from: raw), !assignee.isEmpty {
                        pill(assignee)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private var fullscreen: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            HStack(alignment: .top, spacing: .spacing6) {
                iconShell.frame(width: 72, height: 72)
                VStack(alignment: .leading, spacing: .spacing3) {
                    if let subtitle = kind.subtitle(from: raw) {
                        Text(subtitle)
                            .font(.omSmall)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.fontSecondary)
                    }
                    Text(kind.title(from: raw))
                        .font(.omH1)
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(3)
                    if let description = kind.description(from: raw) {
                        Text(description)
                            .font(.omP)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
            }

            HStack(spacing: .spacing3) {
                pill(kind.statusLabel(from: raw))
                if let assignee = kind.secondaryPill(from: raw), !assignee.isEmpty { pill(assignee) }
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: 860, alignment: .leading)
        .frame(maxWidth: .infinity)
        .padding(.vertical, .spacing12)
        .padding(.bottom, 120)
        .accessibilityIdentifier(kind.fullscreenIdentifier)
    }

    private var iconShell: some View {
        ZStack {
            AppGradientBackground(appId: kind.appId)
            Icon(kind.iconName, size: 28)
                .foregroundStyle(Color.grey0)
        }
        .clipShape(RoundedRectangle(cornerRadius: 18))
    }

    private func pill(_ label: String) -> some View {
        Text(label)
            .font(.omXs)
            .fontWeight(.semibold)
            .foregroundStyle(Color.fontSecondary)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Color.grey10)
            .clipShape(Capsule())
    }
}

struct Models3DSearchParentRenderer: View {
    let embed: EmbedRecord
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private var data: [String: AnyCodable] { embed.rawData ?? [:] }
    private var children: [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return explicit }
        let parented = allEmbedRecords.values
            .filter { ($0.parentEmbedId == embed.id || $0.appId == "models3d") && $0.id != embed.id }
            .sorted { $0.id < $1.id }
        if !parented.isEmpty { return parented }
        return previewChildren
    }

    private var previewChildren: [EmbedRecord] {
        let previewResults = ["preview_results", "results", "preview_thumbnails"]
            .lazy
            .map { EmbedFieldReader.dictionaryArray(data, key: $0) }
            .first { !$0.isEmpty } ?? []
        return previewResults.enumerated().map { index, result in
            var recordData = result.mapValues { AnyCodable($0) }
            recordData["app_id"] = recordData["app_id"] ?? AnyCodable("models3d")
            return EmbedRecord(
                id: "\(embed.id)-models3d-preview-\(index)",
                type: EmbedType.models3dModelResult.rawValue,
                status: .finished,
                data: .raw(recordData),
                parentEmbedId: embed.id,
                appId: "models3d",
                skillId: nil,
                embedIds: nil,
                createdAt: embed.createdAt
            )
        }
    }

    private var query: String {
        EmbedFieldReader.string(data, keys: ["query", "title"]) ?? AppStrings.models3d
    }

    private var provider: String {
        EmbedFieldReader.string(data, keys: ["provider"]) ?? "Printables"
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
        VStack(alignment: .leading, spacing: .spacing4) {
            let imageChildren = childrenWithImages.prefix(5)
            if !imageChildren.isEmpty {
                HStack(spacing: 4) {
                    ForEach(Array(imageChildren)) { child in
                        modelThumbnail(child)
                    }
                }
                .frame(height: 74)
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .background(Color.grey10)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(query)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
                Text(metaText)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .accessibilityIdentifier("models3d-search-preview")
    }

    private var fullscreen: some View {
        Group {
            if children.isEmpty {
                Text(AppStrings.models3dNoResults)
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260, maximum: 320), spacing: .spacing6, alignment: .top)], spacing: .spacing6) {
                    ForEach(children) { child in
                        Models3DResultEmbedRenderer(embed: child, mode: .preview) {
                            onOpenEmbed(child)
                        }
                    }
                }
                .frame(maxWidth: 1040)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing8)
                .padding(.bottom, 120)
            }
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .accessibilityIdentifier("models3d-search-fullscreen")
    }

    private var metaText: String {
        if children.isEmpty { return AppStrings.models3dOpenToView }
        return "\(AppStrings.models3dResultsCount(children.count)) · \(AppStrings.via) \(provider)"
    }

    private var childrenWithImages: [EmbedRecord] {
        children.filter { modelImageURL(for: $0.rawData ?? [:], maxWidth: 260) != nil }
    }

    private func modelThumbnail(_ child: EmbedRecord) -> some View {
        ZStack {
            if let imageURL = modelImageURL(for: child.rawData ?? [:], maxWidth: 260), let url = URL(string: imageURL) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: { Color.grey10 }
            } else {
                Color.grey10.overlay(Icon("3dmodels", size: 32).foregroundStyle(Color.grey40))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .clipped()
    }
}

struct Models3DResultEmbedRenderer: View {
    @Environment(\.openURL) private var openURL

    let embed: EmbedRecord
    let mode: EmbedDisplayMode
    var onTap: () -> Void = {}

    private var raw: [String: AnyCodable] { embed.rawData ?? [:] }
    private var title: String { EmbedFieldReader.string(raw, keys: ["title", "name"]) ?? AppStrings.models3dResultTitle }
    private var provider: String? { EmbedFieldReader.string(raw, keys: ["provider"]) }
    private var creator: String? { EmbedFieldReader.string(raw, keys: ["creator_name", "creatorName"]) }
    private var license: String? { EmbedFieldReader.string(raw, keys: ["license"]) }
    private var filesCount: Int? { EmbedFieldReader.int(raw, keys: ["files_count", "filesCount"]) }
    private var sourceURL: String? { EmbedFieldReader.string(raw, keys: ["source_page_url", "sourcePageUrl", "source_url", "url"]) }
    private var imageURL: String? { modelImageURL(for: raw, maxWidth: mode == .preview ? 520 : 960) }

    var body: some View {
        switch mode {
        case .preview:
            Button(action: onTap) { previewCard }
                .buttonStyle(.plain)
                .accessibilityIdentifier("models3d-result-card")
        case .fullscreen:
            fullscreen
        }
    }

    private var previewCard: some View {
        HStack(alignment: .center, spacing: .spacing4) {
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(title)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                metaLine
                pills
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            imageShell
                .frame(width: 112)
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private var fullscreen: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: .spacing12) {
                largeImageShell.frame(maxWidth: .infinity, minHeight: 360)
                metadata.frame(width: 300, alignment: .leading)
            }
            VStack(alignment: .leading, spacing: .spacing8) {
                largeImageShell.frame(minHeight: 320)
                metadata
            }
        }
        .padding(.spacing12)
        .frame(maxWidth: 1120)
        .frame(maxWidth: .infinity)
        .padding(.bottom, 120)
        .accessibilityIdentifier("models3d-result-fullscreen")
    }

    private var imageShell: some View {
        ZStack {
            if let imageURL, let url = URL(string: imageURL) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: { modelPlaceholder }
            } else {
                modelPlaceholder
            }
        }
        .aspectRatio(4 / 3, contentMode: .fit)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .accessibilityIdentifier("models3d-result-card-image")
    }

    private var largeImageShell: some View {
        ZStack {
            if let imageURL, let url = URL(string: imageURL) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fit)
                } placeholder: { modelPlaceholder }
            } else {
                modelPlaceholder
            }
        }
        .frame(maxWidth: .infinity, maxHeight: 560)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: 24))
    }

    private var modelPlaceholder: some View {
        Color.grey10.overlay(Icon("3dmodels", size: mode == .preview ? 32 : 44).foregroundStyle(Color.grey40))
    }

    private var metadata: some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            Text(title)
                .font(.omH2)
                .foregroundStyle(Color.fontPrimary)
            if let creator { Text(creator).font(.omP).foregroundStyle(Color.fontSecondary) }
            if let license { Text(license).font(.omP).foregroundStyle(Color.fontSecondary) }
            if let filesCount { Text(AppStrings.models3dFilesCount(filesCount)).font(.omP).foregroundStyle(Color.fontSecondary) }
            if let sourceURL, let url = Self.providerURL(sourceURL), let host = url.host {
                Button {
                    openURL(url)
                } label: {
                    Text(AppStrings.models3dOpenOnProvider(provider ?? host))
                        .font(.omSmall)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, 13)
                        .padding(.vertical, 9)
                        .background(Color.buttonPrimary)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("models3d-open-provider-cta-inline")
            }
        }
        .foregroundStyle(Color.fontPrimary)
    }

    static func providerURL(_ source: String) -> URL? {
        guard let url = URL(string: source),
              ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
              url.host != nil else { return nil }
        return url
    }

    private var metaLine: some View {
        HStack(spacing: 6) {
            if let creator { Text(creator) }
            if let provider { Text(provider) }
        }
        .font(.omXs)
        .foregroundStyle(Color.fontSecondary)
        .lineLimit(1)
    }

    private var pills: some View {
        HStack(spacing: 6) {
            if raw["is_free"]?.value as? Bool == true || raw["isFree"]?.value as? Bool == true { pill(AppStrings.models3dFree) }
            if let filesCount { pill(AppStrings.models3dFilesCount(filesCount)) }
            if let license { pill(license) }
        }
    }

    private func pill(_ label: String) -> some View {
        Text(label)
            .font(.omXs)
            .foregroundStyle(Color.fontSecondary)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Color.grey10)
            .clipShape(Capsule())
    }
}

struct Models3DGenerateEmbedRenderer: View {
    let embed: EmbedRecord
    let mode: EmbedDisplayMode

    private var raw: [String: AnyCodable] { embed.rawData ?? [:] }
    private var prompt: String { EmbedFieldReader.string(raw, keys: ["prompt", "title"]) ?? AppStrings.models3d }
    private var providerModel: String? { EmbedFieldReader.string(raw, keys: ["provider_model", "providerModel", "provider"]) }
    private var posterURL: String? { modelImageURL(for: raw, maxWidth: mode == .preview ? 520 : 960) }
    private var encryptedPoster: EncryptedPoster? { Self.encryptedPoster(from: raw) }

    struct EncryptedPoster {
        let baseURL: String
        let s3Key: String
        let aesKey: String
        let nonce: String
    }

    static func encryptedPoster(from raw: [String: AnyCodable]) -> EncryptedPoster? {
        guard let files = raw["files"]?.value as? [String: Any],
              let poster = files["poster"] as? [String: Any],
              let s3Key = poster["s3_key"] as? String, !s3Key.isEmpty,
              let nonce = poster["aes_nonce"] as? String, !nonce.isEmpty,
              let aesKey = raw["aes_key"]?.value as? String, !aesKey.isEmpty,
              let baseURL = raw["s3_base_url"]?.value as? String, !baseURL.isEmpty else {
            return nil
        }
        return EncryptedPoster(baseURL: baseURL, s3Key: s3Key, aesKey: aesKey, nonce: nonce)
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
        ZStack {
            if let posterURL, let url = URL(string: posterURL) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fit)
                } placeholder: { modelFallbackText }
            } else if let encryptedPoster {
                EncryptedImageView(
                    s3Url: encryptedPoster.baseURL,
                    s3Key: encryptedPoster.s3Key,
                    aesKey: encryptedPoster.aesKey,
                    aesNonce: encryptedPoster.nonce,
                    encryption: nil,
                    contentMode: .fit
                )
            } else {
                modelFallbackText
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("models3d-generate-preview")
    }

    private var fullscreen: some View {
        VStack(spacing: .spacing6) {
            if let posterURL, let url = URL(string: posterURL) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fit)
                } placeholder: { modelFallbackText }
                .frame(maxWidth: .infinity, maxHeight: 560)
                .clipShape(RoundedRectangle(cornerRadius: 16))
            } else if let encryptedPoster {
                EncryptedImageView(
                    s3Url: encryptedPoster.baseURL,
                    s3Key: encryptedPoster.s3Key,
                    aesKey: encryptedPoster.aesKey,
                    aesNonce: encryptedPoster.nonce,
                    encryption: nil,
                    contentMode: .fit
                )
                .frame(maxWidth: .infinity, maxHeight: 560)
                .clipShape(RoundedRectangle(cornerRadius: 16))
            } else {
                modelFallbackText
                    .frame(minHeight: 320)
            }
            if let providerModel {
                Text(providerModel)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity)
        .padding(.bottom, 120)
        .accessibilityIdentifier("models3d-generate-fullscreen")
    }

    private var modelFallbackText: some View {
        Text(prompt)
            .font(.omP)
            .foregroundStyle(Color.fontPrimary)
            .multilineTextAlignment(.center)
            .lineLimit(mode == .preview ? 4 : nil)
    }
}

private func modelImageURL(for raw: [String: AnyCodable], maxWidth: Int) -> String? {
    EmbedFieldReader.proxiedImageURL(
        EmbedFieldReader.string(raw, keys: ["preview_image_url", "previewImageUrl", "thumbnail_url", "thumbnailUrl", "poster_url", "posterUrl", "image_url", "image"]),
        maxWidth: maxWidth
    )
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

struct CalendarActionEmbedRenderer: View {
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

    private var title: String {
        isProcessing ? (model.explicitTitle ?? "Search") : model.title
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(title)
                .font(.omP.weight(.bold))
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(2)

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
    let explicitTitle: String?
    let summary: String?
    let error: String?
    let items: [CalendarActionItem]

    init(data: [String: AnyCodable], skillId: String) {
        let fallbackTitle = AppStrings.calendarSkillTitle(skillId)
        explicitTitle = EmbedFieldReader.string(data, keys: ["title"])
        title = explicitTitle ?? fallbackTitle
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
    let childEmbeds: [EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

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
            FitnessSearchPreview(skillId: skillId, group: group, status: embed.status)
        case .fullscreen:
            FitnessSearchFullscreen(group: group, childEmbeds: childEmbeds, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
        }
    }
}

private struct FitnessSearchPreview: View {
    let skillId: String
    let group: FitnessSearchGroup
    let status: EmbedStatus

    private var title: String {
        skillId == "search_locations" ? AppStrings.fitnessSearchLocations : AppStrings.fitnessSearchClasses
    }

    private var locationLabel: String {
        group.filters.string("address") ?? group.filters.string("city") ?? group.query ?? group.provider
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 5.6) {
            Text(group.provider)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
                .lineLimit(1)

            Text(title)
                .font(.omP)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(2)

            Text(locationLabel).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)

            if status == .finished {
                Text("\(group.resultCount) \(skillId == "search_classes" ? "classes" : "locations")")
                    .font(.omP.weight(.semibold))
                    .foregroundStyle(Color.fontPrimary)
                    .accessibilityIdentifier("fitness-search-result-count")
                if let summary = group.summary {
                    Text(summary).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                }
                ForEach(group.results.prefix(2)) { result in
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(result.name).font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontPrimary).lineLimit(1)
                        if let venue = result.venueName {
                            Text(venue).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                        }
                    }
                }
            } else {
                Text(status == .error ? "Search failed." : status == .cancelled ? "Search cancelled." : "Searching Urban Sports Club...")
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }

            if !group.chips.isEmpty {
                FitnessChipRow(chips: group.chips)
                    .frame(maxHeight: .infinity, alignment: .bottom)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

private struct FitnessSearchFullscreen: View {
    let group: FitnessSearchGroup
    let childEmbeds: [EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private let columns = [GridItem(.adaptive(minimum: 300), spacing: .spacing5)]
    private var resultEmbeds: [EmbedRecord] {
        childEmbeds.isEmpty ? group.results.map(\.embedRecord) : childEmbeds
    }

    var body: some View {
        Group {
            if resultEmbeds.isEmpty {
                Text(group.error ?? AppStrings.searchNoResults)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(group.error == nil ? Color.fontSecondary : Color.error)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else {
                LazyVGrid(columns: columns, alignment: .leading, spacing: .spacing5) {
                    ForEach(resultEmbeds, id: \.id) { child in
                        EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords) {
                            onOpenEmbed(child)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
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

    var body: some View {
        switch mode {
        case .preview:
            FitnessResultPreview(result: result)
        case .fullscreen:
            FitnessResultDetail(result: result)
        }
    }
}

private struct FitnessResultPreview: View {
    let result: FitnessResultSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            if let subtitle = result.previewSubtitle {
                Text(subtitle)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
            }

            if !result.previewMeta.isEmpty {
                Text(result.previewMeta.joined(separator: " "))
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

private struct FitnessResultDetail: View {
    let result: FitnessResultSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            Text(result.name)
                .font(.omH3)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)

            if let subtitle = result.detailSubtitle {
                Text(subtitle)
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
            }

            VStack(alignment: .leading, spacing: .spacing3) {
                FitnessDetailField(label: "Address", value: result.address)
                FitnessDetailField(label: "Distance", value: result.distanceText)
                FitnessDetailField(label: "Spots", value: result.spotsDisplay)
                FitnessDetailField(label: "Mode", value: result.attendanceMode)
            }

            if !result.tags.isEmpty {
                FitnessChipRow(chips: result.tags)
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

private struct FitnessDetailField: View {
    let label: String
    let value: String?

    var body: some View {
        if let value, !value.isEmpty {
            VStack(alignment: .leading, spacing: .spacing1) {
                Text(label).font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
                Text(value).font(.omP).foregroundStyle(Color.fontSecondary)
            }
        }
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
            filters.chip("plan").map { "Plan: \($0)" },
            filters.chip("attendance_mode")
        ].compactMap { $0 }
    }
}

private struct FitnessResultSummary: Identifiable {
    let id: String
    let rawData: [String: Any]
    let name: String
    let venueName: String?
    let address: String?
    let date: String?
    let timeRange: String?
    let distanceKm: String?
    let spotsDisplay: String?
    let attendanceMode: String?
    let plansRequired: [String]?
    let disciplines: [String]?
    let url: String?
    let skillId: String?

    init(index: Int, data: [String: Any]) {
        rawData = data
        id = data.string("id") ?? "fitness-result-\(index)"
        name = data.string("name") ?? data.string("venue_name") ?? "Urban Sports result"
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
        attendanceMode = data.string("attendance_mode")
        plansRequired = data.stringArray("plans_required")
        disciplines = data.stringArray("disciplines")
        url = data.string("detail_url") ?? data.string("url") ?? data.string("venue_url")
        skillId = data.string("skill_id") ?? data.string("app_skill_id")
    }

    var previewSubtitle: String? {
        if skillId == "search_classes" || date != nil {
            return [dateTimeText, venueName].compactMap { $0 }.joined(separator: " · ").nilIfEmpty
        }
        return address ?? venueName
    }

    var detailSubtitle: String? {
        if skillId == "search_classes" || date != nil {
            return [date, timeRange, venueName].compactMap { $0 }.joined(separator: " · ").nilIfEmpty
        }
        return address
    }

    var meta: [String] {
        [
            dateTimeText,
            distanceText,
            spotsDisplay
        ].compactMap { $0 }
    }

    var previewMeta: [String] {
        [distanceText, spotsDisplay, disciplines?.prefix(2).joined(separator: ", "), plansRequired?.joined(separator: ", ")]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
    }

    var tags: [String] {
        (disciplines ?? []) + (plansRequired ?? [])
    }

    var embedRecord: EmbedRecord {
        EmbedRecord(
            id: id,
            type: date == nil ? EmbedType.fitnessLocation.rawValue : EmbedType.fitnessClass.rawValue,
            status: .finished,
            data: .raw(rawData.mapValues(AnyCodable.init)),
            parentEmbedId: nil,
            appId: "fitness",
            skillId: skillId,
            embedIds: nil,
            createdAt: nil
        )
    }

    private var dateTimeText: String? {
        [date, timeRange].compactMap { $0 }.joined(separator: " ").nilIfEmpty
    }

    var distanceText: String? {
        guard let distanceKm, let value = Double(distanceKm) else { return distanceKm }
        return value.formatted(.number.precision(.fractionLength(2))) + " km"
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

struct TravelFlightSkillCard: View {
    let data: [String: AnyCodable]
    let mode: EmbedDisplayMode

    var flightNumber: String? { EmbedFieldReader.string(data, keys: ["flight_number"]) }
    private var departureDate: String? { EmbedFieldReader.string(data, keys: ["departure_date"]) }
    var origin: String? { EmbedFieldReader.string(data, keys: ["origin_iata", "departure_iata"]) }
    var destination: String? { EmbedFieldReader.string(data, keys: ["destination_iata", "arrival_iata", "actual_destination_iata"]) }
    var takeoff: String? { EmbedFieldReader.string(data, keys: ["actual_takeoff"]) }
    var landing: String? { EmbedFieldReader.string(data, keys: ["actual_landing"]) }
    var trackCount: Int { (data["tracks"]?.value as? [Any])?.count ?? 0 }
    var diverted: Bool { data["diverted"]?.value as? Bool == true }
    private var actualDestination: String? { EmbedFieldReader.string(data, keys: ["actual_destination_iata"]) }
    private var runwayTakeoff: String? { EmbedFieldReader.string(data, keys: ["runway_takeoff"]) }
    private var runwayLanding: String? { EmbedFieldReader.string(data, keys: ["runway_landing"]) }
    private var fr24Id: String? { EmbedFieldReader.string(data, keys: ["fr24_id"]) }
    private var distance: Int? { EmbedFieldReader.int(data, keys: ["actual_distance_km"]) }
    private var flightMinutes: Int? { EmbedFieldReader.int(data, keys: ["flight_time_minutes"]) }
    #if canImport(MapKit)
    private var trackCoordinates: [CLLocationCoordinate2D] {
        (data["tracks"]?.value as? [[String: Any]] ?? []).compactMap { point in
            guard let latitude = (point["lat"] as? NSNumber)?.doubleValue,
                  let longitude = (point["lon"] as? NSNumber)?.doubleValue,
                  (-90...90).contains(latitude), (-180...180).contains(longitude) else { return nil }
            return CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
        }
    }
    #endif

    var body: some View {
        Group {
            if mode == .preview { preview } else { fullscreen }
        }
    }

    private var preview: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: .spacing4) {
                Text(flightNumber ?? "—")
                    .font(.omP)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                if diverted {
                    Text(AppStrings.travelFlightDiverted)
                        .font(.omXxs.weight(.semibold))
                        .foregroundStyle(Color.warning)
                        .padding(.horizontal, .spacing3)
                        .padding(.vertical, .spacing1)
                        .background(Color.warning.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: .radius1))
                }
            }
            .padding(.bottom, 3)
            if let route {
                Text(route)
                    .font(.omSmall.weight(.medium))
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.bottom, 1)
            }
            if let date = takeoff ?? departureDate {
                Text(formatDate(date))
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.bottom, .spacing2)
            }
            if takeoff != nil || landing != nil {
                HStack(spacing: .spacing3) {
                    if let takeoff {
                        Text(formatTime(takeoff))
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(Color.fontPrimary)
                        Text("→")
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                    }
                    if let landing {
                        Text(formatTime(landing))
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(Color.fontPrimary)
                    }
                }
                .padding(.bottom, .spacing3)
            }
            Text(trackCount > 0 ? "\(AppStrings.travelFlightTrackAvailable) · \(trackCount) pts" : "No track data")
                .font(.omXxs.weight(.medium))
                .foregroundStyle(Color.fontSecondary)
                .padding(.horizontal, .spacing3)
                .padding(.vertical, .spacing1)
                .background(Color.grey20)
                .clipShape(RoundedRectangle(cornerRadius: .radius1))
        }
        .padding(.top, 2)
        .padding(.bottom, .spacing1)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .accessibilityIdentifier("travel-flight-details-preview")
    }

    private var fullscreen: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let date = takeoff ?? departureDate {
                Text(formatDate(date))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity)
                    .padding(.bottom, .spacing6)
            }
            if diverted {
                Text("⚠  Flight diverted\(actualDestination.map { " to \($0)" } ?? "")")
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.warning)
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing5)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.warning.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    .overlay(RoundedRectangle(cornerRadius: .radius4).stroke(Color.warning.opacity(0.3)))
                    .padding(.bottom, .spacing8)
            }
            #if canImport(MapKit)
            if trackCoordinates.count >= 2 {
                FlightTrackMap(coordinates: trackCoordinates, origin: origin, destination: actualDestination ?? destination)
                    .frame(height: 280)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .padding(.bottom, .spacing3)
                HStack(spacing: .spacing1) {
                    Link("© OpenStreetMap", destination: URL(string: "https://www.openstreetmap.org/copyright")!)
                    Text("| Track:")
                    Link("Flightradar24", destination: URL(string: "https://www.flightradar24.com")!)
                }
                .font(.omXxs)
                .foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .padding(.bottom, .spacing10)
            } else {
                noTrackPlaceholder
            }
            #else
            noTrackPlaceholder
            #endif
            VStack(spacing: 0) {
                detailRow("Takeoff", value: formatDateTime(takeoff))
                detailRow("Landing", value: formatDateTime(landing))
                if let flightMinutes {
                    detailRow("Duration", value: "\(flightMinutes / 60)h \(flightMinutes % 60)m")
                }
                if let runwayTakeoff { detailRow("Runway (dep.)", value: runwayTakeoff) }
                if let runwayLanding { detailRow("Runway (arr.)", value: runwayLanding) }
                if let distance { detailRow("Distance", value: "\(distance.formatted()) km") }
                if let fr24Id { detailRow("FR24 ID", value: fr24Id, last: true) }
            }
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20))
        }
        .frame(maxWidth: 600)
        .padding(.horizontal, .spacing10)
        .padding(.top, 60)
        .padding(.bottom, 120)
        .frame(maxWidth: .infinity)
        .accessibilityIdentifier("travel-flight-details-fullscreen")
    }

    private var noTrackPlaceholder: some View {
                VStack(spacing: .spacing4) {
                    Text("✈").font(.omXxl).opacity(0.4)
                    Text("No track data available")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, .spacing20)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                .padding(.bottom, .spacing10)
    }

    private func detailRow(_ label: String, value: String, last: Bool = false) -> some View {
        HStack {
            Text(label).font(.omSmall.weight(.medium)).foregroundStyle(Color.fontSecondary)
            Spacer()
            Text(value).font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontPrimary)
        }
        .padding(.horizontal, .spacing8)
        .padding(.vertical, .spacing6)
        .overlay(alignment: .bottom) { if !last { Color.grey10.frame(height: 1) } }
    }

    private var route: String? {
        guard let origin else { return nil }
        return destination.map { "\(origin) → \($0)" } ?? origin
    }

    private func formatDate(_ source: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: source) else { return source }
        return date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
    }

    private func formatTime(_ source: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: source) else { return source }
        return date.formatted(.dateTime.hour().minute())
    }

    private func formatDateTime(_ source: String?) -> String {
        guard let source, let date = ISO8601DateFormatter().date(from: source) else { return "—" }
        return date.formatted(.dateTime.month(.abbreviated).day().hour().minute())
    }
}

#if canImport(MapKit)
private struct FlightTrackMap: View {
    let coordinates: [CLLocationCoordinate2D]
    let origin: String?
    let destination: String?

    var body: some View {
        #if os(iOS)
        FlightOSMMap(coordinates: coordinates, origin: origin, destination: destination)
        #else
        Map(initialPosition: .rect(MKPolyline(coordinates: coordinates, count: coordinates.count).boundingMapRect)) {
            MapPolyline(coordinates: coordinates)
                .stroke(Color.buttonPrimary, lineWidth: 2.5)
        }
        #endif
    }
}

#if os(iOS)
private final class FlightOSMTiles: MKTileOverlay {
    override func url(forTilePath path: MKTileOverlayPath) -> URL {
        let host = ["a", "b", "c"][(path.x + path.y) % 3]
        return URL(string: "https://\(host).tile.openstreetmap.org/\(path.z)/\(path.x)/\(path.y).png")!
    }
}

private struct FlightOSMMap: UIViewRepresentable {
    let coordinates: [CLLocationCoordinate2D]
    let origin: String?
    let destination: String?

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> MKMapView {
        let map = MKMapView()
        map.delegate = context.coordinator
        map.isRotateEnabled = false
        map.isPitchEnabled = false
        map.isScrollEnabled = true
        map.isZoomEnabled = true
        map.showsCompass = false
        map.pointOfInterestFilter = .excludingAll

        let tiles = FlightOSMTiles(urlTemplate: nil)
        tiles.canReplaceMapContent = true
        map.addOverlay(tiles, level: .aboveRoads)

        let line = MKPolyline(coordinates: coordinates, count: coordinates.count)
        map.addOverlay(line, level: .aboveLabels)
        if let first = coordinates.first {
            let marker = MKPointAnnotation()
            marker.coordinate = first
            marker.title = origin ?? "Departure"
            map.addAnnotation(marker)
        }
        if let last = coordinates.last {
            let marker = MKPointAnnotation()
            marker.coordinate = last
            marker.title = destination ?? "Arrival"
            map.addAnnotation(marker)
        }
        map.setVisibleMapRect(
            line.boundingMapRect,
            edgePadding: UIEdgeInsets(top: 40, left: 40, bottom: 40, right: 40),
            animated: false
        )
        return map
    }

    func updateUIView(_ map: MKMapView, context: Context) {}

    final class Coordinator: NSObject, MKMapViewDelegate {
        func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            if let tiles = overlay as? MKTileOverlay {
                return MKTileOverlayRenderer(tileOverlay: tiles)
            }
            if let line = overlay as? MKPolyline {
                let renderer = MKPolylineRenderer(polyline: line)
                renderer.strokeColor = UIColor(Color.buttonPrimary)
                renderer.lineWidth = 2.5
                renderer.alpha = 0.85
                return renderer
            }
            return MKOverlayRenderer(overlay: overlay)
        }

        func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            let view = mapView.dequeueReusableAnnotationView(withIdentifier: "flight-route-dot")
                ?? MKAnnotationView(annotation: annotation, reuseIdentifier: "flight-route-dot")
            view.annotation = annotation
            view.frame = CGRect(x: 0, y: 0, width: 16, height: 16)
            view.backgroundColor = UIColor(Color.buttonPrimary)
            view.layer.cornerRadius = 8
            view.layer.borderWidth = 3
            view.layer.borderColor = UIColor(Color.grey0).cgColor
            view.canShowCallout = true
            return view
        }
    }
}
#endif
#endif

private struct MathCalculateSkillCard: View {
    let data: [String: AnyCodable]
    let status: EmbedStatus
    let mode: EmbedDisplayMode

    private var results: [[String: Any]] { EmbedFieldReader.dictionaryArray(data, key: "results") }
    private var first: [String: Any] { results.first ?? [:] }
    private var title: String? {
        EmbedFieldReader.string(data, keys: ["title"]) ?? first["title"] as? String
    }
    private var expression: String? {
        EmbedFieldReader.string(data, keys: ["query", "expression"]) ?? first["expression"] as? String
    }
    private var result: String? { first["result"] as? String ?? EmbedFieldReader.string(data, keys: ["result"]) }

    var body: some View {
        Group {
            if mode == .preview { preview } else { fullscreen }
        }
    }

    private var preview: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let title, !title.isEmpty {
                previewRow("Title") {
                    Text(title)
                        .font(.omSmall.weight(.bold))
                        .foregroundStyle(Color.grey100)
                        .lineLimit(2)
                }
            }
            if let expression, !expression.isEmpty {
                previewRow("Expression") {
                    Text(expression)
                        .font(.custom("CourierNewPSMT", size: 14))
                        .foregroundStyle(Color.grey70)
                        .lineLimit(2)
                }
            }
            if status == .error {
                Text(AppStrings.genericProcessingError)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .padding(.top, .spacing2)
            } else if status == .finished, let result, !result.isEmpty {
                previewRow("Result") {
                    Text("= \(result)")
                        .font(.custom("CourierNewPS-BoldMT", size: 22))
                        .foregroundStyle(Color.grey100)
                        .lineLimit(2)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .accessibilityIdentifier("math-calculate-preview")
    }

    private func previewRow<Content: View>(_ label: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(label.uppercased())
                .font(.omXxs.weight(.bold))
                .foregroundStyle(Color.grey60)
            content()
        }
    }

    private var fullscreen: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            if results.isEmpty {
                Text(status == .processing ? AppStrings.loading : "No results.")
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else {
                ForEach(Array(results.enumerated()), id: \.offset) { _, item in
                    resultCard(item)
                }
            }
        }
        .frame(maxWidth: 800)
        .padding(.horizontal, .spacing8)
        .padding(.top, .spacing12)
        .padding(.bottom, 120)
        .frame(maxWidth: .infinity)
        .accessibilityIdentifier("math-calculate-fullscreen")
    }

    private func resultCard(_ item: [String: Any]) -> some View {
        let itemExpression = expression ?? item["expression"] as? String
        let itemResult = item["result"] as? String
        let itemError = item["error"] as? String
        let steps = (item["steps"] as? [Any] ?? []).compactMap { step -> String? in
            if let text = step as? String { return text }
            guard let fields = step as? [String: Any] else { return nil }
            if let expression = fields["expression"] as? String, let result = fields["result"] as? String {
                return "\(expression) = \(result)"
            }
            return fields["description"] as? String ?? fields["latex"] as? String
        }
        return VStack(alignment: .leading, spacing: .spacing6) {
            if let itemExpression, !itemExpression.isEmpty {
                resultSection("Expression") {
                    Text(itemExpression).font(.custom("CourierNewPSMT", size: 14)).foregroundStyle(Color.grey70)
                }
            }
            if let itemError, !itemError.isEmpty {
                Text(itemError).font(.omSmall.weight(.medium)).foregroundStyle(Color.error)
            } else if let itemResult, !itemResult.isEmpty {
                resultSection("Result") {
                    Text(itemResult).font(.custom("CourierNewPS-BoldMT", size: 28)).foregroundStyle(Color.grey100)
                }
                if let type = item["result_type"] as? String {
                    Text("Type: \(type)").font(.omXs).foregroundStyle(Color.grey70)
                }
                if let mode = item["mode"] as? String {
                    Text("Mode: \(modeLabel(mode))").font(.omXs).foregroundStyle(Color.grey70)
                }
            }
            if !steps.isEmpty {
                resultSection("Calculation") {
                    VStack(alignment: .leading, spacing: .spacing2) {
                        ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                            Text("\(index + 1). \(step)")
                                .font(.custom("CourierNewPSMT", size: 13)).foregroundStyle(Color.grey70)
                        }
                    }
                }
                .padding(.top, .spacing4)
            } else if let itemExpression, let itemResult, !itemExpression.isEmpty, !itemResult.isEmpty {
                resultSection("Calculation") {
                    Text("\(itemExpression) = \(itemResult)")
                        .font(.custom("CourierNewPSMT", size: 14)).foregroundStyle(Color.grey100)
                }
                .padding(.top, .spacing4)
            }
        }
        .padding(.spacing10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
    }

    private func resultSection<Content: View>(_ label: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(label.uppercased())
                .font(.omXs.weight(.bold))
                .foregroundStyle(Color.grey70)
            content()
        }
    }

    private func modeLabel(_ mode: String) -> String {
        [
            "numeric": "Numeric", "symbolic": "Symbolic", "solve": "Solve",
            "simplify": "Simplify", "diff": "Differentiate", "integrate": "Integrate",
            "convert": "Convert"
        ][mode] ?? mode
    }
}

private struct ReminderSkillCard: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    let data: [String: AnyCodable]
    let status: EmbedStatus
    let mode: EmbedDisplayMode

    private var prompt: String? { EmbedFieldReader.string(data, keys: ["prompt", "message"]) }
    private var trigger: String? { EmbedFieldReader.string(data, keys: ["trigger_at_formatted", "datetime"]) }
    private var target: String? { EmbedFieldReader.string(data, keys: ["target_type"]) }
    private var warning: String? { EmbedFieldReader.string(data, keys: ["email_notification_warning"]) }
    private var error: String? { EmbedFieldReader.string(data, keys: ["error"]) }
    private var reminderId: String? { EmbedFieldReader.string(data, keys: ["reminder_id"]) }
    private var isRepeating: Bool { data["is_repeating"]?.value as? Bool == true }
    private var isActive: Bool {
        let timestamp = (data["trigger_at"]?.value as? NSNumber)?.doubleValue ?? 0
        return timestamp > Date().timeIntervalSince1970
    }

    var body: some View {
        Group {
            if mode == .preview { preview } else { fullscreen }
        }
    }

    private var preview: some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            if status == .processing {
                HStack(spacing: .spacing6) {
                    Circle().fill(Color.grey20).frame(width: 32, height: 32)
                    VStack(alignment: .leading, spacing: .spacing4) {
                        RoundedRectangle(cornerRadius: .radius1).fill(Color.grey20).frame(maxWidth: .infinity).frame(height: 14)
                        RoundedRectangle(cornerRadius: .radius1).fill(Color.grey20).frame(width: 110, height: 14)
                    }
                }
            } else if status == .error || error != nil {
                HStack(spacing: .spacing4) {
                    Text("❌")
                    Text(error ?? AppStrings.genericProcessingError)
                        .font(.omXs)
                        .foregroundStyle(Color.error)
                }
                .padding(.spacing5)
                .background(Color.error.opacity(0.05))
                .clipShape(RoundedRectangle(cornerRadius: .radius2))
            } else {
                if let prompt, !prompt.isEmpty {
                    Text(promptPreview(prompt))
                        .font(.omXs)
                        .foregroundStyle(Color.grey80)
                        .lineLimit(3)
                        .padding(.horizontal, .spacing5)
                        .padding(.vertical, .spacing4)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius2))
                        .overlay(alignment: .leading) { Color.warning.frame(width: 3) }
                }
                if let trigger {
                    HStack(spacing: .spacing4) {
                        Text("🕑").font(.omH3)
                        Text(trigger).font(.omSmall.weight(.medium)).foregroundStyle(Color.grey80)
                    }
                }
                HStack(spacing: .spacing3) {
                    if let target {
                        targetBadge(target)
                    }
                    if isRepeating {
                        Text(LocalizationManager.shared.text("embeds.reminder.repeating"))
                            .font(.omTiny.weight(.medium))
                            .foregroundStyle(Color.warning)
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, 3)
                            .background(Color.warning.opacity(0.1))
                            .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    }
                }
                if let warning {
                    HStack(alignment: .top, spacing: .spacing3) {
                        Text("⚠")
                        Text(warning).font(.omXxs).foregroundStyle(Color.warning)
                    }
                    .padding(.spacing4)
                    .background(Color.warning.opacity(0.05))
                    .clipShape(RoundedRectangle(cornerRadius: .radius2))
                }
            }
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("reminder-embed-preview")
    }

    private var fullscreen: some View {
        VStack(alignment: .leading, spacing: .spacing10) {
            if let error {
                Text(error).font(.omP).foregroundStyle(Color.error)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else {
                VStack(alignment: .leading, spacing: .spacing8) {
                    if let trigger {
                        HStack(spacing: .spacing6) {
                            Text("🕑").font(.omH3)
                            VStack(alignment: .leading, spacing: .spacing2) {
                                Text(LocalizationManager.shared.text("embeds.reminder.scheduled_for"))
                                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                                Text(trigger).font(.omH4.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                            }
                        }
                    }
                    if let target {
                        HStack {
                            Text(LocalizationManager.shared.text("embeds.reminder.target_type"))
                                .foregroundStyle(Color.fontSecondary)
                            Spacer()
                            targetBadge(target)
                        }
                    }
                    HStack {
                        Text(LocalizationManager.shared.text("embeds.reminder.repeating"))
                            .foregroundStyle(Color.fontSecondary)
                        Spacer()
                        Text(isRepeating ? LocalizationManager.shared.text("embeds.reminder.yes") : LocalizationManager.shared.text("embeds.reminder.no"))
                            .foregroundStyle(Color.fontPrimary)
                    }
                    if let reminderId {
                        HStack {
                            Text(LocalizationManager.shared.text("embeds.reminder.id"))
                                .foregroundStyle(Color.fontSecondary)
                            Spacer()
                            Text(String(reminderId.prefix(8)) + "…")
                                .monospaced()
                                .foregroundStyle(Color.fontPrimary)
                        }
                    }
                    if let warning {
                        HStack(alignment: .top, spacing: .spacing3) {
                            Text("⚠")
                            Text(warning).font(.omXs).foregroundStyle(Color.warning)
                        }
                        .padding(.spacing4)
                        .background(Color.warning.opacity(0.05))
                        .clipShape(RoundedRectangle(cornerRadius: .radius2))
                    }
                }
                .font(.omSmall)
                .padding(horizontalSizeClass == .compact ? .spacing8 : .spacing10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20))
                if !isActive {
                    Text("⌛  \(LocalizationManager.shared.text("embeds.reminder.already_fired"))")
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.spacing4)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius2))
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.top, .spacing4)
                }
            }
        }
        .padding(horizontalSizeClass == .compact ? .spacing8 : .spacing12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityIdentifier("reminder-embed-fullscreen")
    }

    private func targetBadge(_ target: String) -> some View {
        let isNew = target == "new_chat"
        return Text(LocalizationManager.shared.text(isNew ? "common.new_chat" : "embeds.reminder.existing_chat"))
            .font(.omTiny.weight(.medium))
            .foregroundStyle(isNew ? Color.buttonPrimary : Color.chatRainbowGreen)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, 3)
            .background((isNew ? Color.buttonPrimary : Color.chatRainbowGreen).opacity(0.1))
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
    }

    private func promptPreview(_ value: String) -> String {
        let lines = value.components(separatedBy: "\n")
        let first = lines.prefix(3).joined(separator: "\n")
        return lines.count > 3 || first.count > 150
            ? String(first.prefix(150)) + "..."
            : first
    }
}

struct WeatherForecastSkillCard: View {
    let data: [String: AnyCodable]
    let childEmbeds: [EmbedRecord]
    let status: EmbedStatus
    let mode: EmbedDisplayMode
    let onOpenEmbed: (EmbedRecord) -> Void

    private var days: [[String: Any]] {
        if mode == .fullscreen && !childEmbeds.isEmpty {
            let hydrated = childEmbeds.compactMap { $0.rawData?.mapValues(\.value) }
            if !hydrated.isEmpty { return hydrated }
        }
        let inline = EmbedFieldReader.dictionaryArray(data, key: "results")
        let preview = inline.isEmpty ? EmbedFieldReader.dictionaryArray(data, key: "preview_results") : inline
        if mode == .preview {
            let previewResults = EmbedFieldReader.dictionaryArray(data, key: "preview_results")
            if !previewResults.isEmpty { return previewResults }
        }
        if !preview.isEmpty { return preview }
        return childEmbeds.compactMap { child in
            child.rawData?.mapValues(\.value)
        }
    }

    var body: some View {
        Group {
            if status == .finished && !days.isEmpty {
                if mode == .preview {
                    dayStrip(count: 4)
                } else {
                    fullscreenGrid
                }
            } else {
                Text(status == .error ? AppStrings.genericProcessingError : AppStrings.loading)
                    .font(.omXs)
                    .foregroundStyle(status == .error ? Color.error : Color.grey70)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .leading)
        .accessibilityIdentifier("weather-forecast-preview")
    }

    private func dayStrip(count: Int) -> some View {
        HStack(spacing: 7) {
            ForEach(0..<min(count, days.count), id: \.self) { index in
                dayPill(days[index])
                    .frame(maxWidth: .infinity)
            }
        }
        .accessibilityIdentifier("weather-forecast-day-strip")
    }

    private func dayPill(_ day: [String: Any]) -> some View {
        let date = day["date"] as? String ?? ""
        let icon = day["icon"] as? String
        let condition = day["condition"] as? String
        let minimum = number(day["temperature_min_c"])
        let maximum = number(day["temperature_max_c"])
        let rain = number(day["precipitation_probability_max_pct"])
        return VStack(spacing: 4) {
            Text(Self.weekday(date))
                .font(.omXxs).foregroundStyle(Color.grey70)
            Image("weather-condition-\(Self.meteoconSlug(icon: icon, condition: condition))")
                .renderingMode(.original)
                .resizable()
                .scaledToFit()
                .frame(width: 34, height: 34)
                .shadow(color: Color.grey100.opacity(0.14), radius: 8, x: 0, y: 4)
                .accessibilityHidden(true)
            Text(temperature(minimum, maximum))
                .font(.omXs.weight(.semibold)).foregroundStyle(Color.grey100)
                .lineLimit(1).minimumScaleFactor(0.75)
            Text("\(Int((rain ?? 0).rounded()))% \(AppStrings.weatherForecastRain)")
                .font(.omXxs).foregroundStyle(Color.grey70)
        }
        .padding(.horizontal, 4)
        .padding(.top, 8)
        .padding(.bottom, 9)
        .frame(maxWidth: .infinity)
        .background {
            Color.grey0.opacity(0.86)
                .overlay {
                    LinearGradient.appWeather
                        .opacity(0.20)
                        .mask {
                            RadialGradient(
                                colors: [.black, .clear],
                                center: UnitPoint(x: 0.5, y: 0.18),
                                startRadius: 0,
                                endRadius: 48
                            )
                        }
                }
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
        .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey20, lineWidth: 1))
        .shadow(color: Color.grey100.opacity(0.07), radius: 9, x: 0, y: 7)
        .accessibilityIdentifier("weather-forecast-day-pill")
    }

    private var fullscreenGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 240), spacing: .spacing6)], spacing: .spacing6) {
            ForEach(Array(days.enumerated()), id: \.offset) { index, day in
                let child = childEmbeds.indices.contains(index) ? childEmbeds[index] : weatherDayRecord(day, index: index)
                EmbedPreviewCard(embed: child, allEmbedRecords: [child.id: child]) {
                    onOpenEmbed(child)
                }
                .frame(width: 300, height: 200)
            }
        }
        .frame(maxWidth: 680)
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing8)
        .frame(maxWidth: .infinity)
        .accessibilityIdentifier("weather-forecast-fullscreen-grid")
    }

    private func weatherDayRecord(_ day: [String: Any], index: Int) -> EmbedRecord {
        let fields = day.mapValues { AnyCodable($0) }
        return EmbedRecord(
            id: day["embed_id"] as? String ?? "forecast-day-\(index)",
            type: EmbedType.weatherDay.rawValue,
            status: .finished,
            data: .raw(fields),
            parentEmbedId: nil,
            appId: "weather",
            skillId: nil,
            embedIds: nil,
            createdAt: nil
        )
    }

    private func number(_ value: Any?) -> Double? {
        if let number = value as? NSNumber { return number.doubleValue }
        if let string = value as? String { return Double(string) }
        return nil
    }

    private func temperature(_ minimum: Double?, _ maximum: Double?) -> String {
        switch (minimum, maximum) {
        case let (min?, max?): return "\(Int(min.rounded()))° / \(Int(max.rounded()))°"
        case let (min?, nil): return "\(Int(min.rounded()))°"
        case let (nil, max?): return "\(Int(max.rounded()))°"
        default: return "—"
        }
    }

    static func weekday(_ date: String) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        guard let value = formatter.date(from: date) else { return String(date.dropFirst(5)) }
        return value.formatted(.dateTime.weekday(.abbreviated))
    }

    static func meteoconSlug(icon: String?, condition: String?) -> String {
        let normalized = "\(icon ?? "") \(condition ?? "")"
            .lowercased()
            .replacingOccurrences(of: "_", with: "-")
        if let wmoStart = normalized.range(of: "wmo-")?.upperBound {
            let digits = normalized[wmoStart...].prefix(while: { $0.isNumber })
            if let code = Int(digits) {
                if [95, 96, 99].contains(code) { return "thunderstorms-day-rain" }
                if [71, 73, 75, 77, 85, 86].contains(code) { return "snow" }
                if [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82].contains(code) { return "rain" }
                if [45, 48].contains(code) { return "fog-day" }
                if code == 3 { return "overcast" }
                if [1, 2].contains(code) { return "partly-cloudy-day" }
            }
        }
        if ["thunder", "storm", "lightning"].contains(where: normalized.contains) { return "thunderstorms-day-rain" }
        if ["snow", "sleet", "hail"].contains(where: normalized.contains) { return "snow" }
        if ["rain", "drizzle", "shower"].contains(where: normalized.contains) { return "rain" }
        if ["fog", "mist", "haze"].contains(where: normalized.contains) { return "fog-day" }
        if normalized.contains("wind") { return "wind" }
        if normalized.contains("overcast") { return "overcast" }
        if normalized.contains("cloud") {
            if normalized.contains("partly") {
                return normalized.contains("night") || normalized.contains("moon")
                    ? "partly-cloudy-night" : "partly-cloudy-day"
            }
            return "cloudy"
        }
        if normalized.contains("night") || normalized.contains("moon") { return "clear-night" }
        return "clear-day"
    }
}

struct FinanceCheckAccountsSkillCard: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    // The web chart and positive totals use --color-app-finance-end.
    private static let incomeColor = Color(hex: 0x2CB81E)

    let data: [String: AnyCodable]
    let status: EmbedStatus
    let mode: EmbedDisplayMode
    let piiMappings: [PIIMapping]
    let hasPIIMappings: Bool
    let isPIIRevealed: Bool
    let onTogglePII: () -> Void

    @State private var selectedAccount = ""
    @State private var selectedSource = ""
    @State private var selectedCategory = ""
    @State private var selectedDirection = ""
    @State private var selectedState = ""
    @State private var selectedPlaceholder = ""
    @State private var startDate = ""
    @State private var endDate = ""

    private var overview: [String: Any] {
        if let overview = data["overview"]?.value as? [String: Any] { return overview }
        let source = EmbedFieldReader.dictionaryArray(data, key: "results").first
            ?? data.mapValues(\.value)
        if let overview = source["overview"] as? [String: Any] { return overview }
        guard source.keys.contains(where: { $0.hasPrefix("overview_") }) else { return [:] }
        let summaries = source.reduce(into: [String: Any]()) { result, item in
            if item.key.hasPrefix("overview_summaries_") {
                result[String(item.key.dropFirst("overview_summaries_".count))] = item.value
            }
        }
        return [
            "accounts": source["overview_accounts"] ?? [],
            "transactions": source["overview_transactions"] ?? [],
            "summaries": summaries
        ]
    }

    private var summaries: [String: Any] { overview["summaries"] as? [String: Any] ?? [:] }
    private var accounts: [[String: Any]] { overview["accounts"] as? [[String: Any]] ?? [] }
    private var transactions: [[String: Any]] { overview["transactions"] as? [[String: Any]] ?? [] }
    private var currency: String {
        (accounts + transactions).compactMap { $0["currency"] as? String }.first ?? "EUR"
    }
    private var income: Double {
        number(summaries["income_total"]) ?? transactions.filter { $0["direction"] as? String == "income" }
            .reduce(0) { $0 + (number($1["amount"]) ?? 0) }
    }
    private var expenses: Double {
        number(summaries["expense_total"]) ?? transactions.filter { $0["direction"] as? String == "expense" }
            .reduce(0) { $0 + abs(number($1["amount"]) ?? 0) }
    }
    private var net: Double { number(summaries["net_total"]) ?? income - expenses }
    private var balance: Double? {
        let balances = accounts.compactMap { number($0["balance"]) }
        return balances.isEmpty ? nil : balances.reduce(0, +)
    }
    private var summary: String? { data["summary"]?.value as? String }
    private var provider: String? { data["provider"]?.value as? String }
    private var accountCount: Int { EmbedFieldReader.int(data, keys: ["account_count"]) ?? accounts.count }
    private var transactionCount: Int { EmbedFieldReader.int(data, keys: ["transaction_count"]) ?? transactions.count }
    private var filteredTransactions: [[String: Any]] {
        transactions.filter { item in
            let posted = String((item["posted_at"] as? String ?? "").prefix(10))
            return (selectedAccount.isEmpty || item["account_ref"] as? String == selectedAccount)
                && (selectedSource.isEmpty || item["source_ref"] as? String == selectedSource)
                && (selectedCategory.isEmpty || item["category"] as? String == selectedCategory)
                && (selectedDirection.isEmpty || item["direction"] as? String == selectedDirection)
                && (selectedState.isEmpty || item["state"] as? String == selectedState)
                && (selectedPlaceholder.isEmpty || item["counterparty_placeholder"] as? String == selectedPlaceholder)
                && (startDate.isEmpty || posted >= startDate)
                && (endDate.isEmpty || posted <= endDate)
        }
    }
    private var filteredAccounts: [[String: Any]] {
        let includedRefs = Set(filteredTransactions.compactMap { $0["account_ref"] as? String })
        return accounts.filter { account in
            let ref = account["account_ref"] as? String ?? ""
            return selectedAccount.isEmpty || ref == selectedAccount || includedRefs.contains(ref)
        }
    }
    private var filteredBalance: Double? {
        let balances = filteredAccounts.compactMap { number($0["balance"]) }
        return balances.isEmpty ? nil : balances.reduce(0, +)
    }
    private var trend: [[String: Any]] {
        Array((summaries["time_series"] as? [[String: Any]] ?? [])
            .sorted { ($0["bucket"] as? String ?? "") < ($1["bucket"] as? String ?? "") }
            .suffix(6))
    }

    var body: some View {
        Group {
            if mode == .preview { previewBody } else { fullscreenBody }
        }
    }

    private var previewBody: some View {
        VStack(alignment: .leading, spacing: 7) {
            VStack(alignment: .leading, spacing: 3) {
                Text(AppStrings.financeNetCashFlow.uppercased())
                    .font(.omXxs.weight(.bold))
                    .foregroundStyle(Color.fontSecondary)
                Text(overview.isEmpty ? "No balance" : money(net))
                    .font(.omLg.weight(.bold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
                    .accessibilityIdentifier("finance-net-cash-flow")
            }
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack(spacing: 6) {
                    HStack(spacing: 5) {
                        Icon("revolut_business", size: 13)
                            .foregroundStyle(Color.fontSecondary)
                        Text(provider ?? "Revolut Business")
                            .font(.omXs)
                    }
                    .accessibilityIdentifier("finance-provider-pill")
                    Text((data["period"]?.value as? String ?? "monthly").replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.omXs)
                }
                Text("\(AppStrings.financeCashBalance) \(balance.map(money) ?? "No balance")")
                    .font(.omXs)
            }
            .foregroundStyle(Color.fontSecondary)
            .lineLimit(1)
            if !trend.isEmpty {
                trendChart(height: 34)
                HStack(spacing: 6) {
                    HStack(spacing: 4) {
                        Circle().fill(Self.incomeColor).frame(width: 7, height: 7)
                        Text("\(AppStrings.financeIncome) \(money(income))")
                    }
                    HStack(spacing: 4) {
                        Circle().fill(Color.warning).frame(width: 7, height: 7)
                        Text("\(AppStrings.financeExpenses) \(money(expenses))")
                    }
                }
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
            } else {
                Text(summary ?? "\(accountCount) \(AppStrings.financeAccounts) · \(transactionCount) \(AppStrings.financeTransactions)")
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(3)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .leading)
        .accessibilityIdentifier("finance-check-accounts-preview")
    }

    private var fullscreenBody: some View {
        Group {
        if overview.isEmpty {
            Text(summary ?? "No account data available.")
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity, minHeight: 240)
                .accessibilityIdentifier("finance-empty-state")
        } else {
        VStack(alignment: .leading, spacing: 18) {
            if hasPIIMappings {
                Button(action: onTogglePII) {
                    HStack(spacing: .spacing3) {
                        Icon(isPIIRevealed ? "hidden" : "visible", size: 16)
                        Text(isPIIRevealed ? AppStrings.piiHide : AppStrings.piiShow)
                    }
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.buttonPrimary)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("finance-toggle-pii")
            }
            Group {
            if horizontalSizeClass == .compact {
                VStack(spacing: .spacing6) {
                    summaryTile(AppStrings.financeNetCashFlow, money(filteredNet), isNet: true)
                    summaryTile(AppStrings.financeIncome, money(filteredIncome), highlight: Self.incomeColor)
                    summaryTile(AppStrings.financeExpenses, money(filteredExpenses), highlight: .warning)
                    summaryTile(AppStrings.financeCashBalance, filteredBalance.map(money) ?? "No balance")
                }
            } else {
                HStack(spacing: .spacing6) {
                    summaryTile(AppStrings.financeNetCashFlow, money(filteredNet), isNet: true)
                    summaryTile(AppStrings.financeIncome, money(filteredIncome), highlight: Self.incomeColor)
                    summaryTile(AppStrings.financeExpenses, money(filteredExpenses), highlight: .warning)
                    summaryTile(AppStrings.financeCashBalance, filteredBalance.map(money) ?? "No balance")
                }
            }
            }
            .accessibilityIdentifier("finance-summary-grid")
            VStack(alignment: .leading, spacing: .spacing8) {
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text("Income and expenses over time").font(.omLg.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                    Text("\((data["period"]?.value as? String ?? "monthly").replacingOccurrences(of: "_", with: " ")) buckets from \(provider ?? "Revolut Business").")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
                if !trend.isEmpty { trendChart(height: 118, showsLabels: true) }
                else { Text(AppStrings.financeNoMatches).font(.omXs).foregroundStyle(Color.fontSecondary) }
            }
            .padding(.spacing10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20))
            .accessibilityIdentifier("finance-fullscreen-chart")
            VStack(alignment: .leading, spacing: .spacing8) {
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(AppStrings.financeFilters).font(.omLg.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                    Text("Filter saved data by account, source, date, category, direction, state, or placeholder.")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
                LazyVGrid(columns: [GridItem(.flexible())], spacing: .spacing6) { filterControls }
            }
            .padding(.spacing10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20))
            .accessibilityIdentifier("finance-filters")
            VStack(alignment: .leading, spacing: .spacing8) {
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(AppStrings.financeAccounts).font(.omLg.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                    Text("\(filteredAccounts.count) account\(filteredAccounts.count == 1 ? "" : "s") in view.")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: .spacing6)], spacing: .spacing6) {
                    ForEach(Array(filteredAccounts.enumerated()), id: \.offset) { _, account in
                        VStack(alignment: .leading, spacing: .spacing3) {
                            Text(account["display_label"] as? String ?? account["account_ref"] as? String ?? "—")
                                .font(.omXs).foregroundStyle(Color.fontPrimary).lineLimit(1)
                            Text(number(account["balance"]).map(money) ?? "No balance")
                                .font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary).lineLimit(1)
                            Text(account["source_ref"] as? String ?? "")
                                .font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                        }
                        .padding(.spacing6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.grey10.opacity(0.68))
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                }
            }
            .padding(.spacing10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20))
            .accessibilityIdentifier("finance-account-list")
            VStack(alignment: .leading, spacing: .spacing8) {
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(AppStrings.financeTransactions).font(.omLg.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                    Text("\(filteredTransactions.count) redacted transaction\(filteredTransactions.count == 1 ? "" : "s") match.")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
                if filteredTransactions.isEmpty {
                    Text(AppStrings.financeNoMatches).font(.omSmall).foregroundStyle(Color.fontSecondary)
                } else {
                    ScrollView(.horizontal) {
                        VStack(spacing: 0) {
                            HStack(spacing: .spacing6) {
                                ForEach(["Date", "Counterparty", "Category", "Account", "Amount", "State"], id: \.self) { label in
                                    Text(label.uppercased()).font(.omXxs.weight(.bold)).frame(maxWidth: .infinity, alignment: .leading)
                                }
                            }
                            .foregroundStyle(Color.fontSecondary)
                            .padding(.spacing6)
                            .background(LinearGradient.appFinance.opacity(0.09))
                            ForEach(Array(filteredTransactions.enumerated()), id: \.offset) { _, transaction in
                                transactionRow(transaction)
                            }
                        }
                        .frame(minWidth: 760)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20))
                    }
                }
            }
            .padding(.spacing10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20))
            .accessibilityIdentifier("finance-transaction-list")
        }
        .frame(maxWidth: 1100, alignment: .leading)
        .padding(.horizontal, horizontalSizeClass == .compact ? .spacing5 : .spacing8)
        .padding(.top, horizontalSizeClass == .compact ? .spacing10 : .spacing16)
        .padding(.bottom, 120)
        .frame(maxWidth: .infinity)
        }
        }
    }

    @ViewBuilder
    private var filterControls: some View {
        financeFilter(AppStrings.financeAccount, key: "account_ref", selection: $selectedAccount, id: "finance-filter-account")
        financeFilter(AppStrings.financeSource, key: "source_ref", selection: $selectedSource, id: "finance-filter-source")
        dateFilter(AppStrings.financeFrom, selection: $startDate, id: "finance-filter-start-date")
        dateFilter(AppStrings.financeTo, selection: $endDate, id: "finance-filter-end-date")
        financeFilter(AppStrings.financeCategory, key: "category", selection: $selectedCategory, id: "finance-filter-category")
        financeFilter(AppStrings.financeDirection, key: "direction", selection: $selectedDirection, id: "finance-filter-direction")
        financeFilter(AppStrings.financeState, key: "state", selection: $selectedState, id: "finance-filter-state")
        financeFilter(AppStrings.financePlaceholder, key: "counterparty_placeholder", selection: $selectedPlaceholder, id: "finance-filter-placeholder")
    }

    private func financeFilter(_ title: String, key: String, selection: Binding<String>, id: String) -> some View {
        let values = Array(Set(transactions.compactMap { $0[key] as? String }.filter { !$0.isEmpty })).sorted()
        return FinanceCompactFilter(
            title: title,
            options: [OMDropdownOption("", label: AppStrings.financeAll)] + values.map { OMDropdownOption($0, label: $0) },
            selection: selection,
            identifier: id
        )
    }

    private func dateFilter(_ title: String, selection: Binding<String>, id: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(title).font(.omXs.weight(.semibold)).foregroundStyle(Color.fontSecondary)
            TextField("", text: selection)
                .font(.omXs)
                .foregroundStyle(Color.fontPrimary)
                .textFieldStyle(.plain)
                .padding(.horizontal, .spacing6)
                .frame(height: 40)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
                .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey30))
                .accessibilityIdentifier(id)
        }
    }

    private func summaryTile(_ label: String, _ value: String, isNet: Bool = false, highlight: Color? = nil) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(label).font(.omXxs).foregroundStyle(Color.fontSecondary)
            Text(value)
                .font((isNet ? Font.omXxl : .omXl).weight(.bold))
                .foregroundStyle(highlight ?? Color.fontPrimary)
                .lineLimit(1)
            if isNet {
                Text("Income - expenses for the selected period and accounts.")
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20))
    }

    private func transactionRow(_ transaction: [String: Any]) -> some View {
        HStack(spacing: .spacing6) {
            Text(transaction["posted_at"] as? String ?? "—")
            Text(Self.counterpartyLabel(
                in: transaction,
                mappings: piiMappings,
                revealed: hasPIIMappings && isPIIRevealed
            ))
            Text(transaction["category"] as? String ?? "—")
            Text(accountLabel(for: transaction["account_ref"] as? String))
            Text(money(number(transaction["amount"]) ?? 0))
                .foregroundStyle(transaction["direction"] as? String == "expense" ? Color.warning : Self.incomeColor)
            Text(transaction["state"] as? String ?? "unknown")
        }
        .frame(minWidth: 760)
        .padding(.spacing6)
        .font(.omXs)
        .foregroundStyle(Color.fontPrimary)
        .overlay(alignment: .bottom) { Color.grey20.frame(height: 1) }
        .accessibilityIdentifier("finance-transaction-row")
    }

    private func accountLabel(for reference: String?) -> String {
        guard let reference else { return "—" }
        return accounts.first(where: { $0["account_ref"] as? String == reference })?["display_label"] as? String ?? reference
    }

    /// Finance counterparties live in nested transactions, outside ChatView's
    /// top-level embed restoration. Reveal only through the shared chat mapping.
    static func counterpartyLabel(
        in transaction: [String: Any],
        mappings: [PIIMapping],
        revealed: Bool
    ) -> String {
        let placeholder = transaction["counterparty_placeholder"] as? String ?? "—"
        guard revealed else { return placeholder }
        return PIIDetector.restorePII(in: placeholder, mappings: mappings)
    }

    private var filteredIncome: Double {
        filteredTransactions.filter { $0["direction"] as? String == "income" }
            .reduce(0) { $0 + (number($1["amount"]) ?? 0) }
    }
    private var filteredExpenses: Double {
        filteredTransactions.filter { $0["direction"] as? String == "expense" }
            .reduce(0) { $0 + abs(number($1["amount"]) ?? 0) }
    }
    private var filteredNet: Double { filteredIncome - filteredExpenses }

    private func number(_ value: Any?) -> Double? {
        if let number = value as? NSNumber { return number.doubleValue }
        if let string = value as? String { return Double(string) }
        return nil
    }

    private func money(_ amount: Double) -> String {
        amount.formatted(.currency(code: currency).precision(.fractionLength(abs(amount) >= 1000 ? 0 : 2)))
    }

    private func trendChart(height: CGFloat, showsLabels: Bool = false) -> some View {
        VStack(spacing: showsLabels ? .spacing5 : 0) {
        GeometryReader { geometry in
            let maximum = max(1, trend.reduce(0) {
                max($0, max(number($1["income"]) ?? 0, number($1["expense"]) ?? 0))
            })
            Path { path in
                for (index, bucket) in trend.enumerated() {
                    let point = CGPoint(
                        x: geometry.size.width * CGFloat(index) / CGFloat(max(1, trend.count - 1)),
                        y: geometry.size.height * (1 - CGFloat(max(0, number(bucket["income"]) ?? 0) / maximum))
                    )
                    if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
                }
            }
            .stroke(Self.incomeColor, style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round))
            Path { path in
                for (index, bucket) in trend.enumerated() {
                    let point = CGPoint(
                        x: geometry.size.width * CGFloat(index) / CGFloat(max(1, trend.count - 1)),
                        y: geometry.size.height * (1 - CGFloat(max(0, number(bucket["expense"]) ?? 0) / maximum))
                    )
                    if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
                }
            }
            .stroke(Color.warning, style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round))
        }
        .frame(height: height)
        if showsLabels {
            HStack {
                ForEach(Array(trend.enumerated()), id: \.offset) { _, bucket in
                    Text(bucket["bucket"] as? String ?? "")
                        .font(.omXxs)
                        .foregroundStyle(Color.fontSecondary)
                    Spacer(minLength: 0)
                }
            }
        }
        }
        .padding(.horizontal, showsLabels ? .spacing8 : .spacing5)
        .padding(.top, showsLabels ? .spacing8 : .spacing3)
        .padding(.bottom, showsLabels ? .spacing6 : .spacing8)
        .background(showsLabels ? Color.grey10.opacity(0.62) : Color.grey0.opacity(0.84))
        .clipShape(RoundedRectangle(cornerRadius: showsLabels ? .radius6 : .radiusFull))
        .overlay(RoundedRectangle(cornerRadius: showsLabels ? .radius6 : .radiusFull).stroke(Color.grey20, lineWidth: showsLabels ? 0 : 1))
        .accessibilityIdentifier("finance-income-expense-chart")
    }
}

private struct FinanceCompactFilter: View {
    let title: String
    let options: [OMDropdownOption]
    @Binding var selection: String
    let identifier: String
    @State private var isExpanded = false

    private var selectedLabel: String {
        options.first(where: { $0.id == selection })?.label ?? AppStrings.financeAll
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(title).font(.omXs.weight(.semibold)).foregroundStyle(Color.fontSecondary)
            Button { isExpanded.toggle() } label: {
                HStack {
                    Text(selectedLabel).font(.omXs).foregroundStyle(Color.fontPrimary)
                    Spacer()
                    Icon("chevron-down", size: 14).foregroundStyle(Color.fontSecondary)
                }
                .padding(.horizontal, .spacing6)
                .frame(height: 40)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
                .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey30))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier(identifier)
            if isExpanded {
                VStack(spacing: 0) {
                    ForEach(options) { option in
                        Button {
                            selection = option.id
                            isExpanded = false
                        } label: {
                            Text(option.label)
                                .font(.omXs)
                                .foregroundStyle(Color.fontPrimary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.spacing4)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
                .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey30))
            }
        }
    }
}
