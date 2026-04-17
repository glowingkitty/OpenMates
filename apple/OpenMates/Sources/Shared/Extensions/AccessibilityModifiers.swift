// Accessibility modifiers — reusable ViewModifiers for consistent VoiceOver, Dynamic Type,
// and reduced motion support across the app. Apply these instead of ad-hoc .accessibilityLabel()
// calls to ensure consistent behavior.

import SwiftUI

// MARK: - Accessible button (label + hint + trait)

struct AccessibleButton: ViewModifier {
    let label: String
    let hint: String?

    func body(content: Content) -> some View {
        content
            .accessibilityLabel(label)
            .accessibilityHint(hint ?? "")
            .accessibilityAddTraits(.isButton)
    }
}

// MARK: - Accessible toggle

struct AccessibleToggle: ViewModifier {
    let label: String
    let isOn: Bool

    func body(content: Content) -> some View {
        content
            .accessibilityLabel(label)
            .accessibilityValue(isOn ? "On" : "Off")
            .accessibilityAddTraits(.isButton)
    }
}

// MARK: - Accessible text input

struct AccessibleInput: ViewModifier {
    let label: String
    let hint: String?

    func body(content: Content) -> some View {
        content
            .accessibilityLabel(label)
            .accessibilityHint(hint ?? "")
    }
}

// MARK: - Accessible image (decorative vs informative)

struct AccessibleImage: ViewModifier {
    let label: String?

    func body(content: Content) -> some View {
        if let label {
            content.accessibilityLabel(label)
        } else {
            content.accessibilityHidden(true)
        }
    }
}

// MARK: - Reduced motion animation

struct ReducedMotionAnimation: ViewModifier {
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    let animation: Animation

    func body(content: Content) -> some View {
        content.animation(reduceMotion ? .none : animation, value: UUID())
    }
}

// MARK: - Accessible chat message

struct AccessibleMessage: ViewModifier {
    let role: String
    let content: String
    let index: Int

    func body(content view: Content) -> some View {
        view
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(role) message: \(content)")
            .accessibilityHint("Double tap to open context menu")
    }
}

// MARK: - Accessible embed preview

struct AccessibleEmbed: ViewModifier {
    let embedType: String
    let title: String?

    func body(content: Content) -> some View {
        content
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(embedType): \(title ?? "untitled")")
            .accessibilityHint("Double tap to open fullscreen")
            .accessibilityAddTraits(.isButton)
    }
}

// MARK: - Accessible setting row

struct AccessibleSettingRow: ViewModifier {
    let label: String
    let value: String?

    func body(content: Content) -> some View {
        content
            .accessibilityElement(children: .combine)
            .accessibilityLabel(value != nil ? "\(label), \(value!)" : label)
    }
}

// MARK: - View extensions

extension View {
    func accessibleButton(_ label: String, hint: String? = nil) -> some View {
        modifier(AccessibleButton(label: label, hint: hint))
    }

    func accessibleToggle(_ label: String, isOn: Bool) -> some View {
        modifier(AccessibleToggle(label: label, isOn: isOn))
    }

    func accessibleInput(_ label: String, hint: String? = nil) -> some View {
        modifier(AccessibleInput(label: label, hint: hint))
    }

    func accessibleImage(_ label: String? = nil) -> some View {
        modifier(AccessibleImage(label: label))
    }

    func accessibleMessage(role: String, content: String, index: Int) -> some View {
        modifier(AccessibleMessage(role: role, content: content, index: index))
    }

    func accessibleEmbed(type: String, title: String?) -> some View {
        modifier(AccessibleEmbed(embedType: type, title: title))
    }

    func accessibleSetting(_ label: String, value: String? = nil) -> some View {
        modifier(AccessibleSettingRow(label: label, value: value))
    }

    func reduceMotionAnimation(_ animation: Animation = .easeInOut) -> some View {
        modifier(ReducedMotionAnimation(animation: animation))
    }
}

// MARK: - Dynamic Type scaling helpers

extension Font {
    static var omDynamic: Font { .body }
    static var omDynamicSmall: Font { .subheadline }
    static var omDynamicCaption: Font { .caption }
    static var omDynamicTitle: Font { .title2 }
    static var omDynamicLargeTitle: Font { .largeTitle }
}

// MARK: - Accessibility announcement helper

enum AccessibilityAnnouncement {
    static func announce(_ message: String) {
        UIAccessibility.post(notification: .announcement, argument: message)
    }

    static func screenChanged(_ message: String? = nil) {
        UIAccessibility.post(notification: .screenChanged, argument: message)
    }

    static func layoutChanged(_ element: Any? = nil) {
        UIAccessibility.post(notification: .layoutChanged, argument: element)
    }
}
