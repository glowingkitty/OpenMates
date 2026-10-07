// AI settings provider families and authenticated response/default preferences.
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.navigation.parent-return, settings-ui.parity.web-apple-shell
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
// Specification: specifications/features/ai-model-routing/specification.yml
// Assertions: ai-model-routing.settings.hierarchy-canonical, ai-model-routing.preferences.exclusive-tier-defaults,
//             ai-model-routing.catalog.capability-recommendation-variants
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/settings/SettingsAI.svelte
//         frontend/packages/ui/src/components/settings/AiTierSettings.svelte
//         frontend/packages/ui/src/components/settings/AiProviderDetailsWrapper.svelte
//         frontend/packages/ui/src/components/settings/AiAskModelDetails.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsItem.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsInfoBox.svelte
// CSS: Inline .ai-settings-body, .ai-provider-body, .settings-item--ai-row
// Data: frontend/packages/ui/src/data/modelsMetadata.ts, aiProviderDisplay.json
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsAIFullView: View {
    var initialModelID: String? = nil
    var initialProviderID: String? = nil
    var initialTier: AIRequestTier? = nil
    var onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)? = nil
    @EnvironmentObject private var authManager: AuthManager
    @ObservedObject private var modelCatalog = NativeModelCatalogRuntime.shared
    @State private var defaultSimpleModel = ""
    @State private var defaultComplexModel = ""
    @State private var defaultMostDemandingModel = ""
    @State private var selectedTier: AIRequestTier?
    @State private var selectedTierProviderID: String?
    @State private var fixturePreferences = NativeModelDisabledPreferences.Value()
    @State private var followUpSuggestionsEnabled = true
    @State private var quickTipsEnabled = true
    @State private var isSaving = false
    @State private var isLoadingPreferences = false
    @State private var hasLoadedPreferences = false
    @State private var errorMessage: String?
    @State private var selectedProviderID: String?
    @State private var selectedModelID: String?

    struct ModelDetail: Identifiable, Equatable {
        let id: String
        let name: String
        let providerName: String
        let description: String
        let releaseDate: String
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.settingsAI, showsHeader: false, contentHorizontalPadding: 0, contentVerticalSpacing: 0, scrollAccessibilityIdentifier: "ai-settings-scroll") {
            VStack(alignment: .leading, spacing: .spacing10) {
                if let selectedModel {
                    if onChildNavigationChanged == nil { childBackRow { selectedModelID = nil } }
                    modelPage(selectedModel)
                } else if let tier = selectedTier {
                    tierPage(tier)
                } else if let provider = selectedProvider {
                    providerPage(provider)
                } else {
                    overview
                }
                if let errorMessage {
                    Text(errorMessage).font(.omSmall).foregroundStyle(Color.error)
                        .accessibilityIdentifier("settings-ai-error")
                }
            }
            .frame(maxWidth: AISettingsMetrics.bodyWidth)
            .frame(maxWidth: .infinity)
        }
        .accessibilityElement(children: .contain)
                .accessibilityIdentifier("ai-settings")
        .task {
            selectInitialRoute()
            await loadModelPreferences()
        }
        .onChange(of: initialModelID) { _, _ in selectInitialRoute() }
        .onChange(of: initialProviderID) { _, _ in selectInitialRoute() }
        .onChange(of: initialTier) { _, _ in selectInitialRoute() }
        .onChange(of: modelCatalog.catalog?.sourceDigest) { _, _ in selectInitialRoute() }
        .onChange(of: selectedProviderID) { _, _ in publishChildNavigation() }
        .onChange(of: selectedModelID) { _, _ in publishChildNavigation() }
        .onChange(of: selectedTier) { _, _ in publishChildNavigation() }
        .onChange(of: selectedTierProviderID) { _, _ in publishChildNavigation() }
        .onDisappear { onChildNavigationChanged?(nil) }
    }

    private var overview: some View {
        VStack(alignment: .leading, spacing: .spacing10) {
            Text(AppStrings.aiPricingNote)
                .font(.omSmall.weight(.medium))
                .foregroundStyle(Color.aiSettingsPricing)
                .padding(.horizontal, .spacing10)
                .accessibilityLabel(AppStrings.pricing)
                .accessibilityIdentifier("ai-pricing-note")

            if isAuthenticated {
                VStack(alignment: .leading, spacing: .spacing5) {
                    AISettingsHeading(title: AppStrings.defaultModels, icon: "settings")
                    VStack(spacing: .spacing4) {
                        ForEach(AIRequestTier.allCases, id: \.self) { tier in
                            AISettingsPreferenceRow(tier: tier, value: modelLabel(tierSelection(tier))) {
                                selectedTier = tier
                            }
                        }
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("ai-default-models-group")
            }

            VStack(alignment: .leading, spacing: .spacing5) {
                AISettingsHeading(title: AppStrings.aiModelsAndAccounts, icon: "ai")
                VStack(spacing: .spacing4) {
                    ForEach(providerFamilies, id: \.id) { provider in
                        AISettingsFamilyRow(title: provider.brandName,
                                            subtitle: attribution(provider), logo: provider.logoSvg) {
                            selectedProviderID = provider.id
                        }
                        .accessibilityIdentifier("ai-provider-family-card")
                        .accessibilityValue(provider.id)
                    }
                }
            }
            .accessibilityElement(children: .contain)
                .accessibilityIdentifier("ai-models-accounts-group")

            if isAuthenticated {
                VStack(alignment: .leading, spacing: .spacing5) {
                    AISettingsHeading(title: AppStrings.aiResponseSettings, icon: "settings")
                    AISettingsSwitchRow(title: AppStrings.aiFollowUpSuggestions, subtitle: AppStrings.aiFollowUpDescription,
                        logo: "chat", value: Binding(get: { followUpSuggestionsEnabled }, set: { next in
                            let previous = followUpSuggestionsEnabled
                            followUpSuggestionsEnabled = next
                            saveDefaults(rollbackFollowUpsTo: previous)
                        }), disabled: isSaving || !hasLoadedPreferences,
                        identifier: "ai-response-feature-follow-up-suggestions")
                    AISettingsSwitchRow(title: AppStrings.aiQuickTips, subtitle: AppStrings.aiQuickTipsDescription,
                        logo: "insight", value: Binding(get: { quickTipsEnabled }, set: { next in
                            let previous = quickTipsEnabled
                            quickTipsEnabled = next
                            saveDefaults(rollbackQuickTipsTo: previous)
                        }), disabled: isSaving || !hasLoadedPreferences,
                        identifier: "ai-response-feature-quick-tips")
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("ai-response-settings-group")
            }
        }
    }

    private func tierPage(_ tier: AIRequestTier) -> some View {
        let models = tierModels.filter { selectedTierProviderID == nil || $0.provider_id == selectedTierProviderID }
        let recommendedID = tier.recommendedModel(in: models)?.id
        return VStack(alignment: .leading, spacing: .spacing10) {
            if onChildNavigationChanged == nil {
                childBackRow { if selectedTierProviderID != nil { selectedTierProviderID = nil } else { selectedTier = nil } }
            }
            Text(selectedTierProviderID == nil ? AppStrings.aiChooseTierProvider : AppStrings.aiChooseExactModel)
                .font(.omSmall.weight(.medium)).foregroundStyle(Color.aiSettingsMuted)
                .padding(.horizontal, .spacing10).accessibilityIdentifier("ai-tier-routing-note")
            VStack(alignment: .leading, spacing: .spacing5) {
                Text(AppStrings.defaultModels).font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
                    .padding(.horizontal, .spacing10)
                HStack(spacing: .spacing6) {
                    AISettingsCapability(level: tier.capability)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(AppStrings.auto).font(.omP.weight(.bold)).foregroundStyle(LinearGradient.primary)
                        Text(AppStrings.aiAutoDescription).font(.omSmall.weight(.bold)).foregroundStyle(Color.aiSettingsMuted)
                    }
                    Spacer(minLength: 0)
                    AISettingsToggle(isOn: Binding(get: { tierSelection(tier) == nil }, set: { _ in saveTierSelection(tier, value: nil) }),
                        disabled: isSaving || !hasLoadedPreferences, accessibilityIdentifier: "ai-model-option-auto-toggle")
                        .accessibilityLabel(AppStrings.auto)
                }
                .padding(.horizontal, .spacing10).accessibilityElement(children: .contain).accessibilityIdentifier("ai-model-option-auto")
                Text(selectedTierProviderID.flatMap { id in providerFamilies.first { $0.id == id }?.brandName } ?? AppStrings.aiModelsAndAccounts)
                    .font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary).padding(.horizontal, .spacing10)
                VStack(spacing: .spacing4) {
                    if selectedTierProviderID != nil {
                        ForEach(models, id: \.id) { model in
                            HStack(spacing: AISettingsMetrics.rowGap) {
                                AISettingsFamilyRow(title: model.name,
                                    subtitle: [model.id == recommendedID ? AppStrings.aiRecommended : nil, model.tier,
                                        model.description, AppStrings.aiCapability(model.capability_level ?? "medium")]
                                        .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "), logo: model.logo_svg, trailingPadding: isAuthenticated && canEditPreferences ? 0 : .spacing10) {
                                    selectedModelID = model.id
                                }.accessibilityIdentifier("ai-model-option-exact").accessibilityValue(model.id)
                                AISettingsToggle(isOn: Binding(get: { tierSelection(tier) == model.provider_id + "/" + model.id },
                                    set: { _ in saveTierSelection(tier, value: model.provider_id + "/" + model.id) }),
                                    disabled: isSaving || !hasLoadedPreferences,
                                    accessibilityIdentifier: "ai-model-option-exact-toggle-" + model.id)
                                    .accessibilityLabel(model.name).padding(.trailing, .spacing10)
                            }
                        }
                    } else {
                        ForEach(providerFamilies.filter { provider in models.contains { $0.provider_id == provider.id } }, id: \.id) { provider in
                            AISettingsFamilyRow(title: provider.brandName,
                                subtitle: attribution(provider) ?? AppStrings.aiViewProviderModels, logo: provider.logoSvg) {
                                selectedTierProviderID = provider.id
                            }.accessibilityIdentifier("ai-provider-family-card").accessibilityValue(provider.id)
                        }
                    }
                }
            }.accessibilityElement(children: .contain)
                .accessibilityIdentifier("ai-tier-provider-catalog")
        }
    }

    private func providerPage(_ provider: NativeModelCatalog.ProviderDisplay) -> some View {
        VStack(alignment: .leading, spacing: .spacing10) {
            if onChildNavigationChanged == nil { childBackRow { selectedProviderID = nil } }
            VStack(spacing: .spacing3) {
                AISettingsProviderLogo(path: provider.logoSvg)
                Text(provider.brandName).font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
                if let attribution = attribution(provider) {
                    Text(attribution).font(.omSmall.weight(.bold)).foregroundStyle(Color.aiSettingsMuted)
                }
            }
            .frame(maxWidth: .infinity)
            .accessibilityIdentifier("ai-provider-identity")

            Text(AppStrings.aiProviderModelsInstruction)
                .font(.omSmall.weight(.medium)).foregroundStyle(Color.aiSettingsMuted)
                .padding(.horizontal, .spacing10)
                .accessibilityIdentifier("ai-provider-guidance")

            VStack(alignment: .leading, spacing: .spacing5) {
                Text(AppStrings.aiProviderModelsHeading(provider.brandName))
                    .font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
                    .padding(.horizontal, .spacing10)
                VStack(spacing: .spacing4) {
                    ForEach(providerModels, id: \.id) { model in
                        HStack(spacing: AISettingsMetrics.rowGap) {
                            AISettingsFamilyRow(title: model.name, subtitle: modelSubtitle(model),
                                                logo: model.logo_svg, trailingPadding: isAuthenticated && canEditPreferences ? 0 : .spacing10) {
                                selectedModelID = model.id
                            }
                            .accessibilityIdentifier("provider-model-item")
                            .accessibilityValue(model.id)
                            if isAuthenticated, canEditPreferences {
                                AISettingsToggle(isOn: Binding(
                                    get: { !disabledPreferences.disabled_ai_models.contains(model.id) },
                                    set: { setModel(model.id, enabled: $0) }),
                                    accessibilityIdentifier: "provider-model-item-toggle-" + model.id)
                                .accessibilityLabel(model.name)
                                .padding(.trailing, .spacing10)
                            }
                        }
                    }
                }
            }
            .accessibilityElement(children: .contain)
                .accessibilityIdentifier("ai-provider-details")
        }
    }

    private func modelPage(_ model: NativeModelCatalog.Model) -> some View {
        VStack(alignment: .leading, spacing: .spacing10) {
            Text(model.description ?? "")
                .font(.omSmall.weight(.medium)).foregroundStyle(Color.aiSettingsMuted)
                .padding(.horizontal, .spacing10)
                .accessibilityIdentifier("ai-model-description")
            if isAuthenticated, canEditPreferences {
                HStack(spacing: AISettingsMetrics.rowGap) {
                    AISettingsFamilyRow(title: AppStrings.aiEnableModel, subtitle: model.name, logo: model.logo_svg, trailingPadding: isAuthenticated && canEditPreferences ? 0 : .spacing10) {
                        setModel(model.id, enabled: disabledPreferences.disabled_ai_models.contains(model.id))
                    }
                    AISettingsToggle(isOn: Binding(
                        get: { !disabledPreferences.disabled_ai_models.contains(model.id) },
                        set: { setModel(model.id, enabled: $0) }),
                        accessibilityIdentifier: "ai-model-enabled-toggle")
                        .accessibilityLabel(AppStrings.aiEnableModel)
                        .padding(.trailing, .spacing10)
                }
            }
            modelSection(AppStrings.aiDetails, identifier: "ai-model-summary-section") {
                HStack(spacing: .spacing6) {
                    AISettingsCapability(level: model.capability_level ?? "medium")
                    VStack(alignment: .leading, spacing: 0) {
                        Text(AppStrings.aiCapabilityTitle).font(.omSmall.weight(.bold)).foregroundStyle(Color.aiSettingsMuted)
                        Text(AppStrings.aiCapability(model.capability_level ?? "medium"))
                            .font(.omP.weight(.medium)).foregroundStyle(LinearGradient.primary)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, .spacing10)
                .accessibilityIdentifier("ai-model-capability-row")
                AISettingsDetailRow(title: AppStrings.aiModelOrigin,
                    value: modelCatalog.catalog?.providers.first(where: { $0.id == model.provider_id })?.companyName ?? model.provider_name,
                    icon: "openmates", identifier: "ai-model-origin-row")
                if let date = model.release_date {
                    AISettingsDetailRow(title: AppStrings.aiModelReleaseDate, value: AISettingsReleaseDate.string(date),
                        icon: "time", identifier: "ai-model-release-row")
                }
                AISettingsDetailRow(title: AppStrings.aiModelInputTypes,
                    value: (model.input_types ?? []).map(AppStrings.aiMediaType).joined(separator: ", "),
                    icon: "text", identifier: "ai-model-input-types-row")
                AISettingsDetailRow(title: AppStrings.aiModelOutputTypes,
                    value: (model.output_types ?? []).map(AppStrings.aiMediaType).joined(separator: ", "),
                    icon: "document", identifier: "ai-model-output-types-row")
            }
            if let pricing = model.pricing {
                modelSection(AppStrings.pricing, identifier: "ai-model-pricing-section") {
                    let cacheActive = model.cachePricesActive()
                    let longContext = model.longContextPricesActive() ? pricing.context_bands?.over_272k : nil
                    if longContext != nil {
                        Text(AppStrings.modelPriceStandardPricing).font(.omSmall.weight(.bold))
                            .foregroundStyle(Color.aiSettingsMuted).padding(.horizontal, .spacing10)
                    }
                    if let input = pricing.input_tokens_per_credit {
                        AISettingsDetailRow(title: AppStrings.modelPriceUncachedInput, value: AppStrings.aiPrice(input),
                            icon: "coins", identifier: "ai-model-pricing-input-row")
                        AISettingsDetailRow(title: AppStrings.modelPriceCacheRead,
                            value: cacheActive ? pricing.cache_read_tokens_per_credit.flatMap { $0 > 0 ? AppStrings.aiPrice($0) : nil } ?? AppStrings.modelPriceUnavailable : AppStrings.modelPriceUnavailable,
                            icon: "coins", identifier: "ai-model-pricing-cache-read-row")
                        let writeValue = cacheActive
                            ? (model.cache_pricing?.write_billing == "included_in_input" ? AppStrings.modelPriceIncludedInInput : pricing.cache_write_tokens_per_credit.flatMap { $0 > 0 ? AppStrings.aiPrice($0) : nil } ?? AppStrings.modelPriceUnavailable)
                            : AppStrings.modelPriceUnavailable
                        AISettingsDetailRow(title: model.cache_pricing?.write_billing == "included_in_input" ? AppStrings.modelPriceCacheWrite : AppStrings.modelPriceCacheWrite5m,
                            value: writeValue,
                            icon: "coins", identifier: "ai-model-pricing-cache-write-row")
                        if cacheActive, model.supportsOneHourCacheWrites,
                           let oneHour = pricing.cache_write_1h_tokens_per_credit, oneHour > 0 {
                            AISettingsDetailRow(title: AppStrings.modelPriceCacheWrite1h, value: AppStrings.aiPrice(oneHour),
                                icon: "coins", identifier: "ai-model-pricing-cache-write-1h-row")
                        }
                    }
                    if let output = pricing.output_tokens_per_credit {
                        AISettingsDetailRow(title: AppStrings.modelPriceOutput, value: AppStrings.aiPrice(output),
                            icon: "coins", identifier: "ai-model-pricing-output-row")
                    }
                    if let band = longContext {
                        Text(AppStrings.modelPriceOver272kPricing).font(.omSmall.weight(.bold))
                            .foregroundStyle(Color.aiSettingsMuted).padding(.horizontal, .spacing10)
                        Text(AppStrings.modelPriceOver272kExplanation).font(.omSmall)
                            .foregroundStyle(Color.aiSettingsMuted).padding(.horizontal, .spacing10)
                        if let input = band.input_tokens_per_credit {
                            AISettingsDetailRow(title: AppStrings.modelPriceUncachedInput, value: AppStrings.aiPrice(input),
                                icon: "coins", identifier: "ai-model-pricing-over-272k-input-row")
                        }
                        if let read = band.cache_read_tokens_per_credit {
                            AISettingsDetailRow(title: AppStrings.modelPriceCacheRead, value: AppStrings.aiPrice(read),
                                icon: "coins", identifier: "ai-model-pricing-over-272k-cache-read-row")
                        }
                        let writeValue = model.cache_pricing?.write_billing == "included_in_input"
                            ? AppStrings.modelPriceIncludedInInput
                            : band.cache_write_tokens_per_credit.map(AppStrings.aiPrice) ?? AppStrings.modelPriceUnavailable
                        AISettingsDetailRow(title: model.cache_pricing?.write_billing == "included_in_input" ? AppStrings.modelPriceCacheWrite : AppStrings.modelPriceCacheWrite5m,
                            value: writeValue, icon: "coins", identifier: "ai-model-pricing-over-272k-cache-write-row")
                        if let output = band.output_tokens_per_credit {
                            AISettingsDetailRow(title: AppStrings.modelPriceOutput, value: AppStrings.aiPrice(output),
                                icon: "coins", identifier: "ai-model-pricing-over-272k-output-row")
                        }
                    }
                    if let summary = modelCatalog.catalog?.automaticSummaryPricing(for: model) {
                        Text(AppStrings.modelPriceAutomaticSummaryTitle).font(.omSmall.weight(.bold))
                            .foregroundStyle(Color.aiSettingsMuted).padding(.horizontal, .spacing10)
                        Text(AppStrings.modelPriceAutomaticSummaryExplanation).font(.omSmall)
                            .foregroundStyle(Color.aiSettingsMuted).padding(.horizontal, .spacing10)
                        Text(summary.primary.modelName).font(.omSmall.weight(.bold))
                            .foregroundStyle(Color.aiSettingsMuted).padding(.horizontal, .spacing10)
                        AISettingsDetailRow(title: AppStrings.modelPriceUncachedInput, value: AppStrings.aiPrice(summary.primary.inputTokensPerCredit),
                            icon: "coins", identifier: "ai-model-pricing-summary-primary-input-row")
                        AISettingsDetailRow(title: AppStrings.modelPriceOutput, value: AppStrings.aiPrice(summary.primary.outputTokensPerCredit),
                            icon: "coins", identifier: "ai-model-pricing-summary-primary-output-row")
                        Text(AppStrings.modelPriceAutomaticSummaryFallback + ": " + summary.fallback.modelName).font(.omSmall.weight(.bold))
                            .foregroundStyle(Color.aiSettingsMuted).padding(.horizontal, .spacing10)
                        AISettingsDetailRow(title: AppStrings.modelPriceUncachedInput, value: AppStrings.aiPrice(summary.fallback.inputTokensPerCredit),
                            icon: "coins", identifier: "ai-model-pricing-summary-fallback-input-row")
                        AISettingsDetailRow(title: AppStrings.modelPriceOutput, value: AppStrings.aiPrice(summary.fallback.outputTokensPerCredit),
                            icon: "coins", identifier: "ai-model-pricing-summary-fallback-output-row")
                    }
                }
            }
            modelSection(AppStrings.aiExamples, identifier: "ai-model-example-chats") {
                AISettingsExampleCard(title: AppStrings.simpleRequests, subtitle: AppStrings.aiSimpleRequestsDescription)
                AISettingsExampleCard(title: AppStrings.complexRequests, subtitle: AppStrings.aiComplexRequestsDescription)
            }
            if !model.servers.isEmpty {
                modelSection(AppStrings.aiModelProviders, identifier: "ai-model-provider-options") {
                    ForEach(model.servers, id: \.id) { server in
                        HStack(spacing: AISettingsMetrics.rowGap) {
                            AISettingsFamilyRow(title: server.name ?? server.id,
                                subtitle: AppStrings.aiServerRegion(server.region ?? ""), logo: "server", trailingPadding: isAuthenticated && canEditPreferences ? 0 : .spacing10) {
                                guard isAuthenticated, canEditPreferences else { return }
                                let disabled = disabledPreferences.disabled_ai_servers[model.id] ?? []
                                setServer(server.id, model: model.id, enabled: disabled.contains(server.id))
                            }
                            if isAuthenticated, canEditPreferences {
                                AISettingsToggle(isOn: Binding(
                                    get: { !(disabledPreferences.disabled_ai_servers[model.id] ?? []).contains(server.id) },
                                    set: { setServer(server.id, model: model.id, enabled: $0) }),
                                    accessibilityIdentifier: "ai-model-provider-option-" + server.id)
                                    .accessibilityLabel(server.name ?? server.id)
                                    .padding(.trailing, .spacing10)
                            }
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("ai-model-provider-option-" + server.id + "-row")
                    }
                }
            }
        }
        .accessibilityElement(children: .contain)
                .accessibilityIdentifier("ai-model-details")
    }
    private func modelSection<Content: View>(_ title: String, identifier: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            Text(title).font(.omP.weight(.bold)).foregroundStyle(Color.fontPrimary)
                .padding(.horizontal, .spacing10)
            VStack(alignment: .leading, spacing: .spacing4, content: content)
        }.accessibilityElement(children: .contain).accessibilityIdentifier(identifier)
    }

    private func childBackRow(_ action: @escaping () -> Void) -> some View {
        OMSettingsRow(title: AppStrings.back, icon: "back", showsChevron: false,
                      accessibilityIdentifier: "settings-ai-child-back", action: action)
    }

    private var isAuthenticated: Bool { authManager.currentUser != nil }
    private var providerFamilies: [NativeModelCatalog.ProviderDisplay] {
        Self.providerFamilies(catalog: modelCatalog.catalog)
    }
    private var selectedProvider: NativeModelCatalog.ProviderDisplay? {
        providerFamilies.first { $0.id == selectedProviderID }
    }
    private var selectedModel: NativeModelCatalog.Model? {
        modelCatalog.catalog?.models.first { $0.id == selectedModelID }
    }
    private var providerModels: [NativeModelCatalog.Model] {
        Self.providerModels(catalog: modelCatalog.catalog, providerID: selectedProviderID)
    }
    private var usesPreferenceFixture: Bool {
        #if DEBUG
        return authManager.currentUser?.id == "ui-test-chat-navigation-user" &&
            ProcessInfo.processInfo.arguments.contains("--ui-test-ai-preferences-fixture")
        #else
        return false
        #endif
    }
    private var canEditPreferences: Bool { usesPreferenceFixture || modelCatalog.canEditPreferences }
    private var disabledPreferences: NativeModelDisabledPreferences.Value {
        usesPreferenceFixture ? fixturePreferences : modelCatalog.disabledPreferences
    }
    private func setModel(_ id: String, enabled: Bool) {
        guard isAuthenticated else { return }
        if usesPreferenceFixture {
            if enabled { fixturePreferences.disabled_ai_models.remove(id) }
            else { fixturePreferences.disabled_ai_models.insert(id) }
        } else { modelCatalog.setModel(id, enabled: enabled) }
    }
    private func setServer(_ id: String, model: String, enabled: Bool) {
        guard isAuthenticated else { return }
        if usesPreferenceFixture {
            if enabled { fixturePreferences.disabled_ai_servers[model, default: []].remove(id) }
            else { fixturePreferences.disabled_ai_servers[model, default: []].insert(id) }
        } else { modelCatalog.setServer(id, model: model, enabled: enabled) }
    }
    private func modelLabel(_ value: String?) -> String {
        guard let value else { return AppStrings.auto }
        return modelCatalog.catalog?.models.first { $0.provider_id + "/" + $0.id == value }?.name ?? value
    }
    private func tierSelection(_ tier: AIRequestTier) -> String? {
        let value: String
        switch tier {
        case .simple: value = defaultSimpleModel
        case .complex: value = defaultComplexModel
        case .mostDemanding: value = defaultMostDemandingModel
        }
        return value.isEmpty ? nil : value
    }
    private func setTierSelection(_ tier: AIRequestTier, value: String?) {
        switch tier {
        case .simple: defaultSimpleModel = value ?? ""
        case .complex: defaultComplexModel = value ?? ""
        case .mostDemanding: defaultMostDemandingModel = value ?? ""
        }
    }
    private var tierModels: [NativeModelCatalog.Model] {
        guard let catalog = modelCatalog.catalog else { return [] }
        let routing = catalog.routing(disabledModels: disabledPreferences.disabled_ai_models,
            disabledServers: disabledPreferences.disabled_ai_servers, health: usesPreferenceFixture ? nil : modelCatalog.health)
        return AIRequestTier.eligibleModels(catalog: catalog, routing: routing)
    }
    private func saveTierSelection(_ tier: AIRequestTier, value: String?) {
        guard isAuthenticated, hasLoadedPreferences, !isSaving, value != tierSelection(tier) else { return }
        let previous = tierSelection(tier)
        setTierSelection(tier, value: value)
        isSaving = true
        errorMessage = nil
        Task {
            do {
                if usesPreferenceFixture {
                    if ProcessInfo.processInfo.arguments.contains("--ui-test-ai-preferences-save-failure") { throw CocoaError(.fileWriteUnknown) }
                } else {
                    let _: Data = try await APIClient.shared.request(.post, path: "/v1/settings/ai-model-defaults",
                        body: AITierSelectionRequest(tier: tier, selection: value))
                }
            } catch {
                setTierSelection(tier, value: previous)
                errorMessage = AppStrings.aiPreferencesSaveError
                NativeDiagnostics.error("AI tier preference save failed", category: "settings.ai")
            }
            isSaving = false
        }
    }

    private func attribution(_ provider: NativeModelCatalog.ProviderDisplay) -> String? {
        provider.brandName == provider.companyName ? nil : AppStrings.aiFromProvider(provider.companyName)
    }
    private func modelSubtitle(_ model: NativeModelCatalog.Model) -> String {
        [AppStrings.aiCapability(model.capability_level ?? "medium"), model.description ?? ""]
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }
    private func publishChildNavigation() {
        if let selectedModel {
            onChildNavigationChanged?(SettingsChildBannerNavigation(title: selectedModel.name, description: "", onBack: {
                selectedModelID = nil
            }))
        } else if let tier = selectedTier {
            if let provider = providerFamilies.first(where: { $0.id == selectedTierProviderID }) {
                onChildNavigationChanged?(SettingsChildBannerNavigation(title: provider.brandName,
                    description: AppStrings.aiProviderHeaderDescription(provider.companyName), onBack: { selectedTierProviderID = nil }))
            } else {
                onChildNavigationChanged?(SettingsChildBannerNavigation(title: tier.title,
                    description: tier.description, onBack: { selectedTier = nil }))
            }
        } else if let provider = selectedProvider {
            onChildNavigationChanged?(SettingsChildBannerNavigation(title: provider.brandName, description: AppStrings.aiProviderHeaderDescription(provider.companyName),
                breadcrumb: AppStrings.settings + " / " + AppStrings.settingsAI, onBack: {
                selectedProviderID = nil
            }))
        } else {
            onChildNavigationChanged?(nil)
        }
    }
    private func selectInitialRoute() {
        if let initialTier, isAuthenticated {
            selectedTier = initialTier
            selectedTierProviderID = initialProviderID
        } else if let initialModelID, modelCatalog.catalog?.models.contains(where: { $0.id == initialModelID }) == true {
            selectedModelID = initialModelID
        } else if let initialProviderID, providerFamilies.contains(where: { $0.id == initialProviderID }) {
            selectedProviderID = initialProviderID
        }
    }

    // The overview uses provider product families; hosting servers belong to model
    // details. Filter by ai.ask to avoid exposing unrelated app model families.
    static func providerFamilies(catalog: NativeModelCatalog?) -> [NativeModelCatalog.ProviderDisplay] {
        guard let catalog else { return [] }
        return catalog.pickerProviders.sorted {
            if $0.order != $1.order { return $0.order < $1.order }
            return $0.brandName.localizedCompare($1.brandName) == .orderedAscending
        }
    }
    static func providerModels(catalog: NativeModelCatalog?, providerID: String?, query: String = "") -> [NativeModelCatalog.Model] {
        guard let providerID else { return [] }
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return (catalog?.models ?? []).filter {
            $0.for_app_skill == "ai.ask" && $0.provider_id == providerID &&
            (query.isEmpty || $0.name.localizedCaseInsensitiveContains(query) ||
             ($0.description ?? "").localizedCaseInsensitiveContains(query))
        }
    }
    static func catalogModel(id: String?) -> NativeModelCatalog.Model? {
        guard let id else { return nil }
        return NativeModelCatalogRuntime.shared.catalog?.models.first { $0.id == id }
    }
    static func modelDetail(id: String?, canonicalModels: [NativeModelCatalog.Model]) -> ModelDetail? {
        guard let id, let model = canonicalModels.first(where: { $0.id == id }) ?? catalogModel(id: id) else { return nil }
        return ModelDetail(id: model.id, name: model.name, providerName: model.provider_name,
                           description: model.description ?? "", releaseDate: model.release_date ?? "")
    }

    private func loadModelPreferences() async {
        guard isAuthenticated else { return }
        if usesPreferenceFixture {
            hasLoadedPreferences = true
            return
        }
        isLoadingPreferences = true
        defer { isLoadingPreferences = false }
        do {
            let response: SessionResponse = try await APIClient.shared.request(.get, path: "/v1/auth/session")
            guard let user = response.user else { throw CocoaError(.coderValueNotFound) }
            defaultSimpleModel = user.defaultAiModelSimple ?? ""
            defaultComplexModel = user.defaultAiModelComplex ?? ""
            defaultMostDemandingModel = user.defaultAiModelMostDemanding ?? ""
            followUpSuggestionsEnabled = user.followUpSuggestionsEnabled ?? true
            quickTipsEnabled = user.quickTipsEnabled ?? true
            hasLoadedPreferences = true
        } catch {
            errorMessage = AppStrings.aiPreferencesSaveError
            NativeDiagnostics.error("AI preference load failed", category: "settings.ai")
        }
    }
    private func saveDefaults(rollbackFollowUpsTo: Bool? = nil, rollbackQuickTipsTo: Bool? = nil) {
        guard isAuthenticated, hasLoadedPreferences, !isSaving, !isLoadingPreferences else { return }
        let field = rollbackFollowUpsTo != nil ? "follow_up_suggestions_enabled" : "quick_tips_enabled"
        let value = rollbackFollowUpsTo != nil ? followUpSuggestionsEnabled : quickTipsEnabled
        isSaving = true
        errorMessage = nil
        Task {
            do {
                if usesPreferenceFixture {
                    if ProcessInfo.processInfo.arguments.contains("--ui-test-ai-preferences-save-failure") { throw CocoaError(.fileWriteUnknown) }
                } else {
                    let _: Data = try await APIClient.shared.request(.post, path: "/v1/settings/ai-model-defaults", body: [field: value])
                }
            } catch {
                if let rollbackFollowUpsTo { followUpSuggestionsEnabled = rollbackFollowUpsTo }
                if let rollbackQuickTipsTo { quickTipsEnabled = rollbackQuickTipsTo }
                errorMessage = AppStrings.aiPreferencesSaveError
                NativeDiagnostics.error("AI response preference save failed", category: "settings.ai")
            }
            isSaving = false
        }
    }
}

// Browser-computed geometry from the regular guest AI settings/provider routes
// at a 402px viewport. SettingsItem uses local rem metrics that do not currently
// have generated token counterparts; keep those exact metrics together.
private enum AISettingsMetrics {
    static let bodyWidth: CGFloat = 323
    static let tileSize: CGFloat = 43.7
    static let tilePadding: CGFloat = 9
    static let rowGap: CGFloat = 13
    static let radius: CGFloat = 8.944
}

// Local reusable composition of the canonical SettingsItem ai-row variant.
private struct AISettingsPreferenceRow: View {
    let tier: AIRequestTier
    let value: String
    let action: () -> Void
    var body: some View {
        HStack(spacing: .spacing6) {
            AISettingsCapability(level: tier.capability)
            VStack(alignment: .leading, spacing: 1) {
                Text(tier.title).font(.omSmall.weight(.bold)).foregroundStyle(Color.aiSettingsMuted)
                HStack(spacing: .spacing2) {
                    Icon("ai", size: 22.68).foregroundStyle(LinearGradient.primary)
                    Text(value).font(.omP.weight(.bold)).foregroundStyle(LinearGradient.primary).lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            Button(action: action) {
                Icon("modify", size: 15).foregroundStyle(Color.white)
                    .frame(width: 30, height: 30).background(LinearGradient.primary, in: Circle())
            }.buttonStyle(.plain).accessibilityLabel(AppStrings.aiModify)
                .accessibilityIdentifier("ai-tier-row-" + tier.rawValue + "-modify-button")
        }.padding(.horizontal, .spacing10).frame(minHeight: AISettingsMetrics.tileSize)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("ai-tier-row-" + tier.rawValue)
    }
}
private struct AISettingsCapability: View {
    let level: String
    private var active: Int { ["low": 1, "medium": 2, "high": 3, "max": 4][level] ?? 0 }
    private var color: Color {
        switch level { case "low": return .aiCapabilityLow; case "medium": return .aiCapabilityMedium
        case "high": return .aiCapabilityHigh; case "max": return .aiCapabilityMax; default: return .grey30 }
    }
    var body: some View {
        HStack(alignment: .bottom, spacing: 0.912) {
            ForEach(1...4, id: \.self) { bar in
                UnevenRoundedRectangle(topLeadingRadius: .radius1, topTrailingRadius: .radius1)
                    .fill(bar <= active ? color : Color.grey30)
                    .frame(width: 3.64, height: [5.31, 8.85, 12.744, 17.7][bar - 1])
            }
        }.padding(13).frame(width: AISettingsMetrics.tileSize, height: AISettingsMetrics.tileSize)
            .background(LinearGradient.omGradient(start: .aiIconTileStart, end: .aiIconTileEnd),
                in: RoundedRectangle(cornerRadius: AISettingsMetrics.radius))
            .accessibilityLabel(AppStrings.aiCapability(level)).accessibilityValue(level)
            .accessibilityIdentifier("ai-capability-scale")
    }
}
private struct AISettingsSwitchRow: View {
    let title: String
    let subtitle: String
    let logo: String
    @Binding var value: Bool
    let disabled: Bool
    let identifier: String
    var body: some View {
        HStack(spacing: AISettingsMetrics.rowGap) {
            AISettingsFamilyRow(title: title, subtitle: subtitle, logo: logo, trailingPadding: 0) {
                if !disabled { value.toggle() }
            }.disabled(disabled)
            AISettingsToggle(isOn: $value, disabled: disabled, accessibilityIdentifier: identifier + "-toggle")
                .accessibilityLabel(title).padding(.trailing, .spacing10)
        }.accessibilityElement(children: .contain).accessibilityIdentifier(identifier)
    }
}
private struct AISettingsToggle: View {
    @Binding var isOn: Bool
    var disabled = false
    let accessibilityIdentifier: String
    var body: some View {
        Button { if !disabled { isOn.toggle() } } label: {
            ZStack(alignment: isOn ? .trailing : .leading) {
                Capsule().fill(Color.grey30)
                if isOn { Capsule().fill(LinearGradient.primary) }
                Circle().fill(Color.fontButton).frame(width: 25, height: 25)
                    .shadow(color: .black.opacity(0.2), radius: .spacing2, x: 0, y: .spacing1).padding(2)
            }.frame(width: 49, height: 29)
        }.buttonStyle(.plain).disabled(disabled)
            .accessibilityAddTraits(.isToggle).accessibilityValue(isOn ? "On" : "Off")
            .accessibilityIdentifier(accessibilityIdentifier)
    }
}

private struct AISettingsHeading: View {
    let title: String
    let icon: String
    var body: some View {
        HStack(spacing: .spacing6) {
            Icon(icon, size: .iconSizeLg).foregroundStyle(LinearGradient.primary)
            Text(title).font(.omP.weight(.medium)).foregroundStyle(Color.fontPrimary)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing6)
    }
}

private struct AISettingsFamilyRow: View {
    let title: String
    var subtitle: String?
    let logo: String
    var trailingPadding: CGFloat = .spacing10
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: AISettingsMetrics.rowGap) {
                AISettingsProviderLogo(path: logo)
                VStack(alignment: .leading, spacing: 0) {
                    Text(title).font(Font.omP.weight(.bold)).foregroundStyle(LinearGradient.primary)
                    if let subtitle {
                        Text(subtitle).font(Font.omSmall.weight(.bold)).foregroundStyle(Color.aiSettingsMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.leading, .spacing10)
            .padding(.trailing, trailingPadding)
            .frame(minHeight: AISettingsMetrics.tileSize)
            .contentShape(RoundedRectangle(cornerRadius: AISettingsMetrics.radius))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
    }
}
private struct AISettingsProviderLogo: View {
    let path: String
    var body: some View {
        Group {
            if path.contains("/") || path.hasSuffix(".svg") {
                Image(URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent)
                    .renderingMode(.original).resizable().scaledToFit()
            } else {
                Icon(path, size: AISettingsMetrics.tileSize - AISettingsMetrics.tilePadding * 2)
                    .foregroundStyle(LinearGradient.primary)
            }
        }
            .padding(AISettingsMetrics.tilePadding)
            .frame(width: AISettingsMetrics.tileSize, height: AISettingsMetrics.tileSize)
            .background(LinearGradient.omGradient(start: .aiIconTileStart, end: .aiIconTileEnd))
            .clipShape(RoundedRectangle(cornerRadius: AISettingsMetrics.radius))
            .shadow(color: .black.opacity(0.25), radius: 2.032, x: 1.008, y: 1.008)
    }
}

private struct AISettingsExampleCard: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(spacing: .spacing5) {
            Icon("chat", size: .iconSizeMd)
            Text(title).font(.omP.weight(.bold))
            Text(subtitle).font(.omSmall.weight(.medium))
        }
        .foregroundStyle(Color.white)
        .multilineTextAlignment(.center)
        .padding(.horizontal, .spacing10)
        .padding(.vertical, .spacing8)
        .frame(maxWidth: .infinity, minHeight: .spacing32 * 5)
        .background(LinearGradient.appWeb, in: RoundedRectangle(cornerRadius: .radius8))
        .padding(.horizontal, .spacing10)
        .accessibilityIdentifier("ai-model-example-card")
    }
}

private struct AISettingsDetailRow: View {
    let title: String
    let value: String
    let icon: String
    let identifier: String
    var body: some View {
        HStack(spacing: .spacing6) {
            Icon(icon, size: .iconSizeMd).foregroundStyle(LinearGradient.primary)
                .frame(width: .spacing20 + .spacing2, height: .spacing20 + .spacing2)
                .background(LinearGradient.omGradient(start: .aiIconTileStart, end: .aiIconTileEnd))
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
            VStack(alignment: .leading, spacing: 0) {
                Text(title).font(.omSmall.weight(.bold)).foregroundStyle(Color.aiSettingsMuted)
                Text(value).font(.omP.weight(.medium)).foregroundStyle(Color.fontPrimary)
            }
            Spacer(minLength: 0)
        }.padding(.horizontal, .spacing10).accessibilityIdentifier(identifier)
    }
}
@MainActor private enum AISettingsReleaseDate {
    private static let parser: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
    private static var cache: [String: String] = [:]
    static func string(_ raw: String) -> String {
        let key = Locale.current.identifier + raw
        if let cached = cache[key] { return cached }
        guard let date = parser.date(from: raw) else { return raw }
        let formatted = date.formatted(.dateTime.year().month(.wide))
        cache[key] = formatted
        return formatted
    }
}

private extension AppStrings {
    static var aiMostDemandingRequests: String { localized("settings.ai_ask.ai_ask_settings.most_demanding_requests") }
    static var aiMostDemandingDescription: String { localized("settings.ai_ask.ai_ask_settings.most_demanding_requests_description") }
    static var aiChooseTierProvider: String { localized("settings.ai_ask.ai_ask_settings.choose_tier_provider") }
    static var aiChooseExactModel: String { localized("settings.ai_ask.ai_ask_settings.choose_exact_model") }
    static var aiAutoDescription: String { localized("settings.ai_ask.ai_ask_settings.auto_description") }
    static var aiViewProviderModels: String { localized("settings.ai_ask.ai_ask_settings.view_provider_models") }
    static var aiRecommended: String { localized("settings.ai_ask.ai_ask_settings.recommended") }
    static var aiModify: String { localized("settings.modify") }
    static var aiExamples: String { localized("settings.app_store.skills.examples") }
    static var aiSimpleRequestsDescription: String { localized("settings.ai_ask.ai_ask_settings.simple_requests_description") }
    static var aiComplexRequestsDescription: String { localized("settings.ai_ask.ai_ask_settings.complex_requests_description") }
    static var aiEnableModel: String { localized("settings.ai_ask.ai_ask_model_details.enable_model") }
    static var aiDetails: String { localized("common.details") }
    static var aiCapabilityTitle: String { localized("settings.ai_ask.ai_ask_settings.capability") }
    static var aiModelOrigin: String { localized("settings.ai_ask.ai_ask_model_details.origin") }
    static var aiModelReleaseDate: String { localized("settings.ai_ask.ai_ask_model_details.release_date") }
    static var aiModelInputTypes: String { localized("settings.ai_ask.ai_ask_model_details.input_types") }
    static var aiModelOutputTypes: String { localized("settings.ai_ask.ai_ask_model_details.output_types") }
    static var aiModelTextInput: String { localized("settings.ai_ask.ai_ask_model_details.text_input") }
    static var aiModelTextOutput: String { localized("settings.ai_ask.ai_ask_model_details.text_output") }
    static func aiPrice(_ tokens: Double) -> String {
        "1 " + localized("common.credits") + " " + localized("settings.ai_ask.ai_ask_settings.per") + " " +
        tokens.formatted(.number.grouping(.never)) + " " + localized("settings.ai_ask.ai_ask_settings.tokens")
    }
    static func aiMediaType(_ type: String) -> String {
        switch type {
        case "image": return localized("common.images")
        case "audio": return localized("common.audio")
        case "video": return localized("settings.ai_ask.ai_ask_model_details.input_type_video")
        default: return localized("settings.ai_ask.ai_ask_model_details.input_type_text")
        }
    }
    static func aiServerRegion(_ region: String) -> String {
        region + " " + localized("settings.ai_ask.ai_ask_model_details.servers").lowercased()
    }
    static var aiPricingNote: String { localized("common.pricing") + ": " + localized("settings.ai_ask.ai_ask_settings.pricing_note") }
    static var aiModelsAndAccounts: String { localized("settings.ai_ask.ai_ask_settings.models_and_accounts") }
    static var aiResponseSettings: String { localized("settings.ai_ask.ai_ask_settings.response_settings") }
    static var aiFollowUpSuggestions: String { localized("settings.ai_ask.ai_ask_settings.follow_up_suggestions") }
    static var aiFollowUpDescription: String { localized("settings.ai_ask.ai_ask_settings.follow_up_suggestions_description") }
    static var aiQuickTips: String { localized("settings.ai_ask.ai_ask_settings.quick_tips") }
    static var aiQuickTipsDescription: String { localized("settings.ai_ask.ai_ask_settings.quick_tips_description") }
    static var aiProviderModelsInstruction: String { localized("settings.ai_ask.ai_ask_settings.provider_models_instruction") }
    static var aiPreferencesSaveError: String { localized("settings.ai_ask.ai_ask_settings.default_models_save_error") }
    static func aiCapability(_ level: String) -> String { localized("settings.ai_ask.ai_ask_settings.capability_" + level) }
    static func aiFromProvider(_ provider: String) -> String {
        LocalizationManager.shared.text("enter_message.mention_dropdown.from_provider", replacements: ["provider": provider])
    }
    static func aiProviderHeaderDescription(_ provider: String) -> String {
        LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.provider_header_description", replacements: ["provider": provider])
    }
    static func aiProviderModelsHeading(_ provider: String) -> String {
        LocalizationManager.shared.text("settings.ai.provider_models_heading", replacements: ["provider": provider])
    }
}

// Web AiTierSettings: default selections are exclusive within one request tier.
// Recommendation is the nearest capability rank, with a stable model-ID tie break.
enum AIRequestTier: String, CaseIterable {
    case simple, complex
    case mostDemanding = "most-demanding"
    var capability: String {
        switch self { case .simple: return "low"; case .complex: return "high"; case .mostDemanding: return "max" }
    }
    @MainActor var title: String {
        switch self { case .simple: return AppStrings.simpleRequests; case .complex: return AppStrings.complexRequests; case .mostDemanding: return AppStrings.aiMostDemandingRequests }
    }
    @MainActor var description: String {
        switch self { case .simple: return AppStrings.aiSimpleRequestsDescription; case .complex: return AppStrings.aiComplexRequestsDescription; case .mostDemanding: return AppStrings.aiMostDemandingDescription }
    }
    var preferenceField: String {
        switch self {
        case .simple: return "default_ai_model_simple"
        case .complex: return "default_ai_model_complex"
        case .mostDemanding: return "default_ai_model_most_demanding"
        }
    }
    static func eligibleModels(catalog: NativeModelCatalog?, routing: ModelRoutingCatalog) -> [NativeModelCatalog.Model] {
        (catalog?.models ?? []).filter {
            $0.for_app_skill == "ai.ask" && routing.usable($0.provider_id + "/" + $0.id)
        }
    }
    func recommendedModel(in models: [NativeModelCatalog.Model]) -> NativeModelCatalog.Model? {
        let ranks = ["low": 0, "medium": 1, "high": 2, "max": 3]
        let target = ranks[capability] ?? 0
        return models.sorted {
            let a = abs((ranks[$0.capability_level ?? ""] ?? 0) - target)
            let b = abs((ranks[$1.capability_level ?? ""] ?? 0) - target)
            return a != b ? a < b : $0.id < $1.id
        }.first
    }
}
struct AITierSelectionRequest: Encodable {
    let tier: AIRequestTier
    let selection: String?
    private struct Field: CodingKey {
        let stringValue: String
        var intValue: Int? { nil }
        init(_ value: String) { stringValue = value }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }
    func encode(to encoder: Encoder) throws {
        var fields = encoder.container(keyedBy: Field.self)
        if let selection { try fields.encode(selection, forKey: Field(tier.preferenceField)) }
        else { try fields.encodeNil(forKey: Field(tier.preferenceField)) }
    }
}
