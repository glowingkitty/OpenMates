// Web counterpart: frontend/packages/ui/src/components/settings/SettingsTeams.svelte
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.composition.canonical-and-accessible, settings-ui.parity.web-apple-shell, settings-ui.navigation.contextual-availability
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.lifecycle.encrypted-profiled, teams.membership.role-gated, teams.invites.fragment-key-web-flow

import SwiftUI

@MainActor private func teamsText(_ key: String, _ fallback: String) -> String {
    let value = AppStrings.localized(key)
    return value == key ? fallback : value
}

struct SettingsTeamsView: View {
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var controller: SettingsTeamsController
    let initialTeamID: String?
    var onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)?
    @State private var name = ""
    @State private var teamDescription = ""
    @State private var email = ""
    private let fixture: Bool

    init(initialTeamID: String? = nil, onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)? = nil) {
        self.initialTeamID = initialTeamID
        self.onChildNavigationChanged = onChildNavigationChanged
        #if DEBUG
        let fixture = ProcessInfo.processInfo.arguments.contains("--ui-test-teams-settings-fixture")
        self.fixture = fixture
        _controller = StateObject(wrappedValue: SettingsTeamsController(service: fixture ? SettingsTeamsUITestService() : SettingsTeamsService()))
        #else
        fixture = false
        _controller = StateObject(wrappedValue: SettingsTeamsController())
        #endif
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.localized("settings.teams"), showsHeader: false, contentHorizontalPadding: 0, contentVerticalSpacing: 0) {
            if authManager.currentUser != nil {
                VStack(alignment: .leading, spacing: 0) {
                    if controller.loading {
                        OMSettingsInfoBox(title: teamsText("settings.teams.loading", "Loading Teams"),
                            message: teamsText("settings.teams.loading_description", "Decrypting your joined team list on this device."), identifier: "settings-teams-loading")
                    } else if controller.failed {
                        OMSettingsInfoBox(kind: .warning, title: teamsText("settings.teams.load_failed", "Teams unavailable"),
                            message: teamsText("settings.teams.retry_description", "Teams could not be loaded. Please try again."), identifier: "settings-teams-error")
                        Button(AppStrings.retry) { Task { await load() } }
                            .buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
                            .accessibilityIdentifier("settings-teams-retry")
                    } else if let team = controller.selected {
                        teamDetail(team)
                    } else if controller.selectedID != nil {
                        OMSettingsInfoBox(kind: .warning, title: teamsText("settings.teams.not_found", "Team not found"),
                            message: teamsText("settings.teams.not_found_description", "This team may have been removed or may not be available on this device."), identifier: "settings-team-unavailable")
                    } else {
                        overview
                    }
                }
                .padding(.vertical, .spacing6)
            }
        }
        .task(id: authManager.currentUser?.id) { await load() }
        .onReceive(NotificationCenter.default.publisher(for: ServerConfiguration.didChangeNotification)) { _ in
            controller.reset(); name = ""; teamDescription = ""; email = ""
            onChildNavigationChanged?(nil)
            Task { await load() }
        }
        .onChange(of: controller.selectedID) { _, _ in publishNavigation() }
        .onChange(of: controller.teams.map(\.id)) { _, _ in publishNavigation() }
        .onChange(of: authManager.currentUser?.id) { _, _ in
            controller.reset(); name = ""; teamDescription = ""; email = ""
            onChildNavigationChanged?(nil)
        }
    }

    private var overview: some View {
        Group {
            OMSettingsSectionHeading(title: AppStrings.localized("settings.teams"), icon: "team")
            OMSettingsInfoBox(title: teamsText("settings.teams.account_settings", "Teams are account settings."),
                message: teamsText("settings.teams.account_settings_description", "Create and manage encrypted teams here. Switch personal/team context from the profile menu."), identifier: "settings-teams-account-info")
            OMSettingsSectionHeading(title: teamsText("settings.teams.create", "Create team"), icon: "team")
            OMSettingsTextInput(label: teamsText("settings.teams.name", "Team name"), placeholder: teamsText("settings.teams.name", "Team name"),
                value: $name, identifier: "settings-team-name")
            OMSettingsTextInput(label: teamsText("settings.teams.description", "Team description"), placeholder: teamsText("settings.teams.description_placeholder", "What this team works on"),
                value: $teamDescription, identifier: "settings-team-description", multiline: true)
            Button(controller.creating ? teamsText("settings.teams.creating", "Creating team…") : teamsText("settings.teams.create", "Create team")) {
                Task {
                    if await controller.create(name: name, description: teamDescription) {
                        name = ""; teamDescription = ""
                        if !fixture, let accountID = authManager.currentUser?.id { await TeamWorkspaceContext.shared.load(accountID: accountID) }
                    }
                }
            }
            .buttonStyle(OMSettingsButtonStyle()).padding(.horizontal, .spacing5)
            .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || controller.creating)
            .accessibilityIdentifier("settings-team-create")
            OMSettingsSectionHeading(title: teamsText("settings.teams.joined", "Joined teams"), icon: "team")
            if controller.teams.isEmpty {
                OMSettingsInfoBox(title: teamsText("settings.teams.empty", "No teams yet"),
                    message: teamsText("settings.teams.empty_description", "Create your first encrypted team, then invite teammates from its team settings."), identifier: "settings-teams-empty")
            } else {
                ForEach(controller.teams) { team in
                    OMSettingsRow(title: team.name, subtitle: "\(team.role.rawValue) · \(team.description.isEmpty ? teamsText("settings.teams.shared_description", "Shared encrypted team") : team.description)",
                        icon: "team", accessibilityIdentifier: "settings-team-\(team.id)") {
                        email = ""; Task { await controller.select(team.id) }
                    }
                }
            }
        }
    }

    @ViewBuilder private func teamDetail(_ team: TeamWorkspaceTeam) -> some View {
        if onChildNavigationChanged == nil {
            Button(AppStrings.back) { backToOverview() }.buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
        }
        OMSettingsSectionHeading(title: team.name, icon: "team")
        OMSettingsCard {
            OMSettingsDetailRow(label: teamsText("settings.teams.detail_name", "Name"), value: team.name, highlight: true)
            OMSettingsDetailRow(label: teamsText("settings.teams.detail_description", "Description"), value: team.description.isEmpty ? teamsText("settings.teams.shared_description", "Shared encrypted team") : team.description)
            OMSettingsDetailRow(label: teamsText("settings.teams.detail_role", "Role"), value: team.role.rawValue)
            OMSettingsDetailRow(label: teamsText("settings.teams.detail_status", "Status"), value: team.status)
            OMSettingsDetailRow(label: teamsText("settings.teams.detail_credits", "Team credits"), value: String(controller.details?.credits ?? team.zeroBalance))
            OMSettingsDetailRow(label: teamsText("settings.teams.detail_memories", "Team memories"), value: String(controller.details?.memoryCount ?? 0))
            OMSettingsDetailRow(label: AppStrings.privacyConnectedAccounts, value: teamsText("settings.teams.accounts_disabled", "Disabled in V1"), muted: true, showsDivider: false)
        }
        .accessibilityIdentifier("settings-team-detail-card")
        OMSettingsInfoBox(title: teamsText("settings.teams.boundary", "Personal data boundary"),
            message: teamsText("settings.teams.boundary_description", "Personal memories and personal connected accounts stay outside team context."), identifier: "settings-team-personal-boundary")
        OMSettingsSectionHeading(title: teamsText("settings.teams.invite_members", "Invite members"), icon: "team")
        OMSettingsTextInput(label: teamsText("settings.teams.invite_email", "Teammate email"), placeholder: "teammate@example.com",
            value: $email, identifier: "settings-team-invite-email", email: true)
            .disabled(!team.canManage)
        Button(controller.inviting ? teamsText("settings.teams.inviting", "Sending invite…") : teamsText("settings.teams.send_invite", "Send invite")) {
            Task { await controller.invite(email: email); if controller.inviteSent != nil { email = "" } }
        }
        .buttonStyle(OMSettingsButtonStyle()).padding(.horizontal, .spacing5)
        .disabled(!team.canManage || email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || controller.inviting)
        .accessibilityIdentifier("settings-team-send-invite")
        if controller.inviteFailed {
            OMSettingsInfoBox(kind: .warning, message: teamsText("settings.teams.invite_failed", "Invite could not be created"), identifier: "settings-team-invite-result")
        } else if let sent = controller.inviteSent {
            OMSettingsInfoBox(kind: .success, message: sent ? teamsText("settings.teams.invite_sent", "Invite sent") : teamsText("settings.teams.invite_created", "Invite created"), identifier: "settings-team-invite-result")
        }
    }

    private func load() async {
        guard let accountID = authManager.currentUser?.id else {
            controller.reset(); onChildNavigationChanged?(nil)
            NotificationCenter.default.post(name: .openAuth, object: nil)
            return
        }
        await controller.load(accountID: accountID, initialTeamID: initialTeamID)
        publishNavigation()
    }
    private func backToOverview() {
        email = ""
        Task { await controller.select(nil); publishNavigation() }
    }
    private func publishNavigation() {
        onChildNavigationChanged?(controller.selectedID == nil ? nil : SettingsChildBannerNavigation(
            title: controller.selected?.name ?? teamsText("settings.teams.not_found", "Team not found"), description: "", onBack: backToOverview))
    }
}
