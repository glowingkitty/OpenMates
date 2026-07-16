/**
 * Preview fixtures for workflow search app-skill embeds.
 * These snapshots drive the local embed preview gallery.
 * They intentionally use neutral non-OpenMates scenarios.
 * Fullscreen coverage lives in the web app Playwright spec.
 */

const results = [
  {
    embed_id: 'legacy-workflow-packing-1',
    workflow_id: 'workflow-packing-1',
    title: 'Trip packing reminder workflow',
    description: 'A manual workflow that creates a short packing checklist and reminder before each trip.',
    status: 'ready',
    enabled: true,
    trigger_summary: 'Manual trigger',
  },
  {
    embed_id: 'legacy-workflow-packing-2',
    workflow_id: 'workflow-packing-2',
    title: 'Departure day weather check',
    description: 'Check the forecast on the morning of departure and remind me about rain gear if needed.',
    status: 'ready',
    enabled: false,
    trigger_summary: 'Manual trigger',
  },
];

const defaultProps = {
  id: 'preview-workflow-search',
  query: 'travel packing workflows',
  status: 'finished' as const,
  results,
  resultCount: results.length,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  noResults: { ...defaultProps, id: 'preview-workflow-search-empty', query: 'invoice approval workflow', results: [], resultCount: 0 },
  mobile: { ...defaultProps, id: 'preview-workflow-search-mobile', isMobile: true },
};
