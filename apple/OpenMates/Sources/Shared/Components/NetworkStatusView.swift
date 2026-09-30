// Network status indicator — shows connection state at top of screen.
// Mirrors networkStatusStore.ts: offline banner, reconnecting indicator.

import SwiftUI
import Network

@MainActor
final class NetworkMonitor: ObservableObject {
    @Published var isConnected = true
    @Published var connectionType: NWInterface.InterfaceType?

    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "NetworkMonitor")

    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.isConnected = path.status == .satisfied
                self?.connectionType = path.availableInterfaces.first?.type
            }
        }
        monitor.start(queue: queue)
    }

    deinit {
        monitor.cancel()
    }
}

// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/OfflineBanner.svelte
//         frontend/packages/ui/src/components/Notification.svelte
//         frontend/packages/ui/src/components/NotificationStack.svelte
// ────────────────────────────────────────────────────────────────────
struct NetworkStatusBanner: View {
    static let reconnectDelayNanoseconds: UInt64 = 1_500_000_000
    @StateObject private var networkMonitor = NetworkMonitor()
    @ObservedObject var wsManager: WebSocketManager
    @State private var showReconnectBanner = false
    @State private var reconnectBannerTask: Task<Void, Never>?
    private static let notificationKey = "network-connection-status"

    var body: some View {
        // Connection state contributes to the production notification store.
        // The shell's existing ToastOverlay renders it in the same keyed stack.
        Color.clear.frame(width: 0, height: 0)
            .allowsHitTesting(false)
            .onAppear {
                scheduleReconnectBanner(for: wsManager.connectionState)
                updateNotification()
            }
            .onChange(of: networkMonitor.isConnected) { _, _ in updateNotification() }
            .onChange(of: showReconnectBanner) { _, _ in updateNotification() }
            .onChange(of: wsManager.connectionState) { _, newState in
                scheduleReconnectBanner(for: newState)
                updateNotification()
            }
            .onDisappear {
                reconnectBannerTask?.cancel()
                ToastManager.shared.dismiss(dedupeKey: Self.notificationKey)
            }
    }

    private func updateNotification() {
        let manager = ToastManager.shared
        if !networkMonitor.isConnected {
            manager.show(AppStrings.offlineBanner, type: .connection, duration: 0,
                title: AppStrings.offlineNotificationTitle, dedupeKey: Self.notificationKey)
        } else if case .reconnecting = wsManager.connectionState, showReconnectBanner {
            manager.show(AppStrings.reconnectingBanner, type: .connection, duration: 0,
                title: AppStrings.reconnectingBanner, isProcessing: true, dedupeKey: Self.notificationKey)
        } else {
            manager.dismiss(dedupeKey: Self.notificationKey)
        }
    }

    private func scheduleReconnectBanner(for state: WebSocketManager.ConnectionState) {
        reconnectBannerTask?.cancel()
        guard case .reconnecting = state else { showReconnectBanner = false; return }
        reconnectBannerTask = Task {
            do { try await Task.sleep(nanoseconds: Self.reconnectDelayNanoseconds) } catch { return }
            guard !Task.isCancelled else { return }
            if case .reconnecting = wsManager.connectionState { showReconnectBanner = true }
        }
    }
}
