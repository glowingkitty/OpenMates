// Full AI settings — model selection, provider management, and preferences.
// Mirrors the web app's SettingsAI.svelte with model picker and provider toggles.

import SwiftUI

struct SettingsAIFullView: View {
    @State private var defaultSimpleModel = ""
    @State private var defaultComplexModel = ""
    @State private var availableModels: [AIModel] = []
    @State private var disabledProviders: [String] = []
    @State private var isLoading = true
    @State private var searchText = ""

    struct AIModel: Identifiable, Decodable {
        let id: String
        let name: String
        let provider: String
        let providerName: String?
        let pricePerMillionTokens: Double?
        let contextWindow: Int?
        let isEnabled: Bool?
    }

    var filteredModels: [AIModel] {
        guard !searchText.isEmpty else { return availableModels }
        return availableModels.filter {
            $0.name.localizedCaseInsensitiveContains(searchText) ||
            $0.provider.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        List {
            Section("Default Models") {
                Picker("Simple Requests", selection: $defaultSimpleModel) {
                    Text("Auto").tag("")
                    ForEach(availableModels) { model in
                        Text("\(model.name) (\(model.provider))").tag(model.id)
                    }
                }
                .onChange(of: defaultSimpleModel) { _, _ in saveDefaults() }

                Picker("Complex Requests", selection: $defaultComplexModel) {
                    Text("Auto").tag("")
                    ForEach(availableModels) { model in
                        Text("\(model.name) (\(model.provider))").tag(model.id)
                    }
                }
                .onChange(of: defaultComplexModel) { _, _ in saveDefaults() }
            }

            Section("Available Models") {
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
                                .opacity(model.isEnabled != false ? 1 : 0.3)
                        }
                    }
                }
            }
        }
        .searchable(text: $searchText, prompt: "Search models")
        .navigationTitle("AI Model")
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
                    "default_simple": defaultSimpleModel,
                    "default_complex": defaultComplexModel
                ]
            ) as Data
        }
    }
}
