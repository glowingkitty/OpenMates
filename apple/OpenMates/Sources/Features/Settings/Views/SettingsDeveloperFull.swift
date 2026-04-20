// Developer settings — API keys and webhook management.
// Mirrors SettingsDevelopers.svelte.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsDevelopers.svelte
//          frontend/packages/ui/src/components/settings/developers/SettingsApiKeys.svelte
//          frontend/packages/ui/src/components/settings/developers/SettingsWebhooks.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsDeveloperView: View {
    var body: some View {
        List {
            NavigationLink {
                SettingsAPIKeysView()
            } label: {
                Label("API Keys", systemImage: "key")
            }

            NavigationLink {
                SettingsWebhooksView()
            } label: {
                Label("Webhooks", systemImage: "arrow.triangle.branch")
            }
        }
        .navigationTitle("Developers")
    }
}

struct SettingsAPIKeysView: View {
    @State private var apiKeys: [APIKeyItem] = []
    @State private var isLoading = true
    @State private var newKeyName = ""
    @State private var showNewKey = false
    @State private var generatedKey: String?

    struct APIKeyItem: Identifiable, Decodable {
        let id: String
        let name: String?
        let prefix: String?
        let createdAt: String?
        let lastUsedAt: String?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else {
                Section("Your API Keys") {
                    ForEach(apiKeys) { key in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(key.name ?? "Unnamed Key")
                                .font(.omSmall).fontWeight(.medium)
                            if let prefix = key.prefix {
                                Text("\(prefix)...")
                                    .font(.system(.caption, design: .monospaced))
                                    .foregroundStyle(Color.fontTertiary)
                            }
                            if let lastUsed = key.lastUsedAt {
                                Text("\(LocalizationManager.shared.text("settings.developer.last_used")): \(lastUsed)")
                                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityHint(LocalizationManager.shared.text("settings.swipe_left_to_revoke"))
                        .swipeActions {
                            Button(role: .destructive) { revokeKey(key.id) } label: {
                                Label("Revoke", systemImage: "trash")
                            }
                        }
                    }
                }

                Section("Create New Key") {
                    TextField("Key name", text: $newKeyName)
                        .accessibleInput("Key name", hint: LocalizationManager.shared.text("settings.developer.key_name_hint"))
                    Button("Generate API Key") { createKey() }
                        .disabled(newKeyName.isEmpty)
                        .accessibleButton("Generate API Key")
                }

                if let generatedKey {
                    Section("New Key (copy now — shown only once)") {
                        HStack {
                            Text(generatedKey)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                                .accessibilityLabel(LocalizationManager.shared.text("settings.developer.new_api_key"))
                                .accessibilityHint(LocalizationManager.shared.text("settings.developer.key_shown_once_hint"))
                            Button {
                                #if os(iOS)
                                UIPasteboard.general.string = generatedKey
                                #endif
                                ToastManager.shared.show("Copied!", type: .success)
                                AccessibilityAnnouncement.announce(AppStrings.copied)
                            } label: {
                                Image(systemName: "doc.on.doc")
                            }
                            .accessibleButton(AppStrings.copy, hint: LocalizationManager.shared.text("settings.developer.copy_key_hint"))
                        }
                    }
                }
            }
        }
        .navigationTitle("API Keys")
        .task { await loadKeys() }
    }

    private func loadKeys() async {
        do {
            apiKeys = try await APIClient.shared.request(.get, path: "/v1/settings/api-keys")
        } catch {
            print("[Settings] API keys error: \(error)")
        }
        isLoading = false
    }

    private func createKey() {
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/settings/api-keys",
                    body: ["name": newKeyName]
                )
                generatedKey = response["key"]?.value as? String
                newKeyName = ""
                await loadKeys()
            } catch {
                ToastManager.shared.show("Failed to create key", type: .error)
            }
        }
    }

    private func revokeKey(_ id: String) {
        Task {
            try? await APIClient.shared.request(.delete, path: "/v1/settings/api-keys/\(id)") as Data
            apiKeys.removeAll { $0.id == id }
        }
    }
}

struct SettingsWebhooksView: View {
    var body: some View {
        List {
            Section {
                Text(LocalizationManager.shared.text("settings.developer.webhook_description"))
                    .foregroundStyle(Color.fontSecondary)
                Button("Open Webhook Settings") {
                    Task {
                        let url = await APIClient.shared.webAppURL.appendingPathComponent("settings/developers/webhooks")
                        #if os(iOS)
                        await UIApplication.shared.open(url)
                        #elseif os(macOS)
                        NSWorkspace.shared.open(url)
                        #endif
                    }
                }
                .accessibleButton("Open Webhook Settings", hint: LocalizationManager.shared.text("settings.developer.opens_in_browser"))
            }
        }
        .navigationTitle("Webhooks")
    }
}
