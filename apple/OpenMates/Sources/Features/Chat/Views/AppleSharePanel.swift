// Custom cross-platform chat and embed sharing panel.
// Mirrors the web SettingsShare two-step configuration and generated-link flow.
// The platform share sheet is intentionally invoked only after the user creates
// an encrypted link through this product-owned panel.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// CSS:     frontend/packages/ui/src/components/settings/share/SettingsShare.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CoreImage.CIFilterBuiltins
import CryptoKit
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct AppleShareContext {
    enum ContentType: String {
        case chat
        case embed
    }

    let contentType: ContentType
    let id: String
    let title: String
    let summary: String?
    let key: SymmetricKey
    let chatId: String?

    var isChat: Bool { contentType == .chat }
    var keyField: String { isChat ? "chat_encryption_key" : "embed_encryption_key" }
    var path: String { isChat ? "share/chat" : "share/embed" }
}

struct AppleSharePanel: View {
    private enum Constants {
        static let qrCodeSize: CGFloat = 200
        static let passwordMaximumLength = 10
    }

    let context: AppleShareContext
    let onClose: () -> Void
    let onGenerated: (URL, Bool, ShareDuration) async -> Void
    let onStopSharing: (() async -> Void)?

    @State private var password = ""
    @State private var passwordEnabled = false
    @State private var duration: ShareDuration = .noExpiration
    @State private var shareWithCommunity = false
    @State private var shareHighlights = false
    @State private var includeSensitiveData = false
    @State private var isGenerating = false
    @State private var generatedURL: URL?
    @State private var usedLongFallback = false
    @State private var copied = false
    @State private var showsQRFullscreen = false
    @State private var error: String?

    var body: some View {
        ZStack {
            ScrollView {
                VStack(alignment: .leading, spacing: .spacing6) {
                    if let generatedURL {
                        generatedLinkView(generatedURL)
                    } else {
                        configurationView
                    }
                }
                .padding(.spacing8)
            }
            .background(Color.grey0)

            if showsQRFullscreen, let generatedURL {
                qrFullscreen(url: generatedURL)
            }
        }
    }

    private var configurationView: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            preview

            Text(context.isChat ? AppStrings.shareDescription : AppStrings.shareEmbedDescription)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)

            Button(action: generateLink) {
                Text(isGenerating
                    ? (context.isChat ? AppStrings.sharingChatStatus : AppStrings.sharingEmbedStatus)
                    : (context.isChat ? AppStrings.shareChat : AppStrings.shareEmbed))
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(isGenerating || (passwordEnabled && password.isEmpty))
            .accessibilityIdentifier("share-generate-link")

            if isGenerating {
                Text(context.isChat ? AppStrings.sharingChatStatus : AppStrings.sharingEmbedStatus)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .accessibilityIdentifier("share-generation-status")
            }

            options

            if let error {
                Text(error)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .accessibilityIdentifier("share-error")
            }
        }
    }

    private var preview: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(context.isChat ? AppStrings.shareChat : AppStrings.shareEmbed)
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(Color.fontSecondary)
            HStack(spacing: .spacing4) {
                Icon(context.isChat ? "chat" : "embed", size: 20)
                    .foregroundStyle(LinearGradient.primary)
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(context.title)
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                        .lineLimit(2)
                    if let summary = context.summary, !summary.isEmpty {
                        Text(summary)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(2)
                    }
                }
                Spacer(minLength: .spacing2)
            }
            .padding(.spacing5)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius6))
        }
        .accessibilityIdentifier(context.isChat ? "share-chat-preview" : "share-embed-preview")
    }

    private var options: some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            Text(AppStrings.optionalShareSettings)
                .font(.omP.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)

            if context.isChat {
                optionRow(AppStrings.shareCommunity, icon: "shared", isOn: $shareWithCommunity, identifier: "share-community-toggle")
                optionRow(AppStrings.shareHighlights, icon: "shared", isOn: $shareHighlights, identifier: "share-highlights-toggle")
                optionRow(AppStrings.shareSensitiveData, icon: "lock", isOn: $includeSensitiveData, identifier: "share-sensitive-data-toggle")
            }

            optionRow(AppStrings.sharePasswordProtection, icon: "lock", isOn: $passwordEnabled, identifier: "share-password-toggle")
            if passwordEnabled {
                SecureField(AppStrings.sharePasswordPlaceholder, text: $password)
                    .textFieldStyle(OMTextFieldStyle())
                    .onChange(of: password) { _, value in
                        if value.count > Constants.passwordMaximumLength {
                            password = String(value.prefix(Constants.passwordMaximumLength))
                        }
                    }
                    .accessibilityIdentifier("share-password-field")
            }

            Text(AppStrings.shareTimeLimit)
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: .spacing2) {
                ForEach(ShareDuration.allCases) { option in
                    Button {
                        duration = option
                    } label: {
                        Text(durationLabel(option))
                            .font(.omXs.weight(duration == option ? .semibold : .regular))
                            .foregroundStyle(duration == option ? Color.fontButton : Color.fontPrimary)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, .spacing3)
                            .background(duration == option ? Color.buttonPrimary : Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("duration-option")
                }
            }
        }
        .padding(.spacing5)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
        .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey20, lineWidth: 1))
        .accessibilityIdentifier("share-options-section")
    }

    private func optionRow(_ title: String, icon: String, isOn: Binding<Bool>, identifier: String) -> some View {
        HStack(spacing: .spacing4) {
            Icon(icon, size: 18)
                .foregroundStyle(Color.fontSecondary)
            Text(title)
                .font(.omSmall)
                .foregroundStyle(Color.fontPrimary)
            Spacer(minLength: .spacing2)
            OMToggle(isOn: isOn)
                .accessibilityIdentifier(identifier)
        }
    }

    private func generatedLinkView(_ url: URL) -> some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            preview
            Button {
                copy(url)
            } label: {
                HStack(spacing: .spacing3) {
                    Icon(copied ? "check" : "copy", size: 18)
                    Text(copied ? AppStrings.shareLinkCopied : AppStrings.shareClickToCopy)
                    Spacer()
                }
                .padding(.spacing5)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius6))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("share-copy-link")

            Text(url.absoluteString)
                .font(.omXs.monospaced())
                .foregroundStyle(Color.fontSecondary)
                .textSelection(.enabled)
                .accessibilityIdentifier("share-short-link-url")

            if usedLongFallback {
                Text(AppStrings.error)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .accessibilityIdentifier("share-short-link-error")
            }

            if duration != .noExpiration {
                Text("\(AppStrings.shareExpirationPrefix) \(durationLabel(duration))")
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("share-expiration-info")
            }

            qrCode(url)

            Button(action: shareViaSystem) {
                HStack {
                    Icon("share", size: 18)
                    Text(AppStrings.share)
                    Spacer()
                }
            }
            .buttonStyle(OMSecondaryButtonStyle())
            .accessibilityIdentifier("share-native-sheet-button")

            Button(action: resetConfiguration) {
                Text(AppStrings.shareChangeSettings)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMSecondaryButtonStyle())
            .accessibilityIdentifier("share-back-to-config")

            if context.isChat, let onStopSharing {
                Button {
                    Task {
                        await onStopSharing()
                        resetConfiguration()
                    }
                } label: {
                    Text(AppStrings.shareUnshare)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(OMSecondaryButtonStyle())
                .accessibilityIdentifier("share-stop-sharing")
            }
        }
    }

    private func qrCode(_ url: URL) -> some View {
        VStack(spacing: .spacing3) {
            Text(AppStrings.shareQRCode)
                .font(.omP.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
            if let image = qrImage(url) {
                Button { showsQRFullscreen = true } label: {
                    Image(decorative: image, scale: 1)
                        .interpolation(.none)
                        .resizable()
                        .frame(width: Constants.qrCodeSize, height: Constants.qrCodeSize)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("share-qr-code")
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func qrFullscreen(url: URL) -> some View {
        ZStack {
            Color.grey0.ignoresSafeArea()
                .onTapGesture { showsQRFullscreen = false }
            if let image = qrImage(url) {
                Image(decorative: image, scale: 1)
                    .interpolation(.none)
                    .resizable()
                    .scaledToFit()
                    .padding(.spacing10)
            }
        }
        .accessibilityIdentifier("share-qr-fullscreen")
    }

    private func generateLink() {
        guard !isGenerating, !(passwordEnabled && password.isEmpty) else { return }
        if let value = ProcessInfo.processInfo.environment["UI_TEST_CHAT_SHARE_URL"],
           let fixtureURL = URL(string: value), context.isChat {
            generatedURL = fixtureURL
            usedLongFallback = false
            return
        }
        isGenerating = true
        error = nil
        Task {
            defer { isGenerating = false }
            do {
                let blob = try await ShareLinkCrypto.encryptedShareBlob(
                    identifier: context.id,
                    key: context.key,
                    duration: duration,
                    password: passwordEnabled ? password : nil,
                    keyField: context.keyField
                )
                let webURL = await APIClient.shared.webAppURL
                let longURL = try ShareLinkCrypto.urlWithFragment(
                    webURL
                        .appendingPathComponent(context.path)
                        .appendingPathComponent(context.id),
                    fragment: "key=\(blob)"
                )
                let primaryURL = try await durableShortURL(for: longURL, webURL: webURL)
                generatedURL = primaryURL.url
                usedLongFallback = primaryURL.usedLongFallback
                await onGenerated(primaryURL.url, usedLongFallback, duration)
            } catch {
                self.error = AppStrings.error
                NativeDiagnostics.error("Share link generation failed", category: "sharing")
            }
        }
    }

    private func durableShortURL(for longURL: URL, webURL: URL) async throws -> (url: URL, usedLongFallback: Bool) {
        do {
            let encrypted = try await ShareLinkCrypto.encryptedShortURL(longURL)
            let body: [String: Any] = [
                "token": encrypted.token,
                "encrypted_url": encrypted.encryptedURL,
                "content_type": context.contentType.rawValue,
                "content_id": context.id,
                "password_protected": passwordEnabled,
                "ttl_seconds": duration == .noExpiration ? NSNull() : duration.rawValue
            ]
            let _: Data = try await APIClient.shared.request(.post, path: "/v1/share/short-url", body: body)
            return (try ShareLinkCrypto.shortURL(webURL: webURL, token: encrypted.token, shortKey: encrypted.shortKey), false)
        } catch let error as URLError where error.code == .notConnectedToInternet || error.code == .timedOut {
            return (longURL, true)
        }
    }

    private func resetConfiguration() {
        generatedURL = nil
        usedLongFallback = false
        copied = false
        error = nil
    }

    private func copy(_ url: URL) {
        #if os(iOS)
        UIPasteboard.general.string = url.absoluteString
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url.absoluteString, forType: .string)
        #endif
        copied = true
        Task {
            try? await Task.sleep(for: .seconds(2))
            copied = false
        }
    }

    private func shareViaSystem() {
        guard let url = generatedURL else { return }
        #if os(iOS)
        let activity = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let presenter = scene.windows.first(where: \.isKeyWindow)?.rootViewController else { return }
        presenter.present(activity, animated: true)
        #elseif os(macOS)
        let picker = NSSharingServicePicker(items: [url])
        picker.show(relativeTo: .zero, of: NSApp.keyWindow?.contentView ?? NSView(), preferredEdge: .minY)
        #endif
    }

    private func qrImage(_ url: URL) -> CGImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(url.absoluteString.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        return CIContext().createCGImage(scaled, from: scaled.extent)
    }

    private func durationLabel(_ option: ShareDuration) -> String {
        switch option {
        case .noExpiration: AppStrings.shareNoExpiration
        case .oneMinute: AppStrings.shareOneMinute
        case .oneHour: AppStrings.shareOneHour
        case .twentyFourHours: AppStrings.shareTwentyFourHours
        case .sevenDays: AppStrings.shareSevenDays
        case .fourteenDays: AppStrings.shareFourteenDays
        case .thirtyDays: AppStrings.shareThirtyDays
        case .ninetyDays: AppStrings.shareNinetyDays
        }
    }
}
