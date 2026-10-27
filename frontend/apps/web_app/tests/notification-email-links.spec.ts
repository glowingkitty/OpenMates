/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/** Signed-in destinations for the chat, Workflow run, and settings URLs in notification emails. */
export {};

import { randomUUID } from 'node:crypto';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials, skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { CLI_DIST } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair, workflowCliEnv } = require('./helpers/workflow-cli-e2e-helpers');

const { email, password, otpKey } = getTestAccount();

/** Bounded route-only evidence: never retain search params, text or credentials. */
async function observeReminderTargetHashWrites(page: any): Promise<void> {
  await page.addInitScript(() => {
    const writes: Record<string, unknown>[] = [];
    const targetWindow = window as Window & { __reminderTargetHashWrites?: Record<string, unknown>[] };
    targetWindow.__reminderTargetHashWrites = writes;
    const params = (hash: string) => new URLSearchParams(hash.replace(/^#\/?/, ''));
    const safeHash = (hash: string) => {
      const source = params(hash);
      const safe = new URLSearchParams();
      for (const key of ['chat-id', 'embed-id', 'embed_id', 'message-id', 'message_id', 'messageid', 'team-id']) {
        const value = source.get(key);
        if (value !== null) safe.set(key, /^[a-z0-9_-]{1,150}$/i.test(value) ? value : '[redacted]');
      }
      return safe.size ? `#${safe}` : hash ? '#[other-route]' : '';
    };
    const losesTarget = (before: string, after: string) => {
      const oldParams = params(before), newParams = params(after);
      const hasEmbed = (value: URLSearchParams) => value.has('embed-id') || value.has('embed_id');
      const hasMessage = (value: URLSearchParams) => value.has('message-id') || value.has('message_id') || value.has('messageid');
      return (hasEmbed(oldParams) && !hasEmbed(newParams)) || (hasMessage(oldParams) && !hasMessage(newParams));
    };
    for (const method of ['replaceState', 'pushState'] as const) {
      const original = history[method];
      history[method] = function(this: History, ...args: Parameters<History['replaceState']>) {
        const before = window.location.hash;
        const result = original.apply(this, args);
        const after = window.location.hash;
        if (writes.length < 20 && losesTarget(before, after)) {
          writes.push({ method, before: safeHash(before), after: safeHash(after),
            stack: new Error('Reminder target hash removed').stack?.split('\n').slice(0, 14).join('\n').replace(/[?#][^\s)]*/g, '') });
        }
        return result;
      };
    }
  });
}

async function reminderTargetHashWrites(page: any): Promise<unknown[]> {
  return page.evaluate(() => (window as Window & { __reminderTargetHashWrites?: unknown[] }).__reminderTargetHashWrites ?? []).catch(() => []);
}

async function attachRouteWriterSources(page: any, testInfo: any, writes: unknown[]): Promise<void> {
  let excerpts: unknown[];
  try {
    excerpts = await page.evaluate(async (events: { stack?: string }[]) => {
      const scripts = new Map<string, { line: number; column: number }[]>();
      for (const event of events) {
        for (const frame of (event.stack ?? '').matchAll(/(https?:\/\/[^\s)]+\.js):(\d+):(\d+)/g)) {
          const url = new URL(frame[1]);
          if (url.origin !== location.origin || url.search || url.hash || !/^\/_app\/immutable\/.+\.js$/.test(url.pathname)) continue;
          if (!scripts.has(url.href) && scripts.size >= 4) continue;
          const frames = scripts.get(url.href) ?? [];
          const line = Number(frame[2]), column = Number(frame[3]);
          if (frames.length < 2 && !frames.some(value => value.line === line && value.column === column)) frames.push({ line, column });
          scripts.set(url.href, frames);
        }
      }
      const results: Record<string, unknown>[] = [];
      for (const [url, frames] of scripts) {
        const script = new URL(url).pathname;
        try {
          const response = await fetch(url, { credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(5000) });
          if (!response.ok || Number(response.headers.get('content-length') || 0) > 2_000_000) {
            results.push({ script, error: 'static_source_unavailable' }); continue;
          }
          const source = await response.text();
          if (source.length > 2_000_000) { results.push({ script, error: 'static_source_too_large' }); continue; }
          const lines = source.split('\n');
          for (const frame of frames) {
            const line = lines[frame.line - 1];
            if (line === undefined) { results.push({ script, error: 'stack_line_unavailable' }); continue; }
            const offset = Math.max(0, frame.column - 1);
            results.push({ script, ...frame, excerpt: line.slice(Math.max(0, offset - 1500), offset + 1500) });
          }
        } catch { results.push({ script, error: 'static_source_capture_failed' }); }
      }
      return results;
    }, writes);
  } catch { excerpts = [{ error: 'source_capture_failed' }]; }
  try {
    await testInfo.attach('route-writer-source-excerpts', {
      body: Buffer.from(JSON.stringify(excerpts, null, 2)), contentType: 'application/json',
    });
  } catch { /* Evidence capture must never replace the original test failure. */ }
}

/** Same owner-backed encrypted WebSocket fixture protocol as historical embed recovery. */
function seedPrivateLinkTarget(home: string): { chatId: string; embedId: string; messageId: string } {
  const source = String.raw`
    const {pathToFileURL}=require('node:url');
    const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
    (async()=>{
      const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
      const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
      const owner=await client.whoAmI();
      if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal owner');
      const hash=value=>createHash('sha256').update(value).digest('hex');
      const encrypt=async(value,key)=>{
        const iv=randomBytes(12),cryptoKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
        return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},cryptoKey,
          Buffer.from(value)))]).toString('base64');
      };
      const chatId=randomUUID(),userId=randomUUID(),messageId=randomUUID(),embedId=randomUUID();
      const chatKey=randomBytes(32),embedKey=randomBytes(32),now=Math.floor(Date.now()/1000);
      const {ws}=await client.openWsClient({taskUpdateJobs:false});
      const send=async(type,reply,payload)=>{
        const requestId=randomUUID(),receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
        await ws.sendAsync(type,{...payload,request_id:requestId});return (await receipt).payload;
      };
      try {
        const metadata=ws.waitForMessage('encrypted_metadata_stored',p=>p.chat_id===chatId,30000);
        await ws.sendAsync('encrypted_chat_metadata',{
          chat_id:chatId,message_id:userId,team_id:null,created_at:now-1,
          encrypted_content:await encrypt('Save this notification destination',chatKey),
          encrypted_sender_name:await encrypt('You',chatKey),
          encrypted_category:await encrypt('general_knowledge',chatKey),
          encrypted_title:await encrypt('Private notification destination',chatKey),
          encrypted_icon:await encrypt('code',chatKey),
          encrypted_chat_category:await encrypt('general_knowledge',chatKey),
          encrypted_chat_key:await encrypt(chatKey,client.getMasterKeyBytes()),
          versions:{messages_v:2,title_v:1,metadata_v:1,last_edited_overall_timestamp:now},
          message_history:[{message_id:messageId,role:'assistant',created_at:now,
            encrypted_content:await encrypt('Notification destination is ready.',chatKey),
            encrypted_sender_name:await encrypt('Assistant',chatKey),
            encrypted_category:await encrypt('general_knowledge',chatKey)}]
        });
        if((await metadata).payload.message_id!==userId)throw Error('Encrypted metadata not acknowledged');
        let ready=false;
        for(let attempt=0;attempt<30;attempt++){
          await client.ensureSynced(true,[chatId],{personal:true});
          const history=await client.getChatMessagesWindow(chatId,{direction:'latest',limit:10,respectCompressionBoundary:false});
          if(history.messages.some(message=>message.role==='assistant')) {ready=true;break;}
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
        if(!ready)throw Error('Owned encrypted history not ready');
        const content={type:'code',code:'exact private reminder destination',language:'text',filename:'destination.txt'};
        const stored=await send('store_embed','store_embed_confirmed',{
          embed_id:embedId,chat_id:chatId,team_id:null,
          encrypted_content:await encrypt(JSON.stringify(content),embedKey),
          encrypted_type:await encrypt('code',embedKey),status:'finished',
          hashed_chat_id:hash(chatId),hashed_message_id:hash(messageId),hashed_user_id:hash(owner.id),
          created_at:now,updated_at:now,version_number:1
        });
        if(stored.embed_id!==embedId)throw Error('Embed not acknowledged');
        const keys=[{hashed_embed_id:hash(embedId),key_type:'master',hashed_chat_id:null,
          encrypted_embed_key:await encrypt(embedKey,client.getMasterKeyBytes()),hashed_user_id:hash(owner.id),created_at:now},
          {hashed_embed_id:hash(embedId),key_type:'chat',hashed_chat_id:hash(chatId),
          encrypted_embed_key:await encrypt(embedKey,chatKey),hashed_user_id:hash(owner.id),created_at:now}];
        const wrappers=await send('store_embed_keys','store_embed_keys_confirmed',{keys});
        if(wrappers.created_count!==2||wrappers.failed_count!==0)throw Error('Embed wrappers not acknowledged');
        const saved=await client.getEmbed(embedId,{preferCache:false,chatId});
        if(saved.content.code!==content.code)throw Error('Stored embed did not decrypt');
        process.stdout.write(JSON.stringify({chatId,embedId,messageId}));
      } finally {ws.close();}
    })().catch(error=>{console.error('Private notification fixture:',error.message);process.exit(1)});
  `;
  return JSON.parse(execFileSync('node', ['-e', source, path.join(path.dirname(CLI_DIST), 'index.js')], {
    cwd: path.resolve(__dirname, '../../../..'), env: workflowCliEnv(apiUrl(), home), encoding: 'utf8', timeout: 150_000,
  }).trim());
}

function apiUrl(): string {
  if (process.env.PLAYWRIGHT_TEST_API_URL) return process.env.PLAYWRIGHT_TEST_API_URL;
  const base = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  if (base.hostname === 'localhost' || base.hostname === '127.0.0.1') return 'http://localhost:8000';
  if (!base.hostname.startsWith('app.')) throw new Error('Set PLAYWRIGHT_TEST_API_URL for this test target');
  return `${base.protocol}//api.${base.hostname.slice(4)}`;
}

function noInferenceGraph() {
  return {
    version: 1,
    trigger_node_id: 'schedule',
    nodes: [
      { id: 'schedule', type: 'schedule_trigger', title: 'Daily start', config: { schedule: { type: 'daily', time: '09:00', timezone: 'UTC' } } },
      { id: 'approval', type: 'ask_user', title: 'Wait for approval', config: { prompt: 'Continue?', timeout_seconds: 600 } },
      { id: 'notify', type: 'send_notification', title: 'Show result', config: { title: 'Ready', body: 'Ready' } },
      { id: 'end', type: 'end', title: 'Done', config: {} }
    ],
    edges: [
      { from: 'schedule', to: 'approval' },
      { from: 'approval', to: 'notify' },
      { from: 'notify', to: 'end' }
    ]
  };
}

test.describe('Notification email destinations', () => {
  skipWithoutCredentials(test, email, password, otpKey);

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target,notifications.reminder-email.identifiable-default,notifications.reminder-email.durable-limited-context,chat-navigation.open.local-first-coherent
  test('opens a private embed after reload and cold login, creates an identifiable chat reminder, and shows a missing embed error', async ({ page }: { page: any }, testInfo: any) => {
    test.setTimeout(300_000);
    await page.setViewportSize({ width: 1280, height: 900 });
    const home = createWorkflowCliHome('notification-deep-link');
    let reminderId: string | null = null;
    let capturedHashWrites: unknown[] = [];
    await observeReminderTargetHashWrites(page);
    try {
      await loginWorkflowCliViaPair(page, apiUrl(), home, 'notification-deep-link');
      const target = seedPrivateLinkTarget(home);
      const hash = `#chat-id=${target.chatId}&embed-id=${target.embedId}&message-id=${target.messageId}`;
      const assertTarget = async () => {
        await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', target.chatId, { timeout: 45_000 });
        await expect(page.getByTestId('message-assistant').filter({ hasText: 'Notification destination is ready.' })).toBeVisible({ timeout: 45_000 });
        await expect(page.getByTestId('embed-fullscreen-container')).toBeVisible({ timeout: 30_000 });
        await expect(page.getByTestId('embed-fullscreen-container')).toContainText('exact private reminder destination');
        // Check the complete destination once chat and fullscreen navigation
        // have both committed; message DOM can render before that handoff ends.
        const selectedHash = new URL(page.url()).hash;
        capturedHashWrites = await reminderTargetHashWrites(page);
        expect(selectedHash).toContain(`chat-id=${target.chatId}`);
        expect(selectedHash).toContain(`embed-id=${target.embedId}`);
        expect(selectedHash).toContain(`message-id=${target.messageId}`);
        expect(new URL(page.url()).hash).toContain(`embed-id=${target.embedId}`);
      };
      await page.goto(getE2EDebugUrl(`/${hash}`), { waitUntil: 'domcontentloaded' });
      await assertTarget();
      await page.reload({ waitUntil: 'domcontentloaded' });
      await assertTarget();

      // Release all application DB handles before deleting browser state. The
      // backend retains only the owner-encrypted fixture, as on a new device.
      const origin = new URL(page.url()).origin;
      await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
      await page.goto('about:blank');
      const cdp = await page.context().newCDPSession(page);
      await cdp.send('Storage.clearDataForOrigin', { origin, storageTypes: 'indexeddb,local_storage' });
      await cdp.detach();
      await page.context().clearCookies();
      await page.goto(getE2EDebugUrl(`/${hash}`), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('tab-login')).toBeVisible({ timeout: 30_000 });
      expect(await page.evaluate(() => sessionStorage.getItem('pendingDeepLink'))).toContain(hash);
      await loginToTestAccount(page, () => {}, async () => {}, { preserveCurrentUrl: true });
      await assertTarget();

      // Create a real simple reminder from the decrypted owner-backed chat.
      // A future trigger avoids inference and scheduler timing in this check.
      await page.goto(getE2EDebugUrl(`/#chat-id=${target.chatId}`), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', target.chatId, { timeout: 30_000 });
      await page.getByTestId('chat-top-actions').getByRole('button', { name: 'More', exact: true }).click();
      await expect(page.getByTestId('chat-reminders-button')).toBeVisible({ timeout: 20_000 });
      await page.getByTestId('chat-reminders-button').click();
      const settings = page.getByTestId('settings-menu');
      await expect(settings).toBeVisible();
      await expect(settings.getByTestId('chat-context')).toHaveText('Private notification destination', { timeout: 20_000 });
      await expect(settings.getByRole('status').filter({ hasText: 'Reminder emails include identifying details' })).toContainText('Reminder emails include identifying details');
      await settings.getByTestId('settings-dropdown').nth(0).selectOption('this_chat');
      await settings.getByTestId('settings-dropdown').nth(1).selectOption('custom');
      const future = await page.evaluate(() => {
        const date = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000);
        return {
          date: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`,
          time: `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`,
        };
      });
      await settings.getByTestId('settings-reminder-date').fill(future.date);
      await settings.getByTestId('settings-reminder-time').fill(future.time);
      const requestPromise = page.waitForRequest((request: any) =>
        new URL(request.url()).pathname === '/v1/apps/reminder/skills/set-reminder' && request.method() === 'POST');
      const responsePromise = page.waitForResponse((response: any) =>
        new URL(response.url()).pathname === '/v1/apps/reminder/skills/set-reminder' && response.request().method() === 'POST');
      await settings.getByTestId('settings-button-primary').click();
      const reminderRequest = (await requestPromise).postDataJSON();
      expect(reminderRequest).toMatchObject({ chat_id: target.chatId, target_type: 'existing_chat', response_type: 'simple' });
      expect(reminderRequest.notification_context).toMatchObject({ version: 1, kind: 'chat', title: 'Private notification destination' });
      expect(reminderRequest.notification_context).not.toHaveProperty('messages');
      const createdReminder = await responsePromise;
      expect(createdReminder.ok(), await createdReminder.text()).toBe(true);
      const result = await createdReminder.json();
      reminderId = (result.data || result).reminder_id;
      expect(reminderId).toBeTruthy();
      await expect(settings.getByTestId('settings-info-box-success')).toBeVisible({ timeout: 20_000 });
      await page.getByTestId('icon-button-close').click();
      await expect(settings).toBeHidden();

      // Reopen the valid same-document target after reminder settings, then
      // request a different target while its real fullscreen is still open.
      await page.goto(getE2EDebugUrl(`/${hash}`), { waitUntil: 'domcontentloaded' });
      await assertTarget();
      const missingEmbedId = randomUUID();
      await page.goto(getE2EDebugUrl(`/#chat-id=${target.chatId}&embed-id=${missingEmbedId}`), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', target.chatId, { timeout: 30_000 });
      await expect(page.getByTestId('embed-fullscreen-loading')).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 });
      await expect(page.getByTestId('embed-fullscreen-loading').locator('.error')).toBeVisible();
      expect(new URL(page.url()).hash).toContain(`embed-id=${missingEmbedId}`);
    } finally {
      const latestHashWrites = await reminderTargetHashWrites(page);
      await testInfo.attach('reminder-target-hash-writes', {
        body: Buffer.from(JSON.stringify(latestHashWrites.length ? latestHashWrites : capturedHashWrites, null, 2)),
        contentType: 'application/json',
      });
      await attachRouteWriterSources(page, testInfo, latestHashWrites.length ? latestHashWrites : capturedHashWrites);
      if (reminderId) {
        const deleted = await page.request.delete(`${apiUrl()}/v1/settings/reminders/${reminderId}`);
        expect(deleted.ok(), await deleted.text()).toBe(true);
      }
      removeWorkflowCliHome(home);
    }
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
  test('preserves a complete private target from a cold signed-out browser through login without opening another chat', async ({ page }: { page: any }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1280, height: 900 });
    const chatId = randomUUID();
    const embedId = randomUUID();
    const messageId = randomUUID();
    const hash = `#chat-id=${chatId}&embed-id=${embedId}&message-id=${messageId}`;
    // Playwright's fresh per-test context has no account, IndexedDB or localStorage.
    // This inaccessible target must survive auth and fail visibly in its own context.
    await page.goto(getE2EDebugUrl(`/${hash}`), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('tab-login')).toBeVisible({ timeout: 30_000 });
    expect(await page.evaluate(() => sessionStorage.getItem('pendingDeepLink'))).toContain(hash);
    await loginToTestAccount(page, () => {}, async () => {}, { preserveCurrentUrl: true });
    await expect(page.getByText('This chat link is unavailable. It may have been deleted or belong to another account.', { exact: true })).toBeVisible({ timeout: 30_000 });
    const finalHash = new URL(page.url()).hash;
    expect(finalHash).toContain(`chat-id=${chatId}`);
    expect(finalHash).toContain(`embed-id=${embedId}`);
    expect(finalHash).toContain(`message-id=${messageId}`);
    await expect(page.getByTestId('active-chat-container')).not.toHaveAttribute('data-current-chat-id', /.+/);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.surface.semantic-parity,chat-navigation.open.local-first-coherent,workflows.execution.lifecycle-visible
  test('opens populated signed-in chat and exact Workflow run links', async ({ page }: { page: any }) => {
    test.setTimeout(120_000);
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page);

    // This browser-local fixture exercises the signed-in link destination. The
    // separate Mailpit probes check the actual email HTML and server delivery.
    const chatId = `e2e-email-link-${randomUUID()}`;
    const message = 'Notification link destination is populated.';
    await page.evaluate(async ({ chatId, message }) => {
      const seed = (window as Window & {
        __openmatesE2ESeedChat?: (input: {
          chat: Record<string, unknown>;
          messages: Record<string, unknown>[];
        }) => Promise<unknown>;
      }).__openmatesE2ESeedChat;
      if (!seed) throw new Error('E2E chat seed helper is unavailable');
      const now = Math.floor(Date.now() / 1000);
      await seed({
        chat: {
          chat_id: chatId, title: 'Notification link destination', messages_v: 1, title_v: 1,
          last_edited_overall_timestamp: now, created_at: now, updated_at: now
        },
        messages: [{
          message_id: `e2e-email-link-message-${chatId}`, chat_id: chatId,
          role: 'assistant', created_at: now, status: 'synced', content: message
        }]
      });
    }, { chatId, message });

    await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId, { timeout: 30_000 });
    await expect(page.getByTestId('message-assistant').filter({ hasText: message })).toBeVisible();

    await page.goto(getE2EDebugUrl('/#settings/notifications/chat'), { waitUntil: 'domcontentloaded' });
    const settings = page.getByTestId('settings-menu');
    await expect(settings).toBeVisible({ timeout: 20_000 });
    await expect(settings).toHaveAttribute('data-active-view', 'notifications/chat');
    await expect(settings.getByTestId('email-section')).toBeVisible();

    let workflowId: string | null = null;
    try {
      const created = await page.request.post(`${apiUrl()}/v1/workflows`, {
        data: { title: `Notification link ${randomUUID()}`, graph: noInferenceGraph(), enabled: true }
      });
      expect(created.ok(), await created.text()).toBe(true);
      workflowId = (await created.json()).workflow.id;
      const started = await page.request.post(`${apiUrl()}/v1/workflows/${workflowId}/run`, {
        data: { mode: 'test', input: {} },
        headers: { 'Idempotency-Key': `${workflowId}-notification-link` }
      });
      expect(started.ok(), await started.text()).toBe(true);
      const runId = (await started.json()).run.id;

      await page.goto(getE2EDebugUrl(`/#workflow-id=${encodeURIComponent(workflowId)}&workflow-tab=runs&run-id=${encodeURIComponent(runId)}`), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('workflow-run-selector').locator('select')).toHaveValue(runId, { timeout: 30_000 });
      const selectedRun = page.locator(`[data-testid="workflow-run-marker"][data-run-id="${runId}"]`);
      await expect(selectedRun).toBeVisible();
      await expect(selectedRun).toHaveAttribute('aria-pressed', 'true');
      await expect(selectedRun).toHaveAttribute('data-run-status', /^(queued|running|waiting|completed)$/);
      await expect(page.getByTestId('workflow-run-detail')).toBeVisible();
    } finally {
      if (workflowId) {
        const deleted = await page.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`);
        expect(deleted.ok(), await deleted.text()).toBe(true);
      }
    }
  });
});
