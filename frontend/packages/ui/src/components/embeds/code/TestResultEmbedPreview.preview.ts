/** Preview mock data for TestResultEmbedPreview. */
import { browserFailed, browserNoFrame, browserPassed, cliResult, fixtureEvidenceUrl, staleResult, unitResult } from './testResultFixtures';

const defaultProps = {
  presentationOnly: true,
  id: 'preview-test-result-1',
  ...browserPassed,
  status: 'finished' as const,
  isMobile: false,
  resolveEvidenceUrl: fixtureEvidenceUrl,
  onFullscreen: () => console.log('[Preview] Test result fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  browserFailed: { ...defaultProps, id: 'preview-test-result-browser-failed', ...browserFailed },
  browserNoFrame: { ...defaultProps, id: 'preview-test-result-no-frame', ...browserNoFrame },
  cli: { ...defaultProps, id: 'preview-test-result-cli', ...cliResult },
  unit: { ...defaultProps, id: 'preview-test-result-unit', ...unitResult },
  stale: { ...defaultProps, id: 'preview-test-result-stale', ...staleResult },
  mobile: { ...defaultProps, id: 'preview-test-result-mobile', isMobile: true },
};
