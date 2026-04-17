// Chat sharing — generate encrypted shareable links with optional password and expiration.
// Mirrors SettingsShare.svelte: link generation, QR code, copy, password protection.

import SwiftUI
import CoreImage.CIFilterBuiltins

struct ChatShareView: View {
    let chatId: String
    @Environment(\.dismiss) var dismiss

    @State private var shareLink: String?
    @State private var password = ""
    @State private var usePassword = false
    @State private var expirationHours = 24
    @State private var isGenerating = false
    @State private var error: String?
    @State private var copied = false

    private let expirationOptions = [
        (1, "1 hour"), (6, "6 hours"), (24, "24 hours"),
        (72, "3 days"), (168, "1 week"), (720, "30 days")
    ]

    var body: some View {
        NavigationStack {
            Form {
                if let shareLink {
                    Section("Share Link") {
                        HStack {
                            Text(shareLink)
                                .font(.system(.caption, design: .monospaced))
                                .lineLimit(2)
                            Spacer()
                            Button {
                                copyToClipboard(shareLink)
                                copied = true
                                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { copied = false }
                            } label: {
                                Image(systemName: copied ? "checkmark" : "doc.on.doc")
                                    .foregroundStyle(copied ? .green : Color.buttonPrimary)
                            }
                        }

                        if let qrImage = generateQRCode(from: shareLink) {
                            HStack {
                                Spacer()
                                Image(decorative: qrImage, scale: 1.0)
                                    .interpolation(.none)
                                    .resizable()
                                    .frame(width: 200, height: 200)
                                Spacer()
                            }
                            .padding(.vertical, .spacing4)
                        }
                    }

                    Section {
                        Button {
                            let url = URL(string: shareLink)!
                            #if os(iOS)
                            let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
                            if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
                               let rootVC = scene.windows.first?.rootViewController {
                                rootVC.present(activityVC, animated: true)
                            }
                            #endif
                        } label: {
                            Label("Share via...", systemImage: SFSymbol.share2)
                        }
                    }
                } else {
                    Section("Options") {
                        Picker("Expires after", selection: $expirationHours) {
                            ForEach(expirationOptions, id: \.0) { hours, label in
                                Text(label).tag(hours)
                            }
                        }

                        Toggle("Password protect", isOn: $usePassword)
                            .tint(Color.buttonPrimary)

                        if usePassword {
                            SecureField("Share password", text: $password)
                        }
                    }

                    Section {
                        Button(action: generateLink) {
                            Group {
                                if isGenerating {
                                    ProgressView().tint(.fontButton)
                                } else {
                                    Label("Generate Link", systemImage: "link")
                                }
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(isGenerating || (usePassword && password.isEmpty))
                    }

                    if let error {
                        Text(error).font(.omXs).foregroundStyle(Color.error)
                    }
                }
            }
            .navigationTitle("Share Chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func generateLink() {
        isGenerating = true
        error = nil

        Task {
            do {
                var body: [String: Any] = [
                    "chat_id": chatId,
                    "expiration_hours": expirationHours
                ]
                if usePassword && !password.isEmpty {
                    body["password"] = password
                }

                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/chats/share", body: body
                )
                shareLink = response["share_url"]?.value as? String
            } catch {
                self.error = error.localizedDescription
            }
            isGenerating = false
        }
    }

    private func generateQRCode(from string: String) -> CGImage? {
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"

        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        return context.createCGImage(scaled, from: scaled.extent)
    }

    private func copyToClipboard(_ text: String) {
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
    }
}
