// Global Header call pill: replaces the OpenMates brand mark while a call runs
// and its bound chat is not on screen; pressing it opens the bound chat.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/voicecall/VoiceCallPill.svelte
//          frontend/packages/ui/src/components/Header.svelte (brand slot, .voice-call-pill-visible)
//          frontend/apps/web_app/src/routes/+page.svelte (showGlobalVoiceCall, VOICE_CALL_PILL_CONTEXT)
// CSS:     .call-pill: padding spacing-4/spacing-5 (inline spacing-4 at ≤500px in Header.svelte), min-height 2.5rem, radius-full,
//          gradient-primary, color-font-button, font-size-small, gap spacing-2,
//          icon .875rem, timer tabular-nums at .48 opacity while input is idle,
//          voice-call-pulse 3s ease-in-out infinite (opacity 1 → .82), none for reduced motion
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.call-strip-layout
#if !os(watchOS)
import SwiftUI

/// Header brand slot: the brand mark, or the call pill while a connecting or
/// live call's bound chat does not render its own strip (web `showGlobalVoiceCall`).
@MainActor
struct NativeVoiceCallHeaderBrandSlot<Brand: View>: View {
    @ObservedObject var runtime: NativeVoiceCallRootRuntime
    let onReturn: (String) -> Void
    /// Reports whether the pill replaced the brand, so the header keeps its slot.
    var onPillVisibilityChange: (Bool) -> Void = { _ in }
    @ViewBuilder let brand: () -> Brand
    var body: some View {
        if let coordinator = runtime.coordinator {
            NativeVoiceCallHeaderBrandSlotBody(coordinator: coordinator, presentation: runtime.presentation,
                                               onReturn: onReturn, onPillVisibilityChange: onPillVisibilityChange,
                                               brand: brand)
        } else {
            brand()
        }
    }
}

/// Observes the coordinator and presentation directly so the Debug fixture can
/// reuse the production slot without a root runtime.
@MainActor
struct NativeVoiceCallHeaderBrandSlotBody<Brand: View>: View {
    @ObservedObject var coordinator: NativeVoiceCallAppCoordinator
    @ObservedObject var presentation: NativeVoiceCallRootPresentation
    let onReturn: (String) -> Void
    var onPillVisibilityChange: (Bool) -> Void = { _ in }
    @ViewBuilder let brand: () -> Brand
    private var pillChatID: String? {
        guard coordinator.isActive, let chatID = coordinator.boundChatID,
              presentation.stripHostedChatID != chatID else { return nil }
        return chatID
    }
    var body: some View {
        if let chatID = pillChatID {
            NativeVoiceCallHeaderPill(coordinator: coordinator) { onReturn(chatID) }
                // While the pill is on screen it is the call's only global control (web
                // renders no floating bar then); the root overlay reads this flag.
                .onAppear { presentation.headerPillChatID = chatID; onPillVisibilityChange(true) }
                .onDisappear {
                    if presentation.headerPillChatID == chatID { presentation.headerPillChatID = nil }
                    onPillVisibilityChange(false)
                }
        } else {
            brand()
        }
    }
}

/// Web `VoiceCallPill.svelte`: handset icon plus mm:ss timer on the primary gradient.
@MainActor
struct NativeVoiceCallHeaderPill: View {
    @ObservedObject var coordinator: NativeVoiceCallAppCoordinator
    let onReturn: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var dimmed = false
    var body: some View {
        Button(action: onReturn) {
            HStack(spacing: .spacing2) {
                Icon("audiocall", size: 14).accessibilityHidden(true)
                Text(coordinator.formattedDuration)
                    .font(.omSmall.weight(.bold)).monospacedDigit()
                    .opacity(coordinator.activityActive ? 1 : 0.48)
                    .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: coordinator.activityActive)
                    .accessibilityIdentifier("voice-call-pill-timer")
            }
            .font(.omSmall)
            .foregroundStyle(Color.fontButton)
            .padding(.vertical, .spacing4)
            // Header.svelte narrows the pill to padding-inline spacing-4 at ≤500px.
            .padding(.horizontal, horizontalSizeClass == .compact ? .spacing4 : .spacing5)
            .frame(minHeight: 40)
            .background(LinearGradient.primary, in: Capsule())
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .fixedSize()
        .opacity(dimmed ? 0.82 : 1)
        .onAppear { updatePulse() }
        .onChange(of: reduceMotion) { _, _ in updatePulse() }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(AppStrings.nativeCall("return_to_chat"))
        .accessibilityValue(coordinator.formattedDuration)
        .accessibilityIdentifier("voice-call-pill")
    }
    /// Web `voice-call-pulse`: 3 s ease-in-out cycle between opacity 1 and .82.
    private func updatePulse() {
        if reduceMotion {
            withAnimation(nil) { dimmed = false }
        } else {
            withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) { dimmed = true }
        }
    }
}
#endif
