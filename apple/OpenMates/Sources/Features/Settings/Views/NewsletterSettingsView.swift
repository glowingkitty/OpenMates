// Newsletter subscription and category settings using the current public/auth routes.
// Guests request email confirmation; authenticated users manage category preferences.
// Mutations expose saving, success, and failure states without browser redirects.
// All product controls use OpenMates settings primitives and localized strings.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsNewsletter.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct NewsletterSettingsView: View {
    @EnvironmentObject private var authManager: AuthManager
    @ObservedObject private var localization = LocalizationManager.shared
    @State private var email = ""
    @State private var categories: [String: Bool] = [:]
    @State private var isSubscribed = false
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var statusMessage: String?
    @State private var errorMessage: String?

    private var isAuthenticated: Bool { authManager.currentUser != nil }

    var body: some View {
        OMSettingsPage(title: AppStrings.settingsNewsletter, showsHeader: false) {
            OMSettingsSection {
                Text(L("settings.newsletter.description"))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.spacing6)
            }

            if isAuthenticated {
                authenticatedPreferences
            } else {
                subscriptionForm
            }

            if let statusMessage {
                statusText(statusMessage, color: Color.buttonPrimary)
            }
            if let errorMessage {
                statusText(errorMessage, color: Color.error)
            }
        }
        .accessibilityIdentifier("settings-newsletter-page")
        .task { await loadCategoriesIfAuthenticated() }
    }

    private var subscriptionForm: some View {
        OMSettingsSection(AppStrings.email) {
            VStack(alignment: .leading, spacing: .spacing5) {
                TextField(AppStrings.email, text: $email)
                    .textContentType(.emailAddress)
                    .textFieldStyle(OMTextFieldStyle())
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.emailAddress)
                    #endif
                    .accessibilityIdentifier("newsletter-email-input")

                Button(AppStrings.newsletterSubscribe) { subscribe() }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
                    .accessibilityIdentifier("newsletter-subscribe-button")
            }
            .padding(.spacing6)
        }
    }

    @ViewBuilder
    private var authenticatedPreferences: some View {
        if isLoading {
            ProgressView().frame(maxWidth: .infinity).padding(.spacing8)
        } else {
            OMSettingsSection(L("settings.newsletter_categories.heading")) {
                ForEach(categories.keys.sorted(), id: \.self) { category in
                    OMSettingsToggleRow(
                        title: L("settings.newsletter_categories.\(category).title"),
                        subtitle: isSubscribed ? nil : L("settings.newsletter.description"),
                        isOn: Binding(
                            get: { categories[category] ?? true },
                            set: { value in saveCategory(category, enabled: value) }
                        ),
                        disabled: isSaving
                    )
                    .accessibilityIdentifier("newsletter-category-\(category)")
                }
            }
        }
    }

    private func statusText(_ message: String, color: Color) -> some View {
        Text(message)
            .font(.omSmall)
            .foregroundStyle(color)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.spacing6)
            .accessibilityIdentifier("newsletter-status")
    }

    private func loadCategoriesIfAuthenticated() async {
        guard isAuthenticated else {
            isLoading = false
            return
        }
        do {
            let response: NewsletterCategoriesResponse = try await APIClient.shared.request(
                .get, path: "/v1/newsletter/categories"
            )
            categories = response.categories
            isSubscribed = response.subscribed
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Newsletter category load failed", category: "settings.newsletter")
        }
        isLoading = false
    }

    private func subscribe() {
        isSaving = true
        statusMessage = nil
        errorMessage = nil
        Task {
            do {
                let response: NewsletterMutationResponse = try await APIClient.shared.request(
                    .post,
                    path: "/v1/newsletter/subscribe",
                    body: NewsletterSubscribeRequest(
                        email: email.trimmingCharacters(in: .whitespacesAndNewlines),
                        language: localization.currentLanguage.code,
                        darkmode: false
                    )
                )
                if response.success {
                    statusMessage = response.message
                    email = ""
                } else {
                    errorMessage = response.message
                }
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Newsletter subscription failed", category: "settings.newsletter")
            }
            isSaving = false
        }
    }

    private func saveCategory(_ category: String, enabled: Bool) {
        let previous = categories[category]
        categories[category] = enabled
        isSaving = true
        statusMessage = nil
        errorMessage = nil
        Task {
            do {
                let response: NewsletterCategoriesResponse = try await APIClient.shared.request(
                    .patch,
                    path: "/v1/newsletter/categories",
                    body: NewsletterCategoriesUpdateRequest(categories: [category: enabled])
                )
                guard response.success else { throw APIError.invalidResponse }
                categories = response.categories
                isSubscribed = response.subscribed
                statusMessage = AppStrings.success
            } catch {
                categories[category] = previous
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Newsletter category save failed", category: "settings.newsletter")
            }
            isSaving = false
        }
    }
}

private struct NewsletterCategoriesResponse: Decodable {
    let success: Bool
    let subscribed: Bool
    let categories: [String: Bool]
}

private struct NewsletterMutationResponse: Decodable {
    let success: Bool
    let message: String
}

private struct NewsletterSubscribeRequest: Encodable {
    let email: String
    let language: String
    let darkmode: Bool
}

private struct NewsletterCategoriesUpdateRequest: Encodable {
    let categories: [String: Bool]
}

@MainActor
private func L(_ key: String) -> String {
    LocalizationManager.shared.text(key)
}
