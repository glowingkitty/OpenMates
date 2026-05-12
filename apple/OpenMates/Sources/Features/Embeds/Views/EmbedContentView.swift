// Content router — dispatches embed rendering to type-specific views.
// Mirrors the EMBED_PREVIEW_COMPONENTS / EMBED_FULLSCREEN_COMPONENTS registry.
// Supports preview (compact card) and fullscreen (full detail) modes.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

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
    let previewVariant: EmbedPreviewCardVariant
    let onOpenEmbed: (EmbedRecord) -> Void

    init(
        embed: EmbedRecord,
        mode: EmbedDisplayMode,
        allEmbedRecords: [String: EmbedRecord] = [:],
        codePreviewActive: Bool = false,
        previewVariant: EmbedPreviewCardVariant = .compact,
        onOpenEmbed: @escaping (EmbedRecord) -> Void = { _ in }
    ) {
        self.embed = embed
        self.mode = mode
        self.allEmbedRecords = allEmbedRecords
        self.codePreviewActive = codePreviewActive
        self.previewVariant = previewVariant
        self.onOpenEmbed = onOpenEmbed
    }

    private var embedType: EmbedType? {
        EmbedType(rawValue: embed.type)
    }

    private var shouldUseCompositeRenderer: Bool {
        embed.isAppSkillUse || embedType?.isComposite == true
    }

    private var rawData: [String: AnyCodable]? {
        guard let data = embed.data, case .raw(let dict) = data else { return nil }
        return dict
    }

    var body: some View {
        Group {
            if shouldUseCompositeRenderer {
                AppSkillUseRenderer(embed: embed, allEmbedRecords: allEmbedRecords, mode: mode, onOpenEmbed: onOpenEmbed)
            } else {
            switch embedType {
            // Web
            case .webSearch, .newsSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "results")
            case .webWebsite:
                WebsiteEmbedRenderer(data: rawData, mode: mode)
            case .webRead:
                WebReadEmbedRenderer(data: rawData, mode: mode)
            case .wiki:
                WikiRenderer(data: rawData, mode: mode)

            // Code
            case .codeCode:
                CodeEmbedRenderer(
                    data: rawData,
                    mode: mode,
                    previewActive: codePreviewActive,
                    isLargePreview: previewVariant == .large
                )
            case .codeGetDocs:
                CodeGetDocsEmbedRenderer(data: rawData, mode: mode)

            // Documents
            case .docsDoc:
                DocsRenderer(data: rawData, mode: mode)
            case .sheetsSheet:
                SheetRenderer(data: rawData, mode: mode)

            // Videos
            case .videosSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "videos")
            case .videosVideo:
                VideoRenderer(data: rawData, mode: mode)
            case .videosTranscript:
                TranscriptRenderer(data: rawData, mode: mode)

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

            // Health
            case .healthSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "appointments")
            case .healthAppointment:
                AppointmentRenderer(data: rawData, mode: mode)

            // Home
            case .homeSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "listings")
            case .homeListing:
                HomeListingRenderer(data: rawData, mode: mode)

            // Nutrition
            case .nutritionSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "recipes")
            case .nutritionRecipe:
                RecipeRenderer(data: rawData, mode: mode)

            // Shopping
            case .shoppingSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "products")
            case .shoppingProduct:
                ShoppingProductRenderer(data: rawData, mode: mode)

            // Mail
            case .mailEmail:
                MailRenderer(data: rawData, mode: mode)
            case .mailSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "emails")

            // Math
            case .mathPlot:
                MathPlotRenderer(data: rawData, mode: mode)
            case .mathCalculate:
                MathCalculateRenderer(data: rawData, mode: mode)

            // Audio
            case .recording:
                RecordingRenderer(data: rawData, mode: mode)

            // PDF
            case .pdf:
                PDFRenderer(data: rawData, mode: mode)

            // Misc
            case .focusModeActivation:
                FocusModeRenderer(data: rawData, mode: mode)
            case .reminderSet:
                ReminderRenderer(data: rawData, mode: mode)

            default:
                GenericEmbedRenderer(data: rawData, mode: mode, type: embed.type)
            }
            }
        }
    }
}
