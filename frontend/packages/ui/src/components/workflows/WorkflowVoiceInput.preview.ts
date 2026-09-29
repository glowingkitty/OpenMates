/** Static preview; microphone permission and transcription are exercised in the workspace flow. */
const defaultProps = {
  previewOnly: true,
  previewText: 'Send me tomorrow’s weather at eight in Berlin time.',
  onSubmit: async (_text: string) => {},
  onReview: (_text: string) => {},
  onClose: () => {},
};

export default defaultProps;

export const variants = {
  empty: { ...defaultProps, previewText: '' },
};
