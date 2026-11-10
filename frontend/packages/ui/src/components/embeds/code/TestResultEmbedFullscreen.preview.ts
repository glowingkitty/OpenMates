/** Preview mock data for TestResultEmbedFullscreen. */
import { browserFailed, browserPassed, cliResult, fixtureEvidenceUrl, staleResult, unitResult } from './testResultFixtures';

const fixture = (decodedContent: Record<string, unknown>) => ({
  data: { decodedContent, attrs: {} },
  embedId: 'preview-test-result-1',
  resolveEvidenceUrl: fixtureEvidenceUrl,
  onClose: () => console.log('[Preview] close'),
});

const defaultProps = fixture(browserPassed);

export default defaultProps;

export const variants = {
  browserFailed: fixture(browserFailed),
  cli: fixture(cliResult),
  unit: fixture(unitResult),
  stale: fixture(staleResult),
};
