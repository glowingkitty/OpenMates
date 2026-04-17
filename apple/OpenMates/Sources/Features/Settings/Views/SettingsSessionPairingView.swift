// Device pairing — initiate and confirm pairing of new devices/sessions.
// Mirrors the web app's security/SettingsSessionsPairInitiate.svelte and
// security/SettingsSessionsConfirmPair.svelte. Generates a QR code + pairing
// code on the initiating device; confirms the code on the new device.

import SwiftUI
import CoreImage.CIFilterBuiltins

// MARK: - Pair Initiate (existing device generates code)

struct SettingsPairInitiateView: View {
    @State private var pairingCode: String?
    @State private var qrImage: Image?
    @State private var isGenerating = false
    @State private var expiresIn: Int = 300
    @State private var error: String?
    @State private var isPaired = false

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text("Pair a New Device")
                    .font(.omH3).fontWeight(.bold)

                Text("Scan this QR code on your new device, or enter the pairing code manually.")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                if let qrImage {
                    qrImage
                        .interpolation(.none)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 200, height: 200)
                        .padding(.spacing4)
                        .background(Color.white)
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                }

                if let pairingCode {
                    VStack(spacing: .spacing2) {
                        Text("Pairing Code")
                            .font(.omXs).foregroundStyle(Color.fontTertiary)
                        Text(pairingCode)
                            .font(.system(size: 28, weight: .bold, design: .monospaced))
                            .foregroundStyle(Color.buttonPrimary)
                            .textSelection(.enabled)

                        Text("Expires in \(expiresIn / 60) minutes")
                            .font(.omTiny).foregroundStyle(Color.fontTertiary)
                    }

                    Button {
                        copyCode(pairingCode)
                    } label: {
                        Label("Copy Code", systemImage: "doc.on.doc")
                    }
                    .buttonStyle(.bordered)
                }

                if isPaired {
                    Label("Device paired successfully!", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                        .font(.omSmall).fontWeight(.medium)
                }

                if pairingCode == nil && !isGenerating {
                    Button("Generate Pairing Code") {
                        generateCode()
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.buttonPrimary)
                }

                if isGenerating {
                    ProgressView("Generating...")
                }

                if let error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
            .padding(.spacing8)
        }
        .navigationTitle("Pair Device")
    }

    private func generateCode() {
        isGenerating = true
        error = nil
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/auth/sessions/pair/initiate",
                    body: [:] as [String: String]
                )
                pairingCode = response["pairing_code"]?.value as? String
                expiresIn = response["expires_in"]?.value as? Int ?? 300

                if let code = pairingCode {
                    let pairURL = await APIClient.shared.webAppURL
                        .appendingPathComponent("pair")
                        .appending(queryItems: [URLQueryItem(name: "code", value: code)])
                    qrImage = generateQRCode(from: pairURL.absoluteString)
                }

                pollForPairing()
            } catch {
                self.error = error.localizedDescription
            }
            isGenerating = false
        }
    }

    private func pollForPairing() {
        Task {
            for _ in 0..<60 {
                try? await Task.sleep(for: .seconds(5))
                do {
                    let response: [String: AnyCodable] = try await APIClient.shared.request(
                        .get, path: "/v1/auth/sessions/pair/status"
                    )
                    if response["paired"]?.value as? Bool == true {
                        isPaired = true
                        return
                    }
                } catch { break }
            }
        }
    }

    private func generateQRCode(from string: String) -> Image? {
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"

        guard let outputImage = filter.outputImage else { return nil }
        let scaled = outputImage.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else { return nil }

        #if os(iOS)
        return Image(uiImage: UIImage(cgImage: cgImage))
        #elseif os(macOS)
        return Image(nsImage: NSImage(cgImage: cgImage, size: NSSize(width: 200, height: 200)))
        #endif
    }

    private func copyCode(_ code: String) {
        #if os(iOS)
        UIPasteboard.general.string = code
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(code, forType: .string)
        #endif
        ToastManager.shared.show("Code copied", type: .success)
    }
}

// MARK: - Confirm Pair (new device enters code)

struct SettingsConfirmPairView: View {
    @State private var pairingCode = ""
    @State private var isConfirming = false
    @State private var isSuccess = false
    @State private var error: String?

    var body: some View {
        Form {
            Section {
                Text("Enter the pairing code shown on your other device.")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }

            Section("Pairing Code") {
                TextField("Enter code", text: $pairingCode)
                    .font(.system(.body, design: .monospaced))
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.characters)
                    #endif
            }

            Section {
                Button {
                    confirmPairing()
                } label: {
                    HStack {
                        Spacer()
                        if isConfirming {
                            ProgressView()
                        } else {
                            Text("Confirm Pairing")
                                .fontWeight(.medium)
                        }
                        Spacer()
                    }
                }
                .disabled(pairingCode.count < 4 || isConfirming)
            }

            if isSuccess {
                Section {
                    Label("Device paired successfully!", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                }
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Confirm Pairing")
    }

    private func confirmPairing() {
        isConfirming = true
        error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/auth/sessions/pair/confirm",
                    body: ["pairing_code": pairingCode]
                )
                isSuccess = true
            } catch {
                self.error = error.localizedDescription
            }
            isConfirming = false
        }
    }
}
