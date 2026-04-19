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

    private var embedType: EmbedType? {
        EmbedType(rawValue: embed.type)
    }

    private var rawData: [String: AnyCodable]? {
        guard let data = embed.data, case .raw(let dict) = data else { return nil }
        return dict
    }

    var body: some View {
        Group {
            switch embedType {
            // Web
            case .webSearch, .newsSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "results")
            case .webWebsite:
                WebsiteRenderer(data: rawData, mode: mode)
            case .webRead:
                WebReadRenderer(data: rawData, mode: mode)

            // Code
            case .codeCode:
                CodeRenderer(data: rawData, mode: mode)
            case .codeGetDocs:
                DocsRenderer(data: rawData, mode: mode)

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
                ImageResultRenderer(data: rawData, mode: mode)
            case .imagesGenerate, .imagesGenerateDraft:
                ImageGenerateRenderer(data: rawData, mode: mode)
            case .image:
                ImageRenderer(data: rawData, mode: mode)

            // Maps
            case .mapsSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "places")
            case .mapsPlace:
                MapsPlaceRenderer(data: rawData, mode: mode)
            case .maps:
                MapsLocationRenderer(data: rawData, mode: mode)

            // Travel
            case .travelConnections:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "connections")
            case .travelConnection:
                TravelConnectionRenderer(data: rawData, mode: mode)
            case .travelStays:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "stays")
            case .travelStay:
                TravelStayRenderer(data: rawData, mode: mode)
            case .travelPriceCalendar:
                TravelPriceCalendarRenderer(data: rawData, mode: mode)
            case .travelFlight:
                TravelFlightRenderer(data: rawData, mode: mode)

            // Events
            case .eventsSearch:
                SearchResultsRenderer(data: rawData, mode: mode, resultLabel: "events")
            case .eventsEvent:
                EventRenderer(data: rawData, mode: mode)

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
