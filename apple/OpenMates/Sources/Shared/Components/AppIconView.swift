// App icon component — renders a gradient circle with the app's icon.
// Maps app IDs to their gradient and icon from the design token system.

import SwiftUI

struct AppIconView: View {
    let appId: String
    let size: CGFloat

    var body: some View {
        Circle()
            .fill(gradient(for: appId))
            .frame(width: size, height: size)
            .overlay {
                Image(iconName(for: appId))
                    .resizable()
                    .renderingMode(.template)
                    .foregroundStyle(.white)
                    .frame(width: size * 0.5, height: size * 0.5)
            }
    }

    private func gradient(for appId: String) -> LinearGradient {
        switch appId {
        case "ai": return .appAi
        case "health": return .appHealth
        case "nutrition": return .appNutrition
        case "finance": return .appFinance
        case "fitness": return .appFitness
        case "legal": return .appLegal
        case "weather": return .appWeather
        case "travel": return .appTravel
        case "news": return .appNews
        case "jobs": return .appJobs
        case "code": return .appCode
        case "music": return .appMusic
        case "maps": return .appMaps
        case "shopping": return .appShopping
        case "mail": return .appMail
        case "calendar": return .appCalendar
        case "notes": return .appNotes
        case "events": return .appEvents
        case "photos", "images": return .appPhotos
        case "videos": return .appVideos
        case "design": return .appDesign
        case "docs": return .appDocs
        default: return .primary
        }
    }

    private func iconName(for appId: String) -> String {
        // Check aliases first
        switch appId {
        case "health": return IconAlias.health
        case "plants": return IconAlias.plants
        case "events": return IconAlias.events
        case "photos": return IconAlias.photos
        case "books": return IconAlias.books
        case "finance": return IconAlias.finance
        case "code": return IconAlias.code
        case "hosting": return IconAlias.hosting
        case "diagrams": return IconAlias.diagrams
        case "whiteboards": return IconAlias.whiteboards
        case "messages": return IconAlias.messages
        case "contacts": return IconAlias.contacts
        default: return appId
        }
    }
}
