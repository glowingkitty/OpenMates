// Compact explicit permission controls; choices remain transient to the live call.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/AppSettingsMemoriesPermissionDialog.svelte
// CSS: same file — .categories-list, .entry-item, .dialog-actions
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.privacy
import SwiftUI

@MainActor
private enum WatchVoiceMemoryCopy {
    static var title: String { WatchLocalization.text("chat.permissions.title") }
    static var question: String { WatchLocalization.text("chat.permissions.question") }
    static var include: String { WatchLocalization.text("chat.permissions.include_selected") }
    static var reject: String { WatchLocalization.text("chat.permissions.reject_all") }
}

struct WatchVoiceCallMemoryPermissionView: View {
    @ObservedObject var permission: WatchVoiceCallMemoryPermission

    var body: some View {
        if let prompt = permission.prompt {
            ScrollView {
                VStack(alignment: .leading, spacing: .spacing3) {
                    Text(WatchVoiceMemoryCopy.title).font(.omSmall.weight(.semibold))
                    Text(WatchVoiceMemoryCopy.question).font(.omXs)
                    ForEach(prompt.categories) { category in
                        VStack(alignment: .leading, spacing: .spacing2) {
                            Text(category.title).font(.omXs.weight(.semibold))
                            ForEach(prompt.choices.filter { $0.category.id == category.id }) { choice in
                                Button {
                                    permission.setSelected(!prompt.selectedIDs.contains(choice.id),
                                        choiceID: choice.id, promptID: prompt.id)
                                } label: {
                                    HStack(alignment: .top, spacing: .spacing2) {
                                        RoundedRectangle(cornerRadius: .radius1)
                                            .fill(prompt.selectedIDs.contains(choice.id) ? Color.buttonPrimary : Color.grey10)
                                            .frame(width: .spacing4, height: .spacing4)
                                            .overlay(RoundedRectangle(cornerRadius: .radius1).stroke(Color.fontSecondary))
                                        VStack(alignment: .leading, spacing: .spacing1) {
                                            Text(choice.title).font(.omXs.weight(.semibold))
                                            Text(choice.value).font(.omMicro).foregroundStyle(Color.fontSecondary)
                                        }
                                        Spacer(minLength: 0)
                                    }.padding(.spacing2)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .background(Color.grey10, in: RoundedRectangle(cornerRadius: .radius3))
                                }.buttonStyle(.plain).disabled(prompt.deciding)
                                    .accessibilityLabel(choice.title)
                                    .accessibilityAddTraits(prompt.selectedIDs.contains(choice.id) ? .isSelected : [])
                                    .accessibilityIdentifier("watch-voice-memory-entry-" + choice.id)
                            }
                        }
                    }
                    Button {
                        Task { await permission.decide(promptID: prompt.id, includeSelected: true) }
                    } label: {
                        Text(WatchVoiceMemoryCopy.include).font(.omXs.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: .spacing8)
                            .background(LinearGradient.primary, in: Capsule())
                    }.buttonStyle(.plain).disabled(prompt.selectedIDs.isEmpty || prompt.deciding)
                        .opacity(prompt.selectedIDs.isEmpty || prompt.deciding ? 0.6 : 1)
                        .accessibilityIdentifier("watch-voice-memory-include-selected")
                    Button {
                        Task { await permission.decide(promptID: prompt.id, includeSelected: false) }
                    } label: {
                        Text(WatchVoiceMemoryCopy.reject).font(.omXs)
                            .frame(maxWidth: .infinity, minHeight: .spacing8)
                    }.buttonStyle(.plain).disabled(prompt.deciding)
                        .accessibilityIdentifier("watch-voice-memory-reject-all")
                }.padding(.spacing3)
            }
            .foregroundStyle(WatchWorkspacePalette.foreground)
            .background(WatchWorkspacePalette.background.ignoresSafeArea())
            .accessibilityIdentifier("watch-voice-memory-permission")
            .onDisappear { permission.invalidate() }
        }
    }
}
