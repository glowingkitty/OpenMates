// Content router — dispatches embed rendering to type-specific views.
// Mirrors the EMBED_PREVIEW_COMPONENTS / EMBED_FULLSCREEN_COMPONENTS registry.
// Supports preview (compact card) and fullscreen (full detail) modes.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
//                specifications/features/app-skills/code-run/specification.yml
// Assertions: chats.rendering.assistant-document-convergence, code-run.surface-parity

import SwiftUI

enum EmbedDisplayMode {
    case preview
    case fullscreen
}

struct EmbedContentView: View {
    let embed: EmbedRecord
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let codePreviewActive: Bool
    let codeRunViewModel: CodeRunViewModel?
    let chatId: String?
    let hasPIIMappings: Bool
    let piiMappings: [PIIMapping]
    let isPIIRevealed: Bool
    let onTogglePII: () -> Void
    let previewVariant: EmbedPreviewCardVariant
    let onOpenEmbed: (EmbedRecord) -> Void
    let onSheetDisplayedRowsChange: (([[String]]) -> Void)?

    init(
        embed: EmbedRecord,
        mode: EmbedDisplayMode,
        allEmbedRecords: [String: EmbedRecord] = [:],
        codePreviewActive: Bool = false,
        codeRunViewModel: CodeRunViewModel? = nil,
        chatId: String? = nil,
        hasPIIMappings: Bool = false,
        piiMappings: [PIIMapping] = [],
        isPIIRevealed: Bool = false,
        onTogglePII: @escaping () -> Void = {},
        previewVariant: EmbedPreviewCardVariant = .compact,
        onOpenEmbed: @escaping (EmbedRecord) -> Void = { _ in },
        onSheetDisplayedRowsChange: (([[String]]) -> Void)? = nil
    ) {
        self.embed = embed
        self.mode = mode
        self.allEmbedRecords = allEmbedRecords
        self.codePreviewActive = codePreviewActive
        self.codeRunViewModel = codeRunViewModel
        self.chatId = chatId
        self.hasPIIMappings = hasPIIMappings
        self.piiMappings = piiMappings
        self.isPIIRevealed = isPIIRevealed
        self.onTogglePII = onTogglePII
        self.previewVariant = previewVariant
        self.onOpenEmbed = onOpenEmbed
        self.onSheetDisplayedRowsChange = onSheetDisplayedRowsChange
    }

    private var embedType: EmbedType? {
        EmbedType.normalized(rawValue: embed.type)
    }

    private var shouldUseCompositeRenderer: Bool {
        embed.isAppSkillUse || embedType?.isComposite == true
    }

    private var rawData: [String: AnyCodable]? {
        guard let data = embed.data, case .raw(let dict) = data else { return nil }
        return dict
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if HostingEmbedKind.isSearch(embed) {
                HostingSearchEmbedRenderer(embed: embed, mode: mode, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
            } else if HostingEmbedKind.isDomain(embed) {
                HostingDomainEmbedRenderer(embed: embed, mode: mode)
            } else if shouldUseCompositeRenderer {
                AppSkillUseRenderer(
                    embed: embed,
                    allEmbedRecords: allEmbedRecords,
                    mode: mode,
                    hasPIIMappings: hasPIIMappings,
                    piiMappings: piiMappings,
                    isPIIRevealed: isPIIRevealed,
                    onTogglePII: onTogglePII,
                    onOpenEmbed: onOpenEmbed
                )
            } else {
            switch embedType {
            // Web
            case .webSearch:
                WebSearchEmbedRenderer(
                    model: SearchSkillPreviewModel(embed: embed, allEmbedRecords: allEmbedRecords),
                    mode: mode,
                    onOpenEmbed: onOpenEmbed
                )
            case .newsSearch:
                NewsSearchEmbedRenderer(
                    model: SearchSkillPreviewModel(embed: embed, allEmbedRecords: allEmbedRecords),
                    mode: mode,
                    onOpenEmbed: onOpenEmbed
                )
            case .webWebsite:
                if embed.appId == "news" || rawData?["app_id"]?.value as? String == "news" {
                    NewsEmbedRenderer(data: rawData, mode: mode)
                } else {
                    WebsiteEmbedRenderer(data: rawData, mode: mode)
                }
            case .webRead:
                WebReadEmbedRenderer(data: rawData, mode: mode)
            case .businessCompanyFinancialResult:
                BusinessCompanyFinancialResultEmbedRenderer(embed: embed, mode: mode)
            case .wiki:
                WikiRenderer(data: rawData, mode: mode)

            // Code
            case .codeRepoSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "repositories")
            case .codeRepo:
                CodeRepoEmbedRenderer(data: rawData, mode: mode)
            case .codeApplication:
                ApplicationEmbedRenderer(data: rawData, mode: mode)
            case .codeCode:
                CodeEmbedRenderer(
                    data: rawData,
                    embed: embed,
                    embedId: embed.id,
                    chatId: chatId,
                    mode: mode,
                    hasPIIMappings: hasPIIMappings,
                    piiMappings: piiMappings,
                    isPIIRevealed: isPIIRevealed,
                    onTogglePII: onTogglePII,
                    previewActive: codePreviewActive,
                    codeRunViewModel: codeRunViewModel,
                    isLargePreview: previewVariant == .large
                )
            case .codeNotebook:
                NotebookEmbedRenderer(data: rawData, mode: mode)
            case .codeGetDocs:
                CodeGetDocsEmbedRenderer(data: rawData, mode: mode)

            // Design
            case .designSearchIcons:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "icons")
            case .designIconResult:
                DesignIconResultEmbedRenderer(data: rawData, mode: mode)

            // Documents
            case .docsDoc:
                DocsRenderer(data: rawData, mode: mode)
            case .sheetsSheet:
                SheetRenderer(data: rawData, mode: mode,
                              hasPIIMappings: hasPIIMappings, piiMappings: piiMappings,
                              isPIIRevealed: isPIIRevealed,
                              onTogglePII: onTogglePII, onDisplayedRowsChange: onSheetDisplayedRowsChange,
                              isLargePreview: previewVariant == .large)

            // Diagrams
            case .diagramsMermaid:
                MermaidDiagramRenderer(data: rawData, mode: mode)

            // Mind Maps
            case .mindmapsMindmap:
                MindMapEmbedRenderer(data: rawData, mode: mode)

            // 3D Models
            case .models3dSearch:
                Models3DSearchParentRenderer(embed: embed, mode: mode, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
            case .models3dGenerate:
                Models3DGenerateEmbedRenderer(embed: embed, mode: mode)
            case .models3dModelResult:
                Models3DResultEmbedRenderer(embed: embed, mode: mode)

            // Electronics
            case .electronicsSearch:
                ElectronicsSearchParentRenderer(
                    embed: embed,
                    allEmbedRecords: allEmbedRecords,
                    mode: mode,
                    onOpenEmbed: onOpenEmbed
                )
            case .electronicsPcbSchematic:
                PcbSchematicEmbedRenderer(data: rawData, mode: mode, status: embed.status, embedID: embed.id)
            case .electronicsComponent:
                ElectronicsComponentEmbedRenderer(data: rawData, mode: mode)

            // Videos
            case .videosSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "videos")
            case .videosVideo:
                VideoRenderer(data: rawData, mode: mode)
            case .videosTranscript:
                TranscriptRenderer(data: rawData, mode: mode)
            case .videosGenerate:
                VideoGenerateEmbedRenderer(data: rawData, mode: mode)
            case .videosCreate:
                RemotionVideoCreateRenderer(embedId: embed.id, data: rawData, mode: mode)

            // Images
            case .imagesSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "images")
            case .imagesImageResult:
                ImageResultEmbedRenderer(data: rawData, mode: mode)
            case .imagesGenerate, .imagesGenerateDraft:
                ImageGenerateEmbedRenderer(data: rawData, mode: mode)
            case .image:
                ImageEmbedRenderer(data: rawData, mode: mode)

            // Maps
            case .mapsSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "places")
            case .mapsPlace:
                MapsPlaceRenderer(data: rawData, mode: mode)
            case .maps:
                MapsLocationRenderer(data: rawData, mode: mode)

            // Travel
            case .travelConnections:
                TravelSearchEmbedRenderer(
                    embed: embed,
                    data: rawData,
                    mode: mode,
                    allEmbedRecords: allEmbedRecords,
                    onOpenEmbed: onOpenEmbed
                )
            case .travelConnection:
                TravelConnectionEmbedRenderer(data: rawData, mode: mode)
            case .travelStays:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "stays")
            case .travelStay:
                TravelStayEmbedRenderer(data: rawData, mode: mode)
            case .travelPriceCalendar:
                TravelPriceCalendarEmbedRenderer(data: rawData, mode: mode)
            case .travelFlight:
                TravelFlightDetailsEmbedRenderer(data: rawData, mode: mode)

            // Events
            case .eventsSearch:
                EventsSearchEmbedRenderer(
                    embed: embed,
                    data: rawData,
                    mode: mode,
                    allEmbedRecords: allEmbedRecords,
                    onOpenEmbed: onOpenEmbed
                )
            case .eventsEvent:
                EventEmbedRenderer(data: rawData, mode: mode)

            // Fitness
            case .fitnessLocation, .fitnessClass:
                FitnessResultEmbedRenderer(data: rawData, mode: mode)

            // Health
            case .healthSearch:
                SearchDomainParentRenderer(embed: embed, kind: .health, mode: mode,
                                           allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
            case .healthAppointment:
                SearchDomainResultRenderer(data: rawData, kind: .health, mode: mode)

            // Home
            case .homeSearch:
                SearchDomainParentRenderer(embed: embed, kind: .home, mode: mode,
                                           allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
            case .homeListing:
                SearchDomainResultRenderer(data: rawData, kind: .home, mode: mode)

            // Nutrition
            case .nutritionSearch:
                SearchDomainParentRenderer(embed: embed, kind: .nutrition, mode: mode,
                                           allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
            case .nutritionRecipe:
                SearchDomainResultRenderer(data: rawData, kind: .nutrition, mode: mode)

            // Shopping
            case .shoppingSearch:
                SearchDomainParentRenderer(embed: embed, kind: .shopping, mode: mode,
                                           allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
            case .shoppingProduct:
                SearchDomainResultRenderer(data: rawData, kind: .shopping, mode: mode)

            // Mail
            case .mailEmail:
                MailRenderer(data: rawData, mode: mode)
                    .environment(\.embedPIIMappings, piiMappings)
                    .environment(\.embedPIIRevealed, isPIIRevealed)
            case .mailSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "emails")

            // Math
            case .mathPlot:
                MathPlotRenderer(data: rawData, mode: mode)
            case .mathCalculate:
                MathCalculateRenderer(data: rawData, mode: mode)

            // Finance
            case .financeCheckAccounts:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "accounts")

            // Music
            case .musicGenerate:
                MusicGenerateEmbedRenderer(data: rawData, mode: mode)

            // Social media
            case .socialMediaGetPosts, .socialMediaSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "posts")
            case .socialMediaPost:
                SocialMediaPostEmbedRenderer(data: rawData, mode: mode)

            // Tasks
            case .tasksCreate, .tasksSearch:
                TaskWorkflowParentRenderer(embed: embed, kind: .task, mode: mode, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
            case .tasksTask:
                TaskWorkflowEmbedRenderer(embed: embed, kind: .task, mode: mode)

            // Weather
            case .weatherForecast:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "days")
            case .weatherDay:
                WeatherDayEmbedRenderer(data: rawData, mode: mode)

            // Workflows
            case .workflowsCreateOrModify, .workflowsSearch:
                TaskWorkflowParentRenderer(embed: embed, kind: .workflow, mode: mode, allEmbedRecords: allEmbedRecords, onOpenEmbed: onOpenEmbed)
            case .workflowsWorkflow:
                TaskWorkflowEmbedRenderer(embed: embed, kind: .workflow, mode: mode)

            // Audio
            case .recording:
                RecordingRenderer(data: rawData, mode: mode)
            case .audioGenerate:
                GeneratedAudioEmbedRenderer(data: rawData, status: embed.status, skillId: "generate", mode: mode)
            case .audioSpeak:
                GeneratedAudioEmbedRenderer(data: rawData, status: embed.status, skillId: "speak", mode: mode)

            // Calendar
            case .calendarListCalendars, .calendarGetEvents, .calendarCreateEvent,
                 .calendarUpdateEvent, .calendarDeleteEvent:
                CalendarActionEmbedRenderer(
                    embed: embed,
                    data: rawData ?? [:],
                    skillId: embed.skillId ?? embed.type.split(separator: ":").last.map(String.init) ?? "list-calendars",
                    mode: mode
                )

            // PDF
            case .pdf:
                PDFRenderer(data: rawData, mode: mode)
            case .fileFile:
                FileEmbedRenderer(data: rawData, mode: mode, status: embed.status)

            // Misc
            case .focusModeActivation:
                FocusModeRenderer(data: rawData, mode: mode)
            case .reminderSet:
                ReminderRenderer(data: rawData, mode: mode)
            case .reminderList, .reminderCancel:
                ReminderRenderer(data: rawData, mode: mode)

            default:
                GenericEmbedRenderer(data: rawData, mode: mode, type: embed.type)
            }
            }

            if rawData?["learning_mode_shortened"]?.value as? Bool == true {
                Text(AppStrings.learningModeShortenedNotice)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("learning-mode-shortened-notice")
            }
        }
    }
}
