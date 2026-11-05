// playwright-account: not_required reason=isolated_component_preview
/**
 * Report Issue composer: one free-text field with image / element / dictation
 * quick actions. Dictation uses the same realtime transcription socket as the
 * message input and appends the corrected transcript as editable text.
 */
import { expect, test } from '../helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
import { allowFixtureMicrophone } from '../helpers/recording-permission';

const RAW = 'the chat list stays empty after login';
const CORRECTED = 'The chat list stays empty after login.';
const PREVIEW = /\/dev\/preview\/settings\/ReportIssueComposer(?:\?|$)/;

test.use({
	launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
	permissions: ['microphone']
});

async function openComposer(page: Page, variant: string, width = 560): Promise<void> {
	await page.goto(`/dev/preview/settings/ReportIssueComposer?chrome=0&theme=light&width=${width}&variant=${variant}`);
	await waitForComponentPreview(page);
	await expect(page.getByTestId('report-issue-composer')).toBeVisible();
}

const QUOTA_ROUTE = '**/v1/apps/audio/report-issue-dictation-quota';

async function mockDictationQuota(page: Page, remainingSeconds: number): Promise<void> {
	await page.route(QUOTA_ROUTE, route => route.fulfill({ json: {
		available: remainingSeconds > 0,
		remaining_seconds: remainingSeconds,
		daily_limit_seconds: 1800,
		max_recording_seconds: 120,
		resets_in_seconds: 3600
	} }));
}

// contract-test: direct surface=gui.web assertions=issue-reporting.form.single-text-quick-actions
test('signed-in composer shows one text field with compact screenshot, element and record icon buttons', async ({ page }) => {
	await mockDictationQuota(page, 1800);
	await openComposer(page, 'filled');
	const field = page.getByTestId('report-issue-title');
	await expect(field).toHaveValue(/chat list stayed empty/);
	await expect(field).toHaveAttribute('placeholder', /What happened\? Describe what is broken/);
	await expect(page.locator('[data-testid="report-issue-composer"] textarea')).toHaveCount(1);
	const actions = {
		'report-issue-attach-image': 'Upload screenshot',
		'report-issue-pick-element': 'Select UI element',
		'report-issue-dictate': 'Record voice (up to 2 minutes)'
	};
	for (const [testId, label] of Object.entries(actions)) {
		const button = page.getByTestId(testId);
		await expect(button).toBeVisible();
		await expect(button).toBeEnabled();
		await expect(button).toHaveAttribute('aria-label', label);
		// Icon-only: no visible text, compact rounded rectangle.
		await expect(button).toHaveText('');
		const box = await button.boundingBox();
		expect(box?.height ?? 0).toBeLessThanOrEqual(40);
		expect(box?.width ?? 0).toBeLessThanOrEqual(48);
	}
	await expect(page.getByTestId('report-issue-dictate')).not.toHaveAttribute('aria-disabled', 'true');
	await test.info().attach('report-issue-composer-signed-in', {
		body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
		contentType: 'image/png'
	});
});

// contract-test: direct surface=gui.web assertions=issue-reporting.form.free-limited-dictation
test('signed-in record button is greyed out with a try-again-tomorrow tooltip once the daily budget is spent', async ({ page }) => {
	await mockDictationQuota(page, 0);
	await openComposer(page, 'filled');
	const record = page.getByTestId('report-issue-dictate');
	await expect(record).toHaveAttribute('aria-disabled', 'true');
	await expect(record).toHaveAttribute('aria-label', 'Voice recording is unavailable for today. Try again tomorrow.');
	// aria-disabled keeps the tooltip hoverable, so Playwright treats it as not enabled.
	await record.click({ force: true });
	await expect(page.getByTestId('record-overlay')).toHaveCount(0);
	await test.info().attach('report-issue-composer-dictation-unavailable', {
		body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
		contentType: 'image/png'
	});
});

// contract-test: direct surface=gui.web assertions=issue-reporting.form.free-limited-dictation
test('signed-in dictation uses the free report purpose and greys out after the server daily limit', async ({ page }) => {
	const connections: string[] = [];
	await mockDictationQuota(page, 1800);
	await allowFixtureMicrophone(page, PREVIEW);
	await page.addInitScript(() => sessionStorage.setItem('ws_token', 'synthetic-preview-token'));
	await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, socket => {
		connections.push(socket.url());
		socket.send(JSON.stringify({ type: 'session.ready', sample_rate: 16000 }));
		socket.onMessage(raw => {
			if (JSON.parse(String(raw)).type === 'input_audio.append') {
				socket.send(JSON.stringify({ type: 'session.error', code: 'daily_limit',
					message: 'Daily report dictation limit reached. Try again tomorrow.' }));
			}
		});
	});
	await openComposer(page, 'filled');
	await page.getByTestId('report-issue-dictate').click();
	await expect.poll(() => connections.length).toBe(1);
	const url = new URL(connections[0]);
	expect(url.searchParams.get('purpose')).toBe('report_issue');
	expect(url.searchParams.get('anonymous_id')).toBeNull();
	await expect(page.getByTestId('record-overlay')).toHaveCount(0, { timeout: 15000 });
	await expect(page.getByTestId('report-issue-dictate')).toHaveAttribute('aria-disabled', 'true');
});

// contract-test: direct surface=gui.web assertions=issue-reporting.form.single-text-quick-actions
test('guest composer hides image attachment and dictation appends the corrected transcript', async ({ page }) => {
	const connections: string[] = [];
	await allowFixtureMicrophone(page, PREVIEW);
	await page.addInitScript(() => localStorage.setItem('openmates_anonymous_id', 'report-issue-dictation-guest'));
	await page.route('**/v1/anonymous/free-usage/status**', route => route.fulfill({ json: {
		active: true, can_send_text: true, reason: null, daily_remaining_percent: 80
	} }));
	await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, socket => {
		connections.push(socket.url());
		socket.send(JSON.stringify({ type: 'session.ready', sample_rate: 16000 }));
		let deltaSent = false;
		socket.onMessage(raw => {
			const frame = JSON.parse(String(raw));
			if (frame.type === 'input_audio.append' && !deltaSent) {
				deltaSent = true;
				socket.send(JSON.stringify({ type: 'transcription.text.delta', text: RAW }));
			}
			if (frame.type === 'input_audio.end') {
				socket.send(JSON.stringify({ type: 'transcription.done', transcript: RAW, model: 'fixture-transcription' }));
				socket.send(JSON.stringify({ type: 'correction.done', transcript: CORRECTED }));
			}
		});
	});

	await openComposer(page, 'guest', 390);
	await expect(page.getByTestId('report-issue-attach-image')).toHaveCount(0);
	await expect(page.getByTestId('report-issue-pick-element')).toBeVisible();

	const field = page.getByTestId('report-issue-title');
	await field.fill('Existing notes.');
	await page.getByTestId('report-issue-dictate').click();
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible();
	await expect(overlay.getByTestId('record-finish-button')).toBeVisible();
	await expect.poll(() => connections.length).toBe(1);
	await overlay.getByTestId('record-finish-button').click();
	await expect(overlay).toHaveCount(0);
	await expect(field).toHaveValue(`Existing notes.\n${CORRECTED}`);
	await expect(field).toBeEnabled();
	expect(new URL(connections[0]).searchParams.get('anonymous_id')).toBe('report-issue-dictation-guest');
	expect(new URL(connections[0]).searchParams.get('purpose')).toBeNull();
	await test.info().attach('report-issue-composer-dictated', {
		body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
		contentType: 'image/png'
	});
});
