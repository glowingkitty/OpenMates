/**
 * Preview fixtures for task creation app-skill embeds.
 * These snapshots drive the local embed preview gallery.
 * They intentionally use neutral non-OpenMates scenarios.
 * Fullscreen coverage lives in the web app Playwright spec.
 */

const results = [
  {
    embed_id: 'legacy-task-garden-1',
    task_id: 'task-garden-1',
    short_id: 'T-104',
    title: 'Buy starter soil and basil seeds',
    description: 'Pick up seed trays, starter soil, and basil seeds before Saturday.',
    status: 'todo',
    assignee: 'user',
  },
  {
    embed_id: 'legacy-task-garden-2',
    task_id: 'task-garden-2',
    short_id: 'T-105',
    title: 'Clear the balcony planter boxes',
    description: 'Remove old roots and rinse the boxes so the spring planting can start.',
    status: 'in_progress',
    assignee: 'user',
  },
];

const defaultProps = {
  id: 'preview-task-create',
  instruction: 'Create a practical checklist for starting a small balcony herb garden',
  status: 'finished' as const,
  results,
  resultCount: results.length,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  processing: { ...defaultProps, id: 'preview-task-create-processing', status: 'processing' as const, results: [], resultCount: 0 },
  mobile: { ...defaultProps, id: 'preview-task-create-mobile', isMobile: true },
};
