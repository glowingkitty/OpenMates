/* eslint-disable @typescript-eslint/no-require-imports */
/** Browser/terminal parity proof over disposable, client-encrypted sidebar records. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';

const {test, expect, email, password, otpKey, captureProof, installRecorderDeps,
	requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {loginWorkflowCliViaPair, removeWorkflowCliHome, runWorkflowCliJson,
	workflowCliEnv, clearWorkflowCliSyncCache} = require('./helpers/workflow-cli-e2e-helpers');
const {waitForChatReady} = require('./helpers/chat-test-helpers');
const {execFileSync} = require('node:child_process');
const {randomUUID} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../../..');
const COMPOSE = path.join(ROOT, 'test-results/ci-private/compose.json');
const PROFILE = 'cli-terminal';

type ChatRow = {id: string; encrypted_title?: string | null; encrypted_chat_key?: string | null;
	encrypted_draft_md?: string | null; encrypted_draft_preview?: string | null;
	draft_v?: number; pinned?: boolean; is_hidden?: boolean; parent_id?: string | null;
	is_sub_chat?: boolean; timestamp: number; title: string};
type Fixture = {userId: string; rows: ChatRow[]; names: Record<string, string>;
	ids: Record<string, string>; projectId?: string; archivedId?: string};

function sdk(apiUrl: string, home: string, candidateCli: string, program: string, payload: unknown = {}): any {
	const modulePath = path.join(path.dirname(candidateCli), 'index.js');
	expect(fs.existsSync(modulePath), 'Candidate SDK must be built').toBe(true);
	const source = `
		const {pathToFileURL} = require('node:url');
		const {webcrypto,randomUUID,randomBytes,createHash} = require('node:crypto');
		(async () => {
			const {OpenMatesClient} = await import(pathToFileURL(process.argv[1]).href);
			const client = OpenMatesClient.load({apiUrl: process.env.OPENMATES_API_URL});
			const input = JSON.parse(process.argv[2]);
			const encrypt = async (value,key) => {
				const iv=randomBytes(12), cryptoKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
				const bytes=typeof value==='string'?Buffer.from(value):value;
				const encrypted=await webcrypto.subtle.encrypt({name:'AES-GCM',iv},cryptoKey,bytes);
				return Buffer.concat([iv,Buffer.from(encrypted)]).toString('base64');
			};
			${program}
		})().catch(error => { console.error('Sidebar proof SDK fixture failed:', error.message); process.exit(1); });
	`;
	return JSON.parse(execFileSync('node', ['-e', source, modulePath, JSON.stringify(payload)], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 90_000,
	}).trim());
}

function ciphertextFixture(payload: {userId: string; rows: ChatRow[]}, operation: 'seed' | 'cleanup'): void {
	expect(fs.existsSync(COMPOSE), 'Requires disposable coordinator compose').toBe(true);
	const program = `
import asyncio,hashlib,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _chat_list_cache_data_from_metadata,_chat_versions_from_metadata
async def main():
    data=json.load(sys.stdin); cache=CacheService(); directus=DirectusService(cache_service=cache)
    owner=hashlib.sha256(data['userId'].encode()).hexdigest()
    try:
        for row in data['rows']:
            if data['operation']=='seed':
                metadata={k:v for k,v in row.items() if k not in ('timestamp','title','encrypted_draft_md','encrypted_draft_preview','draft_v','is_hidden')}
                metadata.update(hashed_user_id=owner,created_at=row['timestamp'],updated_at=row['timestamp'],
                    last_edited_overall_timestamp=row['timestamp'],messages_v=0,
                    title_v=1 if row.get('encrypted_title') else 0,metadata_v=1,unread_count=0)
                created,_=await directus.chat.create_chat_in_directus(metadata)
                assert created, 'Ciphertext chat seed failed'
                assert await cache.add_chat_to_ids_versions(data['userId'],row['id'],metadata['last_edited_overall_timestamp'])
                assert await cache.set_chat_list_item_data(data['userId'],row['id'],_chat_list_cache_data_from_metadata(metadata))
                assert await cache.set_chat_versions(data['userId'],row['id'],_chat_versions_from_metadata(metadata))
            else:
                metadata=await directus.chat.get_chat_metadata(row['id'])
                if metadata:
                    assert metadata.get('hashed_user_id')==owner, 'Only fixture-owned records may be removed'
                    assert await directus.delete_item('chats',row['id'],admin_required=True), 'Fixture deletion failed'
                    assert not await directus.chat.get_chat_metadata(row['id']), 'Fixture deletion not confirmed'
                await cache.remove_chat_from_ids_versions(data['userId'],row['id'])
        if data['operation']=='cleanup':
            remaining=set(await cache.get_chat_ids_versions(data['userId']))
            assert not remaining.intersection(row['id'] for row in data['rows']), 'Fixture IDs remain cached'
        print('sidebar proof fixture applied')
    finally: await directus.close(); await cache.close()
asyncio.run(main())
`;
	const output = execFileSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', '-e',
		'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
		cwd: ROOT, input: JSON.stringify({...payload, operation}), encoding: 'utf8', timeout: 120_000,
	});
	expect(output.trim()).toBe('sidebar proof fixture applied');
}

function makeCiphertextRows(apiUrl: string, home: string, candidateCli: string): Fixture {
	return sdk(apiUrl, home, candidateCli, `
		const user=await client.whoAmI(), master=client.getMasterKeyBytes();
		if (!user.id || client.getActiveTeamId()) throw Error('Expected paired Personal account');
		const tag=input.tag, todayNoon=Math.floor(new Date().setHours(12,0,0,0)/1000);
		const names={today:'SB '+tag+' today',yesterday:'SB '+tag+' yesterday',week:'SB '+tag+' week',
			month:'SB '+tag+' month',pinned:'SB '+tag+' pinned',draft:'SB '+tag+' draft preview',
			root:'SB '+tag+' project root',deep:'SB '+tag+' deep chat',oldest:'SB '+tag+' oldest history',
			locked:'SB '+tag+' locked hidden'};
		const ids={}, rows=[];
		const add=async (key,title,ageDays,options={}) => {
			const id=randomUUID(), chatKey=randomBytes(32), timestamp=todayNoon-ageDays*86400-(rows.length+1)*13;
			ids[key]=id;
			rows.push({id,title,timestamp,encrypted_title:options.keyless?null:await encrypt(title,chatKey),
				encrypted_chat_key:options.locked?await encrypt(randomBytes(32),randomBytes(32)):
					options.keyless?null:await encrypt(chatKey,master),
				...(options.pinned?{pinned:true}:{}),...(options.hidden?{is_hidden:true}:{}),
				...(options.parent?{parent_id:options.parent,is_sub_chat:true}:{})});
		};
		await add('today',names.today,0);
		await add('yesterday',names.yesterday,1);
		await add('week',names.week,3);
		await add('month',names.month,45);
		await add('pinned',names.pinned,60,{pinned:true});
		await add('draft',names.draft,65,{keyless:true});
		await add('root',names.root,80);
		await add('deep',names.deep,80);
		for(let i=0;i<51;i++) await add('history'+i,'SB '+tag+' history '+String(i).padStart(2,'0'),90+i);
		await add('oldest',names.oldest,200);
		await add('locked',names.locked,0,{locked:true,hidden:true});
		process.stdout.write(JSON.stringify({userId:user.id,rows,names,ids}));
	`, {tag: randomUUID().slice(0, 4)});
}

function addProjectFolders(apiUrl: string, home: string, candidateCli: string, projectId: string,
	fixture: Fixture): {first: string; deep: string} {
	return sdk(apiUrl, home, candidateCli, `
		const detail=await client.getProject(input.projectId,{personal:true});
		const key=await client.decryptProjectKey(detail.project,{personal:true});
		const now=Math.floor(Date.now()/1000), first=randomUUID(), deep=randomUUID();
		for(const [id,parent,name] of [[first,null,input.firstName],[deep,first,input.deepName]])
			await client.createProjectFolder(input.projectId,{folder_id:id,parent_folder_id:parent,
				encrypted_name:await encrypt(name,key),encrypted_sort_key:await encrypt(name.toLowerCase(),key),
				created_at:now,updated_at:now,position:now},{personal:true});
		for(const [chatId,folderId,name] of [[input.rootId,null,input.rootName],[input.deepId,deep,input.deepChatName]])
			await client.createProjectItem(input.projectId,{project_item_id:randomUUID(),folder_id:folderId,
				item_type:'chat',target_id:chatId,target_id_encrypted:await encrypt(chatId,key),
				encrypted_display_name:await encrypt(name,key),created_at:now,updated_at:now,position:now},{personal:true});
		const listed=await client.listProjectItems(input.projectId,{chatOnly:true,personal:true});
		if(listed.items.length!==2||listed.folders.length!==2) throw Error('Nested encrypted Project seed missing');
		process.stdout.write(JSON.stringify({first,deep}));
	`, {projectId, firstName: 'SB immediate folder', deepName: 'SB deep folder',
		rootId: fixture.ids.root, rootName: fixture.names.root,
		deepId: fixture.ids.deep, deepChatName: fixture.names.deep});
}

const proofContract = {
	id: 'cli-tui-chat-sidebar-real-terminal', title: 'OpenMates chat sidebar and nested folders',
	surface: 'cli', devices: [PROFILE],
	transcript: [
		{id: 'startup', text: 'Ctrl+B opens saved chat history and Projects; the Project reveals its encrypted root chat.', checkpoint: 'project-open', devices: [PROFILE]},
		{id: 'deep', text: 'A nested folder opens its saved chat and restores its title.', checkpoint: 'deep-chat-open', devices: [PROFILE]},
		{id: 'history', text: 'Returning to root and pressing End reaches history beyond the first fifty chats.', checkpoint: 'oldest-selected', devices: [PROFILE]},
		{id: 'scroll', text: 'Sidebar wheel input and keyboard focus stay in the sidebar while the main chat remains open.', checkpoint: 'deep-wheel', devices: [PROFILE]},
		{id: 'files', text: 'A Project found by slug opens Files, and Refresh keeps the current folder.', checkpoint: 'files-refreshed', devices: [PROFILE]},
	],
	assertions: [
		{id: 'cli.surface.semantic-parity', checkpoint: 'sidebar-open', visual: 'The real terminal sidebar shows Project roots and date sections for client-encrypted chats.', devices: [PROFILE]},
		{id: 'chat-navigation.projects.nested-readable', checkpoint: 'deep-chat-open', visual: 'A nested Project folder opens its linked saved chat with the Project breadcrumb.', devices: [PROFILE]},
		{id: 'chat-navigation.draft-only.addressable', checkpoint: 'draft-open', visual: 'The keyless encrypted draft opens with its preview and Draft badge.', devices: [PROFILE]},
		{id: 'projects.surface.semantic-parity', checkpoint: 'files-refreshed', visual: 'Slug-only Project search opens the Project and Refresh preserves the current Files folder.', devices: [PROFILE]},
	],
	tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000},
};

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,chat-navigation.projects.nested-readable,chat-navigation.draft-only.addressable
test('records web-matched chat sidebar, nested folders, draft and deep history in the real terminal',
	async ({page}: {page: any}, testInfo: any) => {
		test.setTimeout(300_000);
		test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e', 'Requires isolated GitHub product stack');
		skipWithoutCredentials(test, email, password, otpKey);
		const candidateCli = requireIsolatedCliBuild();
		installRecorderDeps();
		const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-sidebar-proof');
		let fixture: Fixture | undefined, primaryError: unknown, failed = false;
		const projects: string[] = [];
		const cleanupErrors: unknown[] = [];
		try {
			await loginWorkflowCliViaPair(page, apiUrl, home, 'TUI_SIDEBAR_PROOF');
			fixture = makeCiphertextRows(apiUrl, home, candidateCli);
			ciphertextFixture(fixture, 'seed');
			// Pairing may have synced the pre-seed account. Exercise a cold first
			// census consistently, including when Playwright retries this fixture.
			clearWorkflowCliSyncCache(home);
			sdk(apiUrl, home, candidateCli, `
				const draft=await client.saveDraft({chatId:input.id,markdown:'Continue '+input.title,preview:input.title});
				const recovered=await client.getDraft(input.id,true);
				if(!recovered||recovered.markdown!==draft.markdown||recovered.preview!==input.title) throw Error('Encrypted keyless draft did not persist');
				const [sidebar]=await client.getSidebarChats([input.id]);
				if(!sidebar||sidebar.isHiddenCandidate||sidebar.draftPreview!==input.title||!sidebar.hasDraft) throw Error('Linked keyless draft metadata unavailable');
				const census=await client.listChats(Number.MAX_SAFE_INTEGER,1);
				if(!census.chats.some(chat=>chat.id===input.oldestId)) throw Error('Saving a draft suppressed the complete chat census');
				process.stdout.write(JSON.stringify({chatId:draft.chatId}));
			`, {id: fixture.ids.draft, title: fixture.names.draft, oldestId: fixture.ids.oldest});
			const project = (await runWorkflowCliJson(apiUrl, home,
				['projects', 'create', '--name', 'SB nested proof ' + randomUUID().slice(0, 4), '--write-policy', 'always_ask'],
				'create sidebar proof Project')).project;
			fixture.projectId = project.project_id; projects.push(project.project_id);
			const archived = (await runWorkflowCliJson(apiUrl, home,
				['projects', 'create', '--name', 'SB archived proof ' + randomUUID().slice(0, 4), '--write-policy', 'always_ask'],
				'create archived proof Project')).project;
			fixture.archivedId = archived.project_id; projects.push(archived.project_id);
			await runWorkflowCliJson(apiUrl, home, ['projects', 'archive', archived.project_id], 'archive proof Project');
			addProjectFolders(apiUrl, home, candidateCli, project.project_id, fixture);

			await page.goto('/'); await waitForChatReady(page);
			const sidebar = page.getByTestId('activity-history-wrapper');
			const toggle = page.getByTestId('sidebar-toggle');
			if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
			await expect(toggle).toHaveAttribute('aria-expanded', 'true');
			const row = (id: string) => page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${id}"]`);
			await expect(row(fixture.ids.today)).toContainText(fixture.names.today, {timeout: 30_000});
			await expect(row(fixture.ids.yesterday)).toContainText(fixture.names.yesterday);
			await expect(row(fixture.ids.draft)).toContainText(fixture.names.draft);
			await expect(row(fixture.ids.locked)).toHaveCount(0);
			const webIds: string[] = await sidebar.locator('[data-testid="chat-item-wrapper"][data-chat-id]').evaluateAll(
				(elements: Element[]) => elements.map(element => element.getAttribute('data-chat-id') || ''));
			const namedRootIds = [fixture.ids.today, fixture.ids.yesterday, fixture.ids.week,
				fixture.ids.month, fixture.ids.pinned, fixture.ids.draft];
			const fixtureOrder = webIds.filter(id => namedRootIds.includes(id));
			expect(fixtureOrder).toHaveLength(namedRootIds.length);
			expect(fixtureOrder.slice(0, 3)).toEqual([fixture.ids.today, fixture.ids.yesterday, fixture.ids.week]);
			const groups = await sidebar.getByTestId('group-title').allTextContents();
			expect(groups.join(' ')).toMatch(/Today/i);
			expect(groups.join(' ')).toMatch(/Yesterday/i);
			const navigation = sidebar.getByTestId('chat-project-navigation');
			await expect(navigation.getByTestId('chat-project-root').filter({hasText: project.name})).toBeVisible();
			await expect(navigation).not.toContainText(archived.name);
			await navigation.getByTestId('chat-project-root').filter({hasText: project.name}).click();
			await expect(row(fixture.ids.root)).toContainText(fixture.names.root);
			await navigation.getByTestId('chat-project-folder').filter({hasText: 'SB immediate folder'}).click();
			await navigation.getByTestId('chat-project-folder').filter({hasText: 'SB deep folder'}).click();
			await expect(row(fixture.ids.deep)).toContainText(fixture.names.deep);
			await sidebar.screenshot({path: testInfo.outputPath('web-nested-chat-sidebar.png')});

			const listed = await runWorkflowCliJson(apiUrl, home, ['projects', 'list'], 'list sidebar Projects');
			const projectIndex = listed.projects.findIndex((item: {project_id: string}) => item.project_id === project.project_id);
			expect(projectIndex).toBeGreaterThanOrEqual(0);
			const steps: ProofStep[] = [
				{name: 'home-ready', wait_for: 'Continue where you left off', hold_ms: 200},
				{name: 'sidebar-open', key: 'ctrl+b', wait_for: project.name, hold_ms: 500},
				...Array.from({length: projectIndex + 1}, (_, index) => ({name: `project-select-${index}`, key: 'Down'})),
				{name: 'project-open', key: 'Return', wait_for: fixture.names.root, hold_ms: 350},
				{name: 'folder-up-row', key: 'Down'},
				{name: 'folder-select', key: 'Down', wait_for: '> ▸ SB immediate folder'},
				{name: 'folder-open', key: 'Return', wait_for: 'SB deep folder', hold_ms: 350},
				{name: 'deep-up-row', key: 'Down'},
				{name: 'deep-select', key: 'Down'},
				{name: 'deep-open', key: 'Return', wait_for: fixture.names.deep, hold_ms: 350},
				{name: 'deep-chat-up-row', key: 'Down'},
				{name: 'deep-path-row', key: 'Down'},
				{name: 'deep-chat-select', key: 'Down', wait_for: '> ' + fixture.names.deep},
				{name: 'deep-chat-open', key: 'Return', wait_for: 'Started ', wait_for_absent: 'Loading chat…', hold_ms: 500},
				{name: 'deep-sidebar-close', key: 'ctrl+b'},
				{name: 'deep-sidebar-reopen', key: 'ctrl+b', wait_for: '‹ Up one level'},
				{name: 'deep-wheel', wheel: 'down', wait_for: '‹ Up one level', hold_ms: 250} as ProofStep,
				{name: 'sidebar-resume', key: 'ctrl+b'},
				{name: 'chats-command', text: '/chats'},
				{name: 'chats-return', key: 'Return', wait_for: 'Continue where you left off'},
				{name: 'sidebar-reopen', key: 'ctrl+b', wait_for: '‹ Up one level'},
				{name: 'up-from-deep', key: 'Down'},
				{name: 'back-to-folder', key: 'Return', wait_for: 'SB deep folder'},
				{name: 'up-from-folder', key: 'Down'},
				{name: 'back-to-project', key: 'Return', wait_for: 'SB immediate folder'},
				{name: 'up-from-project', key: 'Down'},
				{name: 'back-to-root', key: 'Return', wait_for: 'Today'},
				{name: 'oldest-selected', key: 'End', wait_for: fixture.names.oldest, hold_ms: 500},
				{name: 'page-up', key: 'Page_Up', hold_ms: 200},
				{name: 'page-down', key: 'Page_Down', hold_ms: 200},
				{name: 'sidebar-home', key: 'Home', wait_for: '> + New chat', hold_ms: 350},
				{name: 'sidebar-close-for-draft', key: 'ctrl+b'},
				{name: 'draft-command', text: '/chat ' + fixture.ids.draft},
				{name: 'draft-open', key: 'Return', wait_for: 'Continue ' + fixture.names.draft, wait_for_absent: 'Loading chat…', hold_ms: 400},
				{name: 'clear-draft-composer', key: 'ctrl+u'},
				{name: 'projects-command', text: '/projects'},
				{name: 'projects-home', key: 'Return', wait_for: project.name},
				{name: 'slug-search-command', text: '/search ' + project.slug},
				{name: 'slug-search-results', key: 'Return', wait_for: '> | [folder] ' + project.name},
				{name: 'slug-project-open', key: 'Return', wait_for: '[OVERVIEW]'},
				{name: 'files-tab', text: '2', wait_for: 'SB immediate folder'},
				{name: 'files-folder-open', key: 'Return', wait_for: 'SB deep folder'},
				{name: 'refresh-command', text: '/refresh'},
				{name: 'files-refreshed', key: 'Return', wait_for: 'SB deep folder', wait_for_absent: 'Refreshing Project…', hold_ms: 400},
				{name: 'exit-command', text: '/exit'},
				{name: 'exit', key: 'Return'},
			];
			const recording = await captureProof(apiUrl, home, candidateCli, steps, proofContract, testInfo);
			const opened = recording.frame('sidebar-open').join('\n');
			expect(opened).toContain(project.name);
			expect(opened).toContain('Today');
			expect(opened).not.toContain(archived.name);
			expect(opened).not.toContain(fixture.names.locked);
			const visibleWebNames = fixtureOrder.map(id => fixture.rows.find(item => item.id === id)!.title)
				.filter(name => opened.includes(name));
			expect(visibleWebNames.length).toBeGreaterThanOrEqual(3);
			expect(visibleWebNames.map(name => opened.indexOf(name))).toEqual(
				[...visibleWebNames.map(name => opened.indexOf(name))].sort((a, b) => a - b));
			const rootRows = recording.frame('back-to-root').join('\n');
			for (const id of fixtureOrder.slice(0, 2)) expect(rootRows).toContain(fixture.rows.find(item => item.id === id)!.title);
			expect(recording.frame('folder-select').join('\n')).toContain('SB immediate folder');
			const openedFolder = recording.frame('folder-open').join('\n');
			expect(openedFolder).toContain('SB immedi');
			expect(openedFolder).toContain('‹ Up one level');
			expect(openedFolder).toContain('SB deep folder');
			expect(recording.frame('deep-open').join('\n')).toContain(fixture.names.deep);
			const loadedChat = recording.frame('deep-chat-open').map((line: string) => line.slice(29)).join('\n');
			expect(loadedChat).toContain(fixture.names.deep);
			expect(loadedChat).toContain('Started ');
			expect(loadedChat).not.toContain('Loading chat…');
			expect(recording.frame('oldest-selected').join('\n')).toContain(fixture.names.oldest);
			const beforeWheel = recording.frame('deep-sidebar-reopen'), afterWheel = recording.frame('deep-wheel');
			const selectedSidebarRow = (rows: string[]) => rows.find(row => row.slice(0, 27).includes('> '))?.slice(0, 27);
			expect(selectedSidebarRow(beforeWheel)).toBeTruthy();
			expect(selectedSidebarRow(afterWheel)).toBeTruthy();
			expect(selectedSidebarRow(afterWheel)).not.toBe(selectedSidebarRow(beforeWheel));
			expect(afterWheel.map((line: string) => line.slice(29)).join('\n')).toBe(beforeWheel.map((line: string) => line.slice(29)).join('\n'));
			expect(recording.frame('draft-open').join('\n')).toContain('Draft');
			expect(recording.frame('draft-open').join('\n')).toContain('Continue ' + fixture.names.draft);
			expect(recording.frame('slug-search-results').join('\n')).toContain(project.name);
			const refreshedFiles = recording.frame('files-refreshed').join('\n');
			expect(refreshedFiles).toContain('[FILES]');
			expect(refreshedFiles).toContain('Files / SB immediate folder');
			expect(refreshedFiles).toContain('SB deep folder');
			expect(refreshedFiles).not.toContain('Refreshing Project…');
			await recording.attest();
		} catch (error) { primaryError = error; failed = true; }
		finally {
			// Stop browser synchronization before removing fixture records.
			try { await page.goto('about:blank'); } catch (error) { cleanupErrors.push(error); }
			for (const id of projects.reverse()) {
				try { sdk(apiUrl, home, candidateCli, 'const deleted=await client.deleteProject(input.id,input.id,{personal:true}); if(!deleted.deleted) throw Error("Project cleanup not confirmed"); process.stdout.write("{}");', {id}); }
				catch (error) { cleanupErrors.push(error); }
			}
			if (fixture) {
				try { sdk(apiUrl, home, candidateCli, 'await client.clearDraft(input.id); process.stdout.write("{}");', {id: fixture.ids.draft}); }
				catch (error) { cleanupErrors.push(error); }
				try { ciphertextFixture(fixture, 'cleanup'); } catch (error) { cleanupErrors.push(error); }
			}
			removeWorkflowCliHome(home);
			if (cleanupErrors.length) {
				const cleanupReport = cleanupErrors.map(error => error instanceof Error ? error.stack || error.message : String(error)).join('\n\n');
				console.error('Sidebar proof cleanup failed:', cleanupReport);
				await testInfo.attach('sidebar-fixture-cleanup-errors', {body: cleanupReport, contentType: 'text/plain'});
			}
		}
		if (failed) throw primaryError;
		if (cleanupErrors.length) throw cleanupErrors[0];
	});
