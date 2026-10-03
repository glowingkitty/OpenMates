/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';
const {test, expect, email, password, otpKey, homeProofContract, captureProof, installRecorderDeps, seedWorkspace, cleanupWorkspace, newFixture, requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, skipWithoutCredentials} = require('./cli-tui-proof-helpers');
// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,workspace-shell.nav.released-surfaces-visible,tasks.surface.semantic-parity,projects.surface.semantic-parity,workflows.surface.semantic-parity
test('records the real terminal Chats, Tasks, Projects, Workflows, and Apps homes', async ({page}: {page: any}, testInfo: any) => {
	test.setTimeout(240_000);
	skipWithoutCredentials(test, email, password, otpKey);
	const candidateCli = requireIsolatedCliBuild();
	installRecorderDeps();
	const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-proof-homes'), fixture = newFixture();
	try {
		await seedWorkspace(page, apiUrl, home, fixture, true);
		const steps: ProofStep[] = [
			{name: 'initial-closed', wait_for: 'Continue where you left off', hold_ms: 350},
			{name: 'inspiration-focus', key: 'ctrl+o', wait_for: 'Enter open', hold_ms: 400},
			{name: 'inspiration-next', key: 'Right', wait_for: 'DAILY INSPIRATION', hold_ms: 550},
			{name: 'composer-focus', key: 'shift+Tab'},
			{name: 'content-focus', key: 'shift+Tab'},
			{name: 'scroll-bottom', key: 'End', wait_for: '/search Search chats', hold_ms: 350},
			{name: 'scroll-top', key: 'Home', wait_for: 'DAILY INSPIRATION', hold_ms: 350},
			{name: 'chat-second', key: 'Right', wait_for: 'Chat 2 of 5', hold_ms: 350},
			{name: 'chat-third', key: 'Right', wait_for: 'Chat 3 of 5', hold_ms: 200},
			{name: 'chat-fourth', key: 'Right', wait_for: 'Chat 4 of 5', hold_ms: 500},
			{name: 'chat-open', key: 'Return', wait_for: 'Draft', hold_ms: 600},
			{name: 'clear-proof-draft', key: 'ctrl+u'},
			{name: 'chats-command', text: '/chats'},
			{name: 'chats-home', key: 'Return', wait_for: 'Chat 1 of 5', hold_ms: 200},
			{name: 'sidebar-open', key: 'ctrl+b', wait_for: '+ New chat', hold_ms: 1000},
			{name: 'sidebar-closed', key: 'ctrl+b', hold_ms: 150},
			{name: 'tasks-command', text: '/tasks'},
			{name: 'tasks-home', key: 'Return', wait_for: fixture.taskTitle, hold_ms: 1000},
			{name: 'tasks-backlog', key: 'Left', wait_for: 'Backlog 1/5', hold_ms: 150},
			{name: 'tasks-todo', key: 'Right', wait_for: 'Todo 2/5', hold_ms: 150},
			{name: 'tasks-in-progress', key: 'Right', wait_for: 'In progress 3/5', hold_ms: 150},
			{name: 'tasks-blocked', key: 'Right', wait_for: 'Blocked 4/5', hold_ms: 150},
			{name: 'tasks-done', key: 'Right', wait_for: 'Done 5/5', hold_ms: 150},
			{name: 'projects-command', text: '/projects'},
			{name: 'projects-home', key: 'Return', wait_for: fixture.projectName, hold_ms: 1000},
			{name: 'workflows-command', text: '/workflows'},
			{name: 'workflows-home', key: 'Return', wait_for: fixture.workflowTitle, hold_ms: 1000},
			{name: 'apps-command', text: '/apps'},
			{name: 'apps-home', key: 'Return', wait_for: 'Browse websites', hold_ms: 1200},
			{name: 'apps-scroll-bottom', key: 'End', wait_for: 'Show all', hold_ms: 350},
			{name: 'apps-scroll-top', key: 'Home', wait_for: 'DAILY INSPIRATION', hold_ms: 500},
			{name: 'exit-command', text: '/exit'},
			{name: 'exit', key: 'Return'}
		];
		const recording = await captureProof(apiUrl, home, candidateCli, steps, homeProofContract, testInfo);
		expect(recording.through('initial-closed')).toContain('DAILY INSPIRATION');
		expect(recording.through('initial-closed')).toMatch(/Hey .+!/);
		expect(recording.through('initial-closed')).toContain('Continue where you left off');
		expect(recording.frame('initial-closed').join('\n')).not.toContain('+ New chat');
		expect(recording.segment('inspiration-focus', 'initial-closed')).toContain('Enter open');
		expect(recording.frame('sidebar-open').some((row: string) => row.indexOf('+ New chat') >= 0 && row.indexOf('+ New chat') < 27)).toBe(true);
		expect(recording.segment('chat-fourth', 'chat-third')).toContain('Chat 4 of 5');
		expect(recording.segment('chat-open', 'chat-fourth')).toMatch(/Plan a weekend|Review a project|Learn a concept|Organize a trip|Write a story/);
		expect(recording.segment('scroll-top', 'scroll-bottom')).toContain('DAILY INSPIRATION');
		expect(recording.segment('apps-scroll-bottom', 'apps-home')).toContain('Show all');
		expect(recording.segment('apps-scroll-bottom', 'apps-home')).toContain('DAILY INSPIRATION');
		expect(recording.segment('apps-scroll-bottom', 'apps-home')).toContain('App 1 of 6');
		expect(recording.segment('apps-scroll-top', 'apps-scroll-bottom')).toContain('DAILY INSPIRATION');
		expect(recording.segment('tasks-home', 'tasks-command')).toContain(fixture.taskTitle);
		expect(recording.segment('tasks-home', 'tasks-command')).toContain('DAILY INSPIRATION');
		for (const status of ['Backlog', 'Todo', 'In progress', 'Blocked', 'Done'])
			expect(recording.segment('tasks-done', 'tasks-command')).toContain(status);
		expect(recording.segment('projects-home', 'projects-command')).toContain(fixture.projectName);
		expect(recording.segment('projects-home', 'projects-command')).toContain('PROJECT');
		expect(recording.segment('workflows-home', 'workflows-command')).toContain(fixture.workflowTitle);
		expect(recording.segment('workflows-home', 'workflows-command')).toContain('DAILY INSPIRATION');
		expect(recording.segment('apps-home', 'apps-command')).toContain('What app do you want to use?');
		expect(recording.segment('apps-home', 'apps-command')).toContain('Web');
		await recording.attest();
	} finally {
		await cleanupWorkspace(apiUrl, home, fixture);
	}
});
