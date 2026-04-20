// Full AI settings — model selection, provider management, and preferences.
// Mirrors the web app's SettingsAI.svelte with model picker, auto-select toggle,
// and provider enable/disable. All strings use AppStrings (i18n).

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsAI.svelte
//          frontend/packages/ui/src/components/settings/AiModelDetailsWrapper.svelte
//          frontend/packages/ui/src/components/settings/AiProviderDetailsWrapper.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsAIFullView: View {
    @State private var autoSelectModel = true
    @State private var defaultSimpleModel = ""
    @State private var defaultComplexModel = ""
    @State private var availableModels: [AIModel] = []
    @State private var providers: [AIProvider] = []
    @State private var isLoading = true
    @State private var searchText = ""

    struct AIModel: Identifiable, Decodable {
        let id: String
        let name: String
        let provider: String
        let providerName: String?
        let pricePerMillionTokens: Double?
        let contextWindow: Int?
        var isEnabled: Bool?
    }

    struct AIProvider: Identifiable, Decodable {
        let id: String
        let name: String
        let region: String?
        var isEnabled: Bool
    }

    var filteredModels: [AIModel] {
        let models = availableModels.filter { $0.isEnabled != false }
        guard !searchText.isEmpty else { return models }
        return models.filter {
            $0.name.localizedCaseInsensitiveContains(searchText) ||
            $0.provider.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        List {
            // Default model selection
            Section(AppStrings.defaultModels) {
                Toggle(AppStrings.autoSelectModel, isOn: $autoSelectModel)
                    .tint(Color.buttonPrimary)
                    .onChange(of: autoSelectModel) { _, _ in saveDefaults() }
                    .accessibleToggle(AppStrings.autoSelectModel, isOn: autoSelectModel)

                if !autoSelectModel {
                    Text(AppStrings.autoSelectDescription)
                        .font(.omXs).foregroundStyle(Color.fontSecondary)

                    Picker(AppStrings.simpleRequests, selection: $defaultSimpleModel) {
                        Text(AppStrings.auto).tag("")
                        ForEach(availableModels.filter { $0.isEnabled != false }) { model in
                            Text("\(model.name)").tag(model.id)
                        }
                    }
                    .onChange(of: defaultSimpleModel) { _, _ in saveDefaults() }

                    Picker(AppStrings.complexRequests, selection: $defaultComplexModel) {
                        Text(AppStrings.auto).tag("")
                        ForEach(availableModels.filter { $0.isEnabled != false }) { model in
                            Text("\(model.name)").tag(model.id)
                        }
                    }
                    .onChange(of: defaultComplexModel) { _, _ in saveDefaults() }
                }
            }

            // Available providers with enable/disable toggles
            if !providers.isEmpty {
                Section(AppStrings.availableProviders) {
                    ForEach($providers) { $provider in
                        HStack {
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(provider.name)
                                    .font(.omSmall).fontWeight(.medium)
                                if let region = provider.region {
                                    Text(region)
                                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                                }
                            }
                            Spacer()
                            Toggle("", isOn: $provider.isEnabled)
                                .labelsHidden()
                                .tint(Color.buttonPrimary)
                                .onChange(of: provider.isEnabled) { _, newValue in
                                    toggleProvider(provider.id, enabled: newValue)
                                }
                                .accessibleToggle(provider.name, isOn: provider.isEnabled)
                        }
                        .accessibilityElement(children: .combine)
                        .accessibleSetting(provider.name, value: provider.isEnabled ? AppStrings.enabled : AppStrings.disabled)
                    }
                }
            }

            // Available models list
            Section(AppStrings.availableModels) {
                if isLoading {
                    ProgressView()
                } else {
                    ForEach(filteredModels) { model in
                        HStack {
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(model.name)
                                    .font(.omSmall).fontWeight(.medium)
                                HStack(spacing: .spacing3) {
                                    Text(model.providerName ?? model.provider)
                                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                                    if let price = model.pricePerMillionTokens {
                                        Text("$\(String(format: "%.2f", price))/M")
                                            .font(.omTiny).foregroundStyle(Color.fontTertiary)
                                    }
                                    if let ctx = model.contextWindow {
                                        Text("\(ctx / 1000)K ctx")
                                            .font(.omTiny).foregroundStyle(Color.fontTertiary)
                                    }
                                }
                            }
                            Spacer()
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(Color.buttonPrimary)
                                .accessibilityHidden(true)
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel({
                            var label = model.name
                            label += ", \(model.providerName ?? model.provider)"
                            if let price = model.pricePerMillionTokens {
                                label += ", $\(String(format: "%.2f", price)) per million tokens"
                            }
                            if let ctx = model.contextWindow {
                                label += ", \(ctx / 1000)K context"
                            }
                            return label
                        }())
                    }
                }
            }
        }
        .searchable(text: $searchText, prompt: AppStrings.searchModels)
        .navigationTitle(AppStrings.settingsAI)
        .task { await loadModels() }
    }

    private func loadModels() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/ai-models"
            )
            if let models = response["models"]?.value as? [[String: Any]] {
                availableModels = models.compactMap { dict in
                    guard let id = dict["id"] as? String,
                          let name = dict["name"] as? String,
                          let provider = dict["provider"] as? String else { return nil }
                    return AIModel(
                        id: id, name: name, provider: provider,
                        providerName: dict["provider_name"] as? String,
                        pricePerMillionTokens: dict["price_per_million_tokens"] as? Double,
                        contextWindow: dict["context_window"] as? Int,
                        isEnabled: dict["is_enabled"] as? Bool
                    )
                }
            }
            if let providerList = response["providers"]?.value as? [[String: Any]] {
                providers = providerList.compactMap { dict in
                    guard let id = dict["id"] as? String,
                          let name = dict["name"] as? String else { return nil }
                    return AIProvider(
                        id: id, name: name,
                        region: dict["region"] as? String,
                        isEnabled: dict["is_enabled"] as? Bool ?? true
                    )
                }
            }
            autoSelectModel = response["auto_select"]?.value as? Bool ?? true
            defaultSimpleModel = response["default_simple"]?.value as? String ?? ""
            defaultComplexModel = response["default_complex"]?.value as? String ?? ""
        } catch {
            print("[Settings] Failed to load AI models: \(error)")
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

    private func toggleProvider(_ providerId: String, enabled: Bool) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/ai-providers/\(providerId)/toggle",
                body: ["enabled": enabled]
            ) as Data
        }
    }
}
