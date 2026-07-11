// Focused unit contracts for native Memories and Mates settings parity.
// Tests use public metadata and synthetic values only; they never access accounts,
// encryption keys, persisted memory plaintext, provider APIs, or network state.
// Native composer handoff is verified without launching a browser or sending chat data.

import XCTest
@testable import OpenMates

@MainActor
final class SettingsMemoriesMatesParityTests: XCTestCase {
    func testCanonicalMateCatalogAndMentionSyntax() {
        XCTAssertEqual(CanonicalSettingsMateCatalog.all.count, 17)
        XCTAssertEqual(CanonicalSettingsMateCatalog.all.first?.id, "software_development")
        XCTAssertEqual(CanonicalSettingsMateCatalog.all.last?.id, "onboarding_support")
        XCTAssertEqual(CanonicalSettingsMateCatalog.all.first?.mentionSyntax, "@mate:software_development")
        XCTAssertTrue(CanonicalSettingsMateCatalog.all.allSatisfy { !$0.artworkName.isEmpty })
        XCTAssertTrue(CanonicalSettingsMateCatalog.all.allSatisfy(\.isAvailable))
    }

    func testSettingsComposerHandoffIsNativeAndSingleUse() {
        SettingsComposerHandoff.request(mention: "@mate:finance")

        XCTAssertTrue(SettingsComposerHandoff.hasPendingMention)
        XCTAssertEqual(SettingsComposerHandoff.consume(), "@mate:finance")
        XCTAssertFalse(SettingsComposerHandoff.hasPendingMention)
        XCTAssertNil(SettingsComposerHandoff.consume())
    }

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
