/**
 * Preview fixtures for task search app-skill embeds.
 * These snapshots drive the local embed preview gallery.
 * They intentionally use neutral non-OpenMates scenarios.
 * Fullscreen coverage lives in the web app Playwright spec.
 */

const results = [
  {
    embed_id: 'legacy-task-packing-1',
    task_id: 'task-packing-1',
    short_id: 'T-221',
    title: 'Pack passport and travel documents',
    description: 'Put passport, train ticket, and hotel confirmation in the front backpack pocket.',
    status: 'todo',
    assignee: 'user',
  },
  {
    embed_id: 'legacy-task-packing-2',
    task_id: 'task-packing-2',
    short_id: 'T-222',
    title: 'Charge camera batteries',
    description: 'Charge both batteries and put the charger in the electronics pouch.',
    status: 'done',
    assignee: 'user',
  },
];

const defaultProps = {
  id: 'preview-task-search',
  query: 'packing list tasks',
  status: 'finished' as const,
  results,
  resultCount: results.length,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  noResults: { ...defaultProps, id: 'preview-task-search-empty', query: 'old tax folder cleanup', results: [], resultCount: 0 },
  mobile: { ...defaultProps, id: 'preview-task-search-mobile', isMobile: true },
};
