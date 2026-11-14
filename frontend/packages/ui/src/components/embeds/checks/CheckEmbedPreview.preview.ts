/** Preview mock data for CheckEmbedPreview. */
import { failedRequiredUnit, neverRun, passedMixed, stale, waitingForConfirmation } from './checkFixtures';

const defaultProps = {
  presentationOnly: true,
  id: 'preview-check-1',
  check: passedMixed,
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Check fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  failedRequiredUnit: { ...defaultProps, id: 'preview-check-failed', check: failedRequiredUnit },
  waitingForConfirmation: { ...defaultProps, id: 'preview-check-waiting', check: waitingForConfirmation },
  stale: { ...defaultProps, id: 'preview-check-stale', check: stale },
  neverRun: { ...defaultProps, id: 'preview-check-never', check: neverRun },
};
