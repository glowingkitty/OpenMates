import XCTest
#if os(iOS)
import SwiftUI
import UIKit
#endif
@testable import OpenMates

@MainActor
final class HostingEmbedModelTests: XCTestCase {
    #if os(iOS)
    // contract-test: supporting surface=gui.apple assertions=hosting-domains.surface-parity
    func testHostingIconResolverRendersWebRedOrangeGradientAndMatchesFullscreenPalette() throws {
        // Web gradients.yml / appGradientTheme.ts: Hosting #C50003 -> #FF763B.
        // Exercise the production icon resolver, which supplies preview footers,
        // rather than checking only the generated token's existence.
        func render(_ gradient: LinearGradient) throws -> Data {
            let renderer = ImageRenderer(content: Rectangle().fill(gradient).frame(width: 64, height: 64))
            renderer.scale = 1
            return try XCTUnwrap(renderer.uiImage?.pngData())
        }
        func rgb(_ color: Color) -> [Int] {
            var red: CGFloat = 0, green: CGFloat = 0, blue: CGFloat = 0, alpha: CGFloat = 0
            XCTAssertTrue(UIColor(color).getRed(&red, green: &green, blue: &blue, alpha: &alpha))
            return [red, green, blue].map { Int(($0 * 255).rounded()) }
        }
        let actual = try render(AppIconView.gradient(forAppId: "hosting"))
        let token = try render(.appHosting)
        XCTAssertEqual(actual, token)
        XCTAssertNotEqual(actual, try render(.primary))
        let header = AppGradientPalette.colors(for: "hosting")
        XCTAssertEqual(rgb(header.start), [197, 0, 3])
        XCTAssertEqual(rgb(header.end), [255, 118, 59])
        XCTAssertEqual(actual, try render(.omGradient(start: header.start, end: header.end)))
        for fixture in [DevHostingEmbedFixtures.search().primaryEmbed, DevHostingEmbedFixtures.domain()] {
            let appID = try XCTUnwrap(fixture.appId)
            XCTAssertEqual(try render(AppIconView.gradient(forAppId: appID)), actual)
        }
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.embeds.parent-child,hosting-domains.availability.selection
    func testHydratedCheckedPoolKeepsDeclaredOrderAndSelectedRankingWithoutInventingChildren() {
        let fixture = DevHostingEmbedFixtures.search()
        var raw = fixture.primaryEmbed.rawData?.mapValues(\.value) ?? [:]
        let ids = fixture.childEmbeds.map(\.id)
        raw["embed_ids"] = ids + [ids[0]]
        raw["selected_embed_ids"] = [ids[1], ids[0], ids[1]]
        let parent = DevHostingEmbedFixtures.record(id: fixture.primaryEmbed.id, type: fixture.primaryEmbed.type, raw: raw)
        var records = fixture.allRecords
        let unrelated = DevHostingEmbedFixtures.domain("premium")
        records[unrelated.id] = unrelated
        let model = HostingSearchModel(embed: parent, allEmbedRecords: records)
        XCTAssertEqual(model.children.map(\.id), ids)
        XCTAssertEqual(model.visibleChildren(.selected).map(\.id), [ids[1], ids[0]])
        XCTAssertEqual(model.visibleChildren(.available).count, 2)
        XCTAssertEqual(model.visibleChildren(.inUse).map { HostingDomainModel($0).name }, ["cedarcomet.org", "cedarcomet.co"])
        XCTAssertEqual(model.visibleChildren(.all).count, 2)
        XCTAssertTrue(model.visibleChildren(.all).allSatisfy { HostingDomainModel($0).availability != .unknown })
        XCTAssertEqual(model.visibleChildren(.unknown).map { HostingDomainModel($0).name }, ["cedarcomet.et"])
        records.removeValue(forKey: ids[0])
        let pending = HostingSearchModel(embed: parent, allEmbedRecords: records)
        XCTAssertTrue(pending.isHydrating)
        XCTAssertEqual(pending.visibleChildren(.selected).map(\.id), [ids[1]])
    }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.results.partial-and-safe,hosting-domains.embeds.parent-child
    func testExactUnknownErrorExposesDiagnosticChildAndNeverLabelsItUnavailable() {
        let fixture = DevHostingEmbedFixtures.search("error")
        let model = HostingSearchModel(embed: fixture.primaryEmbed, allEmbedRecords: fixture.allRecords)
        XCTAssertTrue(model.partial)
        XCTAssertEqual(model.visibleChildren(.selected).count, 1)
        XCTAssertEqual(HostingDomainModel(model.visibleChildren(.selected)[0]).availability, .unknown)
        XCTAssertTrue(model.visibleChildren(.inUse).isEmpty)
        XCTAssertNil(model.startingQuote)
    }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.quotes.truthful
    func testOneYearHeadlineSeparatesRegistrationRenewalAndMultiYearPerYearQuotes() throws {
        let model = HostingDomainModel(DevHostingEmbedFixtures.domain(fullscreen: true))
        XCTAssertEqual(model.registration?.quote?.amount, 13.09)
        XCTAssertEqual(model.renewal?.quote?.amount, 38.06)
        XCTAssertFalse(model.registration?.isFirstYearOffer ?? true)
        XCTAssertEqual(model.registrationTiers[1].minimumYears, 2)
        XCTAssertEqual(model.registrationTiers[1].quote?.amount, 30.91, "Provider quotes are per year; do not divide by minimum term")
        XCTAssertFalse(model.registrationTiers[1].isFirstYearOffer)
        let offer = HostingDomainModel(DevHostingEmbedFixtures.domain())
        XCTAssertTrue(try XCTUnwrap(offer.registration).isFirstYearOffer)
        XCTAssertEqual(offer.registration?.taxRate, 19)
        XCTAssertEqual(offer.renewal?.quote?.amount, 47.60)
        let minimum = HostingDomainModel(DevHostingEmbedFixtures.domain("minTwoYears"))
        XCTAssertEqual(minimum.registration?.minimumYears, 2)
        XCTAssertFalse(minimum.registration?.isFirstYearOffer ?? true)
    }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe
    func testMissingPricesAndTaxBasisStayHonestAndMalformedNumbersAreRejected() {
        let unknown = HostingDomainModel(DevHostingEmbedFixtures.domain("unknown"))
        XCTAssertNil(unknown.registration)
        XCTAssertNil(unknown.renewal)
        let excluding = HostingDomainTier(raw: ["unit": "y", "duration_range": ["minimum": "1"],
            "price_excluding_tax": "12.00", "discount": true, "normal_price": 50, "normal_price_before_taxes": 20])
        XCTAssertEqual(excluding.quote?.basis, .excluding)
        XCTAssertEqual(excluding.quote?.amount, 12)
        XCTAssertTrue(excluding.isFirstYearOffer)
        let invalidValues: [Any] = [true, "NaN", Double.infinity, -1]
        for invalid in invalidValues {
            XCTAssertNil(HostingDomainTier(raw: ["price_including_tax": invalid]).quote)
        }
        let both = HostingDomainTier(raw: ["price_including_tax": 14, "price_excluding_tax": 12])
        XCTAssertEqual(both.quote?.basis, .including)
        XCTAssertEqual(both.quote?.amount, 14)
    }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe
    func testStartingQuoteOnlyAppearsOnFinishedOneYearEvidence() {
        for variant in ["processing", "cancelled", "empty", "error"] {
            let fixture = DevHostingEmbedFixtures.search(variant)
            XCTAssertNil(HostingSearchModel(embed: fixture.primaryEmbed, allEmbedRecords: fixture.allRecords).startingQuote)
        }
        let fixture = DevHostingEmbedFixtures.search()
        XCTAssertEqual(HostingSearchModel(embed: fixture.primaryEmbed, allEmbedRecords: fixture.allRecords).startingQuote?.amount, 13.09)
        var raw = fixture.primaryEmbed.rawData?.mapValues(\.value) ?? [:]
        raw["preview_starting_registration"] = ["amount": 20, "currency": "EUR", "unit": "year", "duration": 2]
        let invalid = DevHostingEmbedFixtures.record(id: "parent", type: fixture.primaryEmbed.type, raw: raw)
        XCTAssertNil(HostingSearchModel(embed: invalid, allEmbedRecords: [:]).startingQuote)
    }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.results.partial-and-safe,hosting-domains.embeds.parent-child
    func testGandiCTARequiresExactHTTPSOriginAndWireAliasesHaveNativeRegistration() {
        XCTAssertNotNil(HostingDomainModel.safeGandiURL("https://shop.gandi.net/en/domain/suggest?search=cedar.test"))
        for value in ["http://shop.gandi.net/", "javascript:alert(1)", "https://shop.gandi.net.evil.test/", "https://evil.test/shop.gandi.net", "https://shop.gandi.net@evil.test/"] {
            XCTAssertNil(HostingDomainModel.safeGandiURL(value))
        }
        XCTAssertEqual(AppleComposerRendererRegistry.shared.descriptor(for: "hosting-domain")?.family, .hostingDomain)
        XCTAssertEqual(AppleComposerRendererRegistry.shared.descriptor(for: "hosting-domain-group")?.family, .group(childType: "hosting-domain"))
        XCTAssertEqual(EmbedType.normalized(rawValue: "hosting_domain"), .hostingDomain)
        XCTAssertEqual(EmbedType.normalized(rawValue: "hosting-domain"), .hostingDomain)
        XCTAssertEqual(EmbedType.hostingSearch.childType, .hostingDomain)
        XCTAssertTrue(EmbedType.hostingSearch.isComposite)
        let fixture = DevHostingEmbedFixtures.search()
        var raw = fixture.primaryEmbed.rawData?.mapValues(\.value) ?? [:]
        raw["type"] = "app_skill_use"; raw["app_id"] = "hosting"; raw["skill_id"] = "search_domains"
        let parent = DevHostingEmbedFixtures.record(id: "parent", type: "app-skill-use", raw: raw)
        XCTAssertTrue(HostingEmbedKind.isSearch(parent))
        XCTAssertEqual(EmbedVisualSkillIcon.name(for: parent), "search")
        XCTAssertEqual(EmbedVisualSkillIcon.name(for: DevHostingEmbedFixtures.domain()), "search")
    }
}
