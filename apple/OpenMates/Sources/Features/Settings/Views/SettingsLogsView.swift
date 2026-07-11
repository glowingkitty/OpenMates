// Admin diagnostics viewer for native and backend log snapshots.
// Filters and search mirror the web logs surface without stock toolbar/search chrome.
// Backend data uses the current admin debug logs response and explicit error states.
// Local diagnostics remain privacy-sanitized by NativeClientLogCollector.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsLogs.svelte
// CSS:     frontend/packages/ui/src/components/settings/SettingsLogs.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsLogsView: View {
    @State private var backendLines: [LogLine] = []
    @State private var filter: LogFilter = .all
    @State private var searchText = ""
    @State private var isLoading = true
    @State private var autoRefresh = true
    @State private var errorMessage: String?
    @State private var refreshTask: Task<Void, Never>?

    enum LogFilter: String, CaseIterable, Identifiable {
        case all, warn, error
        var id: String { rawValue }
        var title: String { L("settings.logs.filter_\(rawValue)") }
    }

    struct LogsResponse: Decodable {
        let logs: String
        let servicesQueried: [String]
        let timestamp: String
    }

    struct LogLine: Identifiable {
        let id = UUID()
        let text: String

        var level: LogFilter {
            let lowered = text.lowercased()
            if lowered.contains("error") || lowered.contains("critical") { return .error }
            if lowered.contains("warn") { return .warn }
            return .all
        }
    }

    private var filteredLines: [LogLine] {
        backendLines.filter { line in
            let matchesLevel = filter == .all || line.level == filter
            let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
            return matchesLevel && (query.isEmpty || line.text.localizedCaseInsensitiveContains(query))
        }
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.logs, showsHeader: false) {
            OMSettingsSection {
                VStack(spacing: .spacing5) {
                    OMSegmentedControl(
                        items: LogFilter.allCases.map { .init(id: $0, title: $0.title) },
                        selection: $filter
                    )
                    TextField(L("settings.logs.search"), text: $searchText)
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityIdentifier("settings-logs-search")
                    OMSettingsToggleRow(
                        title: L("settings.logs.auto_refresh"),
                        isOn: $autoRefresh
                    )
                    .onChange(of: autoRefresh) { _, enabled in
                        if enabled { startPolling() } else { stopPolling() }
                    }
                    Button(L("common.refresh")) { Task { await loadLogs() } }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .accessibilityIdentifier("settings-logs-refresh")
                }
                .padding(.spacing6)
            }

            OMSettingsSection(AppStrings.logs) {
                if isLoading {
                    ProgressView().frame(maxWidth: .infinity).padding(.spacing8)
                } else if filteredLines.isEmpty {
                    Text(L("settings.logs.no_entries"))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.spacing6)
                } else {
                    ForEach(filteredLines) { line in
                        Text(line.text)
                            .font(.omXs.monospaced())
                            .foregroundStyle(line.level == .error ? Color.error : Color.fontPrimary)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing2)
                    }
                }
            }

            if let errorMessage {
                Text(errorMessage).font(.omSmall).foregroundStyle(Color.error).padding(.spacing6)
            }
        }
        .accessibilityIdentifier("settings-logs-page")
        .task {
            await loadLogs()
            if autoRefresh { startPolling() }
        }
        .onDisappear { stopPolling() }
    }

    private func loadLogs() async {
        do {
            let response: LogsResponse = try await APIClient.shared.request(
                .get, path: "/v1/admin/debug/logs?limit=200"
            )
            backendLines = response.logs.split(separator: "\n").map { LogLine(text: String($0)) }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Admin log snapshot failed", category: "settings.admin")
        }
        isLoading = false
    }

    private func startPolling() {
        stopPolling()
        refreshTask = Task {
            while !Task.isCancelled {
                do {
                    try await Task.sleep(for: .seconds(5))
                } catch {
                    return
                }
                guard !Task.isCancelled else { return }
                await loadLogs()
            }
        }
    }

    private func stopPolling() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}

@MainActor
private func L(_ key: String) -> String { LocalizationManager.shared.text(key) }
