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
final class VoiceRecorder: ObservableObject {
    @Published var isRecording = false
    @Published var duration: TimeInterval = 0
    @Published var error: String?

    private var audioRecorder: AVAudioRecorder?
    private var timer: Timer?
    private var recordingURL: URL?

    func startRecording() {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default)
            try session.setActive(true)
        } catch {
            self.error = "Microphone permission required"
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

struct VoiceRecordingButton: View {
    @StateObject private var recorder = VoiceRecorder()
    let onRecordingComplete: (URL) -> Void

    var body: some View {
        Group {
            if recorder.isRecording {
                HStack(spacing: .spacing3) {
                    Circle()
                        .fill(Color.error)
                        .frame(width: 8, height: 8)

                    Text(formatDuration(recorder.duration))
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(Color.fontPrimary)

                    Button { cancel() } label: {
                        Icon("close", size: 20)
                            .foregroundStyle(Color.fontTertiary)
                    }

                    Button { stop() } label: {
                        Icon("stop_processing", size: 24)
                            .foregroundStyle(Color.error)
                    }
                }
            } else {
                Button { recorder.startRecording() } label: {
                    Icon("recordaudio", size: 24)
                        .foregroundStyle(Color.fontTertiary)
                }
            }
        }
    }

    private func stop() {
        if let url = recorder.stopRecording() {
            onRecordingComplete(url)
        }
    }

    private func cancel() {
        recorder.cancelRecording()
    }

    private func formatDuration(_ seconds: TimeInterval) -> String {
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return String(format: "%d:%02d", mins, secs)
    }
}
