// First-activation Incognito explainer for native Apple Settings.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/incognito/SettingsIncognitoInfo.svelte
// CSS:     frontend/packages/ui/src/styles/icons.css — .subsetting_icon.incognito
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsIncognitoInfoView: View {
    let onActivate: () -> Void
    let onCancel: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing12) {
                HStack(spacing: .spacing6) {
                    Icon("incognito", size: 44)
                        .foregroundStyle(LinearGradient.incognito)
                        .accessibilityHidden(true)
                    Text(AppStrings.settingsIncognito)
                        .font(.omH2.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                }
                .padding(.bottom, .spacing8)
                .overlay(alignment: .bottom) {
                    Rectangle().fill(Color.grey30).frame(height: 1)
                }

                Text(AppStrings.incognitoExplainerDescription)
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)

                VStack(alignment: .leading, spacing: .spacing8) {
                    feature(AppStrings.incognitoExplainerDeviceSpecific, icon: "check")
                    feature(AppStrings.incognitoExplainerNotStored, icon: "check")
                    feature(AppStrings.incognitoExplainerSessionOnly, icon: "check")
                    feature(AppStrings.incognitoExplainerNoRecovery, icon: "warning")
                }

                HStack(alignment: .top, spacing: .spacing6) {
                    Icon("warning", size: 24)
                        .foregroundStyle(Color.warning)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: .spacing4) {
                        Text(AppStrings.incognitoExplainerWarningTitle)
                            .font(.omP.weight(.semibold))
                            .foregroundStyle(Color.fontPrimary)
                        Text(AppStrings.incognitoExplainerWarningProviders)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontSecondary)
                        Text(AppStrings.incognitoExplainerWarningPersonalInfo)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
                .padding(.spacing8)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .overlay(alignment: .leading) {
                    Rectangle().fill(Color.warning).frame(width: 4)
                }

                VStack(spacing: .spacing4) {
                    Button(action: onActivate) {
                        Text(AppStrings.incognitoExplainerUnderstood)
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .accessibilityIdentifier("incognito-activate-button")

                    Button(action: onCancel) {
                        Text(AppStrings.cancel).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("incognito-cancel-button")
                }
                .padding(.top, .spacing8)
                .overlay(alignment: .top) {
                    Rectangle().fill(Color.grey30).frame(height: 1)
                }
            }
            .padding(.spacing10)
        }
        .accessibilityIdentifier("incognito-info-page")
    }

    private func feature(_ text: String, icon: String) -> some View {
        HStack(alignment: .top, spacing: .spacing6) {
            Icon(icon, size: 24)
                .foregroundStyle(Color.buttonPrimary)
                .accessibilityHidden(true)
            Text(text)
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
    }
}
