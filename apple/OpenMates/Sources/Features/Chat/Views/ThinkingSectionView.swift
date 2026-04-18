// Thinking section — expandable display of AI reasoning/thinking content.
// Mirrors the web app's ThinkingSection.svelte: collapsible section that shows
// the AI's chain-of-thought when the model returns thinking blocks.

import SwiftUI

struct ThinkingSectionView: View {
    let content: String
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: .spacing2) {
                    Image(systemName: "brain")
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)

                    Text(LocalizationManager.shared.text("chat.thinking.header_done"))
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(Color.fontTertiary)

                    Spacer()

                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .font(.omTiny)
                        .foregroundStyle(Color.fontTertiary)
                }
                .padding(.horizontal, .spacing3)
                .padding(.vertical, .spacing2)
            }
            .buttonStyle(.plain)

            if isExpanded {
                Text(content)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing3)
                    .padding(.bottom, .spacing3)
                    .textSelection(.enabled)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .background(Color.grey10.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }
}

// MARK: - Streaming thinking indicator

struct ThinkingIndicator: View {
    @State private var dotCount = 0
    let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: .spacing2) {
            Image(systemName: "brain")
                .font(.omXs)
                .foregroundStyle(Color.fontTertiary)

            Text(LocalizationManager.shared.text("chat.thinking.header_streaming") + String(repeating: ".", count: dotCount))
                .font(.omXs).fontWeight(.medium)
                .foregroundStyle(Color.fontTertiary)
        }
        .padding(.horizontal, .spacing3)
        .padding(.vertical, .spacing2)
        .background(Color.grey10.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .onReceive(timer) { _ in
            dotCount = (dotCount + 1) % 4
        }
    }
}
