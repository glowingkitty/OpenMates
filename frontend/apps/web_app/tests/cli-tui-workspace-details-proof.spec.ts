/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';
const {test, expect, email, password, otpKey, EXAMPLE_SLUG, detailProofContract, captureProof, installRecorderDeps, seedEncryptedAppsResult, seedWorkspace, cleanupWorkspace, newFixture, requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, runWorkflowCliJson, skipWithoutCredentials} = require('./cli-tui-proof-helpers');
// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,projects.surface.semantic-parity,tasks.surface.semantic-parity,workflows.surface.semantic-parity
test('records real terminal Project, Workflow, Apps skill, and encrypted result details', async ({page}: {page: any}, testInfo: any) => {
	test.setTimeout(240_000);
	skipWithoutCredentials(test, email, password, otpKey);
	const candidateCli = requireIsolatedCliBuild();
	installRecorderDeps();
	const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-proof-details'), fixture = newFixture();
	try {
		await seedWorkspace(page, apiUrl, home, fixture, false);
		const savedResultId = seedEncryptedAppsResult(apiUrl, home, candidateCli);
		const steps: ProofStep[] = [
			{name: 'initial-closed', wait_for: 'DAILY INSPIRATION', hold_ms: 350},
			{name: 'project-command', text: '/project ' + fixture.projectId},
			{name: 'project-detail', key: 'Return', wait_for: 'PROJECT WORKSPACE', hold_ms: 900},
			{name: 'project-files-tab', text: '2', wait_for: '[FILES]', hold_ms: 250},
			{name: 'project-tasks-tab', text: '3', wait_for: fixture.taskTitle, hold_ms: 250},
			{name: 'workflow-command', text: '/workflow ' + fixture.workflowId},
			{name: 'workflow-detail', key: 'Return', wait_for: 'Template · g', hold_ms: 500},
			{name: 'workflow-expand', key: 'Return', wait_for: 'Step details', hold_ms: 300},
			{name: 'workflow-editor', text: 'e', wait_for: 'Editing title:', hold_ms: 850},
			{name: 'workflow-editor-cancel', key: 'Escape', wait_for: 'Enter closes details', hold_ms: 650},
			{name: 'workflow-runs-tab', text: 'r', wait_for: 'No runs yet.', hold_ms: 250},
			{name: 'workflow-template-tab', text: 'g', wait_for: 'Template graph', hold_ms: 200},
			{name: 'apps-command', text: '/apps'},
			{name: 'apps-home', key: 'Return', wait_for: 'Browse websites', hold_ms: 300},
			{name: 'app-command', text: '/app web'},
			{name: 'app-detail', key: 'Return', wait_for: 'Which app skill do you want to use?', hold_ms: 650},
			{name: 'app-skill-command', text: '/app-skill web/search'},
			{name: 'app-skill-detail', key: 'Return', wait_for: 'Use this skill manually', hold_ms: 450},
			{name: 'app-run-command', text: '/app-run'},
			{name: 'app-skill-form', key: 'Return', wait_for: 'Ctrl+S saves.', hold_ms: 850},
			{name: 'app-skill-cancel', key: 'Escape', wait_for: 'Use this skill manually', hold_ms: 650},
			{name: 'app-results-command', text: '/app-results'},
			{name: 'app-results', key: 'Return', wait_for: savedResultId.slice(0, 8), hold_ms: 500},
			{name: 'app-result-command', text: '/app-result ' + savedResultId},
			{name: 'app-result', key: 'Return', wait_for: 'Terminal proof saved result', hold_ms: 900},
			{name: 'example-command', text: '/example ' + EXAMPLE_SLUG},
			{name: 'example-open', key: 'Return', wait_for: 'General Knowledge', hold_ms: 1000},
			{name: 'tasks-command', text: '/tasks'},
			{name: 'tasks-list', key: 'Return', wait_for: fixture.taskTitle, hold_ms: 350},
			{name: 'tasks-search-command', text: '/search ' + fixture.taskTitle},
			{name: 'tasks-search', key: 'Return', wait_for: fixture.taskTitle},
			{name: 'tasks-inspiration-focus', key: 'Tab', wait_for: 'Enter open'},
			{name: 'tasks-content-focus', key: 'Tab', hold_ms: 100},
			{name: 'task-select', key: 'Return', wait_for: 'Description', hold_ms: 200},
			{name: 'task-edit-open', text: 'e', wait_for: 'Ctrl+S saves'},
			{name: 'task-edit-cancel-append', text: ' cancelled'},
			{name: 'task-edit-cancel', key: 'Escape', wait_for: 'Actions'},
			{name: 'task-edit-reopen', text: 'e', wait_for: 'Ctrl+S saves'},
			{name: 'task-edit-save-append', text: ' saved'},
			{name: 'task-edit-save', key: 'ctrl+s', wait_for: 'Task saved.', hold_ms: 250},
			{name: 'exit-command', text: '/exit'},
			{name: 'exit', key: 'Return'}
		];
		const recording = await captureProof(apiUrl, home, candidateCli, steps, detailProofContract, testInfo);
		expect(recording.through('initial-closed')).toContain('DAILY INSPIRATION');
		expect(recording.through('initial-closed')).not.toContain('Recent chats');
		expect(recording.segment('project-detail', 'project-command')).toContain(fixture.projectName);
		expect(recording.segment('project-detail', 'project-command')).toContain('PROJECT WORKSPACE');
		for (const tab of ['OVERVIEW', 'Files', 'Tasks']) expect(recording.segment('project-detail', 'project-command')).toContain(tab);
		expect(recording.segment('project-files-tab', 'project-detail')).toContain('[FILES]');
		expect(recording.segment('project-tasks-tab', 'project-files-tab')).toContain(fixture.taskTitle);
		expect(recording.segment('task-edit-save', 'task-edit-save-append')).toContain(fixture.taskTitle + ' saved');
		expect(recording.segment('workflow-detail', 'workflow-command')).toContain(fixture.workflowTitle);
		expect(recording.segment('workflow-expand', 'workflow-detail')).toContain('Step details');
		expect(recording.segment('workflow-editor', 'workflow-expand')).toContain('Editing title:');
		expect(recording.segment('workflow-editor-cancel', 'workflow-editor')).not.toContain('Editing title:');
		expect(recording.segment('workflow-runs-tab', 'workflow-editor-cancel')).toContain('No runs yet.');
		expect(recording.segment('workflow-template-tab', 'workflow-runs-tab')).toContain('Template graph');
		expect(recording.segment('app-detail', 'app-command')).toContain('Which app skill do you want to use?');
		expect(recording.segment('app-skill-detail', 'app-skill-command')).toContain('Use this skill manually');
		expect(recording.segment('app-skill-form', 'app-run-command')).toContain('query *');
		expect(recording.segment('app-skill-form', 'app-run-command')).toContain('Ctrl+S saves.');
		expect(recording.segment('app-skill-cancel', 'app-skill-form')).toContain('Use this skill manually');
		expect(recording.segment('app-results', 'app-results-command')).toContain(savedResultId.slice(0, 8));
		expect(recording.segment('app-result', 'app-result-command')).toContain('Terminal proof saved result');
		expect(recording.segment('example-open', 'example-command')).toContain('General Knowledge');
		expect(recording.segment('example-open', 'example-command')).toContain('web/search');
		expect(recording.segment('example-open', 'example-command')).not.toContain('"type": "app_skill_use"');
		expect(recording.transcript.includes('\x1b[38;2;222;30;102m') || recording.transcript.includes('\x1b[48;2;222;30;102m')).toBe(true);
		const persistedTask = (await runWorkflowCliJson(apiUrl, home, ['tasks', 'show', fixture.taskId!], 'verify TUI task edit')).task;
		expect(persistedTask.title).toBe(fixture.taskTitle + ' saved');
		await recording.attest();
	} finally {
		await cleanupWorkspace(apiUrl, home, fixture);
	}
});
