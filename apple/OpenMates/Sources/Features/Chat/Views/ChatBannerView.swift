// Gradient banner displayed at the top of the chat message list.
// Shown for demo/example chats and new chats while the title is generating.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatHeader.svelte
// CSS:     frontend/packages/ui/src/components/ChatHeader.svelte <style>
//          .chat-header { height:50vh; min-height:240px; border-radius:14px }
//          .chat-header-content (centered icon + title + summary)
//          .deco-icon-left / .deco-icon-right { opacity:0.4; width:126px }
// i18n:    frontend/packages/ui/src/i18n/sources/chat/main.yml
//          Keys: chat.creating_new_chat, chat.header.just_now,
//                chat.header.minutes_ago, chat.header.started_today,
//                chat.header.started_yesterday
//          frontend/packages/ui/src/i18n/sources/settings/main.yml
//          Key: settings.incognito_mode_active
// Tokens:  GradientTokens.generated.swift, ColorTokens.generated.swift,
//          SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

/// Matches the three visual states of ChatHeader.svelte:
/// - loading:  primary blue gradient + "Creating new chat …" shimmer
/// - loaded:   category gradient + icon + title + optional summary
/// - incognito: fixed dark gradient + incognito label
enum ChatBannerState {
    case loading
    case loaded(title: String, appId: String, summary: String?)
    case incognito
}

/// Full-width gradient banner positioned at the top of the chat scroll view.
/// Heights mirror the web CSS: 240pt minimum (iPad/Mac), 190pt minimum (iPhone compact).
struct ChatBannerView: View {
    let state: ChatBannerState
    var createdAt: Date? = nil

    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var shimmerOffset: CGFloat = -200

    private var minHeight: CGFloat { sizeClass == .compact ? 190 : 240 }

    var body: some View {
        ZStack {
            gradientBackground
                .clipShape(RoundedRectangle(cornerRadius: 14))

            // Decorative large icons at left/right edges — opacity 0.4, matching web deco-icon-left/right
            if case .loaded(_, let appId, _) = state {
                HStack {
                    AppIconView(appId: appId, size: 100)
                        .opacity(0.25)
                        .offset(x: -28)
                    Spacer()
                    AppIconView(appId: appId, size: 100)
                        .opacity(0.25)
                        .offset(x: 28)
                }
                .clipped()
                .clipShape(RoundedRectangle(cornerRadius: 14))
            }

            centerContent
        }
        .frame(maxWidth: .infinity)
        .frame(minHeight: minHeight)
    }

    // MARK: - Gradient background

    @ViewBuilder
    private var gradientBackground: some View {
        switch state {
        case .incognito:
            LinearGradient(
                colors: [Color(hex: 0x1A1A2E), Color(hex: 0x2D2D44), Color(hex: 0x1E1E35)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        case .loading:
            LinearGradient.primary
        case .loaded(_, let appId, _):
            ChatHeaderView.appGradientForBanner(appId: appId)
        }
    }

    // MARK: - Center content

    @ViewBuilder
    private var centerContent: some View {
        switch state {
        case .loading:
            VStack(spacing: .spacing4) {
                Circle()
                    .fill(Color.white.opacity(0.35))
                    .frame(width: 38, height: 38)
                    .overlay(shimmerOverlay)

                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.white.opacity(0.35))
                    .frame(width: 180, height: 20)
                    .overlay(shimmerOverlay)

                // i18n: chat.creating_new_chat
                Text(AppStrings.creatingNewChat)
                    .font(.omP).fontWeight(.semibold)
                    .foregroundStyle(.white.opacity(0.0))
            }
            .onAppear { animateShimmer() }

        case .incognito:
            VStack(spacing: .spacing4) {
                Image(systemName: "person.fill.questionmark")
                    .font(.system(size: 38))
                    .foregroundStyle(.white)
                // i18n: settings.incognito_mode_active
                Text(AppStrings.incognitoModeActive)
                    .font(.omH4).fontWeight(.bold)
                    .foregroundStyle(.white)
            }

        case .loaded(let title, let appId, let summary):
            VStack(spacing: .spacing3) {
                AppIconView(appId: appId, size: 38)
                    .colorMultiply(.white)

                Text(title)
                    .font(.omH4).fontWeight(.bold)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, .spacing10)

                if let summary, !summary.isEmpty {
                    Text(summary)
                        .font(.omSmall)
                        .foregroundStyle(.white.opacity(0.85))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, .spacing10)
                        .lineLimit(3)
                }

                if let createdAt {
                    // i18n: chat.header.just_now / minutes_ago / started_today / started_yesterday
                    Text(relativeTime(from: createdAt))
                        .font(.omXs)
                        .foregroundStyle(.white.opacity(0.7))
                }
            }
            .padding(.vertical, .spacing8)
        }
    }

    // MARK: - Shimmer

    private var shimmerOverlay: some View {
        GeometryReader { geo in
            Rectangle()
                .fill(
                    LinearGradient(
                        colors: [.clear, .white.opacity(0.5), .clear],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .offset(x: shimmerOffset)
                .frame(width: geo.size.width * 2)
                .clipped()
        }
        .clipped()
    }

    private func animateShimmer() {
        withAnimation(.linear(duration: 1.4).repeatForever(autoreverses: false)) {
            shimmerOffset = 400
        }
    }

    // MARK: - Time formatting (i18n via AppStrings)

    private func relativeTime(from date: Date) -> String {
        let diff = Date().timeIntervalSince(date)
        let minutes = Int(diff / 60)
        let fmt = DateFormatter()
        fmt.dateFormat = "HH:mm"
        let timeStr = fmt.string(from: date)

        if minutes < 1 { return AppStrings.chatHeaderJustNow }
        if minutes <= 10 { return AppStrings.chatHeaderMinutesAgo(count: minutes) }

        let calendar = Calendar.current
        if calendar.isDateInToday(date) {
            return AppStrings.chatHeaderStartedToday(time: timeStr)
        }
        if calendar.isDateInYesterday(date) {
            return AppStrings.chatHeaderStartedYesterday(time: timeStr)
        }
        let dateFmt = DateFormatter()
        dateFmt.dateFormat = "yyyy/MM/dd"
        return AppStrings.chatHeaderStartedOn(date: dateFmt.string(from: date), time: timeStr)
    }
}

// MARK: - Gradient helper (kept in ChatHeaderView extension for callers that use it directly)

extension ChatHeaderView {
    static func appGradientForBanner(appId: String) -> LinearGradient {
        switch appId {
        case "ai": return .appAi
        case "web": return .appWeb
        case "code": return .appCode
        case "travel": return .appTravel
        case "news": return .appNews
        case "mail": return .appMail
        case "maps": return .appMaps
        case "shopping": return .appShopping
        case "events": return .appEvents
        case "videos": return .appVideos
        case "photos": return .appPhotos
        case "images": return .appImages
        case "nutrition": return .appNutrition
        case "health": return .appHealth
        case "home": return .appHome
        case "finance": return .appFinance
        case "fitness": return .appFitness
        case "legal": return .appLegal
        case "weather": return .appWeather
        case "jobs": return .appJobs
        case "files": return .appFiles
        case "docs": return .appDocs
        case "slides": return .appSlides
        case "sheets": return .appSheets
        case "notes": return .appNotes
        case "whiteboards": return .appWhiteboards
        case "language": return .appLanguage
        case "diagrams": return .appDiagrams
        case "calendar": return .appCalendar
        case "reminder": return .appReminder
        case "business": return .appBusiness
        case "music": return .appMusic
        case "audio": return .appAudio
        case "design": return .appDesign
        case "pdf": return .appPdf
        case "publishing": return .appPublishing
        case "socialmedia": return .appSocialmedia
        case "projectmanagement": return .appProjectmanagement
        case "messages": return .appMessages
        case "books": return .appBooks
        case "plants": return .appPlants
        case "beauty": return .appBeauty
        case "hosting": return .appHosting
        case "fashion": return .appFashion
        case "tv": return .appTv
        case "movies": return .appMovies
        case "secrets": return .appSecrets
        case "study": return .appStudy
        case "contacts": return .appContacts
        case "calculator": return .appCalculator
        case "games": return .appGames
        default: return .primary
        }
    }
}
