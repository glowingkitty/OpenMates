// OpenMates button styles matching the web app's design tokens.
// Primary (solid orange fill, pill-shaped) and secondary (grey, pill-shaped) variants.

// ─── Web source ─────────────────────────────────────────────────────
// CSS:    frontend/packages/ui/src/styles/buttons.css
//         button { border-radius:20px; height:41px; drop-shadow(0 4px 4px rgba(0,0,0,.25)) }
//         button:active { scale:0.98 }
//         button:disabled { opacity:0.6 }
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(macOS)
import AppKit
#endif

// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
// Specification: specifications/features/workflows-ui/specification.yml
// Assertions: workflows-ui.responsive-accessible-reachable
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.surface.semantic-parity
// Specification: specifications/features/apps-workspace/specification.yml
// Assertions: apps.presentation.shared-detail-and-recency
// Native hover affordances follow the explicitly requested 1.05 card scale.
// Web references: workspace/WorkspaceContinueCard.svelte and
// DailyInspirationBanner.svelte .carousel-arrow (white 0.1 hover, 0.18 press).
enum OMCardHoverPolicy {
    static func scale(hovered: Bool, enabled: Bool) -> CGFloat {
        hovered && enabled ? 1.05 : 1
    }

    static func animationDuration(reduceMotion: Bool) -> Double? {
        reduceMotion ? nil : 0.15
    }
}

#if os(macOS)
/// A cursor rectangle, rather than a global cursor stack, follows the lifetime
/// of the clickable surface. This view never consumes mouse or text events.
private struct OMClickableCursorRegion: NSViewRepresentable {
    let enabled: Bool

    func makeNSView(context: Context) -> CursorView { CursorView() }

    func updateNSView(_ view: CursorView, context: Context) {
        guard view.enabled != enabled else { return }
        view.enabled = enabled
        view.window?.invalidateCursorRects(for: view)
    }

    final class CursorView: NSView {
        var enabled = false

        override func hitTest(_ point: NSPoint) -> NSView? { nil }

        override func resetCursorRects() {
            super.resetCursorRects()
            if enabled { addCursorRect(visibleRect, cursor: .pointingHand) }
        }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            window?.invalidateCursorRects(for: self)
        }

        override func setFrameSize(_ newSize: NSSize) {
            super.setFrameSize(newSize)
            window?.invalidateCursorRects(for: self)
        }
    }
}
#endif

private struct OMCardHoverFeedback: ViewModifier {
    #if os(macOS)
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovered = false
    #endif

    func body(content: Content) -> some View {
        #if os(macOS)
        content
            .background(OMClickableCursorRegion(enabled: isEnabled).allowsHitTesting(false))
            .scaleEffect(OMCardHoverPolicy.scale(hovered: hovered, enabled: isEnabled))
            .animation(OMCardHoverPolicy.animationDuration(reduceMotion: reduceMotion).map {
                Animation.easeOut(duration: $0)
            }, value: hovered && isEnabled)
            .onContinuousHover { phase in
                switch phase {
                case .active:
                    if !hovered { hovered = true }
                case .ended:
                    if hovered { hovered = false }
                }
            }
            .onChange(of: isEnabled) { _, enabled in
                if !enabled { hovered = false }
            }
            .onDisappear { hovered = false }
        #else
        content
        #endif
    }
}

private struct OMClickablePointer: ViewModifier {
    let enabled: Bool
    #if os(macOS)
    @Environment(\.isEnabled) private var isEnabled
    #endif

    func body(content: Content) -> some View {
        #if os(macOS)
        content.background(OMClickableCursorRegion(enabled: enabled && isEnabled).allowsHitTesting(false))
        #else
        content
        #endif
    }
}

extension View {
    func omClickablePointer(enabled: Bool = true) -> some View {
        modifier(OMClickablePointer(enabled: enabled))
    }

    func omCardHoverFeedback() -> some View {
        modifier(OMCardHoverFeedback())
    }
}

struct OMInspirationNavigationButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        NavigationLabel(configuration: configuration)
    }

    private struct NavigationLabel: View {
        let configuration: ButtonStyleConfiguration
        #if os(macOS)
        @Environment(\.isEnabled) private var isEnabled
        @Environment(\.accessibilityReduceMotion) private var reduceMotion
        @State private var hovered = false
        #endif

        var body: some View {
            #if os(macOS)
            configuration.label
                .background(OMClickableCursorRegion(enabled: isEnabled).allowsHitTesting(false))
                .background(Color.white.opacity(isEnabled ? (configuration.isPressed ? 0.18 : hovered ? 0.1 : 0) : 0))
                .animation(reduceMotion ? nil : .easeOut(duration: 0.15), value: hovered)
                .onContinuousHover { phase in
                    switch phase {
                    case .active:
                        if !hovered { hovered = true }
                    case .ended:
                        if hovered { hovered = false }
                    }
                }
                .onChange(of: isEnabled) { _, enabled in if !enabled { hovered = false } }
                .onDisappear { hovered = false }
            #else
            configuration.label
            #endif
        }
    }
}

struct OMPrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omP)
            .fontWeight(.semibold)
            .foregroundStyle(Color.fontButton)
            .padding(.horizontal, .spacing12)
            .padding(.vertical, .spacing8)
            .frame(minHeight: 41)
            .background(
                configuration.isPressed ? Color.buttonPrimaryPressed :
                    isEnabled ? Color.buttonPrimary : Color.buttonSecondary
            )
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
            .opacity(isEnabled ? 1.0 : 0.6)
            .scaleEffect(configuration.isPressed ? 0.98 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
            .omClickablePointer()
    }
}

struct OMSecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omP)
            .fontWeight(.medium)
            .foregroundStyle(Color.fontPrimary)
            .padding(.horizontal, .spacing12)
            .padding(.vertical, .spacing8)
            .frame(minHeight: 41)
            .background(Color.buttonSecondary)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
            .opacity(isEnabled ? 1.0 : 0.6)
            .scaleEffect(configuration.isPressed ? 0.98 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
            .omClickablePointer()
    }
}

// Stateless pill field — base style only (no focus ring).
// Callers MUST add focus-ring behavior via .focused($isFocused) and an .overlay stroke
// that switches from Color.grey30 (default) → Color.buttonPrimary (focused), matching
// the fields.css pattern: border-color: var(--color-button-primary) on :focus.
struct OMTextFieldStyle: TextFieldStyle {
    func _body(configuration: TextField<_Label>) -> some View {
        configuration
            .font(.omP)
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing6)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            .overlay(
                RoundedRectangle(cornerRadius: .radiusFull)
                    .stroke(Color.grey30, lineWidth: 2)
            )
    }
}
