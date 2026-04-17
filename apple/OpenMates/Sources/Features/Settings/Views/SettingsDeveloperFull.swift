// Developer settings — API keys and webhook management.
// Mirrors SettingsDevelopers.svelte.

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
                                Text("Last used: \(lastUsed)")
                                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        .swipeActions {
                            Button(role: .destructive) { revokeKey(key.id) } label: {
                                Label("Revoke", systemImage: "trash")
                            }
                        }
                    }
                }

                Section("Create New Key") {
                    TextField("Key name", text: $newKeyName)
                    Button("Generate API Key") { createKey() }
                        .disabled(newKeyName.isEmpty)
                }

                if let generatedKey {
                    Section("New Key (copy now — shown only once)") {
                        HStack {
                            Text(generatedKey)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                            Button {
                                #if os(iOS)
                                UIPasteboard.general.string = generatedKey
                                #endif
                                ToastManager.shared.show("Copied!", type: .success)
                            } label: {
                                Image(systemName: "doc.on.doc")
                            }
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
                Text("Webhook configuration is managed on the web app for full control.")
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
            }
        }
        .navigationTitle("Webhooks")
    }
}
