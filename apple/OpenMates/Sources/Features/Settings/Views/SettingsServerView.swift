// Admin server settings — software updates, server stats, gift card generator, test results.
// Mirrors the web app's SettingsServer.svelte + server/ sub-pages.
// Only accessible when user is admin (is_admin flag from user profile).

import SwiftUI

struct SettingsServerView: View {
    var body: some View {
        List {
            NavigationLink {
                ServerSoftwareUpdateView()
            } label: {
                Label("Software Updates", systemImage: "arrow.down.circle")
            }

            NavigationLink {
                ServerStatsView()
            } label: {
                Label("Statistics", systemImage: "chart.line.uptrend.xyaxis")
            }

            NavigationLink {
                ServerGiftCardGeneratorView()
            } label: {
                Label("Gift Card Generator", systemImage: "gift")
            }

            NavigationLink {
                ServerTestResultsView()
            } label: {
                Label("Test Results", systemImage: "checkmark.diamond")
            }
        }
        .navigationTitle("Server")
    }
}

// MARK: - Software Updates

struct ServerSoftwareUpdateView: View {
    @State private var currentVersion: VersionInfo?
    @State private var latestVersion: VersionInfo?
    @State private var updateAvailable = false
    @State private var commitsBehind = 0
    @State private var isChecking = false
    @State private var isInstalling = false
    @State private var installStatus: String?
    @State private var autoCheckEnabled = true
    @State private var autoInstallEnabled = false
    @State private var error: String?

    struct VersionInfo: Decodable {
        let sha: String?
        let shortSha: String?
        let message: String?
        let date: String?
        let tag: String?
    }

    var body: some View {
        List {
            Section("Current Version") {
                if let v = currentVersion {
                    HStack {
                        Text("Commit")
                        Spacer()
                        Text(v.shortSha ?? v.sha?.prefix(7).description ?? "unknown")
                            .font(.system(.body, design: .monospaced))
                            .foregroundStyle(Color.fontSecondary)
                    }
                    if let tag = v.tag, !tag.isEmpty {
                        HStack {
                            Text("Tag")
                            Spacer()
                            Text(tag).foregroundStyle(Color.fontSecondary)
                        }
                    }
                    if let date = v.date {
                        HStack {
                            Text("Date")
                            Spacer()
                            Text(date).font(.omXs).foregroundStyle(Color.fontTertiary)
                        }
                    }
                } else if isChecking {
                    ProgressView()
                } else {
                    Text("Not available").foregroundStyle(Color.fontTertiary)
                }
            }

            if updateAvailable, let latest = latestVersion {
                Section("Update Available") {
                    HStack {
                        Text("Latest")
                        Spacer()
                        Text(latest.shortSha ?? "")
                            .font(.system(.body, design: .monospaced))
                            .foregroundStyle(Color.buttonPrimary)
                    }
                    if let msg = latest.message {
                        Text(msg)
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    Text("\(commitsBehind) commits behind")
                        .font(.omXs).foregroundStyle(Color.warning)

                    Button {
                        installUpdate()
                    } label: {
                        HStack {
                            Spacer()
                            if isInstalling {
                                ProgressView()
                                Text("Installing...")
                            } else {
                                Label("Install Update", systemImage: "arrow.down.circle.fill")
                            }
                            Spacer()
                        }
                    }
                    .disabled(isInstalling)
                }
            }

            if let status = installStatus {
                Section {
                    Text(status)
                        .font(.omSmall)
                        .foregroundStyle(status.contains("failed") ? Color.error : .green)
                }
            }

            Section("Update Settings") {
                Toggle("Auto-check for updates", isOn: $autoCheckEnabled)
                    .tint(Color.buttonPrimary)
                    .onChange(of: autoCheckEnabled) { _, _ in saveUpdateSettings() }

                Toggle("Auto-install updates", isOn: $autoInstallEnabled)
                    .tint(Color.buttonPrimary)
                    .onChange(of: autoInstallEnabled) { _, _ in saveUpdateSettings() }
            }

            Section {
                Button("Check for Updates") { checkForUpdates() }
                    .disabled(isChecking)
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Software Updates")
        .task { await loadUpdateStatus() }
    }

    private func loadUpdateStatus() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/admin/update/status"
            )
            updateAvailable = response["update_available"]?.value as? Bool ?? false
            commitsBehind = response["commits_behind"]?.value as? Int ?? 0
            autoCheckEnabled = response["auto_check"]?.value as? Bool ?? true
            autoInstallEnabled = response["auto_install"]?.value as? Bool ?? false

            if let current = response["current_version"]?.value as? [String: Any] {
                currentVersion = parseVersionInfo(current)
            }
            if let latest = response["latest_version"]?.value as? [String: Any] {
                latestVersion = parseVersionInfo(latest)
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func parseVersionInfo(_ dict: [String: Any]) -> VersionInfo {
        VersionInfo(
            sha: dict["sha"] as? String,
            shortSha: dict["short_sha"] as? String,
            message: dict["message"] as? String,
            date: dict["date"] as? String,
            tag: dict["tag"] as? String
        )
    }

    private func checkForUpdates() {
        isChecking = true
        error = nil
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/admin/update/check",
                    body: [:] as [String: String]
                )
                updateAvailable = response["update_available"]?.value as? Bool ?? false
                commitsBehind = response["commits_behind"]?.value as? Int ?? 0
                if let latest = response["latest_version"]?.value as? [String: Any] {
                    latestVersion = parseVersionInfo(latest)
                }
            } catch {
                self.error = error.localizedDescription
            }
            isChecking = false
        }
    }

    private func installUpdate() {
        isInstalling = true
        installStatus = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/admin/update/install",
                    body: [:] as [String: String]
                )
                installStatus = "Update installed successfully. Services are restarting."
                updateAvailable = false
            } catch {
                installStatus = "Update failed: \(error.localizedDescription)"
            }
            isInstalling = false
        }
    }

    private func saveUpdateSettings() {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/admin/update/settings",
                body: ["auto_check": autoCheckEnabled, "auto_install": autoInstallEnabled] as [String: Bool]
            ) as Data
        }
    }
}

// MARK: - Server Statistics

struct ServerStatsView: View {
    @State private var dailyStats: [StatRecord] = []
    @State private var todaySummary: [String: AnyCodable]?
    @State private var isLoading = true

    struct StatRecord: Identifiable, Decodable {
        let id: String
        let date: String?
        let newUsersRegistered: Int?
        let newUsersFinishedSignup: Int?
        let incomeEurCents: Int?
        let creditsSold: Int?
        let creditsUsed: Int?
        let messagesSent: Int?
        let chatsCreated: Int?
        let embedsCreated: Int?
        let totalRegularUsers: Int?
        let activeSubscriptions: Int?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else {
                if let today = todaySummary {
                    Section("Today") {
                        statRow("New Users", value: today["new_users_registered"]?.value as? Int)
                        statRow("Signups Completed", value: today["new_users_finished_signup"]?.value as? Int)
                        statRow("Messages Sent", value: today["messages_sent"]?.value as? Int)
                        statRow("Chats Created", value: today["chats_created"]?.value as? Int)
                        statRow("Embeds Created", value: today["embeds_created"]?.value as? Int)
                        statRow("Credits Sold", value: today["credits_sold"]?.value as? Int)
                        statRow("Credits Used", value: today["credits_used"]?.value as? Int)
                        statRow("Income (EUR cents)", value: today["income_eur_cents"]?.value as? Int)
                        statRow("Total Users", value: today["total_regular_users"]?.value as? Int)
                        statRow("Active Subscriptions", value: today["active_subscriptions"]?.value as? Int)
                    }
                }

                Section("Daily History") {
                    ForEach(dailyStats.prefix(30)) { stat in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(stat.date ?? "Unknown")
                                .font(.omSmall).fontWeight(.medium)
                            HStack(spacing: .spacing4) {
                                miniStat("Users", stat.newUsersRegistered)
                                miniStat("Msgs", stat.messagesSent)
                                miniStat("Chats", stat.chatsCreated)
                                miniStat("Credits", stat.creditsSold)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle("Statistics")
        .task { await loadStats() }
    }

    private func statRow(_ label: String, value: Int?) -> some View {
        HStack {
            Text(label)
            Spacer()
            Text("\(value ?? 0)")
                .font(.system(.body, design: .monospaced))
                .foregroundStyle(Color.fontSecondary)
        }
    }

    private func miniStat(_ label: String, _ value: Int?) -> some View {
        VStack(spacing: 0) {
            Text("\(value ?? 0)")
                .font(.omXs).fontWeight(.medium)
            Text(label)
                .font(.omTiny).foregroundStyle(Color.fontTertiary)
        }
    }

    private func loadStats() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/admin/stats"
            )

            todaySummary = response["today"]?.value as? [String: AnyCodable]

            if let daily = response["daily"]?.value as? [[String: Any]] {
                dailyStats = daily.compactMap { dict in
                    guard let id = dict["id"] as? String else { return nil }
                    return StatRecord(
                        id: id,
                        date: dict["date"] as? String,
                        newUsersRegistered: dict["new_users_registered"] as? Int,
                        newUsersFinishedSignup: dict["new_users_finished_signup"] as? Int,
                        incomeEurCents: dict["income_eur_cents"] as? Int,
                        creditsSold: dict["credits_sold"] as? Int,
                        creditsUsed: dict["credits_used"] as? Int,
                        messagesSent: dict["messages_sent"] as? Int,
                        chatsCreated: dict["chats_created"] as? Int,
                        embedsCreated: dict["embeds_created"] as? Int,
                        totalRegularUsers: dict["total_regular_users"] as? Int,
                        activeSubscriptions: dict["active_subscriptions"] as? Int
                    )
                }
            }
        } catch {
            print("[Admin] Stats load error: \(error)")
        }
        isLoading = false
    }
}

// MARK: - Gift Card Generator

struct ServerGiftCardGeneratorView: View {
    @State private var creditsValue = 100
    @State private var quantity = 1
    @State private var prefix = ""
    @State private var notes = ""
    @State private var isGenerating = false
    @State private var generatedCodes: [GeneratedCode] = []
    @State private var activeCards: [ActiveCard] = []
    @State private var error: String?

    struct GeneratedCode: Identifiable {
        let id = UUID()
        let code: String
        let creditsValue: Int
    }

    struct ActiveCard: Identifiable, Decodable {
        let id: String
        let code: String
        let creditsValue: Int?
        let createdAt: String?
        let notes: String?
    }

    private let presetAmounts = [100, 500, 1000, 5000, 10000, 21000]

    var body: some View {
        List {
            Section("Generate Gift Cards") {
                Picker("Credits", selection: $creditsValue) {
                    ForEach(presetAmounts, id: \.self) { amount in
                        Text("\(amount) credits").tag(amount)
                    }
                }

                Stepper("Quantity: \(quantity)", value: $quantity, in: 1...50)

                TextField("Custom prefix (optional)", text: $prefix)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.characters)
                    #endif

                TextField("Notes (optional)", text: $notes)

                Button {
                    generateCards()
                } label: {
                    HStack {
                        Spacer()
                        if isGenerating {
                            ProgressView()
                        } else {
                            Text("Generate \(quantity) Card\(quantity > 1 ? "s" : "")")
                                .fontWeight(.medium)
                        }
                        Spacer()
                    }
                }
                .disabled(isGenerating)
            }

            if !generatedCodes.isEmpty {
                Section("Generated Codes") {
                    ForEach(generatedCodes) { code in
                        HStack {
                            Text(code.code)
                                .font(.system(.body, design: .monospaced))
                                .textSelection(.enabled)
                            Spacer()
                            Button {
                                copyToClipboard(code.code)
                            } label: {
                                Image(systemName: "doc.on.doc")
                            }
                        }
                    }

                    Button("Copy All") {
                        let allCodes = generatedCodes.map(\.code).joined(separator: "\n")
                        copyToClipboard(allCodes)
                    }
                }
            }

            Section("Active Gift Cards") {
                if activeCards.isEmpty {
                    Text("No unredeemed gift cards")
                        .foregroundStyle(Color.fontTertiary)
                } else {
                    ForEach(activeCards) { card in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            HStack {
                                Text(card.code)
                                    .font(.system(.caption, design: .monospaced))
                                Spacer()
                                Text("\(card.creditsValue ?? 0) credits")
                                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                            }
                            if let notes = card.notes, !notes.isEmpty {
                                Text(notes)
                                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
                            }
                        }
                    }
                }
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Gift Card Generator")
        .task { await loadActiveCards() }
    }

    private func generateCards() {
        isGenerating = true
        error = nil
        Task {
            do {
                var body: [String: Any] = [
                    "credits_value": creditsValue,
                    "quantity": quantity
                ]
                if !prefix.isEmpty { body["prefix"] = prefix }
                if !notes.isEmpty { body["notes"] = notes }

                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/admin/gift-cards/generate", body: body
                )
                if let codes = response["codes"]?.value as? [String] {
                    generatedCodes = codes.map { GeneratedCode(code: $0, creditsValue: creditsValue) }
                }
                await loadActiveCards()
            } catch {
                self.error = error.localizedDescription
            }
            isGenerating = false
        }
    }

    private func loadActiveCards() async {
        do {
            activeCards = try await APIClient.shared.request(
                .get, path: "/v1/admin/gift-cards/active"
            )
        } catch {
            print("[Admin] Gift cards load error: \(error)")
        }
    }

    private func copyToClipboard(_ text: String) {
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
        ToastManager.shared.show("Copied", type: .success)
    }
}

// MARK: - Test Results

struct ServerTestResultsView: View {
    @State private var testRun: TestRunData?
    @State private var isLoading = true
    @State private var error: String?

    struct TestRunData: Decodable {
        let runId: String?
        let gitSha: String?
        let gitBranch: String?
        let durationSeconds: Double?
        let summary: TestSummary?
        let suites: [String: SuiteResult]?
    }

    struct TestSummary: Decodable {
        let total: Int?
        let passed: Int?
        let failed: Int?
        let skipped: Int?
    }

    struct SuiteResult: Decodable {
        let status: String?
        let durationSeconds: Double?
        let tests: [TestEntry]?
    }

    struct TestEntry: Identifiable, Decodable {
        var id: String { name ?? file ?? UUID().uuidString }
        let file: String?
        let name: String?
        let status: String?
        let durationSeconds: Double?
        let error: String?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if let run = testRun {
                Section("Last Run") {
                    if let sha = run.gitSha {
                        HStack {
                            Text("Commit")
                            Spacer()
                            Text(String(sha.prefix(7)))
                                .font(.system(.body, design: .monospaced))
                                .foregroundStyle(Color.fontSecondary)
                        }
                    }
                    if let branch = run.gitBranch {
                        HStack {
                            Text("Branch")
                            Spacer()
                            Text(branch).foregroundStyle(Color.fontSecondary)
                        }
                    }
                    if let duration = run.durationSeconds {
                        HStack {
                            Text("Duration")
                            Spacer()
                            Text(String(format: "%.1fs", duration))
                                .foregroundStyle(Color.fontSecondary)
                        }
                    }
                }

                if let summary = run.summary {
                    Section("Summary") {
                        HStack(spacing: .spacing6) {
                            SummaryBadge(label: "Total", value: summary.total ?? 0, color: Color.fontPrimary)
                            SummaryBadge(label: "Passed", value: summary.passed ?? 0, color: .green)
                            SummaryBadge(label: "Failed", value: summary.failed ?? 0, color: Color.error)
                            SummaryBadge(label: "Skipped", value: summary.skipped ?? 0, color: Color.fontTertiary)
                        }
                        .frame(maxWidth: .infinity)
                    }
                }

                if let suites = run.suites {
                    ForEach(Array(suites.keys.sorted()), id: \.self) { suiteName in
                        if let suite = suites[suiteName] {
                            Section(suiteName.replacingOccurrences(of: "_", with: " ").capitalized) {
                                HStack {
                                    Text("Status")
                                    Spacer()
                                    Text(suite.status?.capitalized ?? "Unknown")
                                        .foregroundStyle(suite.status == "passed" ? .green : Color.error)
                                }

                                if let tests = suite.tests {
                                    let failed = tests.filter { $0.status == "failed" }
                                    if !failed.isEmpty {
                                        ForEach(failed) { test in
                                            VStack(alignment: .leading, spacing: .spacing1) {
                                                Text(test.name ?? test.file ?? "Unknown test")
                                                    .font(.omSmall).fontWeight(.medium)
                                                    .foregroundStyle(Color.error)
                                                if let err = test.error {
                                                    Text(err)
                                                        .font(.system(.caption, design: .monospaced))
                                                        .foregroundStyle(Color.fontTertiary)
                                                        .lineLimit(3)
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                Section {
                    Text("No test results available")
                        .foregroundStyle(Color.fontSecondary)
                }
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Test Results")
        .task { await loadResults() }
    }

    private func loadResults() async {
        do {
            testRun = try await APIClient.shared.request(.get, path: "/v1/admin/test-results")
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}

struct SummaryBadge: View {
    let label: String
    let value: Int
    let color: Color

    var body: some View {
        VStack(spacing: .spacing1) {
            Text("\(value)")
                .font(.omH4).fontWeight(.bold)
                .foregroundStyle(color)
            Text(label)
                .font(.omTiny).foregroundStyle(Color.fontTertiary)
        }
    }
}
