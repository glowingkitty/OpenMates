/**
 * Isolated focus activation history regression and component proof.
 * Historical records never create a countdown or mutation callbacks.
 * A current active record can expose its normal details interaction.
 * Live pending cancellation is covered separately by the authenticated flow.
 * The fixture inputs are encoded in the bare preview URL for repeatability.
 */
import { expect, test } from '../helpers/cookie-audit';
// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');
const DEVICE = Number(process.env.PLAYWRIGHT_VIDEO_WIDTH) === 390 ? 'web-phone' : 'web-laptop';
const PROOF = defineVideoProof({
    id: 'focus-mode-history', title: 'Focus history remains historical', surface: 'web',
    devices: ['web-phone', 'web-laptop'], domain: 'app.dev.openmates.org',
    transcript: [{ id: 'history-stable', text: 'A historical Career insights record stays visible without restarting activation.', checkpoint: 'history-stable', devices: ['web-phone', 'web-laptop'] }],
    assertions: [{ id: 'focus-modes.countdown', checkpoint: 'history-stable', visual: 'The historical Career insights record has no countdown or progress bar.', devices: ['web-phone', 'web-laptop'] }],
    tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});
test.describe('Focus activation component history', () => {
    // contract-test: direct surface=gui.web assertions=focus-modes.countdown,focus-modes.history-side-effects
    test('history without current active metadata never starts a countdown', async ({ page }, testInfo) => {
        const proof = createVideoProofRuntime(PROOF, { device: DEVICE, attach: testInfo.attach.bind(testInfo) });
        const query = new URLSearchParams({ chrome: '0', width: DEVICE === 'web-phone' ? '390' : '720', props: JSON.stringify({ id: 'historical-focus-record', alreadyActive: false }) });
        await page.goto(`/dev/preview/embeds/focus_mode/FocusModeActivationEmbed?${query}`, { waitUntil: 'networkidle' });
        const bar = page.getByTestId('focus-mode-bar');
        await expect(bar).toBeVisible();
        await proof.assert('focus-modes.countdown', async () => {
            expect(await page.getByTestId('focus-progress-bar').count()).toBe(0);
            await expect(page.getByTestId('focus-status-value')).not.toContainText(/Activat.*\d/i);
        });
        await bar.focus();
        await page.keyboard.press('Escape');
        await expect(bar).toBeVisible();
        await page.reload({ waitUntil: 'networkidle' });
        expect(await page.getByTestId('focus-progress-bar').count()).toBe(0);
        await proof.checkpoint('history-stable');
        await page.waitForTimeout(PROOF.tutorial.minimumHoldMs);
        await proof.attach();
    });
});
