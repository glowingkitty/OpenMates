// Share debug logs toggle — opt in/out of sharing anonymized diagnostics.
// Mirrors the web app's SettingsShareDebugLogs.svelte.

import SwiftUI

struct SettingsShareDebugLogsView: View {
    @State private var isEnabled = false
    @State private var isLoading = true

    var body: some View {
        List {
            Section {
                Toggle("Share Debug Logs", isOn: $isEnabled)
                    .tint(Color.buttonPrimary)
                    .onChange(of: isEnabled) { _, newValue in
                        savePreference(newValue)
                    }
            }

            Section {
                Text(LocalizationManager.shared.text("settings.debug_logs.description"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }

            Section("What is shared") {
                Label("Error reports", systemImage: "exclamationmark.triangle")
                    .font(.omSmall)
                Label("Performance metrics", systemImage: "speedometer")
                    .font(.omSmall)
                Label("Feature usage statistics", systemImage: "chart.bar")
                    .font(.omSmall)
            }

            Section("What is NOT shared") {
                Label("Chat messages", systemImage: "xmark.circle")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                Label("Personal information", systemImage: "xmark.circle")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                Label("Encryption keys", systemImage: "xmark.circle")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle("Share Debug Logs")
        .task { await loadPreference() }
    }

    private func loadPreference() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/privacy/debug-logs"
            )
            isEnabled = response["enabled"]?.value as? Bool ?? false
        } catch {
            print("[Settings] Debug logs preference error: \(error)")
        }
        isLoading = false
    }

    private func savePreference(_ enabled: Bool) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/privacy/debug-logs",
                body: ["enabled": enabled]
            ) as Data
        }
    }
}
