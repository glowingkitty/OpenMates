// Device pairing — initiate pairing for new devices and authorize CLI login requests.
// Mirrors the web app's security/SettingsSessionsPairInitiate.svelte (initiate side)
// and security/SettingsSessionsConfirmPair.svelte (authorize side).
// The authorize flow uses PBKDF2-SHA256 + AES-256-GCM to encrypt the auth bundle.

import SwiftUI
import CryptoKit
import CoreImage.CIFilterBuiltins

// MARK: - Pair Initiate (start pairing from this device to add a new one)

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
                        CopyMessageFormatter.copyToClipboard(pairingCode)
                        ToastManager.shared.show("Code copied", type: .success)
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
                    Button("Generate Pairing Code") { generateCode() }
                        .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                }

                if isGenerating { ProgressView("Generating...") }

                if let error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
            .padding(.spacing8)
        }
        .navigationTitle("Pair Device")
    }

    private func generateCode() {
        isGenerating = true; error = nil
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/auth/pair/initiate",
                    body: ["device_hint": "ios_app"] as [String: String]
                )
                pairingCode = response["token"]?.value as? String
                expiresIn = response["expires_in"]?.value as? Int ?? 300
                if let code = pairingCode {
                    let pairURL = await APIClient.shared.webAppURL
                        .appendingPathComponent("pair")
                        .appending(queryItems: [URLQueryItem(name: "code", value: code)])
                    qrImage = generateQRCode(from: pairURL.absoluteString)
                }
                pollForPairing()
            } catch { self.error = error.localizedDescription }
            isGenerating = false
        }
    }

    private func pollForPairing() {
        guard let token = pairingCode else { return }
        Task {
            for _ in 0..<100 {
                try? await Task.sleep(for: .seconds(3))
                do {
                    let response: [String: AnyCodable] = try await APIClient.shared.request(
                        .get, path: "/v1/auth/pair/poll/\(token)"
                    )
                    let status = response["status"]?.value as? String
                    if status == "completed" { isPaired = true; return }
                } catch { break }
            }
        }
    }

    private func generateQRCode(from string: String) -> Image? {
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else { return nil }
        #if os(iOS)
        return Image(uiImage: UIImage(cgImage: cgImage))
        #elseif os(macOS)
        return Image(nsImage: NSImage(cgImage: cgImage, size: NSSize(width: 200, height: 200)))
        #endif
    }
}

// MARK: - CLI Pair Authorize (approve a CLI login request from this logged-in device)

struct CLIPairAuthorizeView: View {
    let token: String
    @EnvironmentObject var authManager: AuthManager
    @Environment(\.dismiss) var dismiss

    @State private var step: AuthorizeStep = .loading
    @State private var deviceInfo: DeviceInfo?
    @State private var generatedPIN: String?
    @State private var error: String?
    @State private var isAuthorizing = false

    enum AuthorizeStep {
        case loading, confirm, pinDisplay, completed, error
    }

    struct DeviceInfo {
        let name: String?
        let ip: String?
        let city: String?
        let country: String?
    }

    // PIN alphabet — excludes I, O, S, Z to avoid confusion (matches web app)
    private static let pinAlphabet = Array("ABCDEFGHJKLMNPQRTUVWXY3468")

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: .spacing6) {
                    switch step {
                    case .loading:
                        ProgressView("Loading device info...")
                    case .confirm:
                        confirmView
                    case .pinDisplay:
                        pinDisplayView
                    case .completed:
                        completedView
                    case .error:
                        errorView
                    }
                }
                .padding(.spacing8)
            }
            .navigationTitle("Authorize Device")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .task { await loadDeviceInfo() }
    }

    // MARK: - Step views

    private var confirmView: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "desktopcomputer.and.arrow.down")
                .font(.system(size: 48)).foregroundStyle(Color.buttonPrimary)

            Text("Login Request")
                .font(.omH2).fontWeight(.bold)

            Text("A device wants to log in to your account")
                .font(.omSmall).foregroundStyle(Color.fontSecondary)

            if let info = deviceInfo {
                VStack(alignment: .leading, spacing: .spacing3) {
                    if let name = info.name {
                        Label(name, systemImage: "desktopcomputer")
                            .font(.omSmall)
                    }
                    if let ip = info.ip {
                        Label(ip, systemImage: "network")
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    if let city = info.city, let country = info.country {
                        Label("\(city), \(country)", systemImage: "location")
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                }
                .padding(.spacing4)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
            }

            HStack(spacing: .spacing4) {
                Button("Deny") { dismiss() }
                    .buttonStyle(.bordered)

                Button {
                    authorizeDevice()
                } label: {
                    if isAuthorizing {
                        ProgressView()
                    } else {
                        Text("Allow")
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.buttonPrimary)
                .disabled(isAuthorizing)
            }

            Text("Only approve if you initiated this login.")
                .font(.omTiny).foregroundStyle(Color.fontTertiary)
        }
    }

    private var pinDisplayView: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "checkmark.shield.fill")
                .font(.system(size: 48)).foregroundStyle(.green)

            Text("Enter This PIN")
                .font(.omH2).fontWeight(.bold)

            Text("Enter this code on the requesting device to complete login.")
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            if let pin = generatedPIN {
                Text(pin)
                    .font(.system(size: 40, weight: .bold, design: .monospaced))
                    .foregroundStyle(Color.buttonPrimary)
                    .kerning(8)
                    .padding(.spacing6)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    .textSelection(.enabled)
            }

            Text("This PIN expires in 5 minutes.")
                .font(.omTiny).foregroundStyle(Color.fontTertiary)
        }
    }

    private var completedView: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 48)).foregroundStyle(.green)
            Text("Device Paired").font(.omH2).fontWeight(.bold)
            Text("The device has been successfully logged in.")
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
            Button("Done") { dismiss() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
        }
    }

    private var errorView: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 48)).foregroundStyle(Color.error)
            Text("Error").font(.omH2).fontWeight(.bold)
            if let error { Text(error).font(.omSmall).foregroundStyle(Color.error) }
            Button("Try Again") { Task { await loadDeviceInfo() } }
                .buttonStyle(.bordered)
        }
    }

    // MARK: - API calls

    private func loadDeviceInfo() async {
        step = .loading
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/auth/pair/info/\(token)"
            )
            deviceInfo = DeviceInfo(
                name: response["device_name"]?.value as? String,
                ip: response["anonymized_ip"]?.value as? String,
                city: response["city"]?.value as? String,
                country: response["country"]?.value as? String
            )
            step = .confirm
        } catch {
            self.error = error.localizedDescription
            step = .error
        }
    }

    private func authorizeDevice() {
        isAuthorizing = true
        Task {
            do {
                // Generate 6-char PIN
                let pin = generatePIN()
                generatedPIN = pin

                // Derive AES key from PIN using PBKDF2
                let salt = token.uppercased()
                let pinData = Data(pin.utf8)
                let saltData = Data(salt.utf8)
                let derivedKey = try deriveKey(from: pinData, salt: saltData)

                // Build auth bundle
                let bundle: [String: String] = [
                    "hashed_email": authManager.currentUser?.id ?? "",
                    "session_id": UUID().uuidString,
                ]
                let bundleJSON = try JSONSerialization.data(withJSONObject: bundle)

                // Encrypt with AES-256-GCM
                let symmetricKey = SymmetricKey(data: derivedKey)
                let sealedBox = try AES.GCM.seal(bundleJSON, using: symmetricKey)
                let encryptedBundle = sealedBox.ciphertext + sealedBox.tag
                let iv = sealedBox.nonce

                // Send to server
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/auth/pair/authorize/\(token)",
                    body: [
                        "encrypted_bundle": encryptedBundle.base64EncodedString(),
                        "iv": Data(iv).base64EncodedString(),
                        "pin": pin,
                        "device_name": deviceDisplayName(),
                    ]
                )

                step = .pinDisplay
                pollForCompletion()
            } catch {
                self.error = error.localizedDescription
                step = .error
            }
            isAuthorizing = false
        }
    }

    private func pollForCompletion() {
        Task {
            for _ in 0..<100 {
                try? await Task.sleep(for: .seconds(3))
                do {
                    let response: [String: AnyCodable] = try await APIClient.shared.request(
                        .get, path: "/v1/auth/pair/poll/\(token)"
                    )
                    let status = response["status"]?.value as? String
                    if status == "completed" {
                        step = .completed
                        return
                    }
                } catch { break }
            }
        }
    }

    // MARK: - Crypto helpers

    private func generatePIN() -> String {
        let alphabet = Self.pinAlphabet
        return String((0..<6).map { _ in alphabet.randomElement()! })
    }

    private func deriveKey(from password: Data, salt: Data) throws -> Data {
        // PBKDF2-SHA256 with 100,000 iterations, 32-byte output (AES-256)
        var derivedKey = Data(count: 32)
        let result = derivedKey.withUnsafeMutableBytes { derivedKeyBytes in
            password.withUnsafeBytes { passwordBytes in
                salt.withUnsafeBytes { saltBytes in
                    CCKeyDerivationPBKDF(
                        CCPBKDFAlgorithm(kCCPBKDF2),
                        passwordBytes.baseAddress, password.count,
                        saltBytes.baseAddress, salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256),
                        100_000,
                        derivedKeyBytes.baseAddress, 32
                    )
                }
            }
        }
        guard result == kCCSuccess else {
            throw NSError(domain: "PBKDF2", code: Int(result))
        }
        return derivedKey
    }

    private func deviceDisplayName() -> String {
        #if os(iOS)
        return UIDevice.current.name
        #elseif os(macOS)
        return Host.current().localizedName ?? "Mac"
        #endif
    }
}

// Need CommonCrypto for PBKDF2
import CommonCrypto

// MARK: - Confirm Pair (legacy simple code entry — kept for backward compat)

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
                        if isConfirming { ProgressView() } else { Text("Confirm Pairing").fontWeight(.medium) }
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
        isConfirming = true; error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/auth/pair/confirm",
                    body: ["pairing_code": pairingCode]
                )
                isSuccess = true
            } catch { self.error = error.localizedDescription }
            isConfirming = false
        }
    }
}
