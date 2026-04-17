// API key devices management — approve and revoke devices that use API keys.
// Mirrors the web app's developers/SettingsDevices.svelte.

import SwiftUI

struct SettingsDevicesView: View {
    @State private var devices: [DeviceItem] = []
    @State private var isLoading = true
    @State private var error: String?

    struct DeviceItem: Identifiable, Decodable {
        let id: String
        let apiKeyId: String?
        let anonymizedIp: String?
        let countryCode: String?
        let region: String?
        let city: String?
        let approvedAt: String?
        let firstAccessAt: String?
        let lastAccessAt: String?
        let accessType: String?
        let machineIdentifier: String?
        let deviceName: String?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if devices.isEmpty {
                Section {
                    Text("No devices have accessed your API keys yet.")
                        .foregroundStyle(Color.fontSecondary)
                }
            } else {
                ForEach(devices) { device in
                    DeviceRow(device: device)
                        .swipeActions {
                            Button(role: .destructive) {
                                revokeDevice(device.id)
                            } label: {
                                Label("Revoke", systemImage: "xmark.circle")
                            }
                        }
                }
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Devices")
        .task { await loadDevices() }
    }

    private func loadDevices() async {
        do {
            devices = try await APIClient.shared.request(
                .get, path: "/v1/settings/api-key-devices"
            )
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func revokeDevice(_ id: String) {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/api-key-devices/\(id)/revoke",
                    body: [:] as [String: String]
                )
                devices.removeAll { $0.id == id }
                ToastManager.shared.show("Device revoked", type: .success)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

// MARK: - Device row

struct DeviceRow: View {
    let device: SettingsDevicesView.DeviceItem

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            HStack {
                Text(device.deviceName ?? device.machineIdentifier ?? "Unknown Device")
                    .font(.omSmall).fontWeight(.medium)

                if device.approvedAt != nil {
                    Image(systemName: "checkmark.shield.fill")
                        .foregroundStyle(.green)
                        .font(.caption)
                }
            }

            HStack(spacing: .spacing3) {
                if let ip = device.anonymizedIp {
                    Text(ip)
                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                }

                if let city = device.city, let country = device.countryCode {
                    Text("\(city), \(country)")
                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                }
            }

            HStack(spacing: .spacing3) {
                if let accessType = device.accessType {
                    Text(accessType)
                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                        .padding(.horizontal, .spacing2)
                        .padding(.vertical, 2)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius1))
                }

                if let lastAccess = device.lastAccessAt {
                    Text("Last: \(lastAccess)")
                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                }
            }
        }
        .padding(.vertical, .spacing1)
    }
}
