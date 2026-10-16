/* eslint-disable @typescript-eslint/no-require-imports */
/** Real-terminal composer and controlled-catalog picker proof, without AI inference. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';

const {test, expect, email, password, otpKey, captureProof, installRecorderDeps,
	requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, runWorkflowCliJson,
	skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {loginWorkflowCliViaPair, removeWorkflowCliHome, workflowCliEnv} = require('./helpers/workflow-cli-e2e-helpers');
const {startNewChat, waitForChatReady} = require('./helpers/chat-test-helpers');
const {execFileSync} = require('node:child_process');
const {randomUUID} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../../..');
const PROFILE = 'cli-terminal';
type CatalogEntry = {id: string; name: string; providerId: string; providerName: string;
	providerBrandName?: string; providerOrder?: number; capability?: string; releaseDate?: string; available: boolean};
type TimedProofStep = ProofStep & {wait_timeout_ms?: number};

const choiceContract = {
	id: 'cli-tui-composer-model-choice', title: 'Terminal composer model choice', surface: 'cli', devices: [PROFILE],
	transcript: [
		{id: 'composer', text: 'The chat keeps its encrypted draft and displays the Auto model control beside the composer.', checkpoint: 'chat-open', devices: [PROFILE]},
		{id: 'picker', text: 'A controlled catalog marks one configured model available; the picker shows its provider, model, and capability beside Auto.', checkpoint: 'provider-open', devices: [PROFILE]},
		{id: 'detail', text: 'A model details action explains the selected model and returns to its provider.', checkpoint: 'model-details', devices: [PROFILE]},
		{id: 'selection', text: 'Pointer and keyboard choices switch between an exact model and Auto without changing the draft.', checkpoint: 'exact-again', devices: [PROFILE]},
		{id: 'resize', text: 'The narrow composer retains the selected model and draft after resizing.', checkpoint: 'narrow', devices: [PROFILE]},
	],
	assertions: [
		{id: 'ai-model-routing.composer.responsive-actions', checkpoint: 'narrow', visual: 'Model selection remains directly reachable and the composer draft survives picker interaction and resize.', devices: [PROFILE]},
		{id: 'ai-model-routing.catalog.capability-recommendation-variants', checkpoint: 'provider-open', visual: 'The configured model marked available by this proof catalog appears under its provider with capability and a separate details action.', devices: [PROFILE]},
		{id: 'ai-model-routing.chat-selection.encrypted-user-chat-scope', checkpoint: 'exact-again', visual: 'An exact choice is selected for this chat; Auto remains an explicit alternative.', devices: [PROFILE]},
		{id: 'terminal-pointer.visible-action-parity', checkpoint: 'exact-again', visual: 'Visible model rows activate their exact selection through real terminal mouse clicks.', devices: [PROFILE]},
		{id: 'terminal-pointer.viewport-coherent', checkpoint: 'narrow-picker-open', visual: 'After resizing, a click on the model trigger opens the currently displayed picker.', devices: [PROFILE]},
		{id: 'terminal-pointer.lifecycle-selection-safe', checkpoint: 'narrow-picker-close', visual: 'Escape backs out of the picker while preserving the composer draft and model choice.', devices: [PROFILE]},
	],
	tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000},
};

const restoreContract = {
	id: 'cli-tui-composer-model-restore', title: 'Terminal composer model restore', surface: 'cli', devices: [PROFILE],
	transcript: [
		{id: 'restore', text: 'A new terminal process restores the exact model and encrypted draft for the same chat.', checkpoint: 'exact-restored', devices: [PROFILE]},
		{id: 'scope', text: 'Another disposable chat opens with Auto and its own encrypted draft.', checkpoint: 'other-chat', devices: [PROFILE]},
	],
	assertions: [
		{id: 'ai-model-routing.chat-selection.encrypted-user-chat-scope', checkpoint: 'other-chat', visual: 'The first chat restores its exact choice while a second chat retains Auto.', devices: [PROFILE]},
	],
	tutorial: choiceContract.tutorial,
};

const coldSendContract = {
  id: 'cli-tui-composer-cold-auto-send', title: 'Cold terminal Auto send', surface: 'cli', devices: [PROFILE],
  transcript: [
    {id: 'enter', text: 'Enter clears the new-chat composer and shows the user message while the model catalog is still loading.', checkpoint: 'sent', devices: [PROFILE]},
    {id: 'mate', text: 'The selected Mate appears without a provisional Assistant Thinking label.', checkpoint: 'mate', devices: [PROFILE]},
  ],
  assertions: [
    {id: 'chats.streaming.progressive-presentation', checkpoint: 'mate', visual: 'The cold Auto send keeps its optimistic user row and shows the named Mate before the response.', devices: [PROFILE]},
    {id: 'ai-model-routing.chat-selection.encrypted-user-chat-scope', checkpoint: 'sent', visual: 'A new unsaved Auto chat sends while the catalog remains pending.', devices: [PROFILE]},
  ],
  tutorial: choiceContract.tutorial,
};

// contract-test: direct surface=cli assertions=chats.streaming.progressive-presentation,ai-model-routing.chat-selection.encrypted-user-chat-scope
test('cold Auto Enter sends in the real terminal before catalog readiness', async ({page}: {page: any}, testInfo: any) => {
  test.setTimeout(180_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e', 'Requires isolated GitHub product stack');
  skipWithoutCredentials(test, email, password, otpKey);
  const cli = requireIsolatedCliBuild(); installRecorderDeps();
  const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-cold-auto');
  const adapterPath = path.join(home, 'cold-auto-adapter.mjs');
  const captureFile = path.join(home, 'cold-auto-send.jsonl');
  const latencyFile = path.join(home, 'cold-auto-latency.jsonl');
  const previousOptions = process.env.NODE_OPTIONS, previousLatency = process.env.OPENMATES_TUI_LATENCY_EVENTS;
  try {
    await loginWorkflowCliViaPair(page, apiUrl, home, 'TUI_COLD_AUTO_SEND_PROOF');
    const modulePath = path.join(path.dirname(cli), 'index.js');
    fs.writeFileSync(adapterPath, `
      import fs from 'node:fs'; import {pathToFileURL} from 'node:url';
      const {OpenMatesClient}=await import(pathToFileURL(${JSON.stringify(modulePath)}).href);
      OpenMatesClient.prototype.getChatModelCatalogSources=async function(){return new Promise(()=>{});};
      OpenMatesClient.prototype.sendMessage=async function(options){
        if(options.chatId||!options.newChatId||options.interactiveHuman!==true)throw Error('Cold proof expected a new interactive chat');
        fs.appendFileSync(${JSON.stringify(captureFile)},JSON.stringify({message:options.message,newChatId:options.newChatId})+'\\n',{mode:0o600});
        options.onStream?.({kind:'typing',content:'',category:'software_development',mateName:'Sophia',taskId:'cold-proof'});
        await new Promise(resolve=>setTimeout(resolve,350));
        return {assistant:'Cold Auto response recorded.',chatId:options.newChatId,mateName:'Sophia',category:'software_development',followUpSuggestions:[]};
      };
    `);
    process.env.NODE_OPTIONS = [previousOptions, `--import=${adapterPath}`].filter(Boolean).join(' ');
    process.env.OPENMATES_TUI_LATENCY_EVENTS = latencyFile;
    const prompt = `Cold Auto proof ${randomUUID().slice(0, 8)}`;
    const steps: TimedProofStep[] = [
      {name: 'landing', wait_for: 'Ask anything', hold_ms: 100},
      {name: 'draft', text: prompt, wait_for: prompt, hold_ms: 100},
      {name: 'sent', key: 'Return', wait_for: 'You', hold_ms: 100},
      {name: 'mate', wait_for: 'Sophia', hold_ms: 150},
      {name: 'final', wait_for: 'Cold Auto response recorded.', hold_ms: 150},
      {name: 'exit', key: 'ctrl+c'},
    ];
    const recording = await captureProof(apiUrl, home, cli, steps, coldSendContract, testInfo);
    expect(frame(recording, 'sent')).toContain(prompt);
    expect(frame(recording, 'sent')).toContain('Ask a follow-up');
    expect(frame(recording, 'sent')).not.toContain('Model selection could not be restored');
    expect(frame(recording, 'mate')).not.toContain('Assistant Thinking');
    expect(frame(recording, 'mate')).toContain('Sophia');
    const calls = fs.readFileSync(captureFile, 'utf8').trim().split('\n').map((line: string) => JSON.parse(line));
    expect(calls).toHaveLength(1);
    expect(calls[0].message).toBe(prompt);
    const milestones = fs.readFileSync(latencyFile, 'utf8').trim().split('\n').map((line: string) => JSON.parse(line));
    expect(milestones.find((event: {milestone: string}) => event.milestone === 'optimistic_user')).toBeTruthy();
    expect(milestones.find((event: {milestone: string}) => event.milestone === 'selected_mate')?.elapsedMs).toBeLessThanOrEqual(1500);
    await recording.attest();
  } finally {
    if (previousOptions === undefined) delete process.env.NODE_OPTIONS; else process.env.NODE_OPTIONS = previousOptions;
    if (previousLatency === undefined) delete process.env.OPENMATES_TUI_LATENCY_EVENTS; else process.env.OPENMATES_TUI_LATENCY_EVENTS = previousLatency;
    removeWorkflowCliHome(home);
  }
});

function sdk(apiUrl: string, home: string, cli: string, program: string, input: unknown = {}): any {
	const modulePath = path.join(path.dirname(cli), 'index.js');
	const source = `
		const {pathToFileURL}=require('node:url');
		(async()=>{
			const {OpenMatesClient,createChatModelPreferences}=await import(pathToFileURL(process.argv[1]).href);
			const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
			const preferences=createChatModelPreferences(client);
			const input=JSON.parse(process.argv[2]);
			${program}
		})().catch(error=>{console.error('Composer model fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, modulePath, JSON.stringify(input)], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 90_000,
	}).trim());
}

function installControlledCatalog(home: string, cli: string): () => void {
	// Matches backend/providers/google.yml and the four public catalog response shapes.
	// The isolated stack has no provider credential; availability is controlled here only.
	const model = {id: 'gemini-3.8-flash', name: 'Gemini 3.8 Flash', provider_id: 'google',
		provider_name: 'Google', description: 'Gemini Flash model for automatic routing and explicit selection.'};
	const skill = {apps: {ai: {skills: [{id: 'ask', models: [model]}]}}};
	const sources = {
		all: skill, available: skill,
		routes: {data: [{id: 'google/gemini-3.8-flash', created: 1788307200,
			openmates: {capability_level: 'high'}}]},
		health: {providers: {google: {status: 'healthy'}}},
	};
	const adapterPath = path.join(home, 'controlled-model-catalog.mjs');
	const modulePath = path.join(path.dirname(cli), 'index.js');
	fs.writeFileSync(adapterPath, `
		import {pathToFileURL} from 'node:url';
		const {OpenMatesClient}=await import(pathToFileURL(${JSON.stringify(modulePath)}).href);
		OpenMatesClient.prototype.getChatModelCatalogSources=async function(){return ${JSON.stringify(sources)};};
	`, {mode: 0o600});
	const previousOptions = process.env.NODE_OPTIONS;
	process.env.NODE_OPTIONS = [previousOptions, `--import=${adapterPath}`].filter(Boolean).join(' ');
	return () => {
		if (previousOptions === undefined) delete process.env.NODE_OPTIONS;
		else process.env.NODE_OPTIONS = previousOptions;
	};
}

function scopedTestInfo(testInfo: any, name: string): any {
	return {
		outputPath: (...parts: string[]) => testInfo.outputPath(name, ...parts),
		attach: (attachment: string, options: unknown) => testInfo.attach(`${name}-${attachment}`, options),
	};
}

function frame(recording: {frame: (name: string) => string[]}, name: string): string {
	return recording.frame(name).join('\n');
}

async function captureWebReference(page: any, testInfo: any): Promise<void> {
	await page.setViewportSize({width: 1280, height: 720});
	await page.goto('/');
	await waitForChatReady(page);
	await startNewChat(page);
	const composer = page.getByTestId('active-chat-container').getByTestId('message-field').last();
	const editor = composer.getByTestId('message-editor');
	await expect(editor).toBeVisible();
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');
	await expect(composer).toHaveAttribute('data-focused', 'true');
	await expect(composer.getByTestId('action-buttons')).toBeVisible();
	const selector = composer.getByTestId('composer-model-selector');
	await expect(selector).toHaveAttribute('aria-label', /Model selection: Auto select/i);
	await selector.click();
	const menu = composer.getByTestId('composer-model-selector-menu');
	await expect(menu.getByTestId('composer-model-auto')).toHaveText('Auto select');
	const provider = menu.getByTestId('composer-model-provider-label').first();
	await expect(provider).toBeVisible();
	const rootPath = testInfo.outputPath('web-reference-model-root-wide.png');
	await page.screenshot({path: rootPath});
	await testInfo.attach('web-reference-model-root-wide', {path: rootPath, contentType: 'image/png'});
	await provider.click();
	await expect(menu.getByTestId('composer-model-row').first()).toBeVisible();
	await expect(menu.getByTestId('composer-model-capability').first()).toHaveAttribute('data-level', /^(low|medium|high|max)$/);
	const providerPath = testInfo.outputPath('web-reference-provider-models-wide.png');
	await page.screenshot({path: providerPath});
	await testInfo.attach('web-reference-provider-models-wide', {path: providerPath, contentType: 'image/png'});
	await page.setViewportSize({width: 390, height: 844});
	await expect(selector.getByTestId('composer-model-selector-label')).toBeHidden();
	const phonePath = testInfo.outputPath('web-reference-provider-models-phone.png');
	await page.screenshot({path: phonePath});
	await testInfo.attach('web-reference-provider-models-phone', {path: phonePath, contentType: 'image/png'});
}

// contract-test: direct surface=cli assertions=ai-model-routing.composer.responsive-actions,ai-model-routing.catalog.capability-recommendation-variants,ai-model-routing.chat-selection.encrypted-user-chat-scope,terminal-pointer.visible-action-parity,terminal-pointer.viewport-coherent,terminal-pointer.lifecycle-selection-safe
test('records provider-first model choice, Auto, details, resize and encrypted per-chat restore in a real terminal',
	async ({page}: {page: any}, testInfo: any) => {
		test.setTimeout(360_000);
		test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e', 'Requires isolated GitHub product stack and real graphical terminal');
		skipWithoutCredentials(test, email, password, otpKey);
		const cli = requireIsolatedCliBuild(); installRecorderDeps();
		const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-composer-model');
		const ids: string[] = [];
		let proofError: unknown;
		let restoreCatalog: (() => void) | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, home, 'TUI_COMPOSER_MODEL_PROOF');
			await captureWebReference(page, testInfo);
			const marker = randomUUID().slice(0, 8);
			const firstDraft = `Composer proof ${marker} keep this draft`;
			const secondDraft = `Composer proof ${marker} other chat`;
			for (const content of [firstDraft, secondDraft]) {
				const draft = await runWorkflowCliJson(apiUrl, home, ['drafts', 'create', content], 'seed encrypted composer draft');
				ids.push(draft.chatId);
				expect(draft.markdown).toBe(content);
				expect(draft.encryptedDraftMd).not.toContain(content);
			}
			restoreCatalog = installControlledCatalog(home, cli);
			const catalog: CatalogEntry[] = sdk(apiUrl, home, cli, `
				const entries=await preferences.catalog();
				process.stdout.write(JSON.stringify(entries.map(({id,name,providerId,providerName,providerBrandName,providerOrder,capability,releaseDate,available})=>
					({id,name,providerId,providerName,providerBrandName,providerOrder,capability,releaseDate,available}))));
			`);
			expect(catalog.map(item => [item.id, item.available])).toEqual([['google/gemini-3.8-flash', true]]);
			const eligible = catalog.filter(item => item.available && item.name && item.providerId && item.id);
			const firstProviderId = [...eligible].sort((left, right) =>
				(left.providerOrder ?? Number.MAX_SAFE_INTEGER) - (right.providerOrder ?? Number.MAX_SAFE_INTEGER))[0]?.providerId;
			const capabilityRank: Record<string, number> = {low: 0, medium: 1, high: 2, max: 3};
			const entry = eligible.filter(item => item.providerId === firstProviderId).sort((left, right) =>
				(right.releaseDate ?? '').localeCompare(left.releaseDate ?? '')
				|| (capabilityRank[right.capability ?? 'low'] - capabilityRank[left.capability ?? 'low'])
				|| left.name.localeCompare(right.name))[0];
			expect(entry, 'Controlled catalog must have the configured healthy selectable model').toBeTruthy();
			const provider = entry!.providerBrandName || entry!.providerName;
			const modelRow = `○ ${entry!.name}${entry!.capability ? ` [${entry!.capability}]` : ''}`;
			const availableNames = eligible.filter(item => item.providerId === entry!.providerId).map(item => item.name);
			const unavailableSameProvider = catalog.find(item => !item.available && item.providerId === entry!.providerId
				&& !availableNames.some(name => name.includes(item.name) || item.name.includes(name)));
			const firstSteps: ProofStep[] = [
				{name: 'home', wait_for: 'DAILY INSPIRATION', hold_ms: 300},
				{name: 'chat-command', text: '/chat ' + ids[0]},
				{name: 'chat-open', key: 'Return', wait_for: 'Model: Auto',
					wait_for_absent: 'Continue where you left off', hold_ms: 500},
				{name: 'picker-open', click: {text: 'Model: Auto'}, wait_for: 'Choose AI model', hold_ms: 300},
				{name: 'provider-open', click: {text: provider}, wait_for: entry!.name, hold_ms: 350},
				{name: 'model-details', click: {text: 'About ' + entry!.name}, wait_for: entry!.name, hold_ms: 350},
				{name: 'detail-back', key: 'Escape', wait_for: 'About ' + entry!.name, hold_ms: 250},
				{name: 'exact-selected', click: {text: modelRow}, wait_for: 'Model: ' + entry!.name,
					wait_for_absent: 'Back to providers', hold_ms: 350},
				{name: 'exact-picker-open', click: {text: 'Model: ' + entry!.name}, wait_for: 'Back to providers', hold_ms: 250},
				{name: 'provider-back', click: {text: 'Back to providers'}, wait_for: 'Auto select', hold_ms: 250},
				{name: 'auto-selected', key: 'Return', wait_for: 'Model: Auto',
					wait_for_absent: 'Choose AI model', hold_ms: 300},
				{name: 'auto-picker-open', click: {text: 'Model: Auto'}, wait_for: 'Choose AI model', hold_ms: 250},
				{name: 'provider-again', click: {text: provider}, wait_for: entry!.name, hold_ms: 250},
				{name: 'exact-again', click: {text: modelRow}, wait_for: 'Model: ' + entry!.name,
					wait_for_absent: 'Back to providers', hold_ms: 350},
				{name: 'narrow', resize: {width: 640, height: 600}, wait_for: 'Model:', hold_ms: 500},
				{name: 'narrow-picker-open', click: {text: 'Model:'}, wait_for: 'Back to providers', hold_ms: 250},
				{name: 'narrow-picker-back', key: 'Escape', wait_for: 'Auto select', hold_ms: 200},
				{name: 'narrow-picker-close', key: 'Escape', wait_for: 'Alt+M model',
				wait_for_absent: 'Choose AI model'},
				{name: 'exit', key: 'ctrl+c'},
			];
			const first = await captureProof(apiUrl, home, cli, firstSteps, choiceContract, scopedTestInfo(testInfo, 'choice'));
			expect(frame(first, 'chat-open')).toContain(firstDraft);
			expect(frame(first, 'picker-open')).toContain('Auto select');
			expect(frame(first, 'provider-open')).toContain(entry!.name);
			if (entry!.capability) expect(frame(first, 'provider-open').toLowerCase()).toContain(entry!.capability.toLowerCase());
			if (unavailableSameProvider) expect(frame(first, 'provider-open')).not.toContain(unavailableSameProvider.name);
			expect(frame(first, 'model-details')).toContain(entry!.name);
			for (const checkpoint of ['exact-selected', 'auto-selected', 'exact-again', 'narrow', 'narrow-picker-close'])
				expect(frame(first, checkpoint)).toContain(firstDraft);
			expect(frame(first, 'auto-selected')).toContain('Model: Auto');
			expect(frame(first, 'exact-again')).toContain(entry!.name);
			expect(first.manifest.input_checkpoints.filter((point: {pointer?: unknown}) => point.pointer).length).toBeGreaterThanOrEqual(5);
			const pointers = first.manifest.input_checkpoints.filter((point: {pointer?: unknown}) => point.pointer);
			const widePointer = pointers.find((point: {name: string}) => point.name === 'picker-open')?.pointer;
			const narrowPointer = pointers.find((point: {name: string}) => point.name === 'narrow-picker-open')?.pointer;
			expect(widePointer?.window_width).toBe(1280);
			expect(narrowPointer?.window_width).toBe(640);
			expect(narrowPointer?.columns).toBeLessThan(widePointer?.columns);
			await first.attest();

			const persisted = sdk(apiUrl, home, cli, `
				const record=await client.getChatModelPreference(input.first);
				const first=await preferences.restore(input.first);
				const other=await preferences.restore(input.other);
				process.stdout.write(JSON.stringify({first,other,encrypted:Boolean(record?.ciphertext),
					containsPlainModel:Boolean(record?.ciphertext?.includes(input.model))}));
			`, {first: ids[0], other: ids[1], model: entry!.id});
			expect(persisted.first.selection).toBe(entry!.id);
			expect(persisted.other.selection).toBe('auto');
			expect(persisted.encrypted).toBe(true);
			expect(persisted.containsPlainModel).toBe(false);

			const restoreSteps: TimedProofStep[] = [
				{name: 'fresh-home', wait_for: 'DAILY INSPIRATION', hold_ms: 300},
				{name: 'first-command', text: '/chat ' + ids[0]},
				{name: 'exact-restored', key: 'Return', wait_for: 'Model: ' + entry!.name, wait_for_absent: 'Loading chat…', hold_ms: 600},
				{name: 'clear-local-composer', key: 'ctrl+u', hold_ms: 150},
				{name: 'other-command', text: '/chat ' + ids[1]},
				{name: 'other-chat', key: 'Return', wait_for: 'Model: Auto', wait_for_absent: 'Loading chat…',
					wait_timeout_ms: 30_000, hold_ms: 600},
				{name: 'exit', key: 'ctrl+c'},
			];
			const restored = await captureProof(apiUrl, home, cli, restoreSteps, restoreContract, scopedTestInfo(testInfo, 'restore'));
			expect(frame(restored, 'exact-restored')).toContain(firstDraft);
			expect(frame(restored, 'exact-restored')).toContain('Model: ' + entry!.name);
			expect(frame(restored, 'other-chat')).toContain('Model: Auto');
			expect(frame(restored, 'other-chat')).toContain(secondDraft);
			await restored.attest();
		} catch (error) { proofError = error; }
		const cleanupErrors: unknown[] = [];
		for (const id of ids) {
			try {
				sdk(apiUrl, home, cli, `await preferences.select(input.id,'auto');
					await preferences.flushPending(input.id);process.stdout.write(JSON.stringify({ok:true}));`, {id});
			} catch (error) { cleanupErrors.push(error); }
			try { await runWorkflowCliJson(apiUrl, home, ['drafts', 'clear', id], 'clear proof draft'); }
			catch (error) { cleanupErrors.push(error); }
		}
		restoreCatalog?.();
		removeWorkflowCliHome(home);
		if (cleanupErrors.length) throw new AggregateError(proofError ? [proofError, ...cleanupErrors] : cleanupErrors,
			'Composer model proof cleanup failed');
		if (proofError) throw proofError;
	});
