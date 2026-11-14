// Live Activity for an active voice call: Lock Screen banner and Dynamic Island.
// Target: OpenMatesWidget. Mate name, call timer, hang-up button.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/voicecall/VoiceCallBar.svelte (title, timer, hang-up)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.apple.live-activity
#if os(iOS) && canImport(ActivityKit)
import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

@available(iOS 16.2, *)
struct OpenMatesCallLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: NativeVoiceCallActivityAttributes.self) { context in
            CallActivityBanner(attributes: context.attributes, state: context.state)
                .padding(.spacing6)
                .widgetURL(URL(string: "openmates://chat"))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Text(context.attributes.mateName).font(.omP).lineLimit(1)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    CallTimer(attributes: context.attributes, state: context.state).font(.omP)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    CallHangUpButton(callID: context.attributes.callID)
                }
            } compactLeading: {
                Image(systemName: "phone.fill").foregroundStyle(Color.buttonPrimary)
            } compactTrailing: {
                CallTimer(attributes: context.attributes, state: context.state).frame(maxWidth: 55)
            } minimal: {
                Image(systemName: "phone.fill").foregroundStyle(Color.buttonPrimary)
            }
            .widgetURL(URL(string: "openmates://chat"))
        }
    }
}

@available(iOS 16.2, *)
private struct CallTimer: View {
    let attributes: NativeVoiceCallActivityAttributes
    let state: NativeVoiceCallActivityAttributes.ContentState
    var body: some View {
        if state.phase == "live" {
            Text(timerInterval: attributes.startedAt...Date.distantFuture, pauseTime: nil, countsDown: false)
                .monospacedDigit()
        } else {
            Text(CallActivityStrings.connecting)
        }
    }
}

@available(iOS 16.2, *)
private struct CallActivityBanner: View {
    let attributes: NativeVoiceCallActivityAttributes
    let state: NativeVoiceCallActivityAttributes.ContentState
    var body: some View {
        HStack(spacing: .spacing6) {
            VStack(alignment: .leading, spacing: .spacing2) {
                Text(attributes.mateName).font(.omP).lineLimit(1)
                CallTimer(attributes: attributes, state: state).font(.omSmall)
            }
            Spacer(minLength: .spacing4)
            CallHangUpButton(callID: attributes.callID)
        }
    }
}

@available(iOS 16.2, *)
private struct CallHangUpButton: View {
    let callID: String
    var body: some View {
        if #available(iOS 17.0, *) {
            Button(intent: NativeVoiceCallHangUpIntent(callID: callID)) {
                Text(CallActivityStrings.hangUp).font(.omSmall)
                    .padding(.horizontal, .spacing6).padding(.vertical, .spacing3)
                    .foregroundStyle(Color.fontButton)
                    .background(Color.error, in: Capsule())
            }
            .buttonStyle(.plain)
        }
    }
}

private enum CallActivityStrings {
    private static func text(_ key: String) -> String { WidgetStrings.text(key, languageKey: "widget_tasks_language") }
    static var hangUp: String { text("voicecall.hangup") }
    static var connecting: String { text("voicecall.connecting_short") }
}
#endif
