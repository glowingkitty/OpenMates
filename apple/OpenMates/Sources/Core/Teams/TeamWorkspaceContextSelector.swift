import SwiftUI

// Matches the compact selector inside SettingsMainHeader's banner.
struct TeamWorkspaceContextSelector: View {
    @ObservedObject var context: TeamWorkspaceContext
    var isCollapsed = false

    init(context: TeamWorkspaceContext = .shared, isCollapsed: Bool = false) {
        self.context = context
        self.isCollapsed = isCollapsed
    }

    var body: some View {
        Group {
            if !context.teams.isEmpty {
                VStack(spacing: 2) {
                    HStack(spacing: 12) {
                        if let team = context.selectedTeam {
                            Circle()
                                .fill(LinearGradient(colors: [Self.avatarColor(team.profileImageMetadata.backgroundColor),
                                                              Color(hex: 0x5A85EB)],
                                                     startPoint: .topLeading, endPoint: .bottomTrailing))
                                .frame(width: 26, height: 26)
                                .overlay {
                                    Icon("team", size: 14)
                                        .foregroundStyle(Color.fontButton)
                                }
                                .overlay(Circle().strokeBorder(Color.fontButton.opacity(0.9), lineWidth: 2))
                                .accessibilityHidden(true)
                                .accessibilityIdentifier("profile-open-active-team-avatar")
                        }

                        Menu {
                            Button(AppStrings.teamContextPersonal) {
                                Task { await context.selectTeam(nil) }
                            }
                            ForEach(context.teams) { team in
                                Button(team.name) {
                                    Task { await context.selectTeam(team.id) }
                                }
                            }
                        } label: {
                            HStack(spacing: 7) {
                                Text(context.selectedTeam?.name ?? AppStrings.teamContextPersonal)
                                    .lineLimit(1)
                                Image(systemName: "chevron.down")
                                    .font(.system(size: 9, weight: .bold))
                            }
                            .font(Font.custom("Lexend Deca", size: 12).weight(.bold))
                            .foregroundStyle(Color.fontButton)
                            .padding(.leading, 12)
                            .padding(.trailing, 10)
                            .frame(height: 30)
                            .background(Color.fontButton.opacity(0.16), in: Capsule())
                            .overlay(Capsule().strokeBorder(Color.fontButton.opacity(0.42), lineWidth: 1))
                        }
                        .disabled(context.isLoading)
                        .accessibilityLabel(AppStrings.teamContextSwitch)
                        .accessibilityIdentifier("team-context-dropdown")
                    }
                    .frame(maxWidth: .infinity, alignment: isCollapsed ? .leading : .center)

                    if context.error != nil {
                        Text(AppStrings.teamContextLoadError)
                            .font(Font.custom("Lexend Deca", size: 10))
                            .foregroundStyle(Color.fontButton.opacity(0.85))
                            .accessibilityIdentifier("team-context-load-error")
                    }
                }
                .padding(.top, isCollapsed ? 0 : 8)
                .accessibilityIdentifier("profile-team-context-switcher")
            }
        }
    }

    private static func avatarColor(_ raw: String) -> Color {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.hasPrefix("#") else { return Color(hex: 0x4D73FF) }
        let digits = String(value.dropFirst())
        let expanded: String
        switch digits.count {
        case 3:
            expanded = digits.map { "\($0)\($0)" }.joined()
        case 6:
            expanded = digits
        case 8:
            expanded = String(digits.prefix(6))
        default:
            return Color(hex: 0x4D73FF)
        }
        guard let rgb = UInt32(expanded, radix: 16) else { return Color(hex: 0x4D73FF) }
        return Color(red: Double((rgb >> 16) & 0xFF) / 255,
                     green: Double((rgb >> 8) & 0xFF) / 255,
                     blue: Double(rgb & 0xFF) / 255)
    }
}

private extension AppStrings {
    static var teamContextPersonal: String { LocalizationManager.shared.text("settings.personal_context") }
    static var teamContextSwitch: String { LocalizationManager.shared.text("settings.switch_team_context") }
    static var teamContextLoadError: String { LocalizationManager.shared.text("settings.team_context_load_error") }
}
