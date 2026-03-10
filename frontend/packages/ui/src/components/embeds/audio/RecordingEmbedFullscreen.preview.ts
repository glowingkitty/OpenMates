/**
 * Preview mock data for RecordingEmbedFullscreen (audio/record skill result).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/audio
 */

/** Default props — shows a finished recording transcription in fullscreen */
const defaultProps = {
  filename: "voice-memo-2026-03-10.webm",
  transcript:
    "This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week. Key highlights include the completion of the authentication refactor and the new API rate limiting feature.",
  duration: "0:42",
  model: "voxtral-mini-2602",
  isEditable: false,
  onClose: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Editable transcript (pre-send state) */
  editable: {
    ...defaultProps,
    isEditable: true,
    embedId: "preview-audio-fullscreen-editable",
    onTranscriptChange: (_embedId: string, _transcript: string) => {},
  },

  /** Long transcript */
  longTranscript: {
    ...defaultProps,
    filename: "meeting-notes-2026-03-10.webm",
    duration: "12:34",
    transcript:
      "Welcome everyone to the quarterly planning session. Today we will cover three main topics: the product roadmap for Q2, the engineering capacity planning, and the customer feedback synthesis from last quarter.\n\nStarting with the product roadmap: the team has identified five key areas of focus. First, we need to improve the onboarding flow based on user research. Second, we are adding collaborative features to the workspace. Third, we are enhancing the AI assistant capabilities. Fourth, we need to address performance improvements in the mobile app. Fifth, we are expanding our API for third-party integrations.\n\nFor engineering capacity, we currently have twelve engineers distributed across four teams. The AI team has three engineers working on model integrations and the skill framework. The platform team has four engineers working on infrastructure and developer tools. The product team has three engineers working on core features. The mobile team has two engineers working on iOS and Android.\n\nRegarding customer feedback, the most requested features are offline mode, better search functionality, and more granular permission controls. We have triaged these into our backlog with priorities set for Q2 delivery.",
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    isMobile: true,
  },
};
