/**
 * Preview mock data for RecordingEmbedPreview (audio/record skill result).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/audio
 */

/** Default props — shows a finished recording transcription */
const defaultProps = {
  id: "preview-audio-1",
  filename: "voice-memo-2026-03-10.webm",
  status: "finished" as const,
  transcript:
    "This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week.",
  duration: "0:42",
  model: "voxtral-mini-2602",
  isMobile: false,
  isAuthenticated: true,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
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
