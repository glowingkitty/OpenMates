/**
 * Synthetic artifact proof for deterministic operator security emails.
 * Renders the production Python MIME/HTML templates from this checkout and
 * records their actual browser presentation without sending messages or
 * introducing a product route. The approved reporting Plan requires both
 * phone and laptop proof with hash-bound artifacts and toggleable captions.
 */
import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
// Existing proof helper exports CommonJS for the repository's Playwright runner.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const ROOT = path.resolve(__dirname, '../../../..');
const DEVICES = ['web-phone', 'web-laptop'];
const DEVICE = Number(process.env.PLAYWRIGHT_VIDEO_WIDTH) === 390 ? 'web-phone' : 'web-laptop';
const FIXTURES = ['digest-clean', 'digest-findings', 'digest-incomplete', 'critical-alert'];
const CONTRACT = defineVideoProof({
  id: 'security-reporting-email-artifacts',
  title: 'Read the daily security report and critical alert',
  surface: 'web',
  domain: 'Synthetic operator email artifact',
  devices: DEVICES,
  transcript: [
    { id: 'clean', text: 'The daily report shows its environment, UTC window, and complete finding totals, including clean days.', checkpoint: 'digest-clean', devices: DEVICES },
    { id: 'findings', text: 'Findings are grouped into new, open, and resolved entries, with advisory links.', checkpoint: 'digest-findings', devices: DEVICES },
    { id: 'incomplete', text: 'Incomplete scans stay visible. Collection details identify partial history, disabled monitoring, and scan failures.', checkpoint: 'digest-incomplete', devices: DEVICES },
    { id: 'critical', text: 'A critical incident uses a separate alert with the affected package and advisory.', checkpoint: 'critical-alert', devices: DEVICES }
  ],
  assertions: FIXTURES.map((fixture) => ({ id: fixture, checkpoint: fixture, visual: `The ${fixture} production email artifact is readable without horizontal clipping or raw error text.`, devices: DEVICES })),
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 2000, maximumHoldMs: 6000 }
});

// contract-test-file: infrastructure
// Reporting coverage: security-reporting.digest.actionable-content,security-reporting.content.operator-boundary,security-reporting.coverage.no-false-clean
// contract-test: infrastructure
test('records synthetic production security email artifacts', async ({ page }, testInfo) => {
  const output = testInfo.outputPath('security-email-artifacts');
  execFileSync('python3', [path.join(ROOT, 'scripts/verify_security_reporting.py'), '--render-proof', '--fixtures', path.join(ROOT, 'scripts/tests/fixtures/security-reporting'), '--output', output], { cwd: ROOT, timeout: 30000 });
  const expectedViewport = DEVICE === 'web-phone' ? { width: 390, height: 844 } : { width: 1440, height: 900 };
  await page.setViewportSize(expectedViewport);
  const proof = createVideoProofRuntime(CONTRACT, {
    device: DEVICE,
    attach: testInfo.attach.bind(testInfo),
    captureFrame: () => page.screenshot({ type: 'png' })
  });
  for (const fixture of FIXTURES) {
    const html = readFileSync(path.join(output, `${fixture}.html`), 'utf8');
    await testInfo.attach(`${fixture}.html`, { body: Buffer.from(html), contentType: 'text/html' });
    await testInfo.attach(`${fixture}.eml`, { path: path.join(output, `${fixture}.eml`), contentType: 'message/rfc822' });
    if (fixture === FIXTURES[0]) {
      await page.setContent(html, { waitUntil: 'load' });
    } else {
    await proof.action(`read-${fixture}`, () => page.setContent(html, { waitUntil: 'load' }));
    }
    await proof.assert(fixture, async () => {
      await expect(page.getByRole('heading', { level: 1 })).toContainText(fixture === 'critical-alert' ? 'Critical security alert' : 'Security report:');
      if (fixture !== 'critical-alert') {
        await expect(page.getByRole('heading', { name: 'Finding totals', exact: true })).toBeVisible();
        await expect(page.getByRole('heading', { name: 'Coverage', exact: true })).toBeVisible();
      }
      if (fixture === 'digest-incomplete') {
        await expect(page.getByText('eu_vulns: 23/24 coverage incomplete', { exact: true })).toBeVisible();
        await page.getByRole('heading', { name: 'Collection and remediation details' }).scrollIntoViewIfNeeded();
        await expect(page.getByText('History: partial', { exact: true })).toBeVisible();
        await expect(page.getByText('dependabot monitoring: disabled', { exact: true })).toBeVisible();
        await expect(page.getByText('eu_vulns failure: osv_batch_failed', { exact: true })).toBeVisible();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      for (const link of await page.getByRole('link').all()) {
        expect(await link.getAttribute('href')).toMatch(/^https:\/\/(github\.com\/advisories\/GHSA-|nvd\.nist\.gov\/vuln\/detail\/CVE-)/);
      }
    });
    await proof.checkpoint(fixture);
    // Preserve a readable interval in the actual recording for each caption.
    // This is capture pacing after assertions, not a readiness/test retry wait.
    await new Promise((resolve) => setTimeout(resolve, CONTRACT.tutorial.maximumHoldMs));
    await testInfo.attach(`${fixture}.sha256`, { body: Buffer.from(createHash('sha256').update(html).digest('hex')), contentType: 'text/plain' });
  }
  await testInfo.attach('security-email-manifest', { path: path.join(output, 'manifest.json'), contentType: 'application/json' });
  await proof.attach();
});
