// Web source: frontend/packages/ui/src/components/chats/ChatSettingsShareSection.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift.
// First-party writes preserve account/server/scope fences. Keys and share URL
// fragments remain local; the short-link endpoint receives opaque ciphertext.
import CoreImage.CIFilterBuiltins
import CryptoKit
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

@MainActor
final class ChatSettingsShareModel: ObservableObject {
    @Published var community = false
    @Published var passwordEnabled = false
    @Published var password = ""
    @Published var expire = false
    @Published var generating = false
    @Published var url: URL?
    @Published var error: String?
    @Published var usedLongFallback = false

    func generate(chat: Chat, accountID: String?, preview: Bool = false) async {
        guard !generating else { return }
        guard !passwordEnabled || (!password.isEmpty && password.count <= 10) else { error = AppStrings.chatSettingsPasswordInvalid; return }
        generating = true; error = nil; usedLongFallback = false
        defer { generating = false }
        #if DEBUG
        if preview { url = URL(string: "https://example.invalid/share/chat/preview-chat-settings#key=preview"); return }
        #endif
        do {
            guard let accountID, let key = ChatKeyManager.shared.key(for: chat.id) else { throw UserTasksError.taskKeyUnavailable }
            let fence = UserTasksAccountFence(accountID: accountID)
            try await fence.check()
            guard let duration = ShareDuration(rawValue: expire ? 600 : 0) else { throw UserTasksError.invalidResponse }
            let blob = try await ShareLinkCrypto.encryptedShareBlob(identifier: chat.id, key: key, duration: duration,
                password: passwordEnabled ? password : nil, keyField: "chat_encryption_key")
            try await fence.check()
            let webURL = fence.serverProfile.webBaseURL
            let longURL = try ShareLinkCrypto.urlWithFragment(webURL.appendingPathComponent("share/chat").appendingPathComponent(chat.id), fragment: "key=\(blob)")
            let encrypted = try await ShareLinkCrypto.encryptedShortURL(longURL)
            try await fence.check()
            let shortBody: [String: Any] = ["token": encrypted.token, "encrypted_url": encrypted.encryptedURL,
                "content_type": "chat", "content_id": chat.id, "password_protected": passwordEnabled,
                "ttl_seconds": expire ? 600 : NSNull()]
            var generated = longURL
            do {
                let _: Data = try await shortLink(body: shortBody, fence: fence)
                generated = try ShareLinkCrypto.shortURL(webURL: webURL, token: encrypted.token, shortKey: encrypted.shortKey)
            } catch {
                try await fence.check()
                usedLongFallback = true
            }
            try await fence.check()
            let encryptedURL: Any = usedLongFallback ? NSNull() : try await CryptoManager.shared.encryptContent(generated.absoluteString, key: key)
            var metadata: [String: Any] = ["chat_id": chat.id, "title": chat.title as Any? ?? NSNull(),
                "summary": chat.chatSummary as Any? ?? NSNull(), "share_cta_text": (chat.chatSummary ?? chat.title) as Any? ?? NSNull(),
                "is_shared": true, "encrypted_shared_short_url": encryptedURL,
                "share_pii": community, "share_highlights": true]
            if community { metadata["share_with_community"] = true; metadata["share_link"] = generated.absoluteString }
            let _: Data = try await send("/v1/share/chat/metadata", body: metadata, fence: fence)
            try await fence.check()
            if let encryptedURL = encryptedURL as? String { UserDefaults.standard.set(encryptedURL, forKey: "share.url.\(chat.id)") }
            else { UserDefaults.standard.removeObject(forKey: "share.url.\(chat.id)") }
            url = generated
        } catch { self.error = AppStrings.chatSettingsShareFailed }
    }
    func stop(chatID: String, accountID: String?, preview: Bool = false) async {
        guard !generating else { return }
        #if DEBUG
        if preview { url = nil; return }
        #endif
        generating = true; error = nil
        defer { generating = false }
        do {
            guard let accountID else { throw UserTasksError.accountChanged }
            let fence = UserTasksAccountFence(accountID: accountID)
            let _: Data = try await send("/v1/share/chat/unshare", body: ["chat_id": chatID], fence: fence)
            try await fence.check()
            UserDefaults.standard.removeObject(forKey: "share.url.\(chatID)")
            url = nil
        } catch { self.error = AppStrings.chatSettingsStopFailed }
    }
    private func shortLink(body: [String: Any], fence: UserTasksAccountFence) async throws -> Data {
        // Match PRIMARY_SHORT_LINK_TIMEOUT_MS without transferring a dictionary
        // containing non-Sendable Any values into a child task.
        let payload = try JSONSerialization.data(withJSONObject: body)
        return try await withThrowingTaskGroup(of: Data.self) { group in
            group.addTask {
                try await fence.check()
                return try await APIClient.shared.request(.post, path: "/v1/share/short-url", serverProfile: fence.serverProfile,
                    body: JSONRawBody(data: payload), expectedAccountID: fence.accountID, expectedScope: fence.scope)
            }
            group.addTask { try await Task.sleep(for: .seconds(5)); throw URLError(.timedOut) }
            defer { group.cancelAll() }
            guard let result = try await group.next() else { throw UserTasksError.invalidResponse }
            try await fence.check()
            return result
        }
    }
    private func send(_ path: String, body: [String: Any], fence: UserTasksAccountFence) async throws -> Data {
        try await fence.check()
        let result: Data = try await APIClient.shared.request(.post, path: path, serverProfile: fence.serverProfile,
            body: JSONRawBody(data: JSONSerialization.data(withJSONObject: body)), expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        return result
    }
}

struct ChatSettingsShareSection: View {
    let chat: Chat
    let accountID: String?
    var shared = false
    var example = false
    var originalShareURL: URL?
    var preview = false
    let onDownload: (Bool) -> Void
    @StateObject private var model = ChatSettingsShareModel()
    @State private var showQR = false
    @State private var showURL = false
    @State private var copied = false
    @State private var qrImage: CGImage?
    @FocusState private var passwordFocused: Bool

    private var displayedURL: URL? {
        if example { return try? ShareLinkCrypto.urlWithFragment(ServerProfile.current().webBaseURL, fragment: "chat-id=\(chat.id)") }
        return shared ? originalShareURL : model.url
    }
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            if shared {
                ChatSettingsCard {
                    OMSettingsInfoBox(message: AppStrings.chatSettingsShareReadonly, identifier: "chat-settings-share-readonly")
                    if displayedURL == nil {
                        OMSettingsInfoBox(kind: .warning, message: AppStrings.chatSettingsLinkUnavailable, identifier: "chat-settings-share-link-unavailable")
                    }
                }
            }
            if let url = displayedURL {
                ChatSettingsCard {
                    if !shared && !example {
                        Text(AppStrings.chatSettingsShareCreated + " " + (model.expire ? AppStrings.chatSettingsTenMinutes : AppStrings.chatSettingsNever))
                            .font(.omSmall).foregroundStyle(Color.settingsSuccessAccent).accessibilityIdentifier("chat-settings-share-generated")
                    }
                    OMSettingsRow(title: copied ? AppStrings.shareLinkCopied : AppStrings.shareClickToCopy, icon: "copy", plainIcon: true, showsChevron: false, accessibilityIdentifier: "share-copy-link") { copy(url) }
                    OMSettingsRow(title: showQR ? AppStrings.chatSettingsHideQr : AppStrings.chatSettingsShowQr, icon: "camera", plainIcon: true, showsChevron: false, accessibilityIdentifier: showQR ? "chat-settings-share-hide-qr" : "chat-settings-share-show-qr") { showQR.toggle() }
                    if showQR, let qrImage {
                        Image(decorative: qrImage, scale: 1).resizable().interpolation(.none).scaledToFit()
                            .frame(maxWidth: 260, maxHeight: 260).padding(.spacing4).background(Color.white)
                            .frame(maxWidth: .infinity).accessibilityIdentifier("chat-settings-share-qr")
                    }
                    OMSettingsRow(title: showURL ? AppStrings.chatSettingsHideUrl : AppStrings.chatSettingsShowUrl, icon: "copy", plainIcon: true, showsChevron: false, accessibilityIdentifier: showURL ? "chat-settings-share-hide-url" : "chat-settings-share-show-url") { showURL.toggle() }
                    if showURL { Text(url.absoluteString).font(.omXs.monospaced()).foregroundStyle(Color.fontPrimary).textSelection(.enabled).accessibilityIdentifier("chat-settings-share-url") }
                    if model.usedLongFallback { Text(AppStrings.chatSettingsShortFallback).font(.omSmall).foregroundStyle(Color.fontSecondary).accessibilityIdentifier("share-short-link-error") }
                    if !shared && !example {
                        OMSettingsRow(title: AppStrings.chatSettingsStopSharing, icon: "delete", plainIcon: true, showsChevron: false, accessibilityIdentifier: "chat-settings-share-stop") {
                            Task { await model.stop(chatID: chat.id, accountID: accountID, preview: preview) }
                        }.disabled(model.generating)
                    }
                }
            } else if !shared {
                ChatSettingsCard(spacing: 0) {
                    ChatSettingsShareOption(title: AppStrings.chatSettingsCommunity, subtitle: AppStrings.chatSettingsCommunityDetail, icon: "share", isOn: $model.community, identifier: "chat-settings-share-community")
                    ChatSettingsShareOption(title: AppStrings.chatSettingsPassword, subtitle: AppStrings.chatSettingsPasswordDetail, icon: "key", isOn: $model.passwordEnabled, identifier: "chat-settings-share-password")
                    if model.passwordEnabled {
                        SecureField(AppStrings.sharePasswordPlaceholder, text: $model.password).textFieldStyle(OMTextFieldStyle())
                            .focused($passwordFocused)
                            .submitLabel(.done)
                            .onSubmit { passwordFocused = false }
                            .onChange(of: model.password) { _, value in if value.count > 10 { model.password = String(value.prefix(10)) } }
                            .accessibilityIdentifier("chat-settings-share-password-input")
                    }
                    ChatSettingsShareOption(title: AppStrings.chatSettingsAutoExpire, subtitle: AppStrings.chatSettingsExpireDetail, icon: "clock", isOn: $model.expire, identifier: "chat-settings-share-expire")
                    Button {
                        passwordFocused = false
                        Task { await model.generate(chat: chat, accountID: accountID, preview: preview) }
                    } label: {
                        Text(model.generating ? AppStrings.sharingChatStatus : AppStrings.shareChat)
                            .font(.omP.weight(.bold)).foregroundStyle(Color.fontButton).frame(maxWidth: .infinity).frame(height: 41)
                            .background(LinearGradient.primary).clipShape(Capsule()).shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                    }.buttonStyle(.plain).disabled(model.generating).accessibilityIdentifier("share-generate-link")
                }
                if model.generating { Text(AppStrings.sharingChatStatus).font(.omSmall).accessibilityIdentifier("share-generation-status") }
            }
            if let error = model.error { Text(error).font(.omSmall).foregroundStyle(Color.error).accessibilityIdentifier("share-error") }
            ChatSettingsCard {
                OMSettingsRow(title: AppStrings.chatSettingsDownloadChat, icon: "download", plainIcon: true, showsChevron: false, accessibilityIdentifier: "chat-settings-share-download-chat") { onDownload(false) }
                OMSettingsRow(title: AppStrings.chatSettingsDownloadZip, icon: "files", plainIcon: true, showsChevron: false, accessibilityIdentifier: "chat-settings-share-download-zip") { onDownload(true) }
            }
            if !shared && !example && model.url == nil {
                ChatSettingsCard {
                    HStack(spacing: .spacing4) {
                        Icon("chat", size: 22).foregroundStyle(LinearGradient.primary)
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text(chat.title ?? AppStrings.chat).font(.omP.weight(.semibold)).accessibilityIdentifier("chat-title")
                            Text(ChatSettingsProjection.summary(chat.chatSummary)).font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }.accessibilityIdentifier("share-chat-preview")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-settings-share-section")
        .onChange(of: model.passwordEnabled) { _, enabled in
            if !enabled { passwordFocused = false }
        }
        .onChange(of: displayedURL, initial: true) { _, url in
            guard let url else { qrImage = nil; showQR = false; showURL = false; return }
            let filter = CIFilter.qrCodeGenerator(); filter.message = Data(url.absoluteString.utf8); filter.correctionLevel = "M"
            qrImage = filter.outputImage.flatMap { let image = $0.transformed(by: CGAffineTransform(scaleX: 10, y: 10)); return CIContext().createCGImage(image, from: image.extent) }
        }
    }
    private func copy(_ url: URL) {
        #if os(iOS)
        UIPasteboard.general.string = url.absoluteString
        #elseif os(macOS)
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(url.absoluteString, forType: .string)
        #endif
        copied = true
        Task { try? await Task.sleep(for: .seconds(2)); copied = false }
    }
}

// SettingsItem quickaction toggle: 44-point gradient tile, subtitle ABOVE the
// bold primary-gradient title. Both title area and toggle are operable.
private struct ChatSettingsShareOption: View {
    let title: String
    let subtitle: String
    let icon: String
    @Binding var isOn: Bool
    let identifier: String
    var body: some View {
        HStack(spacing: .spacing6) {
            Button { isOn.toggle() } label: {
                HStack(spacing: .spacing6) {
                    Icon(icon, size: 22).foregroundStyle(LinearGradient.primary).frame(width: 44, height: 44)
                        .background(LinearGradient(colors: [Color.grey20, Color.grey30], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(subtitle).font(.omSmall.weight(.medium)).foregroundStyle(Color.grey60)
                        Text(title).font(.omP.weight(.bold)).foregroundStyle(LinearGradient.primary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }.contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityIdentifier(identifier + "-label")
            OMToggle(isOn: $isOn, accessibilityIdentifier: identifier).accessibilityLabel(title)
        }.padding(.vertical, .spacing2)
            .accessibilityElement(children: .contain).accessibilityIdentifier(identifier + "-row")
    }
}
