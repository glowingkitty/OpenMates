// Pricing overview — shows App Store prices from StoreKit for non-authenticated users.
// Falls back to hardcoded tiers from pricing.yml if StoreKit products aren't available.
// Links to Apps and AI models for browsing before signup.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsPricing.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
//          frontend/packages/ui/src/styles/cards.css (.pricing-card)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import StoreKit

struct SettingsPricingView: View {
    @StateObject private var storeManager = StoreManager.shared

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text(LocalizationManager.shared.text("settings.billing.credit_packages"))
                    .font(.omH3).fontWeight(.bold)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)

                if storeManager.products.isEmpty {
                    // Fallback: show hardcoded tiers while StoreKit loads
                    ForEach(fallbackTiers) { tier in
                        FallbackPricingCard(tier: tier)
                    }
                } else {
                    ForEach(storeManager.products, id: \.id) { product in
                        StoreKitPricingCard(product: product)
                    }
                }

                Divider().padding(.vertical, .spacing4)

                VStack(spacing: .spacing4) {
                    Text(LocalizationManager.shared.text("settings.pricing.explore_before_signup"))
                        .font(.omH4).fontWeight(.semibold)

                    Text(LocalizationManager.shared.text("settings.pricing.browse_apps_models"))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .multilineTextAlignment(.center)

                    HStack(spacing: .spacing4) {
                        NavigationLink {
                            SettingsAppsFullView()
                        } label: {
                            Label(AppStrings.apps, systemImage: "square.grid.2x2")
                                .font(.omSmall).fontWeight(.medium)
                        }
                        .buttonStyle(.bordered)

                        NavigationLink {
                            SettingsAIFullView()
                        } label: {
                            Label(LocalizationManager.shared.text("settings.pricing.ai_models"), systemImage: "brain")
                                .font(.omSmall).fontWeight(.medium)
                        }
                        .buttonStyle(.bordered)
                    }
                }
                .padding(.horizontal)

                Spacer(minLength: .spacing8)
            }
            .padding(.vertical)
        }
        .navigationTitle(AppStrings.settingsPricing)
        .task { await storeManager.loadProducts() }
    }

    // MARK: - Fallback tiers (shown while StoreKit loads or if unavailable)

    struct FallbackTier: Identifiable {
        let id = UUID()
        let credits: Int
        let priceDisplay: String
        let bonusCredits: Int?
        let recommended: Bool
    }

    private var fallbackTiers: [FallbackTier] {
        [
            FallbackTier(credits: 1_000, priceDisplay: "$2.99", bonusCredits: nil, recommended: false),
            FallbackTier(credits: 10_000, priceDisplay: "$14.99", bonusCredits: 500, recommended: false),
            FallbackTier(credits: 21_000, priceDisplay: "$29.99", bonusCredits: 1_000, recommended: true),
            FallbackTier(credits: 54_000, priceDisplay: "$59.99", bonusCredits: 3_000, recommended: false),
        ]
    }
}

// MARK: - StoreKit pricing card (real App Store prices)

struct StoreKitPricingCard: View {
    let product: Product

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack(spacing: .spacing3) {
                    Text("\(product.formattedCredits) credits")
                        .font(.omP).fontWeight(.semibold)

                    if product.isRecommended {
                        Text(LocalizationManager.shared.text("settings.billing.best_value"))
                            .font(.omTiny).fontWeight(.bold)
                            .foregroundStyle(.white)
                            .padding(.horizontal, .spacing2)
                            .padding(.vertical, 2)
                            .background(Color.buttonPrimary)
                            .clipShape(RoundedRectangle(cornerRadius: .radius1))
                    }
                }

                let bonusCredits: Int = switch product.creditsAmount {
                case 10_000: 500
                case 21_000: 1_000
                case 54_000: 3_000
                default: 0
                }
                if bonusCredits > 0 {
                    Text("+\(bonusCredits) bonus with monthly auto top-up")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }

            Spacer()

            Text(product.displayPrice)
                .font(.omH4).fontWeight(.bold)
                .foregroundStyle(Color.buttonPrimary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel({
            let bonus: Int = switch product.creditsAmount {
            case 10_000: 500; case 21_000: 1_000; case 54_000: 3_000; default: 0
            }
            var label = "\(product.formattedCredits) credits, \(product.displayPrice)"
            if product.isRecommended { label += ", \(LocalizationManager.shared.text("settings.billing.best_value"))" }
            if bonus > 0 { label += ", plus \(bonus) bonus credits with auto top-up" }
            return label
        }())
        .padding(.spacing4)
        .background(product.isRecommended ? Color.buttonPrimary.opacity(0.05) : Color.grey10.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .overlay {
            if product.isRecommended {
                RoundedRectangle(cornerRadius: .radius4)
                    .stroke(Color.buttonPrimary.opacity(0.3), lineWidth: 1)
            }
        }
        .padding(.horizontal)
    }
}

// MARK: - Fallback pricing card (hardcoded prices)

struct FallbackPricingCard: View {
    let tier: SettingsPricingView.FallbackTier

    private var formattedCredits: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.groupingSeparator = "."
        return formatter.string(from: NSNumber(value: tier.credits)) ?? "\(tier.credits)"
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack(spacing: .spacing3) {
                    Text("\(formattedCredits) credits")
                        .font(.omP).fontWeight(.semibold)

                    if tier.recommended {
                        Text(LocalizationManager.shared.text("settings.billing.best_value"))
                            .font(.omTiny).fontWeight(.bold)
                            .foregroundStyle(.white)
                            .padding(.horizontal, .spacing2)
                            .padding(.vertical, 2)
                            .background(Color.buttonPrimary)
                            .clipShape(RoundedRectangle(cornerRadius: .radius1))
                    }
                }

                if let bonus = tier.bonusCredits {
                    Text("+\(bonus) bonus with monthly auto top-up")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }

            Spacer()

            Text(tier.priceDisplay)
                .font(.omH4).fontWeight(.bold)
                .foregroundStyle(Color.buttonPrimary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel({
            var label = "\(formattedCredits) credits, \(tier.priceDisplay)"
            if tier.recommended { label += ", \(LocalizationManager.shared.text("settings.billing.best_value"))" }
            if let bonus = tier.bonusCredits { label += ", plus \(bonus) bonus credits with auto top-up" }
            return label
        }())
        .padding(.spacing4)
        .background(tier.recommended ? Color.buttonPrimary.opacity(0.05) : Color.grey10.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .overlay {
            if tier.recommended {
                RoundedRectangle(cornerRadius: .radius4)
                    .stroke(Color.buttonPrimary.opacity(0.3), lineWidth: 1)
            }
        }
        .padding(.horizontal)
    }
}
