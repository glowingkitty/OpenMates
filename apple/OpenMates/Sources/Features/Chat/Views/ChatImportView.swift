// Native OpenMates YAML and ZIP chat import with safety-scanned server storage.
// Parses exported files on-device, previews aggregate counts, then submits only
// normalized chat/message fields to the real settings import endpoint.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsImportAccount.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import UniformTypeIdentifiers
import Yams
import ZIPFoundation

struct ChatImportView: View {
    @State private var showImporter = false
    @State private var chats: [ImportChat] = []
    @State private var result: ImportResponse?
    @State private var isImporting = false
    @State private var errorMessage: String?

    private var importTypes: [UTType] {
        [.zip] + ["yaml", "yml"].compactMap { UTType(filenameExtension: $0) }
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.importChats) {
            OMSettingsSection(AppStrings.importChats, icon: "upload") {
                VStack(alignment: .leading, spacing: .spacing5) {
                    Text(AppStrings.importDescription).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    Text(AppStrings.importSafetyNotice).font(.omXs).foregroundStyle(Color.fontTertiary)
                    Button(AppStrings.importChooseFile) { showImporter = true }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .disabled(isImporting)
                        .accessibilityIdentifier("settings-import-file")

                    if !chats.isEmpty {
                        OMSettingsStaticRow(title: AppStrings.chats, value: String(chats.count))
                        OMSettingsStaticRow(
                            title: AppStrings.importMessagesImported,
                            value: String(chats.reduce(0) { $0 + $1.messages.count })
                        )
                        Button(AppStrings.importChats) { submit() }
                            .buttonStyle(OMPrimaryButtonStyle())
                            .disabled(isImporting)
                            .accessibilityIdentifier("settings-import-submit")
                    }

                    if isImporting {
                        HStack(spacing: .spacing3) { ProgressView(); Text(AppStrings.importing).font(.omSmall) }
                    }
                }
                .padding(.spacing6)
            }

            if let result {
                OMSettingsSection(AppStrings.importSuccess, icon: "check") {
                    OMSettingsStaticRow(title: AppStrings.chats, value: String(result.imported.count))
                    OMSettingsStaticRow(title: AppStrings.importCreditsCharged, value: String(result.totalCreditsCharged))
                }
            }
            if let errorMessage {
                Text(errorMessage).font(.omSmall).foregroundStyle(Color.error).padding(.horizontal, .spacing6)
            }
        }
        .fileImporter(
            isPresented: $showImporter,
            allowedContentTypes: importTypes
        ) { selection in
            handleSelection(selection)
        }
        .accessibilityIdentifier("settings-import-page")
    }

    private func handleSelection(_ selection: Result<URL, Error>) {
        errorMessage = nil
        do {
            let url = try selection.get()
            let accessed = url.startAccessingSecurityScopedResource()
            defer { if accessed { url.stopAccessingSecurityScopedResource() } }
            chats = try parse(url: url)
            guard !chats.isEmpty else { throw ImportError.noChats }
        } catch {
            if let importError = error as? ImportError {
                errorMessage = importError == .invalidFormat
                    ? AppStrings.importInvalidFormat
                    : AppStrings.importNoChats
            } else {
                errorMessage = error.localizedDescription
            }
            NativeDiagnostics.error("Chat import parse failed", category: "settings.account")
        }
    }

    private func parse(url: URL) throws -> [ImportChat] {
        if url.pathExtension.lowercased() == "zip" {
            let archive = try Archive(url: url, accessMode: .read)
            return try archive.compactMap { entry in
                guard ["yaml", "yml"].contains(URL(fileURLWithPath: entry.path).pathExtension.lowercased()) else {
                    return nil
                }
                var data = Data()
                _ = try archive.extract(entry) { data.append($0) }
                return try parseYAML(data)
            }
        }
        return [try parseYAML(Data(contentsOf: url))]
    }

    private func parseYAML(_ data: Data) throws -> ImportChat {
        guard let yaml = String(data: data, encoding: .utf8),
              let root = try load(yaml: yaml) as? [String: Any],
              let metadata = root["chat"] as? [String: Any],
              let messages = root["messages"] as? [[String: Any]]
        else { throw ImportError.invalidFormat }
        return ImportChat(
            title: metadata["title"] as? String,
            draft: metadata["draft"] as? String,
            summary: metadata["summary"] as? String,
            messages: messages.compactMap(ImportMessage.init)
        )
    }

    private func submit() {
        isImporting = true
        errorMessage = nil
        Task {
            do {
                result = try await APIClient.shared.request(
                    .post,
                    path: "/v1/settings/import-chat",
                    body: ImportRequest(chats: chats)
                )
                chats = []
                AccessibilityAnnouncement.announce(AppStrings.importSuccess)
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Chat import request failed", category: "settings.account")
            }
            isImporting = false
        }
    }
}

private struct ImportRequest: Encodable { let chats: [ImportChat] }

private struct ImportChat: Encodable {
    let title: String?
    let draft: String?
    let summary: String?
    let messages: [ImportMessage]
}

private struct ImportMessage: Encodable {
    let role: String
    let content: String
    let completedAt: String?
    let assistantCategory: String?
    let thinking: String?
    let hasThinking: Bool?
    let thinkingTokens: Int?

    init?(_ source: [String: Any]) {
        guard let role = source["role"] as? String else { return nil }
        self.role = role
        content = source["content"] as? String ?? ""
        completedAt = source["completed_at"] as? String
        assistantCategory = source["assistant_category"] as? String
        thinking = source["thinking"] as? String
        hasThinking = source["has_thinking"] as? Bool
        thinkingTokens = source["thinking_tokens"] as? Int
    }
}

private struct ImportResponse: Decodable {
    let imported: [ImportedChat]
    let totalCreditsCharged: Int
}

private struct ImportedChat: Decodable {
    let chatId: String
    let title: String?
    let messagesImported: Int
    let messagesBlocked: Int
    let creditsCharged: Int
}

private enum ImportError: Error, Equatable {
    case invalidFormat
    case noChats
}
