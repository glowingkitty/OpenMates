// Root view controller — switches between auth flow and main app
// based on AuthManager state, mirroring the web app's +page.svelte logic.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/+page.svelte
//          (top-level routing: unauthenticated → landing, authenticated → app)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#endif
#if os(macOS)
import AppKit
#endif

struct RootView: View {
    let launchCommand: AppWindowLaunchCommand?

    @EnvironmentObject var authManager: AuthManager
    #if os(iOS)
    @StateObject private var externalDisplayCoordinator = ExternalDisplayCoordinator.shared
    #endif
    #if DEBUG
    @State private var devPreviewConfiguration = DevPreviewLaunchConfiguration.current
    #endif

    init(launchCommand: AppWindowLaunchCommand? = nil) {
        self.launchCommand = launchCommand
    }

    var body: some View {
        Group {
            #if DEBUG
            if let devPreviewConfiguration {
                DevPreviewRootView(configuration: devPreviewConfiguration)
            } else {
                rootContent
            }
            #else
            rootContent
            #endif
        }
        #if os(iOS)
        .overlay {
            if externalDisplayCoordinator.shouldShowPhoneController {
                ExternalDisplayControllerView()
                    .environmentObject(externalDisplayCoordinator)
                    .transition(.opacity)
            }
        }
        .onAppear {
            externalDisplayCoordinator.refreshConnectedDisplays()
        }
        #endif
        .animation(.easeInOut(duration: 0.3), value: authManager.state)
        .modifier(MacWindowChromeModifier())
        #if DEBUG
        .onOpenURL { url in
            if let configuration = DevPreviewLaunchConfiguration.parse(url: url) {
                devPreviewConfiguration = configuration
            }
        }
        #endif
    }

    @ViewBuilder
    private var rootContent: some View {
        switch authManager.state {
        case .initializing:
            LaunchScreen()

        case .unauthenticated:
            MainAppView(launchCommand: launchCommand)
                .transition(.opacity)

        case .needsDeviceVerification(let type):
            DeviceVerificationView(verificationType: type)
                .transition(.opacity)

        case .authenticated:
            MainAppView(launchCommand: launchCommand)
                .transition(.opacity)
        }
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
