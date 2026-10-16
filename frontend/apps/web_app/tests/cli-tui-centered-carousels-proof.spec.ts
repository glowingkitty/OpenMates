/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';
const {test, expect, email, password, otpKey, centeredCarouselProofContract, captureProof, installRecorderDeps, seedWorkspace, cleanupWorkspace, newFixture, requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, skipWithoutCredentials} = require('./cli-tui-proof-helpers');

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,apps.discovery.public-catalog
test('records centered chat and app containers without an outer terminal border', async ({page}: {page: any}, testInfo: any) => {
	test.setTimeout(240_000);
	skipWithoutCredentials(test, email, password, otpKey);
	const candidateCli = requireIsolatedCliBuild();
	installRecorderDeps();
	const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-centered-carousels'), fixture = newFixture();
	try {
		await seedWorkspace(page, apiUrl, home, fixture, true);
		const steps: ProofStep[] = [
			{name: 'initial-centered', wait_for: 'Chat 1 of 5', hold_ms: 1000},
			{name: 'chat-second', key: 'Right', wait_for: 'Chat 2 of 5', hold_ms: 400},
			{name: 'chat-third', key: 'Right', wait_for: 'Chat 3 of 5', hold_ms: 300},
			{name: 'chat-fourth', key: 'Right', wait_for: 'Chat 4 of 5', hold_ms: 1000},
			{name: 'chat-open', key: 'Return', wait_for: 'Draft', hold_ms: 1000},
			{name: 'chat-sidebar', key: 'ctrl+b', wait_for: '+ New chat', hold_ms: 600},
			{name: 'chat-sidebar-close', key: 'ctrl+b', hold_ms: 500},
			{name: 'clear-proof-draft', key: 'ctrl+u'},
			{name: 'apps-command', text: '/apps'},
			{name: 'apps-home', key: 'Return', wait_for: 'App 1 of 6', hold_ms: 1000},
			{name: 'app-second', key: 'Right', wait_for: 'App 2 of 6', hold_ms: 500},
			{name: 'app-third', key: 'Right', wait_for: 'App 3 of 6', hold_ms: 1000},
			{name: 'app-open', key: 'Return', wait_for: 'APP  /  HEALTH', hold_ms: 1000},
			{name: 'exit-command', text: '/exit'},
			{name: 'exit', key: 'Return'}
		];
		const recording = await captureProof(apiUrl, home, candidateCli, steps, centeredCarouselProofContract, testInfo);
		expect(recording.through('initial-centered')).toContain('Chat 1 of 5');
		expect(recording.through('initial-centered')).toContain('DAILY INSPIRATION');
		expect(recording.segment('chat-fourth', 'chat-third')).toContain('Chat 4 of 5');
		expect(recording.segment('chat-open', 'chat-fourth')).toMatch(/Plan a weekend|Review a project|Learn a concept|Organize a trip|Write a story/);
		expect(recording.segment('apps-home', 'apps-command')).toContain('App 1 of 6');
		expect(recording.segment('apps-home', 'apps-command')).toContain('←/→ choose app');
		expect(recording.segment('app-third', 'app-second')).toContain('App 3 of 6');
		expect(recording.segment('app-third', 'app-second')).toContain('Health');
		expect(recording.segment('app-open', 'app-third')).toContain('APP  /  HEALTH');
		expect(recording.segment('app-open', 'app-third')).toContain('[Skills]');
		const chatRows = recording.frame('chat-open'), appRows = recording.frame('app-open');
		const input = chatRows.find((row: string) => /^\s+╭─+╮\s+$/.test(row));
		expect(input).toBeTruthy();
		const left = input.indexOf('╭'), right = input.length - input.indexOf('╮') - 1;
		expect(left).toBeGreaterThan(2);
		expect(Math.abs(left - right)).toBeLessThanOrEqual(1);
		expect(input.indexOf('╮') - left + 1).toBe(100);
		expect(chatRows.find((row: string) => row.includes('What would you like to work on?')).indexOf('What')).toBe(left + 2);
    const appHeader=appRows.find((row: string)=>row.includes('APP WORKSPACE'));
    const appLeft=appHeader.indexOf('╭'),appRight=appHeader.length-appHeader.indexOf('╮')-1;
    expect(appLeft).toBeGreaterThanOrEqual(2);
    expect(Math.abs(appLeft-appRight)).toBeLessThanOrEqual(1);
    expect(appHeader.indexOf('╮')-appLeft+1).toBeGreaterThanOrEqual(100);
    expect(appRows.find((row: string) => row.includes('[Skills]')).indexOf('1 [Skills]')).toBe(appLeft + 1);
		for (const checkpoint of ['initial-centered', 'chat-open', 'chat-sidebar', 'app-open']) {
			const rows = recording.frame(checkpoint);
			expect(rows.every((row: string) => row.startsWith(' ') && row.endsWith(' '))).toBe(true);
			if (checkpoint === 'chat-sidebar') {
				const border = rows.find((row: string) => /^\s+╭─+╮\s+$/.test(row));
				expect(border.indexOf('╭')).toBeGreaterThan(left);
				expect(rows.join('\n')).toContain('+ New chat');
			}
		}
		await recording.attest();
	} finally {
		await cleanupWorkspace(apiUrl, home, fixture);
	}
});
