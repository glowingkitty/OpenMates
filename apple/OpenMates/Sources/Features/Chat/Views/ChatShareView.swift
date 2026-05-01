// Chat sharing — generate encrypted shareable links with optional password and expiration.
// Mirrors SettingsShare.svelte: link generation, QR code, copy, password protection.

import SwiftUI
import CoreImage.CIFilterBuiltins

struct ChatShareView: View {
    let chatId: String

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
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                if let shareLink {
                    OMSettingsSection("Share Link") {
                        VStack(alignment: .leading, spacing: .spacing5) {
                            HStack(spacing: .spacing3) {
                                Text(shareLink)
                                    .font(.omXs.monospaced())
                                    .foregroundStyle(Color.fontPrimary)
                                    .lineLimit(2)
                                Spacer()
                                Button {
                                    copyToClipboard(shareLink)
                                    copied = true
                                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { copied = false }
                                } label: {
                                    Icon(copied ? "check" : "copy", size: 18)
                                        .foregroundStyle(copied ? Color.buttonPrimary : Color.buttonPrimary)
                                        .frame(width: 34, height: 34)
                                        .background(Color.grey10)
                                        .clipShape(RoundedRectangle(cornerRadius: .radius5))
                                }
                                .buttonStyle(.plain)
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
                        .padding(.spacing6)
                    }

                    Button {
                        shareViaSystem(shareLink)
                    } label: {
                        HStack {
                            Icon("share", size: 16)
                            Text("Share via...")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                } else {
                    OMSettingsSection("Options") {
                        VStack(alignment: .leading, spacing: .spacing5) {
                            Text("Expires after")
                                .font(.omSmall)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.fontSecondary)

                            OMSegmentedControl(
                                items: expirationOptions.map { .init(id: $0.0, title: $0.1) },
                                selection: $expirationHours
                            )

                            Button {
                                usePassword.toggle()
                            } label: {
                                HStack(spacing: .spacing3) {
                                    Icon(usePassword ? "check" : "close", size: 16)
                                        .foregroundStyle(usePassword ? Color.buttonPrimary : Color.fontTertiary)
                                    Text("Password protect")
                                        .font(.omSmall)
                                        .foregroundStyle(Color.fontPrimary)
                                    Spacer()
                                }
                            }
                            .buttonStyle(.plain)

                            if usePassword {
                                SecureField("Share password", text: $password)
                                    .textFieldStyle(OMTextFieldStyle())
                            }
                        }
                        .padding(.spacing6)
                    }

                    Button(action: generateLink) {
                        Text(isGenerating ? AppStrings.loading : "Generate Link")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(isGenerating || (usePassword && password.isEmpty))

                    if let error {
                        Text(error).font(.omXs).foregroundStyle(Color.error)
                    }
                }
            }
            .padding(.spacing8)
        }
        .background(Color.grey0)
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

    private func shareViaSystem(_ shareLink: String) {
        guard let url = URL(string: shareLink) else { return }
        #if os(iOS)
        let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
           let rootVC = scene.windows.first?.rootViewController {
            rootVC.present(activityVC, animated: true)
        }
        #endif
    }
}
