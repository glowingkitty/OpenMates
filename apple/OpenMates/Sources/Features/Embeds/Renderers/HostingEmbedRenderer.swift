// Hosting parent search and independent domain detail renderers.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/hosting/HostingSearchEmbedPreview.svelte
//         frontend/packages/ui/src/components/embeds/hosting/HostingSearchEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/hosting/HostingDomainEmbedPreview.svelte
//         frontend/packages/ui/src/components/embeds/hosting/HostingDomainEmbedFullscreen.svelte
// CSS: same components — .search-summary, .grid, .domain-preview, .domain-details
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Source reference: dev 3053414ea2c50d4dfa0990e1211931fe09cf2b26; rendered/native proof is recorded separately.
// ────────────────────────────────────────────────────────────────────
import SwiftUI

private struct HostingDomainViewKey: EnvironmentKey {
    static let defaultValue: Binding<HostingDomainView> = .constant(.selected)
}
extension EnvironmentValues {
    var hostingDomainView: Binding<HostingDomainView> {
        get { self[HostingDomainViewKey.self] }
        set { self[HostingDomainViewKey.self] = newValue }
    }
}

struct HostingHeaderAction: Identifiable {
    let view: HostingDomainView
    let label: String
    let active: Bool
    let perform: () -> Void
    var id: String { "hosting-view-\(view.rawValue)" }
}

/// Surface identifiers belong on the production fullscreen shell, which
/// contains both chrome and content. A one-child renderer wrapper is flattened
/// by SwiftUI accessibility and replaces the content's grid/details identifier.
struct HostingFullscreenAccessibility: ViewModifier {
    let embed: EmbedRecord?
    @ViewBuilder
    func body(content: Content) -> some View {
        if let embed, HostingEmbedKind.isSearch(embed) {
            content.accessibilityElement(children: .contain)
                .accessibilityIdentifier("hosting-search-fullscreen")
        } else if let embed, HostingEmbedKind.isDomain(embed) {
            content.accessibilityElement(children: .contain)
                .accessibilityIdentifier("hosting-domain-fullscreen")
        } else {
            content
        }
    }
}

struct HostingSearchEmbedRenderer: View {
    let model: HostingSearchModel
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void
    @Environment(\.hostingDomainView) private var selectedView
    @State private var paneWidth: CGFloat = 390

    init(embed: EmbedRecord, mode: EmbedDisplayMode, allEmbedRecords: [String: EmbedRecord], onOpenEmbed: @escaping (EmbedRecord) -> Void) {
        model = HostingSearchModel(embed: embed, allEmbedRecords: allEmbedRecords)
        self.mode = mode; self.allEmbedRecords = allEmbedRecords; self.onOpenEmbed = onOpenEmbed
    }

    var body: some View {
        if mode == .preview { preview }
        else { fullscreen }
    }
    private var preview: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(model.query.isEmpty ? AppStrings.hosting(.title) : model.query)
                .font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontPrimary).lineLimit(3)
            Text(AppStrings.hosting(.providerVia, ["provider": model.provider]))
                .font(.omP).foregroundStyle(Color.fontSecondary)
            if model.embed.status == .processing {
                Text(AppStrings.hosting(.processing)).font(.omP)
            } else if model.embed.status == .cancelled {
                Text(AppStrings.hosting(.cancelled)).font(.omP)
            } else {
                Text(counts).font(.omP).foregroundStyle(Color.fontSecondary)
                if model.partial {
                    Text(AppStrings.hosting(.partialResults)).font(.omP).foregroundStyle(Color.warning)
                        .accessibilityIdentifier("hosting-search-partial")
                }
                if model.embed.status == .error, !model.error.isEmpty {
                    Text(model.error).font(.omP).foregroundStyle(Color.error)
                }
                if model.embed.status == .finished, model.resultCount == 0, model.checkedCount == 0 {
                    Text(AppStrings.hosting(.noResults)).font(.omP)
                }
                if let quote = model.startingQuote {
                    Text(AppStrings.hosting(.fromFirstYear, ["price": HostingMoney.format(quote.amount, currency: model.startingCurrency)])
                         + (quote.basis == .excluding ? " · \(AppStrings.hosting(.taxExcluded))" : ""))
                        .font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
                }
            }
        }
        .padding(.top, .spacing5)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityElement(children: .contain).accessibilityIdentifier("hosting-search-preview")
    }
    private var counts: String {
        var values = [AppStrings.hosting(.checkedCount, ["count": String(model.checkedCount)]),
                      AppStrings.hosting(.availableCount, ["count": String(model.availableCount)]),
                      AppStrings.hosting(.unavailableCount, ["count": String(model.unavailableCount)])]
        if model.unknownCount > 0 { values.append(AppStrings.hosting(.unknownCount, ["count": String(model.unknownCount)])) }
        return values.joined(separator: " · ")
    }
    private var fullscreen: some View {
        let visible = model.visibleChildren(selectedView.wrappedValue)
        return Group {
            if !visible.isEmpty {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: .spacing8)], spacing: .spacing8) {
                    ForEach(visible) { child in
                        EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords) { onOpenEmbed(child) }
                            .environment(\.embedPreviewFillsGridCell, false)
                    }
                }
                .padding(.vertical, .spacing8)
                .accessibilityElement(children: .contain).accessibilityIdentifier("hosting-domain-grid")
            } else if model.isHydrating || model.embed.status == .processing {
                Text(AppStrings.hosting(.processing)).font(.omP).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("hosting-search-loading")
            } else if model.embed.status == .cancelled {
                Text(AppStrings.hosting(.cancelled)).font(.omP).foregroundStyle(Color.fontSecondary)
            } else if !model.error.isEmpty {
                Text(model.error).font(.omP).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("hosting-search-error")
            } else {
                Text(AppStrings.hosting(.noDomainsInView)).font(.omP).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("hosting-search-empty")
            }
        }
        .padding(.horizontal, paneWidth <= 340 ? 0 : paneWidth <= 500 ? .spacing4 : .spacing8)
        .padding(.bottom, 96) // HostingSearchEmbedFullscreen.svelte .grid bottom padding.
        .frame(maxWidth: 1100, alignment: .topLeading)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { paneWidth = $0 }
        // Fullscreen surface identity belongs to the shared chrome container.
        // This Group may have only the grid child; assigning its own identity
        // would replace hosting-domain-grid in the rendered AX hierarchy.
    }
}

struct HostingDomainEmbedRenderer: View {
    let model: HostingDomainModel
    let mode: EmbedDisplayMode
    @State private var paneWidth: CGFloat = 390
    init(embed: EmbedRecord, mode: EmbedDisplayMode) { model = HostingDomainModel(embed); self.mode = mode }
    var body: some View {
        if mode == .preview { preview }
        else { fullscreen }
    }
    private var preview: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            HStack(spacing: .spacing2) {
                Text(model.statusLabel).font(.omSmall).fontWeight(.semibold)
                    .foregroundStyle(model.availability == .available ? Color.buttonPrimary : model.availability == .unknown ? Color.warning : Color.fontPrimary)
                Spacer(minLength: 0)
                if model.premium { badge(.premium) }
            }
            if model.showsBodyName { domainName }
            Text(model.registration?.money(currency: model.currency) ?? AppStrings.hosting(.priceUnavailable))
                .font(model.registration?.quote == nil ? .omSmall : .omH3).fontWeight(.bold)
                .foregroundStyle(model.registration?.quote == nil ? Color.fontSecondary : Color.fontPrimary)
                .accessibilityIdentifier("hosting-domain-registration")
            if let registration = model.registration {
                Text(registration.minimumYears == 1 ? AppStrings.hosting(.firstYear)
                     : registration.minimumYears.map { AppStrings.hosting(.minimumYears, ["count": HostingMoney.number($0)]) } ?? "")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                if registration.quote?.basis == .excluding { Text(AppStrings.hosting(.taxExcluded)).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            }
            if let renewal = model.renewal, let money = renewal.money(currency: model.currency) {
                Text(AppStrings.hosting(.renewalPrice, ["price": money])).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("hosting-domain-renewal")
                if renewal.quote?.basis == .excluding { Text(AppStrings.hosting(.taxExcluded)).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            }
            HStack(spacing: .spacing2) {
                if model.registration?.isFirstYearOffer == true { badge(.firstYearOffer) }
                if let minimum = model.registration?.minimumYears, minimum > 1 {
                    badgeLabel(AppStrings.hosting(.minimumYears, ["count": HostingMoney.number(minimum)]))
                }
                if !model.restrictions.isEmpty { badge(.registrationRestrictions) }
            }
        }
        .padding(.top, .spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityElement(children: .contain).accessibilityIdentifier("hosting-domain-preview")
    }
    private var domainName: some View {
        HStack(spacing: 0) {
            if let dot = model.name.lastIndex(of: "."), dot > model.name.startIndex {
                Text(String(model.name[..<dot])).lineLimit(1).truncationMode(.tail)
                Text(String(model.name[dot...])).fixedSize()
            } else { Text(model.name).lineLimit(1) }
        }.font(.omP).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
    }
    private var fullscreen: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            section {
                field(.domainUnicode, model.name)
                field(.domainASCII, model.ascii).accessibilityIdentifier("hosting-domain-ascii")
            }
            priceSection(.registration, tiers: model.registrationTiers).accessibilityIdentifier("hosting-domain-registration")
            priceSection(.renewal, tiers: model.renewalTiers).accessibilityIdentifier("hosting-domain-renewal")
            section {
                heading(.quoteDetails)
                field(.currency, model.currency)
                if !model.country.isEmpty { Text(AppStrings.hosting(.taxCountry, ["country": model.country])).font(.omP).foregroundStyle(Color.fontSecondary) }
                field(.tax, model.registration?.taxLabel ?? AppStrings.hosting(.taxUnknown))
                if let minimum = model.registration?.minimumYears {
                    field(.minimumTerm, "\(HostingMoney.number(minimum)) \(AppStrings.hosting(minimum == 1 ? .year : .years))")
                }
                if model.premium { field(.premium, AppStrings.hosting(.yes)) }
                if let checked = model.checkedAt {
                    Text(AppStrings.hosting(.checkedAt, ["date": checked.formatted(date: .abbreviated, time: .shortened)]))
                        .font(.omP).foregroundStyle(Color.fontSecondary)
                }
            }
            if !model.restrictions.isEmpty {
                section {
                    heading(.registrationRequirements)
                    ForEach(Array(model.restrictions.enumerated()), id: \.offset) { _, restriction in
                        Text(restriction).font(.omP).textSelection(.enabled)
                    }
                }
            }
            if model.registrationTiers.count > 1 || model.renewalTiers.count > 1 {
                section {
                    Text(AppStrings.hosting(.otherTermPrices, ["count": String(model.registrationTiers.count + model.renewalTiers.count)])).font(.omH3)
                    if model.registrationTiers.count > 1 { tierTable(.registration, tiers: model.registrationTiers) }
                    if model.renewalTiers.count > 1 { tierTable(.renewal, tiers: model.renewalTiers) }
                }
            }
            Text(AppStrings.hosting(.availabilityMayChange)).font(.omSmall).foregroundStyle(Color.fontSecondary)
        }
        .padding(paneWidth <= 600 ? .spacing4 : .spacing8)
        .frame(maxWidth: 760, alignment: .leading)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { paneWidth = $0 }
        .foregroundStyle(Color.fontPrimary)
        .accessibilityElement(children: .contain).accessibilityIdentifier("hosting-domain-details")
    }
    private func badge(_ key: HostingString) -> some View { badgeLabel(AppStrings.hosting(key)) }
    private func badgeLabel(_ label: String) -> some View {
        Text(label).font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.horizontal, .spacing2).padding(.vertical, 2)
            .overlay(RoundedRectangle(cornerRadius: .radius3).stroke(Color.grey30))
    }
    private func heading(_ key: HostingString) -> some View { Text(AppStrings.hosting(key)).font(.omH3) }
    private func field(_ key: HostingString, _ value: String) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: .spacing3) {
                Text(AppStrings.hosting(key)).foregroundStyle(Color.fontSecondary); Spacer(minLength: 0); Text(value).fontWeight(.semibold)
            }
            VStack(alignment: .leading, spacing: .spacing2) {
                Text(AppStrings.hosting(key)).foregroundStyle(Color.fontSecondary); Text(value).fontWeight(.semibold)
            }
        }.font(.omP).textSelection(.enabled).padding(.vertical, .spacing3)
    }
    private func section<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: .spacing4, content: content)
            .frame(maxWidth: .infinity, alignment: .leading).padding(.spacing6)
            .background(Color.grey0).overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey30))
    }
    private func priceSection(_ key: HostingString, tiers: [HostingDomainTier]) -> some View {
        section {
            heading(key)
            if let tier = HostingDomainTier.headline(tiers), let money = tier.money(currency: model.currency) {
                Text(money).font(.omH3).fontWeight(.bold)
                Text(key == .registration && tier.minimumYears == 1 ? AppStrings.hosting(.firstYear)
                     : key == .registration && tier.minimumYears != nil ? AppStrings.hosting(.minimumYears, ["count": HostingMoney.number(tier.minimumYears!)]) : tier.termLabel)
                    .font(.omP).foregroundStyle(Color.fontSecondary)
                if key == .registration, tier.isFirstYearOffer, let normal = tier.normalPrice {
                    Text("\(AppStrings.hosting(.firstYearOffer)) · \(AppStrings.hosting(.normalRegistration)) \(HostingMoney.format(normal, currency: model.currency)) / \(AppStrings.hosting(.year))").font(.omP)
                }
            } else { Text(AppStrings.hosting(.priceUnavailable)).font(.omP) }
        }
    }
    private func tierTable(_ key: HostingString, tiers: [HostingDomainTier]) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(AppStrings.hosting(key)).font(.omP).fontWeight(.semibold)
            ForEach(Array(tiers.enumerated()), id: \.offset) { _, tier in
                HStack(alignment: .top, spacing: .spacing3) {
                    Text(tier.termLabel)
                    Spacer(minLength: 0)
                    Text("\(tier.money(currency: model.currency) ?? AppStrings.hosting(.priceUnavailable)) · \(tier.taxLabel)")
                }.font(.omP).textSelection(.enabled)
                Rectangle().fill(Color.grey25).frame(height: 1)
            }
        }
    }
}
