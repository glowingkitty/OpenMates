// Support contribution hub — one-time and monthly contributions to OpenMates.
// Mirrors the web app's SettingsSupport.svelte + support/SettingsSupportOneTime.svelte
// + support/SettingsSupportMonthly.svelte. Includes GitHub Sponsors link.

import SwiftUI

struct SettingsSupportView: View {
    @State private var destination: SupportDestination?

    var body: some View {
        if let destination {
            switch destination {
            case .oneTime: SupportOneTimeView()
            case .monthly: SupportMonthlyView()
            }
        } else {
            OMSettingsPage(title: AppStrings.settingsSupport, showsHeader: false) {
            OMSettingsSection {
                Text(LocalizationManager.shared.text("settings.support.description"))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.spacing5)
            }

            OMSettingsSection(LocalizationManager.shared.text("settings.support.contribute")) {
                OMSettingsRow(title: LocalizationManager.shared.text("settings.support.one_time"), icon: "support") {
                    destination = .oneTime
                }

                OMSettingsRow(title: LocalizationManager.shared.text("settings.support.monthly"), icon: "support") {
                    destination = .monthly
                }
            }

            OMSettingsSection(LocalizationManager.shared.text("settings.support.other_ways")) {
                Link(destination: URL(string: "https://github.com/sponsors/glowingkitty")!) {
                    HStack(spacing: .spacing4) {
                        Icon("github", size: 22)
                        Text("GitHub Sponsors")
                            .font(.omP)
                            .fontWeight(.medium)
                    }
                    .foregroundStyle(LinearGradient.primary)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing3)
                }
                .accessibilityHint(LocalizationManager.shared.text("settings.support.github_sponsors_hint"))

                Link(destination: URL(string: "https://github.com/OpenMates/OpenMates")!) {
                    HStack(spacing: .spacing4) {
                        Icon("coding", size: 22)
                        Text(LocalizationManager.shared.text("settings.support.contribute_code"))
                            .font(.omP)
                            .fontWeight(.medium)
                    }
                    .foregroundStyle(LinearGradient.primary)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing3)
                }
                .accessibilityHint(LocalizationManager.shared.text("settings.support.contribute_code_hint"))

                Button {
                    shareApp()
                } label: {
                    HStack(spacing: .spacing4) {
                        Icon("share", size: 22)
                        Text(LocalizationManager.shared.text("settings.support.share_openmates"))
                            .font(.omP)
                            .fontWeight(.medium)
                    }
                    .foregroundStyle(LinearGradient.primary)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing3)
                }
                .accessibleButton("Share OpenMates")
                .buttonStyle(.plain)
            }
        }
        }
    }

    private enum SupportDestination {
        case oneTime, monthly
    }

    private func shareApp() {
        let url = URL(string: "https://openmates.org")!
        #if os(iOS)
        let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        if let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
           let rootVC = windowScene.windows.first?.rootViewController {
            rootVC.present(activityVC, animated: true)
        }
        #elseif os(macOS)
        let picker = NSSharingServicePicker(items: [url])
        if let window = NSApp.keyWindow, let contentView = window.contentView {
            picker.show(relativeTo: .zero, of: contentView, preferredEdge: .minY)
        }
        #endif
    }
}

// MARK: - One-time contribution

struct SupportOneTimeView: View {
    @State private var selectedAmount: Int?
    @State private var customAmount = ""
    @State private var isProcessing = false
    @State private var success = false

    private let presetAmounts = [5, 10, 25, 50, 100]

    var body: some View {
        OMSettingsPage(title: LocalizationManager.shared.text("settings.support.one_time"), showsHeader: false) {
            OMSettingsSection(LocalizationManager.shared.text("settings.support.choose_amount")) {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 80))], spacing: .spacing3) {
                    ForEach(presetAmounts, id: \.self) { amount in
                        Button {
                            selectedAmount = amount
                            customAmount = ""
                        } label: {
                            Text("$\(amount)")
                                .font(.omSmall).fontWeight(.medium)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, .spacing3)
                                .background(selectedAmount == amount ? Color.buttonPrimary : Color.grey10)
                                .foregroundStyle(selectedAmount == amount ? .white : Color.fontPrimary)
                                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                        }
                        .buttonStyle(.plain)
                        .accessibleButton(
                            "$\(amount)",
                            hint: selectedAmount == amount ? LocalizationManager.shared.text("settings.support.amount_selected") : nil
                        )
                    }
                }
                .padding(.spacing5)

                HStack {
                    Text("$")
                    TextField("Custom amount", text: $customAmount)
                        .textFieldStyle(OMTextFieldStyle())
                        #if os(iOS)
                        .keyboardType(.numberPad)
                        #endif
                        .onChange(of: customAmount) { _, _ in
                            selectedAmount = nil
                        }
                        .accessibleInput("Custom amount", hint: LocalizationManager.shared.text("settings.support.custom_amount_hint"))
                }
                .padding(.horizontal, .spacing5)
                .padding(.bottom, .spacing5)
            }

            OMSettingsSection {
                Button {
                    processPayment()
                } label: {
                    HStack {
                        Spacer()
                        if isProcessing {
                            ProgressView()
                        } else {
                            Text(LocalizationManager.shared.text("settings.support.contribute"))
                                .fontWeight(.medium)
                        }
                        Spacer()
                    }
                }
                .disabled(selectedAmount == nil && customAmount.isEmpty)
                .buttonStyle(OMPrimaryButtonStyle())
                .accessibleButton(LocalizationManager.shared.text("settings.support.contribute"))
                .padding(.spacing5)
            }

            if success {
                OMSettingsSection {
                    HStack(spacing: .spacing3) {
                        Icon("support", size: 22)
                        Text(LocalizationManager.shared.text("settings.support.thank_you"))
                            .font(.omSmall)
                            .fontWeight(.semibold)
                    }
                    .foregroundStyle(Color.buttonPrimary)
                    .padding(.spacing5)
                }
            }
        }
    }

    private func processPayment() {
        let amount = selectedAmount ?? Int(customAmount) ?? 0
        guard amount > 0 else { return }

        isProcessing = true
        Task {
            let url = await APIClient.shared.webAppURL
                .appendingPathComponent("settings/support/one-time")
                .appending(queryItems: [URLQueryItem(name: "amount", value: "\(amount)")])
            #if os(iOS)
            await UIApplication.shared.open(url)
            #elseif os(macOS)
            NSWorkspace.shared.open(url)
            #endif
            isProcessing = false
        }
    }
}

// MARK: - Monthly support

struct SupportMonthlyView: View {
    @State private var selectedTier: Int?
    @State private var isActive = false
    @State private var currentAmount: Int?

    private let tiers = [
        (5, "Supporter", "Help keep the lights on"),
        (10, "Backer", "Fund new feature development"),
        (25, "Champion", "Accelerate growth and innovation"),
        (50, "Patron", "Shape the future of OpenMates"),
    ]

    var body: some View {
        OMSettingsPage(title: LocalizationManager.shared.text("settings.support.monthly"), showsHeader: false) {
            if isActive, let amount = currentAmount {
                OMSettingsSection {
                    HStack {
                        Icon("check", size: 18)
                            .foregroundStyle(Color.buttonPrimary)
                        Text(LocalizationManager.shared.text("settings.support.active_subscription"))
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                        Spacer()
                        Text("$\(amount)/month")
                            .font(.omSmall).fontWeight(.medium)
                    }
                    .padding(.spacing5)

                    Button("Manage on Web") {
                        openWebSupport()
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .padding(.horizontal, .spacing5)

                    Button(role: .destructive) {
                        openWebSupport()
                    } label: {
                        Text(LocalizationManager.shared.text("settings.support.cancel_subscription"))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Color.error)
                    .padding(.spacing5)
                }
            }

            OMSettingsSection(LocalizationManager.shared.text("settings.support.monthly_tiers")) {
                ForEach(tiers, id: \.0) { amount, name, description in
                    Button {
                        selectedTier = amount
                        openMonthlyPayment(amount)
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(name)
                                    .font(.omSmall).fontWeight(.medium)
                                    .foregroundStyle(Color.fontPrimary)
                                Text(description)
                                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                            }
                            Spacer()
                            Text("$\(amount)/mo")
                                .font(.omSmall).fontWeight(.semibold)
                                .foregroundStyle(Color.buttonPrimary)
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing3)
                    .accessibleButton("\(name), $\(amount) per month. \(description)")
                }
            }
        }
        .task { await loadStatus() }
    }

    private func loadStatus() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/support/monthly/status"
            )
            isActive = response["active"]?.value as? Bool ?? false
            currentAmount = response["amount"]?.value as? Int
        } catch {
            // No subscription — that's fine
        }
    }

    private func openMonthlyPayment(_ amount: Int) {
        Task {
            let url = await APIClient.shared.webAppURL
                .appendingPathComponent("settings/support/monthly")
                .appending(queryItems: [URLQueryItem(name: "tier", value: "\(amount)")])
            #if os(iOS)
            await UIApplication.shared.open(url)
            #elseif os(macOS)
            NSWorkspace.shared.open(url)
            #endif
        }
    }

    private func openWebSupport() {
        Task {
            let url = await APIClient.shared.webAppURL.appendingPathComponent("settings/support/monthly")
            #if os(iOS)
            await UIApplication.shared.open(url)
            #elseif os(macOS)
            NSWorkspace.shared.open(url)
            #endif
        }
    }
}
