// Native account and guest Learning Mode management for Apple Settings.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/learning-mode/SettingsLearningModeSetup.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsPageContainer.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsDropdown.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsLearningModeView: View {
    let isAuthenticated: Bool
    @ObservedObject var guestSession: LearningModeGuestSession
    @ObservedObject private var controller: LearningModeController
    @State private var selectedAgeGroup = LearningModeAgeGroup.age13To15.rawValue
    @State private var passcode = ""

    init(
        isAuthenticated: Bool,
        guestSession: LearningModeGuestSession,
        controller: LearningModeController = LearningModeController()
    ) {
        self.isAuthenticated = isAuthenticated
        self.guestSession = guestSession
        self.controller = controller
    }

    private var status: LearningModeStatus {
        isAuthenticated ? controller.status : guestSession.status
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                statusBox

                if !status.enabled {
                    VStack(alignment: .leading, spacing: .spacing4) {
                        sectionHeading(AppStrings.learningModeAgeGroup, icon: "user")
                        OMDropdown(
                            title: AppStrings.learningModeAgeGroup,
                            options: LearningModeAgeGroup.allCases.map {
                                OMDropdownOption($0.rawValue, label: ageGroupLabel($0))
                            },
                            selection: $selectedAgeGroup,
                            disabled: controller.isLoading
                        )
                        .accessibilityIdentifier("learning-mode-age-group-dropdown")
                    }
                }

                if isAuthenticated {
                    VStack(alignment: .leading, spacing: .spacing4) {
                        sectionHeading(
                            status.enabled ? AppStrings.learningModeDisablePasscodeLabel : AppStrings.learningModeEnablePasscodeLabel,
                            icon: "lock"
                        )
                        SecureField(
                            status.enabled ? AppStrings.learningModeDisablePasscodePlaceholder : AppStrings.learningModeEnablePasscodePlaceholder,
                            text: $passcode
                        )
                        .textFieldStyle(OMTextFieldStyle())
                        .accessibilityLabel(
                            status.enabled ? AppStrings.learningModeDisablePasscodeLabel : AppStrings.learningModeEnablePasscodeLabel
                        )
                        .accessibilityIdentifier("learning-mode-passcode-input")
                    }
                }

                Button(action: submit) {
                    Text(status.enabled ? AppStrings.learningModeDisableButton : AppStrings.learningModeEnableButton)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(controller.isLoading || (isAuthenticated && passcode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
                .accessibilityIdentifier(status.enabled ? "learning-mode-disable-button" : "learning-mode-enable-button")
            }
            .padding(.spacing8)
        }
        .background(Color.grey0)
        .accessibilityIdentifier("learning-mode-settings-page")
        .task {
            guard isAuthenticated, !controller.hasLoaded else { return }
            await controller.loadAccountStatus()
            if let ageGroup = controller.status.ageGroup {
                selectedAgeGroup = ageGroup.rawValue
            }
        }
    }

    private var statusBox: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(status.enabled ? AppStrings.learningModeActive : AppStrings.learningModeInactive)
                .font(.omP.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
            Text(statusDescription)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)

            if status.isLocked {
                Text(AppStrings.learningModeLocked)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.error)
                    .accessibilityIdentifier("learning-mode-lockout-message")
            } else if status.failedAttempts > 0 {
                Text(AppStrings.learningModeAttemptsRemaining(
                    max(0, LearningModeStatus.maximumDeactivationAttempts - status.failedAttempts)
                ))
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.error)
                    .accessibilityIdentifier("learning-mode-attempts-remaining")
            } else if let error = controller.error {
                Text(error == .load ? AppStrings.learningModeLoadError : AppStrings.learningModeSaveError)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.error)
                    .accessibilityIdentifier("learning-mode-error")
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(status.enabled ? Color.warning.opacity(0.1) : Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }

    private var statusDescription: String {
        if isAuthenticated {
            return status.enabled ? AppStrings.learningModeActiveDetail : AppStrings.learningModeInactiveDetail
        }
        return status.enabled ? AppStrings.learningModeGuestActiveDetail : AppStrings.learningModeGuestInactiveDetail
    }

    private func sectionHeading(_ title: String, icon: String) -> some View {
        HStack(spacing: .spacing4) {
            Icon(icon, size: 20).foregroundStyle(Color.fontSecondary)
            Text(title).font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
        }
    }

    private func ageGroupLabel(_ ageGroup: LearningModeAgeGroup) -> String {
        switch ageGroup {
        case .under10: return AppStrings.learningModeAgeUnder10
        case .age10To12: return AppStrings.learningModeAge10To12
        case .age13To15: return AppStrings.learningModeAge13To15
        case .age16To18: return AppStrings.learningModeAge16To18
        case .adult: return AppStrings.learningModeAgeAdult
        }
    }

    private func submit() {
        guard let ageGroup = LearningModeAgeGroup(rawValue: selectedAgeGroup) else { return }
        if !isAuthenticated {
            status.enabled ? guestSession.deactivate() : guestSession.activate(ageGroup: ageGroup)
            return
        }

        let trimmedPasscode = passcode.trimmingCharacters(in: .whitespacesAndNewlines)
        Task {
            if status.enabled {
                await controller.deactivateAccount(passcode: trimmedPasscode)
            } else {
                await controller.activateAccount(passcode: trimmedPasscode, ageGroup: ageGroup)
            }
            if controller.error == nil { passcode = "" }
        }
    }
}
