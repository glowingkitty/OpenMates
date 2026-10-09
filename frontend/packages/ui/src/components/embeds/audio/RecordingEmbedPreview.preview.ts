/**
 * Preview mock data for RecordingEmbedPreview (audio/record skill result).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/audio
 */

/** Default props — shows a finished recording transcription */
const defaultProps = {
  id: "preview-audio-1",
  filename: "transcription-demo-voice-note.wav",
  status: "finished" as const,
  transcript: "Real-time transcription is working correctly in OpenMates.",
  previewAudioUrl: "/store-examples/transcription-demo-voice-note.wav",
  duration: "0:05",
  model: "voxtral-mini-2602",
  isMobile: false,
  isAuthenticated: true,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Logged-out visitor playing a reviewed public example recording. */
  guest: {
    ...defaultProps,
    id: "preview-audio-guest",
    isAuthenticated: false,
  },

  /** Uploading state */
  uploading: {
    id: "preview-audio-uploading",
    filename: "voice-memo.webm",
    status: "uploading" as const,
    duration: "1:15",
    isMobile: false,
    isAuthenticated: true,
  },

  /** Transcribing state */
  transcribing: {
    id: "preview-audio-transcribing",
    filename: "voice-memo.webm",
    status: "transcribing" as const,
    duration: "0:42",
    model: "voxtral-mini-2602",
    isMobile: false,
    isAuthenticated: true,
  },

  /** Raw transcript is visible while AI correction is running */
  correcting: {
    id: "preview-audio-correcting",
    filename: "voice-memo.webm",
    status: "correcting" as const,
    duration: "0:42",
    transcript: "Please schedule the project review for Thursday afternoon.",
    transcriptOriginal: "Please schedule the project review for Thursday afternoon.",
    model: "voxtral-mini-transcribe-realtime-2602",
    isMobile: false,
    isAuthenticated: true,
  },

  /** Error state */
  error: {
    id: "preview-audio-error",
    filename: "voice-memo.webm",
    status: "error" as const,
    uploadError: "Transcription failed. Please try again.",
    isMobile: false,
    isAuthenticated: true,
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: "preview-audio-mobile",
    isMobile: true,
  },
};
