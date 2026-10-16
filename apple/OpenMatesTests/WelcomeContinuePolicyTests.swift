// Specification: specifications/features/continue-carousel/specification.yml
import XCTest
@testable import OpenMates

final class WelcomeContinuePolicyTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDecorativeClocksPauseForInvisibleInactiveOrReducedMotionSurfaces() {
        XCTAssertTrue(WelcomeDecorativeMotionPolicy.runs(paneVisible: true, scrollVisible: true,
            sceneActive: true, windowVisible: true, reduced: false))
        for flags in [(false, true, true, true, false), (true, false, true, true, false),
                      (true, true, false, true, false), (true, true, true, false, false), (true, true, true, true, true)] {
            XCTAssertFalse(WelcomeDecorativeMotionPolicy.runs(paneVisible: flags.0, scrollVisible: flags.1,
                sceneActive: flags.2, windowVisible: flags.3, reduced: flags.4))
        }
        XCTAssertEqual(WelcomeDecorativeMotionPolicy.minimumInterval, 0.05, accuracy: 0.0001,
            "20Hz caps decorative invalidation; orb periods still use wall-clock time")
    }

    let now = Date(timeIntervalSince1970: 1_800_000_000)
    private func memory(_ id: String, offset: Double, endOffset: Double? = nil) -> SettingsMemoryEntry {
        let formatter = ISO8601DateFormatter()
        var fields: [String: SettingsMemoryValue] = ["embed_id": .string(id), "title": .string("Public event fixture"),
            "date_start": .string(formatter.string(from: now.addingTimeInterval(offset)))]
        if let endOffset { fields["date_end"] = .string(formatter.string(from: now.addingTimeInterval(endOffset))) }
        return .init(id: id, appId: "events", categoryId: "saved_events", key: id, value: "", createdAt: 0,
            updatedAt: 0, version: 1, isExample: false, fields: fields)
    }
    private func reminder(_ target: String, type: String, offset: Double) -> WelcomeContinueReminder {
        .init(triggerAt: now.addingTimeInterval(offset).timeIntervalSince1970, targetType: type,
              targetChatId: type == "chat" ? target : nil, targetEmbedId: type == "embed" ? target : nil, status: "pending")
    }
    // contract-test: supporting surface=gui.apple assertions=continue-carousel.saved-item.start-time-gated
    func testSavedStartOwnsTwentyFourHourBoundaryDespiteEarlierReminder() {
        let entries = [memory("outside", offset: 24 * 3600 + 1), memory("boundary", offset: 24 * 3600), memory("near", offset: 3600)]
        let items = WelcomeContinuePolicy.items(entries: entries, reminders: [reminder("outside", type: "embed", offset: 60)], now: now)
        XCTAssertEqual(items.map(\.id), ["embed:near", "embed:boundary"])
        XCTAssertEqual(items[0].priority.timestamp, now.addingTimeInterval(3600))
        XCTAssertTrue(UpcomingMemoryActivityPolicy.candidates(from: entries, now: now).contains { $0.memoryID == "outside" })
        XCTAssertGreaterThan(UpcomingMemoryActivityPolicy.candidates(from: entries, now: now).first(where: { $0.memoryID == "boundary" })!.activityStartsAt, now,
            "Continue promotion does not open the separate four-hour Live Activity window")
    }
    // contract-test: supporting surface=gui.apple assertions=continue-carousel.chat.reminder-gated,continue-carousel.saved-item.start-time-gated
    func testRanksDueSoonOngoingAndNearestSavedItemsAndDeduplicatesTargets() {
        let items = WelcomeContinuePolicy.items(entries: [memory("near", offset: 3600), memory("far", offset: 7200), memory("ongoing", offset: -48 * 3600, endOffset: 3600)],
            reminders: [reminder("due", type: "chat", offset: -60), reminder("soon", type: "chat", offset: 60), reminder("soon", type: "chat", offset: 120), reminder("late", type: "chat", offset: 24 * 3600 + 1)], now: now)
        XCTAssertEqual(items.map(\.id), ["chat:due", "chat:soon", "embed:ongoing", "embed:near", "embed:far"])
        XCTAssertEqual(items[1].priority.timestamp, now.addingTimeInterval(60))
    }
    // contract-test: supporting surface=gui.apple assertions=continue-carousel.saved-item.start-time-gated
    func testUnlinkedExamplesOldItemsAndFallbackPreviewContract() {
        var unlinked = memory("unlinked", offset: 3600); unlinked.fields.removeValue(forKey: "embed_id")
        let valid = memory("valid", offset: 3600)
        let example = SettingsMemoryEntry(id: "example", appId: valid.appId, categoryId: valid.categoryId,
            key: "", value: "", createdAt: 0, updatedAt: 0, version: 1, isExample: true, fields: valid.fields)
        XCTAssertEqual(WelcomeContinuePolicy.items(entries: [unlinked, example, memory("old", offset: -12 * 3600 - 1), valid], reminders: [], now: now).map(\.id), ["embed:valid"])
        let record = WelcomeContinuePolicy.savedRecord(valid)
        XCTAssertEqual(record?.id, "valid")
        XCTAssertEqual(record?.type, "events-event")
        XCTAssertEqual(record?.rawData?["title"]?.value as? String, "Public event fixture")
        XCTAssertNil(record?.encryptedContent)
    }
    // contract-test: supporting surface=gui.apple assertions=continue-carousel.saved-item.start-time-gated,apple-live-activities.memories.upcoming
    func testCalendarOnlyDateIsContinueEligibleButNeverActivityEligible() {
        var entry = memory("calendar", offset: 0)
        entry.fields.removeValue(forKey: "date_start")
        let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd"
        entry.fields["date"] = .string(formatter.string(from: now))
        XCTAssertEqual(WelcomeContinuePolicy.items(entries: [entry], reminders: [], now: now).count, 1)
        XCTAssertTrue(UpcomingMemoryActivityPolicy.candidates(from: [entry], now: now).isEmpty)
    }
    @MainActor
    // contract-test: supporting surface=gui.apple assertions=continue-carousel.saved-item.start-time-gated,apple-live-activities.lifecycle.isolation
    func testCacheRejectsStaleFullReadAndOldAccountAndClearsOnLogout() {
        let service = WelcomeContinueService(observesSync: false)
        let token = UUID(), team = APIRequestTeamContext(epoch: 0, teamID: nil)
        let scope = UpcomingMemorySnapshotScope(accountID: "disposable-account", server: .development, scope: token, team: team)
        service.configure(accountID: scope.accountID, server: scope.server, generation: token, team: team, authenticated: true)
        var saved = memory("saved", offset: 3600)
        saved.fields["date_start"] = .string(ISO8601DateFormatter().string(from: Date().addingTimeInterval(3600)))
        service.accept(.init(scope: scope, entries: [saved], revision: 10))
        XCTAssertEqual(service.items.map(\.id), ["embed:saved"])
        service.accept(.init(scope: scope, entries: [], revision: 12, change: .removed("saved")))
        service.accept(.init(scope: scope, entries: [saved], revision: 11))
        XCTAssertTrue(service.items.isEmpty)
        service.configure(accountID: "other-account", server: .development, generation: UUID(), team: team, authenticated: true)
        service.accept(.init(scope: scope, entries: [saved], revision: 99))
        XCTAssertTrue(service.items.isEmpty)
        service.configure(accountID: nil, server: .development, generation: UUID(), team: team, authenticated: false)
        XCTAssertTrue(service.items.isEmpty)
    }

}
