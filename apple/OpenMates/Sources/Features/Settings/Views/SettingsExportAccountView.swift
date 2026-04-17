// Account data export — request and download a full account data archive.
// Mirrors the web app's account/SettingsExportAccount.svelte.
// Triggers a server-side export job and provides download when ready.

import SwiftUI

struct SettingsExportAccountView: View {
    @State private var exportStatus: ExportStatus = .idle
    @State private var downloadURL: String?
    @State private var error: String?

    enum ExportStatus: Equatable {
        case idle
        case requesting
        case processing
        case ready
    }

    var body: some View {
        List {
            Section {
                Text("Export all your account data including chats, messages, embeds, memories, and settings.")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }

            Section {
                switch exportStatus {
                case .idle:
                    Button("Request Data Export") {
                        requestExport()
                    }

                case .requesting:
                    HStack {
                        ProgressView()
                        Text("Requesting export...")
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }

                case .processing:
                    VStack(alignment: .leading, spacing: .spacing3) {
                        HStack {
                            ProgressView()
                            Text("Preparing your data...")
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                        Text("This may take a few minutes for large accounts.")
                            .font(.omXs).foregroundStyle(Color.fontTertiary)
                    }

                case .ready:
                    if let downloadURL {
                        VStack(alignment: .leading, spacing: .spacing3) {
                            Label("Export ready", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(.green)

                            Button("Download Archive") {
                                openDownload(downloadURL)
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(Color.buttonPrimary)

                            Text("The download link expires in 24 hours.")
                                .font(.omXs).foregroundStyle(Color.fontTertiary)
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
        .navigationTitle("Export Data")
        .task { await checkExistingExport() }
    }

    private func checkExistingExport() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/export/status"
            )
            let status = response["status"]?.value as? String
            if status == "ready" {
                downloadURL = response["download_url"]?.value as? String
                exportStatus = .ready
            } else if status == "processing" {
                exportStatus = .processing
                pollForCompletion()
            }
        } catch {
            // No existing export — that's fine
        }
    }

    private func requestExport() {
        exportStatus = .requesting
        error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/export/request",
                    body: [:] as [String: String]
                )
                exportStatus = .processing
                pollForCompletion()
            } catch {
                self.error = error.localizedDescription
                exportStatus = .idle
            }
        }
    }

    private func pollForCompletion() {
        Task {
            for _ in 0..<60 {
                try? await Task.sleep(for: .seconds(5))
                do {
                    let response: [String: AnyCodable] = try await APIClient.shared.request(
                        .get, path: "/v1/settings/export/status"
                    )
                    let status = response["status"]?.value as? String
                    if status == "ready" {
                        downloadURL = response["download_url"]?.value as? String
                        exportStatus = .ready
                        return
                    } else if status == "failed" {
                        error = "Export failed. Please try again."
                        exportStatus = .idle
                        return
                    }
                } catch {
                    break
                }
            }
        }
    }

    private func openDownload(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        #if os(iOS)
        UIApplication.shared.open(url)
        #elseif os(macOS)
        NSWorkspace.shared.open(url)
        #endif
    }
}
