// Voice recording input — record audio messages directly in chat.
// Mirrors RecordAudio.svelte: start/stop/cancel, duration timer, waveform.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/RecordAudio.svelte
// CSS:     RecordAudio.svelte <style>
// i18n:    enter_message.record_audio.{slide_left_to_cancel,press_esc_to_cancel,release_to_finish,
//          press_and_hold_reminder,allow_microphone_access,microphone_blocked}
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import AVFoundation

@MainActor
enum MicPermissionState: Equatable {
    case unknown
    case granted
    case denied
}

@MainActor
final class VoiceRecorder: ObservableObject {
    static let waveformSampleCount = 64
    static let waveformSampleInterval: TimeInterval = 0.05
    static let waveformMinimumVisibleLevel = 0.04

    private static let waveformMinimumDecibels: Float = -46
    private static let waveformMaximumDecibels: Float = -18

    @Published var isRecording = false
    @Published var duration: TimeInterval = 0
    @Published var error: String?
    @Published private(set) var waveformSamples = Array(
        repeating: 0.0,
        count: VoiceRecorder.waveformSampleCount
    )

    private var audioRecorder: AVAudioRecorder?
    private var durationTask: Task<Void, Never>?
    private var waveformTask: Task<Void, Never>?
    private var recordingURL: URL?

    deinit {
        durationTask?.cancel()
        waveformTask?.cancel()
    }

    func requestPermission() async -> Bool {
        #if os(iOS)
        return await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
        #else
        return true
        #endif
    }

    func startRecording() {
        guard !isRecording else { return }
        error = nil
        resetWaveform()
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default)
            try session.setActive(true)
        } catch {
            self.error = AppStrings.microphoneBlocked
            return
        }
        #endif

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("recording_\(Int(Date().timeIntervalSince1970)).m4a")
        recordingURL = url

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44100.0,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]

        do {
            audioRecorder = try AVAudioRecorder(url: url, settings: settings)
            audioRecorder?.isMeteringEnabled = true
            guard audioRecorder?.record() == true else {
                audioRecorder?.deleteRecording()
                audioRecorder = nil
                recordingURL = nil
                error = AppStrings.microphoneBlocked
                return
            }
            isRecording = true
            duration = 0

            durationTask = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .milliseconds(100))
                    guard let self, self.isRecording, !Task.isCancelled else { return }
                    self.duration += 0.1
                }
            }

            waveformTask = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .milliseconds(50))
                    guard let self, self.isRecording, !Task.isCancelled else { return }
                    self.sampleWaveform()
                }
            }
        } catch {
            stopTimersAndWaveform()
            self.error = error.localizedDescription
        }
    }

    func stopRecording() -> URL? {
        guard isRecording else {
            stopTimersAndWaveform()
            return nil
        }
        audioRecorder?.stop()
        isRecording = false
        stopTimersAndWaveform()
        return recordingURL
    }

    func cancelRecording() {
        audioRecorder?.stop()
        audioRecorder?.deleteRecording()
        isRecording = false
        stopTimersAndWaveform()
        duration = 0
        recordingURL = nil
    }

    static func normalizedWaveformLevel(forAveragePower averagePower: Float) -> Double {
        guard averagePower.isFinite, averagePower > waveformMinimumDecibels else { return 0 }
        let decibelRange = waveformMaximumDecibels - waveformMinimumDecibels
        let normalized = (averagePower - waveformMinimumDecibels) / decibelRange
        return Double(min(1, max(0, normalized)))
    }

    func appendLocalWaveformLevel(_ normalizedLevel: Double) {
        let level = min(1, max(0, normalizedLevel))
        waveformSamples = Array(waveformSamples.dropFirst()) + [level]
    }

    func resetWaveform() {
        waveformSamples = Array(repeating: 0, count: Self.waveformSampleCount)
    }

    private func sampleWaveform() {
        guard isRecording, let audioRecorder else { return }
        audioRecorder.updateMeters()
        appendLocalWaveformLevel(
            Self.normalizedWaveformLevel(
                forAveragePower: audioRecorder.averagePower(forChannel: 0)
            )
        )
    }

    private func stopTimersAndWaveform() {
        durationTask?.cancel()
        durationTask = nil
        waveformTask?.cancel()
        waveformTask = nil
        audioRecorder?.isMeteringEnabled = false
        resetWaveform()
    }
}

struct ComposerRecordingOverlay: View {
    private static let waveformTrackHeight: CGFloat = 64
    private static let waveformBarSpacing: CGFloat = 2
    private static let waveformBarMaximumWidth: CGFloat = 3
    private static let waveformBarMinimumHeight: CGFloat = 2
    private static let recordingPanelMinimumHeight: CGFloat = 220

    @ObservedObject var recorder: VoiceRecorder
    let dragOffsetX: CGFloat
    var startedFromKeyboard = false
    let onStop: (URL) -> Void
    let onCancel: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: .spacing4) {
                Text(recorder.error ?? AppStrings.releaseToFinishRecording)
                    .font(.omP.weight(.bold))
                    .foregroundStyle(Color.white)
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("release-text")

                recordingWaveform
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            HStack(spacing: .spacing4) {
                Text(formatDuration(recorder.duration))
                    .font(.omSmall.weight(.bold))
                    .foregroundStyle(Color.white)
                    .monospacedDigit()
                    .frame(minWidth: 60)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing2)
                    .background(Color.error)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    .accessibilityIdentifier("timer-pill")

                Button(action: onCancel) {
                    Group {
                        if startedFromKeyboard {
                            Text(AppStrings.pressEscToCancelRecording)
                                .font(.omXs)
                                .foregroundStyle(Color.white.opacity(0.7))
                        } else {
                            HStack(spacing: .spacing2) {
                                Text("‹")
                                    .font(.omH3)
                                    .foregroundStyle(Color.white.opacity(0.5))
                                Text(AppStrings.slideLeftToCancelRecording)
                                    .font(.omXs)
                                    .foregroundStyle(Color.white.opacity(0.7))
                            }
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .opacity(max(0.3, 1 + Double(dragOffsetX / 80)))
                .accessibilityLabel(startedFromKeyboard ? AppStrings.pressEscToCancelRecording : AppStrings.slideLeftToCancelRecording)
                .accessibilityIdentifier("cancel-hint")

                Button {
                    if let url = recorder.stopRecording() {
                        onStop(url)
                    }
                } label: {
                    Icon("recordaudio", size: 22)
                        .foregroundStyle(Color.white)
                        .frame(width: 44, height: 44)
                        .background(Color.buttonPrimary)
                        .clipShape(Circle())
                        .shadow(color: .black.opacity(0.25), radius: 8, x: 0, y: 2)
                        .offset(x: max(-120, dragOffsetX))
                }
                .buttonStyle(.plain)
                .help(Text(AppStrings.releaseToFinishRecording))
                .accessibilityLabel(AppStrings.releaseToFinishRecording)
                .accessibilityIdentifier("mic-button")
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("record-controls")
        }
        .padding(.top, .spacing8)
        .padding(.horizontal, .spacing8)
        .padding(.bottom, .spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .frame(minHeight: Self.recordingPanelMinimumHeight)
        .background(LinearGradient.primary)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .overlay(alignment: .topLeading) {
            Button(action: onCancel) {
                Color.clear.frame(width: 1, height: 1)
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.cancelAction)
            .accessibilityHidden(true)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("record-overlay")
    }

    private var recordingWaveform: some View {
        GeometryReader { proxy in
            let totalSpacing = Self.waveformBarSpacing * CGFloat(VoiceRecorder.waveformSampleCount - 1)
            let availableBarWidth = (proxy.size.width - totalSpacing) / CGFloat(VoiceRecorder.waveformSampleCount)
            let barWidth = min(Self.waveformBarMaximumWidth, max(1, availableBarWidth))

            HStack(spacing: Self.waveformBarSpacing) {
                ForEach(Array(recorder.waveformSamples.enumerated()), id: \.offset) { _, level in
                    Capsule()
                        .fill(Color.white)
                        .frame(
                            width: barWidth,
                            height: max(
                                Self.waveformBarMinimumHeight,
                                Self.waveformTrackHeight * max(VoiceRecorder.waveformMinimumVisibleLevel, level)
                            )
                        )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: 480)
        .frame(height: Self.waveformTrackHeight)
        .padding(.horizontal, .spacing2)
        .allowsHitTesting(false)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(AppStrings.voiceRecording)
        .accessibilityValue(AppStrings.releaseToFinishRecording)
        .accessibilityIdentifier("recording-waveform")
    }

    private func formatDuration(_ seconds: TimeInterval) -> String {
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return String(format: "%02d:%02d", mins, secs)
    }
}
