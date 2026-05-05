// OpenMates custom design primitives — replacements for native iOS controls.
// These match the web app's Svelte components and CSS custom properties exactly.
// Never use Form, List, Toggle, Picker, NavigationStack, etc. in product UI — use these instead.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/elements/SettingsItem.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsSectionHeading.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsConsentToggle.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsDropdown.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsConfirmBlock.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsPageContainer.svelte
//          frontend/packages/ui/src/components/Toggle.svelte
// CSS:     Toggle: 52x32 track, 24px thumb, grey-30 off / primary gradient on
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

private struct OMSettingsScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat { 0 }

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

struct OMSettingsScrollOffsetHandler: @unchecked Sendable {
    var callback: (@MainActor @Sendable (CGFloat) -> Void)?

    init(_ callback: (@MainActor @Sendable (CGFloat) -> Void)? = nil) {
        self.callback = callback
    }
}

private struct OMSettingsScrollOffsetHandlerKey: EnvironmentKey {
    static var defaultValue: OMSettingsScrollOffsetHandler { OMSettingsScrollOffsetHandler() }
}

extension EnvironmentValues {
    var omSettingsScrollOffsetHandler: OMSettingsScrollOffsetHandler {
        get { self[OMSettingsScrollOffsetHandlerKey.self] }
        set { self[OMSettingsScrollOffsetHandlerKey.self] = newValue }
    }
}

// MARK: - OMToggle
// Web source: Toggle.svelte — 52x32 pill track, 24px white circle thumb
// OFF = grey-30 track, ON = primary gradient (#4867cd->#5a85eb), 0.3s animation
// Track: inset shadow (inset 0 2px 4px rgba(0,0,0,0.2)), simulated via inner stroke overlay
// Thumb: outer shadow (0 2px 4px rgba(0,0,0,0.2))

struct OMToggle: View {
    @Binding var isOn: Bool
    var disabled = false

    private let trackWidth: CGFloat = 52
    private let trackHeight: CGFloat = 32
    private let thumbSize: CGFloat = 24
    private let thumbPadding: CGFloat = 4

    var body: some View {
        Button {
            guard !disabled else { return }
            withAnimation(.easeInOut(duration: 0.3)) {
                isOn.toggle()
            }
        } label: {
            ZStack(alignment: isOn ? .trailing : .leading) {
                // Track — OFF: grey30 solid, ON: primary gradient
                RoundedRectangle(cornerRadius: trackHeight / 2)
                    .fill(Color.grey30)
                    .overlay(
                        Group {
                            if isOn {
                                RoundedRectangle(cornerRadius: trackHeight / 2)
                                    .fill(LinearGradient.primary)
                            }
                        }
                    )
                    .frame(width: trackWidth, height: trackHeight)
                    // Inset shadow simulation — web CSS: inset 0 2px 4px rgba(0,0,0,0.2)
                    // SwiftUI has no native inset shadow; approximate with inner stroke + blur
                    .overlay(
                        RoundedRectangle(cornerRadius: trackHeight / 2)
                            .stroke(Color.black.opacity(0.15), lineWidth: 1)
                            .blur(radius: 2)
                            .offset(y: 1)
                            .mask(RoundedRectangle(cornerRadius: trackHeight / 2))
                    )

                // Thumb — white circle, outer shadow (0 2px 4px rgba(0,0,0,0.2))
                Circle()
                    .fill(Color.white)
                    .frame(width: thumbSize, height: thumbSize)
                    .shadow(color: .black.opacity(0.2), radius: 2, x: 0, y: 2)
                    .padding(thumbPadding)
            }
        }
        .buttonStyle(.plain)
        .opacity(disabled ? 0.5 : 1)
        .allowsHitTesting(!disabled)
        .accessibilityAddTraits(.isToggle)
        .accessibilityValue(isOn ? "On" : "Off")
    }
}

// MARK: - OMSettingsToggleRow
// Convenience: OMSettingsRow + OMToggle combined in a single row
// Web source: SettingsItem.svelte — padding: 0.75rem 0.625rem = 12pt vert / 10pt horiz, gap: 0.75rem = 12pt

struct OMSettingsToggleRow: View {
    let title: String
    var subtitle: String?
    var icon: String?
    @Binding var isOn: Bool
    var disabled = false

    var body: some View {
        HStack(spacing: 0) {
            if let icon {
                // 44x44 icon with grey gradient bg (Mode A), colored icon at 50% (22pt)
                Icon(icon, size: 22)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(width: 44, height: 44)
                    .background(
                        LinearGradient(
                            colors: [Color.grey20, Color.grey30],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    .padding(.trailing, .spacing6)
            }

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(title)
                    .font(.omP.weight(.medium))
                    .foregroundStyle(Color.fontPrimary)
                if let subtitle {
                    Text(subtitle)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(2)
                }
            }

            Spacer(minLength: .spacing4)

            OMToggle(isOn: $isOn, disabled: disabled)
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing2)
        .frame(minHeight: 40)
        .contentShape(Rectangle())
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .accessibilityLabel(title)
    }
}

// MARK: - OMDropdown
// Web source: SettingsDropdown.svelte — grey-0 bg, border-radius: 1.5rem=24pt, shadow, chevron
// Padding: 1.0625rem top/bottom (17pt), 1.4375rem left (23pt), 3rem right (48pt) for chevron
// Shadow: 0 4px 4px rgba(0,0,0,0.1) — matches web box-shadow
// Opens a custom overlay list instead of native Picker wheel

struct OMDropdownOption: Identifiable, Equatable {
    let id: String
    let label: String

    init(_ id: String, label: String) {
        self.id = id
        self.label = label
    }
}

struct OMDropdown: View {
    let title: String
    let options: [OMDropdownOption]
    @Binding var selection: String
    var disabled = false

    @State private var isExpanded = false

    private var selectedLabel: String {
        options.first(where: { $0.id == selection })?.label ?? title
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Closed row — shows current selection
            Button {
                guard !disabled else { return }
                withAnimation(.easeInOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: .spacing4) {
                    Text(selectedLabel)
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(selection.isEmpty ? Color.fontTertiary : Color.fontPrimary)

                    Spacer(minLength: .spacing4)

                    Icon("chevron-down", size: 16)
                        .foregroundStyle(Color.fontTertiary)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
                // Padding from SettingsDropdown.svelte: 1.0625rem top/bottom, 1.4375rem left, 3rem right
                // No exact tokens: 17pt ≈ spacing8(16pt), 23pt between spacing12(24) and spacing10(20)
                // Using spacing24=48pt for trailing (exact match for 3rem chevron space)
                .padding(.leading, .spacing12)  // 1.4375rem=23px — closest: spacing12=24pt
                .padding(.trailing, .spacing24) // 3rem=48px — exact: spacing24=48pt
                .padding(.vertical, .spacing8)  // 1.0625rem=17px — closest: spacing8=16pt
                .background(Color.grey0)
                // border-radius: 1.5rem = 24px — no matching radius token exists (radius7=16, radius8=20)
                .clipShape(RoundedRectangle(cornerRadius: 24)) // 1.5rem from SettingsDropdown.svelte
                .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 4)
            }
            .buttonStyle(.plain)
            .opacity(disabled ? 0.5 : 1)

            // Expanded dropdown list
            if isExpanded {
                VStack(spacing: 0) {
                    ForEach(options) { option in
                        Button {
                            selection = option.id
                            withAnimation(.easeInOut(duration: 0.2)) {
                                isExpanded = false
                            }
                        } label: {
                            HStack(spacing: .spacing4) {
                                Text(option.label)
                                    .font(.omP)
                                    .foregroundStyle(Color.fontPrimary)

                                Spacer(minLength: .spacing4)

                                if option.id == selection {
                                    Icon("check", size: 16)
                                        .foregroundStyle(Color.buttonPrimary)
                                }
                            }
                            .padding(.horizontal, .spacing6)
                            .padding(.vertical, .spacing4)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .background(Color.grey0)
                // Same 1.5rem = 24pt radius as closed row — matches SettingsDropdown.svelte
                .clipShape(RoundedRectangle(cornerRadius: 24)) // 1.5rem from SettingsDropdown.svelte
                .overlay(
                    RoundedRectangle(cornerRadius: 24) // 1.5rem from SettingsDropdown.svelte
                        .stroke(Color.grey20, lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 4)
                .padding(.top, .spacing2)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .accessibilityLabel(title)
    }
}

// MARK: - OMSettingsPickerRow
// Convenience: OMSettingsRow label + OMDropdown combined

struct OMSettingsPickerRow: View {
    let title: String
    var subtitle: String?
    var icon: String?
    let options: [OMDropdownOption]
    @Binding var selection: String

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: 0) {
                if let icon {
                    Icon(icon, size: 22)
                        .foregroundStyle(Color.fontSecondary)
                        .frame(width: 44, height: 44)
                        .background(
                            LinearGradient(
                                colors: [Color.grey20, Color.grey30],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                        .padding(.trailing, .spacing6)
                }

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(title)
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                    if let subtitle {
                        Text(subtitle)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(2)
                    }
                }
            }

            OMDropdown(title: title, options: options, selection: $selection)
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing2)
        .accessibilityLabel(title)
    }
}

// MARK: - OMConfirmDialog
// Web source: SettingsConfirmBlock.svelte — overlay card with warning + action buttons
// ZStack overlay, dimming, card with title/message/buttons

struct OMConfirmDialog: View {
    let title: String
    let message: String
    var confirmTitle: String = "Confirm"
    var isDestructive: Bool = false
    let onConfirm: () -> Void
    let onCancel: () -> Void

    var body: some View {
        ZStack {
            Color.black.opacity(0.35)
                .ignoresSafeArea()
                .onTapGesture { onCancel() }

            VStack(spacing: .spacing6) {
                VStack(spacing: .spacing3) {
                    Text(title)
                        .font(.omH3)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                        .multilineTextAlignment(.center)

                    Text(message)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .multilineTextAlignment(.center)
                }

                HStack(spacing: .spacing4) {
                    Button(action: onCancel) {
                        Text(AppStrings.cancel)
                            .font(.omP)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.fontPrimary)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, .spacing4)
                            .background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius8))
                            .overlay(
                                RoundedRectangle(cornerRadius: .radius8)
                                    .stroke(Color.grey20, lineWidth: 1)
                            )
                    }
                    .buttonStyle(.plain)

                    Button(action: onConfirm) {
                        Text(confirmTitle)
                            .font(.omP)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.fontButton)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, .spacing4)
                            .background(isDestructive ? Color.error : Color.buttonPrimary)
                            .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.spacing8)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .shadow(color: .black.opacity(0.25), radius: 12, x: 0, y: 4)
            .padding(.horizontal, .spacing12)
        }
    }
}

// MARK: - OMSheet
// Custom bottom sheet — slides up with spring, grey-0 bg, drag handle, close button
// Replaces native .sheet() which renders detent/drag handle chrome

struct OMSheet<Content: View>: View {
    @Binding var isPresented: Bool
    var title: String?
    @ViewBuilder let content: Content

    @State private var dragOffset: CGFloat = 0

    var body: some View {
        if isPresented {
            ZStack(alignment: .bottom) {
                Color.black.opacity(0.35)
                    .ignoresSafeArea()
                    .onTapGesture { dismiss() }

                VStack(spacing: 0) {
                    // Drag handle
                    Capsule()
                        .fill(Color.grey30)
                        .frame(width: 36, height: 5)
                        .padding(.top, .spacing4)
                        .padding(.bottom, .spacing3)

                    // Header with optional title and close button
                    if title != nil {
                        HStack {
                            if let title {
                                Text(title)
                                    .font(.omH3)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(Color.fontPrimary)
                            }

                            Spacer()

                            OMIconButton(icon: "x", label: "Close") {
                                dismiss()
                            }
                        }
                        .padding(.horizontal, .spacing8)
                        .padding(.bottom, .spacing4)
                    }

                    // Content
                    content
                        .padding(.horizontal, .spacing8)
                        .padding(.bottom, .spacing8)
                }
                .background(Color.grey0)
                .clipShape(
                    UnevenRoundedRectangle(
                        topLeadingRadius: .radius8,
                        topTrailingRadius: .radius8
                    )
                )
                .offset(y: dragOffset)
                .gesture(
                    DragGesture()
                        .onChanged { value in
                            if value.translation.height > 0 {
                                dragOffset = value.translation.height
                            }
                        }
                        .onEnded { value in
                            if value.translation.height > 100 {
                                dismiss()
                            } else {
                                withAnimation(.spring(response: 0.3)) {
                                    dragOffset = 0
                                }
                            }
                        }
                )
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            .animation(.spring(response: 0.35, dampingFraction: 0.85), value: isPresented)
        }
    }

    private func dismiss() {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) {
            isPresented = false
            dragOffset = 0
        }
    }
}

// MARK: - Original Primitives

struct OMIconButton: View {
    let icon: String
    var label: String
    var size: CGFloat = 36
    var iconSize: CGFloat = 18
    var isProminent = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Icon(icon, size: iconSize)
                .foregroundStyle(isProminent ? Color.fontButton : Color.fontPrimary)
                .frame(width: size, height: size)
                .background(isProminent ? Color.buttonPrimary : Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius7))
                .overlay(
                    RoundedRectangle(cornerRadius: .radius7)
                        .stroke(isProminent ? Color.clear : Color.grey20, lineWidth: 1)
                )
                .contentShape(RoundedRectangle(cornerRadius: .radius7))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

struct OMSettingsPage<Content: View>: View {
    @Environment(\.omSettingsScrollOffsetHandler) private var scrollOffsetHandler
    let title: String
    var subtitle: String?
    var trailing: AnyView?
    var showsHeader = true
    var showsFooter = true
    @ViewBuilder let content: Content

    init(
        title: String,
        subtitle: String? = nil,
        trailing: AnyView? = nil,
        showsHeader: Bool = true,
        showsFooter: Bool = true,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.subtitle = subtitle
        self.trailing = trailing
        self.showsHeader = showsHeader
        self.showsFooter = showsFooter
        self.content = content()
    }

    var body: some View {
        VStack(spacing: 0) {
            if showsHeader {
                HStack(alignment: .center, spacing: .spacing4) {
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(title)
                            .font(.omH2)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.fontPrimary)
                        if let subtitle {
                            Text(subtitle)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontSecondary)
                        }
                    }
                    Spacer(minLength: .spacing4)
                    if let trailing {
                        trailing
                    }
                }
                .padding(.horizontal, .spacing8)
                .padding(.top, .spacing8)
                .padding(.bottom, .spacing6)
                .background(Color.grey20)
            }

            GeometryReader { scrollFrame in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: .spacing8) {
                        GeometryReader { contentFrame in
                            Color.clear.preference(
                                key: OMSettingsScrollOffsetPreferenceKey.self,
                                value: max(
                                    0,
                                    scrollFrame.frame(in: .global).minY - contentFrame.frame(in: .global).minY
                                )
                            )
                        }
                        .frame(height: 0)

                        content

                        if showsFooter {
                            OMSettingsFooter()
                        }
                    }
                    .padding(.horizontal, .spacing5)
                    .padding(.bottom, .spacing16)
                }
                .onPreferenceChange(OMSettingsScrollOffsetPreferenceKey.self) { offset in
                    if let callback = scrollOffsetHandler.callback {
                        Task { @MainActor in
                            callback(offset)
                        }
                    }
                }
                .scrollContentBackground(.hidden)
                .background(Color.grey20)
            }
        }
        .background(Color.grey20)
    }
}

struct OMSettingsFooter: View {
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            footerSection(LocalizationManager.shared.text("footer.sections.for_everyone")) {
                footerLink(LocalizationManager.shared.text("settings.instagram"), url: "https://instagram.com/openmates")
                footerLink(LocalizationManager.shared.text("common.discord"), url: "https://discord.gg/openmates")
                footerLink(LocalizationManager.shared.text("settings.meetup"), url: "https://www.meetup.com/openmates")
                footerLink(LocalizationManager.shared.text("settings.bluesky"), url: "https://bsky.app/profile/openmates.org")
                footerLink(LocalizationManager.shared.text("settings.mastodon"), url: "https://mastodon.social/@openmates")
                footerLink(LocalizationManager.shared.text("settings.pixelfed"), url: "https://pixelfed.social/openmates")
            }

            footerSection(LocalizationManager.shared.text("footer.sections.for_developers")) {
                footerLink(LocalizationManager.shared.text("settings.api_docs"), url: "\(APIClient.shared.baseURL.absoluteString)/docs")
                footerLink(LocalizationManager.shared.text("common.github"), url: "https://github.com/OpenMates/OpenMates")
                footerLink(LocalizationManager.shared.text("settings.signal"), url: "https://signal.me/#eu/openmates")
            }

            footerSection(LocalizationManager.shared.text("common.contact")) {
                footerLink(LocalizationManager.shared.text("common.email"), url: "mailto:hello@openmates.org")
            }

            footerSection(LocalizationManager.shared.text("common.legal")) {
                footerLink(AppStrings.imprint, url: "https://openmates.org/imprint")
                footerLink(AppStrings.privacyPolicy, url: "https://openmates.org/privacy")
                footerLink(AppStrings.termsOfService, url: "https://openmates.org/terms")
            }

            footerSection("App version") {
                Text("v\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")")
                    .font(.omSmall)
                    .foregroundStyle(Color.grey50)
                    .padding(.vertical, .spacing3)
            }
        }
        .padding(.top, .spacing32 + .spacing20)
        .padding(.horizontal, .spacing5)
        .padding(.bottom, .spacing8)
    }

    private func footerSection<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title)
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(Color.fontSecondary)
                .padding(.vertical, .spacing3)
            content()
        }
    }

    private func footerLink(_ title: String, url: String) -> some View {
        Button {
            if let target = URL(string: url) {
                openURL(target)
            }
        } label: {
            Text(title)
                .font(.omSmall)
                .foregroundStyle(Color.grey50)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, .spacing3)
        }
        .buttonStyle(.plain)
    }
}

struct OMSettingsSection<Content: View>: View {
    let title: String?
    let icon: String
    @ViewBuilder let content: Content

    init(_ title: String? = nil, icon: String = "settings", @ViewBuilder content: () -> Content) {
        self.title = title
        self.icon = icon
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let title {
                OMSettingsSectionHeading(title: title, icon: icon)
            }

            VStack(spacing: 0) {
                content
            }
        }
    }
}

struct OMSettingsSectionHeading: View {
    let title: String
    var icon: String = "settings"

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(spacing: .spacing6) {
                Icon(icon, size: 22)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 44, height: 44)

                Text(title)
                    .font(.omP.weight(.bold))
                    .foregroundStyle(Color.fontPrimary)
            }

            RoundedRectangle(cornerRadius: 11)
                .fill(LinearGradient.primary)
                .frame(height: 4)
        }
        .padding(.horizontal, .spacing5)
        .padding(.top, .spacing12)
        .padding(.bottom, .spacing8)
    }
}

// Web source: SettingsItem.svelte (top-level) — .menu-item with .settings-icon
// Icon container: 44x44, radius-4 (10pt), icon at 50% (22pt), margin-end 12px
// Mode B (.has-bg): gradient bg + white icon. Mode A (no .has-bg): grey gradient bg + colored icon
// Row: padding 5px 10px, min-height 40px, border-radius radius-3 (8pt)
// Hover: background-color grey-10

struct OMSettingsRow: View {
    let title: String
    var subtitle: String?
    var icon: String?
    var iconGradient: LinearGradient?
    var value: String?
    var isDestructive = false
    var showsChevron = true
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 0) {
                if let icon {
                    // .icon-container: 44x44, margin-inline-end 12px, flex-shrink 0
                    // .settings-icon: 44x44, radius-4 (10pt)
                    // Mode B (.has-bg): gradient bg, white icon at 50% (22pt)
                    // Mode A (no .has-bg): grey-20→grey-30 gradient bg, colored icon at 50% (22pt)
                    Icon(icon, size: 22)
                        .foregroundStyle(.white)
                        .frame(width: 44, height: 44)
                        .background(isDestructive ? LinearGradient.appNews : LinearGradient.primary)
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                        .padding(.trailing, .spacing6) // margin-inline-end: 12px
                }

                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(title)
                        .font(.omP.weight(.medium))
                        .foregroundStyle(isDestructive ? AnyShapeStyle(Color.error) : AnyShapeStyle(LinearGradient.primary))
                    if let subtitle {
                        Text(subtitle)
                            .font(.omXs)
                            .foregroundStyle(Color.fontSecondary)
                            .lineLimit(2)
                    }
                }

                Spacer(minLength: .spacing4)

                if let value {
                    Text(value)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(1)
                }

                if showsChevron {
                    Icon("chevron-right", size: 16)
                        .foregroundStyle(Color.fontTertiary)
                }
            }
            // padding: 5px 10px (top/bottom 5pt, left/right 10pt)
            .padding(.horizontal, .spacing5) // 10px
            .padding(.vertical, .spacing2)   // web: 5px, closest token: spacing2 (4pt)
            .frame(minHeight: 40)            // min-height: 40px
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .clipShape(RoundedRectangle(cornerRadius: .radius3)) // border-radius: var(--radius-3)
        .accessibilityLabel(title)
    }
}

struct OMSettingsStaticRow: View {
    let title: String
    let value: String
    var icon: String?

    var body: some View {
        HStack(spacing: 0) {
            if let icon {
                Icon(icon, size: 22)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(width: 44, height: 44)
                    .background(
                        LinearGradient(
                            colors: [Color.grey20, Color.grey30],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    .padding(.trailing, .spacing6)
            }
            Text(title)
                .font(.omP)
                .foregroundStyle(Color.fontPrimary)
            Spacer()
            Text(value)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing2)
        .frame(minHeight: 40)
    }
}

struct OMSegmentedControl<Option: Hashable>: View {
    struct Item: Identifiable {
        let id: Option
        let title: String
    }

    let items: [Item]
    @Binding var selection: Option

    var body: some View {
        HStack(spacing: .spacing2) {
            ForEach(items) { item in
                Button {
                    selection = item.id
                } label: {
                    Text(item.title)
                        .font(.omSmall)
                        .fontWeight(selection == item.id ? .semibold : .regular)
                        .foregroundStyle(selection == item.id ? Color.fontButton : Color.fontPrimary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, .spacing4)
                        .background(selection == item.id ? Color.buttonPrimary : Color.clear)
                        .clipShape(RoundedRectangle(cornerRadius: .radius5))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.spacing2)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius7))
        .overlay(
            RoundedRectangle(cornerRadius: .radius7)
                .stroke(Color.grey20, lineWidth: 1)
        )
    }
}
