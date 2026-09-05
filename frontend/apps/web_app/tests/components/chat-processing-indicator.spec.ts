/**
 * Focused deployed contract for ChatProcessingIndicator.
 * The preview callback emits a browser event, making navigation observable.
 * Identity assertions remain red until the processing UI adds the approved
 * portrait, AI badge, and accessible mate name control.
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
            id: 'selected-mate-visible',
            text: 'George is shown as the selected mate while processing continues.',
            checkpoint: 'selected-mate-visible',
            devices: ['web-laptop', 'web-phone'],
        },
        {
            id: 'selected-mate-activated',
            text: 'Keyboard activation dispatches the preview callback while George remains visible.',
            checkpoint: 'selected-mate-activated',
            devices: ['web-laptop', 'web-phone'],
        },
    ],
    assertions: [
        {
            id: 'chat-processing-feedback.selected-mate-identity',
            checkpoint: 'selected-mate-visible',
            visual: 'The selected mate has a small circular portrait with an AI badge and an accessible George control.',
            devices: ['web-laptop', 'web-phone'],
        },
        {
            id: 'chat-processing-feedback.accessible-responsive',
            checkpoint: 'selected-mate-activated',
            visual: 'George has a keyboard-focusable name action whose activation dispatches the isolated preview callback without hiding the indicator.',
            devices: ['web-laptop', 'web-phone'],
        },
    ],
    tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

test.describe('ChatProcessingIndicator component preview', () => {
    // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance,chat-processing-feedback.selected-mate-identity,chat-processing-feedback.accessible-responsive
    test('shows the initial text-only selection state without a mate identity', async ({ page }) => {
        const params = new URLSearchParams({
            variant: 'selecting',
            theme: 'light',
            background: '#dbeafe',
            width: PREVIEW_WIDTH,
            chrome: '0',
        });

        await page.goto(`/dev/preview/ChatProcessingIndicator?${params}`, { waitUntil: 'networkidle' });

        const indicator = page.getByTestId('chat-processing-indicator');
        await expect(indicator).toHaveText('Selecting mate & AI model...');
        await expect(indicator.getByTestId('chat-processing-mate-avatar')).toHaveCount(0);
        await expect(indicator.getByTestId('chat-processing-mate-name')).toHaveCount(0);
    });

    // contract-test: direct surface=gui.web assertions=chat-processing-feedback.selected-mate-identity,chat-processing-feedback.accessible-responsive
    test('shows and activates the selected mate while processing', async ({ page }, testInfo) => {
        const proof = createVideoProofRuntime(CHAT_PROCESSING_INDICATOR_PROOF, {
            device: PROOF_DEVICE,
            attach: testInfo.attach.bind(testInfo),
        });
        const params = new URLSearchParams({
            theme: 'light',
            background: '#dbeafe',
            width: PREVIEW_WIDTH,
            chrome: '0',
        });
        await page.goto(`/dev/preview/ChatProcessingIndicator?${params}`, { waitUntil: 'networkidle' });
        await page.evaluate(() => {
            window.addEventListener('openmates-preview-mate-click', (event) => {
                const detail = (event as CustomEvent<{ mateCategory: string }>).detail;
                (window as Window & { __chatProcessingMateClicks?: string[] }).__chatProcessingMateClicks ??= [];
                (window as Window & { __chatProcessingMateClicks: string[] }).__chatProcessingMateClicks.push(detail.mateCategory);
            });
        });

        const indicator = page.getByTestId('chat-processing-indicator');
        await expect(indicator).toHaveText('George is thinking...');
        await expect(indicator).toHaveClass(/status-typing/);

        await proof.assert('chat-processing-feedback.selected-mate-identity', async () => {
            const avatar = indicator.getByTestId('chat-processing-mate-avatar');
            const mateName = indicator.getByTestId('chat-processing-mate-name');
            await expect(avatar).toBeVisible();
            await expect(avatar).toHaveAttribute('data-mate-category', 'general_knowledge');
            await expect(avatar.getByTestId('chat-processing-ai-badge')).toBeVisible();
            await expect(mateName).toHaveAccessibleName('George');
        });
        await proof.checkpoint('selected-mate-visible');

        const mateName = indicator.getByTestId('chat-processing-mate-name');
        await proof.action('hover-selected-mate', async () => mateName.hover());
        await proof.action('focus-selected-mate', async () => mateName.focus());
        await expect(mateName).toBeFocused();
        await proof.action('activate-selected-mate', async () => mateName.press('Enter'));
        await proof.assert('chat-processing-feedback.accessible-responsive', async () => {
            await expect.poll(() => page.evaluate(() =>
                (window as Window & { __chatProcessingMateClicks?: string[] }).__chatProcessingMateClicks ?? []
            )).toEqual(['general_knowledge']);
            await expect(indicator).toBeVisible();
        });
        await proof.checkpoint('selected-mate-activated');
        await proof.attach();
    });
});
