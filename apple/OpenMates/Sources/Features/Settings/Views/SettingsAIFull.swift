// Full AI settings — native reproduction of SettingsAI.svelte.
// Uses OpenMates settings primitives and provider metadata parity, never default iOS List/Form controls.

import SwiftUI

struct SettingsAIFullView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var autoSelectModel = true
    @State private var defaultSimpleModel = ""
    @State private var defaultComplexModel = ""
    @State private var serverModels: [AIModel] = []
    @State private var serverProviders: [AIProvider] = []
    @State private var isLoading = true
    @State private var searchText = ""
    @State private var sortBy: AIModelSort = .performance

    struct AIModel: Identifiable, Decodable {
        let id: String
        let name: String
        let provider: String
        let providerName: String
        let description: String
        let logo: String
        let releaseDate: String
        let inputTokensPerCredit: Int
        let outputTokensPerCredit: Int
        let servers: [AIProvider]
        var isEnabled: Bool?

        var tierScore: Int {
            let lowerName = name.lowercased()
            if lowerName.contains("opus") || lowerName.contains("gpt-5.5") || lowerName.contains("gemini 3.1 pro") {
                return 3
            }
            if lowerName.contains("small") || lowerName.contains("haiku") || lowerName.contains("flash") || lowerName.contains("ministral") {
                return 1
            }
            return 2
        }

        var priceScore: Int {
            inputTokensPerCredit + outputTokensPerCredit
        }
    }

    struct AIProvider: Identifiable, Decodable, Hashable {
        let id: String
        let name: String
        let region: String
        let logo: String
        var isEnabled: Bool
    }

    struct AIMemoryCategory: Identifiable {
        let id: String
        let titleKey: String
        let descriptionKey: String
        let icon: String
    }

    enum AIModelSort: String, CaseIterable {
        case performance
        case price
        case newest

        var next: AIModelSort {
            switch self {
            case .performance: return .price
            case .price: return .newest
            case .newest: return .performance
            }
        }
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.settingsAI, showsHeader: false) {
            OMSettingsSection(LocalizationManager.shared.text("common.pricing"), icon: "coins") {
                VStack(alignment: .leading, spacing: .spacing5) {
                    Text(LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.pricing_starting_at"))
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary)

                    aiPricingRow(
                        icon: "download",
                        label: LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.input_text"),
                        tokens: cheapestInputTokens
                    )
                    aiPricingRow(
                        icon: "coins",
                        label: LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.output_text"),
                        tokens: cheapestOutputTokens
                    )

                    Text(LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.pricing_note"))
                        .font(.omSmall)
                        .italic()
                        .foregroundStyle(Color.fontTertiary)
                        .padding(.top, .spacing4)
                }
                .padding(.leading, 10)
                .padding(.vertical, .spacing4)
            }

            if isAuthenticated {
                OMSettingsSection(AppStrings.defaultModels, icon: "settings") {
                    OMSettingsToggleRow(
                        title: AppStrings.autoSelectModel,
                        subtitle: AppStrings.autoSelectDescription,
                        icon: "ai",
                        isOn: $autoSelectModel
                    )
                    .onChange(of: autoSelectModel) { _, _ in saveDefaults() }
                    .accessibleToggle(AppStrings.autoSelectModel, isOn: autoSelectModel)

                    if !autoSelectModel {
                        OMSettingsPickerRow(
                            title: AppStrings.simpleRequests,
                            icon: "ai",
                            options: simpleModelOptions,
                            selection: $defaultSimpleModel
                        )
                        .onChange(of: defaultSimpleModel) { _, _ in saveDefaults() }

                        OMSettingsPickerRow(
                            title: AppStrings.complexRequests,
                            icon: "ai",
                            options: complexModelOptions,
                            selection: $defaultComplexModel
                        )
                        .onChange(of: defaultComplexModel) { _, _ in saveDefaults() }
                    }
                }
            }

            if !memoryCategories.isEmpty {
                OMSettingsSection(LocalizationManager.shared.text("settings.app_store.settings_memories.title"), icon: "settings") {
                    Text(LocalizationManager.shared.text("settings.app_store.settings_memories.section_description"))
                        .font(.omSmall.weight(.medium))
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.leading, 10)
                        .padding(.bottom, .spacing2)

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: .spacing6) {
                            ForEach(memoryCategories) { category in
                                AIMemoryAppStoreCard(category: category)
                            }
                        }
                        .padding(.vertical, .spacing2)
                    }
                }
            }

            OMSettingsSection(AppStrings.availableModels, icon: "ai") {
                Text(LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.models_description"))
                    .font(.omSmall.weight(.medium))
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.leading, 10)
                    .padding(.top, .spacing2)

                AIModelSearchSortBar(searchText: $searchText, sortBy: $sortBy)
                    .padding(.leading, 10)
                    .padding(.vertical, .spacing4)

                if isLoading && serverModels.isEmpty {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.spacing6)
                } else if filteredModels.isEmpty {
                    Text(LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.no_models_found"))
                        .font(.omSmall.weight(.medium))
                        .foregroundStyle(Color.fontTertiary)
                        .frame(maxWidth: .infinity)
                        .padding(.spacing8)
                } else {
                    VStack(spacing: 0) {
                        ForEach(filteredModels) { model in
                            modelRow(model)
                        }
                    }
                    .padding(.leading, .spacing5)
                }
            }

            if !displayProviders.isEmpty {
                OMSettingsSection(AppStrings.availableProviders, icon: "server") {
                    Text(LocalizationManager.shared.text("settings.ai.available_providers_description"))
                        .font(.omSmall.weight(.medium))
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.leading, 10)
                        .padding(.top, .spacing2)

                    VStack(spacing: 0) {
                        ForEach(displayProviders) { provider in
                            providerRow(provider)
                        }
                    }
                    .padding(.leading, .spacing5)
                }
            }
        }
        .task { await loadModelPreferences() }
    }

    private var isAuthenticated: Bool {
        authManager.currentUser != nil
    }

    private var displayModels: [AIModel] {
        let serverById = Dictionary(uniqueKeysWithValues: serverModels.map { ($0.id, $0) })
        return Self.catalogModels.map { catalogModel in
            var model = catalogModel
            if let serverModel = serverById[catalogModel.id] {
                model.isEnabled = serverModel.isEnabled
            }
            return model
        }
    }

    private var filteredModels: [AIModel] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        var models = displayModels.filter { $0.isEnabled != false }
        if !query.isEmpty {
            models = models.filter {
                $0.name.lowercased().contains(query) ||
                    $0.providerName.lowercased().contains(query) ||
                    $0.description.lowercased().contains(query)
            }
        }

        switch sortBy {
        case .price:
            return models.sorted {
                if $0.priceScore != $1.priceScore { return $0.priceScore > $1.priceScore }
                return $0.name < $1.name
            }
        case .performance:
            return models.sorted {
                if $0.tierScore != $1.tierScore { return $0.tierScore > $1.tierScore }
                return $0.name < $1.name
            }
        case .newest:
            return models.sorted {
                if $0.releaseDate != $1.releaseDate { return $0.releaseDate > $1.releaseDate }
                return $0.name < $1.name
            }
        }
    }

    private var displayProviders: [AIProvider] {
        let enabledById = Dictionary(uniqueKeysWithValues: serverProviders.map { ($0.id, $0.isEnabled) })
        var seen = Set<String>()
        var providers: [AIProvider] = []
        for model in Self.catalogModels {
            for provider in model.servers where !seen.contains(provider.id) {
                seen.insert(provider.id)
                var merged = provider
                if let isEnabled = enabledById[provider.id] {
                    merged.isEnabled = isEnabled
                }
                providers.append(merged)
            }
        }
        return providers.sorted {
            if $0.region == "EU", $1.region != "EU" { return true }
            if $0.region != "EU", $1.region == "EU" { return false }
            return $0.name < $1.name
        }
    }

    private var cheapestInputTokens: Int {
        displayModels.map(\.inputTokensPerCredit).max() ?? 3_300
    }

    private var cheapestOutputTokens: Int {
        displayModels.map(\.outputTokensPerCredit).max() ?? 2_222
    }

    private var simpleModelOptions: [OMDropdownOption] {
        [OMDropdownOption("", label: LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.model_auto"))] +
            displayModels
                .sorted {
                    if $0.tierScore != $1.tierScore { return $0.tierScore < $1.tierScore }
                    return $0.name < $1.name
                }
                .map { OMDropdownOption("\($0.provider)/\($0.id)", label: $0.name) }
    }

    private var complexModelOptions: [OMDropdownOption] {
        [OMDropdownOption("", label: LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.model_auto"))] +
            displayModels
                .sorted {
                    if $0.tierScore != $1.tierScore { return $0.tierScore > $1.tierScore }
                    return $0.name < $1.name
                }
                .map { OMDropdownOption("\($0.provider)/\($0.id)", label: $0.name) }
    }

    private var memoryCategories: [AIMemoryCategory] {
        [
            AIMemoryCategory(
                id: "communication_style",
                titleKey: "app_settings_memories.ai.communication_style",
                descriptionKey: "app_settings_memories.ai.communication_style.description",
                icon: "chat"
            ),
            AIMemoryCategory(
                id: "learning_preferences",
                titleKey: "app_settings_memories.ai.learning_preferences",
                descriptionKey: "app_settings_memories.ai.learning_preferences.description",
                icon: "library"
            ),
            AIMemoryCategory(
                id: "interaction_preferences",
                titleKey: "app_settings_memories.ai.interaction_preferences",
                descriptionKey: "app_settings_memories.ai.interaction_preferences.description",
                icon: "settings_memories"
            )
        ]
    }

    private func aiPricingRow(icon: String, label: String, tokens: Int) -> some View {
        HStack(spacing: .spacing5) {
            Icon(icon, size: 22)
                .foregroundStyle(LinearGradient.primary)
                .frame(width: 44, height: 44)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))

            Text(label)
                .font(.omSmall.weight(.bold))
                .foregroundStyle(Color.fontTertiary)
                .frame(minWidth: 80, alignment: .leading)

            HStack(spacing: .spacing2) {
                Text("1")
                Icon("coins", size: 16)
                    .foregroundStyle(Color.fontButton)
                    .frame(width: 18, height: 18)
                    .background(LinearGradient.primary)
                    .clipShape(RoundedRectangle(cornerRadius: .radius2))
                Text("\(LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.per")) \(tokens) \(LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.tokens"))")
            }
            .font(.omP.weight(.medium))
            .foregroundStyle(Color.fontPrimary)
        }
    }

    private func modelRow(_ model: AIModel) -> some View {
        Button {
            // Model detail routes are still web-only; keep row behavior visual without invoking native navigation.
        } label: {
            HStack(spacing: .spacing6) {
                ProviderLogo(name: model.logo)

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(model.name)
                        .font(.omP.weight(.medium))
                        .foregroundStyle(LinearGradient.primary)
                        .lineLimit(1)

                    Text(LocalizationManager.shared.text("enter_message.mention_dropdown.from_provider").replacingOccurrences(of: "{provider}", with: simplifyProviderName(model.providerName)))
                        .font(.omSmall.weight(.medium))
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                }

                Spacer()

                if isAuthenticated {
                    OMToggle(
                        isOn: Binding(
                            get: { model.isEnabled != false },
                            set: { _ in toggleModel(model.id) }
                        )
                    )
                    .accessibilityHidden(true)
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing5)
            .frame(minHeight: 58)
            .contentShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibleSetting(model.name, value: simplifyProviderName(model.providerName))
    }

    private func providerRow(_ provider: AIProvider) -> some View {
        Button {
            // Provider detail routes are still web-only; preserve clickable row styling.
        } label: {
            HStack(spacing: .spacing6) {
                ProviderLogo(name: provider.logo)

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(provider.name)
                        .font(.omP.weight(.medium))
                        .foregroundStyle(LinearGradient.primary)
                        .lineLimit(1)

                    Text(regionLabel(provider.region))
                        .font(.omSmall.weight(.medium))
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                }

                Spacer()

                if isAuthenticated {
                    OMToggle(
                        isOn: Binding(
                            get: { displayProviders.first(where: { $0.id == provider.id })?.isEnabled ?? provider.isEnabled },
                            set: { toggleProvider(provider.id, enabled: $0) }
                        )
                    )
                    .accessibilityHidden(true)
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing5)
            .frame(minHeight: 58)
            .contentShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibleSetting(provider.name, value: regionLabel(provider.region))
    }

    private func simplifyProviderName(_ name: String) -> String {
        name
            .replacingOccurrences(of: " API", with: "")
            .replacingOccurrences(of: " AI", with: "")
            .replacingOccurrences(of: " (MaaS)", with: "")
    }

    private func regionLabel(_ region: String) -> String {
        switch region {
        case "EU": return "EU Server"
        case "US": return "US Server"
        case "global": return "Global"
        default: return region
        }
    }

    private func loadModelPreferences() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/ai-models"
            )
            if let models = response["models"]?.value as? [[String: Any]] {
                serverModels = models.compactMap { dict in
                    guard let id = dict["id"] as? String else { return nil }
                    var model = Self.catalogModels.first { $0.id == id }
                    model?.isEnabled = dict["is_enabled"] as? Bool
                    return model
                }
            }
            if let providerList = response["providers"]?.value as? [[String: Any]] {
                serverProviders = providerList.compactMap { dict in
                    guard let id = dict["id"] as? String else { return nil }
                    var provider = displayProviders.first { $0.id == id }
                    provider?.isEnabled = dict["is_enabled"] as? Bool ?? true
                    return provider
                }
            }
            autoSelectModel = response["auto_select"]?.value as? Bool ?? true
            defaultSimpleModel = response["default_simple"]?.value as? String ?? ""
            defaultComplexModel = response["default_complex"]?.value as? String ?? ""
        } catch {
            print("[Settings] Failed to load AI model preferences: \(error)")
        }
        isLoading = false
    }

    private func saveDefaults() {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/ai-model-defaults",
                body: [
                    "auto_select": autoSelectModel,
                    "default_simple": defaultSimpleModel,
                    "default_complex": defaultComplexModel
                ]
            ) as Data
        }
    }

    private func toggleModel(_ modelId: String) {
        guard let index = serverModels.firstIndex(where: { $0.id == modelId }) else {
            if var model = Self.catalogModels.first(where: { $0.id == modelId }) {
                model.isEnabled = false
                serverModels.append(model)
            }
            return
        }
        serverModels[index].isEnabled = !(serverModels[index].isEnabled ?? true)
    }

    private func toggleProvider(_ providerId: String, enabled: Bool) {
        if let index = serverProviders.firstIndex(where: { $0.id == providerId }) {
            serverProviders[index].isEnabled = enabled
        } else if var provider = displayProviders.first(where: { $0.id == providerId }) {
            provider.isEnabled = enabled
            serverProviders.append(provider)
        }
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/ai-providers/\(providerId)/toggle",
                body: ["enabled": enabled]
            ) as Data
        }
    }
}

private struct AIModelSearchSortBar: View {
    @Binding var searchText: String
    @Binding var sortBy: SettingsAIFullView.AIModelSort

    var body: some View {
        HStack(spacing: .spacing4) {
            HStack(spacing: .spacing3) {
                Icon("search", size: 18)
                    .foregroundStyle(Color.grey50)

                TextField(AppStrings.searchModels, text: $searchText)
                    .font(.omP.weight(.medium))
                    .foregroundStyle(Color.fontPrimary)
                    .submitLabel(.search)

                if !searchText.isEmpty {
                    Button {
                        searchText = ""
                    } label: {
                        Icon("delete", size: 16)
                            .foregroundStyle(Color.grey50)
                    }
                    .buttonStyle(.plain)
                    .accessibleButton(LocalizationManager.shared.text("common.clear"))
                }
            }
            .padding(.horizontal, .spacing6)
            .frame(height: 44)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            .shadow(color: .black.opacity(0.10), radius: 4, x: 0, y: 4)

            Button {
                sortBy = sortBy.next
            } label: {
                Icon("sort", size: 22)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 44, height: 44)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                    .shadow(color: .black.opacity(0.10), radius: 4, x: 0, y: 4)
            }
            .buttonStyle(.plain)
            .accessibleButton(sortLabel)
        }
    }

    private var sortLabel: String {
        switch sortBy {
        case .performance:
            return LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.sort_by_performance")
        case .price:
            return LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.sort_by_price")
        case .newest:
            return LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.sort_by_new")
        }
    }
}

private struct ProviderLogo: View {
    let name: String

    var body: some View {
        Image(name)
            .renderingMode(.original)
            .resizable()
            .scaledToFit()
            .frame(width: 32, height: 32)
            .frame(width: 40, height: 40)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }
}

private struct AIMemoryAppStoreCard: View {
    let category: SettingsAIFullView.AIMemoryCategory

    var body: some View {
        Button {
            // Category detail route parity can hook into the settings router once native nested memory pages are wired.
        } label: {
            VStack(alignment: .leading, spacing: .spacing5) {
                Icon(category.icon, size: 26)
                    .foregroundStyle(Color.fontButton)
                    .frame(width: 44, height: 44)
                    .background(LinearGradient(colors: [Color(hex: 0xD80ABF), Color(hex: 0xFF3361)], startPoint: .topLeading, endPoint: .bottomTrailing))
                    .overlay(
                        RoundedRectangle(cornerRadius: .radius4)
                            .stroke(Color.fontButton.opacity(0.9), lineWidth: 2)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))

                Text(LocalizationManager.shared.text(category.titleKey))
                    .font(.omH4.weight(.bold))
                    .foregroundStyle(Color.fontButton)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)

                Text(LocalizationManager.shared.text(category.descriptionKey))
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.fontButton)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
            }
            .padding(.spacing8)
            .frame(width: 250, height: 150, alignment: .topLeading)
            .background(LinearGradient(colors: [Color(hex: 0xC9653D), Color(hex: 0xE58A63)], startPoint: .topLeading, endPoint: .bottomTrailing))
            .clipShape(RoundedRectangle(cornerRadius: .radius6))
        }
        .buttonStyle(.plain)
        .accessibleButton(LocalizationManager.shared.text(category.titleKey))
    }
}

private extension SettingsAIFullView {
    static let providerAWS = AIProvider(id: "aws_bedrock", name: "AWS Bedrock", region: "EU", logo: "server", isEnabled: true)
    static let providerAnthropic = AIProvider(id: "anthropic", name: "Anthropic", region: "US", logo: "anthropic", isEnabled: true)
    static let providerCerebras = AIProvider(id: "cerebras", name: "Cerebras", region: "US", logo: "server", isEnabled: true)
    static let providerGoogle = AIProvider(id: "google", name: "Google Vertex AI", region: "global", logo: "google", isEnabled: true)
    static let providerGoogleAIStudio = AIProvider(id: "google_ai_studio", name: "Google AI Studio", region: "US", logo: "google", isEnabled: true)
    static let providerGoogleMaaS = AIProvider(id: "google_maas", name: "Google Vertex AI (MaaS)", region: "EU", logo: "google", isEnabled: true)
    static let providerMistral = AIProvider(id: "mistral", name: "Mistral", region: "EU", logo: "mistral", isEnabled: true)
    static let providerOpenAI = AIProvider(id: "openai", name: "OpenAI", region: "US", logo: "openai", isEnabled: true)
    static let providerOpenRouter = AIProvider(id: "openrouter", name: "OpenRouter", region: "US", logo: "server", isEnabled: true)
    static let providerTogether = AIProvider(id: "together", name: "Together AI", region: "US", logo: "server", isEnabled: true)

    static let catalogModels: [AIModel] = [
        AIModel(id: "qwen3-235b-a22b-2507", name: "Qwen 3 256b", provider: "alibaba", providerName: "Alibaba", description: "Alibaba AI Ask model", logo: "alibaba", releaseDate: "2025-07-01", inputTokensPerCredit: 550, outputTokensPerCredit: 300, servers: [providerCerebras, providerAWS, providerOpenRouter], isEnabled: true),
        AIModel(id: "claude-haiku-4-5-20251001", name: "Claude Haiku 4.5", provider: "anthropic", providerName: "Anthropic", description: "Anthropic AI Ask model", logo: "anthropic", releaseDate: "2025-10-15", inputTokensPerCredit: 350, outputTokensPerCredit: 70, servers: [providerAWS, providerAnthropic], isEnabled: true),
        AIModel(id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6", provider: "anthropic", providerName: "Anthropic", description: "Anthropic AI Ask model", logo: "anthropic", releaseDate: "2026-02-18", inputTokensPerCredit: 110, outputTokensPerCredit: 20, servers: [providerAnthropic, providerAWS], isEnabled: true),
        AIModel(id: "claude-opus-4-6", name: "Claude Opus 4.6", provider: "anthropic", providerName: "Anthropic", description: "Anthropic AI Ask model", logo: "anthropic", releaseDate: "2026-02-06", inputTokensPerCredit: 70, outputTokensPerCredit: 15, servers: [providerAnthropic, providerAWS], isEnabled: true),
        AIModel(id: "claude-opus-4-7", name: "Claude Opus 4.7", provider: "anthropic", providerName: "Anthropic", description: "Anthropic AI Ask model", logo: "anthropic", releaseDate: "2026-04-16", inputTokensPerCredit: 70, outputTokensPerCredit: 15, servers: [providerAnthropic, providerAWS], isEnabled: true),
        AIModel(id: "deepseek-v3.2", name: "DeepSeek V3.2", provider: "deepseek", providerName: "DeepSeek", description: "DeepSeek AI Ask model", logo: "deepseek", releaseDate: "2025-12-01", inputTokensPerCredit: 600, outputTokensPerCredit: 200, servers: [providerGoogleMaaS, providerOpenRouter], isEnabled: true),
        AIModel(id: "gemini-3-flash-preview", name: "Gemini 3 Flash", provider: "google", providerName: "Google", description: "Google AI Ask model", logo: "google", releaseDate: "2025-12-17", inputTokensPerCredit: 650, outputTokensPerCredit: 110, servers: [providerGoogleAIStudio, providerGoogle], isEnabled: true),
        AIModel(id: "gemini-3.1-pro-preview", name: "Gemini 3.1 Pro", provider: "google", providerName: "Google", description: "Google AI Ask model", logo: "google", releaseDate: "2026-02-19", inputTokensPerCredit: 170, outputTokensPerCredit: 30, servers: [providerGoogleAIStudio, providerGoogle], isEnabled: true),
        AIModel(id: "mistral-small-2506", name: "Mistral Small 3.2", provider: "mistral", providerName: "Mistral AI", description: "Mistral AI Ask model", logo: "mistral", releaseDate: "2025-06-01", inputTokensPerCredit: 3300, outputTokensPerCredit: 1100, servers: [providerMistral, providerOpenRouter], isEnabled: true),
        AIModel(id: "mistral-small-latest", name: "Mistral Small 4", provider: "mistral", providerName: "Mistral AI", description: "Mistral AI Ask model", logo: "mistral", releaseDate: "2025-06-01", inputTokensPerCredit: 1650, outputTokensPerCredit: 550, servers: [providerMistral, providerOpenRouter], isEnabled: true),
        AIModel(id: "mistral-medium-latest", name: "Mistral Medium", provider: "mistral", providerName: "Mistral AI", description: "Mistral AI Ask model", logo: "mistral", releaseDate: "2025-05-01", inputTokensPerCredit: 850, outputTokensPerCredit: 170, servers: [providerMistral, providerOpenRouter], isEnabled: true),
        AIModel(id: "ministral-8b-2512", name: "Ministral 3 8B", provider: "mistral", providerName: "Mistral AI", description: "Mistral AI Ask model", logo: "mistral", releaseDate: "2025-12-01", inputTokensPerCredit: 2222, outputTokensPerCredit: 2222, servers: [providerMistral, providerOpenRouter], isEnabled: true),
        AIModel(id: "devstral-2512", name: "Devstral 2", provider: "mistral", providerName: "Mistral AI", description: "Mistral AI Ask model", logo: "mistral", releaseDate: "2025-12-01", inputTokensPerCredit: 850, outputTokensPerCredit: 170, servers: [providerAWS, providerMistral, providerOpenRouter], isEnabled: true),
        AIModel(id: "kimi-k2.5", name: "Kimi K2.5", provider: "moonshot", providerName: "Moonshot AI", description: "Moonshot AI Ask model", logo: "moonshot", releaseDate: "2026-01-27", inputTokensPerCredit: 650, outputTokensPerCredit: 120, servers: [providerTogether, providerOpenRouter], isEnabled: true),
        AIModel(id: "kimi-k2.6", name: "Kimi K2.6", provider: "moonshot", providerName: "Moonshot AI", description: "Moonshot AI Ask model", logo: "moonshot", releaseDate: "2026-04-28", inputTokensPerCredit: 275, outputTokensPerCredit: 75, servers: [providerTogether, providerOpenRouter], isEnabled: true),
        AIModel(id: "gpt-5.5", name: "GPT-5.5", provider: "openai", providerName: "OpenAI", description: "OpenAI AI Ask model", logo: "openai", releaseDate: "2026-04-15", inputTokensPerCredit: 65, outputTokensPerCredit: 10, servers: [providerOpenAI], isEnabled: true),
        AIModel(id: "gpt-5.4", name: "GPT-5.4", provider: "openai", providerName: "OpenAI", description: "OpenAI AI Ask model", logo: "openai", releaseDate: "2026-03-05", inputTokensPerCredit: 130, outputTokensPerCredit: 20, servers: [providerOpenAI], isEnabled: true),
        AIModel(id: "gpt-oss-120b", name: "GPT-OSS-120b", provider: "openai", providerName: "OpenAI", description: "OpenAI AI Ask model", logo: "openai", releaseDate: "2025-08-01", inputTokensPerCredit: 1300, outputTokensPerCredit: 500, servers: [providerAWS, providerOpenRouter], isEnabled: true),
        AIModel(id: "zai-glm-4.7", name: "GLM 4.7", provider: "zai", providerName: "Z.ai", description: "Z.ai AI Ask model", logo: "zai", releaseDate: "2025-12-22", inputTokensPerCredit: 150, outputTokensPerCredit: 120, servers: [providerCerebras, providerAWS, providerOpenRouter], isEnabled: true)
    ]
}
