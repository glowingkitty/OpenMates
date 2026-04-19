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
