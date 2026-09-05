/**
 * Focused deployed contract for ChatProcessingIndicator.
 * It covers selection before identity and selected-mate rendering without
 * requiring an account or a full chat flow.
 * The preview callback is asserted as supporting behavior, not visual proof.
 */
import { expect, test } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const PREVIEW_WIDTH = PROOF_DEVICE === 'web-phone' ? '390' : '420';

const CHAT_PROCESSING_INDICATOR_PROOF = defineVideoProof({
    id: 'chat-processing-indicator-selected-mate',
    title: 'Chat processing selected mate',
    surface: 'web',
    devices: ['web-laptop', 'web-phone'],
    domain: 'app.dev.openmates.org',
    transcript: [
        {
            id: 'selection-text-only',
            text: 'The initial selection status is text-only and does not guess a mate identity.',
            checkpoint: 'selection-text-only',
            devices: ['web-laptop', 'web-phone'],
        },
        {
            id: 'selected-mate-visible',
            text: 'George is shown as the selected mate while processing continues.',
            checkpoint: 'selected-mate-visible',
            devices: ['web-laptop', 'web-phone'],
        },
        {
            id: 'selected-mate-accessible',
            text: 'George remains visible as a focused, keyboard-accessible selected mate action.',
            checkpoint: 'selected-mate-accessible',
            devices: ['web-laptop', 'web-phone'],
        },
    ],
    assertions: [
        {
            id: 'chat-processing-feedback.selection-after-acceptance',
            checkpoint: 'selection-text-only',
            visual: 'The status has one text-only selection line with no portrait, badge, or mate-name action.',
            devices: ['web-laptop', 'web-phone'],
        },
        {
            id: 'chat-processing-feedback.selected-mate-identity',
            checkpoint: 'selected-mate-visible',
            visual: 'The selected mate has a small circular portrait with an AI badge and an accessible George control.',
            devices: ['web-laptop', 'web-phone'],
        },
        {
            id: 'chat-processing-feedback.accessible-responsive',
            checkpoint: 'selected-mate-accessible',
            visual: 'The portrait and bottom-right AI badge fit within the indicator while the selected-mate action is visibly focused.',
            devices: ['web-laptop', 'web-phone'],
        },
    ],
    tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

test.describe('ChatProcessingIndicator component preview', () => {
    // contract-test: direct surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance,chat-processing-feedback.selected-mate-identity,chat-processing-feedback.accessible-responsive
    test('progresses from text-only selection to an accessible selected mate', async ({ page }, testInfo) => {
        const proof = createVideoProofRuntime(CHAT_PROCESSING_INDICATOR_PROOF, {
            device: PROOF_DEVICE,
            attach: testInfo.attach.bind(testInfo),
        });
        const selectingParams = new URLSearchParams({
            variant: 'selecting',
            theme: 'light',
            background: '#dbeafe',
            width: PREVIEW_WIDTH,
            chrome: '0',
        });

        await page.goto(`/dev/preview/ChatProcessingIndicator?${selectingParams}`, { waitUntil: 'networkidle' });

        const indicator = page.getByTestId('chat-processing-indicator');
        await proof.assert('chat-processing-feedback.selection-after-acceptance', async () => {
            await expect(indicator).toHaveText('Selecting mate & AI model...');
            await expect(indicator.getByTestId('chat-processing-mate-avatar')).toHaveCount(0);
            await expect(indicator.getByTestId('chat-processing-mate-name')).toHaveCount(0);
        });
        await proof.checkpoint('selection-text-only');
        // Preserve actual recorded frames for this state before navigating away.
        await page.waitForTimeout(CHAT_PROCESSING_INDICATOR_PROOF.tutorial.minimumHoldMs);

        const selectedMateParams = new URLSearchParams({
            theme: 'light',
            background: '#dbeafe',
            width: PREVIEW_WIDTH,
            chrome: '0',
        });
        await proof.action('show-selected-mate', async () => {
            await page.goto(`/dev/preview/ChatProcessingIndicator?${selectedMateParams}`, { waitUntil: 'networkidle' });
        });
        await page.evaluate(() => {
            window.addEventListener('openmates-preview-mate-click', (event) => {
                const detail = (event as CustomEvent<{ mateCategory: string }>).detail;
                (window as Window & { __chatProcessingMateClicks?: string[] }).__chatProcessingMateClicks ??= [];
                (window as Window & { __chatProcessingMateClicks: string[] }).__chatProcessingMateClicks.push(detail.mateCategory);
            });
        });

        await expect(indicator).toHaveText('George is thinking...');
        await expect(indicator).toHaveClass(/status-typing/);

        await proof.assert('chat-processing-feedback.selected-mate-identity', async () => {
            const avatar = indicator.getByTestId('chat-processing-mate-avatar');
            const mateName = indicator.getByTestId('chat-processing-mate-name');
            await expect(avatar).toBeVisible();
            await expect(avatar).toHaveAttribute('data-mate-category', 'general_knowledge');
            await expect(avatar.getByTestId('chat-processing-ai-badge')).toBeVisible();
            await expect(mateName).toHaveAccessibleName('George');
            await expect(mateName).toHaveText('George');
        });
        await proof.checkpoint('selected-mate-visible');
        await page.waitForTimeout(CHAT_PROCESSING_INDICATOR_PROOF.tutorial.minimumHoldMs);

        const mateName = indicator.getByTestId('chat-processing-mate-name');
        await proof.action('focus-selected-mate', async () => {
            await mateName.hover();
            await mateName.focus();
        });
        await expect(mateName).toBeFocused();
        await proof.assert('chat-processing-feedback.accessible-responsive', async () => {
            const [indicatorBox, avatarBox, badgeBox] = await Promise.all([
                indicator.boundingBox(),
                page.getByTestId('chat-processing-mate-avatar').boundingBox(),
                page.getByTestId('chat-processing-ai-badge').boundingBox(),
            ]);
            expect(indicatorBox).not.toBeNull();
            expect(avatarBox).not.toBeNull();
            expect(badgeBox).not.toBeNull();
            await expect(page.getByTestId('chat-processing-mate-avatar')).toHaveCSS('border-radius', '50%');
            expect(Math.abs(avatarBox!.width - avatarBox!.height)).toBeLessThanOrEqual(1);
            expect(badgeBox!.x + badgeBox!.width / 2).toBeGreaterThan(avatarBox!.x + avatarBox!.width * 0.7);
            expect(badgeBox!.y + badgeBox!.height / 2).toBeGreaterThan(avatarBox!.y + avatarBox!.height * 0.7);
            expect(badgeBox!.x + badgeBox!.width).toBeLessThanOrEqual(indicatorBox!.x + indicatorBox!.width);
            expect(badgeBox!.y + badgeBox!.height).toBeLessThanOrEqual(indicatorBox!.y + indicatorBox!.height);
            await expect(indicator).toBeVisible();
        });
        await proof.checkpoint('selected-mate-accessible');
        await page.waitForTimeout(CHAT_PROCESSING_INDICATOR_PROOF.tutorial.minimumHoldMs);

        await mateName.press('Enter');
        await expect.poll(() => page.evaluate(() =>
            (window as Window & { __chatProcessingMateClicks?: string[] }).__chatProcessingMateClicks ?? []
        )).toEqual(['general_knowledge']);
        await proof.attach();
    });
});
