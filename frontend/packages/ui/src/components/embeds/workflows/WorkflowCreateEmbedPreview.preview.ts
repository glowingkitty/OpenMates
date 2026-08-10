/**
 * Preview fixtures for workflow creation app-skill embeds.
 * These snapshots drive the local embed preview gallery.
 * They intentionally use neutral non-OpenMates scenarios.
 * Fullscreen coverage lives in the web app Playwright spec.
 */

const results = [
  {
    embed_id: 'legacy-workflow-garden-1',
    workflow_id: 'workflow-garden-1',
    title: 'Weekly balcony garden reminder',
    description: 'Every Saturday morning, remind me to water herbs and note which plants need trimming.',
    status: 'ready',
    enabled: true,
    trigger_summary: 'Manual or weekly Saturday reminder',
  },
];

const defaultProps = {
  id: 'preview-workflow-create',
  instruction: 'Create a simple manual workflow for a weekly balcony garden check-in',
  status: 'finished' as const,
  results,
  resultCount: results.length,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  processing: { ...defaultProps, id: 'preview-workflow-create-processing', status: 'processing' as const, results: [], resultCount: 0 },
  mobile: { ...defaultProps, id: 'preview-workflow-create-mobile', isMobile: true },
};
