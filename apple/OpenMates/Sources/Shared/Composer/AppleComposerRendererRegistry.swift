// Native composer preview registry derived from the web write-mode registry.
// Every insertable embed type maps to an explicit native preview family.
// Structural groups delegate to their registered child type without fallback.
// Lifecycle support is declared centrally for deterministic host behavior.
// This semantic layer owns no SwiftUI views, encryption keys, or persisted data.

import Foundation

enum AppleComposerEmbedLifecycleState: String, CaseIterable, Codable, Sendable {
    case draft
    case uploading
    case processing
    case transcribing
    case finished
    case error
    case cancelled
}

enum AppleComposerPreviewFamily: Equatable, Sendable {
    case recording
    case appSkillUse
    case repository
    case code
    case document
    case pcbSchematic
    case electronicsComponent
    case event
    case fitnessLocation
    case fitnessClass
    case appointment
    case homeListing
    case image
    case imageResult
    case email
    case place
    case map
    case mathPlot
    case mindMap
    case website
    case recipe
    case pdf
    case product
    case socialPost
    case travelConnection
    case travelStay
    case video
    case weatherDay
    case sheet
    case focusActivation
    case group(childType: String)
}

struct AppleComposerPreviewDescriptor: Equatable, Sendable {
    let embedType: String
    let family: AppleComposerPreviewFamily
    let rendererIdentifier: String
    let supportedStates: Set<AppleComposerEmbedLifecycleState>

    init(
        embedType: String = "",
        family: AppleComposerPreviewFamily,
        rendererIdentifier: String,
        supportedStates: Set<AppleComposerEmbedLifecycleState> = Set(AppleComposerEmbedLifecycleState.allCases)
    ) {
        self.embedType = embedType
        self.family = family
        self.rendererIdentifier = rendererIdentifier
        self.supportedStates = supportedStates
    }

    func withEmbedType(_ embedType: String) -> Self {
        Self(
            embedType: embedType,
            family: family,
            rendererIdentifier: rendererIdentifier,
            supportedStates: supportedStates
        )
    }
}

enum AppleComposerRendererRegistryError: Error, Equatable {
    case expectedEmbedNode(String)
    case missingLifecycleStatus(String)
    case unsupportedLifecycleStatus(String)
}

struct AppleComposerRendererRegistry: Sendable {
    static let shared = Self()

    let notApplicableTypes: Set<String> = []

    var registeredTypes: [String] {
        Self.descriptors.keys.sorted()
    }

    func descriptor(for embedType: String) -> AppleComposerPreviewDescriptor? {
        Self.descriptors[embedType]?.withEmbedType(embedType)
    }

    func lifecycleState(for node: ComposerNodeV1) throws -> AppleComposerEmbedLifecycleState {
        guard node.kind == "embed" else {
            throw AppleComposerRendererRegistryError.expectedEmbedNode(node.id)
        }
        guard let status = node.status else {
            throw AppleComposerRendererRegistryError.missingLifecycleStatus(node.id)
        }
        guard let state = AppleComposerEmbedLifecycleState(rawValue: status) else {
            throw AppleComposerRendererRegistryError.unsupportedLifecycleStatus(status)
        }
        return state
    }

    private static let descriptors: [String: AppleComposerPreviewDescriptor] = [
        "recording": .init(family: .recording, rendererIdentifier: "RecordingRenderer"),
        "app-skill-use": .init(family: .appSkillUse, rendererIdentifier: "AppSkillUseComposerPreview"),
        "code-repo": .init(family: .repository, rendererIdentifier: "RepositoryComposerPreview"),
        "code-repo-group": .init(family: .group(childType: "code-repo"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "code-code": .init(family: .code, rendererIdentifier: "CodeEmbedRenderer"),
        "code-code-group": .init(family: .group(childType: "code-code"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "docs-doc": .init(family: .document, rendererIdentifier: "DocsRenderer"),
        "docs-doc-group": .init(family: .group(childType: "docs-doc"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "electronics-pcb-schematic": .init(family: .pcbSchematic, rendererIdentifier: "PcbSchematicComposerPreview"),
        "electronics-pcb-schematic-group": .init(family: .group(childType: "electronics-pcb-schematic"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "electronics-component": .init(family: .electronicsComponent, rendererIdentifier: "ElectronicsComponentComposerPreview"),
        "electronics-component-group": .init(family: .group(childType: "electronics-component"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "events-event": .init(family: .event, rendererIdentifier: "EventEmbedRenderer"),
        "events-event-group": .init(family: .group(childType: "events-event"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "fitness-location": .init(family: .fitnessLocation, rendererIdentifier: "FitnessLocationComposerPreview"),
        "fitness-location-group": .init(family: .group(childType: "fitness-location"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "fitness-class": .init(family: .fitnessClass, rendererIdentifier: "FitnessClassComposerPreview"),
        "fitness-class-group": .init(family: .group(childType: "fitness-class"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "health-appointment": .init(family: .appointment, rendererIdentifier: "AppointmentRenderer"),
        "health-appointment-group": .init(family: .group(childType: "health-appointment"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "home-listing": .init(family: .homeListing, rendererIdentifier: "HomeListingRenderer"),
        "home-listing-group": .init(family: .group(childType: "home-listing"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "image": .init(family: .image, rendererIdentifier: "ImageEmbedRenderer"),
        "images-image-result": .init(family: .imageResult, rendererIdentifier: "ImageResultEmbedRenderer"),
        "images-image-result-group": .init(family: .group(childType: "images-image-result"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "mail-email": .init(family: .email, rendererIdentifier: "MailRenderer"),
        "mail-email-group": .init(family: .group(childType: "mail-email"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "maps-place": .init(family: .place, rendererIdentifier: "MapsPlaceRenderer"),
        "maps-place-group": .init(family: .group(childType: "maps-place"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "maps": .init(family: .map, rendererIdentifier: "MapsLocationRenderer"),
        "math-plot": .init(family: .mathPlot, rendererIdentifier: "MathPlotRenderer"),
        "mindmaps-mindmap": .init(family: .mindMap, rendererIdentifier: "MindMapEmbedRenderer"),
        "mindmaps-mindmap-group": .init(family: .group(childType: "mindmaps-mindmap"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "web-website": .init(family: .website, rendererIdentifier: "WebsiteEmbedRenderer"),
        "web-website-group": .init(family: .group(childType: "web-website"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "nutrition-recipe": .init(family: .recipe, rendererIdentifier: "RecipeRenderer"),
        "nutrition-recipe-group": .init(family: .group(childType: "nutrition-recipe"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "pdf": .init(family: .pdf, rendererIdentifier: "PDFRenderer"),
        "shopping-product": .init(family: .product, rendererIdentifier: "ShoppingProductRenderer"),
        "shopping-product-group": .init(family: .group(childType: "shopping-product"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "social-media-post": .init(family: .socialPost, rendererIdentifier: "SocialPostComposerPreview"),
        "social-media-post-group": .init(family: .group(childType: "social-media-post"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "travel-connection": .init(family: .travelConnection, rendererIdentifier: "TravelConnectionEmbedRenderer"),
        "travel-connection-group": .init(family: .group(childType: "travel-connection"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "travel-stay": .init(family: .travelStay, rendererIdentifier: "TravelStayEmbedRenderer"),
        "travel-stay-group": .init(family: .group(childType: "travel-stay"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "videos-video": .init(family: .video, rendererIdentifier: "VideoRenderer"),
        "videos-video-group": .init(family: .group(childType: "videos-video"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "weather-day": .init(family: .weatherDay, rendererIdentifier: "WeatherDayComposerPreview"),
        "weather-day-group": .init(family: .group(childType: "weather-day"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "sheets-sheet": .init(family: .sheet, rendererIdentifier: "SheetRenderer"),
        "sheets-sheet-group": .init(family: .group(childType: "sheets-sheet"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
        "focus-mode-activation": .init(family: .focusActivation, rendererIdentifier: "FocusModeComposerPreview"),
        "app-skill-use-group": .init(family: .group(childType: "app-skill-use"), rendererIdentifier: "AppleComposerGroupedEmbedPreview"),
    ]
}
