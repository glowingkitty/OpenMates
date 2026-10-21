import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// This focused fixture exercises the production service/component with mocked
// transport. application-preview.spec.ts separately proves authenticated WS/E2B.
for (const responseMode of ['queued', 'reject-poll', 'reject-open'] as const) {
// contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot,code-run.execution.stream-status-visible
test(`fullscreen adopts a late preview once before screenshot (${responseMode})`, async ({ page }, testInfo) => {
	await page.setViewportSize({ width: 1280, height: 900 });
	let serviceUrl = '';
	page.on('request', (request) => {
		if (request.url().includes('/src/services/applicationPreviewService.ts')) serviceUrl = request.url();
	});
	let releaseStart!: () => void;
	const startGate = new Promise<void>((resolve) => { releaseStart = resolve; });
	let releaseObsolete!: () => void;
	const obsoleteGate = new Promise<void>((resolve) => { releaseObsolete = resolve; });
	let obsoleteRequestHeld = false;
	let starts = 0;
	let opens = 0;
	let statusReads = 0;
	let stopped = false;
	const sessionId = 'component-preview-session';
	const chatId = 'preview-chat-1';
	const embedId = 'preview-application-1';
	const cors = {
		'access-control-allow-origin': 'http://localhost:5173',
		'access-control-allow-credentials': 'true',
		'access-control-allow-methods': 'GET, POST, OPTIONS',
		'access-control-allow-headers': 'content-type'
	};
	await page.route('**/v1/applications/**', async (route) => {
		const request = route.request();
		const headers = { ...cors, 'access-control-allow-origin': request.headers().origin || cors['access-control-allow-origin'] };
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers });
			return;
		}
		if (request.url().endsWith('/preview/start')) {
			starts += 1;
			await startGate;
			await route.fulfill({ headers, json: {
				session_id: sessionId, preview_url: 'https://application-preview.fixture.test/t/component',
				status: 'queued', credits_per_minute: 1
			} });
			return;
		}
		if (request.url().endsWith('/open')) opens += 1;
		else if (request.url().endsWith('/stop')) stopped = true;
		else statusReads += 1;
		const rejectThisRequest = !obsoleteRequestHeld && (
			(responseMode === 'reject-open' && request.url().endsWith('/open'))
			|| (responseMode === 'reject-poll' && request.method() === 'GET')
		);
		if (rejectThisRequest) {
			obsoleteRequestHeld = true;
			await obsoleteGate;
			await route.fulfill({ status: 503, headers, json: { detail: 'Obsolete startup request failed' } });
			return;
		}
		await route.fulfill({ headers, json: { session_id: sessionId, status: stopped ? 'stopped' : 'queued' } });
	});
	await page.route('https://application-preview.fixture.test/**', (route) => route.fulfill({
		contentType: 'text/html', body: '<!doctype html><title>Fixture runtime</title><p>Runtime ready before screenshot</p>'
	}));
	await page.goto('/dev/preview/embeds/code/ApplicationEmbedFullscreen?theme=light&background=%23dbeafe&width=1280&chrome=0');
	const canvas = await waitForComponentPreview(page);
	const panel = page.getByTestId('application-preview-panel');
	const start = page.getByTestId('application-start-preview');
	const status = page.getByTestId('application-preview-status').locator('[data-status]');
	await expect(panel).toBeVisible();
	await expect(page.getByTestId('embed-header-title')).toHaveText('Recipe Manager');
	await expect(page.locator('.header-skill-icon[data-skill-icon="coding"]')).toBeVisible();
	await expect(status).toHaveAttribute('data-status', 'idle');
	await expect(start).toBeEnabled();
	await start.hover();
	await start.focus();
	await expect(start).toBeFocused();
	await expect(page.getByTestId('application-preview-files')).toContainText('src/App.svelte');
	await expect(page.getByTestId('application-preview-logs')).toBeVisible();
	expect(serviceUrl, 'must share the mounted component production service module').not.toBe('');
	await page.evaluate(async ({ serviceUrl, chatId, embedId }) => {
		const service = await import(/* @vite-ignore */ serviceUrl);
		// Both initiators share the same paid POST while fullscreen is mounted.
		void service.startApplicationPreview(chatId, embedId, { autoStarted: true });
		void service.startApplicationPreview(chatId, embedId);
	}, { serviceUrl, chatId, embedId });
	await expect.poll(() => starts).toBe(1);
	await expect(page.getByTestId('application-preview-iframe')).toHaveCount(0);
	releaseStart();
	await expect(status).toHaveAttribute('data-status', 'queued');
	await expect(start).toBeDisabled();
	await expect.poll(() => opens).toBe(1);
	if (responseMode !== 'reject-open') {
		await expect.poll(() => statusReads, { timeout: 10_000 }).toBeGreaterThan(0);
	}
	await testInfo.attach('application-preview-loading', { body: await canvas.screenshot(), contentType: 'image/png' });

	await page.evaluate(async ({ serviceUrl, chatId, embedId, sessionId }) => {
		const service = await import(/* @vite-ignore */ serviceUrl);
		const update = { chat_id: chatId, application_embed_id: embedId, session_id: sessionId, status: 'running', updated_at: 20 };
		service.handleApplicationPreviewStatusUpdate({ ...update, session_id: 'different-session' });
	}, { serviceUrl, chatId, embedId, sessionId });
	await expect(status).toHaveAttribute('data-status', 'queued');
	const readsBeforePush = statusReads;
	await page.evaluate(async ({ serviceUrl, chatId, embedId, sessionId }) => {
		const service = await import(/* @vite-ignore */ serviceUrl);
		service.handleApplicationPreviewStatusUpdate({ chat_id: chatId, application_embed_id: embedId,
			session_id: sessionId, status: 'running', updated_at: 30 });
	}, { serviceUrl, chatId, embedId, sessionId });
	const iframe = page.getByTestId('application-preview-iframe');
	await expect(iframe).toBeVisible();
	await expect.poll(() => statusReads).toBeGreaterThan(readsBeforePush);
	if (responseMode !== 'queued') {
		expect(obsoleteRequestHeld).toBe(true);
		const rejectedResponse = page.waitForResponse((response) => response.status() === 503
			&& response.url().includes('/v1/applications/preview/'));
		releaseObsolete();
		await (await rejectedResponse).finished();
		// Let the rejected fetch and its component catch settle before asserting.
		await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
	}
	await expect(status).toHaveAttribute('data-status', 'running');
	await expect(iframe.contentFrame().getByText('Runtime ready before screenshot')).toBeVisible();
	await expect(page.getByTestId('application-fullscreen-screenshot')).toHaveCount(0);
	const open = page.getByTestId('application-open-preview-window');
	await expect(open).toBeEnabled();
	await open.hover();
	await open.focus();
	await expect(open).toBeFocused();
	const panelBox = await panel.boundingBox();
	const frameBox = await iframe.boundingBox();
	expect(panelBox).not.toBeNull();
	expect(frameBox).not.toBeNull();
	expect(frameBox!.width).toBeGreaterThan(300);
	expect(frameBox!.x + frameBox!.width).toBeLessThanOrEqual(panelBox!.x + panelBox!.width + 1);
	await testInfo.attach('application-preview-ready-before-screenshot', { body: await canvas.screenshot(), contentType: 'image/png' });
	expect(starts, 'cache adoption and readiness must not start a second paid preview').toBe(1);
	expect(opens, 'auto-start opening must preserve exactly one lifetime transition').toBe(1);
	await page.getByTestId('application-stop-preview').click();
	await expect(status).toHaveAttribute('data-status', 'stopped');
	await expect(iframe).toHaveCount(0);
	await expect(start).toBeEnabled();
	await testInfo.attach('application-preview-stopped', { body: await canvas.screenshot(), contentType: 'image/png' });
});

}
