// Canonical native counterparts of settings/elements/ on the web.
// Web sources: frontend/packages/ui/src/components/settings/elements/SettingsInfoBox.svelte
//              frontend/packages/ui/src/components/settings/elements/SettingsDetailRow.svelte
//              frontend/packages/ui/src/components/settings/elements/SettingsCard.svelte
//              frontend/packages/ui/src/components/settings/elements/SettingsInput.svelte
//              frontend/packages/ui/src/components/settings/elements/SettingsTextarea.svelte
//              frontend/packages/ui/src/components/settings/elements/SettingsButton.svelte
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.composition.canonical-and-accessible, settings-ui.parity.web-apple-shell

// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.surface.semantic-parity

import SwiftUI

extension Color {
    // Exact CSS fallback semantics used by SettingsInfoBox; these stay the same in both themes.
    static let settingsInfoAccent = Color(hex: 0x2196F3)
    static let settingsSuccessAccent = Color(hex: 0x4CAF50)
    static let settingsWarningIcon = Color(hex: 0x856404)
    // Canonical primary-start token, also emitted in GradientTokens.generated.swift.
    static let settingsPrimaryStart = Color(hex: 0x4867CD)
}

struct OMSettingsInfoBox: View {
    enum Kind { case info, warning, success }
    var kind: Kind = .info
    var title: String? = nil
    let message: String
    var identifier: String? = nil
    private var accent: Color {
        switch kind { case .info: .settingsInfoAccent; case .warning: .warning; case .success: .settingsSuccessAccent }
    }

    var body: some View {
        HStack(alignment: .top, spacing: .spacing6) {
            Icon(kind == .info ? "info" : kind == .success ? "check" : "warning", size: 20)
                .foregroundStyle(kind == .warning ? Color.settingsWarningIcon : accent)
                .padding(.top, .spacing1)
            VStack(alignment: .leading, spacing: .spacing4) {
                if let title { Text(title).font(.omP.weight(.bold)) }
                Text(message).font(.omP.weight(.medium)).lineSpacing(2.4)
            }
            .foregroundStyle(Color.fontPrimary)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, .spacing8)
        .padding(.horizontal, CGFloat.spacing10 - CGFloat.spacing1) // SettingsInfoBox.svelte: 1.125rem (18pt).
        .padding(.leading, .spacing2)
        .background(Color.grey0)
        .overlay(alignment: .leading) { accent.frame(width: .spacing2) }
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 4)
        .padding(.horizontal, .spacing5)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier ?? "settings-info-box")
    }
}

struct OMSettingsCard<Content: View>: View {
    @ViewBuilder let content: Content
    let horizontalPadding: CGFloat
    let verticalPadding: CGFloat
    let horizontalMargin: CGFloat
    init(horizontalPadding: CGFloat = .spacing10, verticalPadding: CGFloat = .spacing10,
         horizontalMargin: CGFloat = .spacing5, @ViewBuilder content: () -> Content) {
        self.content = content(); self.horizontalPadding = horizontalPadding
        self.verticalPadding = verticalPadding; self.horizontalMargin = horizontalMargin
    }
    var body: some View {
        VStack(spacing: 0) { content }
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, verticalPadding)
            .frame(maxWidth: .infinity)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey25, lineWidth: 1))
            .padding(.horizontal, horizontalMargin)
    }
}

struct OMSettingsDetailRow: View {
    let label: String
    let value: String
    var muted = false
    var highlight = false
    var showsDivider = true
    var body: some View {
        HStack(spacing: .spacing8) {
            Text(label).foregroundStyle(Color.fontSecondary)
            Spacer(minLength: 0)
            Text(value).foregroundStyle(highlight ? Color.settingsPrimaryStart : Color.fontPrimary)
                .multilineTextAlignment(.trailing)
        }
        .font(.omP.weight(.medium))
        .padding(.vertical, .spacing4)
        .frame(maxWidth: .infinity)
        .overlay(alignment: .bottom) { if showsDivider { Color.grey20.frame(height: 1) } }
        .opacity(muted ? 0.7 : 1)
    }
}

struct OMSettingsButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var secondary = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omP.weight(.semibold))
            .foregroundStyle(secondary ? Color.fontPrimary : Color.grey0)
            .padding(.horizontal, .spacing12)
            .padding(.vertical, .spacing6)
            .background(secondary ? AnyShapeStyle(Color.grey0) : AnyShapeStyle(LinearGradient.primary))
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .overlay(RoundedRectangle(cornerRadius: 24).stroke(secondary ? Color.grey30 : .clear, lineWidth: 1))
            .shadow(color: .black.opacity(secondary ? 0 : 0.1), radius: 4, x: 0, y: 4)
            .opacity(enabled ? 1 : 0.5)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .omClickablePointer()
    }
}

struct OMSettingsTextInput: View {
    let label: String
    let placeholder: String
    @Binding var value: String
    let identifier: String
    var multiline = false
    var email = false
    var secure = false
    @FocusState private var focused: Bool
    var body: some View {
        Group {
            if secure {
                SecureField(placeholder, text: $value)
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    #endif
            } else if multiline {
                TextField(placeholder, text: $value, axis: .vertical)
                    .lineLimit(3...8)
                    .frame(minHeight: 146, alignment: .top)
            } else {
                TextField(placeholder, text: $value)
                    #if os(iOS)
                    .keyboardType(email ? .emailAddress : .default)
                    .textInputAutocapitalization(email ? .never : .sentences)
                    .autocorrectionDisabled(email)
                    #endif
            }
        }
        .textFieldStyle(.plain)
        .focused($focused)
        .onSubmit { if !multiline { focused = false } }
        .font(.omP.weight(.medium))
        .foregroundStyle(Color.fontPrimary)
        // Exact canonical SettingsInput/SettingsTextarea CSS: 17px by 23px, 24px radius.
        .padding(.vertical, 17)
        .padding(.horizontal, 23)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 4)
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(focused ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.clear), lineWidth: 2))
        .accessibilityLabel(label)
        .accessibilityIdentifier(identifier)
        .padding(.horizontal, .spacing5)
    }
}

// Web source: settings/elements/SettingsProgressBar.svelte — .progress-track
// is 0.5rem high with a 0.25rem radius and 0.625rem horizontal inset.
struct OMSettingsProgressBar: View {
    let value: Double
    var warning = false
    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: .radius1).fill(Color.grey20)
                RoundedRectangle(cornerRadius: .radius1)
                    .fill(warning ? Color.warning : Color.settingsPrimaryStart)
                    .frame(width: geometry.size.width * min(1, max(0, value / 100)))
            }
        }
        .frame(height: .spacing4)
        .padding(.horizontal, .spacing5)
        .accessibilityLabel(AppStrings.storage)
        .accessibilityValue("\(Int(min(100, max(0, value))))%")
    }
}
