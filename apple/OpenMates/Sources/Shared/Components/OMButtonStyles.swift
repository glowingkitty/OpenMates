// OpenMates button styles matching the web app's design tokens.
// Primary (gradient fill) and secondary (outline) variants.

import SwiftUI

struct OMPrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omP)
            .fontWeight(.semibold)
            .foregroundStyle(Color.fontButton)
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing4)
            .background(
                configuration.isPressed ? Color.buttonPrimaryPressed :
                    isEnabled ? Color.buttonPrimary : Color.buttonSecondary
            )
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .scaleEffect(configuration.isPressed ? 0.98 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

struct OMSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.omP)
            .fontWeight(.medium)
            .foregroundStyle(Color.fontPrimary)
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing4)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .overlay(
                RoundedRectangle(cornerRadius: .radius3)
                    .stroke(Color.grey30, lineWidth: 1)
            )
            .scaleEffect(configuration.isPressed ? 0.98 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

struct OMTextFieldStyle: TextFieldStyle {
    func _body(configuration: TextField<_Label>) -> some View {
        configuration
            .font(.omP)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .overlay(
                RoundedRectangle(cornerRadius: .radius3)
                    .stroke(Color.grey30, lineWidth: 1)
            )
    }
}
