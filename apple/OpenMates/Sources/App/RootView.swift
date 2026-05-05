// Root view controller — switches between auth flow and main app
// based on AuthManager state, mirroring the web app's +page.svelte logic.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/+page.svelte
//          (top-level routing: unauthenticated → landing, authenticated → app)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(macOS)
import AppKit
#endif

struct RootView: View {
    @EnvironmentObject var authManager: AuthManager

    var body: some View {
        Group {
            switch authManager.state {
            case .initializing:
                LaunchScreen()

            case .unauthenticated:
                MainAppView()
                    .transition(.opacity)

            case .needsDeviceVerification(let type):
                DeviceVerificationView(verificationType: type)
                    .transition(.opacity)

            case .authenticated:
                MainAppView()
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.3), value: authManager.state)
        .modifier(MacWindowChromeModifier())
    }
}

private struct MacWindowChromeModifier: ViewModifier {
    func body(content: Content) -> some View {
        #if os(macOS)
        content
            .background {
                MacWindowChromeConfigurator()
                    .frame(width: 0, height: 0)
            }
        #else
        content
        #endif
    }
}

#if os(macOS)
private struct MacWindowChromeConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView(frame: .zero)
        DispatchQueue.main.async {
            configure(window: view.window)
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            configure(window: nsView.window)
        }
    }

    private func configure(window: NSWindow?) {
        guard let window else { return }
        window.styleMask.insert(.fullSizeContentView)
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(named: "grey-0", bundle: .main) ?? .black
        window.isMovableByWindowBackground = true
    }
}
#endif

struct LaunchScreen: View {
    var body: some View {
        ZStack {
            Color.grey0.ignoresSafeArea()
            VStack(spacing: .spacing4) {
                Image("openmates-brand")
                    .renderingMode(.original)
                    .resizable()
                    .frame(width: 64, height: 64)
                    .clipShape(Circle())
                ProgressView()
                    .tint(.fontSecondary)
            }
        }
    }
}
