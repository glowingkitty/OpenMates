// Temporary native debug-log sharing backed by the real debug-session lifecycle.
// Activating starts sanitized NativeLogForwarder uploads tagged with the server's
// short debugging ID; stopping revokes the server session before local shutdown.
// Failures remain visible and never report false activation or local-only success.
// Product controls use OpenMates primitives; clipboard access is OS-owned.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsShareDebugLogs.svelte
// CSS:     frontend/packages/ui/src/components/settings/SettingsShareDebugLogs.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct SettingsShareDebugLogsView: View {
    @StateObject private var controller = PrivacyDebugSessionController()
    @State private var copied = false

    var body: some View {
        OMSettingsPage(title: AppStrings.privacyShareDebugLogs, showsHeader: false) {
            Text(AppStrings.privacyDebugSessionDescription)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .lineSpacing(3)
                .padding(.horizontal, .spacing8)

            if controller.session.active {
                activeSession
            } else {
                activationForm
            }

            if let errorMessage = controller.errorMessage {
                Text(errorMessage)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.horizontal, .spacing8)
            }
        }
        .accessibilityIdentifier("privacy-debug-session-page")
        .task {
            if !PrivacySettingsUITestFixture.enabled { await controller.load() }
        }
    }

    private var activationForm: some View {
        OMSettingsSection(AppStrings.privacyDebugSessionDuration, icon: "time") {
            OMDropdown(
                title: AppStrings.privacyDebugSessionDuration,
                options: PrivacyDebugDuration.allCases.map { OMDropdownOption($0.rawValue, label: $0.label) },
                selection: Binding(
                    get: { controller.selectedDuration.rawValue },
                    set: { controller.selectedDuration = PrivacyDebugDuration(rawValue: $0) ?? .fiveMinutes }
                ),
                disabled: controller.isLoading
            )
            .accessibilityIdentifier("privacy-debug-session-duration")

            Button {
                Task {
                    if PrivacySettingsUITestFixture.enabled { return }
                    await controller.activate()
                }
            } label: {
                Text(controller.isLoading ? AppStrings.privacyDebugSessionActivating : AppStrings.privacyDebugSessionStart)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(controller.isLoading)
            .accessibilityIdentifier("privacy-debug-session-start")
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing4)
        }
    }

    private var activeSession: some View {
        OMSettingsSection(AppStrings.privacyDebugSessionActive, icon: "log") {
            if let debuggingId = controller.session.debuggingId {
                VStack(alignment: .leading, spacing: .spacing4) {
                    Text(AppStrings.privacyDebugSessionId)
                        .font(.omXs.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary)

                    HStack(spacing: .spacing4) {
                        Text(debuggingId)
                            .font(.omP.weight(.semibold))
                            .foregroundStyle(Color.fontPrimary)
                            .textSelection(.enabled)
                            .padding(.horizontal, .spacing6)
                            .padding(.vertical, .spacing4)
                            .background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius3))

                        Button(copied ? AppStrings.copied : AppStrings.copy) {
                            copy(debuggingId)
                        }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .accessibilityIdentifier("privacy-debug-session-copy")
                    }

                    Text(AppStrings.privacyDebugSessionShareHint)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)

                    Text(expiryLabel)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                }
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing4)
            }

            Button {
                Task { await controller.deactivate() }
            } label: {
                Text(controller.isLoading ? AppStrings.privacyDebugSessionStopping : AppStrings.privacyDebugSessionStop)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMSecondaryButtonStyle())
            .disabled(controller.isLoading)
            .accessibilityIdentifier("privacy-debug-session-stop")
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing4)
        }
    }

    private var expiryLabel: String {
        guard let expiresAt = controller.session.expiresAt,
              let date = ISO8601DateFormatter().date(from: expiresAt) else {
            return AppStrings.privacyDebugSessionNoExpiry
        }
        let seconds = max(0, Int(date.timeIntervalSinceNow))
        if seconds < 3_600 { return AppStrings.privacyDebugSessionMinutesRemaining(seconds / 60) }
        if seconds < 86_400 { return AppStrings.privacyDebugSessionHoursRemaining(seconds / 3_600) }
        return AppStrings.privacyDebugSessionDaysRemaining(seconds / 86_400)
    }

    private func copy(_ value: String) {
        #if os(iOS)
        UIPasteboard.general.string = value
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
        #endif
        copied = true
        Task {
            do {
                try await Task.sleep(for: .seconds(2))
            } catch {
                return
            }
            copied = false
        }
    }
}

private extension PrivacyDebugDuration {
    @MainActor var label: String {
        switch self {
        case .fiveMinutes: return AppStrings.privacyDebugDuration5Minutes
        case .oneHour: return AppStrings.privacyDebugDuration1Hour
        case .threeDays: return AppStrings.privacyDebugDuration3Days
        case .sevenDays: return AppStrings.privacyDebugDuration7Days
        case .noLimit: return AppStrings.privacyDebugDurationNoLimit
        }
    }
}
