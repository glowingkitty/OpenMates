// Native-only included STT choice; no web product counterpart or web parity claim.
// Approved existing settings element geometry is reused without a new control.
// Web sources: frontend/packages/ui/src/components/settings/elements/SettingsDropdown.svelte
//              frontend/packages/ui/src/components/settings/elements/SettingsCard.svelte
//              frontend/packages/ui/src/components/settings/elements/SettingsDetailRow.svelte
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.privacy-context
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.composition.canonical-and-accessible
import SwiftUI

struct SettingsRecordingTranscriptionSection: View {
    @ObservedObject var store: LocalModelStore
    var body: some View {
        RecordingTranscriptionSettingsContent(preference: store.recordingTranscriptionPreference,
            included: store.bundledWhistle, changing: store.changingRecordingTranscriptionPreference,
            onSelect: { choice in Task { await store.setRecordingTranscriptionPreference(choice) } })
    }
}

struct RecordingTranscriptionSettingsContent: View {
    let preference: RecordingTranscriptionPreference
    let included: BundledSpeechModelDescriptor
    var changing = false
    let onSelect: (RecordingTranscriptionPreference) -> Void

    var body: some View {
        OMSettingsSection(AppStrings.recordingTranscriptionTitle) {
            OMSettingsPickerRow(title: AppStrings.recordingTranscriptionTitle,
                subtitle: AppStrings.recordingTranscriptionDescription(preference), icon: "microphone",
                options: RecordingTranscriptionPreference.allCases.map {
                    OMDropdownOption($0.rawValue, label: AppStrings.recordingTranscriptionLabel($0))
                }, selection: Binding(get: { preference.rawValue }, set: {
                    if let choice = RecordingTranscriptionPreference(rawValue: $0) { onSelect(choice) }
                }))
                .disabled(changing)
                .accessibilityIdentifier("recording-transcription-choice")
            OMSettingsCard {
                VStack(alignment: .leading, spacing: .spacing4) {
                    OMSettingsDetailRow(label: AppStrings.recordingWhistleName,
                        value: included.isIncluded ? AppStrings.recordingWhistleIncluded : AppStrings.recordingWhistleUnavailable)
                        .accessibilityIdentifier("bundled-whistle-status")
                    OMSettingsDetailRow(label: AppStrings.recordingBundledSize,
                        value: ByteCountFormatter.string(fromByteCount: included.includedSizeBytes, countStyle: .file))
                        .accessibilityIdentifier("bundled-whistle-size")
                    Text(AppStrings.recordingWhistleMemory)
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("bundled-whistle-memory-policy")
                }
            }
            .accessibilityIdentifier("bundled-whistle-card")
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recording-transcription-settings")
    }
}
