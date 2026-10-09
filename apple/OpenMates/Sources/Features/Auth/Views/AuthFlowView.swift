// Auth flow container — manages step transitions for the login flow.
// Mirrors Login.svelte's step-based navigation between email lookup,
// password entry, passkey, recovery key, and backup code screens.
// VoiceOver: screen change announcements on step transitions, combined header group.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Login.svelte
//          frontend/packages/ui/src/components/LoginMethodSelector.svelte
//          frontend/packages/ui/src/components/AppIconGrid.svelte
//          frontend/packages/ui/src/components/settings/SettingsSessionsPairInitiate.svelte
// CSS:     frontend/packages/ui/src/styles/auth.css (.login-box, .form-container)
//          Login.svelte (.login-tabs, .tab-button)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

@MainActor
final class AuthFlowState: ObservableObject {
    @Published var currentStep: AuthStep = .emailLookup
    @Published var authMode: AuthMode = .signup
    @Published var email = ""
    @Published var availableMethods: [LoginMethod] = []
    @Published var tfaEnabled = false
    @Published var stayLoggedIn = true
    @Published var userEmailSalt: String?
    let phonePair = PhonePairLoginState()

    enum AuthMode {
        case login
        case signup
    }

    enum AuthStep {
        case emailLookup
        case passwordLogin
        case passkeyLogin
        case recoveryKey
        case backupCode
        case pairInitiate
        case accountRecovery
    }

    func reset() {
        currentStep = .emailLookup
        authMode = .signup
        email = ""
        availableMethods = []
        tfaEnabled = false
        stayLoggedIn = true
        userEmailSalt = nil
        phonePair.reset()
    }

    func resetForAnotherAccount() {
        currentStep = .emailLookup
        email = ""
        availableMethods = []
        userEmailSalt = nil
        phonePair.reset()
    }
}

struct AuthFlowView: View {
    let onBackToDemo: () -> Void
    @ObservedObject var flowState: AuthFlowState

    @EnvironmentObject var authManager: AuthManager
    @State private var authViewport = CGSize(width: 390, height: 844)
    private var authViewportWidth: CGFloat { authViewport.width }
    @State private var signupSessionIdentity = UUID()

    private var prefersPasswordLoginForUITests: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-prefer-password-login")
    }

    var body: some View {
        ZStack {
            Color.grey20.ignoresSafeArea()
                .onGeometryChange(for: CGSize.self) { $0.size } action: { authViewport = $0 }
            ScrollView {
                AuthEntryLayout(viewport: authViewport) {
                    VStack(spacing: 0) {
                        AuthEntryHeader(mobile: authViewportWidth <= 600, mode: flowState.authMode,
                            onBackToDemo: onBackToDemo, onSelectMode: selectMode)
                        if flowState.authMode == .login {
                            AuthLoginHeading(compact: authViewportWidth <= 730)
                            loginContent
                                .padding(.top, .spacing24)
                                .padding(.bottom, .spacing5)
                        } else {
                            SignupFlowView(compact: authViewportWidth <= 730)
                                .id(signupSessionIdentity)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Subviews

    private func selectMode(_ mode: AuthFlowState.AuthMode) {
        if flowState.currentStep == .pairInitiate {
            flowState.phonePair.reset()
        }
        if mode == .signup && flowState.authMode != .signup {
            // Closing signup cancels and scrubs its coordinator. Returning
            // creates a fresh session, never reuses an inactive StateObject.
            signupSessionIdentity = UUID()
        }
        flowState.authMode = mode
        if mode == .login {
            flowState.currentStep = .emailLookup
        }
    }

    @ViewBuilder
    private var loginContent: some View {
        switch flowState.currentStep {
        case .emailLookup:
            EmailLookupView(
                email: $flowState.email,
                stayLoggedIn: $flowState.stayLoggedIn,
                onPasskeyLogin: { flowState.currentStep = .passkeyLogin },
                onPairLogin: { flowState.currentStep = .pairInitiate },
                onLookupComplete: handleLookupComplete
            )

        case .passwordLogin:
            PasswordLoginView(
                email: flowState.email,
                userEmailSalt: flowState.userEmailSalt,
                tfaEnabled: flowState.tfaEnabled,
                stayLoggedIn: $flowState.stayLoggedIn,
                onRecoveryKey: { flowState.currentStep = .recoveryKey },
                onAnotherAccount: { flowState.resetForAnotherAccount() },
                onAccountRecovery: { flowState.currentStep = .accountRecovery }
            )

        case .passkeyLogin:
            PasskeyLoginView(email: flowState.email, stayLoggedIn: $flowState.stayLoggedIn)

        case .recoveryKey:
            RecoveryKeyView(email: flowState.email, userEmailSalt: flowState.userEmailSalt)

        case .backupCode:
            BackupCodeView(email: flowState.email, userEmailSalt: flowState.userEmailSalt)

        case .pairInitiate:
            PhonePairLoginView(stayLoggedIn: $flowState.stayLoggedIn, pairState: flowState.phonePair)

        case .accountRecovery:
            AccountRecoveryView()
        }
    }

    // MARK: - Navigation bar (back button for non-email steps)

    private var showBackButton: Bool {
        flowState.currentStep != .emailLookup
    }

    // MARK: - Actions

    private func handleLookupComplete(methods: [LoginMethod], tfa: Bool, userEmailSalt: String?) {
        flowState.availableMethods = methods
        flowState.tfaEnabled = tfa
        flowState.userEmailSalt = userEmailSalt

        if methods.contains(.passkey), !prefersPasswordLoginForUITests {
            flowState.currentStep = .passkeyLogin
            AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.passkey_login_screen"))
        } else {
            flowState.currentStep = .passwordLogin
            AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.password_login_screen"))
        }
    }

}

// auth.css desktop grid columns: equal flexible sides around a440px form.
// Side decoration stays outside the form; narrow windows crop only its outer
// columns. Use the same container in production and isolated entry previews.
struct AuthEntryLayout<Content: View>: View {
    let viewport: CGSize
    private let content: Content
    init(viewport: CGSize, @ViewBuilder content: () -> Content) {
        self.viewport = viewport
        self.content = content()
    }
    private var mobile: Bool { viewport.width <= 600 }
    private var formWidth: CGFloat { mobile ? min(440, max(0, viewport.width - 40)) : 440 }
    private var sideWidth: CGFloat { max(0, (viewport.width - formWidth) / 2) }

    var body: some View {
        HStack(spacing: 0) {
            if !mobile { sideGrid(.leading) }
            content.frame(width: formWidth)
                .padding(.top, mobile ? 0 : 50)
                .padding(.bottom, mobile ? .spacing10 : 55)
            if !mobile { sideGrid(.trailing) }
        }
        .frame(width: viewport.width)
        .frame(minHeight: mobile ? 0 : viewport.height, alignment: mobile ? .top : .center)
    }
    private func sideGrid(_ side: AuthAppIconGrid.Side) -> some View {
        AuthAppIconGrid(side: side)
            .frame(width: sideWidth, alignment: side == .leading ? .trailing : .leading)
            // The middle column shifts up30px. Preserve that vertical extent
            // while cropping columns that fall beyond the viewport's sides.
            .mask { Rectangle().padding(.vertical, -30) }
    }
}

// Login.svelte navigation and decorative grid, shared with the isolated header
// fixture so its real controls and spacing can be exercised without an account.
struct AuthEntryHeader: View {
    let mobile: Bool
    let mode: AuthFlowState.AuthMode
    let onBackToDemo: () -> Void
    let onSelectMode: (AuthFlowState.AuthMode) -> Void

    var body: some View {
        VStack(spacing: 0) {
            if mobile {
                AuthAppIconGrid(side: .mobile)
                    .clipped()
                    // auth.css: mobile grid -25px bottom + login-box 20px top.
                    .padding(.bottom, -5)
            }
            HStack {
                Button(action: onBackToDemo) {
                    HStack(spacing: .spacing2) {
                        Icon("back", size: 18)
                        Text(AppStrings.authDemo).font(.omSmall).fontWeight(.semibold)
                    }
                    .foregroundStyle(Color.fontSecondary)
                    .frame(minHeight: 44, alignment: .top)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("auth-demo-back")
                Spacer()
            }
            .frame(height: .spacing24, alignment: .topLeading)
            HStack(spacing: .spacing4) {
                tab(AppStrings.login, selection: .login)
                tab(AppStrings.signup, selection: .signup)
            }
            .padding(.spacing2)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .padding(.bottom, .spacing16)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("auth-entry-header")
    }

    private func tab(_ title: String, selection: AuthFlowState.AuthMode) -> some View {
        Button { onSelectMode(selection) } label: {
            Text(title)
                .font(.omP)
                .fontWeight(mode == selection ? .semibold : .medium)
                .foregroundStyle(mode == selection ? Color.fontButton : Color.fontSecondary)
                .padding(.horizontal, .spacing10)
                .padding(.vertical, .spacing6)
                .frame(maxWidth: .infinity)
                .background {
                    if mode == selection { LinearGradient.primary }
                    else { Color.clear }
                }
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .shadow(color: mode == selection ? AppGradientPalette.colors(for: "openmates").start.opacity(0.25) : .clear,
                    radius: 4, x: 0, y: 2)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(selection == .login ? "auth-login-tab" : "auth-signup-tab")
        .accessibilityAddTraits(mode == selection ? .isSelected : [])
    }
}

// AppIconGrid.svelte + icons.css: mobile content size36, border1, margin5
// produce38px tiles in48px wrappers; row gap2, odd-column shift10.
// Desktop67px content plus2px borders gives71px tiles and a677px grid.
// User-requested tile backgrounds use web opacity0.2; white glyphs stay
// fully opaque. Decorative icons never receive input or VoiceOver focus.
private struct AuthAppIconGrid: View {
    enum Side { case leading, trailing, mobile }
    let side: Side
    private let left = [["videos", "health", "web"], ["calendar", "nutrition", "language"],
        ["plants", "fitness", "shipping"], ["shopping", "jobs", "books"], ["study", "home", "tv"],
        ["weather", "events", "legal"], ["travel", "photos", "maps"]]
    private let right = [["finance", "business", "files"], ["code", "pcbdesign", "audio"],
        ["mail", "socialmedia", "messages"], ["hosting", "diagrams", "news"],
        ["notes", "whiteboards", "projectmanagement"], ["design", "publishing", "pdfeditor"],
        ["slides", "sheets", "docs"]]
    var body: some View {
        let mobile = side == .mobile
        let rows = mobile ? [left.prefix(4).flatMap { $0 }, right.prefix(4).flatMap { $0 }] : (side == .leading ? left : right)
        let size: CGFloat = mobile ? 38 : 71
        VStack(spacing: mobile ? 2 : 30) {
            ForEach(rows.indices, id: \.self) { row in
                HStack(spacing: mobile ? 2 : 30) {
                    ForEach(rows[row].indices, id: \.self) { column in
                        let app = rows[row][column]
                        let colors = AppGradientPalette.colors(for: app)
                        RoundedRectangle(cornerRadius: mobile ? 9 : 17)
                            .fill(LinearGradient.omGradient(start: colors.start, end: colors.end))
                            .opacity(0.2)
                            .frame(width: size, height: size)
                            .overlay {
                                Icon(AppIconView.iconName(forAppId: app), size: mobile ? 18 : 33.5)
                                    .foregroundStyle(.white)
                            }
                            .overlay {
                                RoundedRectangle(cornerRadius: mobile ? 9 : 17)
                                    .strokeBorder(Color.grey20, lineWidth: mobile ? 1 : 2)
                                    .opacity(0.2)
                            }
                            .padding(mobile ? .spacing2 + 1 : 0)
                            .offset(y: column.isMultiple(of: 2) ? 0 : (mobile ? -10 : -30))
                        }
                    }
                }
            }
        // The shifted mobile tile starts5px above its48px wrapper. Reserve
        // that space before the header clips its horizontal overflow.
        .padding(.top, mobile ? 5 : 0)
        .frame(maxWidth: mobile ? .infinity : nil)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
