// Developer settings for native API-key, device, and webhook management.
// Secret material is generated and encrypted on-device and revealed only once.
// Lists decode the backend's current wrapped responses and expose explicit failures.
// Product navigation and destructive confirmation use OpenMates primitives.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsDevelopers.svelte
//          frontend/packages/ui/src/components/settings/developers/SettingsApiKeys.svelte
//          frontend/packages/ui/src/components/settings/developers/SettingsDevices.svelte
//          frontend/packages/ui/src/components/settings/developers/SettingsWebhooks.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CryptoKit
import Security
import SwiftUI

struct SettingsDeveloperView: View {
    @State private var destination: Destination?

    var body: some View {
        if let destination {
            VStack(spacing: 0) {
                OMSettingsRow(
                    title: AppStrings.back,
                    icon: "back",
                    showsChevron: false,
                    accessibilityIdentifier: "settings-developers-back"
                ) { self.destination = nil }
                destination.view
            }
            .background(Color.grey0)
        } else {
            OMSettingsPage(title: AppStrings.settingsDevelopers, showsHeader: false) {
                OMSettingsSection {
                    developerRow(.apiKeys, title: AppStrings.apiKeys, icon: "key")
                    developerRow(.devices, title: AppStrings.devices, icon: "devices")
                    developerRow(.webhooks, title: AppStrings.webhooks, icon: "link")
                }
            }
            .accessibilityIdentifier("settings-developers-page")
        }
    }

    private func developerRow(_ value: Destination, title: String, icon: String) -> some View {
        OMSettingsRow(title: title, icon: icon, accessibilityIdentifier: value.identifier) {
            destination = value
        }
    }

    private enum Destination {
        case apiKeys, devices, webhooks

        var identifier: String {
            switch self {
            case .apiKeys: return "settings-developers-api-keys-row"
            case .devices: return "settings-developers-devices-row"
            case .webhooks: return "settings-developers-webhooks-row"
            }
        }

        @MainActor @ViewBuilder var view: some View {
            switch self {
            case .apiKeys: SettingsAPIKeysView()
            case .devices: SettingsDevicesView()
            case .webhooks: SettingsWebhooksView()
            }
        }
    }
}

struct SettingsAPIKeysView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var apiKeys: [APIKeyItem] = []
    @State private var displayNames: [String: String] = [:]
    @State private var displayPrefixes: [String: String] = [:]
    @State private var newName = ""
    @State private var createdKey: String?
    @State private var pendingRevocation: APIKeyItem?
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var errorMessage: String?

    struct APIKeyItem: Identifiable, Decodable {
        let id: String
        let encryptedName: String?
        let encryptedKeyPrefix: String?
        let createdAt: String?
        let lastUsedAt: String?
    }

    private struct ListResponse: Decodable { let apiKeys: [APIKeyItem] }

    var body: some View {
        OMSettingsPage(title: AppStrings.apiKeys, showsHeader: false) {
            if isLoading {
                ProgressView().frame(maxWidth: .infinity).padding(.spacing8)
            } else {
                OMSettingsSection(AppStrings.apiKeys) {
                    ForEach(apiKeys) { key in
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text(displayNames[key.id] ?? L("settings.api_keys.unknown"))
                                .font(.omP.weight(.semibold))
                            Text(displayPrefixes[key.id] ?? L("settings.api_keys.unknown"))
                                .font(.omSmall.monospaced())
                                .foregroundStyle(Color.fontSecondary)
                            if let lastUsedAt = key.lastUsedAt {
                                Text("\(L("settings.developer.last_used")): \(lastUsedAt)")
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                        OMSettingsRow(
                            title: AppStrings.remove,
                            icon: "trash",
                            isDestructive: true,
                            showsChevron: false,
                            accessibilityIdentifier: "api-key-revoke-\(key.id)"
                        ) { pendingRevocation = key }
                    }
                }
            }

            OMSettingsSection(L("settings.api_keys.create")) {
                VStack(alignment: .leading, spacing: .spacing5) {
                    TextField(L("settings.api_keys.name"), text: $newName)
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityIdentifier("api-key-name-input")
                    Button(L("settings.api_keys.create")) { createKey() }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
                        .accessibilityIdentifier("api-key-create-button")
                }
                .padding(.spacing6)
            }

            if let createdKey {
                OMSettingsSection(L("settings.api_keys.save_key_warning")) {
                    Text(createdKey)
                        .font(.omP.monospaced())
                        .textSelection(.enabled)
                        .padding(.spacing6)
                        .accessibilityIdentifier("api-key-created-secret")
                }
            }
            errorView(errorMessage)
        }
        .task { await loadKeys() }
        .overlay {
            if let pendingRevocation {
                OMConfirmDialog(
                    title: AppStrings.remove,
                    message: L("settings.api_keys.revoke_confirm"),
                    confirmTitle: AppStrings.remove,
                    isDestructive: true,
                    onConfirm: { self.pendingRevocation = nil; revokeKey(pendingRevocation.id) },
                    onCancel: { self.pendingRevocation = nil }
                )
            }
        }
    }

    private func loadKeys() async {
        isLoading = true
        do {
            let response: ListResponse = try await APIClient.shared.request(.get, path: "/v1/settings/api-keys")
            apiKeys = response.apiKeys
            try await decryptDisplayFields(response.apiKeys)
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("API key list failed", category: "settings.developer")
        }
        isLoading = false
    }

    private func decryptDisplayFields(_ keys: [APIKeyItem]) async throws {
        guard let user = authManager.currentUser,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id) else {
            throw APIError.invalidResponse
        }
        var names: [String: String] = [:]
        var prefixes: [String: String] = [:]
        for key in keys {
            if let value = key.encryptedName {
                names[key.id] = try await CryptoManager.shared.decryptContent(base64String: value, key: masterKey)
            }
            if let value = key.encryptedKeyPrefix {
                prefixes[key.id] = try await CryptoManager.shared.decryptContent(base64String: value, key: masterKey)
            }
        }
        displayNames = names
        displayPrefixes = prefixes
    }

    private func createKey() {
        isSaving = true
        errorMessage = nil
        createdKey = nil
        Task {
            do {
                guard let user = authManager.currentUser,
                      let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id) else {
                    throw APIError.invalidResponse
                }
                let rawKey = "sk-api-\(Self.randomToken(length: 32))"
                let salt = Self.randomData(count: 16)
                let wrappingKey = await CryptoManager.shared.deriveWrappingKeyFromPassword(password: rawKey, salt: salt)
                let wrapped = try await CryptoManager.shared.encrypt(masterKey.withUnsafeBytes { Data($0) }, using: wrappingKey)
                let name = newName.trimmingCharacters(in: .whitespacesAndNewlines)
                let prefix = String(rawKey.prefix(12)) + "..."
                let _: APIKeyItem = try await APIClient.shared.request(
                    .post,
                    path: "/v1/settings/api-keys",
                    body: APIKeyCreateRequest(
                        encryptedName: try await CryptoManager.shared.encryptWithMasterKey(name, masterKey: masterKey),
                        apiKeyHash: Self.sha256Hex(rawKey),
                        encryptedKeyPrefix: try await CryptoManager.shared.encryptWithMasterKey(prefix, masterKey: masterKey),
                        encryptedMasterKey: wrapped.ciphertext.base64EncodedString(),
                        salt: salt.base64EncodedString(),
                        keyIv: wrapped.nonce.base64EncodedString(),
                        fullAccess: true,
                        scopes: APIKeyScopes(),
                        expiresAt: nil
                    )
                )
                createdKey = rawKey
                newName = ""
                await loadKeys()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("API key creation failed", category: "settings.developer")
            }
            isSaving = false
        }
    }

    private func revokeKey(_ id: String) {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(.delete, path: "/v1/settings/api-keys/\(id)")
                await loadKeys()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("API key revocation failed", category: "settings.developer")
            }
        }
    }

    fileprivate static func randomData(count: Int) -> Data {
        var bytes = [UInt8](repeating: 0, count: count)
        let status = SecRandomCopyBytes(kSecRandomDefault, count, &bytes)
        precondition(status == errSecSuccess, "Secure random generation failed")
        return Data(bytes)
    }

    fileprivate static func randomToken(length: Int) -> String {
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
        return String(randomData(count: length).map { alphabet[Int($0) % alphabet.count] })
    }

    fileprivate static func sha256Hex(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

private struct APIKeyCreateRequest: Encodable {
    let encryptedName: String
    let apiKeyHash: String
    let encryptedKeyPrefix: String
    let encryptedMasterKey: String
    let salt: String
    let keyIv: String
    let fullAccess: Bool
    let scopes: APIKeyScopes
    let expiresAt: String?
}

private struct APIKeyScopes: Encodable {
    let chat = ["chat:create_incognito", "chat:create_saved", "chat:read_existing", "chat:append_existing", "chat:delete", "chat:share"]
    let memories = ["memory:read"]
    let apps = APIKeyAppScopes()
}

private struct APIKeyAppScopes: Encodable {
    let mode = "all"
    let allowedSkills: [String] = []
    let allowedApps: [String] = []
}

struct SettingsWebhooksView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var webhooks: [WebhookItem] = []
    @State private var names: [String: String] = [:]
    @State private var newName = ""
    @State private var createdSecret: String?
    @State private var pendingDeletion: WebhookItem?
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var errorMessage: String?

    struct WebhookItem: Identifiable, Decodable {
        let id: String
        let encryptedName: String?
        let isActive: Bool
        let lastUsedAt: String?
    }
    private struct ListResponse: Decodable { let webhooks: [WebhookItem] }

    var body: some View {
        OMSettingsPage(title: AppStrings.webhooks, showsHeader: false) {
            if isLoading { ProgressView().frame(maxWidth: .infinity).padding(.spacing8) }
            else if webhooks.isEmpty { errorView(L("settings.developers_webhooks_empty")) }
            else {
                OMSettingsSection(AppStrings.webhooks) {
                    ForEach(webhooks) { webhook in
                        OMSettingsStaticRow(
                            title: names[webhook.id] ?? L("settings.api_keys.unknown"),
                            value: webhook.isActive ? AppStrings.enabled : AppStrings.disabled
                        )
                        OMSettingsRow(
                            title: AppStrings.remove,
                            icon: "trash",
                            isDestructive: true,
                            showsChevron: false,
                            accessibilityIdentifier: "webhook-delete-\(webhook.id)"
                        ) { pendingDeletion = webhook }
                    }
                }
            }

            OMSettingsSection(L("settings.developers_webhooks_create")) {
                VStack(alignment: .leading, spacing: .spacing5) {
                    TextField(L("settings.developers_webhooks_name"), text: $newName)
                        .textFieldStyle(OMTextFieldStyle())
                    Button(L("settings.developers_webhooks_create")) { createWebhook() }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
                }
                .padding(.spacing6)
            }
            if let createdSecret {
                Text(createdSecret).font(.omP.monospaced()).textSelection(.enabled).padding(.spacing6)
            }
            errorView(errorMessage)
        }
        .task { await loadWebhooks() }
        .overlay {
            if let pendingDeletion {
                OMConfirmDialog(
                    title: AppStrings.remove,
                    message: L("settings.developers_webhooks_delete_confirm"),
                    confirmTitle: AppStrings.remove,
                    isDestructive: true,
                    onConfirm: { self.pendingDeletion = nil; deleteWebhook(pendingDeletion.id) },
                    onCancel: { self.pendingDeletion = nil }
                )
            }
        }
    }

    private func loadWebhooks() async {
        isLoading = true
        do {
            let response: ListResponse = try await APIClient.shared.request(.get, path: "/v1/webhooks")
            webhooks = response.webhooks
            guard let user = authManager.currentUser,
                  let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id) else {
                throw APIError.invalidResponse
            }
            var values: [String: String] = [:]
            for webhook in response.webhooks where webhook.encryptedName != nil {
                values[webhook.id] = try await CryptoManager.shared.decryptContent(
                    base64String: webhook.encryptedName!, key: masterKey
                )
            }
            names = values
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Webhook list failed", category: "settings.developer")
        }
        isLoading = false
    }

    private func createWebhook() {
        isSaving = true
        Task {
            do {
                guard let user = authManager.currentUser,
                      let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id) else {
                    throw APIError.invalidResponse
                }
                let secret = "wh-\(SettingsAPIKeysView.randomToken(length: 64))"
                let prefix = String(secret.prefix(12)) + "..."
                let _: WebhookItem = try await APIClient.shared.request(
                    .post,
                    path: "/v1/webhooks",
                    body: WebhookCreateRequest(
                        encryptedName: try await CryptoManager.shared.encryptWithMasterKey(newName, masterKey: masterKey),
                        webhookKeyHash: SettingsAPIKeysView.sha256Hex(secret),
                        encryptedKeyPrefix: try await CryptoManager.shared.encryptWithMasterKey(prefix, masterKey: masterKey),
                        direction: "incoming",
                        permissions: ["trigger_chat"],
                        requireConfirmation: false,
                        messageTemplate: "{{payload_json}}",
                        rateLimitCount: 3,
                        rateLimitPeriod: "hour"
                    )
                )
                createdSecret = secret
                newName = ""
                await loadWebhooks()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Webhook creation failed", category: "settings.developer")
            }
            isSaving = false
        }
    }

    private func deleteWebhook(_ id: String) {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(.delete, path: "/v1/webhooks/\(id)")
                await loadWebhooks()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Webhook deletion failed", category: "settings.developer")
            }
        }
    }
}

private struct WebhookCreateRequest: Encodable {
    let encryptedName: String
    let webhookKeyHash: String
    let encryptedKeyPrefix: String
    let direction: String
    let permissions: [String]
    let requireConfirmation: Bool
    let messageTemplate: String
    let rateLimitCount: Int
    let rateLimitPeriod: String
}

@ViewBuilder
private func errorView(_ message: String?) -> some View {
    if let message {
        Text(message)
            .font(.omSmall)
            .foregroundStyle(Color.error)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.spacing6)
    }
}

@MainActor
private func L(_ key: String) -> String { LocalizationManager.shared.text(key) }
