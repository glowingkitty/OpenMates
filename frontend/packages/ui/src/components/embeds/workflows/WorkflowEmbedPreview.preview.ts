/**
 * Preview fixtures for workflow child embed cards.
 * These snapshots drive the local embed preview gallery.
 * They intentionally avoid live workflow workspace reads.
 * Fullscreen coverage lives in the web app Playwright spec.
 */

const defaultProps = {
  id: 'preview-workflow-child',
  workflowId: 'workflow-garden-1',
  title: 'Weekly balcony garden reminder',
  description: 'Every Saturday morning, remind me to water herbs and note which plants need trimming.',
  status: 'ready',
  enabled: true,
  triggerSummary: 'Manual or weekly Saturday reminder',
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  disabled: { ...defaultProps, id: 'preview-workflow-disabled', enabled: false },
  mobile: { ...defaultProps, id: 'preview-workflow-child-mobile', isMobile: true },
};
