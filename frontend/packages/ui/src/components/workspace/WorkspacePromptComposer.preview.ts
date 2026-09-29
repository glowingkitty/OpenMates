/** Static workspace prompt fixture. Recording uses the browser's fake microphone in component tests. */
const defaultProps = {
  surface: 'workflows',
  value: '',
  placeholder: 'Describe a workflow',
  submitLabel: 'Create workflow',
  submittingLabel: 'Creating...',
  disabled: false,
  submitting: false,
  onSubmit: async (_value: string) => {},
  onMicClick: () => {},
};

export default defaultProps;

export const variants = {
  recording: { ...defaultProps, recording: true, onRecordingClose: () => {} },
};
