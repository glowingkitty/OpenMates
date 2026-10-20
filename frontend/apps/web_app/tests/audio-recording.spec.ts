/**
 * Audio recording flow E2E tests.
 *
 * Tests the mic button interaction in an authenticated composer.
 *
 * Chromium is launched with --use-fake-device-for-media-stream so that
 * getUserMedia() resolves with a fake audio stream (no real microphone needed).
 * Microphone permission is auto-granted via browser context settings.
 *
 * Test matrix:
 *   1. Legacy manual dark mode → remains dark after app initialization
 *   2. Single tap  → no recording overlay; inline "Press & hold" label highlights
 *   3. Press & hold (>500ms) → recording overlay appears with correct UI elements
 *   4. Active recording → quiet speech produces clearly visible rolling bars
 *   5. Finish → corrected transcript becomes editable draft text without audio storage
 *   6. Cancel → no draft text or embed
 */

import { test, expect } from './helpers/cookie-audit';
/* eslint-disable @typescript-eslint/no-require-imports */
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');

// Configure the browser to use a fake audio device and grant mic permission
test.use({
	launchOptions: {
		args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
	},
	permissions: ['microphone']
});

const consoleLogs: string[] = [];
const audioDraftSnapshots: Array<{ label: string; diagnostics: unknown[]; recordingDiagnostics: unknown[]; editorFocused: boolean; sendDisabled: boolean | null }> = [];

async function snapshotAudioDraftState(page: any, label: string) {
	const snapshot = await page.evaluate(() => {
		const diagnostics = (window as typeof window & { __openmatesMessageInputDraftDiagnostics?: unknown[] })
			.__openmatesMessageInputDraftDiagnostics ?? [];
		const recordingDiagnostics = (window as typeof window & { __openmatesAudioRecordingDiagnostics?: unknown[] })
			.__openmatesAudioRecordingDiagnostics ?? [];
		const editor = document.querySelector('[data-testid="message-editor"] [contenteditable="true"]');
		const send = document.querySelector('[data-testid="composer-send-button"]') as HTMLButtonElement | null;
		return { diagnostics: [...diagnostics], recordingDiagnostics: [...recordingDiagnostics], editorFocused: document.activeElement === editor, sendDisabled: send?.disabled ?? null };
	}).catch(() => ({ diagnostics: [], recordingDiagnostics: [], editorFocused: false, sendDisabled: null }));
	audioDraftSnapshots.push({ label, ...snapshot });
}

async function enableAudioDiagnosticMarker(page: any) {
	// The recording diagnostic is gated by the existing E2E session marker.
	// Enable it only in the three bounded failure investigations after login.
	await page.evaluate(() => sessionStorage.setItem(
		'openmates_e2e_log_forwarding',
		JSON.stringify({ runId: 'audio-recording-diagnostic', token: 'local-e2e' })
	));
}

test.beforeEach(async ({ page }) => {
	consoleLogs.length = 0;
	audioDraftSnapshots.length = 0;

	// Collect console logs for debugging on failure
	page.on('console', (msg) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
});

test.afterEach(async ({ page }, testInfo) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		const draftDiagnostics = await page.evaluate(() =>
			(window as typeof window & { __openmatesMessageInputDraftDiagnostics?: unknown[] })
				.__openmatesMessageInputDraftDiagnostics ?? []
		).catch(() => []);
		const recordingDiagnostics = await page.evaluate(() =>
			(window as typeof window & { __openmatesAudioRecordingDiagnostics?: unknown[] })
				.__openmatesAudioRecordingDiagnostics ?? []
		).catch(() => []);
		const idAliases = new Map<string, string>();
		const aliasId = (id: unknown) => {
			if (typeof id !== 'string' || !id) return id;
			if (!idAliases.has(id)) idAliases.set(id, `chat-${idAliases.size + 1}`);
			return idAliases.get(id);
		};
		const sanitizeDiagnostics = (entries: unknown[]) => entries.map((raw) => {
			const entry = raw as Record<string, unknown>;
			return {
				event: entry.event,
				chatId: aliasId(entry.chatId),
				currentChatId: aliasId(entry.currentChatId),
				draftStateChatId: aliasId(entry.draftStateChatId),
				version: entry.version,
				hasEditor: entry.hasEditor,
				hasDraftContent: entry.hasDraftContent,
				textLength: entry.textLength,
				reason: entry.reason
			};
		});
		const sanitizeRecordingDiagnostics = (entries: unknown[]) => entries.map((raw) => {
			const entry = raw as Record<string, unknown>;
			return {
				event: entry.event,
				reason: entry.reason,
				contextPresent: entry.contextPresent,
				sameContext: entry.sameContext,
				generationMatch: entry.generationMatch,
				editorSame: entry.editorSame,
				editorAlive: entry.editorAlive,
				chatIdEqual: entry.chatIdEqual,
				chatIdEqualsDraftId: entry.chatIdEqualsDraftId,
				draftStateIdEqualsContext: entry.draftStateIdEqualsContext,
				contextChatIdPresent: entry.contextChatIdPresent,
				contextDraftIdPresent: entry.contextDraftIdPresent,
				currentChatIdPresent: entry.currentChatIdPresent,
				draftStateIdPresent: entry.draftStateIdPresent,
				correctionPending: entry.correctionPending,
				realtimeAssigned: entry.realtimeAssigned,
				editorFocused: entry.editorFocused,
				authenticated: entry.authenticated
			};
		});
		console.log('[DRAFT CONTEXT DIAGNOSTICS]', sanitizeDiagnostics(draftDiagnostics));
		console.log('[RECORDING CONTEXT DIAGNOSTICS]', sanitizeRecordingDiagnostics(recordingDiagnostics));
		console.log('[DRAFT BOUNDARY SNAPSHOTS]', audioDraftSnapshots.map((snapshot) => ({
			label: snapshot.label,
			diagnostics: sanitizeDiagnostics(snapshot.diagnostics),
			recordingDiagnostics: sanitizeRecordingDiagnostics(snapshot.recordingDiagnostics),
			editorFocused: snapshot.editorFocused,
			sendDisabled: snapshot.sendDisabled
		})));
		const lifecycleEvents = /draftEditorUIState signals new chat to select|Preserving live composer while activating persisted draft shell|Activated persisted draft-only chat|Generated new temporary chat ID|Set currentChatId in draft state to new temporary chat ID|Recording transcription failed|Recording finished|Component destroying/;
		console.log('[DRAFT/RECORDING LIFECYCLE]');
		consoleLogs.slice(-1000).forEach((log: string) => {
			const event = log.match(lifecycleEvents)?.[0];
			if (event) console.log(`${log.slice(0, 26)} ${event}`);
		});
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

/**
 * Helper: navigate to the app, wait for the page to be loaded, and focus the
 * message field editor so action buttons appear. Returns the message field locator.
 */
async function setupAndFocusMessageField(page: any) {
	await loginToTestAccount(page, () => undefined, async () => undefined);
	await startNewChat(page, () => undefined);

	const messageField = page.getByTestId('message-field');
	await expect(messageField).toBeVisible({ timeout: 20000 });

	// Click the editor content area to focus it — this sets isMessageFieldFocused=true
	// and makes ActionButtons visible via shouldShowActionButtons.
	// Use `.editor-content.prose` to target the main message input field specifically,
	// since demo chat messages also have `.editor-content` elements on the page.
	await messageField.click();
	const editorContent = page.getByTestId('message-editor');
	await expect(editorContent).toBeVisible({ timeout: 10000 });
	await editorContent.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');

	// Give time for focus state to propagate and action buttons to render
	await page.waitForTimeout(1000);

	return messageField;
}

/**
 * Helper: find the mic/record button. Uses aria-label as a stable selector.
 * Falls back to class selector if aria-label not found.
 */
function getMicButton(page: any) {
	return page.locator('[data-testid="message-field"]').last().getByTestId('record-audio-button');
}

/**
 * Helper: wait for mic button to be visible, with extended timeout and debug.
 */
async function waitForMicButton(page: any) {
	const micButton = getMicButton(page);

	// Check if action buttons wrapper exists at all
	const actionButtonsWrapper = page.locator('[data-testid="action-buttons"]').last();
	const actionButtonsVisible = await actionButtonsWrapper.isVisible().catch(() => false);
	if (!actionButtonsVisible) {
		// Take screenshot for debugging
		await page.screenshot({ path: '/tmp/pw-results/debug-no-action-buttons.png' });
		console.log('[DEBUG] action-buttons not visible. Dumping relevant DOM...');
		const html = await page
			.locator('[data-testid="message-field"]')
			.last()
			.innerHTML()
			.catch(() => 'NOT FOUND');
		console.log('[DEBUG] message-field innerHTML (first 500 chars):', html.substring(0, 500));
	}

	await expect(micButton).toBeVisible({ timeout: 20000 });
	return micButton;
}

async function installDeterministicAudioAnalyser(page: any) {
	await page.addInitScript(() => {
		const quietSpeechAmplitude = 8;
		const testState = {
			frame: 0,
			contexts: [] as Array<{ analyser: boolean; processor: boolean; closeCount: number }>
		};
		Object.defineProperty(window, '__waveformTestState', {
			configurable: true,
			value: testState
		});

		class DeterministicAnalyser {
			fftSize = 256;
			frequencyBinCount = 128;

			getByteTimeDomainData(data: Uint8Array) {
				const amplitude = testState.frame++ % 2 === 0 ? 0 : quietSpeechAmplitude;
				for (let index = 0; index < data.length; index += 1) {
					data[index] = 128 + Math.round(Math.sin((index / data.length) * Math.PI * 2) * amplitude);
				}
			}

			disconnect() {}
		}

		class DeterministicSource {
			connect(node: DeterministicAnalyser) {
				return node;
			}

			disconnect() {}
		}

		class DeterministicAudioContext {
			state = 'running';
			destination = {};
			private graph = { analyser: false, processor: false, closeCount: 0 };

			constructor() {
				testState.contexts.push(this.graph);
			}

			createAnalyser() {
				this.graph.analyser = true;
				return new DeterministicAnalyser();
			}

			createMediaStreamSource() {
				return new DeterministicSource();
			}

			createScriptProcessor() {
				this.graph.processor = true;
				return { onaudioprocess: null, connect: () => undefined, disconnect: () => undefined };
			}

			createGain() {
				return { gain: { value: 1 }, connect: () => undefined, disconnect: () => undefined };
			}

			close() {
				this.graph.closeCount += 1;
				this.state = 'closed';
				return Promise.resolve();
			}
		}

		Object.defineProperty(window, 'AudioContext', {
			configurable: true,
			value: DeterministicAudioContext
		});
	});
}

async function installLegacyDarkModePreference(page: any) {
	await page.emulateMedia({ colorScheme: 'light' });
	await page.addInitScript(() => {
		localStorage.removeItem('theme_mode');
		localStorage.setItem('theme_preference', 'manual');
		localStorage.setItem('theme', 'dark');
	});
}

async function expectWaveformContained(overlay: any, waveform: any) {
	await expect
		.poll(async () => {
			const overlayBox = await overlay.boundingBox();
			const waveformBox = await waveform.boundingBox();
			if (!overlayBox || !waveformBox) return false;

			return (
				waveformBox.x >= overlayBox.x &&
				waveformBox.x + waveformBox.width <= overlayBox.x + overlayBox.width
			);
		})
		.toBe(true);
}

async function dispatchHoldAndReleaseMicButton(page: any, micButton: any, holdMs = 2000, verifyDiagnosticCapture = false, waitForCorrection = true) {
	await micButton.dispatchEvent('mousedown', { button: 0 });
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	if (verifyDiagnosticCapture) {
		await expect.poll(() => page.evaluate(() =>
			Boolean(sessionStorage.getItem('openmates_e2e_log_forwarding'))
		)).toBe(true);
		await expect.poll(() => page.evaluate(() => {
			const events = (window as typeof window & { __openmatesAudioRecordingDiagnostics?: Array<{ event?: string }> })
				.__openmatesAudioRecordingDiagnostics ?? [];
			return events.some((entry) => entry.event === 'capture');
		})).toBe(true);
	}
	await page.waitForTimeout(holdMs);
	await overlay.getByTestId('record-finish-button').click();
    if (waitForCorrection) await expect(overlay).not.toBeVisible({ timeout: 10000 });
}

async function getEditorPlainText(page: any): Promise<string> {
	return page.getByTestId('message-editor').evaluate((element: HTMLElement) =>
		(element.textContent ?? '').replace(/\u00a0/g, ' ')
	);
}

function getEditableEditor(page: any) {
	return page.getByTestId('message-editor').locator('[contenteditable="true"]');
}

async function expectRecordingAudioContextsReleased(page: any) {
	await expect.poll(() => page.evaluate(() => {
		const state = (window as unknown as {
			__waveformTestState: { contexts: Array<{ analyser: boolean; processor: boolean; closeCount: number }> };
		}).__waveformTestState;
		return state.contexts;
	})).toEqual([
		{ analyser: false, processor: true, closeCount: 1 },
		{ analyser: true, processor: false, closeCount: 1 }
	]);
}

// ─────────────────────────────────────────────────────────────────────────────
// Test 1: Existing users keep their legacy manual dark mode preference
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.layout.responsive-parity
test('legacy manual dark mode preference remains active on app load', async ({ page }) => {
	test.setTimeout(60000);

	await installLegacyDarkModePreference(page);
	await page.goto(getE2EDebugUrl('/'));

	await expect
		.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme')))
		.toBe('dark');
	await expect
		.poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor))
		.toBe('rgb(23, 23, 23)');
	await expect.poll(() => page.evaluate(() => localStorage.getItem('theme_mode'))).toBe('dark');
});

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript
test('guest microphone opens authentication before recording', async ({ page }) => {
	await page.goto(getE2EDebugUrl('/'));
	const microphone = page.getByTestId('guest-cta-mic-button');
	await expect(microphone).toBeVisible();
	await microphone.dispatchEvent('mousedown', { button: 0 });
	await expect(page.getByTestId('record-overlay')).toHaveCount(0);
	await expect(page.locator('[data-testid="login-modal"], [data-testid="signup-modal"]')).toBeVisible();
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 2: Single tap starts recording and keeps the composer expanded
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
test('single tap on mic button starts recording without focusing the text editor', async ({ page }) => {
	test.setTimeout(60000);

	await setupAndFocusMessageField(page);
	const micButton = await waitForMicButton(page);

	// Quick click starts the explicit recording overlay.
	await micButton.click({ delay: 50 });

	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	await expect(overlay.getByTestId('release-text')).toContainText('Recording');
	await expect(overlay.getByTestId('record-cancel-button')).toBeVisible();
	await expect(overlay.getByTestId('record-finish-button')).toBeVisible();

	// Recording keeps the composer expanded, but the editable field must release
	// focus so touch devices do not open the software keyboard under the overlay.
	const messageField = page.getByTestId('message-field');
	await expect(messageField).not.toHaveClass(/compact/);
	await expect
		.poll(() =>
			page.getByTestId('message-editor').evaluate((element: HTMLElement) =>
				element.contains(document.activeElement)
			)
		)
		.toBe(false);
	expect(await getEditorPlainText(page)).toBe('');
	await page.keyboard.type('must not reach editor');
	expect(await getEditorPlainText(page)).toBe('');
	await overlay.getByTestId('record-cancel-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 5000 });

	console.log('[TEST] Single tap: recording overlay visible and composer expanded');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 2b: Keyboard shortcut starts recording without inserting text
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
test('keyboard recording shortcut shows Enter and Escape controls without inserting text', async ({ page }) => {
	test.setTimeout(60000);

	await setupAndFocusMessageField(page);
	const messageField = page.getByTestId('message-field');
	await page.mouse.click(8, 8);
	await expect(messageField).toHaveClass(/compact/, { timeout: 5000 });
	expect(await getEditorPlainText(page)).toBe('');
	const embedCountBefore = await page.getByTestId('recording-preview').count();

	await page.keyboard.press('Control+Shift+M');
	await expect(messageField).toHaveClass(/focused/);
	await expect(messageField).not.toHaveClass(/compact/);

	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	await expect(overlay.getByTestId('release-text')).toContainText('Recording');
	await expect(overlay.getByTestId('record-shortcuts')).toContainText('Press Enter to finish');
	await expect(overlay.getByTestId('record-shortcuts')).toContainText('Escape to cancel');

	await page.mouse.move(20, 20);
	await page.waitForTimeout(500);
	await expect(overlay).toBeVisible();
	expect(await getEditorPlainText(page)).toBe('');
	expect(await page.getByTestId('recording-preview').count()).toBe(embedCountBefore);

	await page.waitForTimeout(500);
	await overlay.getByTestId('record-cancel-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 5000 });

	expect(await getEditorPlainText(page)).toBe('');
	expect(await page.getByTestId('recording-preview').count()).toBe(embedCountBefore);

	console.log('[TEST] Keyboard recording shortcut: controls visible and cancel leaves editor empty');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 2c: Keyboard recording shortcut must suppress focus-visible outlines.
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
test('keyboard recording shortcut suppresses composer outline', async ({ page }) => {
	test.setTimeout(60000);

	await setupAndFocusMessageField(page);
	const messageField = page.getByTestId('message-field');
	await waitForMicButton(page);

	await messageField.evaluate((element: HTMLElement) => element.focus());
	await expect
		.poll(() =>
			messageField.evaluate((element: HTMLElement) => ({
				isActive: document.activeElement === element,
				outlineStyle: getComputedStyle(element).outlineStyle
			}))
		)
		.toMatchObject({ isActive: true, outlineStyle: 'solid' });

	await page.keyboard.press('Control+Shift+M');

	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	await expect(overlay.getByTestId('record-shortcuts')).toContainText('Press Enter to finish');
	await expect
		.poll(() =>
			overlay.evaluate((element: HTMLElement) => ({
				outlineStyle: getComputedStyle(element).outlineStyle
			}))
		)
		.toMatchObject({ outlineStyle: 'none' });
	await expect
		.poll(() =>
			messageField.evaluate((element: HTMLElement) => ({
				isActive: document.activeElement === element,
				outlineStyle: getComputedStyle(element).outlineStyle
			}))
		)
		.toMatchObject({ isActive: false, outlineStyle: 'none' });

	await page.keyboard.press('Escape');
	await expect(overlay).not.toBeVisible({ timeout: 5000 });

	console.log('[TEST] Keyboard recording shortcut: overlay owns focus and composer outline is suppressed');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 3: Press & hold shows recording overlay with expected UI elements
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
test('press and hold mic button shows recording overlay', async ({ page }) => {
	test.setTimeout(60000);

	await setupAndFocusMessageField(page);
	const micButton = await waitForMicButton(page);

	// Press and hold: mousedown, wait for overlay, then verify before releasing
	await micButton.dispatchEvent('mousedown', { button: 0 });

	// Wait for the recording overlay to appear (200ms hold threshold + mount time)
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });

	// Verify overlay contains expected UI elements
	// 1. "Release to finish" heading
	const releaseText = overlay.getByTestId('release-text');
	await expect(releaseText).toBeVisible();

	// 2. Timer pill (showing 00:00 or 00:01)
	const timerPill = overlay.getByTestId('timer-pill');
	await expect(timerPill).toBeVisible();


	// 3. Keyboard shortcut hint and explicit action buttons
	await expect(overlay.getByTestId('record-shortcuts')).toContainText('Escape to cancel');
	await expect(overlay.getByTestId('record-cancel-button')).toBeVisible();
	await expect(overlay.getByTestId('record-finish-button')).toBeVisible();

	console.log('[TEST] Press & hold: overlay visible with all UI elements');

	// Cancel to clean up
	await overlay.getByTestId('record-cancel-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 5000 });
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 4: Active recording shows a responsive rolling waveform
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
test('active recording shows live rolling waveform and releases analyser resources', async ({ page }) => {
	test.setTimeout(60000);

	await installDeterministicAudioAnalyser(page);
	await setupAndFocusMessageField(page);
	const micButton = await waitForMicButton(page);
	await micButton.dispatchEvent('mousedown', { button: 0 });

	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });

	const releaseText = overlay.getByTestId('release-text');
	const waveform = overlay.getByTestId('recording-waveform');
	const controls = overlay.getByTestId('record-controls');
	await expect(waveform).toBeVisible();
	await expect(waveform).toHaveAttribute('aria-hidden', 'true');
	await expect
		.poll(async () => (await overlay.boundingBox())?.height ?? 0)
		.toBeGreaterThanOrEqual(220);

	const bars = waveform.getByTestId('recording-waveform-bar');
	expect(await bars.count()).toBeGreaterThan(20);

	const initialLevels = await bars.evaluateAll((elements: Element[]) =>
		elements.map((element) => element.getAttribute('data-level'))
	);
	await expect
		.poll(
			async () =>
				bars.evaluateAll((elements: Element[]) =>
					elements.map((element) => element.getAttribute('data-level'))
				),
			{ timeout: 5000 }
		)
		.not.toEqual(initialLevels);

	const levels = (await bars.evaluateAll((elements: Element[]) =>
		elements.map((element) => Number(element.getAttribute('data-level')))
	)) as number[];
	expect(levels.some((level) => level === 0)).toBeTruthy();
	expect(levels.some((level) => level > 0)).toBeTruthy();

	const minimumBarHeight = Math.min(
		...(await bars.evaluateAll((elements: Element[]) =>
			elements.map((element) => Number.parseFloat(getComputedStyle(element).height))
		))
	);
	expect(minimumBarHeight).toBeGreaterThanOrEqual(2);
	const maximumBarHeight = Math.max(
		...(await bars.evaluateAll((elements: Element[]) =>
			elements.map((element) => Number.parseFloat(getComputedStyle(element).height))
		))
	);
	expect(maximumBarHeight).toBeGreaterThanOrEqual(24);

	await expect
		.poll(async () => {
			const releaseBox = await releaseText.boundingBox();
			const waveformBox = await waveform.boundingBox();
			const controlsBox = await controls.boundingBox();
			if (!releaseBox || !waveformBox || !controlsBox) return false;

			return (
				waveformBox.y >= releaseBox.y + releaseBox.height &&
				waveformBox.y + waveformBox.height <= controlsBox.y
			);
		})
		.toBe(true);
	await expectWaveformContained(overlay, waveform);

	await page.setViewportSize({ width: 390, height: 844 });
	await expect(waveform).toBeVisible();
	await expectWaveformContained(overlay, waveform);

	await overlay.getByTestId('record-cancel-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 10000 });
	await expectRecordingAudioContextsReleased(page);
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 5: Corrected speech enters the existing draft as editable text
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript
test('Mercury corrected recording inserts editable text at the original caret without audio storage', async ({ page }) => {
	test.setTimeout(120000);
	let audioUploadRequests = 0;
	let batchTranscriptionRequests = 0;
	page.on('request', (request: any) => {
		if (request.method() !== 'POST') return;
		if (request.url().includes('/v1/upload/file')) audioUploadRequests++;
		if (request.url().includes('/v1/apps/audio/skills/transcribe')) batchTranscriptionRequests++;
	});
	await page.routeWebSocket('**/v1/apps/audio/realtime-transcription*', (socket: any) => {
		socket.send(JSON.stringify({ type: 'session.ready' }));
		socket.onMessage((payload: string) => {
			if (JSON.parse(payload).type !== 'input_audio.end') return;
			socket.send(JSON.stringify({ type: 'transcription.done', transcript: 'um review please', model: 'test-realtime' }));
			socket.send(JSON.stringify({ type: 'correction.started', model: 'mercury-3' }));
			socket.send(JSON.stringify({ type: 'correction.done', transcript: 'review', correction_model: 'mercury-3' }));
		});
	});
	await setupAndFocusMessageField(page);
	await enableAudioDiagnosticMarker(page);
	const editor = getEditableEditor(page);
	await editor.fill('Please  now');
	await editor.press('Home');
	for (let index = 0; index < 7; index++) await editor.press('ArrowRight');
	const micButton = await waitForMicButton(page);
	await snapshotAudioDraftState(page, 'before-existing-draft-recording');
	await dispatchHoldAndReleaseMicButton(page, micButton, 2000, true);
	await snapshotAudioDraftState(page, 'after-existing-draft-release');
	await expect(editor).toHaveText('Please review now', { timeout: 30000 });
	await expect(page.getByTestId('recording-preview')).toHaveCount(0);
	const activeSendButton = page.getByTestId('composer-send-button').filter({ visible: true });
	await expect(activeSendButton).toHaveCount(1);
	await expect(activeSendButton).toBeVisible();
	await expect(editor).toBeFocused();
	await page.keyboard.type('!');
	await expect(editor).toHaveText('Please review! now');
	expect(audioUploadRequests).toBe(0);
	expect(batchTranscriptionRequests).toBe(0);
});

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript
test('corrected transcript markup and newlines stay ordinary editable text', async ({ page }) => {
	test.setTimeout(120000);
	const transcript = 'literal <b>bold</b> & <img src=x>\nnext line';
	await page.routeWebSocket('**/v1/apps/audio/realtime-transcription*', (socket: any) => {
		socket.send(JSON.stringify({ type: 'session.ready' }));
		socket.onMessage((payload: string) => {
			if (JSON.parse(payload).type !== 'input_audio.end') return;
			socket.send(JSON.stringify({ type: 'transcription.done', transcript, model: 'test-realtime' }));
			socket.send(JSON.stringify({ type: 'correction.done', transcript }));
		});
	});
	await setupAndFocusMessageField(page);
	await enableAudioDiagnosticMarker(page);
	await dispatchHoldAndReleaseMicButton(page, await waitForMicButton(page), 2000, true);
	const editor = getEditableEditor(page);
	await expect(editor).toContainText('<b>bold</b> & <img src=x>');
	await expect(editor).toContainText('next line');
	await expect(editor.locator('b, img, a, audio, video, iframe')).toHaveCount(0);
	await expect(editor.locator('br:not(.ProseMirror-trailingBreak)')).toHaveCount(1);
	await snapshotAudioDraftState(page, 'before-literal-followup-key');
	await expect(editor).toBeFocused();
	await page.keyboard.type('!');
	await expect(editor).toContainText('next line!');
});

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript
test('pending correction keeps the overlay visible until corrected text is inserted', async ({ page }) => {
	test.setTimeout(120000);
	let releaseCorrection: (() => void) | null = null;
	await page.routeWebSocket('**/v1/apps/audio/realtime-transcription*', (socket: any) => {
		socket.send(JSON.stringify({ type: 'session.ready' }));
		socket.onMessage((payload: string) => {
			if (JSON.parse(payload).type !== 'input_audio.end') return;
			socket.send(JSON.stringify({ type: 'transcription.done', transcript: 'review', model: 'test-realtime' }));
			releaseCorrection = () => socket.send(JSON.stringify({ type: 'correction.done', transcript: 'review' }));
		});
	});
	await setupAndFocusMessageField(page);
	await enableAudioDiagnosticMarker(page);
	const editor = getEditableEditor(page);
	await editor.fill('Please  now');
	await editor.press('Home');
	for (let index = 0; index < 7; index++) await editor.press('ArrowRight');
	await snapshotAudioDraftState(page, 'before-pending-draft-recording');
	await dispatchHoldAndReleaseMicButton(page, await waitForMicButton(page), 2000, true, false);
	await expect.poll(() => releaseCorrection !== null).toBe(true);
	await snapshotAudioDraftState(page, 'pending-existing-draft-correction');
	const overlay = page.getByTestId('record-overlay');
	const status = overlay.getByTestId('recording-processing-text');
	await expect(overlay).toBeVisible();
	await expect(status).toHaveText('Improving transcript…');
	await expect(overlay.getByTestId('record-finish-button')).toBeDisabled();
	await expect(overlay.getByTestId('record-cancel-button')).toBeVisible();
	await expect(editor).toHaveText('Please  now');
	await expect(editor).not.toBeFocused();
	const sendButton = page.getByTestId('composer-send-button').last();
	await expect.poll(async () => (await sendButton.count()) === 0 || await sendButton.isDisabled()).toBe(true);
	const sentMessagesBefore = await page.getByTestId('message-user').count();
	await editor.evaluate((element: HTMLElement) => element.dispatchEvent(new CustomEvent('custom-send-message', {
		bubbles: true,
		cancelable: true
	})));
	await expect(page.getByTestId('message-user')).toHaveCount(sentMessagesBefore);
	await expect(status).toHaveText('Removing filler words…', { timeout: 4000 });
	await expect(status).toHaveText('Making it more concise…', { timeout: 4000 });
	await expect(overlay).toBeVisible();
	await expect(editor).toHaveText('Please  now');
	(releaseCorrection as (() => void) | null)?.();
	await expect(overlay).not.toBeVisible();
	await expect(editor).toHaveText('Please review now');
	await expect(editor).toBeFocused();
	await page.keyboard.type('!');
	await expect(editor).toHaveText('Please review! now');
	await expect(sendButton).toBeVisible();
	await expect(sendButton).toBeEnabled();
	await expect(page.getByTestId('recording-preview')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
test('Escape cancels pending correction without changing the existing draft', async ({ page }) => {
	test.setTimeout(120000);
	let correctionPending = false;
	await page.routeWebSocket('**/v1/apps/audio/realtime-transcription*', (socket: any) => {
		socket.send(JSON.stringify({ type: 'session.ready' }));
		socket.onMessage((payload: string) => {
			if (JSON.parse(payload).type !== 'input_audio.end') return;
			socket.send(JSON.stringify({ type: 'transcription.done', transcript: 'discard me', model: 'test-realtime' }));
			correctionPending = true;
		});
	});
	await setupAndFocusMessageField(page);
	const editor = getEditableEditor(page);
	await editor.fill('Keep this draft');
	await dispatchHoldAndReleaseMicButton(page, await waitForMicButton(page), 2000, false, false);
	await expect.poll(() => correctionPending).toBe(true);
	await expect(page.getByTestId('recording-processing-text')).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(page.getByTestId('record-overlay')).not.toBeVisible();
	await expect(editor).toHaveText('Keep this draft');
	await expect(page.getByTestId('recording-preview')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
test('correction failure closes processing and preserves the existing draft', async ({ page }) => {
	test.setTimeout(120000);
	let failCorrection: (() => void) | null = null;
	await page.routeWebSocket('**/v1/apps/audio/realtime-transcription*', (socket: any) => {
		socket.send(JSON.stringify({ type: 'session.ready' }));
		socket.onMessage((payload: string) => {
			if (JSON.parse(payload).type !== 'input_audio.end') return;
			failCorrection = () => socket.send(JSON.stringify({ type: 'session.error', message: 'Synthetic correction failure' }));
		});
	});
	await setupAndFocusMessageField(page);
	const editor = getEditableEditor(page);
	await editor.fill('Keep this draft');
	await dispatchHoldAndReleaseMicButton(page, await waitForMicButton(page), 2000, false, false);
	await expect.poll(() => failCorrection !== null).toBe(true);
	await expect(page.getByTestId('recording-processing-text')).toBeVisible();
	(failCorrection as (() => void) | null)?.();
	await expect(page.getByTestId('record-overlay')).not.toBeVisible();
	await expect(editor).toHaveText('Keep this draft');
	await expect(page.getByTestId('recording-preview')).toHaveCount(0);
});

// Test 5b: A late correction belongs only to its original draft
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript
test('late correction cannot alter the next chat draft', async ({ page }) => {
	test.setTimeout(120000);
	let releaseCorrection: (() => void) | null = null;
	await page.routeWebSocket('**/v1/apps/audio/realtime-transcription*', (socket: any) => {
		socket.send(JSON.stringify({ type: 'session.ready' }));
		socket.onMessage((payload: string) => {
				if (JSON.parse(payload).type !== 'input_audio.end') return;
			socket.send(JSON.stringify({ type: 'transcription.done', transcript: 'old words', model: 'test-realtime' }));
			releaseCorrection = () => socket.send(JSON.stringify({ type: 'correction.done', transcript: 'old words' }));
		});
	});
	await setupAndFocusMessageField(page);
	const editor = getEditableEditor(page);
	await editor.fill('Original note');
	await dispatchHoldAndReleaseMicButton(page, await waitForMicButton(page), 2000, false, false);
	await expect.poll(() => releaseCorrection !== null).toBe(true);
	await startNewChat(page, () => undefined);
	await getEditableEditor(page).fill('New draft');
	(releaseCorrection as (() => void) | null)?.();
	await expect(page.getByTestId('message-editor')).toHaveText('New draft');
	await expect(page.getByTestId('recording-preview')).toHaveCount(0);
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 6: Press & hold then Escape → recording cancelled, no embed
// ─────────────────────────────────────────────────────────────────────────────
// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.audio.editable-transcript
test('press hold then escape cancels recording', async ({ page }) => {
	test.setTimeout(60000);

	await installDeterministicAudioAnalyser(page);
	await setupAndFocusMessageField(page);
	const micButton = await waitForMicButton(page);

	// Count existing recording embeds before
	const embedCountBefore = await page.getByTestId('recording-preview').count();

	// Press and hold
	await micButton.dispatchEvent('mousedown', { button: 0 });

	// Wait for overlay to appear
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });

	// Hold briefly, then press Escape to cancel
	await page.waitForTimeout(500);
	await page.keyboard.press('Escape');

	// Overlay should disappear
	await expect(overlay).not.toBeVisible({ timeout: 5000 });

	// No new recording embed should have been inserted
	await page.waitForTimeout(1000);
	const embedCountAfter = await page.getByTestId('recording-preview').count();
	expect(embedCountAfter).toBe(embedCountBefore);
	await expectRecordingAudioContextsReleased(page);

	console.log('[TEST] Press hold escape: recording cancelled, no embed');
});
