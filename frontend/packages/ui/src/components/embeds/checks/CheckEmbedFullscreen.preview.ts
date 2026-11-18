/** Preview mock data for CheckEmbedFullscreen. */
import { failedRequiredUnit, neverRun, passedMixed, running, stale, storedHumanSource, waitingForConfirmation } from './checkFixtures';

const fixture = (check: typeof passedMixed) => ({
  check,
  embedId: 'preview-check-1',
  onClose: () => console.log('[Preview] close'),
  onRun: () => console.log('[Preview] run'),
  onCancel: () => console.log('[Preview] cancel'),
  onConfirm: (bindingId: string, decision: string) => console.log('[Preview] confirm', bindingId, decision),
  onSelectRun: (runId: string) => console.log('[Preview] select run', runId),
  onOpenTestResult: (embedId: string) => console.log('[Preview] open test result', embedId),
});

const defaultProps = fixture(passedMixed);

export default defaultProps;

export const variants = {
  failedRequiredUnit: fixture(failedRequiredUnit),
  waitingForConfirmation: fixture(waitingForConfirmation),
  stale: fixture(stale),
  neverRun: fixture(neverRun),
  running: fixture(running),
  storedHumanSource: fixture(storedHumanSource),
};
