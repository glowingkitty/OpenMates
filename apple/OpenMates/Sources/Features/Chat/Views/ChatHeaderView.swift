// Chat header — gradient banner at the top of a chat with title, category, and app icon.
// Mirrors the web app's ChatHeader.svelte with animated gradient background
// based on the chat's app category, shimmer effect during loading.

import SwiftUI

struct ChatHeaderView: View {
    let chat: Chat?
    let isLoading: Bool

    private var appId: String? { chat?.appId }
    private var title: String { chat?.displayTitle ?? "" }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            gradientBackground
            if isLoading {
                shimmerOverlay
            }
            headerContent
        }
        .frame(height: 80)
        .clipShape(RoundedRectangle(cornerRadius: 0))
    }

    private var gradientBackground: some View {
        Group {
            if let appId {
                LinearGradient(
                    colors: gradientColors(for: appId),
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            } else {
                LinearGradient.primary
            }
        }
        .opacity(0.15)
    }

    private var headerContent: some View {
        HStack(spacing: .spacing3) {
            if let appId {
                AppIconView(appId: appId, size: 28)
            }

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(title)
                    .font(.omSmall).fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)

                if let appId {
                    Text(appId.capitalized)
                        .font(.omTiny)
                        .foregroundStyle(Color.fontTertiary)
                }
            }

            Spacer()
        }
        .padding(.horizontal, .spacing4)
        .padding(.bottom, .spacing3)
    }

    private var shimmerOverlay: some View {
        ShimmerView()
            .opacity(0.3)
    }

    private func gradientColors(for appId: String) -> [Color] {
        switch appId {
        case "ai": return [.blue, .purple]
        case "web": return [.cyan, .blue]
        case "code": return [.green, .teal]
        case "travel": return [.orange, .pink]
        case "news": return [.red, .orange]
        case "mail": return [.blue, .cyan]
        case "maps": return [.green, .blue]
        case "shopping": return [.pink, .purple]
        case "events": return [.purple, .pink]
        case "videos": return [.red, .pink]
        case "photos", "images": return [.indigo, .purple]
        case "nutrition": return [.green, .yellow]
        case "health": return [.red, .pink]
        case "home": return [.orange, .brown]
        default: return [.blue, .purple]
        }
    }
}

// MARK: - Shimmer effect

struct ShimmerView: View {
    @State private var offset: CGFloat = -1

    var body: some View {
        GeometryReader { geo in
            LinearGradient(
                colors: [.clear, .white.opacity(0.3), .clear],
                startPoint: .leading,
                endPoint: .trailing
            )
            .frame(width: geo.size.width * 0.6)
            .offset(x: offset * geo.size.width)
            .onAppear {
                withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: false)) {
                    offset = 1.5
                }
            }
        }
        .clipped()
    }
}
