// Web source: components/settings/TeamContextPicker.svelte
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.context.full-switch-local
import SwiftUI

// Matches the compact selector inside SettingsMainHeader's banner.
struct TeamWorkspaceContextSelector: View {
    @ObservedObject var context: TeamWorkspaceContext
    var isCollapsed = false
    @State private var avatarData: Data?

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
                                    if let avatarData, let image = platformImage(avatarData) {
                                        image.resizable().scaledToFill().frame(width: 26, height: 26).clipShape(Circle())
                                    } else {
                                        Icon(team.profileImageMetadata.iconName, size: 14).foregroundStyle(Color.fontButton)
                                    }
                                }
                                .overlay(Circle().strokeBorder(Color.fontButton.opacity(0.9), lineWidth: 2))
                                .accessibilityHidden(true)
                                .accessibilityIdentifier("profile-open-active-team-avatar")
                        }

                        OMDropdown(title: AppStrings.teamContextSwitch,
                            options: [OMDropdownOption("", label: AppStrings.teamContextPersonal)] + context.teams.map { OMDropdownOption($0.id, label: $0.name) },
                            selection: Binding(get: { context.teamID ?? "" }, set: { value in
                                Task { await context.selectTeam(value.isEmpty ? nil : value) }
                            }), disabled: context.isLoading && context.teams.isEmpty,
                            controlHeight: 30)
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
        .task(id: "\(context.teamID ?? "")|\(context.selectedTeam?.updatedAt ?? 0)|\(context.contextEpoch)") {
            avatarData = nil
            guard let team = context.selectedTeam, let accountID = context.loadedAccountID else { return }
            let snapshot = context.snapshot
            let data = try? await SettingsTeamsService().avatar(team: team, fence: TeamWorkspaceFence(accountID: accountID))
            guard context.isCurrent(snapshot) else { return }
            avatarData = data
        }
    }

    private func platformImage(_ data: Data) -> Image? {
        #if os(iOS)
        return UIImage(data: data).map { Image(uiImage: $0) }
        #elseif os(macOS)
        return NSImage(data: data).map { Image(nsImage: $0) }
        #else
        return nil
        #endif
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
