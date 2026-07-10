// Contract tests for native composer renderer registry completeness.
// The generated web write-mode registry remains the authoritative type set.
// Every composer-capable type must use an explicit native preview family.
// Structural groups delegate to typed child previews instead of a fallback.
// Lifecycle coverage is required before any renderer can enter host surfaces.

import XCTest
@testable import OpenMates

@MainActor
final class AppleComposerRendererRegistryTests: XCTestCase {
    private struct FixtureCatalog: Decodable {
        let schemaVersion: Int
        let lifecycleStates: [String]
        let fixtures: [String: Fixture]

        enum CodingKeys: String, CodingKey {
            case schemaVersion = "schema_version"
            case lifecycleStates = "lifecycle_states"
            case fixtures
        }
    }

    private struct Fixture: Decodable {
        let title: String
        let mediaKind: String

        enum CodingKeys: String, CodingKey {
            case title
            case mediaKind = "media_kind"
        }
    }

    func testRegistryExactlyCoversGeneratedWebWriteModeTypes() throws {
        let expectedTypes = Set([
            "recording", "app-skill-use", "code-repo", "code-repo-group",
            "code-code", "code-code-group", "docs-doc", "docs-doc-group",
            "electronics-pcb-schematic", "electronics-pcb-schematic-group",
            "electronics-component", "electronics-component-group",
            "events-event", "events-event-group", "fitness-location",
            "fitness-location-group", "fitness-class", "fitness-class-group",
            "health-appointment", "health-appointment-group", "home-listing",
            "home-listing-group", "image", "images-image-result",
            "images-image-result-group", "mail-email", "mail-email-group",
            "maps-place", "maps-place-group", "maps", "math-plot",
            "mindmaps-mindmap", "mindmaps-mindmap-group", "web-website",
            "web-website-group", "nutrition-recipe", "nutrition-recipe-group",
            "pdf", "shopping-product", "shopping-product-group",
            "social-media-post", "social-media-post-group", "travel-connection",
            "travel-connection-group", "travel-stay", "travel-stay-group",
            "videos-video", "videos-video-group", "weather-day",
            "weather-day-group", "sheets-sheet", "sheets-sheet-group",
            "focus-mode-activation", "app-skill-use-group",
        ])
        let registry = AppleComposerRendererRegistry.shared

        XCTAssertEqual(
            Set(registry.registeredTypes).union(registry.notApplicableTypes),
            expectedTypes
        )
        XCTAssertTrue(registry.notApplicableTypes.isEmpty)
        XCTAssertEqual(Set(registry.registeredTypes), expectedTypes)
    }

    func testEveryRegisteredTypeHasExplicitFamilyAndAllLifecycleStates() throws {
        let registry = AppleComposerRendererRegistry.shared
        let expectedStates = Set(AppleComposerEmbedLifecycleState.allCases)
        XCTAssertEqual(
            Set(AppleComposerEmbedLifecycleState.allCases.map(\.rawValue)),
            ["draft", "uploading", "processing", "transcribing", "finished", "error", "cancelled"]
        )

        for embedType in registry.registeredTypes {
            let descriptor = try XCTUnwrap(registry.descriptor(for: embedType), embedType)
            XCTAssertEqual(descriptor.embedType, embedType)
            XCTAssertEqual(descriptor.supportedStates, expectedStates, embedType)
            XCTAssertFalse(descriptor.rendererIdentifier.contains("Generic"), embedType)
            XCTAssertFalse(descriptor.rendererIdentifier.isEmpty, embedType)
        }
        XCTAssertNil(registry.descriptor(for: "future-unregistered-embed"))
    }

    func testStructuralGroupsDelegateToTheirRegisteredChildType() throws {
        let registry = AppleComposerRendererRegistry.shared

        for groupType in registry.registeredTypes.filter({ $0.hasSuffix("-group") }) {
            let descriptor = try XCTUnwrap(registry.descriptor(for: groupType))
            let childType = String(groupType.dropLast("-group".count))
            XCTAssertEqual(descriptor.family, .group(childType: childType), groupType)
            XCTAssertNotNil(registry.descriptor(for: childType), childType)
        }
    }

    func testDocumentStatusNormalizesToExplicitLifecycleState() throws {
        let registry = AppleComposerRendererRegistry.shared
        let node = ComposerNodeV1.embed(
            id: "composer:embed:fixture",
            embedType: "recording",
            canonicalSource: "```json\n{\"type\":\"recording\"}\n```",
            referenceOnly: false,
            display: ComposerEmbedDisplayV1(title: "Synthetic recording", mediaKind: "audio")
        )

        for state in AppleComposerEmbedLifecycleState.allCases {
            XCTAssertEqual(
                try registry.lifecycleState(for: node.updatingStatus(state.rawValue)),
                state
            )
        }
        XCTAssertThrowsError(try registry.lifecycleState(for: node.updatingStatus("future-state")))
    }

    func testSyntheticFixtureCatalogCoversEveryRegisteredTypeAndLifecycle() throws {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let fixtureURL = repositoryRoot
            .appendingPathComponent("shared/composer/fixtures/apple-composer-renderer-v1.json")
        let catalog = try JSONDecoder().decode(
            FixtureCatalog.self,
            from: Data(contentsOf: fixtureURL)
        )
        let registry = AppleComposerRendererRegistry.shared

        XCTAssertEqual(catalog.schemaVersion, 1)
        XCTAssertEqual(Set(catalog.fixtures.keys), Set(registry.registeredTypes))
        XCTAssertEqual(
            Set(catalog.lifecycleStates),
            Set(AppleComposerEmbedLifecycleState.allCases.map(\.rawValue))
        )
        for (embedType, fixture) in catalog.fixtures {
            XCTAssertFalse(fixture.title.isEmpty, embedType)
            XCTAssertEqual(fixture.mediaKind, embedType)
        }
    }
}
