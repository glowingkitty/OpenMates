/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Plans V1 web flow coverage.
 *
 * Verifies the deployed web app can create encrypted durable plans from the
 * central Plans workspace, display plan board cards, and archive with explicit
 * confirmation plus undo.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const PROOF_RECORDING_DIR = 'test-results/proof-video-source/plans-flow';
const PROOF_VIEWPORTS = [
	{ name: 'web-laptop', width: 1440, height: 900 },
	{ name: 'web-phone', width: 390, height: 844 }
];
const PROOF_READY_TRIM_LEAD_SECONDS = 0.15;

function proofVideoPath(testInfo: any, viewport: { name: string }): string {
	return path.resolve(PROOF_RECORDING_DIR, `${viewport.name}-${String(testInfo.title).replace(/[^A-Za-z0-9._-]+/g, '-')}.webm`);
}

function trimProofVideoToReadyMarker(rawPath: string, outputPath: string, readyTimestampMs: number): void {
	const trimStartSeconds = Math.max(0, readyTimestampMs / 1000 - PROOF_READY_TRIM_LEAD_SECONDS);
	const result = spawnSync('ffmpeg', [
		'-y', '-ss', trimStartSeconds.toFixed(3), '-i', rawPath,
		'-map', '0:v:0', '-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '4', '-b:v', '0', '-crf', '32', '-an', outputPath
	], { encoding: 'utf8' });
	if (result.error || result.status !== 0 || !fs.existsSync(outputPath)) {
		throw new Error(`Proof video trim failed: ${String(result.error?.message || result.stderr || result.stdout).slice(-1000)}`);
	}
	fs.rmSync(rawPath, { force: true });
}

async function runWithProofPage(
	browser: any,
	baseURL: string,
	testInfo: any,
	viewport: { name: string; width: number; height: number },
	callback: (page: any, markReady: () => void) => Promise<void>
): Promise<void> {
	fs.mkdirSync(PROOF_RECORDING_DIR, { recursive: true });
	const outputPath = proofVideoPath(testInfo, viewport);
	const rawOutputPath = `${outputPath}.raw.webm`;
	fs.rmSync(outputPath, { force: true });
	fs.rmSync(rawOutputPath, { force: true });
	const context = await browser.newContext({
		baseURL,
		recordVideo: { dir: PROOF_RECORDING_DIR, size: { width: viewport.width, height: viewport.height } },
		viewport: { width: viewport.width, height: viewport.height }
	});
	const page = await context.newPage();
	const video = page.video();
	const recordingStartedAt = Date.now();
	let readyTimestampMs: number | null = null;
	let thrown: unknown;
	try {
		await callback(page, () => {
			if (readyTimestampMs === null) readyTimestampMs = Date.now() - recordingStartedAt;
		});
	} catch (error) {
		thrown = error;
	} finally {
		await page.waitForTimeout(500).catch(() => undefined);
		await context.close();
	}
	if (!video) throw new Error(`Playwright did not create a proof video for ${viewport.name}`);
	const generatedPath = await video.path();
	await video.saveAs(rawOutputPath);
	if (path.resolve(generatedPath) !== path.resolve(rawOutputPath)) fs.rmSync(generatedPath, { force: true });
	if (readyTimestampMs === null && !thrown) throw new Error(`Proof video for ${viewport.name} did not record a ready marker`);
	if (readyTimestampMs !== null && !thrown) trimProofVideoToReadyMarker(rawOutputPath, outputPath, readyTimestampMs);
	else fs.renameSync(rawOutputPath, outputPath);
	await testInfo.attach(`${viewport.name}-proof-video`, { path: outputPath, contentType: 'video/webm' });
	if (thrown) throw thrown;
}

async function runPlanLifecycle(page: any, markReady?: () => void): Promise<void> {
	const planTitle = `E2E plan ${Date.now()}`;
	const renamedPlanTitle = `${planTitle} renamed`;
	let createRequestPayload = '';

	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await loginToTestAccount(page);
	await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('plans-page')).toBeVisible({ timeout: 30000 });
	await expect(page.getByTestId('plans-workspace-home')).toBeVisible({ timeout: 30000 });
	await expect(page.getByTestId('plan-greeting')).toContainText(/what is your next plan\?/i, { timeout: 15000 });
	await expect(page.getByTestId('plans-loading')).toHaveCount(0, { timeout: 30000 });
	await expect(page.getByTestId('plan-board')).toBeVisible({ timeout: 30000 });
	await expect(page.getByTestId('task-create-form')).toHaveCount(0);
	await page.waitForTimeout(800);
	markReady?.();
	if (markReady) await page.waitForTimeout(1200);

	const createResponse = page.waitForResponse((response: any) => {
		if (!response.url().includes('/v1/user-plans') || response.request().method() !== 'POST') return false;
		createRequestPayload = response.request().postData() ?? '';
		return response.ok();
	});
	await page.getByTestId('plan-workspace-input').fill(planTitle);
	await page.getByTestId('plan-workspace-submit').click();
	await createResponse;
	expect(createRequestPayload).not.toContain(planTitle);

	const planCard = page.getByTestId('plan-card').filter({ hasText: planTitle }).first();
	await expect(planCard).toBeVisible({ timeout: 30000 });
	await expect(planCard).toHaveAttribute('data-plan-status', 'draft');
	await expect(page.getByTestId('plan-column-backlog')).toContainText(planTitle);

	await page.getByTestId('plan-workspace-input').fill(`rename ${planTitle} to ${renamedPlanTitle}`);
	await Promise.all([
		page.waitForResponse((response: any) => response.request().method() === 'PATCH' && response.url().includes('/v1/user-plans/') && response.ok()),
		page.getByTestId('plan-workspace-submit').click()
	]);
	const renamedCard = page.getByTestId('plan-card').filter({ hasText: renamedPlanTitle }).first();
	await expect(renamedCard).toBeVisible({ timeout: 30000 });

	await page.getByTestId('plan-workspace-input').fill(`delete ${renamedPlanTitle}`);
	await page.getByTestId('plan-workspace-submit').click();
	await expect(page.getByTestId('plan-archive-confirmation')).toBeVisible({ timeout: 15000 });
	if (markReady) await page.waitForTimeout(1200);
	await Promise.all([
		page.waitForResponse((response: any) => response.request().method() === 'PATCH' && response.url().includes('/v1/user-plans/') && response.ok()),
		page.getByTestId('plan-archive-confirm').click()
	]);
	await expect(page.getByTestId('plan-board')).not.toContainText(renamedPlanTitle, { timeout: 30000 });
	await expect(page.getByTestId('plan-archive-undo')).toBeVisible({ timeout: 15000 });
}

test.describe('Plans V1 flow', () => {
	// contract-test: direct surface=gui.web assertions=plans.lifecycle.visible,plans.content.client-encrypted,plans.surface.semantic-parity
	test('creates and archives an encrypted plan from the Plans workspace', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);
		await runPlanLifecycle(page);
	});

	for (const viewport of PROOF_VIEWPORTS) {
		// contract-test: direct surface=gui.web assertions=plans.lifecycle.visible,plans.content.client-encrypted,plans.surface.semantic-parity
		test(`records ${viewport.name} Plan lifecycle proof`, async ({ browser, baseURL }: { browser: any; baseURL: string }, testInfo: any) => {
			test.setTimeout(180000);
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await runWithProofPage(browser, baseURL, testInfo, viewport, async (page, markReady) => {
				await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);
				await runPlanLifecycle(page, markReady);
			});
		});
	}
});
