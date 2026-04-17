// Newsletter subscription management — subscribe/unsubscribe with category preferences.
// Mirrors the web app's newsletter-flow and newsletter-categories specs:
// email confirmation, category toggles, and subscription status display.

import SwiftUI

struct NewsletterSettingsView: View {
    @State private var isSubscribed = false
    @State private var email = ""
    @State private var categories: [NewsletterCategory] = []
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var showConfirmation = false
    @State private var error: String?

    struct NewsletterCategory: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        var isEnabled: Bool
    }

    var body: some View {
        List {
            Section {
                Toggle("Newsletter", isOn: $isSubscribed)
                    .tint(Color.buttonPrimary)
                    .onChange(of: isSubscribed) { _, newValue in
                        if newValue { subscribe() } else { unsubscribe() }
                    }

                if !isSubscribed {
                    Text("Get product updates, tips, and community highlights.")
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                }
            }

            if isSubscribed {
                Section("Email") {
                    HStack {
                        Text(email.isEmpty ? "Not set" : email)
                            .font(.omSmall)
                            .foregroundStyle(email.isEmpty ? Color.fontTertiary : Color.fontPrimary)
                        Spacer()
                        if showConfirmation {
                            Label("Confirmed", systemImage: "checkmark.circle.fill")
                                .font(.omTiny)
                                .foregroundStyle(.green)
                        }
                    }
                }

                if !categories.isEmpty {
                    Section("Categories") {
                        ForEach($categories) { $category in
                            Toggle(isOn: $category.isEnabled) {
                                VStack(alignment: .leading, spacing: .spacing1) {
                                    Text(category.name)
                                        .font(.omSmall)
                                    if let desc = category.description {
                                        Text(desc)
                                            .font(.omXs)
                                            .foregroundStyle(Color.fontSecondary)
                                    }
                                }
                            }
                            .tint(Color.buttonPrimary)
                            .onChange(of: category.isEnabled) { _, _ in
                                saveCategories()
                            }
                        }
                    }
                }
            }

            if let error {
                Section {
                    Text(error)
                        .font(.omSmall)
                        .foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Newsletter")
        .task { await loadStatus() }
    }

    // MARK: - API calls

    private func loadStatus() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/newsletter"
            )
            isSubscribed = response["subscribed"]?.value as? Bool ?? false
            email = response["email"]?.value as? String ?? ""
            showConfirmation = response["confirmed"]?.value as? Bool ?? false

            if let cats = response["categories"]?.value as? [[String: Any]] {
                categories = cats.compactMap { dict in
                    guard let id = dict["id"] as? String,
                          let name = dict["name"] as? String else { return nil }
                    return NewsletterCategory(
                        id: id, name: name,
                        description: dict["description"] as? String,
                        isEnabled: dict["is_enabled"] as? Bool ?? true
                    )
                }
            }
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func subscribe() {
        isSaving = true
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/newsletter/subscribe",
                    body: [:] as [String: String]
                )
                await loadStatus()
            } catch {
                self.error = error.localizedDescription
                isSubscribed = false
            }
            isSaving = false
        }
    }

    private func unsubscribe() {
        isSaving = true
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/newsletter/unsubscribe",
                    body: [:] as [String: String]
                )
                categories = []
            } catch {
                self.error = error.localizedDescription
                isSubscribed = true
            }
            isSaving = false
        }
    }

    private func saveCategories() {
        let enabledIds = categories.filter(\.isEnabled).map(\.id)
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/newsletter/categories",
                body: ["enabled_categories": enabledIds]
            ) as Data
        }
    }
}
