// Focused unit contracts for native Memories and Mates settings parity.
// Tests use public metadata and synthetic values only; they never access accounts,
// encryption keys, persisted memory plaintext, provider APIs, or network state.
// Native composer handoff is verified without launching a browser or sending chat data.

import XCTest
@testable import OpenMates

@MainActor
final class SettingsMemoriesMatesParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chat-processing-feedback.selected-mate-identity,settings-ui.parity.web-apple-shell
    func testCanonicalMateCatalogAndMentionSyntax() {
        XCTAssertEqual(CanonicalSettingsMateCatalog.all.count, 17)
        XCTAssertEqual(CanonicalSettingsMateCatalog.all.first?.id, "software_development")
        XCTAssertEqual(CanonicalSettingsMateCatalog.all.last?.id, "onboarding_support")
        XCTAssertEqual(CanonicalSettingsMateCatalog.all.first?.mentionSyntax, "@mate:software_development")
        XCTAssertTrue(CanonicalSettingsMateCatalog.all.allSatisfy { !$0.artworkName.isEmpty })
        XCTAssertTrue(CanonicalSettingsMateCatalog.all.allSatisfy(\.isAvailable))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageMateSettingsTargetResolvesCanonicalDetail() {
        XCTAssertEqual(
            CanonicalSettingsMateCatalog.mate(id: "electrical_engineering")?.id,
            "electrical_engineering"
        )
        XCTAssertNil(CanonicalSettingsMateCatalog.mate(id: "openmates_official"))
        XCTAssertNil(CanonicalSettingsMateCatalog.mate(id: "unknown"))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-processing-feedback.selected-mate-identity,settings-ui.parity.web-apple-shell
    func testSettingsComposerHandoffIsNativeAndSingleUse() {
        SettingsComposerHandoff.request(mention: "@mate:finance")

        XCTAssertTrue(SettingsComposerHandoff.hasPendingMention)
        XCTAssertEqual(SettingsComposerHandoff.consume(), "@mate:finance")
        XCTAssertFalse(SettingsComposerHandoff.hasPendingMention)
        XCTAssertNil(SettingsComposerHandoff.consume())
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testMemoryEntryUsesCanonicalEntryMentionSyntax() {
        let entry = SettingsMemoryEntry(
            id: "entry-1",
            appId: "travel",
            categoryId: "preferred_activities",
            key: "key",
            value: "value",
            createdAt: 1,
            updatedAt: 1,
            version: 1,
            isExample: false
        )

        XCTAssertEqual(entry.mentionSyntax, "@memory-entry:travel:preferred_activities:entry-1")
    }
}
