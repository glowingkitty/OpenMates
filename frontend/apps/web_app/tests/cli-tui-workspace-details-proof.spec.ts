/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';
const {test, expect, email, password, otpKey, EXAMPLE_SLUG, detailProofContract, captureProof, installRecorderDeps, seedEncryptedAppsResult, seedWorkspace, cleanupWorkspace, newFixture, requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, runWorkflowCliJson, skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {writeWorkflowYaml} = require('./helpers/workflow-cli-e2e-helpers');
const {execFileSync} = require('node:child_process');
const {randomUUID} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '../../../..');
const COMPOSE = path.join(ROOT, 'test-results/ci-private/compose.json');

/** Persist a real encrypted, owner-scoped run without relying on an unrelated worker queue. */
function seedRetainedWorkflowRun(userId: string, workflowId: string): {id: string; version_id: string; status: string} {
	expect(fs.existsSync(COMPOSE), 'Requires the disposable isolated CI compose').toBe(true);
	const program = `
import asyncio,json,logging,os,sys,time,uuid
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED') == '1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.workflow_models import WorkflowNodeRun,WorkflowRunDetail
from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeService
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository,WorkflowService
async def main():
    data=json.load(sys.stdin)
    cache=CacheService(); directus=DirectusService(cache_service=cache)
    repository=DirectusWorkflowRepository(); service=WorkflowService(repository=repository)
    try:
        user_id=data['userId']; workflow_id=data['workflowId']
        workflow=service.get_workflow(workflow_id,user_id)
        assert not workflow.enabled, 'Fixture workflow must stay inactive'
        assert {node.id for node in workflow.graph.nodes} == {'trigger','gate','unused_notification'}
        accepted=await WorkflowRuntimeService(directus).execute('accept_manual_run',{
            'workflow_id':workflow_id,'hashed_user_id':repository.workflow_owner_hash(user_id),
            'trigger_type':'test','idempotency_key':workflow_id+'-terminal-proof'})
        assert accepted['status']=='queued' and accepted['version_id']==workflow.current_version_id
        run_id=accepted['run_id']; now=int(time.time())
        nodes={node.id:node for node in workflow.graph.nodes}
        node_runs=[WorkflowNodeRun(id=str(uuid.uuid4()),run_id=run_id,workflow_id=workflow_id,
            node_id=node_id,node_type=nodes[node_id].type,status='completed',started_at=now-1,finished_at=now,
            output_summary=output) for node_id,output in (
                ('trigger',{}),('gate',{'matched':False,'branch':'no'}))]
        saved=service.save_run(user_id,WorkflowRunDetail(id=run_id,workflow_id=workflow_id,
            version_id=accepted['version_id'],trigger_type='test',status='completed',started_at=now-1,
            finished_at=now,node_runs=node_runs))
        assert saved.content_available and [node.node_id for node in saved.node_runs]==['trigger','gate']
        assert any(run.id==run_id for run in service.list_runs(workflow_id,user_id))
        print(json.dumps({'id':saved.id,'version_id':saved.version_id,'status':saved.status.value}))
    finally:
        repository._client.close(); await directus.close(); await cache.close()
asyncio.run(main())
`;
	const output = execFileSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', '-e',
		'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
		cwd: ROOT, input: JSON.stringify({userId, workflowId}), encoding: 'utf8', timeout: 90_000,
	});
	return JSON.parse(output.trim());
}

const offlineProofContract = {
	id: 'cli-tui-workspace-offline-real-terminal', title: 'OpenMates saved terminal workspace offline', surface: 'cli', devices: ['cli-terminal'],
	transcript: [
		{id: 'saved-project', text: 'The saved Project list, detail, and Files reopen while its API is unavailable.', checkpoint: 'offline-project-files', devices: ['cli-terminal']},
		{id: 'saved-tasks', text: 'The saved Tasks board reopens and filters its retained task.', checkpoint: 'offline-tasks-filter', devices: ['cli-terminal']},
		{id: 'saved-workflow', text: 'The saved Workflow, recorded run graph, and Events input schema reopen.', checkpoint: 'offline-event-form', devices: ['cli-terminal']}
	],
	assertions: [
		{id: 'projects.surface.semantic-parity', checkpoint: 'offline-project-files', visual: 'The saved Project and Files open from a persisted snapshot during API failure.', devices: ['cli-terminal']},
		{id: 'tasks.surface.semantic-parity', checkpoint: 'offline-tasks-filter', visual: 'The saved task board and filter work during API failure.', devices: ['cli-terminal']},
		{id: 'workflows.surface.semantic-parity', checkpoint: 'offline-event-form', visual: 'The saved Workflow, retained run version, and typed Events form work during API failure.', devices: ['cli-terminal']}
	],
	tutorial: detailProofContract.tutorial
};
// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,projects.surface.semantic-parity,tasks.surface.semantic-parity,workflows.surface.semantic-parity
test('records real terminal Project, Workflow, Apps skill, and encrypted result details', async ({page}: {page: any}, testInfo: any) => {
	test.setTimeout(300_000);
	skipWithoutCredentials(test, email, password, otpKey);
	const candidateCli = requireIsolatedCliBuild();
	installRecorderDeps();
	const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-proof-details'), fixture = newFixture();
	const tag = randomUUID().slice(0, 6);
	fixture.projectName = 'Proof project ' + tag;
	fixture.workflowTitle = 'Proof workflow ' + tag;
	fixture.taskTitle = 'Proof task ' + tag;
	let seededRunId: string | undefined;
	try {
		await seedWorkspace(page, apiUrl, home, fixture, false);
		const noOpYaml = writeWorkflowYaml(home, 'terminal-proof-retained-run.yml', [
			'title: ' + fixture.workflowTitle,
			'description: Disposable retained run for terminal proof.',
			'start_when:', '  schedule:', '    type: once', '    at: "2036-01-01T00:00:00Z"', 'steps:',
			'  - id: gate', '    if:', '      left: 0', '      op: eq', '      right: 1',
			'    if_true:', '      - id: unused_notification', '        send_notification:',
			'          title: Disposable terminal proof',
			'          body: This false branch must never send a notification.',
			'    if_false: []'
		].join('\n'));
		const noOpUpdate = await runWorkflowCliJson(apiUrl, home, ['workflows', 'update', fixture.workflowId!, '--file', noOpYaml], 'prepare disposable workflow run');
		expect(noOpUpdate.validation.enable_ready, JSON.stringify(noOpUpdate.validation.diagnostics)).toBe(true);
		const owner = await runWorkflowCliJson(apiUrl, home, ['whoami'], 'identify proof workflow owner');
		const ownerId = owner.id || owner.user_id;
		expect(ownerId).toBeTruthy();
		const seededRun = seedRetainedWorkflowRun(ownerId, fixture.workflowId!);
		seededRunId = seededRun.id;
		const retainedRun = await runWorkflowCliJson(apiUrl, home,
			['workflows', 'run-show', fixture.workflowId!, seededRun.id], 'verify retained workflow run');
		expect(retainedRun.version_id).toBe(seededRun.version_id);
		expect(retainedRun.status).toBe('completed');
		expect(retainedRun.content_available).toBe(true);
		expect(retainedRun.node_runs.map((node: {node_id: string}) => node.node_id)).toEqual(['trigger', 'gate']);
		expect(retainedRun.node_runs.some((node: {node_id: string}) => node.node_id === 'unused_notification')).toBe(false);
		const listedRuns = await runWorkflowCliJson(apiUrl, home, ['workflows', 'runs', fixture.workflowId!], 'verify retained workflow list');
		expect(listedRuns.some((run: {id: string; version_id: string}) => run.id === retainedRun.id && run.version_id === seededRun.version_id)).toBe(true);
		const eventsYaml = writeWorkflowYaml(home, 'terminal-proof-events.yml', [
			'title: ' + fixture.workflowTitle,
			'description: Disposable Events search workflow for terminal proof.',
			'start_when:', '  schedule:', '    type: once', '    at: "2036-01-01T00:00:00Z"',
			'steps:', '  - id: events', '    use_app_skill: events.search', '    input:',
			'      requests:', '        - query: OpenMates meetup Berlin', '          location: Berlin',
			'          count: 3', '          start_date: "2036-01-01"', '          end_date: "2036-01-02"',
			'          providers:', '            - Meetup'
		].join('\n'));
		await runWorkflowCliJson(apiUrl, home, ['workflows', 'update', fixture.workflowId!, '--file', eventsYaml], 'prepare Events search editor proof');
		const savedResultId = seedEncryptedAppsResult(apiUrl, home, candidateCli);
		const steps: ProofStep[] = [
			{name: 'initial-closed', wait_for: 'DAILY INSPIRATION', hold_ms: 350},
			{name: 'projects-command', text: '/projects'},
			{name: 'projects-list', key: 'Return', wait_for: fixture.projectName, hold_ms: 250},
			{name: 'project-command', text: '/project ' + fixture.projectId},
			{name: 'project-detail', key: 'Return', wait_for: '[Overview · 1]', hold_ms: 900},
			{name: 'project-files-tab', text: '2', wait_for: '[Files · 2]', hold_ms: 250},
			{name: 'project-tasks-tab', text: '3', wait_for: fixture.taskTitle, hold_ms: 250},
			{name: 'workflows-command', text: '/workflows'},
			{name: 'workflows-list', key: 'Return', wait_for: fixture.workflowTitle, hold_ms: 250},
			{name: 'workflow-command', text: '/workflow ' + fixture.workflowId},
			{name: 'workflow-detail', key: 'Return', wait_for: 'Template · g', hold_ms: 500},
			{name: 'workflow-expand', key: 'Return', wait_for: 'Step details', hold_ms: 300},
			{name: 'workflow-editor', text: 'e', wait_for: 'Editing title:', hold_ms: 850},
			{name: 'workflow-editor-cancel', key: 'Escape', wait_for: 'Enter closes details', hold_ms: 650},
			{name: 'workflow-event-selected', key: 'Down', wait_for: 'Use app skill', hold_ms: 350},
			{name: 'workflow-event-form', text: 'E', wait_for: 'requests 1 / query', hold_ms: 450},
			{name: 'workflow-field-tabs-to-start-date', key: 'Tab', repeat: 8},
			{name: 'workflow-event-date', key: 'Tab', wait_for: 'requests 1 / end date', hold_ms: 350},
			{name: 'workflow-field-tabs-to-provider', key: 'Tab', repeat: 5},
			{name: 'workflow-event-providers', key: 'Tab', wait_for: 'requests 1 / providers 1', hold_ms: 350},
			{name: 'workflow-event-form-cancel', key: 'Escape', wait_for: 'Template graph', hold_ms: 300},
			{name: 'workflow-runs-tab', text: 'r', wait_for: 'Selected run ' + retainedRun.id, hold_ms: 500},
			{name: 'workflow-run-graph', key: 'Home', wait_for: 'Run graph', hold_ms: 300},
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
			{name: 'tasks-composer-focus', key: 'Tab', wait_for: 'Ctrl+O explore'},
			{name: 'tasks-inspiration-focus', key: 'Tab', wait_for: 'Enter open'},
			{name: 'tasks-navigation-focus', key: 'Tab', wait_for: '←/→ workspace'},
			{name: 'tasks-content-focus', key: 'Tab', wait_for: '↑/↓ task'},
			{name: 'tasks-ctrl-g-navigation', key: 'ctrl+g', wait_for: 'Ctrl+G navigation', hold_ms: 350},
			{name: 'tasks-navigation-escape', key: 'Escape', wait_for: '↑/↓ task'},
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
		const bytes = Buffer.from(recording.transcript, 'utf8');
		const checkpointOffset = (name: string) => {
			const checkpoint = recording.manifest.input_checkpoints.find((item: {name: string}) => item.name === name);
			expect(checkpoint, `Missing real terminal checkpoint ${name}`).toBeTruthy();
			return checkpoint.transcript_offset as number;
		};
		const rawSegment = (name: string, prior: string) => bytes.subarray(checkpointOffset(prior), checkpointOffset(name)).toString('utf8');
		expect(recording.through('initial-closed')).toContain('DAILY INSPIRATION');
		expect(recording.through('initial-closed')).not.toContain('Recent chats');
		const projectFrame = recording.frame('project-detail');
		const projectTitleRow = projectFrame.find((row: string) => row.includes(fixture.projectName));
		const projectTabsRow = projectFrame.find((row: string) => row.includes('[Overview · 1]'));
		expect(projectTitleRow).toBeTruthy();
		expect(projectFrame.some((row: string) => row.trim() === 'Project')).toBe(true);
		expect(projectFrame.join('\n')).toContain('A disposable terminal Project with files and tasks.');
		expect(projectTabsRow).toContain('Files · 2');
		expect(projectTabsRow).toContain('Tasks · 3');
		expect(projectTabsRow).not.toContain('Embeds');
		expect(projectTitleRow!.indexOf(fixture.projectName)).toBeGreaterThan(20);
		expect(Math.abs(projectTitleRow!.indexOf(fixture.projectName) - projectTabsRow!.indexOf('[Overview · 1]'))).toBeLessThan(22);
		expect(projectFrame.some((row: string) => row.includes('Started'))).toBe(true);
		expect(rawSegment('project-detail', 'project-command')).toContain('\x1b[48;2;0;91;165m');
		expect(recording.segment('project-files-tab', 'project-detail')).toContain('[Files · 2]');
		expect(recording.segment('project-tasks-tab', 'project-files-tab')).toContain(fixture.taskTitle);
		expect(recording.segment('task-edit-save', 'task-edit-save-append')).toContain(fixture.taskTitle + ' saved');
		expect(recording.segment('workflow-detail', 'workflow-command')).toContain(fixture.workflowTitle);
		expect(recording.frame('workflow-detail').some((row: string) => row.includes('Workflow on') || row.includes('Workflow off'))).toBe(true);
		expect(rawSegment('workflow-detail', 'workflow-command')).toContain('\x1b[48;2;222;30;102m');
		expect(rawSegment('workflow-detail', 'workflow-command')).toContain('\x1b[48;2;72;103;205m');
		expect(recording.segment('workflow-expand', 'workflow-detail')).toContain('Step details');
		expect(recording.segment('workflow-editor', 'workflow-expand')).toContain('Editing title:');
		expect(recording.segment('workflow-editor-cancel', 'workflow-editor')).not.toContain('Editing title:');
		expect(recording.frame('workflow-event-selected').join('\n')).toContain('Use app skill');
		expect(rawSegment('workflow-event-selected', 'workflow-editor-cancel')).toContain('\x1b[48;2;162;0;0m');
		expect(recording.segment('workflow-event-form', 'workflow-event-selected')).toContain('requests 1 / query');
		const eventFields = recording.segment('workflow-event-providers', 'workflow-event-form');
		for (const field of ['location', 'count', 'start date', 'end date', 'providers 1'])
			expect(eventFields).toContain('requests 1 / ' + field);
		expect(recording.frame('workflow-event-date').join('\n')).toContain('requests 1 / end date');
		expect(recording.frame('workflow-event-providers').join('\n')).toContain('requests 1 / providers 1');
		expect(recording.segment('workflow-runs-tab', 'workflow-event-form-cancel')).toContain('Selected run ' + retainedRun.id);
		expect(recording.frame('workflow-run-graph').join('\n')).toContain('Run graph');
		expect(recording.frame('workflow-run-graph').join('\n')).toContain('completed');
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
		const tasksFrame = recording.frame('tasks-list').join('\n');
		for (const status of ['Backlog', 'Todo', 'In progress', 'Blocked', 'Done']) expect(tasksFrame).toContain(status);
		expect(recording.frame('tasks-list').filter((row: string) => row.includes('╔')).length).toBe(1);
		expect(tasksFrame).toContain('› ' + fixture.taskTitle);
		const taskColors = rawSegment('tasks-list', 'tasks-command');
		for (const rgb of ['191;90;242', '50;173;230', '240;160;80', '255;107;107', '48;209;88'])
			expect(taskColors).toContain(`\x1b[1m\x1b[38;2;${rgb}m`);
		expect(taskColors).toContain('\x1b[48;2;38;59;82m');
		const navFrame = recording.frame('tasks-ctrl-g-navigation').join('\n');
		expect(navFrame).toContain('Ctrl+G navigation');
		const navColors = rawSegment('tasks-ctrl-g-navigation', 'tasks-content-focus');
		expect(navColors).toContain('\x1b[38;2;50;173;230m');
		expect(navColors).toContain('\x1b[38;2;128;128;128m');
		const persistedTask = (await runWorkflowCliJson(apiUrl, home, ['tasks', 'show', fixture.taskId!], 'verify TUI task edit')).task;
		expect(persistedTask.title).toBe(fixture.taskTitle + ' saved');
		await recording.attest();

		// Only this second CLI process sees an unavailable API. The paired profile,
		// encrypted snapshot file, account identity, and cleanup API remain intact.
		const preload = path.join(home, 'offline-api-proof.cjs');
		fs.writeFileSync(preload, [
			"const apiOrigin = new URL(process.env.OPENMATES_API_URL).origin;",
			"const liveFetch = globalThis.fetch.bind(globalThis);",
			"globalThis.fetch = (input, init) => {",
			"  const url = typeof input === 'string' || input instanceof URL ? String(input) : input.url;",
			"  if (new URL(url).origin === apiOrigin) return Promise.reject(new TypeError('OFFLINE_PROOF_API_UNAVAILABLE'));",
			"  return liveFetch(input, init);",
			"};"
		].join('\n'), {encoding: 'utf8', mode: 0o600});
		const offlineSteps: ProofStep[] = [
			{name: 'offline-initial', wait_for: 'DAILY INSPIRATION'},
			{name: 'offline-projects-command', text: '/projects'},
			{name: 'offline-projects-list', key: 'Return', wait_for: 'Showing saved Projects. Offline', hold_ms: 300},
			{name: 'offline-project-command', text: '/project ' + fixture.projectId},
			{name: 'offline-project-detail', key: 'Return', wait_for: '[Overview · 1]', hold_ms: 300},
			{name: 'offline-project-files', text: '2', wait_for: '[Files · 2]', hold_ms: 300},
			{name: 'offline-tasks-command', text: '/tasks'},
			{name: 'offline-tasks-list', key: 'Return', wait_for: 'Showing cached tasks. Refresh failed.', hold_ms: 300},
			{name: 'offline-tasks-search-command', text: '/search ' + fixture.taskTitle},
			{name: 'offline-tasks-filter', key: 'Return', wait_for: 'Search: ' + fixture.taskTitle, hold_ms: 300},
			{name: 'offline-workflows-command', text: '/workflows'},
			{name: 'offline-workflows-list', key: 'Return', wait_for: 'Showing cached workflows. Refresh failed.', hold_ms: 300},
			{name: 'offline-workflow-command', text: '/workflow ' + fixture.workflowId},
			{name: 'offline-workflow-detail', key: 'Return', wait_for: 'Showing cached runs. Refresh failed.', hold_ms: 300},
			{name: 'offline-workflow-runs', text: 'r', wait_for: 'Showing cached recorded graph. Refresh failed.', hold_ms: 350},
			{name: 'offline-workflow-template', text: 'g', wait_for: 'Template graph'},
			{name: 'offline-event-select', key: 'Down', wait_for: 'Use app skill'},
			{name: 'offline-event-form', text: 'E', wait_for: 'requests 1 / query', hold_ms: 350},
			{name: 'offline-event-form-cancel', key: 'Escape', wait_for: 'Template graph'},
			{name: 'offline-exit-command', text: '/exit'},
			{name: 'offline-exit', key: 'Return'}
		];
		const offlineInfo = {
			outputPath: (...parts: string[]) => testInfo.outputPath('offline', ...parts),
			attach: (name: string, options: unknown) => testInfo.attach('offline-' + name, options)
		};
		const priorNodeOptions = process.env.NODE_OPTIONS;
		const offlineRecording = await (async (): Promise<Awaited<ReturnType<typeof captureProof>>> => {
			try {
				process.env.NODE_OPTIONS = [priorNodeOptions, `--require=${preload}`].filter(Boolean).join(' ');
				return await captureProof(apiUrl, home, candidateCli, offlineSteps, offlineProofContract, offlineInfo);
			} finally {
				if (priorNodeOptions === undefined) delete process.env.NODE_OPTIONS;
				else process.env.NODE_OPTIONS = priorNodeOptions;
			}
		})();
		expect(offlineRecording.frame('offline-projects-list').join('\n')).toContain(fixture.projectName);
		expect(offlineRecording.frame('offline-project-detail').join('\n')).toContain('[Overview · 1]');
		expect(offlineRecording.frame('offline-project-files').join('\n')).toContain('[Files · 2]');
		expect(offlineRecording.frame('offline-tasks-list').join('\n')).toContain(fixture.taskTitle + ' saved');
		expect(offlineRecording.frame('offline-tasks-filter').join('\n')).toContain('Search: ' + fixture.taskTitle);
		expect(offlineRecording.frame('offline-workflows-list').join('\n')).toContain(fixture.workflowTitle);
		expect(offlineRecording.frame('offline-workflow-detail').join('\n')).toContain('Template graph');
		expect(offlineRecording.frame('offline-workflow-runs').join('\n')).toContain(retainedRun.id);
		expect(offlineRecording.frame('offline-workflow-runs').join('\n')).toContain('Run graph');
		expect(offlineRecording.frame('offline-event-form').join('\n')).toContain('requests 1 / query');
		await offlineRecording.attest();
	} finally {
		try {
			if (seededRunId && fixture.workflowId) await runWorkflowCliJson(apiUrl, home,
				['workflows', 'run-delete', fixture.workflowId, seededRunId, '--yes'], 'delete proof workflow run');
		} finally {
			await cleanupWorkspace(apiUrl, home, fixture);
		}
	}
});
