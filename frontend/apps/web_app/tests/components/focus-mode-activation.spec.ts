/**
 * Isolated focus activation history regression and component proof.
 * Historical records never create a countdown or mutation callbacks.
 * A current active record can expose its normal details interaction.
 * Live pending cancellation is covered separately by the authenticated flow.
 * The fixture inputs are encoded in the bare preview URL for repeatability.
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
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
    // contract-test: direct surface=gui.web assertions=projects.focus.inferred-consent
    test('Project access uses the standard cancellable four-second countdown', async ({ page }) => {
        const query = new URLSearchParams({ chrome: '0', variant: 'projectConsent' });
        await page.goto(`/dev/preview/embeds/focus_mode/FocusModeActivationEmbed?${query}`);
        await waitForComponentPreview(page);
        await expect(page.getByTestId('focus-progress-bar')).toBeVisible();
        await expect(page.getByTestId('focus-reject-hint')).toBeVisible();
        await expect(page.getByTestId('project-focus-grant')).toHaveCount(0);
        await page.screenshot({ path: test.info().outputPath('project-focus-pending.png') });
        await expect(page.getByTestId('focus-status-value')).toHaveText('Focus activated');
        await expect(page.getByTestId('focus-progress-bar')).toHaveCount(0);
        await page.screenshot({ path: test.info().outputPath('project-focus-consent.png') });
    });
    // contract-test: direct surface=gui.web assertions=projects.focus.inferred-consent,focus-modes.countdown
    test('Project countdown is interrupted with Escape', async ({ page }) => {
        await page.goto('/dev/preview/embeds/focus_mode/FocusModeActivationEmbed?chrome=0&variant=projectConsent');
        await waitForComponentPreview(page);
        await expect(page.getByTestId('focus-progress-bar')).toBeVisible();
        await page.keyboard.press('Escape');
        await expect(page.getByTestId('focus-mode-bar')).toHaveCount(0);
        await page.waitForTimeout(4_100);
        await expect(page.getByTestId('focus-mode-bar')).toHaveCount(0);
    });
    // contract-test: direct surface=gui.web assertions=projects.focus.inferred-consent
    test('Project approval waits for a Grant access click', async ({ page }) => {
        await page.goto('/dev/preview/embeds/focus_mode/FocusModeActivationEmbed?chrome=0&variant=projectApproval');
        await waitForComponentPreview(page);
        await expect(page.getByTestId('focus-status-value')).toHaveText('Waiting for your permission');
        await expect(page.getByTestId('focus-progress-bar')).toHaveCount(0);
        await page.waitForTimeout(4_100);
        await expect(page.getByTestId('focus-status-value')).toHaveText('Waiting for your permission');
        await page.getByTestId('project-focus-grant-access').click();
        await expect(page.getByTestId('focus-status-value')).toHaveText('Focus activated');
    });
    // contract-test: direct surface=gui.web assertions=projects.focus.inferred-consent,focus-modes.history-side-effects
    test('historical Project request does not expose a grant action', async ({ page }) => {
        const query = new URLSearchParams({ chrome: '0', props: JSON.stringify({
            focusId: 'project-11111111-1111-4111-8111-111111111111', appId: 'projects',
            focusModeName: 'Work on Garden notes', alreadyActive: false,
        }) });
        await page.goto(`/dev/preview/embeds/focus_mode/FocusModeActivationEmbed?${query}`);
        await waitForComponentPreview(page);
        await expect(page.getByTestId('focus-mode-bar')).toBeVisible();
        await expect(page.getByTestId('project-focus-consent')).toHaveCount(0);
        await expect(page.getByTestId('focus-progress-bar')).toHaveCount(0);
    });
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
    // contract-test: direct surface=gui.web assertions=focus-modes.countdown
    test('explicit live pending activation remains cancellable', async ({ page }) => {
        const query = new URLSearchParams({ chrome: '0', props: JSON.stringify({
            id: 'live-focus-record', alreadyActive: false, pendingUntil: Date.now() + 4000,
        }) });
        await page.goto(`/dev/preview/embeds/focus_mode/FocusModeActivationEmbed?${query}`);
        await waitForComponentPreview(page);
        await expect(page.getByTestId('focus-progress-bar')).toBeVisible();
        await page.getByTestId('focus-mode-bar').click();
        await expect(page.getByTestId('focus-mode-bar')).toHaveCount(0);
    });
});
