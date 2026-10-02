/* eslint-disable @typescript-eslint/no-require-imports */
export {};

// Saved ciphertext and task markers live only in the coordinator's disposable stack.
// AI naming is controlled here; real inference is verified separately on dev.
const { test, expect } = require('./helpers/cookie-audit');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { CLI_DIST } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome, workflowCliEnv, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { waitForChatReady } = require('./helpers/chat-test-helpers');
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
import asyncio,hashlib,json,logging,os,sys,time
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
                metadata={**row,'hashed_user_id':owner,'created_at':int(time.time())-60,'updated_at':int(time.time())-60,
                  'last_edited_overall_timestamp':int(time.time())-60,'messages_v':0,'title_v':1,'metadata_v':1,'unread_count':0}
                created,_=await directus.chat.create_chat_in_directus(metadata)
                assert created, 'Ciphertext chat seed failed'
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

// contract-test: direct surface=gui.web assertions=chat-navigation.projects.organize,chat-navigation.projects.nested-readable,chat-navigation.activity.global-running,projects.lifecycle.encrypted-crud,projects.files.write-policy-setup
test('groups saved chats, navigates deep folders and reveals running descendants globally', async ({ page }: { page: any }) => {
  test.setTimeout(300_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e', 'Requires isolated GitHub product stack');
  skipWithoutCredentials(test, email, password, otpKey);
  const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('sidebar-projects');
  const projects: string[] = [];
  let data: any;
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
        chats.push({id, encrypted_title:await encrypt(title,key),encrypted_chat_key:await encrypt(key,master),parent_id:parentId,is_sub_chat:!!parentId});
      }
      process.stdout.write(JSON.stringify({userId:user.id,chats}));
    `);
    fixture(data, 'seed');
    const [parent, research, child] = data.chats.map((row: any) => row.id);
    const row = (id: string) => page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${id}"]`);
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
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ proposed_project: { name: naming.length === 1 ? 'Website launch' : 'Research archive' } }) });
    });
    const created = page.waitForResponse((response: any) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/v1/projects' && response.ok());
    await row(research).dragTo(row(parent));
    const response = await created, createPayload = response.request().postDataJSON();
    const projectId = (await response.json()).project.project_id; projects.push(projectId);
    expect(naming[0]).toContain('Launch copy'); expect(naming[0]).toContain('Market research');
    expect(createPayload).toMatchObject({ write_mode: null, chat_organization_only: true });
    expect(createPayload.encrypted_name).not.toContain('Website launch');
    await expect(page.getByTestId('workspace-detail-title')).toHaveText('Website launch', { timeout: 30_000 });
    expect(page.url()).toContain(`project-id=${projectId}`);
    let items = sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id: projectId });
    expect(items.items).toHaveLength(2);
    expect(JSON.stringify(items)).not.toContain('Market research');

    await page.goto('/'); await waitForChatReady(page); await openSidebar();
    const navigation = sidebar.getByTestId('chat-project-navigation');
    await navigation.getByTestId('chat-project-root').filter({ hasText: 'Website launch' }).click();
    for (const name of ['Marketing', 'Campaigns', 'Launch copy', 'Drafts']) {
      await navigation.getByRole('button', { name: 'New subfolder', exact: true }).click();
      const input = navigation.getByRole('textbox', { name: 'Folder name' });
      await input.fill(name); await input.press('Enter');
      await navigation.getByTestId('chat-project-folder').filter({ hasText: name }).click();
    }
    await expect(navigation.getByRole('navigation')).toContainText('Website launch');
    await expect(navigation.getByRole('navigation')).toContainText('Drafts');
    await navigation.getByRole('button', { name: 'Show full path' }).click();
    await expect(navigation.getByTestId('chat-project-ancestors').getByRole('button')).toHaveText(['Website launch', 'Marketing', 'Campaigns', 'Launch copy', 'Drafts']);
    await navigation.getByTestId('chat-project-ancestors').getByRole('button', { name: 'Website launch', exact: true }).click();
    await expect(row(parent)).toBeVisible();

    // The real context menu moves the parent into an existing deep destination.
    await row(parent).click({ button: 'right' });
    await page.getByTestId('chat-context-move-to-project').click();
    const picker = page.getByTestId('chat-project-picker');
    await picker.getByTestId('chat-project-root').filter({ hasText: 'Website launch' }).click();
    for (const name of ['Marketing', 'Campaigns', 'Launch copy', 'Drafts']) await picker.getByTestId('chat-project-folder').filter({ hasText: name }).click();
    await picker.getByTestId('chat-project-add-here').click(); await expect(picker).toHaveCount(0);
    items = sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id: projectId });
    expect(items.items).toHaveLength(2);
    const drafts = items.folders.find((folder: any) => !items.folders.some((candidate: any) => candidate.hashed_parent_folder_id === createHash('sha256').update(folder.folder_id).digest('hex')));
    expect(items.items.some((item: any) => item.hashed_folder_id === createHash('sha256').update(drafts.folder_id).digest('hex'))).toBe(true);

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
    await navigation.getByTestId('chat-project-root').filter({ hasText: 'Website launch' }).click();
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
    await expect(page.getByTestId('workspace-detail-title')).toHaveText('Research archive');
    const secondId = new URL(page.url()).hash.match(/project-id=([^&]+)/)[1]; projects.push(secondId);
    expect(sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id: projectId }).items).toHaveLength(1);
    await page.goto('/'); await waitForChatReady(page); await openSidebar();
    await closeSidebar();
    const continueCard = page.locator(`.continue-priority-card[data-chat-id="${parent}"], .resume-chat-card[data-chat-id="${parent}"], .resume-chat-large-card[data-chat-id="${parent}"]`).first();
    await expect(continueCard).toBeVisible({ timeout: 30_000 });
    await continueCard.click({ button: 'right' });
    await expect(page.getByTestId('chat-context-create-project')).toBeVisible();
    await expect(page.getByTestId('chat-context-move-to-project')).toBeVisible();
    await page.getByTestId('chat-context-add-to-project').click();
    await picker.getByTestId('chat-project-root').filter({ hasText: 'Website launch' }).click();
    await picker.getByTestId('chat-project-add-here').click(); await expect(picker).toHaveCount(0);
    for (const id of projects) expect(sdk(apiUrl, home, 'process.stdout.write(JSON.stringify(await client.listProjectItems(input.id,{chatOnly:true})));', { id }).items.length).toBe(id === projectId ? 2 : 1);
  } catch (error) { primaryError = error; throw error; }
  finally {
    const cleanupErrors: unknown[] = [];
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
