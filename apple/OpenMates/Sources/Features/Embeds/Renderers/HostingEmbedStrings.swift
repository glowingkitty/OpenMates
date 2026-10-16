// Hosting accessors reuse the exact deployed web i18n keys.
import Foundation

enum HostingString: String {
    case title, providerVia = "provider_via", checkedCount = "checked_count", availableCount = "available_count"
    case unavailableCount = "unavailable_count", unknownCount = "unknown_count", selectedCount = "selected_count"
    case fromFirstYear = "from_first_year", renewalPrice = "renewal_price", firstYearOffer = "first_year_offer"
    case normalRegistration = "normal_registration", priceUnavailable = "price_unavailable", available, unavailable
    case couldNotCheck = "could_not_check", premium, minimumYears = "minimum_years", registrationRestrictions = "registration_restrictions"
    case showAvailable = "show_available", showAll = "show_all", showInUse = "show_in_use", showUnknown = "show_unknown"
    case partialResults = "partial_results", noResults = "no_results", processing, cancelled
    case taxIncluded = "tax_included", taxExcluded = "tax_excluded", taxUnknown = "tax_unknown", taxCountry = "tax_country"
    case currency, checkedAt = "checked_at", registration, renewal, quoteDetails = "quote_details", minimumTerm = "minimum_term"
    case domainASCII = "domain_ascii", domainUnicode = "domain_unicode", otherTermPrices = "other_term_prices"
    case openOnGandi = "open_on_gandi", availabilityMayChange = "availability_may_change", year, years
    case registrationRequirements = "registration_requirements", noDomainsInView = "no_domains_in_view", firstYear = "first_year"
    case tax, yes, term, price
}

extension AppStrings {
    static func hosting(_ key: HostingString, _ replacements: [String: String] = [:]) -> String {
        LocalizationManager.shared.text("embeds.hosting.search_domains.\(key.rawValue)", replacements: replacements)
    }
}

@MainActor
extension HostingDomainModel {
    var statusLabel: String {
        AppStrings.hosting(availability == .available ? .available : availability == .unavailable ? .unavailable : .couldNotCheck)
    }
    var subtitle: String { "\(statusLabel) · \(AppStrings.hosting(.providerVia, ["provider": provider]))" }
}

@MainActor
extension HostingDomainTier {
    func money(currency: String) -> String? {
        guard let quote else { return nil }
        let value = HostingMoney.format(quote.amount, currency: currency)
        return isYearly ? "\(value) / \(AppStrings.hosting(.year))" : value
    }
    var termLabel: String {
        guard let minimumYears, minimumYears > 0 else { return raw["minimum_term"] as? String ?? "" }
        if let maximumYears, maximumYears > minimumYears {
            return "\(HostingMoney.number(minimumYears))–\(HostingMoney.number(maximumYears)) \(AppStrings.hosting(.years))"
        }
        return "\(HostingMoney.number(minimumYears)) \(AppStrings.hosting(minimumYears == 1 ? .year : .years))"
    }
    var taxLabel: String {
        guard let quote else { return AppStrings.hosting(.taxUnknown) }
        let basis = AppStrings.hosting(quote.basis == .including ? .taxIncluded : .taxExcluded)
        return taxRate.map { "\(basis) (\(HostingMoney.number($0))%)" } ?? basis
    }
}

enum HostingMoney {
    static func format(_ amount: Double, currency: String) -> String {
        let formatter = NumberFormatter(); formatter.numberStyle = .currency; formatter.currencyCode = currency
        return formatter.string(from: NSNumber(value: amount)) ?? "\(currency) \(String(format: "%.2f", amount))"
    }
    static func number(_ value: Double) -> String { value.formatted(.number.precision(.fractionLength(0...2))) }
}
