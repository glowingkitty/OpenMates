// Native Account Import V1 deferral screen.
// Apple opens the verified web import flow until native parsing implements the
// same scan, compression, billing, encryption, and persistence contract.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsImportAccount.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ChatImportView: View {
    static let nativeImportEnabled = false

    @Environment(\.openURL) private var openURL

    var body: some View {
        OMSettingsPage(title: AppStrings.importChats) {
            OMSettingsSection(AppStrings.importChats, icon: "upload") {
                VStack(alignment: .leading, spacing: .spacing5) {
                    Text(AppStrings.importDescription)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)

                    Text(AppStrings.importNativeDeferred)
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)

                    Button(AppStrings.importOpenWeb) {
                        openVerifiedWebImport()
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .accessibilityIdentifier("settings-import-open-web")
                }
                .padding(.spacing6)
            }
        }
        .accessibilityIdentifier("settings-import-page")
    }

    static func webImportURL(baseURL: URL) -> URL? {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            return nil
        }
        components.fragment = "settings/account/import"
        return components.url
    }

    private func openVerifiedWebImport() {
        Task {
            let baseURL = await APIClient.shared.webAppURL
            guard let url = Self.webImportURL(baseURL: baseURL) else {
                NativeDiagnostics.error("Account import web URL unavailable", category: "settings.account")
                return
            }
            openURL(url)
        }
    }
}
