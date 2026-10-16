// Web counterpart: frontend/packages/ui/src/components/settings/FocusModePhases.svelte
// Specification: specifications/features/focus-modes/specification.yml
// Assertions: focus-modes.phases
import SwiftUI

struct FocusModePhasesNativeView: View {
    let phases: [FocusPhaseDefinition]
    var body: some View {
        OMSettingsSection(L("focus_phases.phases"), icon: "systemprompt") {
            VStack(alignment: .leading, spacing: .spacing5) {
                ForEach(Array(phases.enumerated()), id: \.element.id) { index, phase in
                    VStack(alignment: .leading, spacing: .spacing2) {
                        Text("\(index + 1). \(phase.title)").font(.omP.weight(.semibold))
                        Text(phase.instructions).font(.omSmall).foregroundStyle(Color.fontSecondary)
                            .accessibilityIdentifier("focus-phase-instructions")
                        Text(L("focus_phases.requirements")).font(.omSmall.weight(.semibold))
                        ForEach(phase.requirements) { requirement in
                            VStack(alignment: .leading, spacing: .spacing1) {
                                Text("• \(requirement.text)").font(.omSmall)
                                if requirement.type == "user_confirmation" { Text(L("focus_phases.confirmation")).font(.omSmall).foregroundStyle(Color.fontSecondary) }
                            }.accessibilityIdentifier("focus-phase-requirement")
                        }
                    }.accessibilityElement(children: .contain)
                        .accessibilityIdentifier("focus-mode-phase")
                }
            }.padding(.horizontal, .spacing5).padding(.vertical, .spacing3)
        }.accessibilityElement(children: .contain)
            .accessibilityIdentifier("focus-mode-phases")
    }
}

@MainActor
private func L(_ key: String) -> String {
    LocalizationManager.shared.text(key)
}
