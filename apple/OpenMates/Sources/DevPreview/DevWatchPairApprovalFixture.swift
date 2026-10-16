#if DEBUG && os(iOS)
// Production approval UI and bridge; fictional transport only. No WC/APNs,
// backend PAKE, authenticated session, Keychain or reusable credentials are seeded.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.pairing.iphone-first-fallback, apple-watch.pairing.private-session
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/settings/security/SettingsSessionsConfirmPair.svelte
//         frontend/packages/ui/src/components/settings/security/SettingsSessions.svelte
// CSS: frontend/packages/ui/src/styles/settings.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
import SwiftUI

struct DevWatchPairApprovalFixture: View {
    @StateObject private var model = DevWatchPairApprovalModel()
    @StateObject private var theme = ThemeManager()
    var body: some View {
        DevWatchPairApprovalContent(model: model, bridge: model.bridge)
            .environmentObject(theme)
    }
}

private struct DevWatchPairApprovalContent: View {
    @ObservedObject var model: DevWatchPairApprovalModel
    @ObservedObject var bridge: PhoneWatchLoginBridge
    var body: some View {
        VStack(spacing: .spacing4) {
            if model.dismissed {
                Text("Approval view dismissed").accessibilityIdentifier("fixture-pair-dismissed")
            } else {
                SettingsView(isolatedNavigation: true, isolatedAccountPreview: true,
                    onWatchPairPreviewDone: { model.dismissed = true },
                    deepLinkPath: "account/security/sessions")
                    .environment(\.phoneWatchPairBridge, bridge)
                    .environmentObject(model.auth)
            }
            VStack(spacing: .spacing1) {
            Text("Synthetic bridge coordination; no account or connectivity proof.")
                .font(.omXs).accessibilityIdentifier("fixture-pair-boundary")
            Text(String(model.authorizations)).accessibilityIdentifier("fixture-pair-authorizations")
            Text(String(model.sends)).accessibilityIdentifier("fixture-pair-sends")
            Text(bridge.hasPendingApproval ? "pending" : "empty")
                .accessibilityIdentifier("fixture-pair-buffer")
            Text(bridge.pinReceiptReceived ? "received" : "waiting")
                .accessibilityIdentifier("fixture-pair-receipt")
            Text(String(model.cancellations)).accessibilityIdentifier("fixture-pair-cancellations")
            }
            .font(.omTiny)
            HStack {
                Button("Reachable, send fails") { model.reachable = true }
                    .accessibilityIdentifier("fixture-pair-reachable-error")
                Button("Receive PIN") { model.delivers = true }
                    .accessibilityIdentifier("fixture-pair-deliver")
                Button("Exchange acknowledged") { model.status = "acknowledged" }
                    .accessibilityIdentifier("fixture-pair-complete")
            }
            HStack {
                Button("Expire") { model.now = model.expiry }
                    .accessibilityIdentifier("fixture-pair-expire")
                Button("Logout") { model.auth.state = .unauthenticated }
                    .accessibilityIdentifier("fixture-pair-logout")
                Button("Change server") { model.profile = .production }
                    .accessibilityIdentifier("fixture-pair-profile")
            }
        }
        .padding(.spacing4)
    }
}

@MainActor private final class DevWatchPairApprovalModel: ObservableObject {
    let auth = AuthManager()
    private(set) var bridge: PhoneWatchLoginBridge!
    @Published var authorizations = 0
    @Published var sends = 0
    @Published var cancellations = 0
    @Published var dismissed = false
    var now = 10_000
    let expiry = 10_090
    var profile = ServerProfile.development
    var reachable = false
    var delivers = false
    var status = "approved"

    init() {
        // Fixed fictional user metadata stays in this local AuthManager instance.
        auth.currentUser = try! JSONDecoder().decode(UserProfile.self,
            from: Data(#"{"id":"pair-fixture-user","username":"pair-fixture"}"#.utf8))
        auth.state = .authenticated
        var dependencies = PhoneWatchPairDependencies()
        dependencies.usesConnectivity = false
        dependencies.offersNotification = false
        dependencies.profile = { [weak self] in self?.profile ?? .development }
        dependencies.now = { [weak self] in self?.now ?? 0 }
        dependencies.reachable = { [weak self] in self?.reachable ?? false }
        dependencies.authorize = { [weak self] _, _ in
            guard let self else { throw CancellationError() }
            self.authorizations += 1
            return PairV2Authorization(pin: "ABC346", expiresAt: self.expiry, relayTask: Task {})
        }
        dependencies.poll = { [weak self] _ in
            guard let self else { throw CancellationError() }
            return PairV2AuthorizerPoll(status: self.status, expiresAt: self.expiry,
                                       receiverRequest: nil, receiverFinish: nil)
        }
        dependencies.cancel = { [weak self] _ in self?.cancellations += 1 }
        dependencies.send = { [weak self] approval, completion in
            guard let self else { completion(nil); return }
            self.sends += 1
            // Exercise the same parser/active-attempt check used by the Watch.
            guard self.delivers,
                  let received = WatchPairLoginConnectivityPayload.parseApproval(
                    WatchPairLoginConnectivityPayload.approvalMessage(approval)),
                  WatchPairLoginConnectivityPayload.canReceiveApproval(received,
                    token: self.bridge.pendingRequest?.token, status: .ready) else {
                completion(nil)
                return
            }
            completion(WatchPairLoginConnectivityPayload.parseApprovalReceipt(
                WatchPairLoginConnectivityPayload.approvalReceiptMessage(token: received.token)))
        }
        dependencies.stepUpMethods = { _ in
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            return try decoder.decode(PairV2StepUpMethods.self,
                from: Data(#"{"has_passkey":false,"has_password":false,"has_2fa":false}"#.utf8))
        }
        dependencies.pause = { try await Task.sleep(for: .milliseconds(100)) }
        bridge = PhoneWatchLoginBridge(dependencies: dependencies)
        bridge.start(isAuthenticated: { [weak self] in self?.auth.state == .authenticated })
        bridge.receive(WatchPairLoginRequest(token: "ABC123",
            pairURLString: "https://app.dev.openmates.org/#pair=ABC123", deviceName: "Fixture Watch",
            serverProfile: .development, createdAt: now))
    }
}
#endif
