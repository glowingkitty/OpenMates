// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/settings/SettingsTeams.svelte
// CSS: frontend/packages/ui/src/styles/settings.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.cold.discoverable-bounded, storage.cold.shared-team-authorized, storage.surface.semantic-parity
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.composition.canonical-and-accessible, settings-ui.parity.web-apple-shell, settings-ui.navigation.contextual-availability
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.lifecycle.encrypted-profiled, teams.membership.role-gated, teams.invites.fragment-key-web-flow

import SwiftUI
import PhotosUI

struct SettingsTeamsView: View {
    @EnvironmentObject private var authManager: AuthManager
    @Environment(\.openURL) private var openURL
    @StateObject private var controller: SettingsTeamsController
    let initialTeamID: String?
    var onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)?
    @State private var name = ""
    @State private var email = ""
    @State private var inviteRecipient = ""
    @State private var page = ""
    @State private var memberID: String?
    @State private var confirmed = false
    @State private var domain = ""
    @State private var avatarIcon = "team"
    @State private var avatarColor = "#4d73ff"
    @State private var draftJPEG: Data?
    @State private var avatarOptionsOpen = false
    @State private var avatarGeneratedChanged = false
    @State private var selectedPhoto: PhotosPickerItem?
    @State private var photoGeneration = UUID()
    @State private var preparingPhoto = false
    @State private var photoFailed = false
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
        OMSettingsPage(title: AppStrings.teamsTitle, showsHeader: false, contentHorizontalPadding: 0, contentVerticalSpacing: 0, scrollAccessibilityIdentifier: "settings-teams-page") {
            if authManager.currentUser != nil {
                VStack(alignment: .leading, spacing: 0) {
                    if controller.loading {
                        OMSettingsInfoBox(title: AppStrings.teamsLoadingTeams,
                            message: AppStrings.teamsDescription, identifier: "settings-teams-loading")
                    } else if controller.failed && controller.teams.isEmpty {
                        OMSettingsInfoBox(kind: .warning, title: AppStrings.teamsLoadFailed,
                            message: AppStrings.teamsLoadFailed, identifier: "settings-teams-error")
                        Button(AppStrings.retry) { Task { await load() } }
                            .buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
                            .accessibilityIdentifier("settings-teams-retry")
                    } else if let team = controller.selected {
                        if controller.failed {
                            OMSettingsInfoBox(kind: .warning, message: AppStrings.teamsLoadFailed, identifier: "team-cached-details")
                        }
                        if page.isEmpty { teamDetail(team) }
                        else { managementPage(team) }
                    } else if controller.selectedID != nil {
                        OMSettingsInfoBox(kind: .warning, title: AppStrings.teamsTeamNotFound,
                            message: AppStrings.teamsTeamNotFound, identifier: "settings-team-unavailable")
                    } else {
                        if page == "new" || page == "new/avatar" { creation }
                        else { overview }
                    }
                }
                .padding(.vertical, .spacing6)
            }
        }
        .task(id: authManager.currentUser?.id) { await load() }
        .onReceive(NotificationCenter.default.publisher(for: ServerConfiguration.didChangeNotification)) { _ in
            photoGeneration = UUID(); preparingPhoto = false; selectedPhoto = nil; photoFailed = false
            controller.reset(); name = ""; email = ""; inviteRecipient = ""; draftJPEG = nil; page = ""
            onChildNavigationChanged?(nil)
            Task { await load() }
        }
        .onReceive(TeamWorkspaceContext.shared.$teams) { values in
            if !fixture { Task { await controller.membershipChanged(values) } }
        }
        .onReceive(TeamWorkspaceContext.shared.$contextEpoch.dropFirst()) { _ in
            if !fixture { Task { await controller.membershipChanged(TeamWorkspaceContext.shared.teams) } }
        }
        .onChange(of: selectedPhoto) { _, item in loadPhoto(item) }
        .onChange(of: controller.accountDeleted) { _, deleted in if deleted { Task { await authManager.logout() } } }
        .onChange(of: controller.selectedID) { _, _ in
            inviteRecipient = ""
            photoGeneration = UUID(); preparingPhoto = false; selectedPhoto = nil; photoFailed = false
            publishNavigation()
        }
        .onChange(of: controller.teams.map(\.id)) { _, _ in publishNavigation() }
        .onChange(of: authManager.currentUser?.id) { _, _ in
            photoGeneration = UUID(); preparingPhoto = false; selectedPhoto = nil; photoFailed = false
            controller.reset(); name = ""; email = ""; inviteRecipient = ""; draftJPEG = nil; page = ""
            onChildNavigationChanged?(nil)
        }
    }

    private var overview: some View {
        Group {
            if controller.teams.isEmpty {
                OMSettingsInfoBox(message: AppStrings.teamsEmptyTeams, identifier: "settings-teams-empty")
            } else {
                ForEach(controller.teams) { team in
                    Button {
                        email = ""; page = ""; Task { await controller.select(team.id) }
                    } label: {
                        HStack(spacing: .spacing6) {
                            SettingsTeamContextAvatar(team: team, size: 43)
                                .accessibilityIdentifier("team-settings-team-avatar")
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text(team.name).font(.omP.weight(.bold)).foregroundStyle(LinearGradient.primary)
                                Text("\(team.role.rawValue) \(AppStrings.teamsRoleSuffix)")
                                    .font(.omSmall.weight(.medium)).foregroundStyle(Color.fontSecondary)
                            }
                            Spacer(minLength: .spacing4)
                            Icon("chevron-right", size: 16).foregroundStyle(Color.fontTertiary)
                        }.padding(.horizontal, .spacing5).padding(.vertical, 5).contentShape(Rectangle())
                    }.buttonStyle(.plain).accessibilityIdentifier("settings-team-\(team.id)")

                }
            }
            OMSettingsRow(title: AppStrings.teamsNewTeam, icon: "create",
                accessibilityIdentifier: "team-create-open") {
                    controller.beginCreation(); name = ""; draftJPEG = nil
                    avatarIcon = "team"; avatarColor = "#4d73ff"; avatarOptionsOpen = false; avatarGeneratedChanged = false
                    page = "new"; publishNavigation()
                }
        }
    }

    @ViewBuilder private var creation: some View {
        if page == "new" {
            OMSettingsTextInput(label: AppStrings.teamsTeamName, placeholder: AppStrings.teamsNamePlaceholder,
                value: $name, identifier: "settings-team-name")
                .disabled(controller.checkingName || controller.createdForDraft != nil)
            Button(controller.checkingName ? AppStrings.loading : AppStrings.teamsContinue) {
                Task { if await controller.continueCreation(name: name), page == "new" { page = "new/avatar"; publishNavigation() } }
            }
            .buttonStyle(SettingsTeamCTAButtonStyle()).padding(.horizontal, .spacing5)
            .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || controller.checkingName)
            .accessibilityIdentifier("team-create-continue")
            if controller.nameCheckFailed {
                OMSettingsInfoBox(kind: .warning, message: AppStrings.teamsNameCheckFailed, identifier: "team-create-name-error")
            }
            VStack(alignment: .leading, spacing: .spacing4) {
                ForEach([AppStrings.teamsBenefitMultipleTeams, AppStrings.teamsBenefitNoSubscription,
                         AppStrings.teamsBenefitNoMinimum, AppStrings.teamsBenefitWorkspaces, AppStrings.teamsBenefitEncryption], id: \.self) { benefit in
                    HStack(alignment: .top, spacing: .spacing4) { Text("•"); Text(benefit) }.font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
            }.padding(.horizontal, .spacing5).padding(.top, .spacing6)
        } else {
            avatarEditor(isCreation: true, canManage: true)
            Button {
                Task {
                    if await controller.create(name: name, description: "", memberName: authManager.currentUser?.username,
                        icon: avatarIcon, color: avatarColor, jpeg: draftJPEG) {
                        name = ""; draftJPEG = nil; page = ""; publishNavigation()
                        if !fixture, let accountID = authManager.currentUser?.id { await TeamWorkspaceContext.shared.load(accountID: accountID) }
                    }
                }
            } label: {
                HStack(spacing: .spacing4) {
                    Icon("create", size: 20)
                    Text(controller.creating ? AppStrings.loading : controller.createdForDraft != nil && draftJPEG != nil ? AppStrings.teamsRetryUpload : AppStrings.teamsCreateAction)
                }
            }
            .buttonStyle(SettingsTeamCTAButtonStyle()).padding(.horizontal, .spacing5)
            .disabled(controller.creating || preparingPhoto)
            .accessibilityIdentifier("team-create-submit")
            if controller.creationFailed {
                OMSettingsInfoBox(kind: .warning, message: controller.imageRejected ? AppStrings.teamsImageRejected :
                    controller.createdForDraft != nil ? AppStrings.teamsUploadFailed : AppStrings.teamsCreateFailed,
                    identifier: "team-create-error")
            }
        }
    }

    @ViewBuilder private func teamDetail(_ team: TeamWorkspaceTeam) -> some View {
        if onChildNavigationChanged == nil {
            Button(AppStrings.back) { backToOverview() }.buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
        }
        // Web detail starts with management actions; its header owns the Team name.
        VStack(alignment: .leading, spacing: 0) {
        OMSettingsRow(title: AppStrings.teamsMembers, icon: "team", accessibilityIdentifier: "team-members-open") { openPage("members") }
        OMSettingsRow(title: AppStrings.teamsSecurity, icon: "safety", accessibilityIdentifier: "team-security-open") { openPage("security") }
        if team.canManage {
            OMSettingsRow(title: AppStrings.teamsName, icon: "text", accessibilityIdentifier: "team-name-open") { name = team.name; openPage("name") }
        }
        if team.canManage {
            OMSettingsRow(title: AppStrings.teamsProfileImage, icon: "image", accessibilityIdentifier: "team-avatar-open") {
                avatarIcon = team.profileImageMetadata.iconName; avatarColor = team.profileImageMetadata.backgroundColor
                draftJPEG = nil; avatarOptionsOpen = false; avatarGeneratedChanged = false; openPage("avatar")
            }
        }
        if team.role == .owner {
            OMSettingsRow(title: AppStrings.teamsDeleteTeam, icon: "delete", accessibilityIdentifier: "team-delete-open") { openPage("delete") }
        }
        if team.canViewBilling {
            OMSettingsSectionHeading(title: AppStrings.teamStorageTitle, icon: "storage")
            if let value = controller.storage {
                TeamStorageStatusView(value: value, noticeController: controller.storageNotice)
            } else if controller.storageFailed {
                OMSettingsInfoBox(kind: .warning, message: AppStrings.teamStorageError, identifier: "team-storage-error")
                Button(AppStrings.retry) { Task { await controller.loadStorage() } }
                    .buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
            } else if controller.storageLoading {
                OMSettingsInfoBox(message: AppStrings.storageLoading)
            }
        }
        }
        // Contain children so the detail identifier does not replace action identifiers.
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings-team-detail-card")
    }


    @ViewBuilder private func inviteControls(_ team: TeamWorkspaceTeam) -> some View {
        Text(AppStrings.teamsInviteMembersGuidance).font(.omSmall).foregroundStyle(Color.fontSecondary)
            .padding(.horizontal, .spacing10).accessibilityIdentifier("team-invite-members-guidance")
        OMSettingsTextInput(label: AppStrings.teamsInviteEmail, placeholder: AppStrings.teamsInviteEmail,
            value: $email, identifier: "settings-team-invite-email", email: true)
            .disabled(!team.canManage)
        if !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            Button(AppStrings.teamsInviteAction) {
                let recipient = email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                let accountID = authManager.currentUser?.id
                let server = ServerProfile.current()
                Task {
                    await controller.invite(email: recipient)
                    guard controller.selectedID == team.id, authManager.currentUser?.id == accountID,
                          ServerProfile.current() == server, controller.inviteSent != nil else { return }
                    inviteRecipient = recipient; email = ""
                }
            }
            .buttonStyle(SettingsTeamCTAButtonStyle()).padding(.horizontal, .spacing5)
            .disabled(!team.canManage || controller.inviting)
            .accessibilityIdentifier("settings-team-send-invite")
        }
        if controller.inviteFailed {
            OMSettingsInfoBox(kind: .warning, message: AppStrings.teamsInviteFailed, identifier: "settings-team-invite-result")
        } else if let sent = controller.inviteSent {
            OMSettingsInfoBox(kind: .success, message: sent ? AppStrings.teamsInviteReadyPending : AppStrings.teamsInviteReady, identifier: "settings-team-invite-result")
        }
        if !inviteRecipient.isEmpty, let url = controller.inviteURL {
            Button(AppStrings.teamsOpenEmailDraft) { openInviteEmailDraft(url: url) }
                .buttonStyle(OMSettingsButtonStyle()).padding(.horizontal, .spacing5)
                .accessibilityIdentifier("team-invite-open-email")
            Button(AppStrings.teamsCopySecureLink) { copyInviteURL(url) }
                .buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.horizontal, .spacing5)
                .accessibilityIdentifier("team-invite-copy-secure-link")
        }
        Text(AppStrings.teamsInviteSharingGuidance).font(.omSmall).foregroundStyle(Color.fontSecondary)
            .padding(.horizontal, .spacing10).accessibilityIdentifier("team-invite-sharing-guidance")
        OMSettingsRow(title: AppStrings.teamsCopyLink, icon: "copy", accessibilityIdentifier: "team-copy-invite-link") {
            inviteRecipient = ""
            let accountID = authManager.currentUser?.id
            let server = ServerProfile.current()
            Task {
                await controller.invite(email: nil)
                guard controller.selectedID == team.id, authManager.currentUser?.id == accountID,
                      ServerProfile.current() == server, !controller.inviteFailed, let url = controller.inviteURL else { return }
                copyInviteURL(url)
            }
        }.disabled(!team.canManage || controller.inviting)
        if controller.inviteURL != nil {
            OMSettingsInfoBox(message: AppStrings.teamsShareLinkInfo, identifier: "team-invite-share-link-info")
        }
    }

    private func copyInviteURL(_ url: URL) {
        #if os(iOS)
        UIPasteboard.general.string = url.absoluteString
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url.absoluteString, forType: .string)
        #endif
    }

    private func openInviteEmailDraft(url: URL) {
        guard !inviteRecipient.isEmpty else { return }
        var components = URLComponents()
        components.scheme = "mailto"; components.path = inviteRecipient
        components.queryItems = [URLQueryItem(name: "subject", value: AppStrings.teamsMailSubject),
            URLQueryItem(name: "body", value: AppStrings.teamsMailBodyIntro + "\n\n" + url.absoluteString + "\n\n" + AppStrings.teamsMailBodyPrivacy)]
        if let mailURL = components.url { openURL(mailURL) }
    }

    @ViewBuilder private func managementPage(_ team: TeamWorkspaceTeam) -> some View {
        if onChildNavigationChanged == nil { Button(AppStrings.back) { openPage("") }.buttonStyle(OMSettingsButtonStyle(secondary: true)) }
        if controller.actionFailed {
            OMSettingsInfoBox(kind: .warning, message: AppStrings.teamsLoadFailed, identifier: "team-action-error")
        }
        if page == "name" {
            OMSettingsTextInput(label: AppStrings.teamsTeamName, placeholder: team.name, value: $name, identifier: "team-edit-name-input")
            Button(AppStrings.teamsSaveName) { Task { await controller.rename(name); publishNavigation() } }
                .buttonStyle(SettingsTeamCTAButtonStyle()).padding(.horizontal, .spacing5)
                .disabled(!team.canManage || controller.actionBusy || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("team-edit-name-save")
        } else if page == "avatar" {
            avatarEditor(isCreation: false, canManage: team.canManage)
            Button(AppStrings.teamsSaveProfile) {
                Task {
                    if let jpeg = draftJPEG { await controller.uploadAvatar(jpeg) }
                    else { await controller.saveAvatar(icon: avatarIcon, color: avatarColor) }
                    if !controller.actionFailed { draftJPEG = nil; openPage("") }
                }
            }
            .buttonStyle(SettingsTeamCTAButtonStyle()).disabled(!team.canManage || controller.actionBusy || preparingPhoto || (draftJPEG == nil && !avatarGeneratedChanged))
            .accessibilityIdentifier("team-avatar-save")
        } else if page == "delete" {
            if team.role == .owner {
                OMSettingsInfoBox(kind: .warning, message: AppStrings.teamsDeleteWarning)
                OMSettingsToggleRow(title: AppStrings.teamsDeleteConfirm, isOn: $confirmed)
                Button(AppStrings.teamsDeleteTeam) { Task { await controller.deleteSelected(confirmed: confirmed); if controller.selectedID == nil { page = "" }; publishNavigation() } }
                    .buttonStyle(OMSettingsButtonStyle()).padding(.horizontal, .spacing5)
                    .disabled(!confirmed || controller.actionBusy).accessibilityIdentifier("team-delete-submit")
            }
        } else if page == "members" {
            if let management = controller.management {
                OMSettingsSectionHeading(title: AppStrings.teamsAdmins, icon: "safety")
                memberRows(management.members.filter { $0.role == .owner || $0.role == .admin })
                OMSettingsSectionHeading(title: AppStrings.teamsMembers, icon: "user")
                memberRows(management.members.filter { $0.role != .owner && $0.role != .admin })
                if team.canManage {
                    inviteControls(team)
                    if management.invites.contains(where: { ["pending", "created", "sent"].contains($0.status) }) {
                        OMSettingsSectionHeading(title: AppStrings.teamsPendingInvites, icon: "team")
                    }
                    ForEach(management.invites.filter { ["pending", "created", "sent"].contains($0.status) }) { invite in
                        OMSettingsRow(title: invite.recipient.isEmpty ? AppStrings.teamsInviteLink : invite.recipient,
                            subtitle: invite.status, icon: "delete", accessibilityIdentifier: "team-invite-revoke-\(invite.id)") { Task { await controller.revokeInvite(invite.id) } }
                    }
                }
            } else { managementState }
        } else if page == "member", let member = controller.management?.members.first(where: { $0.id == memberID }) {
            memberPortrait(member, size: 120).frame(maxWidth: .infinity).padding(.vertical, .spacing6)
            OMSettingsCard {
                OMSettingsDetailRow(label: AppStrings.teamsRoleLabel, value: member.role.rawValue)
                OMSettingsDetailRow(label: AppStrings.teamsStatusLabel, value: member.status, showsDivider: false)
            }.accessibilityIdentifier("team-member-detail")
            if team.canManage, member.role != .owner, member.userID != nil {
                OMDropdown(title: AppStrings.teamsMemberRole,
                    options: ["admin", "member", "viewer"].map { OMDropdownOption($0, label: teamRoleLabel($0)) },
                    selection: Binding(get: { member.role.rawValue }, set: { value in
                        if let role = TeamWorkspaceRole(rawValue: value) { Task { await controller.changeRole(member, role: role) } }
                    }), disabled: controller.actionBusy)
                    .accessibilityIdentifier("team-member-detail-role")
                OMSettingsToggleRow(title: AppStrings.teamsRemoveConfirm, isOn: $confirmed)
                Button(AppStrings.teamsRemoveMember) { Task { await controller.removeMember(member); if !controller.actionFailed { openPage("members") } } }
                    .buttonStyle(OMSettingsButtonStyle()).padding(.horizontal, .spacing5)
                    .disabled(!confirmed || controller.actionBusy).accessibilityIdentifier("team-member-remove")
            }
        } else if page == "security" {
            if let policy = controller.management?.security {
                securityToggle("domain_restriction", value: policy.restrictEmailDomains) { var next = policy; next.restrictEmailDomains = $0; Task { await controller.saveSecurity(next) } }
                if policy.restrictEmailDomains {
                    OMSettingsTextInput(label: AppStrings.teamsDomainPlaceholder, placeholder: AppStrings.teamsDomainPlaceholder, value: $domain, identifier: "team-security-domain-input")
                    Button(AppStrings.teamsAllowDomain) {
                        var next = policy; let value = domain.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                        if !value.isEmpty, !next.allowedEmailDomains.contains(value) { next.allowedEmailDomains.append(value); Task { await controller.saveSecurity(next); if !controller.actionFailed { domain = "" } } }
                    }.buttonStyle(OMSettingsButtonStyle()).disabled(!team.canManage || controller.actionBusy || domain.isEmpty).accessibilityIdentifier("team-security-domain-add")
                    ForEach(policy.allowedEmailDomains, id: \.self) { value in
                        OMSettingsRow(title: value, icon: "delete", accessibilityIdentifier: "team-security-domain-remove-\(value)") { var next = policy; next.allowedEmailDomains.removeAll { $0 == value }; Task { await controller.saveSecurity(next) } }.disabled(!team.canManage || controller.actionBusy)
                    }
                }
                securityToggle("signup_approval", value: policy.requireInviteLinkApproval) { var next = policy; next.requireInviteLinkApproval = $0; Task { await controller.saveSecurity(next) } }
                securityToggle("strong_auth", value: policy.requireStrongAuth) { var next = policy; next.requireStrongAuth = $0; Task { await controller.saveSecurity(next) } }
            } else { managementState }
        }
    }

    private var avatarIcons: [String] { ["team", "project", "design", "coding", "heart", "travel"] }
    private var avatarColors: [String] { ["#4d73ff", "#e35d6a", "#5aab77", "#8b62c9", "#db8f36"] }

    @ViewBuilder private func avatarEditor(isCreation: Bool, canManage: Bool) -> some View {
        let busy = controller.creating || controller.actionBusy || preparingPhoto
        ZStack(alignment: .bottomTrailing) {
            if let data = draftJPEG ?? (!isCreation && !avatarGeneratedChanged ? controller.avatarData : nil), let image = platformImage(data) {
                image.resizable().scaledToFill().frame(width: 144, height: 144).clipShape(Circle()).accessibilityIdentifier("team-avatar-uploaded-preview")
            } else { generatedPortrait(icon: avatarIcon, color: avatarColor, size: 144).accessibilityIdentifier("team-avatar-preview") }
            Button {
                draftJPEG = nil; avatarGeneratedChanged = true; avatarOptionsOpen = true
                avatarIcon = avatarIcons[((avatarIcons.firstIndex(of: avatarIcon) ?? -1) + 1) % avatarIcons.count]
                avatarColor = avatarColors[((avatarColors.firstIndex(of: avatarColor) ?? -1) + 1) % avatarColors.count]
            } label: { Icon("reload", size: 27).foregroundStyle(LinearGradient.primary).frame(width: 40, height: 40).background(Color.grey0).clipShape(Circle()).shadow(radius: 2) }
            .buttonStyle(.plain).disabled(!canManage || busy).accessibilityLabel(AppStrings.teamsChangeGeneratedAvatar).accessibilityIdentifier("team-avatar-regenerate")
        }.frame(maxWidth: .infinity).padding(.top, .spacing5).padding(.bottom, .spacing10)
        PhotosPicker(selection: $selectedPhoto, matching: .images) {
            HStack(spacing: .spacing8) {
                Icon("files", size: 24).foregroundStyle(LinearGradient.primary)
                Text(preparingPhoto ? AppStrings.loading : AppStrings.teamsSelectImage).foregroundStyle(LinearGradient.primary)
                Spacer(minLength: 0)
            }
        }
        .buttonStyle(SettingsTeamFileButtonStyle()).padding(.horizontal, .spacing5)
        .disabled(!canManage || busy).accessibilityIdentifier("team-avatar-upload")
        if avatarOptionsOpen {
            OMDropdown(title: AppStrings.teamsTeamIcon, options: zip(avatarIcons, [AppStrings.teamsIconTeam, AppStrings.teamsIconProject, AppStrings.teamsIconDesign, AppStrings.teamsIconCode, AppStrings.teamsIconHeart, AppStrings.teamsIconTravel]).map { OMDropdownOption($0.0, label: $0.1, iconName: $0.0) }, selection: $avatarIcon, disabled: busy)
                .accessibilityIdentifier("team-avatar-icon")
            OMDropdown(title: AppStrings.teamsTeamColor, options: zip(avatarColors, [AppStrings.teamsColorBlue, AppStrings.teamsColorRed, AppStrings.teamsColorGreen, AppStrings.teamsColorPurple, AppStrings.teamsColorOrange]).map { OMDropdownOption($0.0, label: $0.1) }, selection: $avatarColor, disabled: busy)
                .accessibilityIdentifier("team-avatar-color")
        }
        if draftJPEG != nil {
            Button(AppStrings.teamsUseGenerated) { draftJPEG = nil; avatarGeneratedChanged = true; photoFailed = false }
                .buttonStyle(OMSettingsButtonStyle(secondary: true)).disabled(busy).accessibilityIdentifier("team-avatar-use-generated")
        }
        if controller.imageFinalWarning {
            OMSettingsInfoBox(kind: .warning, message: AppStrings.teamsImageFinalWarning, identifier: "team-avatar-final-warning")
        }
        if photoFailed || controller.imageRejected {
            OMSettingsInfoBox(kind: .warning, message: photoFailed ? AppStrings.teamsImageOpenFailed : AppStrings.teamsImageRejected, identifier: "team-avatar-upload-error")
        }
    }

    private func generatedPortrait(icon: String, color: String, size: CGFloat) -> some View {
        let hex = color.hasPrefix("#") ? UInt32(color.dropFirst(), radix: 16) : nil
        return Icon(icon, size: size * 0.5).foregroundStyle(Color.white).frame(width: size, height: size)
            .background(Color(hex: hex ?? 0x4D73FF)).clipShape(Circle())
    }
    @ViewBuilder private func memberPortrait(_ member: SettingsTeamMember, size: CGFloat) -> some View {
        if let data = controller.memberAvatarData[member.id], let image = platformImage(data) {
            image.resizable().scaledToFill().frame(width: size, height: size).clipShape(Circle()).accessibilityIdentifier("team-member-avatar-uploaded-" + member.id)
        } else {
            generatedPortrait(icon: member.avatarIcon, color: member.avatarColor, size: size).accessibilityIdentifier("team-member-avatar-generated-" + member.id)
        }
    }

    private func loadPhoto(_ item: PhotosPickerItem?) {
        guard let item, page == "avatar" || page == "new/avatar" else { return }
        let teamID = controller.selectedID, expectedPage = page
        let accountID = authManager.currentUser?.id
        let scope = OfflineStore.shared.scopeGeneration
        let server = ServerProfile.current()
        let token = UUID(); photoGeneration = token
        preparingPhoto = true; photoFailed = false
        Task {
            defer { if photoGeneration == token { preparingPhoto = false; selectedPhoto = nil } }
            do {
                guard let data = try await item.loadTransferable(type: Data.self) else { throw NativeImageRaster.ProcessingError.invalidImage }
                let jpeg = try await Task.detached(priority: .utility) { try SettingsTeamsService.avatarJPEG(data) }.value
                guard photoGeneration == token, controller.selectedID == teamID, page == expectedPage, authManager.currentUser?.id == accountID,
                      scope == OfflineStore.shared.scopeGeneration, server == ServerProfile.current() else { return }
                draftJPEG = jpeg
            } catch { if photoGeneration == token { photoFailed = true } }
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
    private func memberRows(_ members: [SettingsTeamMember]) -> some View {
        ForEach(members) { member in
            Button { memberID = member.id; openPage("member") } label: {
                HStack(spacing: .spacing6) {
                    memberPortrait(member, size: 42)
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(member.name).font(.omP.weight(.medium)).foregroundStyle(LinearGradient.primary)
                        Text(member.role.rawValue).font(.omSmall.weight(.medium)).foregroundStyle(Color.grey60)
                    }
                    Spacer(minLength: .spacing4)
                    Icon("chevron-right", size: 16).foregroundStyle(Color.fontTertiary)
                }.padding(.horizontal, .spacing5).padding(.vertical, 5).frame(minHeight: 52).contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityIdentifier("team-member-row").accessibilityLabel(member.name)
        }
    }
    private func securityToggle(_ key: String, value: Bool, changed: @escaping (Bool) -> Void) -> some View {
        OMSettingsToggleRow(title: securityTitle(key), isOn: Binding(get: { value }, set: changed), disabled: controller.selected?.canManage != true || controller.actionBusy)
            .accessibilityIdentifier("team-security-" + key + "-toggle")
    }
    private var managementState: some View {
        Group {
            if controller.managementLoading { OMSettingsInfoBox(message: AppStrings.loading) }
            else if controller.managementFailed {
                OMSettingsInfoBox(kind: .warning, message: AppStrings.teamsLoadFailed)
                Button(AppStrings.retry) { Task { await controller.loadManagement() } }.buttonStyle(OMSettingsButtonStyle(secondary: true)).accessibilityIdentifier("team-management-retry")
            }
        }
    }
    private func openPage(_ value: String) { page = value; confirmed = false; publishNavigation() }

    private func load() async {
        guard let accountID = authManager.currentUser?.id else {
            controller.reset(); onChildNavigationChanged?(nil)
            NotificationCenter.default.post(name: .openAuth, object: nil)
            return
        }
        await controller.load(accountID: accountID, initialTeamID: initialTeamID == "new" ? nil : initialTeamID)
        if initialTeamID == "new", !controller.failed { controller.beginCreation(); page = "new" }
        publishNavigation()
    }
    private func backToOverview() {
        guard !controller.creating else { return }
        controller.cancelCreationCheck()
        email = ""; inviteRecipient = ""; memberID = nil; confirmed = false
        if !page.isEmpty {
            photoGeneration = UUID(); preparingPhoto = false; selectedPhoto = nil
            page = page == "member" ? "members" : page == "new/avatar" ? "new" : ""
            publishNavigation(); return
        }
        Task { await controller.select(nil); publishNavigation() }
    }
    private func teamRoleLabel(_ role: String) -> String {
        switch role { case "admin": return AppStrings.teamsRoleAdmin; case "viewer": return AppStrings.teamsRoleViewer; default: return AppStrings.teamsRoleMember }
    }
    private func securityTitle(_ key: String) -> String {
        switch key { case "domain_restriction": return AppStrings.teamsDomainRestriction; case "signup_approval": return AppStrings.teamsSignupApproval; default: return AppStrings.teamsStrongAuth }
    }
    private var pageTitle: String {
        switch page {
        case "new": return AppStrings.teamsCreateTitle
        case "new/avatar", "avatar": return AppStrings.teamsProfileImage
        case "members": return AppStrings.teamsMembers
        case "member": return controller.management?.members.first(where: { $0.id == memberID })?.name ?? AppStrings.teamsMemberFallback
        case "name": return AppStrings.teamsName
        case "delete": return AppStrings.teamsDeleteTeam
        default: return AppStrings.teamsSecurity
        }
    }
    private func publishNavigation() {
        onChildNavigationChanged?(controller.selectedID == nil && page.isEmpty ? nil : SettingsChildBannerNavigation(
            title: page.isEmpty ? (controller.selected?.name ?? AppStrings.teamsTeamNotFound) : pageTitle, description: "", onBack: backToOverview))
    }
}

// Typed Teams accessors reuse the deployed canonical settings/teams_ui.yml copy.
// Kept beside the owned Teams surface to avoid parallel AppStrings.swift edits.
extension AppStrings {
    static var teamsPendingInvites: String { localized("settings.teams_ui.pending_invites") }
    static var teamsMailBodyPrivacy: String { localized("settings.teams_ui.mail_body_privacy") }
    static var teamsMailBodyIntro: String { localized("settings.teams_ui.mail_body_intro") }
    static var teamsMailSubject: String { localized("settings.teams_ui.mail_subject") }
    static var teamsOpenEmailDraft: String { localized("settings.teams_ui.open_email_draft") }
    static var teamsShareLinkInfo: String { localized("settings.teams_ui.share_link_info") }
    static var teamsInviteSharingGuidance: String { localized("settings.teams_ui.invite_sharing_guidance") }
    static var teamsInviteMembersGuidance: String { localized("settings.teams_ui.invite_members_guidance") }
    static var teamsTitle: String { localized("settings.teams") }
    static var teamsRoleSuffix: String { localized("settings.teams_ui.role_suffix") }
    static var teamsMemberFallback: String { localized("settings.teams_ui.team_member") }
    static var teamsAdmins: String { localized("settings.teams_ui.admins") }
    static var teamsAllowDomain: String { localized("settings.teams_ui.allow_domain") }
    static var teamsBenefitEncryption: String { localized("settings.teams_ui.benefit_encryption") }
    static var teamsBenefitMultipleTeams: String { localized("settings.teams_ui.benefit_multiple_teams") }
    static var teamsBenefitNoMinimum: String { localized("settings.teams_ui.benefit_no_minimum") }
    static var teamsBenefitNoSubscription: String { localized("settings.teams_ui.benefit_no_subscription") }
    static var teamsBenefitWorkspaces: String { localized("settings.teams_ui.benefit_workspaces") }
    static var teamsChangeGeneratedAvatar: String { localized("settings.teams_ui.change_generated_avatar") }
    static var teamsColorBlue: String { localized("settings.teams_ui.color_blue") }
    static var teamsColorGreen: String { localized("settings.teams_ui.color_green") }
    static var teamsColorOrange: String { localized("settings.teams_ui.color_orange") }
    static var teamsColorPurple: String { localized("settings.teams_ui.color_purple") }
    static var teamsColorRed: String { localized("settings.teams_ui.color_red") }
    static var teamsContinue: String { localized("settings.teams_ui.continue") }
    static var teamsCopyLink: String { localized("settings.teams_ui.copy_link") }
    static var teamsCopySecureLink: String { localized("settings.teams_ui.copy_secure_link") }
    static var teamsCreateAction: String { localized("settings.teams_ui.create_action") }
    static var teamsCreateFailed: String { localized("settings.teams_ui.create_failed") }
    static var teamsCreateTitle: String { localized("settings.teams_ui.create_title") }
    static var teamsDeleteConfirm: String { localized("settings.teams_ui.delete_confirm") }
    static var teamsDeleteTeam: String { localized("settings.teams_ui.delete_team") }
    static var teamsDeleteWarning: String { localized("settings.teams_ui.delete_warning") }
    static var teamsDescription: String { localized("settings.teams_ui.description") }
    static var teamsDomainPlaceholder: String { localized("settings.teams_ui.domain_placeholder") }
    static var teamsDomainRestriction: String { localized("settings.teams_ui.domain_restriction") }
    static var teamsEmptyTeams: String { localized("settings.teams_ui.empty_teams") }
    static var teamsIconCode: String { localized("settings.teams_ui.icon_code") }
    static var teamsIconDesign: String { localized("settings.teams_ui.icon_design") }
    static var teamsIconHeart: String { localized("settings.teams_ui.icon_heart") }
    static var teamsIconProject: String { localized("settings.teams_ui.icon_project") }
    static var teamsIconTeam: String { localized("settings.teams_ui.icon_team") }
    static var teamsIconTravel: String { localized("settings.teams_ui.icon_travel") }
    static var teamsImageOpenFailed: String { localized("settings.teams_ui.image_open_failed") }
    static var teamsImageFinalWarning: String { localized("settings.teams_ui.image_final_warning") }
    static var teamsImageRejected: String { localized("settings.teams_ui.image_rejected") }
    static var teamsInviteAction: String { localized("settings.teams_ui.invite_action") }
    static var teamsInviteEmail: String { localized("settings.teams_ui.invite_email") }
    static var teamsInviteFailed: String { localized("settings.teams_ui.invite_failed") }
    static var teamsInviteLink: String { localized("settings.teams_ui.invite_link") }
    static var teamsInviteMembers: String { localized("settings.teams_ui.invite_members") }
    static var teamsInviteReady: String { localized("settings.teams_ui.invite_ready") }
    static var teamsInviteReadyPending: String { localized("settings.teams_ui.invite_ready_pending") }
    static var teamsLoadFailed: String { localized("settings.teams_ui.load_failed") }
    static var teamsLoadingTeams: String { localized("settings.teams_ui.loading_teams") }
    static var teamsMemberRole: String { localized("settings.teams_ui.member_role") }
    static var teamsMembers: String { localized("settings.teams_ui.members") }
    static var teamsName: String { localized("settings.teams_ui.name") }
    static var teamsNameCheckFailed: String { localized("settings.teams_ui.name_check_failed") }
    static var teamsNamePlaceholder: String { localized("settings.teams_ui.name_placeholder") }
    static var teamsNewTeam: String { localized("settings.teams_ui.new_team") }
    static var teamsPersonalScopeInfo: String { localized("settings.teams_ui.personal_scope_info") }
    static var teamsProfileImage: String { localized("settings.teams_ui.profile_image") }
    static var teamsRemoveConfirm: String { localized("settings.teams_ui.remove_confirm") }
    static var teamsRemoveMember: String { localized("settings.teams_ui.remove_member") }
    static var teamsRetryUpload: String { localized("settings.teams_ui.retry_upload") }
    static var teamsRoleAdmin: String { localized("settings.teams_ui.role_admin") }
    static var teamsRoleLabel: String { localized("settings.teams_ui.role_label") }
    static var teamsRoleMember: String { localized("settings.teams_ui.role_member") }
    static var teamsRoleViewer: String { localized("settings.teams_ui.role_viewer") }
    static var teamsSaveName: String { localized("settings.teams_ui.save_name") }
    static var teamsSaveProfile: String { localized("settings.teams_ui.save_profile") }
    static var teamsSecurity: String { localized("settings.teams_ui.security") }
    static var teamsSelectImage: String { localized("settings.teams_ui.select_image") }
    static var teamsSignupApproval: String { localized("settings.teams_ui.signup_approval") }
    static var teamsStatusLabel: String { localized("settings.teams_ui.status_label") }
    static var teamsStrongAuth: String { localized("settings.teams_ui.strong_auth") }
    static var teamsTeamColor: String { localized("settings.teams_ui.team_color") }
    static var teamsTeamCredits: String { localized("settings.teams_ui.team_credits") }
    static var teamsTeamIcon: String { localized("settings.teams_ui.team_icon") }
    static var teamsTeamName: String { localized("settings.teams_ui.team_name") }
    static var teamsTeamNotFound: String { localized("settings.teams_ui.team_not_found") }
    static var teamsUploadFailed: String { localized("settings.teams_ui.upload_failed") }
    static var teamsUseGenerated: String { localized("settings.teams_ui.use_generated") }
}


// Canonical SettingsButton.cta and SettingsFileUpload, composed locally to keep
// this bounded parity delta inside the owned Teams surface.
private struct SettingsTeamCTAButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.omP.weight(.semibold)).foregroundStyle(Color.fontButton)
            .padding(.horizontal, .spacing12).padding(.vertical, .spacing5)
            .frame(maxWidth: .infinity, minHeight: CGFloat.spacing20 + .spacing1)
            .background(configuration.isPressed ? Color.buttonPrimaryPressed : Color.buttonPrimary)
            .clipShape(RoundedRectangle(cornerRadius: .radius7))
            .opacity(enabled ? 1 : 0.5)
    }
}
private struct SettingsTeamFileButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.omP.weight(.medium))
            .padding(.horizontal, .spacing12).padding(.vertical, .spacing6)
            .frame(maxWidth: .infinity, minHeight: CGFloat.spacing24 + .spacing3)
            .background(Color.grey0).clipShape(Capsule())
            .shadow(color: .black.opacity(0.1), radius: 2, y: 2)
            .opacity(enabled ? 1 : 0.5)
    }
}


#if DEBUG
// Complete the existing in-memory GUI fixture's invitation result so the real
// production email/copy controls are exercised; this URL never reaches a server.
extension SettingsTeamsUITestService {
    func invitation(team: TeamWorkspaceTeam, email: String?, fence: TeamWorkspaceFence) async throws -> SettingsTeamInvitation {
        try await fence.check()
        guard team.canManage else { throw SettingsTeamsError.permissionDenied }
        return SettingsTeamInvitation(url: URL(string: "https://example.invalid/team-invite/synthetic#key=ui-test-fragment"), delivered: true)
    }
}
#endif
