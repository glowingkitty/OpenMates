// Native API-key device management with approve and revoke actions.
// The current wrapped backend response is decoded without exposing encrypted names.
// Pending and approved states remain explicit and mutations surface failures.
// OpenMates settings primitives replace stock list, swipe, and symbol controls.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/developers/SettingsDevices.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsDevicesView: View {
    @State private var devices: [DeviceItem] = []
    @State private var isLoading = true
    @State private var pendingRevocation: DeviceItem?
    @State private var errorMessage: String?

    struct DeviceItem: Identifiable, Decodable {
        let id: String
        let anonymizedIp: String
        let countryCode: String?
        let region: String?
        let city: String?
        let approvedAt: String?
        let firstAccessAt: String?
        let lastAccessAt: String?
        let accessType: String
        let machineIdentifier: String?
    }
    private struct ListResponse: Decodable { let devices: [DeviceItem] }

    var body: some View {
        OMSettingsPage(title: AppStrings.devices, showsHeader: false) {
            if isLoading {
                ProgressView().frame(maxWidth: .infinity).padding(.spacing8)
            } else if devices.isEmpty {
                Text(L("settings.devices.no_devices"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.spacing6)
            } else {
                OMSettingsSection(AppStrings.devices) {
                    ForEach(devices) { device in
                        DeviceRow(device: device)
                        if device.approvedAt == nil {
                            OMSettingsRow(
                                title: L("settings.devices.approve"),
                                icon: "check",
                                showsChevron: false,
                                accessibilityIdentifier: "device-approve-\(device.id)"
                            ) { approveDevice(device.id) }
                        }
                        OMSettingsRow(
                            title: AppStrings.remove,
                            icon: "trash",
                            isDestructive: true,
                            showsChevron: false,
                            accessibilityIdentifier: "device-revoke-\(device.id)"
                        ) { pendingRevocation = device }
                    }
                }
            }
            if let errorMessage {
                Text(errorMessage).font(.omSmall).foregroundStyle(Color.error).padding(.spacing6)
            }
        }
        .task { await loadDevices() }
        .overlay {
            if let pendingRevocation {
                OMConfirmDialog(
                    title: AppStrings.remove,
                    message: L("settings.devices.revoke_confirm"),
                    confirmTitle: AppStrings.remove,
                    isDestructive: true,
                    onConfirm: { self.pendingRevocation = nil; revokeDevice(pendingRevocation.id) },
                    onCancel: { self.pendingRevocation = nil }
                )
            }
        }
    }

    private func loadDevices() async {
        isLoading = true
        do {
            let response: ListResponse = try await APIClient.shared.request(
                .get, path: "/v1/settings/api-key-devices"
            )
            devices = response.devices
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("API key device list failed", category: "settings.developer")
        }
        isLoading = false
    }

    private func approveDevice(_ id: String) {
        mutateDevice(id, action: "approve")
    }

    private func revokeDevice(_ id: String) {
        mutateDevice(id, action: "revoke")
    }

    private func mutateDevice(_ id: String, action: String) {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post,
                    path: "/v1/settings/api-key-devices/\(id)/\(action)",
                    body: EmptySettingsRequest()
                )
                await loadDevices()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("API key device mutation failed", category: "settings.developer")
            }
        }
    }
}

struct DeviceRow: View {
    let device: SettingsDevicesView.DeviceItem

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            HStack(spacing: .spacing3) {
                Icon(device.approvedAt == nil ? "warning" : "shield-check", size: 18)
                    .foregroundStyle(device.approvedAt == nil ? Color.warning : Color.buttonPrimary)
                Text(device.machineIdentifier ?? L("settings.sessions.unknown_device"))
                    .font(.omP.weight(.semibold))
            }
            Text(device.anonymizedIp).font(.omXs).foregroundStyle(Color.fontTertiary)
            if let city = device.city, let country = device.countryCode {
                Text("\(city), \(country)").font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            if let lastAccess = device.lastAccessAt {
                Text("\(L("settings.devices.last_access")): \(lastAccess)")
                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.horizontal, .spacing6)
        .padding(.vertical, .spacing5)
    }
}

private struct EmptySettingsRequest: Encodable {}

@MainActor
private func L(_ key: String) -> String { LocalizationManager.shared.text(key) }
