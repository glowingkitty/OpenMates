/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.catalog.capability-recommendation-variants
test('Mercury 3 is manually selectable through Inception with medium capability', async ({ page }: { page: any }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, email, password, otpKey);

	const log = createSignupLogger('MERCURY3_MODEL_PICKER');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'mercury3-model-picker' });
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const sidebar = page.getByTestId('activity-history-wrapper');
	if (await sidebar.isVisible()) {
		await sidebar.getByRole('button', { name: 'Close', exact: true }).click();
	}
	await expect(sidebar).not.toBeVisible();

	const composer = page.getByTestId('active-chat-container').getByTestId('message-field').last();
	const editor = composer.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 20000 });
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');
	const selector = composer.getByTestId('composer-model-selector');
	await expect(selector).toBeVisible({ timeout: 10000 });
	await selector.click();
	const menu = composer.getByTestId('composer-model-selector-menu');
	await menu.getByTestId('composer-model-show-more').click();
	const inception = menu.getByTestId('composer-model-provider-inception');
	await expect(inception.getByTestId('composer-model-provider-label').locator('strong')).toHaveText('Inception');
	const providerIcon = inception.getByTestId('composer-model-provider-icon');
	// Vite inlines this small SVG in production builds; development serves the file URL.
	await expect(providerIcon).toHaveAttribute('src', /^(?:data:image\/svg\+xml[;,]|.*\/inception(?:[.-][\w-]+)?\.svg(?:\?|$))/);
	await expect.poll(() => providerIcon.evaluate((icon: HTMLImageElement) => icon.complete && icon.naturalWidth > 0)).toBe(true);
	const inceptionIconSrc = await providerIcon.getAttribute('src');
	await inception.click();

	const mercury = menu.getByTestId('composer-model-row').filter({
		has: page.getByTestId('composer-model-name').locator('strong').filter({ hasText: /^Mercury 3$/ })
	});
	await expect(mercury).toHaveCount(1);
	await expect(mercury.getByTestId('composer-model-capability')).toHaveAttribute('data-level', 'medium');
	const modelIcon = mercury.getByTestId('composer-model-icon').locator('img');
	await expect(modelIcon).toHaveAttribute('src', inceptionIconSrc);
	await expect.poll(() => modelIcon.evaluate((icon: HTMLImageElement) => icon.complete && icon.naturalWidth > 0)).toBe(true);
	await screenshot(page, 'inception-mercury3-available');

	// Change only this unsent draft's selection; no inference or account-default write.
	await mercury.getByTestId('composer-model-toggle').click();
	await expect(menu).not.toBeVisible();
	await expect(selector.getByTestId('composer-model-selector-label')).toHaveText('Mercury 3');
	await expect(selector.getByTestId('composer-model-selector-capability')).toHaveAttribute('data-level', 'medium');
	await expect(selector).toHaveAttribute('aria-label', 'Model selection: Mercury 3, Mercury 3, Medium capability');
	await screenshot(page, 'mercury3-selected');

	// Reopening must return to the exact selected model's provider with its toggle checked.
	await selector.click();
	await expect(mercury.getByRole('checkbox', { name: 'Mercury 3', exact: true })).toBeChecked();
	await menu.getByTestId('composer-model-back').click();
	await menu.getByTestId('composer-model-auto').click();
	await expect(selector.getByTestId('composer-model-selector-label')).toHaveText('Auto select');
	await expect(menu).not.toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=ai-model-routing.reasoning.preprocessor-recommendation,ai-model-routing.defaults.google-tier-profiles,ai-model-routing.precedence.chat-over-tier-over-auto,ai-model-routing.recovery.affordable-current-models
test('Auto uses current affordable models and recovers Gemini before Mercury', async ({ page }: { page: any }) => {
	test.setTimeout(540000);
	test.skip(process.env.CI !== 'true' || process.env.CI_TEST_MODE !== 'e2e'
		|| process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the isolated provider-free product stack.');
	skipWithoutCredentials(test, email, password, otpKey);
	const log = createSignupLogger('MERCURY3_AUTO_ROUTING');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'mercury3-auto-routing' });
	const admissions: any[] = [];
	page.on('websocket', (socket: any) => socket.on('framesent', (frame: { payload: string | Buffer }) => {
		try {
			const event = JSON.parse(String(frame.payload));
			if (['chat_turn_admit', 'chat_turn_preflight'].includes(event.type)) {
				admissions.push(event.payload.inference_request);
			}
		} catch { /* Ignore non-JSON control frames. */ }
	}));
	await installE2EServerContentOverrideGate(page, 'mercury-auto-routing');
	await loginToTestAccount(page, log, screenshot);
	async function setMercuryEnabled(enabled: boolean) {
		const url = new URL(page.url());
		url.hash = 'settings/ai/model/mercury-3';
		await page.goto(url.href, { waitUntil: 'domcontentloaded' });
		const toggle = page.getByTestId('ai-model-details').getByTestId('ai-model-enabled-toggle');
		const checkbox = toggle.locator('input[type="checkbox"]');
		await expect(toggle).toBeVisible({ timeout: 20000 });
		if (await checkbox.isChecked() !== enabled) await toggle.click();
		if (enabled) await expect(checkbox).toBeChecked();
		else await expect(checkbox).not.toBeChecked();
		await screenshot(page, enabled ? 'mercury-enabled' : 'mercury-disabled');
		await page.getByTestId('icon-button-close').click();
		await expect(page.getByTestId('ai-model-details')).not.toBeVisible();
	}

	for (const scenario of [
		{ id: 'success', question: 'What is 2 + 2?', answer: 'The answer is 4. Automatic routing completed successfully.', model: 'Mercury 3' },
		{ id: 'high', question: 'What is 5 + 5?', answer: 'The answer is 10. Low complexity used the separate HIGH recommendation.', model: 'Mercury 3' },
		{ id: 'extra_high', question: 'What is 6 + 6?', answer: 'The answer is 12. Google clamped the EXTRA_HIGH recommendation to HIGH.', model: 'Gemini 3.8 Flash' },
		{ id: 'fallback', question: 'What is 3 + 3?', answer: 'The answer is 6. Automatic routing recovered successfully.', model: 'Gemini 3.8 Flash' },
		{ id: 'disabled', question: 'What is 4 + 4?', answer: 'The answer is 8. Your disabled model was respected.', model: 'Gemini 3.8 Flash' },
		{ id: 'gemini_retry', question: 'Compare the available evidence.', answer: 'Gemini completed the answer on its first clean retry.', model: 'Gemini 3.8 Flash' },
		{ id: 'cheap_fallback', question: 'Summarize the available evidence.', answer: 'Mercury completed the answer as the inexpensive last resort.', model: 'Mercury 3' },
		{ id: 'high_recovery', question: 'Review the interacting constraints.', answer: 'Mercury preserved the recommendation at HIGH during recovery.', model: 'Mercury 3' }
	]) {
		if (scenario.id === 'disabled') await setMercuryEnabled(false);
		await startNewChat(page, log);
		const sidebar = page.getByTestId('activity-history-wrapper');
		if (await sidebar.isVisible()) await sidebar.getByRole('button', { name: 'Close', exact: true }).click();
		await expect(sidebar).not.toBeVisible();
		const composer = page.getByTestId('active-chat-container').getByTestId('message-field').last();
		const editor = composer.getByTestId('message-editor');
		await expect(editor).toBeVisible({ timeout: 20000 });
		await editor.click();
		await page.keyboard.type(' ');
		await page.keyboard.press('Backspace');
		await expect(composer.getByTestId('composer-model-selector-label')).toHaveText('Auto select');
		try {
			// The signed LIVE marker only replaces Jev/provider boundaries. Real model
			// selection, fallback, persistence, and WebSocket delivery still execute.
			// The replay fails closed unless provider effort and Mercury output caps
			// match Jev's independent recommendation (or the unchanged tier default).
			await sendMessage(page,
				`${scenario.question} MERCURY_ROUTING_E2E:${scenario.id} <<<TEST_LIVE_MOCK:mercury_auto_low>>>`,
				log, screenshot, `auto-${scenario.id}`);
			await expect.poll(() => admissions.find(request =>
				request?.message?.content?.includes(`MERCURY_ROUTING_E2E:${scenario.id}`)))
				.toBeTruthy();
			const request = admissions.find(request => request?.message?.content?.includes(`MERCURY_ROUTING_E2E:${scenario.id}`));
			expect(request.test_mock_marker).toBe('<<<TEST_LIVE_MOCK:mercury_auto_low>>>');
			expect(Object.keys(request.model_routing_restrictions).sort()).toEqual(['disabled_ai_models', 'disabled_ai_servers']);
			if (scenario.id === 'disabled') expect(request.model_routing_restrictions.disabled_ai_models).toContain('mercury-3');
			else expect(request.model_routing_restrictions.disabled_ai_models).not.toContain('mercury-3');
			const assistant = await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
			await expect(assistant).toContainText(scenario.answer, { timeout: 60000 });
			await expect(assistant.getByTestId('generated-by')).toContainText(scenario.model, { timeout: 60000 });
			await expect(page.getByTestId('active-chat-container').getByTestId('message-assistant')).toHaveCount(1);
			const answerOccurrences = (await assistant.textContent()).split(scenario.answer).length - 1;
			expect(answerOccurrences).toBe(1);
			if (['gemini_retry', 'cheap_fallback', 'high_recovery'].includes(scenario.id)) {
				const text = await assistant.innerText();
				expect(text.split('Verified prefix.').length - 1).toBe(1);
				expect(text).not.toMatch(/```(?:toon|tool_code)|app_id:|skill_id:|Sonnet|Gemini 3\.7/);
			}
			// Focus Tiptap itself; the empty wrapper's center can be outside its text box.
			await editor.locator('[contenteditable="true"]').click();
			await page.keyboard.type(' ');
			await page.keyboard.press('Backspace');
			await expect(composer).toHaveAttribute('data-focused', 'true');
			await expect(composer.getByTestId('composer-model-selector-label')).toHaveText('Auto select');
			await screenshot(page, `auto-${scenario.id}-completed`);
		} finally {
			if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, `cleanup-${scenario.id}`);
			if (scenario.id === 'disabled') await setMercuryEnabled(true);
		}
	}
});
