#if DEBUG
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/Login.svelte
//         frontend/packages/ui/src/components/EmailLookup.svelte
// CSS: frontend/packages/ui/src/styles/auth.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
import SwiftUI

// Local controller callbacks drive the production form tasks. No credentials,
// network requests, account publication or AuthenticationServices UI are used.
struct DevPasskeyLifecycleFixture: View {
    @StateObject private var model = DevPasskeyLifecycleModel()
    @StateObject private var auth = AuthManager()
    @State private var email = ""
    @State private var stay = false
    @State private var manual = false
    @State private var destination: String?

    var body: some View {
        VStack(spacing: .spacing8) {
            Text(model.phase).accessibilityIdentifier("fixture-passkey-phase")
            if let destination {
                Text(destination).accessibilityIdentifier("fixture-auth-destination")
                Text("This local controller fixture stops before external account authentication.").font(.omSmall)
                Button(AppStrings.back) { self.destination = nil }
                    .accessibilityIdentifier("fixture-auth-return")
            } else if manual {
                PasskeyLoginView(email: email, stayLoggedIn: $stay, login: model.manualLogin)
                    .environmentObject(auth)
                Button(AppStrings.back) { manual = false }
                    .accessibilityIdentifier("fixture-passkey-return")
            } else {
                EmailLookupForm(email: $email, stayLoggedIn: $stay,
                    onPasskeyLogin: { manual = true }, onPairLogin: { destination = "device-pairing" },
                    lookup: { _, _ in throw AuthFormError.rejected }, immediatePasskey: model.automaticLogin)
            }
            if model.phase == "automatic-cancelling" {
                Button("Acknowledge local controller cancellation") { model.acknowledgeAutomaticCancellation() }
                    .accessibilityIdentifier("fixture-passkey-acknowledge-cancel")
            }
        }
        .frame(maxWidth: 440)
        .padding(.spacing8)
    }
}

@MainActor private final class DevPasskeyLifecycleModel: ObservableObject {
    @Published var phase = "idle"
    private let lifecycle = PasskeyAssertionLifecycle()
    private var attemptedAutomatic = false
    private var automatic: Controller?

    func automaticLogin() async {
        guard !attemptedAutomatic else { return }
        attemptedAutomatic = true
        let controller = Controller(delayedCancellation: true) { [weak self] in self?.phase = $0 }
        automatic = controller
        _ = try? await lifecycle.perform { controller }
    }

    func manualLogin() async throws {
        let controller = Controller(delayedCancellation: false) { [weak self] in self?.phase = $0 }
        _ = try await lifecycle.perform { controller }
    }

    func acknowledgeAutomaticCancellation() { automatic?.acknowledgeCancellation() }

    private final class Controller: PasskeyAssertionController {
        let delayedCancellation: Bool
        let update: @MainActor (String) -> Void
        private var completion: (@MainActor (Result<PasskeyAssertionResult, Error>) -> Void)?
        init(delayedCancellation: Bool, update: @escaping @MainActor (String) -> Void) {
            self.delayedCancellation = delayedCancellation
            self.update = update
        }
        func start(completion: @escaping @MainActor (Result<PasskeyAssertionResult, Error>) -> Void) {
            self.completion = completion
            update(delayedCancellation ? "automatic-active" : "manual-active")
        }
        func cancel() {
            if delayedCancellation { update("automatic-cancelling") }
            else { update("manual-cancelled"); acknowledgeCancellation() }
        }
        func acknowledgeCancellation() {
            let completion = self.completion
            self.completion = nil
            completion?(.failure(PasskeyError.cancelled))
        }
    }
}
#endif
