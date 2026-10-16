// Web: services/savedEmbedMemoryService.ts and five supported fullscreen components.
// Synthetic metadata, ephemeral encryption key and in-process transport only.
import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class NativeEmbedMemoryActionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testFiveFamiliesBuildCanonicalKeysAndPayloadsAndExcludeSearchParents() throws {
        let event = try XCTUnwrap(NativeEmbedMemoryConfig.config(type: .eventsEvent, embedID: "event-child", content: ["id": "event-42", "title": "Public event", "provider": "meetup", "venue_city": "Berlin", "venue_country": "Germany"]))
        XCTAssertEqual(event.appID, "events"); XCTAssertEqual(event.itemKey, "saved_events.event-42")
        XCTAssertEqual(event.fields["provider"], .string("Meetup")); XCTAssertEqual(event.fields["location"], .string("Berlin, Germany"))
        let health = try XCTUnwrap(NativeEmbedMemoryConfig.config(type: .healthAppointment, embedID: "health-child", content: ["name": "Public doctor", "speciality": "General", "booking_url": "https://example.invalid/book", "slot_datetime": "2026-10-04T00:30:00+02:00"]))
        XCTAssertEqual(health.itemKey, "appointments.https://example.invalid/book.2026-10-04T00:30:00+02:00")
        XCTAssertEqual(health.fields["date"], .string("2026-10-03")); XCTAssertEqual(health.fields["where"], .string("Public doctor · General"))
        let connection = try XCTUnwrap(NativeEmbedMemoryConfig.config(type: .travelConnection, embedID: "connection-child", content: ["hash": "route-hash", "legs": [["origin": "A", "departure": "start"], ["destination": "B", "arrival": "end"]]]))
        XCTAssertEqual(connection.itemKey, "saved_connections.route-hash"); XCTAssertEqual(connection.fields["origin"], .string("A")); XCTAssertEqual(connection.fields["arrival"], .string("end"))
        let stay = try XCTUnwrap(NativeEmbedMemoryConfig.config(type: .travelStay, embedID: "stay-child", content: ["name": "Public stay", "link": "https://example.invalid/stay", "extracted_total_rate": 123.6, "overall_rating": 4.5, "amenities": (1...10).map { "Amenity \($0)" }]))
        XCTAssertEqual(stay.itemKey, "saved_stays.https://example.invalid/stay"); XCTAssertEqual(stay.fields["price"], .string("EUR 124"))
        XCTAssertEqual(stay.fields["rating"], .number(4.5)); XCTAssertFalse(stay.fields["notes"]!.display.contains("Amenity 9"))
        let home = try XCTUnwrap(NativeEmbedMemoryConfig.config(type: .homeListing, embedID: "home-child", content: ["title": "Public home", "url": "https://www.example.invalid/listing", "listing_type": "apartment", "size_sqm": 80]))
        XCTAssertEqual(home.itemKey, "saved_listings.https://www.example.invalid/listing"); XCTAssertEqual(home.fields["provider"], .string("example.invalid")); XCTAssertEqual(home.fields["notes"], .string("80 m² · Apartment"))
        for config in [event, health, connection, stay, home] { XCTAssertNotNil(config.fields["embed_id"]) }
        XCTAssertNil(NativeEmbedMemoryConfig.config(type: .eventsSearch, embedID: "search", content: [:]))
        XCTAssertNil(NativeEmbedMemoryConfig.config(type: .eventsEvent, embedID: "", content: [:]))
    }

    private func entry(_ config: NativeEmbedMemoryConfig, key: String? = nil, app: String? = nil, category: String? = nil, example: Bool = false) -> SettingsMemoryEntry {
        .init(id: UUID().uuidString, appId: app ?? config.appID, categoryId: category ?? config.categoryID,
              key: key ?? config.itemKey, value: "{}", createdAt: 1, updatedAt: 1, version: 1, isExample: example, fields: config.fields)
    }
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testSavedMatchingUsesKeyOrEmbedWithinExactCategoryAndNeverExamples() throws {
        let config = try XCTUnwrap(NativeEmbedMemoryConfig.config(type: .eventsEvent, embedID: "child", content: ["title": "Public event"]))
        let sameKey = entry(config), sameEmbed = entry(config, key: "legacy-key")
        XCTAssertEqual(config.savedEntry(in: [sameKey])?.id, sameKey.id)
        XCTAssertEqual(config.savedEntry(in: [sameEmbed])?.id, sameEmbed.id)
        XCTAssertNil(config.savedEntry(in: [entry(config, app: "travel"), entry(config, category: "other"), entry(config, example: true)]))
    }

    private let metadata = Data("{\"apps\":{\"events\":{\"settings_and_memories\":[{\"id\":\"saved_events\",\"name\":\"Saved events\"}]}}}".utf8)
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testEncryptedSaveAndForgetToggleOnlyAfterSuccessfulTransport() async throws {
        let config = try XCTUnwrap(NativeEmbedMemoryConfig.config(type: .eventsEvent, embedID: "public-child", content: ["title": "Synthetic private payload"]))
        let key = SymmetricKey(size: .bits256), scope = UUID(), server = ServerProfile.current()
        var sent: SettingsEncryptedMemoryRecord?, deletes = 0, failDelete = true
        var service: SettingsMemoryService!
        service = SettingsMemoryService(transport: { method, path, body, _ in
            if path.contains("metadata") { return self.metadata }
            if method == .get { return Data("{\"memories\":[]}".utf8) }
            if method == .delete {
                XCTAssertEqual(service.state, .pending)
                XCTAssertNotNil(config.savedEntry(in: service.entries))
                if failDelete { throw URLError(.notConnectedToInternet) }
                deletes += 1; return Data("{}".utf8)
            }
            XCTAssertEqual(service.state, .pending)
            XCTAssertNil(config.savedEntry(in: service.entries))
            let body = try XCTUnwrap(body)
            XCTAssertFalse(String(decoding: body, as: UTF8.self).contains("Synthetic private payload"))
            let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
            sent = try JSONDecoder().decode(SettingsEncryptedMemoryRecord.self, from: JSONSerialization.data(withJSONObject: try XCTUnwrap(object["entry"])))
            return Data("{}".utf8)
        }, keyLoader: { _ in key }, environment: .init(currentAccountID: { "synthetic" }, scopeGeneration: { scope }, serverProfile: { server }), teamContext: { .init(epoch: 0, teamID: nil) }, observesSync: false, liveActivitySnapshot: { _ in })
        await service.load()
        let category = try XCTUnwrap(service.categories.first)
        let saved = await service.save(entry: nil, category: category, key: config.itemKey, fields: config.fields)
        XCTAssertTrue(saved)
        let encrypted = try XCTUnwrap(sent)
        let plaintext = try await CryptoManager.shared.decryptContent(base64String: encrypted.encryptedItemJson, key: key)
        let decoded = try SettingsMemoryService.decodePayload(plaintext, fallbackKey: "")
        XCTAssertEqual(decoded.key, config.itemKey); XCTAssertEqual(decoded.value, config.fields)
        let selected = try XCTUnwrap(config.savedEntry(in: service.entries))
        let failedDelete = await service.delete(selected)
        XCTAssertFalse(failedDelete); XCTAssertNotNil(config.savedEntry(in: service.entries))
        failDelete = false
        let deleted = await service.delete(selected)
        XCTAssertTrue(deleted); XCTAssertEqual(deletes, 1); XCTAssertNil(config.savedEntry(in: service.entries))
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testDelayedSaveCannotPublishIntoChangedAccountAndErrorRetainsAddState() async throws {
        let config = try XCTUnwrap(NativeEmbedMemoryConfig.config(type: .eventsEvent, embedID: "child", content: ["title": "Public event"]))
        let key = SymmetricKey(size: .bits256), scope = UUID(), server = ServerProfile.current()
        var account: String? = "first", fail = false
        let service = SettingsMemoryService(transport: { method, path, _, _ in
            if path.contains("metadata") { return self.metadata }
            if method == .get { return Data("{\"memories\":[]}".utf8) }
            if fail { throw URLError(.notConnectedToInternet) }
            await Task.yield(); account = "second"
            return Data("{}".utf8)
        }, keyLoader: { _ in key }, environment: .init(currentAccountID: { account }, scopeGeneration: { scope }, serverProfile: { server }), teamContext: { .init(epoch: 0, teamID: nil) }, observesSync: false, liveActivitySnapshot: { _ in })
        await service.load()
        let category = try XCTUnwrap(service.categories.first)
        let stale = await service.save(entry: nil, category: category, key: config.itemKey, fields: config.fields)
        XCTAssertFalse(stale); XCTAssertNil(config.savedEntry(in: service.entries)); XCTAssertFalse(service.isAuthenticated)
        fail = true; await service.load()
        let failed = await service.save(entry: nil, category: category, key: config.itemKey, fields: config.fields)
        XCTAssertFalse(failed); XCTAssertNil(config.savedEntry(in: service.entries))
        guard case .error = service.state else { return XCTFail("Transport failure must remain visible") }
    }
}
