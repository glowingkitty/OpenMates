/**
 * Component proof for live, sandboxed HTML visuals in code embeds.
 * The fixture animates a canvas and probes cookies, storage, the parent page,
 * the network and navigation; every probe must stay inside the sandbox.
 */
import { expect, test } from '../helpers/cookie-audit';
import type { FrameLocator, Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports -- video-proof helper is CommonJS, as in the other component proofs
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const devices = ['web-laptop'];
const device = 'web-laptop';
const tutorial = { readingWordsPerSecond: 3, minimumHoldMs: 1200, maximumHoldMs: 3000 };
const cardProof = defineVideoProof({
	id: 'interactive-html-visual-card', title: 'Live HTML visual in a chat card', surface: 'web', devices, domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'card', text: 'An HTML code embed shows its animation directly in the chat card.', checkpoint: 'card', devices },
		{ id: 'contained', text: 'The page cannot read cookies, storage or the app, and cannot reach the network.', checkpoint: 'contained', devices },
	],
	assertions: [
		{ id: 'card-live', checkpoint: 'card', visual: 'The card shows the moving orbit instead of HTML source.', devices },
		{ id: 'card-contained', checkpoint: 'contained', visual: 'Cookie, storage, parent and fetch probes all read blocked; the scripted navigation sends no request.', devices },
	],
	tutorial,
});
const fullscreenProof = defineVideoProof({
	id: 'interactive-html-visual-fullscreen', title: 'Live HTML visual in fullscreen with code switch', surface: 'web', devices, domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'fullscreen', text: 'Fullscreen opens on the interactive visual.', checkpoint: 'fullscreen', devices },
		{ id: 'code', text: 'One button switches to the source code and back.', checkpoint: 'code', devices },
	],
	assertions: [
		{ id: 'fullscreen-visual', checkpoint: 'fullscreen', visual: 'Fullscreen shows only the live visual with a View code button.', devices },
		{ id: 'code-switch', checkpoint: 'code', visual: 'View code shows the source; View visual brings the animation back.', devices },
	],
	tutorial,
});

const PREVIEW = '/dev/preview/embeds/code/CodeEmbedPreview?variant=interactiveHtml&theme=light&width=420&chrome=0';
const FULLSCREEN = '/dev/preview/embeds/code/CodeEmbedFullscreen?variant=interactiveHtml&theme=light&width=1280&chrome=0';

function recordLeaks(page: Page): string[] {
	const leaks: string[] = [];
	page.on('request', (request) => {
		if (request.url().includes('example.com')) leaks.push(request.url());
	});
	return leaks;
}

function visual(page: Page): FrameLocator {
	// The author document is nested inside a script-free wrapper document.
	return page.frameLocator('[data-testid="interactive-html-iframe"]').frameLocator('iframe');
}

async function readTicks(page: Page): Promise<number> {
	return Number(await visual(page).getByTestId('probe-ticks').textContent());
}

// contract-test: direct surface=gui.web assertions=interactive-html.render.live-preview-and-code-switch,interactive-html.security.isolated-and-offline
test('chat card renders the HTML visual live, inert and contained', async ({ page }, testInfo) => {
	const proof = createVideoProofRuntime(cardProof, { device, attach: testInfo.attach.bind(testInfo) });
	const leaks = recordLeaks(page);
	await page.goto(PREVIEW);
	await waitForComponentPreview(page);

	await proof.assert('card-live', async () => {
		const frameHost = page.getByTestId('interactive-html-frame');
		await expect(frameHost).toBeVisible({ timeout: 30_000 });
		await expect(frameHost).toHaveCSS('pointer-events', 'none');
		await expect(page.getByTestId('interactive-html-iframe')).toHaveAttribute('sandbox', 'allow-scripts');
		await expect(visual(page).getByTestId('visual-title')).toHaveText('Orbit demo');
		await expect.poll(() => readTicks(page)).toBeGreaterThan(10);
	});
	await proof.checkpoint('card');

	await proof.assert('card-contained', async () => {
		for (const probe of ['cookie', 'storage', 'parent', 'fetch']) {
			await expect(visual(page).getByTestId(`probe-${probe}`)).toHaveText('blocked');
		}
		// The fixture sets location.href at 800ms; the wrapper's frame-src blocks it before any request.
		await page.waitForTimeout(1500);
		await expect(page.getByTestId('interactive-html-iframe')).toBeVisible();
		expect(page.url()).toContain('/dev/preview/embeds/code/CodeEmbedPreview');
		expect(leaks).toEqual([]);
	});
	await proof.checkpoint('contained');
	await proof.attach();
});

// contract-test: direct surface=gui.web assertions=interactive-html.render.live-preview-and-code-switch,interactive-html.security.isolated-and-offline
test('fullscreen opens on the interactive visual and switches to code and back', async ({ page }, testInfo) => {
	const proof = createVideoProofRuntime(fullscreenProof, { device, attach: testInfo.attach.bind(testInfo) });
	const leaks = recordLeaks(page);
	await page.goto(FULLSCREEN);
	await waitForComponentPreview(page);
	const toggle = page.getByTestId('embed-preview-button');

	await proof.assert('fullscreen-visual', async () => {
		await expect(page.getByTestId('interactive-html-iframe')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('interactive-html-frame')).toHaveCSS('pointer-events', 'auto');
		await expect(page.getByTestId('code-source-panel')).toBeHidden();
		await expect.poll(() => readTicks(page)).toBeGreaterThan(10);
		await expect(toggle).toHaveText(/View code/);
	});
	await proof.checkpoint('fullscreen');

	await proof.assert('code-switch', async () => {
		await toggle.click();
		await expect(page.getByTestId('code-fullscreen-code')).toBeVisible();
		await expect(page.getByTestId('code-fullscreen-code')).toContainText('requestAnimationFrame');
		await expect(page.getByTestId('interactive-html-iframe')).toHaveCount(0);
		await expect(toggle).toHaveText(/View visual/);
		await toggle.click();
		await expect(page.getByTestId('interactive-html-iframe')).toBeVisible();
		await expect(page.getByTestId('code-source-panel')).toBeHidden();
		// A click on an external link is ignored and the visual keeps running.
		await visual(page).getByTestId('external-link').click();
		await page.waitForTimeout(500);
		await expect(visual(page).getByTestId('visual-title')).toHaveText('Orbit demo');
		// A scripted navigation is blocked by the browser before any request.
		await visual(page).getByTestId('navigate-button').click();
		await page.waitForTimeout(1500);
		expect(page.url()).toContain('/dev/preview/embeds/code/CodeEmbedFullscreen');
		expect(leaks).toEqual([]);
	});
	await proof.checkpoint('code');
	await proof.attach();
});

const SVG_PREVIEW = '/dev/preview/embeds/code/CodeEmbedPreview?variant=svg&theme=light&width=420&chrome=0';
const SVG_STREAMING_PREVIEW = '/dev/preview/embeds/code/CodeEmbedPreview?variant=svgStreaming&theme=light&width=420&chrome=0';

// contract-test: direct surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
test('SVG code embed renders as an image, also from partial streaming source', async ({ page }) => {
	await page.goto(SVG_PREVIEW);
	await waitForComponentPreview(page);
	const image = page.getByTestId('svg-embed-image');
	await expect(image).toBeVisible({ timeout: 30_000 });
	await expect(image).toHaveAttribute('src', /^data:image\/svg\+xml/);
	await expect(page.getByTestId('svg-embed-visual')).toHaveAttribute('data-streaming', 'false');

	await page.goto(SVG_STREAMING_PREVIEW);
	await waitForComponentPreview(page);
	await expect(page.getByTestId('svg-embed-visual')).toHaveAttribute('data-streaming', 'true');
	await expect(page.getByTestId('svg-embed-image')).toBeVisible({ timeout: 30_000 });
});
