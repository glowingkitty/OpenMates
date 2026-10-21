// Web: frontend/packages/ui/src/components/ChatMessage.svelte
// CSS: .assistant-response-transient, .assistant-identity-row.transient,
//      .assistant-transient-thinking
// Rendered reference: .runtime/followups123/web-reference362.json
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.streaming.progressive-presentation, chats.surface.semantic-parity
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

/// A presentation of the current reducer identity, never an empty stored Message.
struct TransientAssistantResponseView: View {
    let response: ChatTransientAssistantResponse
    let memories: [ChatAppliedMemory]
    let viewportWidth: CGFloat
    let onOpenMateSettings: ((String) -> Void)?
    let onOpenModelSettings: ((String) -> Void)?
    private var stacked: Bool { ChatResponsiveLayoutPolicy.stacksAssistantIdentity(containerWidth: viewportWidth) }
    private var displayName: String {
        if let name = response.mateName, !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return name }
        let key = "mates." + response.mateCategory
        let value = AppStrings.localized(key)
        return value == key ? AppStrings.openMatesName : value
    }
    private var activity: AssistantActivityConfiguration {
        .init(chatID: response.chatId, responseActive: true, thinkingContent: "", thinkingStreaming: false,
              memories: memories, embeds: [:], completedSubChatIDs: [], viewportWidth: viewportWidth)
    }

    var body: some View {
        let layout = stacked ? AnyLayout(VStackLayout(alignment: .leading, spacing: .spacing2))
            : AnyLayout(HStackLayout(alignment: .top, spacing: .spacing8 - 1))
        layout {
            avatar
            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: .spacing3) {
                    HStack(spacing: .spacing2) {
                        AssistantMessageIdentityView(placement: .mateName, displayName: displayName,
                            category: response.mateCategory, modelName: response.modelName,
                            onOpenMateSettings: onOpenMateSettings, onOpenModelSettings: onOpenModelSettings,
                            timingBinding: .init(chatID: response.chatId, userMessageID: response.userMessageId,
                                responseID: response.id, category: response.mateCategory))
                            .lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                        HStack(spacing: .spacing2) {
                            Icon("ai", size: 14).accessibilityHidden(true)
                            Text(AppStrings.thinkingHeaderStreaming).font(.omSmall).fixedSize()
                        }
                        .foregroundStyle(LinearGradient.primary)
                        .accessibilityElement(children: .combine).accessibilityIdentifier("assistant-transient-thinking")
                        Color.clear.frame(maxWidth: .infinity).accessibilityHidden(true)
                    }.frame(minHeight: 24)
                    if !memories.isEmpty {
                        AssistantActivityGroupView(configuration: activity, segment: nil, thinking: "", thinkingStreaming: false,
                            memories: memories, active: true, openFocusIDs: [], content: { EmptyView() })
                    }
                }
                .padding(.top, .spacing2).padding(.horizontal, .spacing6).padding(.bottom, .spacing3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.grey0).clipShape(RoundedRectangle(cornerRadius: 13))
                .overlay(alignment: .bottom) { AssistantResponseGlow() }
                .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                AssistantMessageIdentityView(placement: .modelAttribution, displayName: displayName,
                    category: response.mateCategory, modelName: response.modelName,
                    onOpenMateSettings: onOpenMateSettings, onOpenModelSettings: onOpenModelSettings)
            }
            .padding(.trailing, stacked ? 0 : .spacing5 * 2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain).accessibilityIdentifier("assistant-response-transient")
    }

    private var avatar: some View {
        Group {
            if let profile = profileImage {
                profile.renderingMode(.original).resizable().scaledToFill()
            } else {
                AppIconView(appId: response.mateCategory, size: stacked ? 25 : 60)
            }
        }
        .frame(width: stacked ? 25 : 60, height: stacked ? 25 : 60).clipShape(Circle())
        .overlay(alignment: .bottomTrailing) {
            Circle().fill(Color.grey0).frame(width: stacked ? 12 : 24, height: stacked ? 12 : 24)
                .overlay { Icon("ai", size: stacked ? 8 : 16).foregroundStyle(LinearGradient.primary) }
        }
        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4).accessibilityHidden(true)
    }
    private var profileImage: Image? {
        guard CategoryMapping.isKnownCategory(response.mateCategory) else { return nil }
        let path = Bundle.main.path(forResource: response.mateCategory, ofType: "jpeg", inDirectory: "mates")
            ?? Bundle.main.path(forResource: response.mateCategory, ofType: "jpeg", inDirectory: "Mates")
            ?? Bundle.main.path(forResource: response.mateCategory, ofType: "jpeg")
        guard let path else { return nil }
        #if os(iOS)
        guard let image = UIImage(contentsOfFile: path) else { return nil }
        return Image(uiImage: image)
        #elseif os(macOS)
        guard let image = NSImage(contentsOfFile: path) else { return nil }
        return Image(nsImage: image)
        #else
        return nil
        #endif
    }
}
