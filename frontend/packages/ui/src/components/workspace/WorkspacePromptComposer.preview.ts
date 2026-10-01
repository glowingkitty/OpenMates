/** Static workspace prompt fixture. Recording uses the browser's fake microphone in component tests. */
const defaultProps = {
  surface: 'workflows',
  value: '',
  placeholder: 'Describe new workflow.',
  submitLabel: 'Create workflow',
  submittingLabel: 'Creating...',
  disabled: false,
  submitting: false,
  onSubmit: async (_value: string) => {},
  onMicClick: () => {},
  fileImport: { label: 'Import .workflow.yml', testId: 'workflow-import-button', onClick: () => {} },
};

export default defaultProps;

export const variants = {
  workflowEdit: { ...defaultProps, placeholder: 'Describe workflow change.', submitLabel: 'Update workflow', submittingLabel: 'Updating...', fileImport: undefined },
  tasks: { ...defaultProps, surface: 'tasks', placeholder: 'Click to add or update tasks', submitLabel: 'Send', submittingLabel: 'Saving...', fileImport: undefined },
  disabled: { ...defaultProps, disabled: true },
  projects: { ...defaultProps, surface: 'projects', placeholder: 'Create a project', fileImport: undefined },
  recording: { ...defaultProps, recording: true, onRecordingClose: () => {} },
};
