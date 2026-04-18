// Chat import — upload a ZIP file to import chats from export.
// Settings > Account > Import route.

import SwiftUI
#if os(iOS)
import UniformTypeIdentifiers
#endif

struct ChatImportView: View {
    @State private var isPickingFile = false
    @State private var importResult: ImportResult?
    @State private var isImporting = false
    @State private var error: String?

    struct ImportResult: Decodable {
        let chatCount: Int
        let messageCount: Int
        let status: String?
    }

    var body: some View {
        List {
            Section {
                Text(LocalizationManager.shared.text("settings.account.import_description"))
                    .foregroundStyle(Color.fontSecondary)
            }

            Section {
                Button {
                    isPickingFile = true
                } label: {
                    if isImporting {
                        HStack {
                            ProgressView()
                            Text(LocalizationManager.shared.text("settings.account.import_importing")).font(.omP)
                        }
                    } else {
                        Label("Select ZIP File", systemImage: "doc.zipper")
                    }
                }
                .disabled(isImporting)
            }

            if let result = importResult {
                Section("Import Complete") {
                    HStack {
                        Text(LocalizationManager.shared.text("settings.account.import_chats_selected"))
                        Spacer()
                        Text("\(result.chatCount)").foregroundStyle(Color.fontSecondary)
                    }
                    HStack {
                        Text(LocalizationManager.shared.text("settings.account.import_messages_imported"))
                        Spacer()
                        Text("\(result.messageCount)").foregroundStyle(Color.fontSecondary)
                    }
                }
            }

            if let error {
                Section {
                    Text(error).font(.omXs).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Import Chats")
        #if os(iOS)
        .sheet(isPresented: $isPickingFile) {
            DocumentPickerView { url in
                importFile(url)
            }
        }
        #endif
    }

    private func importFile(_ url: URL) {
        isImporting = true
        error = nil

        Task {
            do {
                let data = try Data(contentsOf: url)
                let boundary = UUID().uuidString
                var body = Data()
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(url.lastPathComponent)\"\r\n".data(using: .utf8)!)
                body.append("Content-Type: application/zip\r\n\r\n".data(using: .utf8)!)
                body.append(data)
                body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

                let apiURL = await APIClient.shared.baseURL.appendingPathComponent("/v1/settings/import-chat")
                var request = URLRequest(url: apiURL)
                request.httpMethod = "POST"
                request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
                request.httpBody = body

                let (responseData, _) = try await URLSession.shared.data(for: request)
                importResult = try JSONDecoder().decode(ImportResult.self, from: responseData)
                ToastManager.shared.show("Import complete!", type: .success)
            } catch {
                self.error = error.localizedDescription
            }
            isImporting = false
        }
    }
}
