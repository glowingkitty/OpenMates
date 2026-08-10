// Native account data export using the web export manifest and data endpoints.
// The archive is assembled on-device and handed to the OS file exporter; no
// browser URL or unauthenticated download fallback is used.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsExportAccount.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import UniformTypeIdentifiers

struct SettingsExportAccountView: View {
    @State private var isExporting = false
    @State private var document: AccountExportDocument?
    @State private var showExporter = false
    @State private var errorMessage: String?
    @State private var statusMessage: String?

    var body: some View {
        OMSettingsPage(title: AppStrings.exportData) {
            OMSettingsSection(AppStrings.exportData, icon: "download") {
                VStack(alignment: .leading, spacing: .spacing5) {
                    Text(AppStrings.exportDescription)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                    Text(AppStrings.exportGDPRNotice)
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                    Button(AppStrings.exportButton) { prepareExport() }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(isExporting)
                        .accessibilityIdentifier("settings-export-start")
                    if isExporting {
                        HStack(spacing: .spacing3) {
                            ProgressView()
                            Text(AppStrings.exporting).font(.omSmall)
                        }
                    }
                }
                .padding(.spacing6)
            }
            if let statusMessage { status(statusMessage, color: Color.buttonPrimary) }
            if let errorMessage { status(errorMessage, color: Color.error) }
        }
        .fileExporter(
            isPresented: $showExporter,
            document: document,
            contentType: .json,
            defaultFilename: AppStrings.exportFilename
        ) { result in
            switch result {
            case .success:
                statusMessage = AppStrings.exportSuccess
            case .failure(let error):
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Account export save failed", category: "settings.account")
            }
            document = nil
        }
        .accessibilityIdentifier("settings-export-page")
    }

    private func prepareExport() {
        isExporting = true
        errorMessage = nil
        statusMessage = nil
        Task {
            do {
                document = AccountExportDocument(data: try await AccountSecurityService.shared.exportAccountData())
                showExporter = true
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Account export request failed", category: "settings.account")
            }
            isExporting = false
        }
    }

    private func status(_ message: String, color: Color) -> some View {
        Text(message).font(.omSmall).foregroundStyle(color).padding(.horizontal, .spacing6)
    }
}

private struct AccountExportDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.json] }
    let data: Data

    init(data: Data) { self.data = data }

    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else { throw CocoaError(.fileReadCorruptFile) }
        self.data = data
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }
}
