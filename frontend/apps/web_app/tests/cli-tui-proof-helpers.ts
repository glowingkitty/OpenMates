/* eslint-disable @typescript-eslint/no-require-imports */
/** Real 1280×720 graphical terminal proof of the built OpenMates CLI workspace. */
export {};
import type {Page, TestInfo} from '@playwright/test';

const {test, expect} = require('./helpers/cookie-audit');
const {spawn, spawnSync, execFileSync} = require('node:child_process');
const {createHash, randomUUID} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {getTestAccount} = require('./signup-flow-helpers');
const {skipWithoutCredentials} = require('./helpers/env-guard');
const {
	createWorkflowCliHome, deleteWorkflowQuietly, loginWorkflowCliViaPair,
	removeWorkflowCliHome, runWorkflowCli, runWorkflowCliJson, workflowApiUrl,
	workflowCliEnv, writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const {email, password, otpKey} = getTestAccount();
const EXAMPLE_SLUG = 'gigantic-airplanes-transporting-rocket-parts';
const PROFILE = 'cli-terminal';

const detailProofContract = {
	id: 'cli-tui-workspace-real-terminal',
	title: 'OpenMates terminal workspace',
	surface: 'cli',
	devices: [PROFILE],
	transcript: [
		{id: 'project', text: 'The Project opens with its identity card and Overview, Files, and Tasks tabs.', checkpoint: 'project-detail', devices: [PROFILE]},
		{id: 'workflow', text: 'The workflow graph expands a step in place and opens its editor.', checkpoint: 'workflow-editor', devices: [PROFILE]},
		{id: 'app', text: 'The app shows its skill catalog, and the selected skill opens a typed input form.', checkpoint: 'app-skill-form', devices: [PROFILE]},
		{id: 'result', text: 'An encrypted saved Apps result opens from the app history.', checkpoint: 'app-result', devices: [PROFILE]},
		{id: 'example', text: 'A public example chat opens with its General Knowledge category color and transcript header.', checkpoint: 'example-open', devices: [PROFILE]}
	],
	assertions: [
		{id: 'cli.tui.project-tabs', checkpoint: 'project-detail', visual: 'The seeded Project detail shows its identity and Overview, Files, and Tasks cards.', devices: [PROFILE]},
		{id: 'cli.tui.workflow-tabs', checkpoint: 'workflow-editor', visual: 'The saved Workflow shows Template and Runs, with a step expanded in place and an edit control.', devices: [PROFILE]},
		{id: 'cli.tui.app-skill', checkpoint: 'app-skill-form', visual: 'The selected app skill shows its input schema and opens a typed form without execution.', devices: [PROFILE]},
		{id: 'cli.tui.app-results', checkpoint: 'app-result', visual: 'The app history opens a client-encrypted saved result.', devices: [PROFILE]},
		{id: 'cli.tui.example-category', checkpoint: 'example-open', visual: 'The example chat header displays General Knowledge with its web category color.', devices: [PROFILE]}
	],
	tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000}
};

const homeProofContract = {
	id: 'cli-tui-homes-real-terminal',
	title: 'OpenMates terminal workspace homes',
	surface: 'cli',
	devices: [PROFILE],
	transcript: [
		{id: 'chats', text: 'Chats opens with Daily Inspiration, a personal greeting, horizontal keyboard-selected recent chats, and a sidebar revealed by Ctrl+B.', checkpoint: 'sidebar-open', devices: [PROFILE]},
		{id: 'chat-navigation', text: 'Left and Right move through horizontal previews, Enter opens the chosen chat, and Home and End scroll the page reliably.', checkpoint: 'chat-open', devices: [PROFILE]},
		{id: 'tasks', text: 'Tasks keeps the inspiration banner above a five-status board with the seeded task.', checkpoint: 'tasks-home', devices: [PROFILE]},
		{id: 'projects', text: 'Projects shows its greeting and a card for the seeded Project.', checkpoint: 'projects-home', devices: [PROFILE]},
		{id: 'workflows', text: 'Workflows shows the inspiration banner and the saved workflow card.', checkpoint: 'workflows-home', devices: [PROFILE]},
		{id: 'apps', text: 'Apps opens to its greeting and a browsable catalog of app cards.', checkpoint: 'apps-home', devices: [PROFILE]}
	],
	assertions: [
		{id: 'cli.tui.chat-carousel.open', checkpoint: 'chat-open', visual: 'Enter opens the fourth keyboard-selected preview with its encrypted draft restored, and its header has one solid color.', devices: [PROFILE]},
		{id: 'cli.tui.chat-carousel.scroll', checkpoint: 'apps-scroll-top', visual: 'The fitted Apps home preserves Daily Inspiration and the selected centered app when Home and End reach its viewport bounds.', devices: [PROFILE]},
		{id: 'cli.tui.sidebar.toggle', checkpoint: 'sidebar-open', visual: 'Chats shows Daily Inspiration, a greeting, horizontal recent chat previews, and the opened sidebar.', devices: [PROFILE]},
		{id: 'cli.tui.tasks-board', checkpoint: 'tasks-home', visual: 'The Tasks home shows Daily Inspiration and all five status columns with the seeded task.', devices: [PROFILE]},
		{id: 'cli.tui.projects-home', checkpoint: 'projects-home', visual: 'The Projects home shows its greeting and the seeded Project card.', devices: [PROFILE]},
		{id: 'cli.tui.workflows-home', checkpoint: 'workflows-home', visual: 'The Workflows home shows its greeting and the saved workflow card.', devices: [PROFILE]},
		{id: 'cli.tui.apps-home', checkpoint: 'apps-home', visual: 'The Apps home shows its greeting and app cards from the catalog.', devices: [PROFILE]}
	],
	tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000}
};

function plain(text: string): string {
	// eslint-disable-next-line no-control-regex -- ANSI escape bytes are intentional in terminal transcripts.
	return text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '').replace(/\r/g, '');
}

function sha256(file: string): string {
	return `sha256:${createHash('sha256').update(fs.readFileSync(file)).digest('hex')}`;
}

async function recordInteractiveCli(apiUrl: string, home: string, outputDir: string, inputPlan: string, candidateCli: string): Promise<{code: number | null; stdout: string; stderr: string}> {
	const cliDir = path.dirname(path.dirname(candidateCli));
	const args = [
		path.join(ROOT, 'scripts/cli_video_capture.py'), '--output-dir', outputDir,
		'--target-environment', apiUrl, '--classification', 'cli_tui_workspace',
		'--display-number', String(110 + Number(process.env.PLAYWRIGHT_WORKER_SLOT || '1')),
		'--timeout-seconds', '90', '--input-plan', inputPlan, '--no-response-media',
		'--', 'node', candidateCli
	];
	return new Promise((resolve) => {
		const child = spawn('python3', args, {
			cwd: ROOT,
			env: {...workflowCliEnv(apiUrl, home), NODE_PATH: path.join(cliDir, 'node_modules'), TERM: 'xterm-256color', COLORTERM: 'truecolor'},
			stdio: ['ignore', 'pipe', 'pipe']
		});
		const stdout: string[] = [], stderr: string[] = [];
		child.stdout.on('data', (chunk: Buffer) => stdout.push(chunk.toString()));
		child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk.toString()));
		child.on('close', (code: number | null) => resolve({code, stdout: stdout.join(''), stderr: stderr.join('')}));
	});
}

export type ProofStep = {name: string; text?: string; key?: string; repeat?: number; wheel?: 'up' | 'down'; wait_for?: string; wait_for_absent?: string; hold_ms?: number};
type ProofContract = typeof detailProofContract | typeof homeProofContract;
type CliCheckpoint = {name: string; at_ms: number; transcript_offset: number};
type CliManifest = {
  input_checkpoints: CliCheckpoint[]; capture_kind: string; reconstructed: boolean;
  exit_status: number; width: number; height: number; video_sha256: string; input_plan_sha256: string;
};

async function captureProof(apiUrl: string, home: string, candidateCli: string, steps: ProofStep[], contract: ProofContract, testInfo: TestInfo) {
	const outputDir = testInfo.outputPath('cli-terminal1280x720');
	fs.mkdirSync(outputDir, {recursive: true});
	const inputPlan = testInfo.outputPath('cli-tui-input-plan.json');
	fs.writeFileSync(inputPlan, JSON.stringify({steps}, null, 2));
	const result = await recordInteractiveCli(apiUrl, home, outputDir, inputPlan, candidateCli);
	const manifestPath = path.join(outputDir, 'manifest.json');
	const videoPath = path.join(outputDir, 'raw-terminal.mp4');
	const transcriptPath = path.join(outputDir, 'transcript.txt');
	for (const [name, file, contentType] of [
		['openmates-cli-real-terminal-video', videoPath, 'video/mp4'],
		['openmates-cli-real-terminal-manifest', manifestPath, 'application/json'],
		['openmates-cli-real-terminal-transcript', transcriptPath, 'text/plain'],
		['openmates-cli-real-terminal-events', path.join(outputDir, 'events.jsonl'), 'application/jsonl'],
		['openmates-cli-terminal-input-plan', inputPlan, 'application/json']
	]) if (fs.existsSync(file)) await testInfo.attach(name, {path: file, contentType});
	expect(result.code, 'Interactive recorder exited ' + result.code + ': ' + result.stderr + '\n' + result.stdout).toBe(0);
	const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as CliManifest;
	const transcriptBytes = fs.readFileSync(transcriptPath);
	const transcript = transcriptBytes.toString('utf8');
	const checkpoints = new Map<string, CliCheckpoint>(manifest.input_checkpoints.map((checkpoint) => [checkpoint.name, checkpoint]));
	const checkpoint = (name: string): CliCheckpoint => {
		const value = checkpoints.get(name);
		if (!value) throw new Error(`Missing recorder checkpoint: ${name}`);
		return value;
	};
	const through = (name: string) => plain(transcriptBytes.subarray(0, checkpoint(name).transcript_offset).toString('utf8'));
	const segment = (name: string, prior: string) => plain(transcriptBytes.subarray(checkpoint(prior).transcript_offset, checkpoint(name).transcript_offset).toString('utf8'));
	const frame = (name: string): string[] => {
		const output = transcriptBytes.subarray(0, checkpoint(name).transcript_offset).toString('utf8');
		const end = output.lastIndexOf('\x1b[?2026l'), start = output.lastIndexOf('\x1b[?2026h', end);
		if (start < 0 || end < start) throw new Error(`No complete terminal frame at ${name}`);
		// eslint-disable-next-line no-control-regex -- Inspect actual synchronized terminal row writes.
		const rows = [...output.slice(start + 8, end).matchAll(/\x1b\[(\d+);1H\x1b\[2K([\s\S]*?)(?=\x1b\[\d+;1H|$)/g)];
		if (!rows.length) throw new Error(`No terminal rows at ${name}`);
		return rows.map((row) => plain(row[2]));
	};
	expect(manifest.capture_kind).toBe('real_terminal_screen');
	expect(manifest.reconstructed).toBe(false);
	expect(manifest.exit_status).toBe(0);
	expect([manifest.width, manifest.height]).toEqual([1280, 720]);
	expect(manifest.video_sha256).toBe(sha256(videoPath));
	expect(manifest.input_plan_sha256).toBe(sha256(inputPlan));
	expect(checkpoints.size).toBe(steps.length);
	return {
		manifest, transcript, through, segment, frame,
		async attest() {
			const assertions = contract.assertions.map((assertion) => ({id: assertion.id, status: 'passed', at_ms: checkpoint(assertion.checkpoint).at_ms}));
			const timeline = {
				schema_version: 1, device: PROFILE, contract,
				source_video_path: videoPath, source_video_sha256: manifest.video_sha256,
				events: manifest.input_checkpoints.map((checkpoint) => ({id: checkpoint.name, kind: 'checkpoint', at_ms: checkpoint.at_ms})),
				assertion_results: assertions, checkpoint_frames: []
			};
			await testInfo.attach('openmates-proof-timeline', {body: Buffer.from(JSON.stringify(timeline)), contentType: 'application/vnd.openmates.proof-timeline+json'});
		}
	};
}

function installRecorderDeps(): void {
	execFileSync('sudo', ['apt-get', 'install', '-y', 'zutty', 'fonts-dejavu-core', 'x11-xserver-utils', 'xdotool'],
		{cwd: ROOT, timeout: 120_000, stdio: 'pipe'});
}

function seedEncryptedAppsResult(apiUrl: string, home: string, candidateCli: string): string {
	const dist = path.dirname(candidateCli);
	const script = [
		"import {randomBytes,randomUUID,webcrypto} from 'node:crypto';",
		"import {pathToFileURL} from 'node:url';",
		"const root=process.argv[1];",
		"const {OpenMatesClient}=await import(pathToFileURL(root+'/index.js').href);",
		"async function seal(data,keyBytes){const iv=randomBytes(12);const key=await webcrypto.subtle.importKey('raw',keyBytes,{name:'AES-GCM'},false,['encrypt']);const encrypted=await webcrypto.subtle.encrypt({name:'AES-GCM',iv},key,data);return Buffer.concat([iv,Buffer.from(encrypted)]).toString('base64');}",
		"const encryptBytesWithAesGcm=(bytes,key)=>seal(bytes,key);",
		"const encryptWithAesGcmCombined=(text,key)=>seal(Buffer.from(text,'utf8'),key);",
		"const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});",
		"const owner=await client.whoAmI();const ownerId=owner.id||owner.user_id;",
		"if(!ownerId||client.getActiveTeamId())throw Error('Expected paired Personal account');",
		"const embedId=randomUUID(),key=randomBytes(32);",
		"const content={app_id:'web',skill_id:'search',input:{query:'terminal proof'},results:[{title:'Terminal proof saved result'}],status:'finished',result_count:1,embed_ids:[]};",
		"await client.saveAppsWorkspaceResult({app_id:'web',skill_id:'search',root_embed_id:embedId,expected_user_id:ownerId,linked_embed_ids:[],encrypted_embed_key:await encryptBytesWithAesGcm(key,client.getMasterKeyBytes()),embeds:[{embed_id:embedId,encrypted_type:await encryptWithAesGcmCombined('app_skill_use',key),encrypted_content:await encryptWithAesGcmCombined(JSON.stringify(content),key),status:'finished',embed_ids:[]}]});",
		"const result=await client.getAppsWorkspaceResult(embedId);if(!result)throw Error('Saved Apps result missing');",
		"process.stdout.write(embedId);"
	].join('\n');
	const cliDir = path.dirname(dist);
	const result = spawnSync('node', ['--input-type=module', '-e', script, dist], {
		cwd: ROOT, encoding: 'utf8', timeout: 60_000,
		env: {...workflowCliEnv(apiUrl, home), NODE_PATH: path.join(cliDir, 'node_modules')}
	});
	expect(result.status, 'Seed encrypted Apps result: ' + result.stderr).toBe(0);
	expect(result.stdout.trim()).toMatch(/^[0-9a-f-]{36}$/);
	return result.stdout.trim();
}

type SeededWorkspace = {projectId?: string; taskId?: string; workflowId?: string; draftIds: string[]; projectName: string; taskTitle: string; workflowTitle: string};

async function seedWorkspace(page: Page, apiUrl: string, home: string, fixture: SeededWorkspace, withRecentChats: boolean): Promise<void> {
	await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_TUI_PROOF');
	const project = (await runWorkflowCliJson(apiUrl, home, [
		'projects', 'create', '--name', fixture.projectName, '--description', 'A disposable terminal Project with files and tasks.',
		'--write-policy', 'always_ask'
	], 'create proof project')).project;
	fixture.projectId = project.project_id;
	const task = (await runWorkflowCliJson(apiUrl, home, [
		'tasks', 'create', '--title', fixture.taskTitle, '--assign', 'user', '--project', fixture.projectId!
	], 'create proof task')).task;
	fixture.taskId = task.task_id;
	const yaml = writeWorkflowYaml(home, 'terminal-proof-workflow.yml', [
		'title: ' + fixture.workflowTitle,
		'description: Disposable disabled workflow for terminal proof.',
		'start_when:',
		'  schedule:',
		'    type: once',
		'    at: "2036-01-01T00:00:00Z"',
		'steps:',
		'  - id: note',
		'    send_chat_message:',
		'      title: Terminal proof',
		'      message: This workflow is not executed.'
	].join('\n'));
	const workflow = (await runWorkflowCliJson(apiUrl, home, ['workflows', 'create', '--file', yaml], 'create proof workflow')).workflow;
	fixture.workflowId = workflow.id;
	expect(workflow.enabled).toBe(false);
	if (withRecentChats) {
		for (const label of ['Plan a weekend', 'Review a project', 'Learn a concept', 'Organize a trip', 'Write a story']) {
			const draft = await runWorkflowCliJson(apiUrl, home, ['drafts', 'create', label], 'seed encrypted recent chat');
			fixture.draftIds.push(draft.chatId);
			expect(draft.markdown).toBe(label);
			expect(draft.encryptedDraftMd).not.toContain(label);
		}
		const listed = await runWorkflowCliJson(apiUrl, home, ['drafts', 'list', '--refresh'], 'verify encrypted recent chats');
		for (const id of fixture.draftIds) expect(listed.drafts.some((item: {chatId: string}) => item.chatId === id)).toBe(true);
	}
}

async function cleanupWorkspace(apiUrl: string, home: string, fixture: SeededWorkspace): Promise<void> {
	// Clearing a draft leaves its chat behind; remove only this test's owned chats.
	for (const id of fixture.draftIds) await runWorkflowCliJson(apiUrl, home, ['chats', 'delete', id, '--yes', '--json'], 'delete proof chat');
	if (fixture.workflowId) await deleteWorkflowQuietly(apiUrl, home, fixture.workflowId);
	if (fixture.taskId) await runWorkflowCli(apiUrl, home, ['tasks', 'delete', fixture.taskId, '--confirm', '--json']);
	if (fixture.projectId) await runWorkflowCli(apiUrl, home, ['projects', 'delete', fixture.projectId, '--confirm', fixture.projectId, '--json']);
	removeWorkflowCliHome(home);
}

function newFixture(): SeededWorkspace {
	return {
		draftIds: [], projectName: 'Terminal proof project ' + randomUUID().slice(0, 8),
		taskTitle: 'Proof task ' + randomUUID().slice(0, 8),
		workflowTitle: 'Terminal proof workflow ' + randomUUID().slice(0, 8)
	};
}

function requireIsolatedCliBuild(): string {
	expect(process.env.CI).toBe('true');
	expect(process.env.PLAYWRIGHT_TEST_BASE_URL).toBe('http://localhost:5173');
	const candidateCli = path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');
	expect(fs.existsSync(candidateCli), 'Candidate CLI build missing: ' + candidateCli).toBe(true);
	return candidateCli;
}


const centeredCarouselProofContract = {
	id: 'cli-tui-centered-layout-real-terminal',
	title: 'Centered terminal content and carousels', surface: 'cli', devices: [PROFILE],
	transcript: [
		{id: 'centered-chats', text: 'The newest chat starts centered, with no outer terminal border.', checkpoint: 'chat-fourth', devices: [PROFILE]},
		{id: 'open-chat', text: 'The chosen chat opens with centered header and input containers.', checkpoint: 'chat-open', devices: [PROFILE]},
		{id: 'centered-apps', text: 'Apps uses the same carousel controls and centered page margins.', checkpoint: 'app-open', devices: [PROFILE]}
	],
	assertions: [
		{id: 'cli.tui.chat-carousel.centered', checkpoint: 'chat-fourth', visual: 'The newest chat starts horizontally centered, and the fourth keyboard-selected chat remains centered with neighboring previews visible.', devices: [PROFILE]},
		{id: 'cli.tui.chat-carousel.open', checkpoint: 'chat-open', visual: 'Enter opens the fourth selected chat with its encrypted draft restored.', devices: [PROFILE]},
		{id: 'cli.tui.apps-carousel.centered', checkpoint: 'app-third', visual: 'The first app starts horizontally centered, and Left/Right centers the third app with an App 3 of 6 counter.', devices: [PROFILE]},
		{id: 'cli.tui.apps-carousel.open', checkpoint: 'app-open', visual: 'Enter opens the selected Health app and its Skills tab.', devices: [PROFILE]},
		{id: 'cli.tui.centered-content', checkpoint: 'app-open', visual: 'The open chat header and message input share a centered container; the app page uses the same side margins, and the outer terminal border is absent.', devices: [PROFILE]}
	],
	tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000}
};

module.exports = {test, expect, email, password, otpKey, EXAMPLE_SLUG, detailProofContract, homeProofContract, centeredCarouselProofContract, recordInteractiveCli, captureProof, installRecorderDeps, seedEncryptedAppsResult, seedWorkspace, cleanupWorkspace, newFixture, requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, runWorkflowCliJson, skipWithoutCredentials};
