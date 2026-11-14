// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

const PREVIEW = '/dev/preview/embeds/code/TestResultEmbedPreview';
const FULLSCREEN = '/dev/preview/embeds/code/TestResultEmbedFullscreen';

async function open(page: Page, path: string, variant?: string, width = '900') {
	const query = new URLSearchParams({ theme: 'light', width, chrome: '0' });
	if (variant) query.set('variant', variant);
	await page.goto(`${path}?${query}`, { waitUntil: 'domcontentloaded' });
	await waitForComponentPreview(page);
}

test.describe('test result preview card', () => {
	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('browser run shows the preview frame image with status and counts', async ({ page }, testInfo) => {
		await open(page, PREVIEW);
		const frame = page.getByTestId('test-result-preview-frame');
		await expect(frame).toBeVisible({ timeout: 30_000 });
		await expect
			.poll(() => frame.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0))
			.toBe(true);
		await expect(page.getByTestId('test-result-preview-status')).toHaveAttribute('data-status', 'passed');
		await expect(page.getByTestId('test-result-preview-counts')).toContainText('4');
		await expect(page.getByTestId('test-result-preview-stale')).toHaveCount(0);
		// The title names the test; the execution target ("e2b") is never the title.
		await expect(page.getByTestId('test-result-preview-title')).toHaveText('Signing in opens the dashboard');
		// The compact card keeps its 24px text inset (the arrow clearance is for wide cards only).
		const compact = await page.getByTestId('test-result-preview').boundingBox();
		const compactTitle = await page.getByTestId('test-result-preview-title').boundingBox();
		expect(compact && compactTitle && compactTitle.x - compact.x <= 30, 'compact card keeps its text width').toBe(true);
		await testInfo.attach('test-result-preview-card', {
			body: await page.getByTestId('test-result-preview').screenshot(),
			contentType: 'image/png'
		});
		// Grouped results render the card wide with carousel arrows 10px from its
		// bottom corners (36px): title and counts start clear of them.
		await page.addStyleTag({ content: '[data-testid="embed-preview"] { width: 900px !important; height: 520px !important; max-width: none !important; }' });
		const card = await page.getByTestId('test-result-preview').boundingBox();
		expect(card && card.width > 800, 'wide card rendered').toBe(true);
		for (const id of ['test-result-preview-title', 'test-result-preview-counts']) {
			const text = await page.getByTestId(id).boundingBox();
			expect(card && text && text.x - card.x >= 46 && card.x + card.width - (text.x + text.width) >= 46, `${id} clears the carousel arrows`).toBe(true);
		}
		await testInfo.attach('test-result-preview-card-wide', {
			body: await page.getByTestId('test-result-preview').screenshot(),
			contentType: 'image/png'
		});
	});

	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('browser run without a frame shows a status-styled placeholder, not a blank frame', async ({ page }) => {
		await open(page, PREVIEW, 'browserNoFrame');
		const placeholder = page.getByTestId('test-result-preview-placeholder');
		await expect(placeholder).toBeVisible();
		await expect(placeholder).toContainText(/passed/i);
		const background = await placeholder.evaluate((el) => getComputedStyle(el).backgroundColor);
		expect(background).not.toBe('rgb(255, 255, 255)');
		await expect(page.getByTestId('test-result-preview-frame')).toHaveCount(0);
	});

	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('failed browser run placeholder or frame reports failed status', async ({ page }) => {
		await open(page, PREVIEW, 'browserFailed');
		await expect(page.getByTestId('test-result-preview-status')).toHaveAttribute('data-status', 'failed');
		await expect(page.getByTestId('test-result-preview-counts')).toContainText('1');
	});

	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('cli and unit runs render a compact status card without a frame area', async ({ page }) => {
		for (const variant of ['cli', 'unit']) {
			await open(page, PREVIEW, variant);
			await expect(page.getByTestId('test-result-preview')).toHaveAttribute('data-kind', variant);
			await expect(page.getByTestId('test-result-preview-status')).toBeVisible();
			await expect(page.getByTestId('test-result-preview-counts')).toBeVisible();
			await expect(page.getByTestId('test-result-preview-frame-area')).toHaveCount(0);
		}
	});

	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('stale run shows a visible stale marker', async ({ page }) => {
		await open(page, PREVIEW, 'stale');
		await expect(page.getByTestId('test-result-preview-stale')).toBeVisible();
	});
});

test.describe('test result fullscreen', () => {
	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('browser kind: video beside a vertical timeline; clicking a step seeks and highlights', async ({ page }) => {
		await open(page, FULLSCREEN, undefined, '1100');
		const video = page.getByTestId('test-result-video');
		await expect(video).toBeVisible({ timeout: 30_000 });
		await expect
			.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 30_000 })
			.toBeGreaterThanOrEqual(1);

		const steps = [0, 1, 2, 3].map((i) => page.getByTestId(`test-result-step-${i}`));
		for (const step of steps) await expect(step).toBeVisible();
		await expect(steps[0]).toContainText('Open sign-in page');
		await expect(steps[0]).toHaveAttribute('data-status', 'passed');
		await expect(steps[3]).toHaveAttribute('data-status', 'passed');

		// Vertical: each step is below the previous one; timeline sits beside the video.
		const boxes = await Promise.all(steps.map((s) => s.boundingBox()));
		for (let i = 1; i < boxes.length; i++) expect(boxes[i]!.y).toBeGreaterThan(boxes[i - 1]!.y);
		const videoBox = await video.boundingBox();
		expect(boxes[0]!.x).toBeGreaterThan(videoBox!.x + videoBox!.width - 1);

		await steps[2].click();
		await expect
			.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 10_000 })
			.toBeCloseTo(4, 0);
		await expect(steps[2]).toHaveAttribute('aria-current', 'step');
		await expect(steps[0]).not.toHaveAttribute('aria-current', 'step');

		await steps[0].click();
		await expect(steps[0]).toHaveAttribute('aria-current', 'step');
	});

	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('browser failed step shows its error and failed status', async ({ page }) => {
		await open(page, FULLSCREEN, 'browserFailed', '1100');
		const last = page.getByTestId('test-result-step-3');
		await expect(last).toHaveAttribute('data-status', 'failed');
		await expect(last).toContainText('Expected element');
	});

	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('cli kind: terminal view with command, output and status per step, no video', async ({ page }) => {
		await open(page, FULLSCREEN, 'cli');
		await expect(page.getByTestId('test-result-terminal')).toBeVisible();
		await expect(page.getByTestId('test-result-video')).toHaveCount(0);
		await expect(page.getByTestId('test-result-term-command-0')).toContainText('cargo build -p openmates-sdk');
		await expect(page.getByTestId('test-result-term-output-0')).toContainText('Compiling openmates-sdk');
		await expect(page.getByTestId('test-result-term-status-0')).toBeVisible();
		await expect(page.getByTestId('test-result-term-step-1')).toHaveAttribute('data-status', 'failed');
		const font = await page.getByTestId('test-result-term-output-1').evaluate((el) => getComputedStyle(el).fontFamily);
		expect(font).toMatch(/mono|Menlo|Consolas/i);
	});

	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('unit kind: counts and per-test list with status and error text', async ({ page }) => {
		await open(page, FULLSCREEN, 'unit');
		await expect(page.getByTestId('test-result-count-passed')).toContainText('2');
		await expect(page.getByTestId('test-result-count-failed')).toContainText('1');
		await expect(page.getByTestId('test-result-count-skipped')).toContainText('1');
		const failing = page.getByTestId('test-result-test-2');
		await expect(failing).toHaveAttribute('data-status', 'failed');
		await expect(failing).toContainText('test_parse_invalid');
		await expect(failing).toContainText('AssertionError');
		await expect(page.getByTestId('test-result-test-0')).toHaveAttribute('data-status', 'passed');
		await expect(page.getByTestId('test-result-video')).toHaveCount(0);
	});

	// contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
	test('stale marker visible only when the result is not current', async ({ page }) => {
		await open(page, FULLSCREEN, 'stale', '1100');
		await expect(page.getByTestId('test-result-stale')).toBeVisible();
		await open(page, FULLSCREEN, undefined, '1100');
		await expect(page.getByTestId('test-result-stale')).toHaveCount(0);
	});
});
