// Admin logs viewer — live stream of backend and client console logs.
// Mirrors the web app's SettingsLogs.svelte: filter by level (all/warn/error),
// search by keyword, auto-scroll with newest entries at the bottom.

import SwiftUI

struct SettingsLogsView: View {
    @State private var logs: [LogEntry] = []
    @State private var filter: LogFilter = .all
    @State private var searchText = ""
    @State private var isLoading = true
    @State private var autoRefresh = true
    @State private var refreshTask: Task<Void, Never>?

    enum LogFilter: String, CaseIterable {
        case all = "All"
        case warn = "Warnings"
        case error = "Errors"
    }

    struct LogEntry: Identifiable, Decodable {
        let id: String
        let timestamp: String?
        let level: String?
        let message: String?
        let service: String?
        let source: String?
    }

    private var filteredLogs: [LogEntry] {
        var result = logs

        switch filter {
        case .warn:
            result = result.filter { $0.level == "warn" || $0.level == "WARNING" }
        case .error:
            result = result.filter { $0.level == "error" || $0.level == "ERROR" || $0.level == "CRITICAL" }
        case .all:
            break
        }

        if !searchText.isEmpty {
            let query = searchText.lowercased()
            result = result.filter { ($0.message?.lowercased().contains(query) ?? false) }
        }

        return result
    }

    var body: some View {
        VStack(spacing: 0) {
            filterBar

            if isLoading {
                Spacer()
                ProgressView("Loading logs...")
                Spacer()
            } else if filteredLogs.isEmpty {
                Spacer()
                ContentUnavailableView(
                    "No Logs",
                    systemImage: "doc.text.magnifyingglass",
                    description: Text("No log entries match your filter.")
                )
                Spacer()
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 1) {
                            ForEach(filteredLogs) { log in
                                LogRow(entry: log)
                                    .id(log.id)
                            }
                        }
                        .padding(.horizontal, .spacing2)
                    }
                    .onChange(of: filteredLogs.count) { _, _ in
                        if let last = filteredLogs.last {
                            withAnimation {
                                proxy.scrollTo(last.id, anchor: .bottom)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle("Logs")
        .searchable(text: $searchText, prompt: "Search logs")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Toggle(isOn: $autoRefresh) {
                    Label("Auto-refresh", systemImage: autoRefresh ? "arrow.clockwise.circle.fill" : "arrow.clockwise.circle")
                }
                .onChange(of: autoRefresh) { _, newValue in
                    if newValue { startPolling() } else { stopPolling() }
                }
            }
        }
        .task {
            await loadLogs()
            if autoRefresh { startPolling() }
        }
        .onDisappear { stopPolling() }
    }

    // MARK: - Filter bar

    private var filterBar: some View {
        Picker("Filter", selection: $filter) {
            ForEach(LogFilter.allCases, id: \.self) { f in
                Text(f.rawValue).tag(f)
            }
        }
        .pickerStyle(.segmented)
        .padding(.horizontal)
        .padding(.vertical, .spacing2)
    }

    // MARK: - Data loading

    private func loadLogs() async {
        do {
            logs = try await APIClient.shared.request(
                .get, path: "/v1/admin/logs?limit=200"
            )
        } catch {
            print("[Admin] Logs load error: \(error)")
        }
        isLoading = false
    }

    private func startPolling() {
        stopPolling()
        refreshTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard !Task.isCancelled else { break }
                await loadLogs()
            }
        }
    }

    private func stopPolling() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}

// MARK: - Log row

struct LogRow: View {
    let entry: SettingsLogsView.LogEntry

    private var levelColor: Color {
        switch entry.level?.lowercased() {
        case "error", "critical": return Color.error
        case "warn", "warning": return .orange
        case "info": return Color.fontSecondary
        case "debug": return Color.fontTertiary
        default: return Color.fontPrimary
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: .spacing2) {
                Text(entry.level?.uppercased().prefix(4) ?? "LOG")
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(levelColor)
                    .frame(width: 36, alignment: .leading)

                if let ts = entry.timestamp {
                    Text(formatTimestamp(ts))
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(Color.fontTertiary)
                }

                if let service = entry.service {
                    Text(service)
                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                        .foregroundStyle(Color.buttonPrimary.opacity(0.7))
                }
            }

            Text(entry.message ?? "")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(4)
                .textSelection(.enabled)
        }
        .padding(.vertical, 3)
        .padding(.horizontal, .spacing2)
        .background(
            entry.level?.lowercased() == "error" || entry.level?.lowercased() == "critical"
                ? Color.error.opacity(0.05)
                : Color.clear
        )
    }

    private func formatTimestamp(_ ts: String) -> String {
        // Trim to HH:MM:SS.mmm from ISO format
        if let tIndex = ts.firstIndex(of: "T") {
            let time = ts[ts.index(after: tIndex)...]
            return String(time.prefix(12))
        }
        return String(ts.suffix(12))
    }
}
