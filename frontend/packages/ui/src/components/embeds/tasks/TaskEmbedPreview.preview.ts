/**
 * Preview fixtures for task child embed cards.
 * These snapshots drive the local embed preview gallery.
 * They intentionally avoid live task workspace reads.
 * Fullscreen coverage lives in the web app Playwright spec.
 */

const defaultProps = {
  id: 'preview-task-child',
  taskId: 'task-garden-1',
  shortId: 'T-104',
  title: 'Buy starter soil and basil seeds',
  description: 'Pick up seed trays, starter soil, and basil seeds before Saturday.',
  status: 'todo',
  assignee: 'user',
  dueDate: '2026-11-24',
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  openmates: { ...defaultProps, id: 'preview-task-openmates', assignee: 'openmates', status: 'in_progress' },
  validWithoutDueDate: { ...defaultProps, id: 'preview-task-no-due', shortId: '', dueDate: '' },
  inProgress: { ...defaultProps, id: 'preview-task-in-progress', status: 'in_progress' },
  invalid: {
    ...defaultProps,
    id: 'preview-task-invalid',
    // Never created: no Task, so no id (messages as the backend validator writes them).
    taskId: '',
    shortId: '',
    validation: {
      status: 'invalid',
      errors: ['The Project "Garden beds" was not found.', 'Use a valid date or a timestamp with a UTC offset.'],
      warnings: [],
    },
  },
  longTitle: {
    ...defaultProps,
    id: 'preview-task-long-title',
    title: 'Plan the whole spring planting season for the front garden, the herb boxes on the balcony and the shared allotment',
  },
  mobile: { ...defaultProps, id: 'preview-task-child-mobile', isMobile: true },
};
