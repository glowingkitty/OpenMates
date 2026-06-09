// Voice recording input — record audio messages directly in chat.
// Mirrors RecordAudio.svelte: start/stop/cancel, duration timer, waveform.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/RecordAudio.svelte
// CSS:     RecordAudio.svelte <style>
// i18n:    enter_message.record_audio.{slide_left_to_cancel,release_to_finish,
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
    @Published var isRecording = false
    @Published var duration: TimeInterval = 0
    @Published var error: String?

    private var audioRecorder: AVAudioRecorder?
    private var timer: Timer?
    private var recordingURL: URL?

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
        error = nil
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
            audioRecorder?.record()
            isRecording = true
            duration = 0

            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    self?.duration += 0.1
                }
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    func stopRecording() -> URL? {
        guard isRecording else { return nil }
        audioRecorder?.stop()
        timer?.invalidate()
        timer = nil
        isRecording = false
        return recordingURL
    }

    func cancelRecording() {
        audioRecorder?.stop()
        audioRecorder?.deleteRecording()
        timer?.invalidate()
        timer = nil
        isRecording = false
        duration = 0
        recordingURL = nil
    }
}

struct ComposerRecordingOverlay: View {
    @ObservedObject var recorder: VoiceRecorder
    let dragOffsetX: CGFloat
    let onStop: (URL) -> Void
    let onCancel: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            Text(recorder.error ?? AppStrings.releaseToFinishRecording)
                .font(.omP.weight(.bold))
                .foregroundStyle(Color.white)
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("release-text")

            Spacer()

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

                HStack(spacing: .spacing2) {
                    Text("‹")
                        .font(.omH3)
                        .foregroundStyle(Color.white.opacity(0.5))
                    Text(AppStrings.slideLeftToCancelRecording)
                        .font(.omXs)
                        .foregroundStyle(Color.white.opacity(0.7))
                }
                .opacity(max(0.3, 1 + Double(dragOffsetX / 80)))
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .combine)
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
                .accessibilityLabel(AppStrings.releaseToFinishRecording)
                .accessibilityIdentifier("mic-button")
            }
        }
        .padding(.top, .spacing8)
        .padding(.horizontal, .spacing8)
        .padding(.bottom, .spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(LinearGradient.primary)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("record-overlay")
    }

    private func formatDuration(_ seconds: TimeInterval) -> String {
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return String(format: "%02d:%02d", mins, secs)
    }
}
