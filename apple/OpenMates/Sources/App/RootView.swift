// Root view controller — switches between auth flow and main app
// based on AuthManager state, mirroring the web app's +page.svelte logic.

import SwiftUI

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
    }
}

struct LaunchScreen: View {
    var body: some View {
        ZStack {
            Color.grey0.ignoresSafeArea()
            VStack(spacing: .spacing4) {
                Image.iconOpenmates
                    .resizable()
                    .frame(width: 64, height: 64)
                ProgressView()
                    .tint(.fontSecondary)
            }
        }
    }
}
