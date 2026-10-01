// Native Support provides information and team contact.
// Legacy contribution deep links resolve to this hub; payments are not offered.

import SwiftUI

// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.navigation.parent-return, settings-ui.parity.web-apple-shell
struct SettingsSupportView: View {
    @Environment(\.openURL) private var openURL
    var onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)? = nil

    nonisolated static let contactEmail = "support@openmates.org"
    nonisolated static var contactURL: URL? { URL(string: "mailto:" + contactEmail) }

    init(deepLinkPath: String? = nil, onChildNavigationChanged: ((SettingsChildBannerNavigation?) -> Void)? = nil) {
        // Keep the settings router compatible with existing support child links.
        // All paths display the contact hub without allocating a payment order.
        self.onChildNavigationChanged = onChildNavigationChanged
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.settingsSupport, showsHeader: false,
            contentHorizontalPadding: 0, contentVerticalSpacing: 0) {
            OMSettingsInfoBox(message: AppStrings.localized("settings.support.description"))
                .accessibilityIdentifier("settings-support-information")
            OMSettingsSection {
                OMSettingsRow(title: AppStrings.email, subtitleTop: Self.contactEmail,
                    icon: "mail", showsChevron: false,
                    accessibilityIdentifier: "settings-support-contact-row") {
                    if let url = Self.contactURL { openURL(url) }
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings-support-hub")
        .onAppear { onChildNavigationChanged?(nil) }
        .onDisappear { onChildNavigationChanged?(nil) }
    }
}
