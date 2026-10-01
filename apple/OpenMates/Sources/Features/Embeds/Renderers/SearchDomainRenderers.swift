// Native counterparts of the health, home, nutrition, and shopping search/result
// embeds. The outer EmbedPreviewCard and fullscreen shell supply app chrome.
// Web: frontend/packages/ui/src/components/embeds/{health,home,nutrition,shopping}/
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI
#if canImport(MapKit)
import MapKit
#endif

enum SearchDomainKind: String {
    case health, home, nutrition, shopping

    var childType: String {
        switch self {
        case .health: "health-appointment"
        case .home: "home-listing"
        case .nutrition: "nutrition-recipe"
        case .shopping: "shopping-product"
        }
    }

}

/// Reads both decrypted child records and the inline result rows used while
/// child hydration is pending. It keeps the parent's declared order and gives
/// inline rows a real child record so tapping them opens the correct detail.
@MainActor
struct SearchDomainParentModel {
    let kind: SearchDomainKind
    let query: String
    let provider: String?
    let resultCount: Int
    let results: [EmbedRecord]

    init(kind: SearchDomainKind, embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        self.kind = kind
        let raw = embed.rawData ?? [:]
        query = kind == .health ? HealthAppointmentModel.searchSummary(raw)
            : EmbedFieldReader.string(raw, keys: ["query", "city", "title"])
                ?? EmbedType.normalized(rawValue: embed.type)?.displayName ?? AppStrings.search
        provider = EmbedFieldReader.string(raw, keys: ["provider"])
            ?? EmbedFieldReader.stringArray(raw, keys: ["providers"]).first

        let rows = Self.flattenedRows(from: raw)
        let inline = rows.enumerated().map { index, row in
            var fields = row.mapValues(AnyCodable.init)
            fields["app_id"] = fields["app_id"] ?? AnyCodable(kind.rawValue)
            return EmbedRecord(
                id: EmbedFieldReader.string(fields, keys: ["embed_id", "id"])
                    ?? (embed.childEmbedIds.indices.contains(index) ? embed.childEmbedIds[index] : nil)
                    ?? "\(embed.id)-result-\(index)",
                type: kind.childType,
                status: .finished,
                data: .raw(fields),
                parentEmbedId: embed.id,
                appId: kind.rawValue,
                skillId: nil,
                embedIds: nil,
                createdAt: embed.createdAt
            )
        }
        // Persisted skill parents may retain a TOON result payload after their
        // child records have been compacted away. Reuse the existing decoder,
        // then give those fallback records the domain-specific child type.
        let encodedFallback: [EmbedRecord] = rows.isEmpty && raw["results_toon"] != nil
            ? SearchSkillPreviewModel(embed: embed, allEmbedRecords: [:]).childEmbeds.map { source in
                EmbedRecord(
                    id: source.id, type: kind.childType, status: source.status,
                    data: source.data, parentEmbedId: embed.id,
                    appId: kind.rawValue, skillId: nil, embedIds: nil,
                    createdAt: source.createdAt
                )
            }
            : []
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        results = SearchSkillPreviewModel.mergedRecords(
            parentOrder: embed.childEmbedIds,
            inlineRecords: inline + encodedFallback,
            hydratedRecords: explicit + parented
        )
        resultCount = EmbedFieldReader.int(raw, keys: ["result_count", "total_results"])
            ?? results.count
    }

    static func flattenedRows(from raw: [String: AnyCodable]) -> [[String: Any]] {
        let source = ["results", "preview_results"].lazy
            .map { EmbedFieldReader.dictionaryArray(raw, key: $0) }
            .first { !$0.isEmpty } ?? []
        func flatten(_ rows: [[String: Any]]) -> [[String: Any]] {
            rows.flatMap { row in
                guard let nested = row["results"] as? [[String: Any]] else { return [row] }
                return flatten(nested)
            }
        }
        return flatten(source)
    }
}

struct SearchDomainParentRenderer: View {
    let embed: EmbedRecord
    let kind: SearchDomainKind
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private var model: SearchDomainParentModel {
        SearchDomainParentModel(kind: kind, embed: embed, allEmbedRecords: allEmbedRecords)
    }

    private var previewCountLabel: String {
        switch kind {
        case .health:
            let noun = model.resultCount == 1
                ? AppStrings.domainHealthAppointmentAvailable : AppStrings.domainHealthAppointmentsAvailable
            return "\(model.resultCount) \(noun)"
        case .home: return AppStrings.moreResults(model.resultCount)
        case .nutrition: return "\(model.resultCount) \(AppStrings.domainNutritionRecipes)"
        case .shopping: return "\(model.resultCount) \(AppStrings.domainShoppingProducts)"
        }
    }

    private var previewExtraLabel: String? {
        switch kind {
        case .health:
            let earliest = model.results.compactMap {
                DomainFields($0.rawData ?? [:]).string("slot_datetime")
            }.sorted().first
            guard let earliest else { return nil }
            let label = DomainFields(["slot_datetime": AnyCodable(earliest)]).slotLabel
            return label.map { "\(AppStrings.domainFrom) \($0.components(separatedBy: " · ").first ?? $0)" }
        case .shopping:
            let prices = model.results.compactMap {
                DomainFields($0.rawData ?? [:]).double("price_cents")
            }
            guard let minimum = prices.min() else { return nil }
            let euro = (minimum / 100).formatted(
                .currency(code: "EUR").locale(Locale(identifier: "de_DE"))
            )
            return "\(AppStrings.domainFrom) \(euro)"
        case .home, .nutrition: return nil
        }
    }

    var body: some View {
        if mode == .preview {
            VStack(alignment: .leading, spacing: 8) {
                Text(model.query)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                if let provider = model.provider, !provider.isEmpty, kind != .home {
                    Text("\(AppStrings.via) \(provider)")
                        .font(.system(size: 12))
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                }
                if embed.status == .finished {
                    Text(previewCountLabel)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Color.fontSecondary)
                    if let previewExtraLabel {
                        Text(previewExtraLabel)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Color.fontPrimary)
                    }
                } else if embed.status == .error {
                    Text(AppStrings.searchFailed)
                        .font(.system(size: 12))
                        .foregroundStyle(Color.error)
                }
            }
            .padding(.spacing6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .accessibilityIdentifier("\(kind.rawValue)-search-preview")
        } else {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 280, maximum: 320), spacing: 16)], spacing: 16) {
                ForEach(model.results) { child in
                    EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords, variant: .compact) {
                        onOpenEmbed(child)
                    }
                    .environment(\.embedPreviewFillsGridCell, true)
                    .accessibilityIdentifier("embed-preview-\(child.id)")
                }
            }
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("\(kind.rawValue)-search-results")
        }
    }
}

struct SearchDomainResultRenderer: View {
    let data: [String: AnyCodable]?
    let kind: SearchDomainKind
    let mode: EmbedDisplayMode

    private var fields: DomainFields { DomainFields(data ?? [:]) }

    var body: some View {
        Group {
            if kind == .health {
                // The appointment renderer owns its AX container. A second
                // wrapper identifier replaces that root when SwiftUI merges
                // single-child containers, including the hydrated child route.
                HealthAppointmentRenderer(data: data ?? [:], mode: mode)
            } else {
                Group {
                    if mode == .preview { preview } else { fullscreen }
                }
                .accessibilityIdentifier("\(kind.rawValue)-result-\(mode == .preview ? "preview" : "fullscreen")")
            }
        }
    }

    @ViewBuilder private var preview: some View {
        switch kind {
        case .health: healthPreview
        case .home: homePreview
        case .nutrition: recipePreview
        case .shopping: productPreview
        }
    }

    @ViewBuilder private var fullscreen: some View {
        switch kind {
        case .health: healthFullscreen
        case .home: homeFullscreen
        case .nutrition: recipeFullscreen
        case .shopping: productFullscreen
        }
    }

    // MARK: Health appointment

    private var healthPreview: some View {
        HealthAppointmentRenderer(data: data ?? [:], mode: .preview)
    }

    private var healthFullscreen: some View {
        HealthAppointmentRenderer(data: data ?? [:], mode: .fullscreen)
    }

    // MARK: Home listing

    private var homePreview: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                if let price = fields.string("price_label") {
                    Text(price).font(.system(size: 16, weight: .bold)).foregroundStyle(Color.fontPrimary)
                }
                Text(fields.string("title") ?? AppStrings.domainListing)
                    .font(.system(size: 14, weight: .semibold)).foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                if let address = fields.string("address") {
                    Text(address).font(.system(size: 12)).foregroundStyle(Color.fontSecondary).lineLimit(1)
                }
                Text(fields.homeMetadata.joined(separator: " · "))
                    .font(.system(size: 11)).foregroundStyle(Color.fontSecondary).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if let image = fields.imageURL(maxWidth: 480) {
                DomainImage(url: image, height: 125)
                    .frame(width: 171)
            }
        }
        .domainPreviewPadding()
    }

    private var homeFullscreen: some View {
        EmbedMapDetailTemplate(mapConfiguration: fields.mapConfiguration) {
            VStack(alignment: .leading, spacing: 12) {
                if let image = fields.imageURL(maxWidth: 1200) {
                    DomainImage(url: image, height: 240)
                }
                Text(fields.string("title") ?? AppStrings.domainListing)
                    .font(.system(size: 19, weight: .bold))
                if let price = fields.string("price_label") {
                    Text(price).font(.system(size: 17, weight: .bold))
                }
                DomainSectionTitle(AppStrings.domainLocation)
                if let address = fields.string("address") { Text(address).font(.system(size: 14)) }
                HStack(spacing: 8) {
                    ForEach(fields.homeMetadata, id: \.self) { DomainPill($0) }
                    if let type = fields.string("listing_type") { DomainPill(fields.listingTypeLabel(type)) }
                }
                if let provider = fields.string("provider") { DomainPill(provider) }
                if let url = fields.secureURL("url") {
                    Link(AppStrings.openOnProvider(fields.string("provider") ?? AppStrings.domainListing), destination: url)
                        .font(.system(size: 14, weight: .semibold))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // MARK: Nutrition recipe

    private var recipePreview: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 3) {
                Text(fields.string("title") ?? AppStrings.domainNutritionRecipe)
                    .font(.system(size: 14, weight: .semibold)).foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                Text(fields.recipeMetadata.joined(separator: " · "))
                    .font(.system(size: 11)).foregroundStyle(Color.fontSecondary).lineLimit(1)
                if let rating = fields.double("rating") {
                    Text(String(format: "%.1f", rating) + fields.countSuffix("rating_count"))
                        .font(.system(size: 11)).foregroundStyle(Color.fontSecondary)
                }
                if let servings = fields.int("servings") {
                    Text("\(servings) \(AppStrings.domainNutritionServings)").font(.system(size: 11)).foregroundStyle(Color.fontSecondary)
                }
                HStack(spacing: 4) {
                    ForEach(fields.stringArray("dietary_tags").prefix(2), id: \.self) { DomainPill($0) }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if let image = fields.imageURL(maxWidth: 480) {
                DomainImage(url: image, height: 125).frame(width: 171)
            }
        }
        .domainPreviewPadding()
    }

    private var recipeFullscreen: some View {
        VStack(alignment: .leading, spacing: 15) {
            if let image = fields.imageURL(maxWidth: 1200) {
                DomainImage(url: image, height: 230)
            } else {
                Text("🍳").font(.system(size: 46))
                    .frame(maxWidth: .infinity, minHeight: 170)
                    .background(Color.grey10)
            }
            Text(fields.string("title") ?? AppStrings.domainNutritionRecipe).font(.system(size: 20, weight: .bold))
            if let description = fields.string("description") {
                Text(description).font(.system(size: 14)).foregroundStyle(Color.fontSecondary)
            }
            HStack(spacing: 6) {
                ForEach(fields.recipeMetadata, id: \.self) { DomainPill($0) }
                if let rating = fields.double("rating") { DomainPill(String(format: "★ %.1f", rating)) }
            }
            if let score = fields.int("ernaehrwert_score") { DomainPill("\(AppStrings.domainNutritionHealthScore): \(score)/10") }
            DomainTagRow(values: fields.stringArray("dietary_tags"))
            DomainTagRow(values: fields.stringArray("categories"))
            let ingredients = fields.dictionaryArray("ingredients")
            if !ingredients.isEmpty {
                DomainSectionTitle(AppStrings.domainNutritionIngredients)
                ForEach(Array(ingredients.enumerated()), id: \.offset) { _, ingredient in
                    let item = DomainFields(ingredient.mapValues(AnyCodable.init))
                    Text([item.string("amount"), item.string("unit"), item.string("name")]
                        .compactMap { $0 }.joined(separator: " "))
                        .font(.system(size: 13))
                }
            }
            let steps = fields.dictionaryArray("instructions")
            if !steps.isEmpty {
                DomainSectionTitle(AppStrings.domainNutritionInstructions)
                ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                    let item = DomainFields(step.mapValues(AnyCodable.init))
                    Text("\(index + 1). \(item.string("text") ?? "")")
                        .font(.system(size: 13))
                }
            }
            if let nutrition = fields.dictionary("nutrition") {
                DomainSectionTitle(AppStrings.domainNutritionInfo)
                let values = DomainFields(nutrition.mapValues(AnyCodable.init))
                HStack(spacing: 10) {
                    ForEach(["calories_kcal", "protein_g", "fat_g", "carbs_g"], id: \.self) { key in
                        if let amount = values.double(key) {
                            DomainPill("\(amount.formatted()) \(fields.nutritionLabel(for: key))")
                        }
                    }
                }
            }
            if let url = fields.secureURL("recipe_url") { Link(AppStrings.domainNutritionViewSource, destination: url) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.spacing6)
    }

    // MARK: Shopping product

    private var productPreview: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 3) {
                Text(fields.string("title") ?? AppStrings.domainShoppingProduct)
                    .font(.system(size: 14, weight: .semibold)).foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                if let brand = fields.string("brand") {
                    Text(brand).font(.system(size: 11)).foregroundStyle(Color.fontSecondary)
                }
                HStack(spacing: 4) {
                    Text(fields.productPrice ?? AppStrings.domainShoppingPriceUnavailable)
                        .font(.system(size: 14, weight: .bold)).foregroundStyle(Color.fontPrimary)
                    if let oldPrice = fields.oldProductPrice {
                        Text(oldPrice).strikethrough()
                            .font(.system(size: 11)).foregroundStyle(Color.fontSecondary)
                    }
                }
                if let grammage = fields.string("grammage") {
                    Text(grammage).font(.system(size: 11)).foregroundStyle(Color.fontSecondary)
                }
                if let basePrice = fields.string("base_price") {
                    Text(basePrice).font(.system(size: 11)).foregroundStyle(Color.fontSecondary)
                }
                if let rating = fields.double("rating") {
                    Text(String(format: "★ %.1f", rating) + fields.countSuffix("reviews"))
                        .font(.system(size: 11)).foregroundStyle(Color.fontSecondary)
                }
                DomainTagRow(values: fields.productTags.prefix(2).map { $0 })
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if let image = fields.imageURL(maxWidth: 480) {
                DomainImage(url: image, height: 125).frame(width: 171)
            }
        }
        .domainPreviewPadding()
    }

    private var productFullscreen: some View {
        VStack(alignment: .leading, spacing: 13) {
            if let image = fields.imageURL(maxWidth: 1200) {
                DomainImage(url: image, height: 235)
            } else {
                Image(systemName: "bag")
                    .font(.system(size: 42)).foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, minHeight: 170)
                    .background(Color.grey10)
            }
            Text(fields.string("title") ?? AppStrings.domainShoppingProduct).font(.system(size: 20, weight: .bold))
            if let brand = fields.string("brand") {
                Text(brand).font(.system(size: 14)).foregroundStyle(Color.fontSecondary)
            }
            HStack(spacing: 7) {
                Text(fields.productPrice ?? AppStrings.domainShoppingPriceUnavailable)
                    .font(.system(size: 19, weight: .bold))
                if let oldPrice = fields.oldProductPrice {
                    Text(oldPrice).strikethrough().foregroundStyle(Color.fontSecondary)
                }
            }
            if let grammage = fields.string("grammage") { Text(grammage).font(.system(size: 13)) }
            if let basePrice = fields.string("base_price") { Text(basePrice).font(.system(size: 13)) }
            if let rating = fields.double("rating") {
                Text(String(format: "★ %.1f", rating) + fields.countSuffix("reviews"))
                    .font(.system(size: 13))
            }
            DomainTagRow(values: fields.productTags)
            if let delivery = fields.stringArray("delivery").first {
                DomainSectionTitle(AppStrings.domainDelivery)
                Text(delivery).font(.system(size: 13))
            }
            if let category = fields.string("category_path") {
                DomainSectionTitle(AppStrings.domainCategory)
                Text(category).font(.system(size: 13))
            }
            if let productID = fields.string("product_id") {
                Text("\(AppStrings.domainShoppingProductID): \(productID)")
                    .font(.system(size: 11)).foregroundStyle(Color.fontSecondary)
            }
            if let url = fields.secureURL("purchase_url") {
                Link(AppStrings.openOnProvider(fields.string("provider") ?? AppStrings.domainShoppingProduct), destination: url)
                    .font(.system(size: 14, weight: .semibold))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.spacing6)
    }
}

private struct DomainPill: View {
    let label: String
    init(_ label: String) { self.label = label }
    var body: some View {
        Text(label).font(.system(size: 11, weight: .semibold))
            .foregroundStyle(Color.fontSecondary)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(Color.grey10, in: Capsule())
    }
}

private struct DomainTagRow: View {
    let values: [String]
    var body: some View {
        HStack(spacing: 4) {
            ForEach(values, id: \.self) { DomainPill($0) }
        }
    }
}

private struct DomainSectionTitle: View {
    let title: String
    init(_ title: String) { self.title = title }
    var body: some View {
        Text(title.uppercased()).font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color.fontSecondary)
    }
}

private struct DomainImage: View {
    let url: URL
    let height: CGFloat
    var body: some View {
        CachedRemoteImage(url: url) { image in
            image.resizable().scaledToFill()
        } placeholder: { Color.grey10 }
        .frame(maxWidth: .infinity)
        .frame(height: height)
        .clipped()
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private extension View {
    func domainPreviewPadding() -> some View {
        self.padding(.horizontal, 20).padding(.top, 16)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

@MainActor
struct DomainFields {
    let raw: [String: AnyCodable]
    init(_ raw: [String: AnyCodable]) { self.raw = raw }

    func string(_ keys: String...) -> String? { EmbedFieldReader.string(raw, keys: keys) }
    func int(_ keys: String...) -> Int? { EmbedFieldReader.int(raw, keys: keys) }
    func double(_ keys: String...) -> Double? { EmbedFieldReader.double(raw, keys: keys) }
    func stringArray(_ key: String) -> [String] { EmbedFieldReader.stringArray(raw, keys: [key]) }
    func dictionaryArray(_ key: String) -> [[String: Any]] { EmbedFieldReader.dictionaryArray(raw, key: key) }
    func dictionary(_ key: String) -> [String: Any]? { raw[key]?.value as? [String: Any] }
    func bool(_ key: String) -> Bool? {
        if let value = raw[key]?.value as? Bool { return value }
        if let value = raw[key]?.value as? String { return ["true", "1"].contains(value.lowercased()) }
        return nil
    }

    func countSuffix(_ key: String) -> String {
        int(key).map { " (\($0.formatted()))" } ?? ""
    }

    func secureURL(_ keys: String...) -> URL? {
        guard let value = EmbedFieldReader.string(raw, keys: keys),
              let url = URL(string: value), url.scheme == "https", url.host != nil else { return nil }
        return url
    }

    func imageURL(maxWidth: Int) -> URL? {
        EmbedFieldReader.proxiedImageURL(string("image_url"), maxWidth: maxWidth)
            .flatMap(URL.init(string:))
    }

    func insuranceLabel(_ value: String) -> String {
        switch value.lowercased() {
        case "unknown":
            return AppStrings.domainHealthInsuranceVerify(string("provider_platform") ?? AppStrings.domainProvider)
        case "public": return AppStrings.domainInsurancePublic
        case "private": return AppStrings.domainInsurancePrivate
        default: return value
        }
    }

    func listingTypeLabel(_ value: String) -> String {
        switch value.lowercased() {
        case "rent": return AppStrings.domainRent.uppercased()
        case "buy": return AppStrings.domainBuy.uppercased()
        default: return value.uppercased()
        }
    }

    func nutritionLabel(for key: String) -> String {
        switch key {
        case "calories_kcal": return "kcal"
        case "protein_g": return "g \(AppStrings.domainNutritionProtein)"
        case "fat_g": return "g \(AppStrings.domainNutritionFat)"
        case "carbs_g": return "g \(AppStrings.domainNutritionCarbs)"
        default: return ""
        }
    }

    var slotLabel: String? {
        guard let rawSlot = string("slot_datetime", "date") else { return nil }
        let input = DateFormatter()
        input.locale = Locale(identifier: "en_US_POSIX")
        input.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        let output = DateFormatter()
        output.locale = Locale.current
        output.dateFormat = "EEE, MMM d · h:mm a"
        return input.date(from: String(rawSlot.prefix(19))).map(output.string(from:)) ?? rawSlot
    }

    var homeMetadata: [String] {
        [double("size_sqm").map { "\($0.formatted()) m²" },
         int("rooms").map { "\($0) \($0 == 1 ? AppStrings.domainRoom : AppStrings.domainRooms)" },
         string("available_from").map { "\(AppStrings.domainFrom) \($0)" }].compactMap { $0 }
    }

    var recipeMetadata: [String] {
        let minutes = int("total_time_minutes", "prep_time_minutes")
        let duration = minutes.map { value in
            if value < 60 { return AppStrings.domainMinutes(value) }
            if value % 60 == 0 { return AppStrings.domainHours(value / 60) }
            return AppStrings.domainHoursMinutes(hours: value / 60, minutes: value % 60)
        }
        let difficulty = string("difficulty").map {
            switch $0.lowercased() {
            case "einfach": AppStrings.domainEasy
            case "mittel": AppStrings.domainMedium
            case "schwer": AppStrings.domainHard
            default: $0
            }
        }
        return [duration, difficulty].compactMap { $0 }
    }

    private func euro(_ value: Double) -> String {
        value.formatted(.currency(code: "EUR").locale(Locale(identifier: "de_DE")))
    }

    var productPrice: String? {
        if let amount = double("price_amount") { return euro(amount) }
        if let cents = double("price_cents") { return euro(cents / 100) }
        if let text = string("price_eur", "price") { return text }
        return nil
    }

    var oldProductPrice: String? {
        if let amount = double("old_price_amount") { return euro(amount) }
        if let cents = double("was_price_cents") { return euro(cents / 100) }
        return string("old_price")
    }

    var productTags: [String] {
        let attributes = dictionary("attributes") ?? [:]
        let labels = [
            ("is_organic", AppStrings.domainBio), ("is_vegan", AppStrings.domainVegan),
            ("is_vegetarian", AppStrings.domainVegetarian), ("is_dairy_free", AppStrings.domainDairyFree),
            ("is_gluten_free", AppStrings.domainGlutenFree), ("is_regional", AppStrings.domainRegional)
        ]
        return labels.compactMap { key, label in
            let value = attributes[key]
            return (value as? Bool == true || value as? String == "true") ? label : nil
        }
    }

    #if canImport(MapKit)
    var mapConfiguration: EmbedMapConfiguration? {
        guard let point = AppleResultsViewEntry.coordinate(raw) else { return nil }
        return EmbedMapConfiguration(
            center: point,
            markers: [EmbedMapMarker(coordinate: point, title: string("name", "title") ?? AppStrings.domainLocation)]
        )
    }
    #else
    var mapConfiguration: Never? { nil }
    #endif
}

// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedPreview.svelte
//         frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedFullscreen.svelte
// CSS: .appointment-details, .slot-highlight, .doctor-header, .badges-row
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
// ────────────────────────────────────────────────────────────────────
@MainActor
struct HealthAppointmentModel {
    let fields: DomainFields
    init(_ raw: [String: AnyCodable]) { fields = DomainFields(raw) }
    static func searchSummary(_ raw: [String: AnyCodable]) -> String {
        let fields = DomainFields(raw)
        if let query = fields.string("query"), !query.isEmpty { return query }
        let speciality = fields.string("speciality", "specialty")
        let city = fields.string("city")
        // HealthSearchEmbedFullscreen.svelte assembles these backend fields.
        if let speciality, let city { return speciality.prefix(1).uppercased() + speciality.dropFirst() + " in " + city.prefix(1).uppercased() + city.dropFirst() }
        return speciality ?? city ?? ""
    }
    var name: String? { fields.string("name", "doctor_name") }
    var speciality: String? { fields.string("speciality", "specialty") }
    var provider: String { fields.string("provider_platform", "provider") ?? AppStrings.domainProvider }
    var bookingURL: URL? { fields.secureURL("booking_url") ?? fields.secureURL("practice_url") }
    var title: String { fullSlotLabel ?? name ?? speciality ?? AppStrings.domainHealthAppointment }
    var subtitle: String? {
        let parts = [(fullSlotLabel != nil ? name : nil), speciality].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
    #if canImport(MapKit)
    var mapConfiguration: EmbedMapConfiguration? {
        guard var configuration = fields.mapConfiguration else { return nil }
        // HealthAppointmentEmbedFullscreen uses Leaflet zoom=16.
        configuration.latitudeDelta = 0.005
        configuration.longitudeDelta = 0.005
        return configuration
    }
    #else
    var mapConfiguration: Never? { nil }
    #endif
    var fullSlotLabel: String? { slotLabel(fields.string("slot_datetime"), full: true) }
    func slotLabel(_ value: String?, full: Bool = false) -> String? {
        guard let value, !value.isEmpty else { return nil }
        let input = DateFormatter()
        input.locale = Locale(identifier: "en_US_POSIX")
        input.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        let output = DateFormatter()
        output.locale = Locale.current
        output.setLocalizedDateFormatFromTemplate(full ? "EEEE MMMM d" : "EEE MMM d")
        let time = DateFormatter()
        time.locale = Locale.current
        time.setLocalizedDateFormatFromTemplate("hhmm")
        // Offset-bearing slots preserve their absolute timestamp; unzoned slots
        // retain their provider's local wall-clock time, matching browser Date.
        let zoned = ISO8601DateFormatter().date(from: value)
        guard let date = zoned ?? input.date(from: String(value.prefix(19))) else { return value }
        return output.string(from: date) + " · " + time.string(from: date)
    }
}

struct HealthAppointmentRenderer: View {
    let data: [String: AnyCodable]
    let mode: EmbedDisplayMode
    private var model: HealthAppointmentModel { HealthAppointmentModel(data) }
    private var fields: DomainFields { model.fields }

    var body: some View {
        Group {
            if mode == .preview { preview }
            else if model.mapConfiguration != nil {
                EmbedMapDetailTemplate(mapConfiguration: model.mapConfiguration) { details }
            } else {
                details.frame(maxWidth: 600).padding(.spacing10).frame(maxWidth: .infinity)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(mode == .preview ? "health-appointment-preview" : "health-appointment-fullscreen")
    }

    private var preview: some View {
        VStack(alignment: .leading, spacing: 3) { // health CSS .appointment-details gap=3px
            if let slot = model.slotLabel(fields.string("slot_datetime")) {
                HStack(spacing: .spacing2) {
                    Text(slot).font(.omP).fontWeight(.bold).foregroundStyle(Color.grey100).lineLimit(1)
                    if let count = fields.int("additional_slot_count"), count > 0 {
                        Text(AppStrings.moreResults(count)).font(.omTiny).fontWeight(.semibold)
                    }
                }
            }
            if let name = model.name { Text(name).font(.omSmall).fontWeight(.semibold).foregroundStyle(Color.grey100).lineLimit(2) }
            if let speciality = model.speciality { Text(speciality).font(.omXs).foregroundStyle(Color.grey70).lineLimit(1) }
            if let address = fields.string("address")?.components(separatedBy: "\n").first {
                Text(address).font(.omXxs).foregroundStyle(Color.grey60).lineLimit(1)
            }
            if fields.double("rating") != nil || fields.double("price") != nil {
                HStack(spacing: .spacing3) {
                    if let rating = fields.double("rating") {
                        Text(String(format: "%.1f ★", rating)).foregroundStyle(Color.warning)
                        if let count = fields.int("rating_count"), count > 0 { Text("(\(count))").foregroundStyle(Color.grey60) }
                    }
                    if let price = fields.double("price") { Text("\(price.formatted()) €").foregroundStyle(Color.grey70) }
                    Text(model.provider).foregroundStyle(Color.grey50)
                }.font(.omXxs)
            }
            badges
        }
        .padding(.spacing10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private var details: some View {
        VStack(spacing: .spacing8) {
            if let slot = model.fullSlotLabel {
                Text(slot).font(.omH3).fontWeight(.bold).foregroundStyle(Color.grey100)
                    .frame(maxWidth: .infinity).padding(.vertical, .spacing6).padding(.horizontal, .spacing8)
                    // health CSS uses its explicit rgba primary-rgb fallback.
                    .background(Color(red: 74 / 255, green: 144 / 255, blue: 226 / 255).opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color(red: 74 / 255, green: 144 / 255, blue: 226 / 255).opacity(0.2)))
            }
            VStack(spacing: .spacing3) {
                if let name = model.name { Text(name).font(.omXl).fontWeight(.bold).foregroundStyle(Color.fontPrimary) }
                if let speciality = model.speciality { Text(speciality).font(.omP).foregroundStyle(Color.fontSecondary) }
                if let address = fields.string("address") {
                    Text(address).font(.omXs).foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("health-appointment-address")
                }
            }.multilineTextAlignment(.center)
            if let rating = fields.double("rating") {
                HStack(spacing: .spacing3) {
                    Text(String(format: "%.1f ★", rating)).font(.omP).fontWeight(.bold).foregroundStyle(Color.warning)
                    if let count = fields.int("rating_count"), count > 0 { Text(AppStrings.domainHealthReviewCount(count)).font(.omXs).foregroundStyle(Color.fontSecondary) }
                }
            }
            if fields.string("service_name") != nil || fields.double("price") != nil {
                HStack {
                    if let service = fields.string("service_name") { Text(service).font(.omSmall).fontWeight(.semibold) }
                    if let price = fields.double("price") { Text("\(price.formatted()) €").font(.omP).fontWeight(.bold) }
                }
            }
            badges
            let alternateSlots = fields.stringArray("additional_slot_datetimes")
            if !alternateSlots.isEmpty {
                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(AppStrings.domainHealthAlsoAvailable).font(.omSmall).fontWeight(.bold)
                    ForEach(alternateSlots, id: \.self) { slot in
                        Text(model.slotLabel(slot) ?? slot).font(.omXxs).padding(.spacing2)
                            .background(Color.grey20).clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            if let description = fields.string("description") { Text(description).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            let hours = fields.stringArray("opening_hours")
            ForEach(hours, id: \.self) { Text($0).font(.omXs).foregroundStyle(Color.fontSecondary) }
            if let phone = fields.string("phone") { Text(phone).font(.omXs).foregroundStyle(Color.fontSecondary) }
            if let website = fields.secureURL("website") { Link(website.host ?? model.provider, destination: website).font(.omXs) }
            Text(AppStrings.domainHealthSlotsOutdated(model.provider)).font(.omTiny).foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center).padding(.top, .spacing6)
        }
        .frame(maxWidth: .infinity)
    }

    private var badges: some View {
        HStack(spacing: .spacing3) {
            if fields.bool("telehealth") == true { badge(AppStrings.domainHealthTelehealth, highlighted: true) }
            if let insurance = fields.string("insurance"), !insurance.isEmpty { badge(fields.insuranceLabel(insurance)) }
        }
    }
    private func badge(_ label: String, highlighted: Bool = false) -> some View {
        Text(label).font(.omXxs).fontWeight(.semibold).foregroundStyle(highlighted ? Color.grey100 : Color.grey70)
            .padding(.vertical, .spacing2).padding(.horizontal, .spacing5)
            .background(highlighted ? Color.greyBlue : Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
    }
}
