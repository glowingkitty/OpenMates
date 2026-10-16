// Web contract: travel/TravelConnectionEmbedFullscreen.svelte and TravelStayEmbedFullscreen.svelte.
import XCTest
@testable import OpenMates

@MainActor
final class TravelEmbedFormattingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testProviderWallTimesRemainLocalAndExplicitOffsetsConvert() {
        let locale = Locale(identifier: "en_US")
        let berlin = TimeZone(identifier: "Europe/Berlin")!
        XCTAssertEqual(TravelValue.formatTime("2026-03-15T08:30:00", locale: locale, timeZone: berlin), "08:30 AM")
        XCTAssertEqual(TravelValue.formatTime("2026-03-15T10:00:00", locale: locale, timeZone: berlin), "10:00 AM")
        XCTAssertEqual(TravelValue.formatTime("2026-03-15T08:30:00Z", locale: locale, timeZone: berlin), "09:30 AM")
        XCTAssertEqual(TravelValue.formatTime("2026-03-15T08:30:00+01:00", locale: locale, timeZone: berlin), "08:30 AM")
        XCTAssertEqual(TravelValue.formatTime("2026-03-15T08:30:00.000", locale: locale, timeZone: berlin), "08:30 AM")
        XCTAssertEqual(TravelValue.formatTime("2026-03-15T08:30", locale: Locale(identifier: "de_DE"), timeZone: berlin), "08:30")
        XCTAssertEqual(TravelValue.formatTime("unavailable", locale: locale, timeZone: berlin), "unavailable")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testProviderDateKeepsLocalDayNearMidnight() {
        let berlin = TimeZone(identifier: "Europe/Berlin")!
        let locale = Locale(identifier: "en_US")
        XCTAssertEqual(TravelValue.formatDate("2026-03-15T23:30:00", locale: locale, timeZone: berlin), "Sun, Mar 15")
        XCTAssertEqual(TravelValue.formatDate("2026-03-15T23:30:00Z", locale: locale, timeZone: berlin), "Mon, Mar 16")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testStayFullscreenFixtureHasCanonicalNumericRatesAndPreservesPreview() throws {
        let fullscreen = try XCTUnwrap(DevEmbedPreviewFixtures.fullscreenSkill(forRegistryKey: "travel-stay")?.primaryEmbed.rawData)
        XCTAssertEqual(TravelValue.double(fullscreen, ["extracted_rate_per_night"]), 129)
        XCTAssertEqual(TravelValue.double(fullscreen, ["extracted_total_rate"]), 387)
        XCTAssertEqual(TravelValue.string(fullscreen, ["name"]), "Hotel Maximilian")
        XCTAssertNotNil(TravelValue.string(fullscreen, ["thumbnail"]))
        let preview = try XCTUnwrap(DevEmbedPreviewFixtures.skill(forRegistryKey: "travel-stay")?.primaryEmbed.rawData)
        XCTAssertEqual(TravelValue.double(preview, ["price_per_night"]), 129)
        XCTAssertEqual(TravelValue.double(preview, ["extracted_rate_per_night"]), 129)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testConnectionCopyIncludesCanonicalItineraryAndBookingDetails() throws {
        var data = try XCTUnwrap(DevEmbedPreviewFixtures.skill(forRegistryKey: "travel-connection")?.primaryEmbed.rawData)
        data["bookable_seats"] = AnyCodable(2)
        data["last_ticketing_date"] = AnyCodable("2026-03-14")
        let actions = TravelConnectionActions(data: data, locale: Locale(identifier: "en_US"), timeZone: TimeZone(identifier: "Europe/Berlin")!)
        XCTAssertEqual(actions.copyText, """
        Munich (MUC) → London Heathrow (LHR) · One way · EUR 189
        LH

        Munich (MUC) → London Heathrow (LHR)
        Sun, Mar 15 · 2h 30m · Direct

          08:30 AM  MUC
          LH · LH 123 · 2h 30m
          10:00 AM  LHR

        2 seat(s) remaining
        Book by 2026-03-14
        """)
        let file = try XCTUnwrap(actions.calendarFile(now: Date(timeIntervalSince1970: 0)))
        XCTAssertEqual(file.filename, "munich-muc-london-heathrow-lhr-2026-03-15.ics")
        let unfolded = file.content.replacingOccurrences(of: "\r\n ", with: "")
        XCTAssertTrue(unfolded.contains("DTSTART:20260315T073000Z\r\n"))
        XCTAssertTrue(unfolded.contains("DTEND:20260315T090000Z\r\n"))
        XCTAssertTrue(unfolded.contains("SUMMARY:Munich (MUC) → London Heathrow (LHR)"))
        XCTAssertTrue(unfolded.contains("DESCRIPTION:Munich (MUC) → London Heathrow (LHR) | One way | EUR 189\\nLH"))
        XCTAssertTrue(unfolded.contains("URL:https://www.google.com/travel/flights"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testConnectionCalendarCrossesLocalMidnightAndDSTWithExplicitArrival() throws {
        let data = ["origin": AnyCodable("Berlin"), "destination": AnyCodable("London"),
                    "departure": AnyCodable("2026-03-28T23:30:00"),
                    "arrival": AnyCodable("2026-03-29T03:30:00+02:00")]
        let actions = TravelConnectionActions(data: data, locale: Locale(identifier: "en_US"), timeZone: TimeZone(identifier: "Europe/Berlin")!)
        let file = try XCTUnwrap(actions.calendarFile(now: Date(timeIntervalSince1970: 0)))
        XCTAssertTrue(file.content.contains("DTSTART:20260328T223000Z\r\n"))
        XCTAssertTrue(file.content.contains("DTEND:20260329T013000Z\r\n"))
        XCTAssertEqual(file.filename, "berlin-london-2026-03-28.ics")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testConnectionCalendarFallsBackToLegDatesAndEscapesText() throws {
        let data = ["origin": AnyCodable("A, B; C\\D"), "destination": AnyCodable("E"),
                    "legs": AnyCodable([["origin": "A", "destination": "E", "departure": "2026-03-15T08:30:00Z", "arrival": "2026-03-15T08:00:00Z", "segments": []]]),
                    "booking_url": AnyCodable("https://example.test/book")]
        let actions = TravelConnectionActions(data: data, locale: Locale(identifier: "en_US"), timeZone: TimeZone(secondsFromGMT: 0)!)
        let file = try XCTUnwrap(actions.calendarFile(now: Date(timeIntervalSince1970: 0)))
        XCTAssertTrue(file.content.contains("DTSTART:20260315T083000Z\r\n"))
        XCTAssertTrue(file.content.contains("DTEND:20260315T093000Z\r\n"), "An arrival before departure uses the shared one-hour default")
        XCTAssertTrue(file.content.contains("SUMMARY:A\\, B\\; C\\\\D → E"))
        let missing = TravelConnectionActions(data: ["departure": AnyCodable("invalid")])
        XCTAssertNil(missing.calendarFile())
        let masked = try XCTUnwrap(actions.calendarFile(renderText: { $0.replacingOccurrences(of: "A, B; C\\D", with: "[ADDRESS_1]") }))
        XCTAssertFalse(masked.content.contains("C\\\\D"))
        XCTAssertTrue(masked.content.contains("SUMMARY:[ADDRESS_1] → E"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTravelCalendarAcceptsMinutePrecisionLocalAndOffsetDates() throws {
        let berlin = TimeZone(identifier: "Europe/Berlin")!
        for (start, end, expectedStart, expectedEnd) in [
            ("2026-03-15T08:30", "2026-03-15T10:00", "20260315T073000Z", "20260315T090000Z"),
            ("2026-03-15T23:30+01:00", "2026-03-16T01:15+02:00", "20260315T223000Z", "20260315T231500Z"),
            ("2026-03-15T08:30Z", "2026-03-15T10:00Z", "20260315T083000Z", "20260315T100000Z")
        ] {
            let actions = TravelConnectionActions(data: ["departure": AnyCodable(start), "arrival": AnyCodable(end)], timeZone: berlin)
            let file = try XCTUnwrap(actions.calendarFile(now: Date(timeIntervalSince1970: 0)))
            XCTAssertTrue(file.content.contains("DTSTART:\(expectedStart)\r\n"))
            XCTAssertTrue(file.content.contains("DTEND:\(expectedEnd)\r\n"))
        }
        XCTAssertNil(EmbedCalendarFile.build(title: "Health validation preserved", start: "2026-03-15T08:30",
                                             location: nil, description: nil, url: nil, timeZone: berlin))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFlightsCalendarFallbackPrefersProviderBookingContext() throws {
        let context: [String: Any] = ["departure_id": "BER", "arrival_id": "BKK", "outbound_date": "2026-04-01"]
        let data = ["origin": AnyCodable("Berlin"), "destination": AnyCodable("Bangkok"),
                    "departure": AnyCodable("2026-03-15T08:30"), "booking_context": AnyCodable(context)]
        let expected = "https://www.google.com/travel/flights?q=Flights%20from%20BER%20to%20BKK%20on%202026-04-01"
        XCTAssertEqual(TravelConnectionSummary(embedId: nil, data: data).googleFlightsURL, expected)
        let file = try XCTUnwrap(TravelConnectionActions(data: data).calendarFile())
        let unfolded = file.content.replacingOccurrences(of: "\r\n ", with: "")
        XCTAssertTrue(unfolded.contains("URL:" + expected))
        let flat = ["booking_context_departure_id": AnyCodable("BER"), "booking_context_arrival_id": AnyCodable("BKK"),
                    "booking_context_outbound_date": AnyCodable("2026-04-01")]
        XCTAssertEqual(TravelConnectionSummary(embedId: nil, data: flat).googleFlightsURL, expected)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFlightsFallbackPreservesPlainCitiesAndEncodesQuerySeparators() throws {
        let data = ["origin": AnyCodable("São Paulo & Coast"), "destination": AnyCodable("New York?"),
                    "departure": AnyCodable("2026-03-15T08:30:00")]
        let expected = "https://www.google.com/travel/flights?q=Flights%20from%20S%C3%A3o%20Paulo%20%26%20Coast%20to%20New%20York%3F%20on%202026-03-15"
        XCTAssertEqual(TravelConnectionSummary(embedId: nil, data: data).googleFlightsURL, expected)
        let file = try XCTUnwrap(TravelConnectionActions(data: data).calendarFile())
        XCTAssertTrue(file.content.replacingOccurrences(of: "\r\n ", with: "").contains("URL:" + expected))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testEmptySearchKeepsFlattenedRequestRouteDateAndZeroCount() throws {
        let fixture = try travelSearchFixture("zero-provider-empty")
        let model = TravelSearchPresentation(embed: fixture.primaryEmbed, locale: Locale(identifier: "en_US"),
                                             timeZone: TimeZone(secondsFromGMT: 0)!)
        XCTAssertTrue(TravelSearchPresentation.isSearch(fixture.primaryEmbed))
        XCTAssertEqual(model.route, "Berlin → Prague")
        XCTAssertEqual(model.previewDate, "Mon, Oct 5")
        XCTAssertEqual(model.fullscreenDate, "Mon, October 5, 2026")
        XCTAssertEqual(model.resultCount, 0)
        XCTAssertTrue(model.connections.isEmpty)
        XCTAssertTrue(model.providers.isEmpty)
        XCTAssertNil(model.previewProviderText)
        XCTAssertNil(model.priceText())
        let header = EmbedFullscreenHeader(embed: fixture.primaryEmbed)
        XCTAssertFalse(header.headerTitle.contains("app-skill-use"))
        XCTAssertTrue(header.headerTitle.contains("Berlin → Prague"))
        XCTAssertTrue(header.headerSubtitle?.hasPrefix("0 ") == true)
        XCTAssertFalse(AppStrings.localized("embeds.search_no_results").contains("embeds.search_no_results"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testEmptySearchGroupsRemainMetadataAndQueryFallbackSurvives() throws {
        let grouped = try travelSearchFixture("zero-provider-grouped")
        let model = TravelSearchPresentation(embed: grouped.primaryEmbed, locale: Locale(identifier: "en_US"),
                                             timeZone: TimeZone(secondsFromGMT: 0)!)
        XCTAssertEqual(model.route, "Oslo → Bergen")
        XCTAssertEqual(model.previewDate, "Thu, Oct 8")
        XCTAssertEqual(model.resultCount, 0)
        XCTAssertTrue(model.connections.isEmpty, "A search request group is not a returned connection")
        let query = try travelSearchFixture("zero-provider-query")
        let queryModel = TravelSearchPresentation(embed: query.primaryEmbed)
        XCTAssertEqual(queryModel.route, "Night train from Berlin to Prague")
        XCTAssertNil(queryModel.previewDate)
        XCTAssertEqual(queryModel.fullscreenTitle, queryModel.route)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testEmptySearchDoesNotBorrowConnectionsFromAnotherParent() throws {
        let fixture = try travelSearchFixture("zero-provider-empty")
        let unrelated = try XCTUnwrap(DevEmbedPreviewFixtures.skill(forRegistryKey: "travel-connection")?.primaryEmbed)
        let model = TravelSearchPresentation(embed: fixture.primaryEmbed, allEmbedRecords: [unrelated.id: unrelated])
        XCTAssertTrue(model.connections.isEmpty)
        XCTAssertTrue(model.childEmbeds.isEmpty)
        XCTAssertEqual(model.route, "Berlin → Prague")
        XCTAssertEqual(model.resultCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testSearchMetadataCountAndNestedResultsFollowWebPrecedence() throws {
        let fixture = try travelSearchFixture("zero-provider-empty")
        var data = fixture.primaryEmbed.rawData ?? [:]
        data["result_count"] = AnyCodable(4)
        data["provider"] = AnyCodable("Google")
        let metadata = TravelSearchPresentation(embed: fixture.primaryEmbed, data: data)
        XCTAssertEqual(metadata.resultCount, 4)
        XCTAssertTrue(metadata.connections.isEmpty)
        XCTAssertNil(metadata.previewProviderText, "Legacy attribution requires actual results")
        data["results"] = AnyCodable([["query": "Request", "result_count": 9, "results": [
            ["origin": "Munich", "destination": "London", "departure": "2026-10-06T08:00:00", "price": 50, "currency": "EUR"]
        ]]])
        let loaded = TravelSearchPresentation(embed: fixture.primaryEmbed, data: data)
        XCTAssertEqual(loaded.resultCount, 1)
        XCTAssertEqual(loaded.route, "Munich → London")
        XCTAssertEqual(loaded.priceText(), "EUR 50")
        XCTAssertTrue(loaded.previewProviderText?.contains("Google") == true)
    }

    private func travelSearchFixture(_ name: String) throws -> DevEmbedPreviewSkill {
        let base = try XCTUnwrap(DevEmbedPreviewFixtures.skill(forRegistryKey: "app:travel:search_connections"))
        return try XCTUnwrap(DevEmbedPreviewFixtures.variants(for: base).first { $0.name == name }?.skill)
    }

}
