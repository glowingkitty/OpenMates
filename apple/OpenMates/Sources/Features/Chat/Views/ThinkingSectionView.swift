// Thinking section — expandable display of AI reasoning/thinking content.
// Mirrors the web app's ThinkingSection.svelte: collapsible section that shows
// the AI's chain-of-thought when the model returns thinking blocks.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ThinkingSection.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.streaming.progressive-presentation,
//             chats.rendering.assistant-document-convergence,
//             chats.surface.semantic-parity

import SwiftUI

struct ThinkingSectionView: View {
    let content: String
    var isStreaming = false
    @State private var isExpanded = false
    @State private var userToggledWhileStreaming = false
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    private var headerText: String {
        isStreaming ? AppStrings.thinkingHeaderStreaming : AppStrings.thinkingHeaderDone
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                if isStreaming {
                    userToggledWhileStreaming = true
                }
                withAnimation(reduceMotion ? .none : .easeInOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: .spacing4) {
                    Icon("reasoning", size: 18)
                        .foregroundStyle(Color.fontTertiary)
                        .accessibilityHidden(true)

                    Text(headerText)
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(Color.fontTertiary)

                    Spacer()

                    Icon(isExpanded ? "up" : "down", size: 16)
                        .foregroundStyle(Color.fontTertiary)
                        .accessibilityHidden(true)
                }
                .padding(.horizontal, 14) // Web ThinkingSection.svelte: padding 10px 14px.
                .padding(.vertical, .spacing5)
            }
            .buttonStyle(.plain)
            .accessibleButton(
                isExpanded ? AppStrings.thinkingCollapse : AppStrings.thinkingExpand
            )

            if isExpanded && !content.isEmpty {
                ScrollViewReader { proxy in
                    ScrollView(.vertical, showsIndicators: false) {
                        VStack(alignment: .leading, spacing: 0) {
                            RichMarkdownView(content: content, isUserMessage: false)
                                .font(.omXs)
                                .foregroundStyle(Color.fontSecondary)
                                .textSelection(.enabled)
                            Color.clear.frame(height: 1).id("thinking-content-end")
                        }
                    }
                    .frame(maxHeight: isStreaming ? 200 : nil)
                    .onAppear { scrollToLatest(proxy) }
                    .onChange(of: content) { _, _ in scrollToLatest(proxy) }
                }
                .padding(.horizontal, 14) // Web ThinkingSection.svelte: content padding 0 14px 14px.
                .padding(.bottom, 14)
                .overlay(alignment: .top) {
                    Rectangle().fill(Color.grey30).frame(height: 1)
                }
                .accessibilityIdentifier("thinking-content")
                .transition(reduceMotion ? .opacity : .opacity.combined(with: .move(edge: .top)))
            }
        }
        .background(isExpanded ? Color.grey20 : Color.grey10.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .overlay {
            RoundedRectangle(cornerRadius: .radius3)
                .stroke(isStreaming ? Color.grey20 : Color.grey30, lineWidth: 1)
        }
        .onAppear { synchronizeExpansion(streaming: isStreaming) }
        .onChange(of: isStreaming) { _, streaming in synchronizeExpansion(streaming: streaming) }
    }

    private func synchronizeExpansion(streaming: Bool) {
        if streaming, !userToggledWhileStreaming {
            isExpanded = true
        } else if !streaming {
            if !userToggledWhileStreaming {
                isExpanded = false
            }
            userToggledWhileStreaming = false
        }
    }

    private func scrollToLatest(_ proxy: ScrollViewProxy) {
        guard isStreaming else { return }
        Task { @MainActor in
            await Task.yield()
            proxy.scrollTo("thinking-content-end", anchor: .bottom)
        }
    }
}

// MARK: - Streaming thinking indicator

struct ThinkingIndicator: View {
    @State private var dotCount = 0
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: .spacing2) {
            Icon("reasoning", size: 14)
                .foregroundStyle(Color.fontTertiary)
                .accessibilityHidden(true)

            Text(LocalizationManager.shared.text("chat.thinking.header_streaming") + String(repeating: ".", count: dotCount))
                .font(.omXs).fontWeight(.medium)
                .foregroundStyle(Color.fontTertiary)
        }
        .padding(.horizontal, .spacing3)
        .padding(.vertical, .spacing2)
        .background(Color.grey10.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("AI is thinking")
        .onReceive(timer) { _ in
            if !reduceMotion {
                dotCount = (dotCount + 1) % 4
            }
        }
    }
}
