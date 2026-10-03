/* eslint-disable @typescript-eslint/no-require-imports */
export {};

// Saved ciphertext and task markers live only in the coordinator's disposable stack.
// AI naming is controlled here; real inference is verified separately on dev.
const { test, expect } = require('./helpers/cookie-audit');
const { execFileSync, spawn } = require('node:child_process');
const { copyRemoteHostSession, waitForFixtureEvent, stopFixtureProcess } = require('./helpers/project-remote-fixture');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { CLI_DIST } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome, workflowCliEnv, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { waitForChatReady } = require('./helpers/chat-test-helpers');
const { waitForHydratedChat } = require('./helpers/chat-hydration');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const root = path.resolve(__dirname, '../../../..');
const compose = path.join(root, 'test-results/ci-private/compose.json');
const { email, password, otpKey } = getTestAccount();

function sdk(apiUrl: string, home: string, program: string, payload: unknown = {}): any {
  const modulePath = path.join(path.dirname(CLI_DIST), 'index.js');
  expect(fs.existsSync(modulePath), 'Candidate SDK must be built').toBe(true);
  const source = `
    const {pathToFileURL} = require('node:url');
    const {webcrypto,randomUUID,randomBytes} = require('node:crypto');
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
    })().catch(() => { console.error('Sidebar SDK fixture failed'); process.exit(1); });
  `;
  return JSON.parse(execFileSync('node', ['-e', source, modulePath, JSON.stringify(payload)], {
    cwd: root, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 60_000,
  }).trim());
}

function fixture(payload: unknown, operation: 'seed' | 'active' | 'complete' | 'cleanup'): void {
  expect(fs.existsSync(compose), 'Requires disposable coordinator compose').toBe(true);
  const program = `
import asyncio,hashlib,json,logging,os,sys,time,uuid
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _chat_list_cache_data_from_metadata,_chat_versions_from_metadata
async def main():
    data=json.load(sys.stdin); cache=CacheService(); directus=DirectusService(cache_service=cache)
    owner=hashlib.sha256(data['userId'].encode()).hexdigest()
    try:
        for row in data['chats']:
            if data['operation']=='seed':
                metadata={**{key:value for key,value in row.items() if key!='seed_message'},'hashed_user_id':owner,'created_at':int(time.time())-60,'updated_at':int(time.time())-60,
                  'last_edited_overall_timestamp':int(time.time())-60,'messages_v':1,'title_v':1,'metadata_v':1,'unread_count':0}
                created,_=await directus.chat.create_chat_in_directus(metadata)
                assert created, 'Ciphertext chat seed failed'
                message=await directus.chat.create_message_in_directus({**row['seed_message'],'chat_id':row['id'],'hashed_user_id':owner,'role':'user','created_at':metadata['created_at']})
                assert message and message.get('id'), 'Ciphertext message seed failed'
                assert await cache.add_chat_to_ids_versions(data['userId'],row['id'],metadata['last_edited_overall_timestamp'])
                assert await cache.set_chat_list_item_data(data['userId'],row['id'],_chat_list_cache_data_from_metadata(metadata))
                assert await cache.set_chat_versions(data['userId'],row['id'],_chat_versions_from_metadata(metadata))
            else:
                metadata=await directus.chat.get_chat_metadata(row['id'])
                assert metadata and metadata.get('hashed_user_id')==owner, 'Only fixture-owned records may change'
                if data['operation']=='active':
                    if row.get('parent_id'): assert await cache.set_active_ai_task(row['id'],'sidebar-fixture-task',ttl=600)
                elif data['operation']=='complete': await cache.clear_active_ai_task(row['id'])
                elif data['operation']=='cleanup':
                    await cache.clear_active_ai_task(row['id'])
                    await directus.delete_item('messages',str(uuid.uuid5(uuid.NAMESPACE_DNS,row['seed_message']['message_id'])))
                    await directus.delete_item('chats',row['id'])
                    await cache.remove_chat_from_ids_versions(data['userId'],row['id'])
        print('sidebar fixture applied')
    finally: await directus.close(); await cache.close()
asyncio.run(main())
`;
  const output = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T', '-e', 'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
    cwd: root, input: JSON.stringify({ ...(payload as object), operation }), encoding: 'utf8', timeout: 60_000,
  });
  expect(output.trim()).toBe('sidebar fixture applied');
}

// contract-test: direct surface=gui.web assertions=chat-navigation.projects.organize,chat-navigation.projects.nested-readable,chat-navigation.activity.global-running,projects.lifecycle.encrypted-crud,projects.files.write-policy-setup,projects.links.openmates-only-encrypted,projects.surface.semantic-parity
test('groups saved chats, navigates deep folders and reveals running descendants globally', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(420_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e', 'Requires isolated GitHub product stack');
  skipWithoutCredentials(test, email, password, otpKey);
  const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('sidebar-projects');
  const projects: string[] = [];
  let data: any;
  let bridge: any;
  let primaryError: unknown;
  let cleanupError: unknown;
  try {
    await loginWorkflowCliViaPair(page, apiUrl, home, 'SIDEBAR_PROJECTS');
    await page.goto('about:blank');
    data = sdk(apiUrl, home, `
      const user=await client.whoAmI(), master=client.getMasterKeyBytes();
      const parent=randomUUID(), research=randomUUID(), child=randomUUID();
      const chats=[];
      for (const [id,title,parentId] of [[parent,'Launch copy',null],[research,'Market research',null],[child,'Audience analysis',parent]]) {
        const key=randomBytes(32);
        chats.push({id, encrypted_title:await encrypt(title,key),encrypted_chat_key:await encrypt(key,master),
          seed_message:{message_id:randomUUID(),encrypted_content:await encrypt('Start '+title,key),encrypted_sender_name:await encrypt('User',key)},
          encrypted_chat_summary:await encrypt('Next steps for '+title,key),encrypted_category:await encrypt('technology',key),encrypted_icon:await encrypt('code',key),parent_id:parentId,is_sub_chat:!!parentId});
      }
      process.stdout.write(JSON.stringify({userId:user.id,chats}));
    `);
    fixture(data, 'seed');
    const [parent, research, child] = data.chats.map((row: any) => row.id);
    // A timed-out attempt may leave disposable records until stack teardown.
    // Match this attempt's Project names so a retry cannot target an older one.
    const launchProjectName = `Website launch ${parent.slice(0, 8)}`;
    const researchProjectName = `Research archive ${parent.slice(0, 8)}`;
    const row = (id: string) => page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${id}"]`);
    const projectChat = (id: string) => page.locator(`[data-testid="project-chat-preview"][data-chat-id="${id}"]`).getByTestId('project-chat-card');
    async function expectLoadedProjectChat(id: string, title: string): Promise<void> {
      await waitForChatReady(page);
      await expect(page).toHaveURL(new RegExp(`#chat-id=${id}$`));
      await waitForHydratedChat(page, id, testInfo);
      await expect(page.getByTestId('chat-header-title')).toHaveText(title);
    }
    const sidebar = page.getByTestId('activity-history-wrapper');
    const toggle = page.getByTestId('sidebar-toggle');
    async function openSidebar(): Promise<void> {
      if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
      await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    }
    async function closeSidebar(): Promise<void> {
      if (await toggle.getAttribute('aria-expanded') === 'true') await sidebar.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    }
    await page.goto('/'); await waitForChatReady(page); await openSidebar();
    await expect(row(parent)).toContainText('Launch copy', { timeout: 30_000 });
    await expect(row(research)).toContainText('Market research');
    const naming: string[] = [];
    await page.route('**/v1/projects/ask/plan', async (route: any) => {
      const body = route.request().postDataJSON();
      expect(body.chat_titles.length).toBeLessThanOrEqual(8);
      expect(body.chat_titles.every((title: string) => title.length <= 200)).toBe(true);
      naming.push(JSON.stringify(body.chat_titles));
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ proposed_project: { name: naming.length === 1 ? launchProjectName : researchProjectName } }) });
    });
    const created = page.waitForResponse((response: any) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/v1/projects' && response.ok());
    await row(research).dragTo(row(parent));
    const response = await created, createPayload = response.request().postDataJSON();
    const projectId = (await response.json()).project.project_id; projects.push(projectId);
    expect(naming[0]).toContain('Launch copy'); expect(naming[0]).toContain('Market research');
    expect(createPayload).toMatchObject({ write_mode: null, chat_organization_only: true });
    expect(createPayload.encrypted_name).not.toContain(launchProjectName);
    await expect(page.getByTestId('workspace-detail-title')).toHaveText(launchProjectName, { timeout: 30_000 });
    expect(page.url()).toContain(`project-id=${projectId}`);
    let items = sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id: projectId });
    expect(items.items).toHaveLength(2);
    expect(JSON.stringify(items)).not.toContain('Market research');

    // Linked previews use current authorized metadata and open the original chat.
    await expect(page.getByTestId('project-chats-section').getByTestId('project-chat-card')).toHaveCount(2);
    await expect(projectChat(parent)).toContainText('Launch copy');
    await expect(projectChat(parent)).toContainText('Next steps for Launch copy');
    await expect(projectChat(parent)).toHaveCSS('height', '200px');
    await expect(projectChat(parent)).toHaveAttribute('href', `/#chat-id=${parent}`);
    await projectChat(parent).click();
    await expectLoadedProjectChat(parent, 'Launch copy');
    await expect(page.getByTestId('project-overview-panel')).toHaveCount(0);
    await page.goto(`/#project-id=${projectId}`);
    await expect(page.getByTestId('project-chats-section').getByTestId('project-chat-card')).toHaveCount(2);
    expect(sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id: projectId }).items).toHaveLength(2);

    await page.goto('/'); await waitForChatReady(page); await openSidebar();
    const navigation = sidebar.getByTestId('chat-project-navigation');
    await navigation.getByTestId('chat-project-root').filter({ hasText: launchProjectName }).click();
    for (const name of ['Marketing', 'Campaigns', 'Launch copy', 'Drafts']) {
      await navigation.getByRole('button', { name: 'New subfolder', exact: true }).click();
      const input = navigation.getByRole('textbox', { name: 'Folder name' });
      await input.fill(name); await input.press('Enter');
      await navigation.getByTestId('chat-project-folder').filter({ hasText: name }).click();
    }
    await expect(navigation.getByRole('navigation')).toContainText('Website launch');
    await expect(navigation.getByRole('navigation')).toContainText('Drafts');
    await navigation.getByRole('button', { name: 'Show full path' }).click();
    await expect(navigation.getByTestId('chat-project-ancestors').getByRole('button')).toHaveText([launchProjectName, 'Marketing', 'Campaigns', 'Launch copy', 'Drafts']);
    await navigation.getByTestId('chat-project-ancestors').getByRole('button', { name: launchProjectName, exact: true }).click();
    await expect(row(parent)).toBeVisible();

    // The real context menu moves the parent into an existing deep destination.
    await row(parent).click({ button: 'right' });
    await page.getByTestId('chat-context-move-to-project').click();
    const picker = page.getByTestId('chat-project-picker');
    await picker.getByTestId('chat-project-root').filter({ hasText: launchProjectName }).click();
    for (const name of ['Marketing', 'Campaigns', 'Launch copy', 'Drafts']) await picker.getByTestId('chat-project-folder').filter({ hasText: name }).click();
    await picker.getByTestId('chat-project-add-here').click(); await expect(picker).toHaveCount(0);
    items = sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id: projectId });
    expect(items.items).toHaveLength(2);
    const drafts = items.folders.find((folder: any) => !items.folders.some((candidate: any) => candidate.hashed_parent_folder_id === createHash('sha256').update(folder.folder_id).digest('hex')));
    expect(items.items.some((item: any) => item.hashed_folder_id === createHash('sha256').update(drafts.folder_id).digest('hex'))).toBe(true);

    // Overview includes nested links; Files shows only the current folder's chats.
    await page.goto(`/#project-id=${projectId}`);
    await expect(projectChat(parent)).toBeVisible();
    await page.getByTestId('project-tab-folders').click();
    await expect(projectChat(research)).toBeVisible();
    await expect(projectChat(parent)).toHaveCount(0);
    for (const name of ['Marketing', 'Campaigns', 'Launch copy', 'Drafts']) {
      await page.getByTestId('project-folder-card').filter({ hasText: name }).click();
    }
    await expect(projectChat(parent)).toContainText('Next steps for Launch copy');
    await expect(projectChat(research)).toHaveCount(0);
    await projectChat(parent).focus(); await projectChat(parent).press('Enter');
    await waitForChatReady(page);
    await expect(page.getByTestId('chat-header-title')).toHaveText('Launch copy');

    fixture(data, 'active');
    const census = sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.getChatActivity()));');
    expect(census.ids).toEqual([child]);
    expect(census.chats.find((chat: any) => chat.id === child).parentId).toBe(parent);
    await page.goto('about:blank'); await page.goto('/'); await waitForChatReady(page);
    await expect(page.getByTestId('active-chats-link')).toHaveText('1 chat active…', { timeout: 30_000 });
    await closeSidebar();
    await page.getByTestId('active-chats-link').click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const running = sidebar.getByTestId('running-chats-section');
    await expect(running.locator('[data-testid="chat-item-wrapper"]')).toHaveCount(1);
    await expect(running).toContainText('Launch copy'); await expect(running).toContainText('1 subchat running');
    await expect(running.getByTestId('chat-processing-wheel')).toBeVisible();
    await expect(running.locator('.category-circle')).toHaveCount(0);
    await navigation.getByTestId('chat-project-root').filter({ hasText: launchProjectName }).click();
    await expect(navigation.getByTestId('chat-project-folder').getByTestId('chat-processing-wheel')).toBeVisible();
    for (const name of ['Marketing', 'Campaigns', 'Launch copy']) await navigation.getByTestId('chat-project-folder').filter({ hasText: name }).click();
    await expect(navigation.getByTestId('chat-project-folder').getByTestId('chat-processing-wheel')).toBeVisible();
    const runningBox = await running.boundingBox(), navBox = await navigation.boundingBox();
    expect(runningBox.y).toBeLessThan(navBox.y);
    await sidebar.screenshot({ path: test.info().outputPath('running-chat-deep-folder.png') });
    fixture(data, 'complete');
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await expect(running).toHaveCount(0, { timeout: 30_000 });
    await expect(page.getByTestId('active-chats-link')).toHaveCount(0);
    await expect(navigation.getByTestId('chat-processing-wheel')).toHaveCount(0);
    await navigation.getByTestId('chat-project-folder').filter({ hasText: 'Drafts' }).click();
    await expect(row(parent)).toBeVisible();

    // Add preserves membership; move removes source membership only after destination exists.
    await row(parent).click({ button: 'right' });
    await page.getByTestId('chat-context-create-project').click();
    await expect(page.getByTestId('workspace-detail-title')).toHaveText(researchProjectName);
    const secondId = new URL(page.url()).hash.match(/project-id=([^&]+)/)[1]; projects.push(secondId);
    await expect(page.getByTestId('project-chats-section').getByTestId('project-chat-card')).toHaveCount(1);
    await expect(projectChat(parent)).toContainText('Launch copy');
    expect(sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id: projectId }).items).toHaveLength(1);
    await page.goto('/'); await waitForChatReady(page); await openSidebar();
    await closeSidebar();
    const continueCard = page.locator(`.continue-priority-card[data-chat-id="${parent}"], .resume-chat-card[data-chat-id="${parent}"], .resume-chat-large-card[data-chat-id="${parent}"]`).first();
    await expect(continueCard).toBeVisible({ timeout: 30_000 });
    await continueCard.click({ button: 'right' });
    await expect(page.getByTestId('chat-context-create-project')).toBeVisible();
    await expect(page.getByTestId('chat-context-move-to-project')).toBeVisible();
    await page.getByTestId('chat-context-add-to-project').click();
    await picker.getByTestId('chat-project-root').filter({ hasText: launchProjectName }).click();
    await picker.getByTestId('chat-project-add-here').click(); await expect(picker).toHaveCount(0);
    for (const id of projects) expect(sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id }).items.length).toBe(id === projectId ? 2 : 1);
    await page.goto(`/#project-id=${projectId}`);
    await expect(page.getByTestId('project-chats-section').getByTestId('project-chat-card')).toHaveCount(2);

    // A real, disposable read-only host serves files; chat associations stay in
    // encrypted OpenMates items and survive both its disconnect and a fresh load.
    const hostStateDir = path.join(home, 'remote-host');
    const pairedEnvironment = workflowCliEnv(apiUrl, home);
    const hostSession = copyRemoteHostSession(pairedEnvironment.OPENMATES_STATE_DIR || path.join(home, '.openmates'), hostStateDir);
    const hostEnvironment = { ...pairedEnvironment, OPENMATES_STATE_DIR: hostStateDir };
    bridge = spawn('node', ['--experimental-strip-types', '--loader', './frontend/packages/openmates-cli/tests/loader.mjs',
      'scripts/project_remote_access_live.mjs', 'serve', apiUrl], {
      cwd: root, env: { ...hostEnvironment, OPENMATES_REMOTE_HOST_SESSION: hostSession },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const remote = await waitForFixtureEvent(bridge, 'fixture_ready');
    expect(remote.path_privacy_verified).toBe(true);
    sdk(apiUrl, home, `
      const project=(await client.getProject(input.projectId,{personal:true})).project;
      const key=await client.decryptProjectKey(project,{personal:true}), timestamp=Math.floor(Date.now()/1000);
      const docs=randomUUID(), notes=randomUUID(), deep=randomUUID();
      await client.createProjectFolder(input.projectId,{folder_id:docs,encrypted_name:await encrypt('docs',key),created_at:timestamp,updated_at:timestamp},{personal:true});
      await client.createProjectFolder(input.projectId,{folder_id:notes,parent_folder_id:docs,encrypted_name:await encrypt('Notes',key),created_at:timestamp,updated_at:timestamp},{personal:true});
      await client.createProjectFolder(input.projectId,{folder_id:deep,parent_folder_id:notes,encrypted_name:await encrypt('Deep',key),created_at:timestamp,updated_at:timestamp},{personal:true});
      for(const [chatId,name,folderId,metadata] of [[input.parent,'Launch copy',null,{source_id:input.sourceId,path:'docs'}],
        [input.research,'Market research',deep,{}]]) {
        await client.createProjectItem(input.projectId,{project_item_id:randomUUID(),item_type:'chat',target_id:chatId,folder_id:folderId,
          target_id_encrypted:await encrypt(chatId,key),encrypted_display_name:await encrypt(name,key),encrypted_note:await encrypt('',key),
          encrypted_metadata:await encrypt(JSON.stringify(metadata),key),created_at:timestamp,updated_at:timestamp,position:timestamp},{personal:true});
      }
      process.stdout.write('{}');
    `, { projectId: remote.project_id, sourceId: remote.source_id, parent, research });
    // The fixture creates this Project outside the browser. A new document
    // loads its inventory rather than keeping the prior in-tab Project cache.
    await page.goto('about:blank');
    await page.goto(`/#project-id=${remote.project_id}`);
    await expect(projectChat(parent)).toContainText('Launch copy');
    await expect(page.getByTestId('project-chats-section').getByTestId('project-chat-card')).toHaveCount(2);
    await page.getByTestId('project-tab-folders').click();
    const remoteGrid = page.getByTestId('project-remote-directory-results');
    await expect(remoteGrid).toBeVisible({ timeout: 30_000 });
    await remoteGrid.getByTestId('project-remote-entry').filter({ hasText: 'docs' }).click();
    await expect(remoteGrid.getByTestId('project-chat-card')).toContainText('Launch copy');
    await expect(remoteGrid.getByTestId('project-remote-entry').filter({ hasText: 'readme-image.png' })).toBeVisible();
    const linkedFolderRequests: string[] = [];
    const observeLinkedRequests = (request: any) => {
      if (request.method() === 'POST' && /\/projects\/[^/]+\/sources\/[^/]+\/requests/.test(request.url())) linkedFolderRequests.push(request.url());
    };
    page.on('request', observeLinkedRequests);
    await remoteGrid.getByTestId('project-chat-folder').filter({ hasText: 'Notes' }).click();
    await remoteGrid.getByTestId('project-chat-folder').filter({ hasText: 'Deep' }).click();
    await expect(remoteGrid.getByTestId('project-chat-card')).toContainText('Market research');
    await expect(page.getByTestId('project-remote-error')).toHaveCount(0);
    await page.getByLabel('Project folder path').getByRole('button', { name: 'Notes', exact: true }).click();
    await expect(remoteGrid.getByTestId('project-chat-folder').filter({ hasText: 'Deep' })).toBeVisible();
    await expect(page.getByTestId('project-remote-error')).toHaveCount(0);
    expect(linkedFolderRequests).toEqual([]);
    page.off('request', observeLinkedRequests);
    await page.getByLabel('Project folder path').getByRole('button', { name: 'docs', exact: true }).click();
    const stopped = waitForFixtureEvent(bridge, 'bridge_stopped');
    bridge.kill('SIGUSR1'); await stopped;
    await expect(page.getByTestId('project-remote-error')).toContainText('offline', { timeout: 30_000 });
    await expect(remoteGrid.getByTestId('project-remote-entry')).toHaveCount(0);
    await expect(projectChat(parent)).toContainText('Launch copy');
    const offlineRequests: string[] = [];
    page.on('request', request => { if (request.method() === 'POST' && /\/projects\/[^/]+\/sources\/[^/]+\/requests/.test(request.url())) offlineRequests.push(request.url()); });
    await page.reload();
    await page.getByTestId('project-tab-folders').click();
    await expect(page.getByTestId('project-remote-error')).toContainText('offline');
    await remoteGrid.getByTestId('project-chat-folder').filter({ hasText: 'docs' }).click();
    await expect(projectChat(parent)).toContainText('Launch copy');
    await remoteGrid.getByTestId('project-chat-folder').filter({ hasText: 'Notes' }).click();
    await remoteGrid.getByTestId('project-chat-folder').filter({ hasText: 'Deep' }).click();
    await expect(projectChat(research)).toContainText('Market research');
    await expect(remoteGrid.getByTestId('project-remote-entry')).toHaveCount(0);
    expect(offlineRequests).toEqual([]);
    await page.getByTestId('project-folders-panel').screenshot({ path: testInfo.outputPath('remote-offline-chat-links.png') });
    await projectChat(research).click();
    await expectLoadedProjectChat(research, 'Market research');
    expect(sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id: remote.project_id }).items).toHaveLength(2);
  } catch (error) { primaryError = error; throw error; }
  finally {
    const cleanupErrors: unknown[] = [];
    if (bridge) { try { await stopFixtureProcess(bridge); } catch (error) { cleanupErrors.push(error); } }
    for (const id of projects.reverse()) {
      try { sdk(apiUrl, home, 'await client.deleteProject(input.id,input.id); process.stdout.write("{}");', { id }); }
      catch (error) { cleanupErrors.push(error); }
    }
    if (data) { try { fixture(data, 'cleanup'); } catch (error) { cleanupErrors.push(error); } }
    removeWorkflowCliHome(home);
    if (!primaryError && cleanupErrors.length) cleanupError = cleanupErrors[0];
  }
  if (cleanupError) throw cleanupError;
});
