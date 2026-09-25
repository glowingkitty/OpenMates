/** Static recording-overlay fixtures. They never request microphone access. */
const defaultProps = {
    initialPosition: { x: 0, y: 0 },
    enableRealtime: true,
    previewTranscript: 'Please schedule the project review for Thursday afternoon.',
};

export default defaultProps;

export const variants = {
    liveRecorder: {
        ...defaultProps,
        enableRealtime: false,
        previewTranscript: null,
    },
    waiting: {
        ...defaultProps,
        previewTranscript: '',
    },
    longTranscript: {
        ...defaultProps,
        previewTranscript:
            'Earlier words that should leave the bounded header as recognition continues. The latest spoken sentence remains visible here.',
    },
};
