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
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  openmates: { ...defaultProps, id: 'preview-task-openmates', assignee: 'openmates', status: 'in_progress' },
  mobile: { ...defaultProps, id: 'preview-task-child-mobile', isMobile: true },
};
