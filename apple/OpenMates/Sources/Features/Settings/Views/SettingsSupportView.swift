// Support contribution hub — one-time and monthly contributions to OpenMates.
// Mirrors the web app's SettingsSupport.svelte + support/SettingsSupportOneTime.svelte
// + support/SettingsSupportMonthly.svelte. Includes GitHub Sponsors link.

import SwiftUI

struct SettingsSupportView: View {
    var body: some View {
        List {
            Section {
                Text(LocalizationManager.shared.text("settings.support.description"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }

            Section("Contribute") {
                NavigationLink {
                    SupportOneTimeView()
                } label: {
                    Label("One-Time Contribution", systemImage: "heart")
                }

                NavigationLink {
                    SupportMonthlyView()
                } label: {
                    Label("Monthly Support", systemImage: "heart.circle")
                }
            }

            Section("Other Ways") {
                Link(destination: URL(string: "https://github.com/sponsors/glowingkitty")!) {
                    Label("GitHub Sponsors", systemImage: "star")
                }

                Link(destination: URL(string: "https://github.com/OpenMates/OpenMates")!) {
                    Label("Contribute Code", systemImage: "chevron.left.forwardslash.chevron.right")
                }

                Button {
                    shareApp()
                } label: {
                    Label("Share OpenMates", systemImage: "square.and.arrow.up")
                }
            }
        }
        .navigationTitle("Support")
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
        List {
            Section("Choose Amount") {
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
                    }
                }

                HStack {
                    Text("$")
                    TextField("Custom amount", text: $customAmount)
                        .keyboardType(.numberPad)
                        .onChange(of: customAmount) { _, _ in
                            selectedAmount = nil
                        }
                }
            }

            Section {
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
            }

            if success {
                Section {
                    Label("Thank you for your support!", systemImage: "heart.fill")
                        .foregroundStyle(.pink)
                }
            }
        }
        .navigationTitle("One-Time")
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
        List {
            if isActive, let amount = currentAmount {
                Section {
                    HStack {
                        Label("Active subscription", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                        Spacer()
                        Text("$\(amount)/month")
                            .font(.omSmall).fontWeight(.medium)
                    }

                    Button("Manage on Web") {
                        openWebSupport()
                    }

                    Button(role: .destructive) {
                        openWebSupport()
                    } label: {
                        Text(LocalizationManager.shared.text("settings.support.cancel_subscription"))
                    }
                }
            }

            Section("Monthly Tiers") {
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
                }
            }
        }
        .navigationTitle("Monthly Support")
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
