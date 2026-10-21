/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/** Browser contracts for public Apps navigation, natural-language requests and encrypted retention. */
export {};
import type { Page } from '@playwright/test';
import { assertGuestHeaderControlsSeparated } from './helpers/header-layout';
import { assertWorkspaceNavigationItems } from './helpers/workspace-navigation';
import { ALL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, submitPasswordAndHandleOtp } = require('./helpers/chat-test-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { getE2EDebugUrl, getTestAccount, withMockMarker } = require('./signup-flow-helpers');

type SkillFixture = {
  app_id: string;
  skill_id: string;
  name: string;
  primary_fields: string[];
  anonymous_allowed: boolean;
  requestEnvelope?: boolean;
  relevanceCriteria?: boolean;
};


// Keep startup exceptions available when the app fails before login can render.
// Deliberately exclude ordinary console output, argument objects and HTTP bodies.
const appsRuntimeErrors = new WeakMap<Page, Array<{ source: string; message: string; stack?: string }>>();
function safeRuntimeError(value: string): string {
  return value
    .replace(/https?:\/\/[^\s)]+/g, raw => {
      try { const url = new URL(raw); return `${url.origin}${url.pathname}`; } catch { return '[url]'; }
    })
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, '[email]')
    .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/\b(?:access_token|refresh_token|api_key|password|authorization|cookie)\b\s*[:=]\s*[^\s,;]+/gi, '[credential redacted]')
    .replace(/\b[A-Za-z0-9_+/=-]{48,}\b/g, '[long value redacted]')
    .replace(/\{\s*["'][\s\S]*/, '[structured payload omitted]')
    .slice(0, 700);
}
test.beforeEach(async ({ page }: { page: Page }) => {
  const records: Array<{ source: string; message: string; stack?: string }> = [];
  appsRuntimeErrors.set(page, records);
  const capture = (source: string, message: string, stack?: string) => {
    if (records.length >= 16) return;
    const entry = { source, message: safeRuntimeError(message.split('\n')[0]),
      ...(stack ? { stack: stack.split('\n').filter(line => /^\s*at\s/.test(line)).slice(0, 6).map(safeRuntimeError).join('\n') } : {}) };
    if (!records.some(record => record.source === entry.source && record.message === entry.message)) records.push(entry);
  };
  page.on('pageerror', error => capture('pageerror', `${error.name}: ${error.message}`, error.stack));
  page.on('console', message => {
    if (!['error', 'warning'].includes(message.type())) return;
    const firstLine = message.text().split('\n')[0];
    if (/^\[(?:ChatSyncService:Senders|MessageInput|handleSend)\]/.test(firstLine)) {
      capture(`sender.${message.type()}`, firstLine.replace(/\b[0-9a-f]{8}-[0-9a-f-]{27,}\b/gi, '[id]'));
      return;
    }
    if (/(?:InternalError|ReferenceError|TypeError|SyntaxError|RangeError|Uncaught|Cannot access .{0,120} before initialization|Failed to fetch dynamically imported module|Failed to load module script|\[svelte\].*(?:error|exception))/i.test(firstLine)) {
      capture('console.error', firstLine);
    }
  });
});
test.afterEach(async ({ page }: { page: Page }, testInfo: { status?: string; expectedStatus?: string; attach: (name: string, options: { body: string; contentType: string }) => Promise<void> }) => {
  const records = appsRuntimeErrors.get(page) ?? [];
  appsRuntimeErrors.delete(page);
  if (testInfo.status === testInfo.expectedStatus) return;
  if (records.length) {
    const body = JSON.stringify(records, null, 2);
    await testInfo.attach('apps-client-runtime-errors', { body, contentType: 'application/json' });
    console.info(`[Apps client runtime errors] ${JSON.stringify(records)}`);
  }
  // Capture lifecycle stages and counts, never draft prose, IDs or attachment data.
  const handoff = await page.evaluate(() => {
    const diagnosticWindow = window as typeof window & {
      __openmatesAppsHandoffDebug?: string[];
      __openmatesLastSendDebug?: { step?: string; details?: Record<string, unknown> };
      __openmatesMessageInputDraftDiagnostics?: Array<Record<string, unknown>>;
      __openmatesSendPrepPhases?: Array<{ phase?: unknown; ms?: unknown }>;
      __openmatesLastChatKeyGuardDebug?: { reason?: unknown; teamScoped?: unknown; candidateCount?: unknown };
    };
    const send = diagnosticWindow.__openmatesLastSendDebug;
    const safeLabel = (value: unknown) => typeof value === 'string' && /^[a-z0-9._:-]{1,100}$/i.test(value) ? value : null;
    const error = send?.details?.error;
    const exceptionNames = new Set(['Error', 'TypeError', 'RangeError', 'ReferenceError', 'SyntaxError',
      'AbortError', 'TimeoutError', 'InvalidStateError', 'SecurityError', 'ChatKeyNotReadyError']);
    const errorName = error && typeof error === 'object' && 'name' in error ? error.name : undefined;
    const errorMessage = error && typeof error === 'object' && 'message' in error ? error.message : undefined;
    // Fixed classifications only: exception prose can contain private IDs/data.
    const staticFailures = new Map([
      ['Personal privacy owner unavailable', 'privacy_owner_unavailable'],
      ['Personal privacy owner changed while saving preferences', 'privacy_owner_changed'],
      ['Personal privacy freshness check failed', 'privacy_freshness_rejected'],
      ['Personal privacy connection changed', 'privacy_connection_changed'],
      ['Personal privacy freshness check timed out', 'privacy_freshness_timeout'],
      ['Personal privacy freshness request could not be sent', 'privacy_request_unsent'],
      ['Personal privacy full snapshot owner changed', 'privacy_snapshot_owner_changed'],
      ['Personal privacy session expired before send', 'privacy_session_expired'],
      ['Personal privacy full snapshot unavailable', 'privacy_snapshot_unavailable'],
      ['Personal privacy full snapshot owner unavailable', 'privacy_snapshot_owner_unavailable'],
      ['Personal privacy snapshot is invalid', 'privacy_snapshot_invalid'],
      ['Personal privacy decryption failed', 'privacy_decryption_failed'],
      ['Personal privacy entry is invalid', 'privacy_entry_invalid'],
      ['Personal privacy snapshot is missing encrypted row content', 'privacy_snapshot_content_missing'],
      ['Personal privacy receipt does not match this turn', 'privacy_receipt_mismatch'],
      ['Personal privacy unchanged response has no matching prepared snapshot', 'privacy_unchanged_mismatch'],
      ['Personal privacy changes are not yet confirmed by the server; retry after saving them', 'privacy_mutations_unconfirmed'],
      ['Personal privacy scope changed during freshness check', 'privacy_scope_changed'],
      ['Personal privacy owner or preferences changed before filtering', 'privacy_filter_scope_changed'],
      ['Personal privacy session expired before transmission', 'privacy_transmission_session_expired'],
      ['Personal privacy changed after the encrypted turn was prepared; retry this message', 'privacy_prepared_changed'],
      ['Personal privacy owner changed before transmission', 'privacy_transmission_owner_changed'],
      ['The previous encrypted reply has not been saved. Retry this message after recovery.', 'predecessor_not_saved'],
      ['Cannot bind a settled encrypted chat turn.', 'turn_already_settled'],
      ['Encrypted chat turn identity changed.', 'turn_identity_changed'],
      ['Pending chat admission needs a compatible server connection for exact-ID retry.', 'admission_connection_incompatible'],
      ['Durable chat preflight requires encrypted user content.', 'preflight_content_missing'],
      ['Durable turn preflight requires an authenticated account.', 'preflight_account_missing'],
      ['Retained encrypted turn preflight has a stale canonical version.', 'preflight_version_stale'],
      ['Personal chat timestamp is invalid.', 'personal_timestamp_invalid'],
    ]);
    const errorCode = typeof errorMessage !== 'string' ? null
      : staticFailures.get(errorMessage)
        ?? (/^(?:Cannot read properties of (?:null|undefined) \(reading ['"]chat_id['"]\))$/.test(errorMessage)
          ? 'chat_record_unavailable'
          : /^Saved chat [0-9a-f-]+ has no safe chat key for required embed storage\.?$/i.test(errorMessage)
            ? 'embed_key_not_ready'
            : /^Saved chat [0-9a-f-]+ has no encrypted chat key for durable preflight\.?$/i.test(errorMessage)
              ? 'preflight_encrypted_key_missing'
              : /^Saved chat [0-9a-f-]+ has no safe chat key for durable preflight\.?$/i.test(errorMessage)
                ? 'preflight_key_not_ready' : 'other');
    // Capture only source-owned code paths and coordinates, never the first
    // exception line or arbitrary URL/query/fragment/function payloads.
    const rawStack = error && typeof error === 'object' && 'stack' in error && typeof error.stack === 'string'
      ? error.stack : '';
    const codeFrames = rawStack.split('\n').slice(1).flatMap(line => {
      if (!/^\s*at\s/.test(line)) return [];
      const frame = line.match(/\/(?:_app\/immutable\/(?:chunks|nodes)\/[A-Za-z0-9._-]+\.js|src\/(?:components|services|stores|utils|routes)\/[A-Za-z0-9_./+[\]-]+\.(?:svelte|ts|js)):\d+:\d+(?=[)\s]|$)/);
      return frame ? [frame[0].replace(/^\//, '')] : [];
    }).slice(0, 5);
    const keyGuard = diagnosticWindow.__openmatesLastChatKeyGuardDebug;
    const guardReasons = new Set(['candidate_keys_pending', 'fingerprint_mismatch', 'anonymous_key_unwrap_failed',
      'anonymous_key_mismatch', 'encrypted_key_missing', 'persisted_key_unwrap_failed', 'persisted_key_mismatch']);
    const editors = Array.from(document.querySelectorAll<HTMLElement>('.ProseMirror'));
    const activeEditorChatId = editors[0]?.closest('[data-current-chat-id]')?.getAttribute('data-current-chat-id');
    return {
      phases: (diagnosticWindow.__openmatesAppsHandoffDebug ?? []).slice(-24).map(safeLabel),
      sendStep: safeLabel(send?.step),
      sendFailure: send?.step === 'send_failed' ? {
        failedAfterStep: safeLabel(send.details?.failedAfterStep),
        errorName: typeof errorName === 'string' && exceptionNames.has(errorName) ? errorName : null,
        errorCode,
        codeFrames,
      } : null,
      // The guard has no send identity/timestamp; this is only the last observed failure.
      // Never capture exception messages, chat IDs, keys or private result context.
      lastObservedKeyGuard: keyGuard ? {
        reason: typeof keyGuard.reason === 'string' && guardReasons.has(keyGuard.reason) ? keyGuard.reason : null,
        teamScoped: keyGuard.teamScoped === true,
        candidateCount: typeof keyGuard.candidateCount === 'number' && Number.isSafeInteger(keyGuard.candidateCount)
          && keyGuard.candidateCount >= 0 && keyGuard.candidateCount <= 1000 ? keyGuard.candidateCount : null,
      } : null,
      sendPreparation: (diagnosticWindow.__openmatesSendPrepPhases ?? []).slice(-80).map(row => ({
        phase: safeLabel(row.phase), ms: typeof row.ms === 'number' && Number.isFinite(row.ms) ? row.ms : null,
      })),
      sendFlags: Object.fromEntries(Object.entries(send?.details ?? {}).filter(([key, value]) =>
        /^[a-zA-Z][a-zA-Z0-9_]{0,80}$/.test(key) && (typeof value === 'boolean' || typeof value === 'number'))),
      drafts: (diagnosticWindow.__openmatesMessageInputDraftDiagnostics ?? []).slice(-20).map(row => ({
        event: safeLabel(row.event), hasEditor: row.hasEditor === true,
        hasDraftContent: row.hasDraftContent === true,
        version: typeof row.version === 'number' ? row.version : null,
        textLength: typeof row.textLength === 'number' ? row.textLength : null,
        reason: safeLabel(row.reason),
        matchingChat: typeof row.chatId === 'string' && row.chatId === row.currentChatId,
        matchingActiveEditor: typeof row.chatId === 'string' && row.chatId === activeEditorChatId,
      })),
      editors: editors.map(editor => ({ textLength: editor.innerText.length,
        hasChatId: !!editor.closest('[data-current-chat-id]')?.getAttribute('data-current-chat-id') })),
      userMessageCount: document.querySelectorAll('[data-testid="message-user"]').length,
    };
  }).catch(() => ({ captureUnavailable: true }));
  await testInfo.attach('apps-handoff-lifecycle', { body: JSON.stringify(handoff, null, 2), contentType: 'application/json' });
  console.info(`[Apps handoff lifecycle] ${JSON.stringify(handoff)}`);
});

async function fixtureInterpreter(page: any, appId: string, skillId: string, input: (text: string) => Record<string, unknown>): Promise<void> {
  await page.route('**/v1/apps/workspace/interpret', (route: any) => {
    const request = route.request().postDataJSON();
    expect(request.app_id).toBe(appId);expect(request.request_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(request.timezone).toBeTruthy();expect(request.locale).toBeTruthy();
    return route.fulfill({json:{action:'execute',request_id:request.request_id,skill_id:skillId,input:input(request.text)}});
  });
}

const requestComposer = (page: any) => page.getByTestId('apps-detail-fullscreen').getByTestId('apps-request-composer');
async function openRecent(page: any): Promise<void> { await page.getByTestId('apps-tab-recent').click(); }

async function fixtureSkillDetails(page: any, fixture: SkillFixture): Promise<void> {
  const { app_id, skill_id, name, primary_fields, anonymous_allowed, requestEnvelope, relevanceCriteria } = fixture;
  await fixtureInterpreter(page,app_id,skill_id,text=>requestEnvelope?{requests:[{query:text,count:10}]}:{query:text,location:'Berlin',limit:5});
  await page.route(`**/v1/apps/${app_id}/skills/${skill_id}/details`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        app_id,
        skill_id,
        slug: skill_id.replaceAll('_', '-'),
        name,
        name_translation_key: `${app_id}.${skill_id}.name`,
        description: `${name} fixture description`,
        description_translation_key: `${app_id}.${skill_id}.description`,
        icon_image: null,
        input_schema: requestEnvelope ? {
          type: 'object', required: ['requests'], properties: { requests: {
            type: 'array', minItems: 1, 'x-ui': { basic: true }, items: {
              type: 'object', required: ['query'], properties: {
                query: { type: 'string', title: 'Query', minLength: 1, 'x-ui': { basic: true } },
                count: { type: 'integer', title: 'Count', default: 10, minimum: 1, maximum: 20, 'x-ui': { basic: true } },
                ...(relevanceCriteria ? { relevance_criteria: { type: 'string', title: 'Relevance criteria', maxLength: 1000, 'x-ui': { basic: true } } } : {}),
              },
            },
          } },
        } : {
          type: 'object',
          properties: {
            query: { type: 'string', title: 'Query', minLength: 1 },
            location: { type: 'string', title: 'Location' },
            limit: { type: 'integer', title: 'Limit', minimum: 1, maximum: 10 },
          },
          required: ['query'],
        },
        primary_fields: requestEnvelope ? ['requests[].query', 'requests[].count'] : primary_fields,
        defaults: requestEnvelope ? { requests: [{ count: 10 }] } : { location: 'Berlin', limit: 5 },
        pricing: null,
        providers: [],
        models: [],
        anonymous_allowed,
        execution_available: true,
        unavailable_reason: null,
        execution_mode: 'sync',
      }),
    });
  });
}

function appHash(page: any): string {
  return new URL(page.url()).hash.split('&', 1)[0];
}

function expectPersonalPageQuery(params: URLSearchParams | undefined, appId: string, offset: number): void {
  expect(params?.get('app_id')).toBe(appId);
  expect(params?.get('offset')).toBe(String(offset));
  expect(params?.get('limit')).toBe('20');
  expect(params?.has('team_id')).toBe(false);
}

async function assertProfileInHeader(page: any): Promise<void> {
  const profile = page.getByTestId('profile-container');
  await expect(profile).toBeVisible();
  await profile.evaluate(async (element: Element) => {
    const wrapper = element.closest('.profile-container-wrapper');
    if (wrapper) await Promise.all(wrapper.getAnimations().map(animation => animation.finished.catch(() => {})));
  });
  const header = await page.locator('header').first().boundingBox();
  const account = await profile.boundingBox();
  expect(account.y).toBeGreaterThanOrEqual(header.y);
  expect(account.y + account.height).toBeLessThanOrEqual(header.y + header.height + 4);
}

test.describe('Apps workspace', () => {
  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.navigation.hash-and-forwarding,apps.presentation.shared-detail-and-recency,workspace-shell.start.shared-affordances
  test('Show all replaces the home with the shared searchable grid and restores it after app close', async ({ page }: { page: any }) => {
    test.setTimeout(90000);
    for (const width of [1180, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(getE2EDebugUrl('/#apps/all'), { waitUntil: 'domcontentloaded' });
      const grid = page.getByTestId('apps-all-items-grid');
      await expect(grid).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('apps-all-items-toolbar')).toBeVisible();
      await page.getByTestId('apps-back-to-recent').click();
      await expect.poll(() => appHash(page)).toBe('#apps');
      await expect(page.getByTestId('apps-daily-inspiration-area')).toBeVisible();
      const homeCard = page.getByTestId('apps-app-card').getByTestId('app-store-card').filter({ hasText: /Web/i }).first();
      await expect(homeCard).toBeVisible();
      if (width === 1180) await expect(homeCard).toHaveCSS('height', '129px');
      else await expect(homeCard).toHaveCSS('height', '44px');

      await page.getByTestId('apps-show-all').click();
      await expect.poll(() => appHash(page)).toBe('#apps/all');
      await expect(grid).toBeVisible();
      await expect(grid).toHaveCSS('display', 'grid');
      await expect(page.getByTestId('apps-daily-inspiration-area')).toHaveCount(0);
      await expect(page.getByTestId('apps-home-apps')).toHaveCount(0);
      await expect(page.getByRole('heading', { name: 'What app do you want to use?' })).toHaveCount(0);
      await expect(page.locator('.workspace-composer-slot, .ProseMirror, textarea')).toHaveCount(0);
      await expect(page.getByTestId('apps-search')).toHaveText('Search');
      await page.getByTestId('apps-search').click();
      const controls = page.locator('.search-sort-bar');
      const search = controls.getByRole('textbox');
      await expect(search).toBeFocused();
      await search.fill('Brave');
      const web = grid.locator('[data-app-id="web"]');
      await expect(web).toBeVisible();
      await expect(web).toHaveClass(/app-store-card/);
      await expect(web.getByTestId('app-card-name')).toHaveCSS('text-align', 'left');
      await expect(grid.locator('[data-app-id="health"]')).toHaveCount(0);
      await search.fill('no-app-matches-this-query-7295');
      await expect(grid.getByTestId('apps-all-item')).toHaveCount(0);
      await expect(page.getByTestId('apps-all-items-empty')).toHaveText(/No apps found/i);
      await search.fill('');
      await controls.getByRole('combobox', { name: 'Sort', exact: true }).selectOption('name_asc');
      const names = await grid.getByTestId('app-card-name').allTextContents();
      expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
      await expect(grid.locator('[data-app-id="weather"]')).toHaveCount(1);
      await controls.getByRole('combobox', { name: 'Filter', exact: true }).selectOption('focus_modes');
      await expect(web).toBeVisible();
      await expect(grid.locator('[data-app-id="health"]')).toHaveCount(1);
      await expect(grid.locator('[data-app-id="weather"]')).toHaveCount(0);
      await web.click();
      await expect.poll(() => appHash(page)).toBe('#apps/web');
      await expect(page.getByTestId('apps-detail-fullscreen')).toBeVisible();
      await page.getByTestId('apps-detail-close').click();
      await expect.poll(() => appHash(page)).toBe('#apps/all');
      await expect(grid).toBeVisible();
      await expect(controls.getByRole('combobox', { name: 'Filter', exact: true })).toHaveValue('focus_modes');
      await page.getByTestId('apps-back-to-recent').click();
      await expect.poll(() => appHash(page)).toBe('#apps');
      await expect(homeCard).toBeVisible();
      await page.goBack();
      await expect.poll(() => appHash(page)).toBe('#apps/all');
      await expect(grid).toBeVisible();
      await page.goForward();
      await expect.poll(() => appHash(page)).toBe('#apps');
      await expect(page.getByTestId('apps-home-apps')).toBeVisible();
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.navigation.hash-and-forwarding
  test('guest browses compact skill URLs, then Back, Forward and close restore the parent',async({page}:{page:any})=>{
    test.setTimeout(90000);
    await page.setViewportSize({width:390,height:844});
    await page.goto(getE2EDebugUrl('/#apps'),{waitUntil:'domcontentloaded'});
    await expect(page.getByTestId('apps-workspace-home')).toBeVisible({timeout:30000});
    await expect(page.getByTestId('workspace-mobile-select')).toHaveValue('/#apps');
    await page.getByTestId('apps-app-card').filter({hasText:/Health/i}).first().click();await expect.poll(()=>appHash(page)).toBe('#apps/health');
    await expect(requestComposer(page)).toBeVisible();await expect(page.getByTestId('apps-skill-form')).toHaveCount(0);
    await expect(page.getByTestId('apps-sidebar-toggle')).toHaveCount(0);const sidebarToggle=page.getByTestId('global-header').getByTestId('sidebar-toggle');await sidebarToggle.click();await expect(page.getByTestId('apps-sidebar')).toBeVisible();await sidebarToggle.click();await expect(page.getByTestId('apps-sidebar')).toHaveCount(0);
    await page.evaluate(()=>{window.location.hash='#apps/health/search-appointments';});await expect(requestComposer(page)).toBeVisible();
    await page.goBack();await expect.poll(()=>appHash(page)).toBe('#apps/health');await page.goForward();await expect.poll(()=>appHash(page)).toBe('#apps/health/search-appointments');
    await page.getByTestId('apps-detail-close').click();await expect.poll(()=>appHash(page)).toBe('#apps/health');
    await page.goto(getE2EDebugUrl('/apps/health/search-appointments'),{waitUntil:'domcontentloaded'});await expect(requestComposer(page)).toBeVisible({timeout:30000});
    expect(appHash(page)).toBe('#apps/health/search-appointments');await page.reload({waitUntil:'domcontentloaded'});await expect(requestComposer(page)).toBeVisible({timeout:30000});
    await page.getByTestId('apps-detail-close').click();await expect.poll(()=>appHash(page)).toBe('#apps/health');
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.public-daily,apps.results.shared-fullscreen,apps.presentation.shared-detail-and-recency
  test('public News recommendation cards open the selected article with News identity and return to News', async ({ page }: { page: any }) => {
    const now=Math.floor(Date.now()/1000);
    const first='Synthetic city science report';const second='Synthetic ocean science report';
    await page.route('**/v1/apps/workspace/public/news*',(route:any)=>route.fulfill({json:{cta:null,recommendations:[{id:'92000000-0000-4000-8000-000000000001',skill_id:'search',created_at:now,expires_at:now+3600,input:{requests:[{query:'Science reports'}]},result:{data:{results:[{results:[{type:'search_result',title:first,url:'https://example.test/city-science',description:'City research article',thumbnail:{original:'https://example.test/news-one.png'}},{type:'search_result',title:second,url:'https://example.test/ocean-science',description:'Ocean research article',thumbnail:{original:'https://example.test/news-two.png'}}]}]}}}]}}));
    await page.goto(getE2EDebugUrl('/#apps/news'),{waitUntil:'domcontentloaded'});
    const carousel=page.getByTestId('apps-preview-carousel');await expect(carousel.getByTestId('embed-preview')).toHaveCount(2);
    const selected=carousel.getByTestId('embed-preview').filter({hasText:second});await expect(selected).toContainText('Ocean research article');await expect(selected).toHaveAttribute('data-app-id','news');
    await selected.click();const article=page.getByTestId('apps-recommendation-fullscreen');await expect(article).toBeVisible();await expect(article.getByTestId('embed-header-title')).toHaveText(second);await expect(article.locator('[data-app-icon="news"]')).toBeVisible();
    await page.evaluate(()=>{window.open=((url,target,features)=>{(window as Window&{appsOpenedNewsArticle?:string[]}).appsOpenedNewsArticle=[String(url),String(target),String(features)];return null;}) as typeof window.open;});await article.getByRole('button',{name:'Open on example.test',exact:true}).click();expect(await page.evaluate(()=>(window as Window&{appsOpenedNewsArticle?:string[]}).appsOpenedNewsArticle)).toEqual(['https://example.test/ocean-science','_blank','noopener,noreferrer']);await expect(article.getByTestId('search-template-grid')).toHaveCount(0);await expect(article.getByText(first,{exact:true})).toHaveCount(0);
    await article.getByTestId('embed-minimize').click();await expect(page.getByTestId('apps-recommendation-fullscreen')).toHaveCount(0);await expect.poll(()=>appHash(page)).toBe('#apps/news');await expect(carousel.getByTestId('embed-preview')).toHaveCount(2);
  });

  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding
  test('app, skill, focus and memory detail close restore an example chat origin', async ({ page }: { page: any }) => {
    const exampleChatId = 'example-gigantic-airplanes';
    expect(ALL_EXAMPLE_CHATS.map(chat => chat.chat_id)).toContain(exampleChatId);
    const origin = `#chat-id=${exampleChatId}`;
    for (const path of ['health', 'health/search-appointments', 'health/focus/care-plan', 'health/memory/medical-history']) {
      await page.goto(getE2EDebugUrl(`/#apps/${path}&origin=${encodeURIComponent(origin)}`), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('apps-detail-fullscreen')).toBeVisible({ timeout: 30000 });
      if (path === 'health') {
        await page.getByTestId('apps-settings-open').click();
        await expect(page.getByTestId('settings-menu')).toBeVisible();
        await expect.poll(() => new URLSearchParams(new URL(page.url()).hash.split('&').slice(1).join('&')).get('origin')).toBe(origin);
        await page.getByTestId('icon-button-close').click();
        await expect(page.getByTestId('settings-menu')).not.toBeVisible();
        await page.reload({ waitUntil: 'domcontentloaded' });
        await expect(page.getByTestId('apps-detail-fullscreen')).toBeVisible({ timeout: 30000 });
      }
      await page.getByTestId('apps-detail-close').click();
      await expect.poll(() => new URL(page.url()).hash).toBe(origin);
      await expect(page.getByTestId('chat-close-button')).toBeVisible({ timeout: 30000 });
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding
  test('opaque page origin survives reload and close returns to its first-party path', async ({ page }: { page: any }) => {
    await page.goto(getE2EDebugUrl('/#apps'), { waitUntil: 'domcontentloaded' });
    const token = 'a'.repeat(32);
    const sharePath = '/share/chat/fictional-share#key=fixture-only';
    await page.evaluate(({ token, sharePath }: { token: string; sharePath: string }) =>
      sessionStorage.setItem(`openmates:apps-origin:${token}`, sharePath), { token, sharePath });
    await page.goto(getE2EDebugUrl(`/#apps/health&origin-ref=${token}`), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-detail-fullscreen')).toBeVisible({ timeout: 30000 });
    expect(page.url()).not.toContain('fixture-only');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByTestId('apps-detail-close').click();
    await expect.poll(() => new URL(page.url()).pathname + new URL(page.url()).hash).toBe(sharePath);
  });

  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.requests.natural-language,apps.navigation.hash-and-forwarding
  test('real public skill schema loads after cold boot and leaving Apps cannot reopen the detail', async ({ page }: { page: any }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(getE2EDebugUrl('/#apps'), { waitUntil: 'domcontentloaded' });
    await page.evaluate(async () => {
      localStorage.clear();
      for (const database of await indexedDB.databases()) {
        if (database.name) indexedDB.deleteDatabase(database.name);
      }
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-workspace-home')).toBeVisible({ timeout: 30000 });
    const card = page.getByTestId('apps-app-card').filter({ hasText: /Web/i }).first();
    await expect(card.getByTestId('app-store-card')).toBeVisible();
    await assertProfileInHeader(page);
    await page.getByTestId('profile-container').click();
    await expect(page.getByTestId('settings-menu')).toBeVisible();
    await page.getByTestId('icon-button-close').click();
    await expect(page.getByTestId('settings-menu')).not.toBeVisible();

    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      const selector = page.getByTestId('workspace-mobile-select');
      const login = page.getByTestId('header-login-signup-btn');
      await expect(login).toBeVisible();
      await expect(login).toContainText(/Login|Sign\s*up/i);
      await expect(selector).toBeVisible();
      await assertGuestHeaderControlsSeparated(page, true);
      const appsUrl = page.url();
      await login.click();
      const signupLayer = page.locator('.apps-auth-layer');
      await expect(signupLayer).toBeVisible();
      // The signup icon artwork must not intercept the phone close control.
      await signupLayer.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(signupLayer).toHaveCount(0);
      expect(page.url()).toBe(appsUrl);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });

    // Keep this endpoint real: fixtures cannot prove deployed CORS admission.
    const details = page.waitForResponse((response: any) => response.url().includes('/v1/apps/web/skills/search/details') && response.request().method() === 'GET');
    await page.getByTestId('apps-nav-link').click();
    await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
    await page.evaluate(async (api:string)=>{const response=await fetch(api+'/v1/apps/web/skills/search/details',{credentials:'include'});if(!response.ok)throw new Error('Public skill metadata unavailable');},deriveApiUrl(page.url()));
    expect((await details).status()).toBe(200);
    await expect(requestComposer(page)).toBeVisible({ timeout: 30000 });
    await assertProfileInHeader(page);
    await expect(page.getByText('The skill details could not be loaded.', { exact: true })).toHaveCount(0);
    const hero = page.getByTestId('apps-hero-icon');
    await expect(hero).toHaveAttribute('aria-hidden', 'true');
    await expect(hero).toHaveCSS('pointer-events', 'none');
    const iconBounds = await hero.boundingBox();
    await page.mouse.click(iconBounds.x + iconBounds.width / 2, iconBounds.y + iconBounds.height / 2);
    expect(appHash(page)).toBe('#apps/web/search');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('globalChatSelected', { detail: { chat_id: 'background-restoration' } })));
    expect(appHash(page)).toBe('#apps/web/search');
    await page.getByTestId('chats-nav-link').click();
    await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
    expect(appHash(page)).not.toMatch(/^#apps/);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('chats-nav-link')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
    expect(appHash(page)).not.toMatch(/^#apps/);
  });

  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding,apps.requests.natural-language,apps.execution.direct-shared-contract,apps.results.web-retained-graph,workspace-shell.nav.released-surfaces-visible
  test('login from a skill preserves its route and input, then Chats exits Apps on desktop and mobile', async ({ page }: { page: any }) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    const credentials = getTestAccount();
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: false,
    });
    await page.goto(getE2EDebugUrl('/#apps/web/search&tab=overview'), { waitUntil: 'domcontentloaded' });
    const initialUrl = page.url();
    const query = requestComposer(page).getByTestId('apps-request-textarea');
    await expect(query).toBeVisible({ timeout: 30000 });
    await query.fill('gpt 6 astra');
    await page.evaluate(() => { (window as Window & { appsLoginDocument?: string }).appsLoginDocument = 'same-document'; });
    await page.getByTestId('header-login-signup-btn').click();
    await expect(page.locator('.apps-auth-layer')).toBeVisible();
    await page.getByTestId('tab-login').click();
    await page.getByTestId('login-email-input').fill(credentials.email);
    if (!await page.locator('#stayLoggedIn').isChecked()) {
      await page.locator('label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)').click();
    }
    await expect(page.getByTestId('login-continue-button')).toBeEnabled();
    await page.getByTestId('login-continue-button').click();
    await expect(page.getByTestId('login-password-input')).toBeVisible({ timeout: 15000 });
    await page.getByTestId('login-password-input').fill(credentials.password);
    await submitPasswordAndHandleOtp(page, credentials.otpKey);
    await expect(page.locator('.apps-route')).toHaveAttribute('data-authenticated', 'true');
    await expect(page.locator('.apps-auth-layer')).toHaveCount(0);
    await expect(page.getByTestId('header-login-signup-btn')).toBeHidden();
    expect(page.url()).toBe(initialUrl);
    expect(await page.evaluate(() => (window as Window & { appsLoginDocument?: string }).appsLoginDocument)).toBe('same-document');
    await expect(query).toHaveValue('gpt 6 astra');
    await expect(page.getByTestId('apps-request-submit').first()).toBeVisible();
    // Exercise the retained request immediately after login, before visiting
    // another route or reloading to fill in any missing session state.
    let skillPosts = 0;
    await page.route('**/v1/apps/web/skills/search', (request: any) => {
      skillPosts += 1;
      expect(request.request().postDataJSON().query).toBe('gpt 6 astra');
      return request.fulfill({ json: { success: true, data: { results: [{ id: 'request-1', results: [{
        type: 'search_result', title: 'Saved search after login', url: 'https://example.test/apps/login-return',
        description: 'Safe result fixture after authentication.',
      }] }] } } });
    });
    await page.getByTestId('apps-request-submit').first().click();
    await expect(page.getByTestId('apps-result-fullscreen')).toContainText('Saved search after login',{timeout:30000});
    const grid=page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid');await expect(grid.getByTestId('embed-preview')).toHaveCount(1);
    const childUrl = page.url();
    expect(childUrl).toMatch(/&embed-id=[0-9a-f-]{36}/i);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-result-fullscreen')).toContainText('Saved search after login', { timeout: 30000 });
    await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(1);
    expect(page.url()).toBe(childUrl);
    expect(skillPosts).toBe(1);
    await expect(page.getByText('The request could not finish. You can try again.', { exact: true })).toHaveCount(0);
    await page.getByTestId('apps-result-fullscreen').getByTestId('embed-minimize').click();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      if (width === 1440) await page.getByTestId('apps-nav-link').click();
      else await page.getByTestId('workspace-mobile-select').selectOption('/#apps');
      await expect(page.getByTestId('apps-workspace-home')).toBeVisible({ timeout: 30000 });
      await assertProfileInHeader(page);
      if (width === 1440) {
        await assertWorkspaceNavigationItems(page, 'desktop', [
          'chats-nav-link', 'apps-nav-link', 'projects-nav-link', 'tasks-nav-link', 'workflows-nav-link',
        ]);
      } else {
        await assertWorkspaceNavigationItems(page, 'mobile', [
          '/', '/#apps', '/#projects', '/#tasks', '/#workflows',
        ]);
      }
      await page.getByTestId('apps-app-card').getByTestId('app-store-card').filter({ hasText: /Web/i }).first().click();
      await expect(requestComposer(page)).toBeVisible({ timeout: 30000 });
      await assertProfileInHeader(page);
      if (width === 1440) await page.getByTestId('chats-nav-link').click();
      else await page.getByTestId('workspace-mobile-select').selectOption('/');
      await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
      await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30000 });
      await expect(page.locator('.ProseMirror')).toBeVisible({ timeout: 30000 });
      expect(appHash(page)).not.toMatch(/^#apps/);
      await page.goBack();
      await expect(requestComposer(page)).toBeVisible({ timeout: 30000 });
      await page.goForward();
      await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
      expect(appHash(page)).not.toMatch(/^#apps/);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding,apps.presentation.shared-detail-and-recency,workspace-shell.start.chat-visual-parity
  test('Apps keeps shared gutters and safely exits to Chats while Settings closes', async ({ page }: { page: any }) => {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
      const fullscreen = page.getByTestId('apps-detail-fullscreen');
      await expect(fullscreen).toBeVisible({ timeout: 30000 });
      const main = page.locator('.apps-route-body > main');
      const header = await page.getByTestId('global-header').boundingBox();
      const bounds = await main.boundingBox();
      const geometry = await main.evaluate((element: Element) => ({
        scrollX: window.scrollX,
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        ancestors: [element, element.parentElement, element.closest('.apps-route'), document.body].map(node => {
          const box = node.getBoundingClientRect();
          const style = getComputedStyle(node);
          return { className: node.className, x: box.x, width: box.width, position: style.position, transform: style.transform,
            scrollLeft: node.scrollLeft, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, overflowX: style.overflowX };
        }),
      }));
      await test.info().attach(`apps-layout-${width}`, { body: JSON.stringify(geometry), contentType: 'application/json' });
      // Desktop shares Chat's 10px outer offset plus 10px inner gutter.
      expect(bounds.x).toBeCloseTo(width === 1440 ? 20 : 10, 0);
      expect(bounds.y).toBeCloseTo(header.y + header.height + 10, 0);
      expect(width - bounds.x - bounds.width).toBeCloseTo(width === 1440 ? 20 : 10, 0);
      expect(1000 - bounds.y - bounds.height).toBeCloseTo(width === 1440 ? 20 : 10, 0);
      await page.getByTestId('embed-report-issue-button').click();
      const settings = page.getByTestId('settings-menu');
      await expect(settings).toBeVisible();
      await expect(settings).toHaveCSS('width', '323px');
      await settings.evaluate(async (element: Element) => {
        await Promise.all(element.getAnimations().map(animation => animation.finished.catch(() => {})));
      });
      const panel = await settings.boundingBox();
      expect(width - panel.x - panel.width).toBeCloseTo(width === 1440 ? 20 : 10, 0);
      if (width === 1440) {
        const narrowed = await main.boundingBox();
        expect(panel.x - narrowed.x - narrowed.width).toBeCloseTo(20, 0);
        expect(panel.y).toBeCloseTo(narrowed.y, 0);
        expect(narrowed.x).toBeCloseTo(20, 0);
      }
      const screenshot = test.info().outputPath(`apps-settings-gutters-${width}.png`);
      await page.screenshot({ path: screenshot, animations: 'disabled' });
      await test.info().attach(`apps-settings-gutters-${width}`, { path: screenshot, contentType: 'image/png' });
      // Observe the actual close callbacks so the assertion cannot finish
      // before a delayed write runs after Apps has unmounted. Timer delays
      // and production callbacks are unchanged.
      await page.evaluate(() => {
        const browser = window as Window & {
          appsSettingsCloseTimers?: { scheduled: number; settled: number };
          appsSettingsRestoreTimers?: () => void;
        };
        const stats = { scheduled: 0, settled: 0 };
        browser.appsSettingsCloseTimers = stats;
        const original = window.setTimeout;
        window.setTimeout = ((handler: TimerHandler, delay?: number, ...args: unknown[]) => {
          if (delay !== 300 || typeof handler !== 'function') {
            return original.call(window, handler, delay, ...args);
          }
          stats.scheduled += 1;
          return original.call(window, () => {
            try { handler(...args); }
            finally { stats.settled += 1; }
          }, delay);
        }) as typeof window.setTimeout;
        browser.appsSettingsRestoreTimers = () => { window.setTimeout = original; };
      });
      const navigationErrors: string[] = [];
      const recordError = (error: Error) => navigationErrors.push(error.message);
      page.on('pageerror', recordError);
      await page.getByTestId('icon-button-close').click();
      if (width === 1440) await page.getByTestId('chats-nav-link').click();
      else await page.getByTestId('workspace-mobile-select').selectOption('/');
      await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
      await page.evaluate(() => {
        (window as Window & { appsSettingsRestoreTimers?: () => void }).appsSettingsRestoreTimers?.();
      });
      await expect.poll(() => page.evaluate(() => {
        const stats = (window as Window & { appsSettingsCloseTimers?: { scheduled: number; settled: number } }).appsSettingsCloseTimers;
        return stats && stats.scheduled > 0 && stats.scheduled === stats.settled;
      })).toBe(true);
      expect(navigationErrors).toEqual([]);
      page.off('pageerror', recordError);
      await expect(page.locator('.ProseMirror').first()).toBeVisible({ timeout: 30000 });
      expect(appHash(page)).not.toMatch(/^#apps/);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  test('app settings expose skill pricing and providers while the request uses natural language',async({page}:{page:any})=>{
    await fixtureSkillDetails(page,{app_id:'web',skill_id:'search',name:'Search web',primary_fields:['query'],anonymous_allowed:false});
    await page.goto(getE2EDebugUrl('/#apps/web/search'),{waitUntil:'domcontentloaded'});await expect(requestComposer(page)).toBeVisible({timeout:30000});
    await expect(page.getByTestId('apps-skill-form')).toHaveCount(0);await page.getByTestId('apps-settings-open').click();
    const settings=page.getByTestId('settings-menu');await expect(settings).toBeVisible();await expect(settings.locator('.app-details')).toBeVisible();await expect(page.getByTestId('apps-settings')).toHaveCount(0);
    await settings.getByTestId('settings-skill-cards-scroll').getByTestId('app-store-card').filter({hasText:/Search/}).first().click();await expect(settings.locator('.skill-details')).toBeVisible();await expect(settings.getByText('Pricing',{exact:true}).first()).toBeVisible();await expect(settings.getByText('Providers',{exact:true}).first()).toBeVisible();
  });
  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding,apps.discovery.public-catalog
  test('legacy Settings links forward and public focus and memory details remain reachable', async ({ page }: { page: any }) => {
    await fixtureSkillDetails(page, {
      app_id: 'health', skill_id: 'search_appointments', name: 'Search appointments',
      primary_fields: ['query', 'location'], anonymous_allowed: false,
    });
    await page.goto(getE2EDebugUrl('/#settings/apps/health/skill/search_appointments'), { waitUntil: 'domcontentloaded' });
    await expect(requestComposer(page)).toBeVisible({ timeout: 30000 });
    expect(appHash(page)).toBe('#apps/health/search-appointments');

    await page.goto(getE2EDebugUrl('/#apps/health/focus/prepare_doctor_appointment'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('focus-mode-details')).toBeVisible({ timeout: 30000 });
    await page.goto(getE2EDebugUrl('/#apps/health/memory/medical_history'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('app-settings-memories-category')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('app-settings-memories-category')).toHaveAttribute('data-category-id', 'medical_history');
  });

  // contract-test: supporting surface=gui.web assertions=apps.anonymous.cli-equivalent-gate
  test('guest sees Signup before an ineligible interpreted skill can dispatch',async({page}:{page:any})=>{
    await fixtureSkillDetails(page,{app_id:'web',skill_id:'search',name:'Search web',primary_fields:['query'],anonymous_allowed:false});let providerPosts=0;
    page.on('request',(request:any)=>{if(request.method()==='POST'&&/\/v1\/(?:anonymous\/)?apps\/web\/skills\/search$/.test(new URL(request.url()).pathname))providerPosts++;});
    await page.goto(getE2EDebugUrl('/#apps/web/search'),{waitUntil:'domcontentloaded'});const form=requestComposer(page);await expect(form).toBeVisible({timeout:30000});
    await form.getByTestId('apps-request-textarea').fill('Find accessible museums');await form.getByTestId('apps-request-submit').click();
    await expect(page.locator('.apps-auth-layer')).toBeVisible();expect(providerPosts).toBe(0);await expect(page.getByTestId('apps-result-fullscreen')).toHaveCount(0);
    await page.locator('.apps-auth-layer').getByRole('button',{name:'Close',exact:true}).click();await expect(page.locator('.apps-auth-layer')).toHaveCount(0);
  });
  // contract-test: supporting surface=gui.web assertions=apps.anonymous.cli-equivalent-gate
  test('eligible interpreted skill shows Signup when its request quote denies the budget',async({page}:{page:any})=>{
    await fixtureSkillDetails(page,{app_id:'web',skill_id:'search',name:'Search web',primary_fields:['query'],anonymous_allowed:true});
    await page.route('**/v1/anonymous/apps/web/skills/search/availability',(route:any)=>route.fulfill({json:{allowed:false,reason:'daily_limit_reached'}}));let posts=0;
    page.on('request',(request:any)=>{if(request.method()==='POST'&&new URL(request.url()).pathname==='/v1/anonymous/apps/web/skills/search')posts++;});
    await page.goto(getE2EDebugUrl('/#apps/web/search'),{waitUntil:'domcontentloaded'});const form=requestComposer(page);await expect(form).toBeVisible({timeout:30000});
    await form.getByTestId('apps-request-textarea').fill('accessible museums in Berlin');const quote=page.waitForResponse((response:any)=>response.url().endsWith('/v1/anonymous/apps/web/skills/search/availability')&&response.request().method()==='POST');
    await form.getByTestId('apps-request-submit').click();expect((await quote).request().postDataJSON().query).toBe('accessible museums in Berlin');
    await expect(page.locator('.apps-auth-layer')).toBeVisible();expect(posts).toBe(0);await expect(page.getByTestId('apps-result-fullscreen')).toHaveCount(0);
  });
  // contract-test: supporting surface=gui.web assertions=apps.library.embeds-account-paginated
  test('Personal app libraries request bounded pages and reset when the app changes',async({page}:{page:any})=>{
    test.setTimeout(120000);test.skip(!getTestAccount().email,'Test account credentials required.');await page.goto(getE2EDebugUrl('/'),{waitUntil:'domcontentloaded'});await loginToTestAccount(page,()=>{},async()=>{});
    const queries:URLSearchParams[]=[];const libraryApps:string[]=[];
    await page.route('**/v1/apps/workspace/results?*',(route:any)=>{const params=new URL(route.request().url()).searchParams;queries.push(params);const app=params.get('app_id'),offset=Number(params.get('offset'));return route.fulfill({json:{items:app==='web'?[{embed_id:`web-result-${offset}`,app_id:'web',skill_id:'search',created_at:1,status:'finished'}]:[],offset,limit:20,has_more:app==='web'&&offset===0}});});
    await page.route('**/v1/apps/workspace/library/*',(route:any)=>{const appId=new URL(route.request().url()).pathname.split('/').at(-1)!;libraryApps.push(appId);return route.fulfill({json:{app_id:appId,daily_searches_enabled:true,recommendations:[],saved_searches:[{id:appId,skill_id:'search',query:appId+' saved search',parameters:{query:appId},saved_at:1}]}});});
    await page.goto(getE2EDebugUrl('/#apps/web'),{waitUntil:'domcontentloaded'});await page.getByTestId('apps-tab-saved').click();await expect(page.getByTestId('apps-saved-search-query')).toContainText('web saved search');expectPersonalPageQuery(queries.at(-1),'web',0);
    await openRecent(page);await expect(page.getByTestId('apps-preview-carousel').locator('[data-embed-id="web-result-0"]')).toBeVisible();await page.getByTestId('apps-next-page').click();await expect(page.getByTestId('apps-preview-carousel').locator('[data-embed-id="web-result-20"]')).toBeVisible();expectPersonalPageQuery(queries.at(-1),'web',20);
    await page.goto(getE2EDebugUrl('/#apps/health'),{waitUntil:'domcontentloaded'});await page.getByTestId('apps-tab-saved').click();await expect(page.getByTestId('apps-saved-search-query')).toContainText('health saved search');await expect(page.getByText('web saved search',{exact:true})).toHaveCount(0);
    await expect(page.getByTestId('apps-preview-carousel').locator('[data-embed-id="web-result-20"]')).toHaveCount(0);await expect(page.getByTestId('apps-next-page')).toHaveCount(0);expectPersonalPageQuery(queries.at(-1),'health',0);expect(libraryApps).toContain('web');expect(libraryApps).toContain('health');
  });
  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  test('an open app library indexes an older chat root after background sync and refreshes without reload', async ({ page }: { page: any }) => {
    test.setTimeout(120000);
    expect(getTestAccount().email, 'CI must provide an authenticated test account').toBeTruthy();
    let clientSocket: any;
    await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
      clientSocket = socket;
      socket.connectToServer();
    });
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    const chatId = '9f41750a-b728-4c7d-8ce9-f83cc32b1cc3';
    const embedId = 'd6515197-f14a-4dce-bb89-a9353a4eb9df';
    let indexed = false;
    let batchBody: any;
    await page.route('**/v1/apps/workspace/results/index/batch', async (route: any) => {
      batchBody = route.request().postDataJSON();
      indexed = true;
      await route.fulfill({ json: { indexed: 1, received: batchBody.items.length } });
    });
    await page.route('**/v1/apps/workspace/results?*', (route: any) => route.fulfill({ json: {
      items: indexed ? [{ embed_id: embedId, app_id: 'web', skill_id: 'search', created_at: 1, status: 'finished' }] : [],
      has_more: false, offset: 0, limit: 20,
    } }));
    await page.goto(getE2EDebugUrl('/#apps/web&tab=embeds'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-preview-carousel')).toBeVisible({ timeout: 30000 });
    await openRecent(page);await expect(page.getByTestId('apps-preview-carousel').locator(`[data-embed-id="${embedId}"]`)).toHaveCount(0);
    const chatHash = await page.evaluate(async ({ chatId, embedId }: { chatId: string; embedId: string }) => {
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(chatId))))
        .map(value => value.toString(16).padStart(2, '0')).join('');
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('chats_db');
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        await new Promise<void>((resolve, reject) => {
          const transaction = db.transaction(['chats', 'embeds'], 'readwrite');
          transaction.objectStore('chats').put({ chat_id: chatId, team_id: null, encrypted_title: null,
            messages_v: 0, title_v: 0, created_at: 1, updated_at: 1 });
          transaction.objectStore('embeds').put({ contentRef: `embed:${embedId}`, embed_id: embedId,
            type: 'app-skill-use', app_id: 'web', skill_id: 'search', hashed_chat_id: hash,
            encrypted_content: 'opaque-legacy-ciphertext-fixture', status: 'finished', createdAt: 1, updatedAt: 1 });
          transaction.oncomplete = () => resolve();
          transaction.onerror = () => reject(transaction.error);
          transaction.onabort = () => reject(transaction.error);
        });
      } finally { db.close(); }
      return hash;
    }, { chatId, embedId });
    await expect.poll(() => Boolean(clientSocket)).toBe(true);
    // Exercise the real bulk-sync notification after an empty library scan.
    // The second opaque row makes the normal sync handler commit a batch;
    // classification finds the older app root already present in local storage.
    clientSocket.send(JSON.stringify({ type: 'background_message_sync', payload: {
      batch_number: 1, is_last_batch: true, chats: [], team_id: null, embed_keys: [],
      embeds: [{ embed_id: '3938dc8a-f2cd-4d4c-8ca5-f8fe0d6ad4bc',
        encrypted_type: 'Zml4dHVyZQ==', encrypted_content: 'Zml4dHVyZQ==',
        hashed_chat_id: chatHash, status: 'finished', created_at: 1, updated_at: 1 }],
    } }));
    await expect(page.locator(`[data-embed-id="${embedId}"]`)).toBeVisible({ timeout: 30000 });
    expect(batchBody.expected_user_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(batchBody.team_id).toBeNull();
    expect(batchBody.items.length).toBeLessThanOrEqual(50);
    expect(batchBody.items).toContainEqual({ embed_id: embedId, chat_id: chatId, app_id: 'web', skill_id: 'search' });
  });

  // contract-test: direct surface=gui.web assertions=apps.execution.direct-shared-contract,apps.results.web-retained-graph
  test('Web results render and open locally before the finished background save is acknowledged', async ({ page }: { page: any }) => {
    test.setTimeout(120000);
    expect(getTestAccount().email, 'CI must provide its existing authenticated test account').toBeTruthy();
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: false, requestEnvelope: true,
    });
    const query = 'Accessible museums for a local result';
    const title = 'Website card before save acknowledgment';
    const saves: any[] = [];
    const skillBodies: any[] = [];
    const rootGets: string[] = [];
    // Other tests can leave durable results in this shared account. This case
    // isolates the new local graph, including its strict zero-root-GET contract.
    await page.route('**/v1/apps/workspace/results?*', (route: any) => route.fulfill({ json: {
      items: [], has_more: false, offset: 0, limit: 20,
    } }));
    let releaseFinished!: () => void;
    const finishedGate = new Promise<void>(resolve => { releaseFinished = resolve; });
    page.on('request', (request: any) => {
      if (request.method() === 'GET' && /^\/v1\/apps\/workspace\/results\/[0-9a-f-]{36}$/i.test(new URL(request.url()).pathname)) rootGets.push(request.url());
    });
    await page.route('**/v1/apps/workspace/results', async (route: any) => {
      const body = route.request().postDataJSON();
      saves.push(body);
      await finishedGate;
      await route.fulfill({ json: { root_embed_id: body.root_embed_id, linked_embed_ids: [] } });
    });
    await page.route('**/v1/apps/web/skills/search', async (route: any) => {
      skillBodies.push(route.request().postDataJSON());
      await route.fulfill({ json: { success: true, data: { provider: 'Fixture Search', results: [{ id: 'request-1', results: [{
        type: 'search_result', title, url: 'https://example.test/apps/local-before-save', description: 'Local result fixture.',
      }] }] } } });
    });
    try {
      await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
      const form = requestComposer(page);
      await expect(form).toBeVisible({ timeout: 30000 });
      await form.getByTestId('apps-request-textarea').fill(query);
      await form.getByTestId('apps-request-submit').click();
      await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid')).toContainText(title, { timeout: 30000 });
      await expect.poll(() => saves.length).toBe(1);
      expect(saves).toHaveLength(1);
      expect(saves[0].embeds).toHaveLength(2);
      expect(saves[0].embeds[0].status).toBe('finished');
      expect(skillBodies).toHaveLength(1);
      expect(skillBodies[0].requests[0].query).toBe(query);
      expect(rootGets).toEqual([]);
      await expect(page.getByTestId('apps-result-fullscreen')).toContainText(title);
      expect(rootGets).toEqual([]);
      expect(saves).toHaveLength(1);
      await expect(page.getByTestId('apps-result-fullscreen')).toContainText(title);
      releaseFinished();
      await expect(page.getByTestId('apps-result-save-state')).toHaveAttribute('data-save-state', 'saved');
      expect(rootGets).toEqual([]);
    } finally { releaseFinished(); }
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  test('failed Web save keeps local cards and reload retries the finished graph without skill redispatch', async ({ page }: { page: any }) => {
    test.setTimeout(120000);
    expect(getTestAccount().email, 'CI must provide its existing authenticated test account').toBeTruthy();
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: false, requestEnvelope: true,
    });
    const title = 'Website survives failed save and reload';
    const savedBodies: any[] = [];
    let skillPosts = 0;
    let saveAcknowledged = false;
    let libraryFails = true;
    let requestGeneration = 0;
    const requestGenerations = new WeakMap<object, number>();
    page.on('request', (request: object) => { requestGenerations.set(request, requestGeneration); });
    let releaseFailure!: () => void;
    let releaseRetry!: () => void;
    const failureGate = new Promise<void>(resolve => { releaseFailure = resolve; });
    const retryGate = new Promise<void>(resolve => { releaseRetry = resolve; });
    await page.route('**/v1/apps/workspace/results', async (route: any) => {
      const body = route.request().postDataJSON();
      savedBodies.push(body);
      if (savedBodies.length === 1) {
        await failureGate;
        await route.fulfill({ status: 503, json: { detail: 'Fixture save outage' } });
      } else {
        await retryGate;
        // Model the server commit before its acknowledgment reaches the client.
        // A prior reload can have detached another waiter from this same gate.
        saveAcknowledged = true;
        await route.fulfill({ json: { root_embed_id: body.root_embed_id, linked_embed_ids: [] } })
          .catch(() => {});
      }
    });
    await page.route('**/v1/apps/workspace/results?*', (route: any) => libraryFails
      ? route.fulfill({ status: 503, json: { detail: 'Fixture library outage' } })
      : route.fulfill({ json: {
        items: saveAcknowledged ? [{ embed_id: savedBodies.at(-1).root_embed_id, app_id: 'web', skill_id: 'search',
          created_at: 1, status: 'finished' }] : [],
        has_more: false, offset: 0, limit: 20,
      } }));
    await page.route('**/v1/apps/web/skills/search', (route: any) => {
      skillPosts += 1;
      return route.fulfill({ json: { success: true, data: { provider: 'Fixture Search', results: [{ id: 'request-1', results: [{
        type: 'search_result', title, url: 'https://example.test/apps/retry-after-reload', description: 'Retry fixture.',
      }] }] } } });
    });
    try {
      await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
      const form = requestComposer(page);
      await expect(form).toBeVisible({ timeout: 30000 });
      await form.getByTestId('apps-request-textarea').fill('Accessible museums after outage');
      await form.getByTestId('apps-request-submit').click();
      await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid')).toContainText(title, { timeout: 30000 });
      await expect.poll(() => savedBodies.length).toBe(1);
      expect(savedBodies).toHaveLength(1);
      expect(savedBodies[0].embeds[0].status).toBe('finished');
      expect(savedBodies[0].embeds).toHaveLength(2);
      releaseFailure();
      await expect(page.getByTestId('apps-result-save-state')).toHaveAttribute('data-save-state', 'error');
      await expect(page.getByTestId('apps-result-save-retry')).toBeVisible();
      await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid')).toContainText(title);
      const rootId = savedBodies[0].root_embed_id;
      const rootUrl=page.url();expect(rootUrl).toContain(`embed-id=${rootId}`);
      // A remote library outage must not hide the locally durable outbox card.
      await page.getByTestId('apps-result-fullscreen').getByTestId('embed-minimize').click();
      await openRecent(page);
      const localCard = page.getByTestId(`apps-result-open-${rootId}`);
      await expect(localCard).toBeVisible({ timeout: 30000 });
      await localCard.getByTestId('embed-preview').first().click();
      await expect(page.getByTestId('apps-result-fullscreen')).toContainText(title);
      const childId=savedBodies[0].embeds.find((row:any)=>row.parent_embed_id===rootId).embed_id;expect(page.url()).toContain(`embed-id=${childId}`);expect(page.url()).toContain(`root-id=${rootId}`);
      await page.evaluate((rootId:string)=>{window.location.hash='#apps/web&embed-id='+rootId;},rootId);await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid')).toContainText(title);
      await page.getByTestId('apps-result-save-retry').click();
      await expect.poll(() => savedBodies.length).toBe(2);
      expect(savedBodies[1].embeds[0].status).toBe('finished');
      expect(savedBodies[1].embeds).toHaveLength(2);
      expect(skillPosts).toBe(1);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid')).toContainText(title, { timeout: 30000 });
      await expect.poll(() => savedBodies.length).toBeGreaterThanOrEqual(3);
      expect(savedBodies.at(-1)).toEqual(savedBodies[1]);
      expect(page.url()).toBe(rootUrl);
      expect(skillPosts).toBe(1);
      releaseRetry();
      await expect(page.getByTestId('apps-result-save-state')).toHaveAttribute('data-save-state', 'saved');
      await expect.poll(() => saveAcknowledged).toBe(true);
      libraryFails = false;
      await page.goto(getE2EDebugUrl('/#apps/web&tab=embeds'), { waitUntil: 'domcontentloaded' });
      // Match requests issued for this reload, excluding delayed outage responses
      // from the previous document even when they have the exact same URL.
      const reloadGeneration = ++requestGeneration;
      const reloadedLibrary = page.waitForResponse((response: any) => {
        const url = new URL(response.url());
        return requestGenerations.get(response.request()) === reloadGeneration
          && response.request().method() === 'GET' && url.pathname === '/v1/apps/workspace/results'
          && url.searchParams.get('app_id') === 'web' && url.searchParams.get('offset') === '0';
      });
      // Changing only the hash keeps this Apps scope mounted. Explicitly reload
      // after restoring the remote library so its fresh GET is part of the proof.
      await page.reload({ waitUntil: 'domcontentloaded' });
      const libraryResponse = await reloadedLibrary;
      expect(libraryResponse.ok()).toBe(true);
      expect((await libraryResponse.json()).items).toEqual([expect.objectContaining({ embed_id: rootId, status: 'finished' })]);
      await openRecent(page);await expect(page.getByTestId(`apps-result-open-${rootId}`)).toBeVisible({timeout:30000});
      for(const row of savedBodies[1].embeds.slice(1))await expect(page.getByTestId(`apps-result-open-${row.embed_id}`)).toHaveCount(0);
    } finally { releaseFailure(); releaseRetry(); }
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.execution.direct-shared-contract
  test('Events natural-language criteria posts the interpreted native request without form fields',async({page}:{page:any})=>{
    test.setTimeout(90000);expect(getTestAccount().email).toBeTruthy();await page.goto(getE2EDebugUrl('/'),{waitUntil:'domcontentloaded'});await loginToTestAccount(page,()=>{},async()=>{});
    await fixtureSkillDetails(page,{app_id:'events',skill_id:'search',name:'Search events',primary_fields:['requests[].query'],anonymous_allowed:false,requestEnvelope:true,relevanceCriteria:true});
    const text='Find jazz this weekend. Prefer free outdoor events near public transport.';
    const input={requests:[{query:'jazz this weekend',count:10,relevance_criteria:'Prefer free outdoor events near public transport.'}]};
    await fixtureInterpreter(page,'events','search',value=>{expect(value).toBe(text);return input;});let posted:any;
    await page.route('**/v1/apps/workspace/results',(route:any)=>route.fulfill({json:{root_embed_id:route.request().postDataJSON().root_embed_id,linked_embed_ids:[]}}));
    await page.route('**/v1/apps/events/skills/search',(route:any)=>{posted=route.request().postDataJSON();return route.fulfill({json:{success:true,data:{results:[{id:'request-1',results:[]}]}}});});
    await page.goto(getE2EDebugUrl('/#apps/events/search'),{waitUntil:'domcontentloaded'});const composer=requestComposer(page);await expect(composer).toBeVisible({timeout:30000});
    await expect(page.getByTestId('apps-skill-form')).toHaveCount(0);await composer.getByTestId('apps-request-textarea').fill(text);await composer.getByTestId('apps-request-submit').click();
    await expect.poll(()=>posted).toEqual(input);await expect(page.getByTestId('apps-result-fullscreen')).toBeVisible();
  });
  // contract-test: direct surface=gui.web assertions=apps.execution.direct-shared-contract,apps.results.web-retained-graph,apps.results.shared-fullscreen
  // contract-test: direct surface=rest_api assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  test('one Web search retains all 25 children after leaving its composer and reopens after reload', async ({ page }: { page: any }) => {
    test.setTimeout(120000);
    expect(getTestAccount().email, 'CI must provide its existing authenticated test account').toBeTruthy();
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: false, requestEnvelope: true,
    });

    const marker = `apps-retention-${Date.now()}`;
    const query = `Accessible museums ${marker}`;
    const results = Array.from({ length: 25 }, (_, index) => ({
      type: 'search_result',
      title: `Fixture page ${index + 1} ${marker}`,
      url: `https://example.test/apps/${marker}/${index + 1}`,
      description: `Safe fixture result ${index + 1} for ${marker}`,
    }));
    let skillPosts = 0;
    const chatPosts: string[] = [];
    const savedBodies: Array<Record<string, any>> = [];
    page.on('request', (request: any) => {
      if (request.method() !== 'POST') return;
      const path = new URL(request.url()).pathname;
      if (path === '/v1/apps/web/skills/search') skillPosts += 1;
      if (/^\/v1\/(?:chats|ai)(?:\/|$)/.test(path)) chatPosts.push(path);
      if (path === '/v1/apps/workspace/results') savedBodies.push(request.postDataJSON());
    });
    let releaseSkill!: () => void;
    const skillGate = new Promise<void>(resolve => { releaseSkill = resolve; });
    await page.route('**/v1/apps/web/skills/search', async (route: any) => {
      expect(route.request().method()).toBe('POST');
      expect(route.request().postDataJSON().requests[0].query).toBe(query);
      await skillGate;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        success: true, data: {
          provider: 'Fixture Search',
          results: [{ id: 'request-1', results }],
        },
      }) });
    });

    await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
    const form = requestComposer(page);
    await expect(form).toBeVisible({ timeout: 30000 });
    await form.getByTestId('apps-request-textarea').fill(query);
    const finalSave = page.waitForResponse((response: any) => {
      if (response.request().method() !== 'POST' || new URL(response.url()).pathname !== '/v1/apps/workspace/results') return false;
      return response.request().postDataJSON()?.embeds?.length === 26;
    });
    const skillRequest = page.waitForRequest((request: any) => request.method() === 'POST'
      && new URL(request.url()).pathname === '/v1/apps/web/skills/search');
    await form.getByTestId('apps-request-submit').click();
    await skillRequest;
    await page.getByTestId('apps-detail-close').click();
    await expect.poll(() => appHash(page)).toBe('#apps/web');
    releaseSkill();
    const saved = await finalSave;
    expect(saved.ok(), 'the finished encrypted parent and children must be durable').toBe(true);
    const body = saved.request().postDataJSON();
    const rootId = body.root_embed_id;
    expect(rootId).toMatch(/^[0-9a-f-]{36}$/i);
    expect(skillPosts).toBe(1);
    expect(chatPosts).toEqual([]);
    expect(savedBodies).toHaveLength(1); // The sync processing draft stays local until the finished graph is ready.
    expect(body.embeds).toHaveLength(26);
    const root = body.embeds.find((row: any) => row.embed_id === rootId);
    expect(root?.embed_ids).toHaveLength(25);
    expect(new Set(root?.embed_ids).size).toBe(25);
    // The final child reaches IDB after the complete graph is hydrated. A
    // completed request must preserve the user's newer app-level navigation.
    await page.waitForFunction(async (childId: string) => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('chats_db');
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        return await new Promise<boolean>((resolve, reject) => {
          const request = db.transaction('embeds').objectStore('embeds').get(`embed:${childId}`);
          request.onsuccess = () => resolve(request.result?.status === 'finished');
          request.onerror = () => reject(request.error);
        });
      } finally { db.close(); }
    }, root.embed_ids.at(-1));
    expect(appHash(page)).toBe('#apps/web');
    expect(body.embeds.filter((row: any) => row.parent_embed_id === rootId)).toHaveLength(25);
    expect(typeof body.encrypted_embed_key).toBe('string');
    expect(body.encrypted_embed_key.length).toBeGreaterThan(40);
    for (const write of savedBodies) {
      const serialized = JSON.stringify(write);
      expect(serialized).not.toContain(query);
      expect(serialized).not.toContain(marker);
      for (const row of write.embeds) {
        expect(row.encrypted_content).toMatch(/^[A-Za-z0-9+/]+=*$/);
        expect(row.encrypted_type).toMatch(/^[A-Za-z0-9+/]+=*$/);
      }
    }

    const api = deriveApiUrl(page.url());
    const detail = await page.request.get(`${api}/v1/apps/workspace/results/${rootId}`);
    expect(detail.ok()).toBe(true);
    const persisted = await detail.json();
    expect(persisted.root.embed_id).toBe(rootId);
    expect(persisted.root.embed_ids).toHaveLength(25);
    expect(persisted.children).toHaveLength(25);
    expect(JSON.stringify(persisted)).not.toContain(marker);
    const library = await page.request.get(`${api}/v1/apps/workspace/results?app_id=web&offset=0&limit=50`);
    expect(library.ok()).toBe(true);
    const listed = await library.json();
    expect(listed.items.some((item: any) => item.embed_id === rootId && item.app_id === 'web')).toBe(true);

    await page.goto(getE2EDebugUrl('/#apps/web&tab=embeds'), { waitUntil: 'domcontentloaded' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await openRecent(page);
    const card = page.getByTestId(`apps-result-open-${rootId}`);
    await expect(card).toBeVisible({ timeout: 30000 });
    await expect(card.getByTestId('embed-preview')).toHaveCount(25);await expect(card).toContainText(`Fixture page 25 ${marker}`);
    for(const childId of root.embed_ids)await expect(page.getByTestId(`apps-result-open-${childId}`)).toHaveCount(0);
    await card.getByTestId('embed-preview').first().click();
    await expect(page.getByTestId('apps-result-fullscreen')).toContainText(`Fixture page 1 ${marker}`);
    expect(page.url()).toContain(`embed-id=${root.embed_ids[0]}`);expect(page.url()).toContain(`root-id=${rootId}`);await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid')).toHaveCount(0);
    await page.evaluate((rootId:string)=>{window.location.hash='#apps/web&embed-id='+rootId;},rootId);
    await expect(page.getByTestId('apps-result-fullscreen').getByTestId('apps-request-textarea')).toBeVisible();
    await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-filter')).toHaveCount(0);
    await page.getByTestId('apps-result-fullscreen').getByTestId('search-template-filter-button').click();
    await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-toolbar')).toBeVisible();
    await expect(page.getByTestId('apps-result-fullscreen')).toBeVisible();
    const grid = page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid');
    await expect(grid.getByTestId('embed-preview')).toHaveCount(25, { timeout: 30000 });
    await expect(grid).toContainText(`Fixture page 25 ${marker}`);await page.reload({waitUntil:'domcontentloaded'});await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(25,{timeout:30000});expect(skillPosts).toBe(1);
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.execution.direct-shared-contract,apps.results.web-retained-graph,apps.library.embeds-account-paginated,apps.results.shared-fullscreen
  test('Health public-insurance search sends native filters and retains populated appointment views', async ({ page }: { page: any }) => {
    await page.addInitScript(() => sessionStorage.setItem('openmates:send-prep-timing', '1'));
    test.setTimeout(120000);
    expect(getTestAccount().email, 'CI must provide its existing authenticated test account').toBeTruthy();
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    await page.route('**/v1/geocode/search?**', (route: any) => route.fulfill({ json: [{
      lat: '52.52', lon: '13.405', name: 'Berlin', display_name: 'Berlin, Germany',
      class: 'place', type: 'city', namedetails: { name: 'Berlin' },
      address: { city: 'Berlin', country: 'Germany' },
    }] }));
    // Keep the unique fixture identifier alphabetic: ordinary chat correctly
    // masks long digit sequences as phone numbers by default.
    const marker = `apps-health-${String(Date.now()).replace(/\d/g, digit => String.fromCharCode(97 + Number(digit)))}`;
    const names = [`Synthetic Practice ${marker}`, `Synthetic Doctor ${marker}`];
    const appointments = names.map((name, index) => ({
      type: 'appointment', name, speciality: 'Hautarzt', address: 'Synthetic Street, Berlin',
      slot_datetime: new Date(Date.now() + (index + 1) * 86400000).toISOString(),
      visit_motive: 'Allgemeine Sprechstunde', insurance: 'public', allows_new_patients: true,
      provider_platform: 'Doctolib', practice_url: `https://example.test/appointments/${marker}/${index}`,
      search_coverage: { Doctolib: 'success', Jameda: 'no_match' },
    }));
    let skillPosts = 0;
    let nativeInput: Record<string, any> | undefined;
    await page.route('**/v1/apps/health/skills/search_appointments', async (route: any) => {
      skillPosts += 1;
      nativeInput = route.request().postDataJSON();
      return route.fulfill({ json: { success: true, data: { results: [{ id: '1', results: appointments }], error: null } } });
    });
    const utterance='Find dermatologists in Berlin accepting new patients with public insurance this week.';
    await fixtureInterpreter(page,'health','search_appointments',value=>{expect(value).toBe(utterance);return {requests:[{speciality:'dermatologist',city:'Berlin',provider_platform:'both',insurance_sector:'public',days_ahead:7,max_doctors:10,telehealth:false}]};});
    await page.goto(getE2EDebugUrl('/#apps/health/search-appointments'),{waitUntil:'domcontentloaded'});
    const form=requestComposer(page);await expect(form).toBeVisible({timeout:30000});
    await expect(page.getByTestId('apps-skill-form')).toHaveCount(0);await form.getByTestId('apps-request-textarea').fill(utterance);expect(skillPosts).toBe(0);
    const finalSave = page.waitForResponse((response: any) => response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/v1/apps/workspace/results'
      && response.request().postDataJSON()?.embeds?.length === 3);
    await form.getByTestId('apps-request-submit').click();
    const inline = page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid');
    await expect(inline.getByTestId('embed-preview')).toHaveCount(2, { timeout: 30000 });
    await expect(inline).toContainText(names[0]);
    expect(nativeInput?.requests).toHaveLength(1);
    expect(nativeInput?.requests[0]).toMatchObject({
      speciality: 'dermatologist', city: 'Berlin', provider_platform: 'both',
      insurance_sector: 'public', days_ahead: 7, max_doctors: 10, telehealth: false,
    });
    const saved = await finalSave;
    expect(saved.ok()).toBe(true);
    const body = saved.request().postDataJSON();
    expect(JSON.stringify(body)).not.toContain(marker);
    expect(skillPosts).toBe(1);
    const fullscreen=page.getByTestId('apps-result-fullscreen');
    await expect(fullscreen.getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(2);await expect(fullscreen).toContainText(names[0]);
    await fullscreen.getByTestId('embed-minimize').click();
    await openRecent(page);
    const rootCard=page.getByTestId(`apps-result-open-${body.root_embed_id}`);
    await expect(rootCard).toBeVisible({ timeout: 30000 });
    for (const child of body.embeds.filter((item: any) => item.parent_embed_id === body.root_embed_id)) {
      await expect(page.getByTestId(`apps-result-open-${child.embed_id}`)).toHaveCount(0);
    }
    await expect(rootCard.getByTestId('embed-preview')).toHaveCount(2);
    await rootCard.getByTestId('embed-preview').first().click();
    const selectedChild=body.embeds.find((row:any)=>row.parent_embed_id===body.root_embed_id).embed_id;expect(page.url()).toContain(`embed-id=${selectedChild}`);expect(page.url()).toContain(`root-id=${body.root_embed_id}`);await expect(fullscreen).toContainText(names[0]);
    await page.evaluate((rootId:string)=>{window.location.hash='#apps/health&embed-id='+rootId;},body.root_embed_id);
    await expect(fullscreen.getByTestId('apps-request-textarea')).toBeVisible();
    await expect(fullscreen.getByTestId('search-template-filter')).toHaveCount(0);
    await fullscreen.getByTestId('search-template-filter-button').click();
    await expect(fullscreen.getByTestId('search-template-toolbar')).toBeVisible();
    const children = fullscreen.getByTestId('search-template-grid').getByTestId('embed-preview');
    await expect(children).toHaveCount(2, { timeout: 30000 });
    await expect(fullscreen).toContainText(names[1]);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(fullscreen.getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(2, { timeout: 30000 });
    await expect(fullscreen).toContainText(names[0]);
    expect(skillPosts).toBe(1);
    // The retained root still supplies complete native filters after child navigation.
    // Fixture replay must never fall through to record mode or live inference.
    expect(process.env.E2E_USE_MOCKS, 'ordinary chat handoff requires fixture replay').toBeTruthy();
    expect(process.env.E2E_RECORD_FIXTURES).toBeFalsy();
    const followup = withMockMarker('Explain these saved appointments', 'chat_flow_capital');
    let followupContext: Record<string, any> | undefined;
    await page.route('**/v1/apps/workspace/interpret', (route: any) => {
      const request = route.request().postDataJSON();
      expect(request.text).toBe(followup);
      followupContext = request.context;
      return route.fulfill({ json: { action: 'chat', request_id: request.request_id } });
    });
    await fullscreen.getByTestId('apps-request-textarea').fill(followup);
    await fullscreen.getByTestId('apps-request-submit').click();
    await expect.poll(() => followupContext?.embed_id).toBe(body.root_embed_id);
    expect(followupContext?.input?.requests?.[0]).toMatchObject({
      speciality: 'dermatologist', city: 'Berlin', insurance_sector: 'public',
      provider_platform: 'both', days_ahead: 7, max_doctors: 10, telehealth: false,
    });
    // Keep the complete native context, including the exact saved child IDs.
    expect(followupContext?.result?.results).toHaveLength(2);
    expect(followupContext?.result?.results?.map((item: any) => item.embed_id)).toEqual(expect.arrayContaining(
      body.embeds.filter((item: any) => item.parent_embed_id === body.root_embed_id).map((item: any) => item.embed_id),
    ));
    expect(followupContext?.result?.results?.[0]).toMatchObject({
      type: 'appointment',
      insurance: 'public',
    });
    expect(followupContext?.result?.results?.[0]?.name).toBe(names[0]);
    const delivered = page.getByTestId('message-user').last();
    await expect(delivered).toContainText('Explain these saved appointments', { timeout: 30000 });
    await expect(delivered).toContainText('Result context (data supplied by the user):');
    // The complete saved result context exceeds the user-message collapse limit.
    await delivered.getByRole('button', { name: 'Show full message', exact: true }).click();
    await expect(delivered).toContainText(names[0]);
    await expect(delivered).toContainText('dermatologist');
    await expect(delivered).toContainText('public');
    const assistant = page.getByTestId('message-assistant').last();
    await expect(assistant).toContainText('The capital of Germany', { timeout: 60000 });
    await expect(assistant).toContainText('Berlin');
    // Expanded messages also render a read-only ProseMirror document. Verify
    // that the actual composer cleared after accepting the handoff.
    await expect(page.getByTestId('message-editor').locator('.ProseMirror')).toHaveText('');
    expect(skillPosts).toBe(1);
  });

  // @privacy-promise: pii-placeholder-substitution
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen,pii.composer.detect-redact-exclude
  test('Apps masks two distinct emails and prior context for interpretation while restoring validated native input locally', async ({ page }: { page: any }) => {
    // A fresh guest uses the production privacy store's enabled default settings.
    // Only supplier HTTP responses are fixtures; the detector/store remain real.
    await fixtureSkillDetails(page, { app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: true, requestEnvelope: true });
    await page.route('**/v1/anonymous/apps/web/skills/search/availability', (route: any) => route.fulfill({ json: { allowed: true } }));
    const emails = ['apps-privacy-one@example.com', 'apps-privacy-two@example.net'];
    const queries = [`Find public pages mentioning ${emails[0]} and ${emails[1]}`,
      `Find more public pages mentioning ${emails[0]} and ${emails[1]}`];
    let interpretations = 0;
    let nativePosts = 0;
    await page.route('**/v1/apps/workspace/interpret', (route: any) => {
      const body = route.request().postDataJSON();
      const serialized = JSON.stringify(body);
      for (const email of emails) expect(serialized).not.toContain(email);
      expect(serialized).not.toMatch(/"(?:(?:pii|token|placeholder)[_-]?(?:map|mapping)s?|original(?:Text|Value)?|textToHide|replaceWith)"\s*:/i);
      const tokens = body.text.match(/\[OM_PII_[A-F0-9]{32}\]/g) ?? [];
      expect(tokens).toHaveLength(2);
      expect(new Set(tokens).size).toBe(2);
      expect(body.text).toBe(queries[interpretations].replace(emails[0], tokens[0]).replace(emails[1], tokens[1]));
      if (interpretations === 0) expect(body.context).toBeUndefined();
      else {
        expect(body.context.skill_id).toBe('search');
        expect(body.context.input.requests[0].query).toBe(queries[0].replace(emails[0], tokens[0]).replace(emails[1], tokens[1]));
        expect(body.context.embed_id).toMatch(/^[0-9a-f-]{36}$/i);
      }
      interpretations++;
      return route.fulfill({ json: { action: 'execute', request_id: body.request_id, skill_id: 'search',
        input: { requests: [{ query: body.text, count: 2 }] } } });
    });
    await page.route('**/v1/anonymous/apps/web/skills/search', (route: any) => {
      const input = route.request().postDataJSON();
      expect(input).toEqual({ requests: [{ query: queries[nativePosts], count: 2 }] });
      expect(JSON.stringify(input)).not.toContain('[OM_PII_');
      nativePosts++;
      return route.fulfill({ json: { success: true, data: { results: [{ results: [{ type: 'search_result',
        title: `Private-input result ${nativePosts}`, url: `https://example.test/privacy/${nativePosts}`,
        description: 'A native result rendered after local placeholder restoration.' }] }] } } });
    });
    await page.goto(getE2EDebugUrl('/#apps/web'), { waitUntil: 'domcontentloaded' });
    const composer = requestComposer(page);
    await expect(composer).toBeVisible({ timeout: 30000 });
    await composer.getByTestId('apps-request-textarea').fill(queries[0]);
    await composer.getByTestId('apps-request-submit').click();
    const fullscreen = page.getByTestId('apps-result-fullscreen');
    await expect(fullscreen.getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(1);
    await expect(fullscreen).toContainText('Private-input result 1');
    await fullscreen.getByTestId('apps-request-textarea').fill(queries[1]);
    await fullscreen.getByTestId('apps-request-submit').click();
    await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Private-input result 2');
    await expect(fullscreen.getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(1);
    const secondRootId = page.url().match(/&embed-id=([0-9a-f-]{36})/i)?.[1];
    expect(secondRootId).toBeTruthy();
    await fullscreen.getByTestId('embed-minimize').click();
    await openRecent(page);
    const recent = page.getByTestId(`apps-result-open-${secondRootId}`);
    await expect(recent).toBeVisible();
    await recent.getByTestId('embed-preview').first().click();
    await expect(fullscreen).toContainText('Private-input result 2');expect(page.url()).toContain(`root-id=${secondRootId}`);await expect(fullscreen.getByTestId('search-template-grid')).toHaveCount(0);
    await page.evaluate((rootId:string)=>{window.location.hash='#apps/web&embed-id='+rootId;},secondRootId);await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Private-input result 2');
    expect(interpretations).toBe(2);
    expect(nativePosts).toBe(2);
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
  test('natural-language routing waits for accepted execution before fullscreen and filters actual child previews',async({page}:{page:any})=>{
    await fixtureSkillDetails(page,{app_id:'web',skill_id:'search',name:'Search web',primary_fields:['query'],anonymous_allowed:true,requestEnvelope:true});
    await page.route('**/v1/anonymous/apps/web/skills/search/availability',(route:any)=>route.fulfill({json:{allowed:true}}));
    for(const width of [1180,390]){
      let releaseInterpret!:()=>void,releaseSkill!:()=>void;const interpreted=new Promise<void>(resolve=>{releaseInterpret=resolve;});const skillDone=new Promise<void>(resolve=>{releaseSkill=resolve;});let interpreterPosts=0,providerPosts=0;
      await page.route('**/v1/apps/workspace/interpret',async(route:any)=>{interpreterPosts++;const body=route.request().postDataJSON();expect(body.text).toBe('Find gardens near Berlin');await interpreted;await route.fulfill({json:{action:'execute',request_id:body.request_id,skill_id:'search',input:{requests:[{query:'gardens near Berlin',count:2}]}}});});
      await page.route('**/v1/anonymous/apps/web/skills/search',async(route:any)=>{providerPosts++;expect(route.request().postDataJSON().requests[0].query).toBe('gardens near Berlin');await skillDone;await route.fulfill({json:{success:true,data:{results:[{results:[{type:'search_result',title:'Community garden Berlin',url:'https://example.test/community',description:'Outdoor community garden'},{type:'search_result',title:'Botanical garden Berlin',url:'https://example.test/botanical',description:'Botanical collections'}]}]}}});});
      try{
        await page.setViewportSize({width,height:844});await page.goto(getE2EDebugUrl('/#apps/web'),{waitUntil:'domcontentloaded'});const composer=requestComposer(page);await expect(composer).toBeVisible({timeout:30000});
        await composer.getByTestId('apps-request-textarea').fill('Find gardens near Berlin');await composer.getByTestId('apps-request-submit').click();await expect.poll(()=>interpreterPosts).toBe(1);
        await expect(page.getByTestId('apps-result-fullscreen')).toHaveCount(0);expect(providerPosts).toBe(0);expect(appHash(page)).toBe('#apps/web');
        releaseInterpret();await expect.poll(()=>providerPosts).toBe(1);await expect(page.getByTestId('apps-result-fullscreen')).toHaveCount(0);
        releaseSkill();const fullscreen=page.getByTestId('apps-result-fullscreen');await expect(fullscreen).toBeVisible();const grid=fullscreen.getByTestId('search-template-grid');await expect(grid.getByTestId('embed-preview')).toHaveCount(2);
        await expect(grid).toContainText('Community garden Berlin');await expect(grid).toContainText('Botanical garden Berlin');await expect(fullscreen.getByTestId('search-template-filter')).toHaveCount(0);await fullscreen.getByTestId('search-template-filter-button').click();await expect(fullscreen.getByTestId('search-template-toolbar')).toBeVisible();
        await fullscreen.getByTestId('search-template-filter').fill('Botanical');await expect(grid.getByTestId('embed-preview')).toHaveCount(1);await expect(grid).toContainText('Botanical garden Berlin');
        await expect(fullscreen.getByTestId('apps-request-textarea')).toBeVisible();expect(page.url()).toMatch(/&embed-id=[0-9a-f-]{36}/i);
        const layout=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));expect(layout.scroll).toBeLessThanOrEqual(layout.width+2);
      }finally{releaseInterpret();releaseSkill();await page.unroute('**/v1/apps/workspace/interpret');await page.unroute('**/v1/anonymous/apps/web/skills/search');}
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  test('guest chat interpretation preserves the original draft and exhausted-budget signup gate without dispatch', async ({ page }: { page: any }) => {
    const request = 'Explain how I should compare these travel options';
    let providerPosts = 0, anonymousPosts = 0;
    const exhausted = { active: false, can_send_text: false, reason: 'per_identity_exhausted',
      reset_at: new Date(Date.now() + 3600000).toISOString(), cta: 'Create an account to keep using OpenMates.' };
    await page.route('**/v1/settings/server-status', (route: any) => route.fulfill({ json: {
      is_self_hosted: false, payment_enabled: true, server_edition: 'development',
      domain: 'app.dev.openmates.org', ai_models_configured: true, anonymous_free_usage: exhausted,
    } }));
    await page.route('**/v1/anonymous/free-usage/status**', (route: any) => route.fulfill({ json: exhausted }));
    // An admission regression must fail without spending a real anonymous request.
    await page.route('**/v1/anonymous/chat/stream', (route: any) => { anonymousPosts++; return route.abort(); });
    await page.route('**/v1/apps/workspace/interpret', (route: any) => {
      const body = route.request().postDataJSON(); expect(body.text).toBe(request);
      return route.fulfill({ json: { action: 'chat', request_id: body.request_id, reason: 'chat_required' } });
    });
    page.on('request', (item: any) => {
      if (item.method() === 'POST' && /\/v1\/(?:anonymous\/)?apps\/[^/]+\/skills\/[^/]+$/.test(new URL(item.url()).pathname)) providerPosts++;
    });
    await page.goto(getE2EDebugUrl('/#apps/travel'), { waitUntil: 'domcontentloaded' });
    const composer = requestComposer(page); await expect(composer).toBeVisible({ timeout: 30000 });
    await composer.getByTestId('apps-request-textarea').fill(request); await composer.getByTestId('apps-request-submit').click();
    await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
    await expect(page.locator('.ProseMirror').first()).toContainText(request, { timeout: 30000 });
    await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible();
    await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
    expect(anonymousPosts).toBe(0); expect(providerPosts).toBe(0);
    await expect(page.getByTestId('apps-result-fullscreen')).toHaveCount(0);
    expect(page.url()).not.toContain('model=');
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  test('late chat and workflow interpretations cannot hand off after same-app navigation', async ({ page }: { page: any }) => {
    let downstreamPosts = 0;
    for (const endpoint of ['**/v1/anonymous/chat/stream', '**/v1/workflows/input/stream', '**/v1/anonymous/apps/*/skills/*', '**/v1/apps/*/skills/*']) {
      await page.route(endpoint, (route: any) => {
        if (route.request().method() !== 'POST') return route.fallback();
        downstreamPosts++; return route.abort();
      });
    }
    await page.addInitScript(() => {
      const state = window as typeof window & { appsLateHandoffs: string[] };
      state.appsLateHandoffs = [];
      for (const name of ['appsWorkspaceChatHandoff', 'appsWorkspaceWorkflowHandoff']) {
        window.addEventListener(name, () => state.appsLateHandoffs.push(name));
      }
    });
    for (const action of ['chat', 'workflow']) {
      let release!: () => void, interpreterPosts = 0;
      const pending = new Promise<void>(resolve => { release = resolve; });
      await page.route('**/v1/apps/workspace/interpret', async (route: any) => {
        interpreterPosts++; const body = route.request().postDataJSON();
        await pending; await route.fulfill({ json: { action, request_id: body.request_id } });
      });
      try {
        await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
        const composer = requestComposer(page); await expect(composer).toBeVisible({ timeout: 30000 });
        await composer.getByTestId('apps-request-textarea').fill('Explain this result after I leave');
        await composer.getByTestId('apps-request-submit').click(); await expect.poll(() => interpreterPosts).toBe(1);
        // Same app/account: only the original hash fence can reject this response.
        await page.evaluate(() => { window.location.hash = '#apps/web'; });
        await expect.poll(() => appHash(page)).toBe('#apps/web');
        const response = page.waitForResponse('**/v1/apps/workspace/interpret'); release(); await response;
        const textarea = composer.getByTestId('apps-request-textarea');
        await expect(textarea).toHaveValue('');
        await expect(textarea).toHaveJSProperty('readOnly', false);
        await expect(composer.getByTestId('apps-request-mic')).toBeEnabled();
        await expect(composer.getByTestId('apps-request-submit')).toHaveCount(0);
        expect(downstreamPosts).toBe(0);
        expect(await page.evaluate(() => (window as typeof window & { appsLateHandoffs: string[] }).appsLateHandoffs)).toEqual([]);
        await expect(page.getByTestId('apps-workspace')).toBeVisible(); expect(appHash(page)).toBe('#apps/web');
      } finally { release(); await page.unroute('**/v1/apps/workspace/interpret'); }
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.recommendations.private-daily,apps.results.shared-fullscreen
  test('saving a search explains Daily credit use and Turn off persists before subsequent saves',async({page}:{page:any})=>{
    test.setTimeout(120000);expect(getTestAccount().email).toBeTruthy();await page.goto(getE2EDebugUrl('/'),{waitUntil:'domcontentloaded'});await loginToTestAccount(page,()=>{},async()=>{});
    await fixtureSkillDetails(page,{app_id:'web',skill_id:'search',name:'Search web',primary_fields:['query'],anonymous_allowed:false,requestEnvelope:true});
    let enabled=true;const saves:any[]=[];const changes:any[]=[];
    const library=()=>({app_id:'web',daily_searches_enabled:enabled,recommendations:[],saved_searches:saves.map((body,index)=>({id:`saved-${index}`,skill_id:body.skill_id,title:body.title,query:body.query,parameters:body.parameters,saved_at:Math.floor(Date.now()/1000)}))});
    await page.route('**/v1/apps/workspace/library/web',(route:any)=>route.fulfill({json:library()}));
    await page.route('**/v1/apps/workspace/library/web/saved-searches',(route:any)=>{saves.push(route.request().postDataJSON());return route.fulfill({json:{...library(),first_save:saves.length===1}});});
    await page.route('**/v1/apps/workspace/library/web/settings',(route:any)=>{const body=route.request().postDataJSON();changes.push(body);enabled=body.daily_searches_enabled;return route.fulfill({json:library()});});
    await page.route('**/v1/apps/web/skills/search',(route:any)=>route.fulfill({json:{success:true,data:{results:[{results:[{type:'search_result',title:'Saved garden fixture',url:'https://example.test/garden'}]}]}}}));
    await page.goto(getE2EDebugUrl('/#apps/web'),{waitUntil:'domcontentloaded'});const composer=requestComposer(page);await expect(composer).toBeVisible({timeout:30000});await composer.getByTestId('apps-request-textarea').fill('Find gardens near Berlin');await composer.getByTestId('apps-request-submit').click();
    const fullscreen=page.getByTestId('apps-result-fullscreen');await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Saved garden fixture');await fullscreen.getByRole('button',{name:'Save this search',exact:true}).click();
    await expect.poll(()=>saves.length).toBe(1);expect(saves[0]).toMatchObject({skill_id:'search',parameters:{requests:[{query:'Find gardens near Berlin',count:10}]},query:'Find gardens near Berlin'});expect(saves[0].expected_user_id).toMatch(/^[0-9a-f-]{36}$/i);
    const notice=page.getByTestId('notification').filter({hasText:'Your saved search will run daily and use credits.'});await expect(notice).toBeVisible();await expect(notice).toContainText('latest saved search per app');await expect(notice.getByRole('button',{name:'OK',exact:true})).toBeVisible();
    await notice.getByRole('button',{name:'Turn off',exact:true}).click();await expect.poll(()=>changes.at(-1)?.daily_searches_enabled).toBe(false);expect(changes.at(-1).expected_user_id).toBe(saves[0].expected_user_id);
    const savedButton=fullscreen.getByTestId('search-template-save-search');await expect(savedButton).toHaveText('Saved search');await expect(savedButton).toHaveAttribute('aria-pressed','true');await expect(savedButton).toBeDisabled();expect(saves).toHaveLength(1);expect(enabled).toBe(false);await expect(notice).toHaveCount(0);
    const rootHash=appHash(page);await page.reload({waitUntil:'domcontentloaded'});await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-save-search')).toHaveAttribute('aria-pressed','true');await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-save-search')).toBeDisabled();expect(saves).toHaveLength(1);expect(appHash(page)).toBe(rootHash);
    await page.getByTestId('apps-result-fullscreen').getByTestId('embed-minimize').click();await page.getByTestId('apps-settings-open').click();const settings=page.getByTestId('settings-menu');await expect(settings).toBeVisible();await expect(settings.getByTestId('apps-daily-searches').getByRole('checkbox')).not.toBeChecked();
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
  test('workflow interpretation submits the followup and readable result context once to existing authoring',async({page}:{page:any})=>{
    test.setTimeout(120000);expect(getTestAccount().email).toBeTruthy();await page.goto(getE2EDebugUrl('/'),{waitUntil:'domcontentloaded'});await loginToTestAccount(page,()=>{},async()=>{});
    await fixtureSkillDetails(page,{app_id:'web',skill_id:'search',name:'Search web',primary_fields:['query'],anonymous_allowed:false,requestEnvelope:true});
    const text='Turn this garden search into a weekly workflow';const requests:any[]=[];let skillPosts=0,followupInterpretations=0,workflowId:string|undefined;
    await page.route('**/v1/apps/workspace/interpret',(route:any)=>{const body=route.request().postDataJSON();if(body.text===text){followupInterpretations++;expect(body.context.input.requests[0].query).toBe('Find gardens');expect(JSON.stringify(body.context.result)).toContain('Garden handoff context');return route.fulfill({json:{action:'workflow',request_id:body.request_id}});}return route.fulfill({json:{action:'execute',request_id:body.request_id,skill_id:'search',input:{requests:[{query:'Find gardens',count:1}]}}});});
    await page.route('**/v1/apps/web/skills/search',(route:any)=>{skillPosts++;return route.fulfill({json:{success:true,data:{results:[{results:[{type:'search_result',title:'Garden handoff context',url:'https://example.test/weekly-garden',description:'Garden result retained for workflow interpretation.'}]}]}}});});
    const api=deriveApiUrl(page.url());
    await page.route('**/v1/workflows/input/stream',async(route:any)=>{
      const body=route.request().postDataJSON();requests.push(body);expect(body.text).toContain(text);expect(body.text).toContain('Garden handoff context');expect(body.text).toContain('Find gardens');expect(body.text.length).toBeLessThanOrEqual(20000);expect(body).toMatchObject({input_type:'text',selected_workflow_id:null,optimistic_save:true});expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/i);
      const response=await page.request.post(`${api}/v1/workflows`,{data:{title:`Apps workflow handoff ${Date.now()}`,enabled:false,graph:{version:2,trigger_node_id:'manual',nodes:[{id:'manual',type:'manual_trigger',title:'Manual start',config:{}}],edges:[]}}});expect(response.ok()).toBe(true);const workflow=(await response.json()).workflow;workflowId=workflow.id;
      await route.fulfill({contentType:'text/event-stream',body:`data: ${JSON.stringify({type:'session',session:{session_id:'apps-workflow-handoff',status:'executed',workflow,mutations:[{type:'create_workflow',target_id:workflow.id}]}})}\n\n`});
    });
    try{
      await page.goto(getE2EDebugUrl('/#apps/web'),{waitUntil:'domcontentloaded'});const composer=requestComposer(page);await expect(composer).toBeVisible({timeout:30000});await composer.getByTestId('apps-request-textarea').fill('Find gardens');await composer.getByTestId('apps-request-submit').click();
      const fullscreen=page.getByTestId('apps-result-fullscreen');await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Garden handoff context');await fullscreen.getByTestId('apps-request-textarea').fill(text);await fullscreen.getByTestId('apps-request-submit').click();
      await expect.poll(()=>followupInterpretations).toBe(1);await expect.poll(()=>requests.length).toBe(1);await expect(page.getByTestId('apps-workspace')).toHaveCount(0);await expect.poll(()=>workflowId).toBeTruthy();expect(skillPosts).toBe(1);expect(page.url()).not.toContain('model=');
    }finally{if(workflowId)await page.request.delete(`${api}/v1/workflows/${workflowId}`);}
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
  test('Create workflow link submits one bounded search context with the native query and options', async ({ page }: { page: any }) => {
    test.setTimeout(120000);
    expect(getTestAccount().email).toBeTruthy();
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    await fixtureSkillDetails(page, { app_id: 'web', skill_id: 'search', name: 'Search web', primary_fields: ['query'], anonymous_allowed: false, requestEnvelope: true });
    const nativeInput = { requests: [{ query: 'Find gardens near Berlin', count: 7 }] };
    const largeResult = { type: 'search_result', title: 'Direct workflow garden context', url: 'https://example.test/direct-garden', description: 'Garden details '.repeat(3000) };
    expect(JSON.stringify(largeResult).length).toBeGreaterThan(39000);
    const requests: any[] = [];
    let interpretations = 0, skillPosts = 0, workflowId: string | undefined;
    const workflowTitle = `Apps direct workflow link ${Date.now()}`;
    await page.route('**/v1/apps/workspace/interpret', (route: any) => {
      interpretations++;
      const body = route.request().postDataJSON();
      return route.fulfill({ json: { action: 'execute', request_id: body.request_id, skill_id: 'search', input: nativeInput } });
    });
    await page.route('**/v1/apps/web/skills/search', (route: any) => {
      skillPosts++;
      expect(route.request().postDataJSON()).toMatchObject(nativeInput);
      return route.fulfill({ json: { success: true, data: { results: [{ results: [largeResult] }] } } });
    });
    const api = deriveApiUrl(page.url());
    await page.route('**/v1/workflows/input/stream', async (route: any) => {
      expect(route.request().method()).toBe('POST');
      const body = route.request().postDataJSON();
      requests.push(body);
      expect(body).toMatchObject({ input_type: 'text', selected_workflow_id: null, optimistic_save: true });
      expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/i);
      expect(body.text.length).toBeLessThanOrEqual(20000);
      expect(body.text).toContain('Create a workflow based on this search.');
      const context = JSON.parse(body.text.split('Result context (data supplied by the user):\n')[1]);
      expect(context).toMatchObject({ skill_id: 'search', input: nativeInput });
      expect(JSON.stringify(context.result)).toContain(largeResult.title);
      expect(JSON.stringify(context.result)).toContain(largeResult.url);
      // Persist a real isolated workflow; authoring SSE remains provider-free.
      const response = await page.request.post(`${api}/v1/workflows`, { data: { title: workflowTitle, enabled: false, graph: { version: 2, trigger_node_id: 'manual', nodes: [{ id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} }], edges: [] } } });
      expect(response.ok()).toBe(true);
      const workflow = (await response.json()).workflow;
      workflowId = workflow.id;
      await route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ type: 'session', session: { session_id: 'apps-direct-workflow-link', status: 'executed', workflow, mutations: [{ type: 'create_workflow', target_id: workflow.id }] } })}\n\n` });
    });
    try {
      await page.goto(getE2EDebugUrl('/#apps/web'), { waitUntil: 'domcontentloaded' });
      const composer = requestComposer(page);
      await expect(composer).toBeVisible({ timeout: 30000 });
      await composer.getByTestId('apps-request-textarea').fill('Find gardens near Berlin');
      await composer.getByTestId('apps-request-submit').click();
      const fullscreen = page.getByTestId('apps-result-fullscreen');
      await expect(fullscreen.getByTestId('search-template-grid')).toContainText(largeResult.title);
      await fullscreen.getByTestId('search-template-create-workflow').click();
      await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
      const detail = page.getByTestId('workflow-detail');
      await expect(detail).toBeVisible();
      await expect(detail.getByTestId('workspace-detail-title')).toHaveText(workflowTitle);
      await expect.poll(() => workflowId).toBeTruthy();
      const persisted = await page.request.get(`${api}/v1/workflows/${workflowId}`);
      expect(persisted.ok()).toBe(true);
      expect((await persisted.json()).workflow).toMatchObject({ id: workflowId, title: workflowTitle, enabled: false });
      expect(requests).toHaveLength(1);
      expect(skillPosts).toBe(1);
      expect(interpretations).toBe(1);
      await expect(page.getByTestId('workflows-error')).toHaveCount(0);
    } finally {
      if (workflowId) expect((await page.request.delete(`${api}/v1/workflows/${workflowId}`)).ok()).toBe(true);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
  test('workflow handoff failures use a readable notification without an inline HTTP error',async({page}:{page:any})=>{
    test.setTimeout(120000);expect(getTestAccount().email).toBeTruthy();await page.goto(getE2EDebugUrl('/'),{waitUntil:'domcontentloaded'});await loginToTestAccount(page,()=>{},async()=>{});
    await fixtureSkillDetails(page,{app_id:'web',skill_id:'search',name:'Search web',primary_fields:['query'],anonymous_allowed:false,requestEnvelope:true});
    let workflowPosts=0;
    await page.route('**/v1/apps/workspace/interpret',(route:any)=>{const body=route.request().postDataJSON();return route.fulfill({json:{action:'execute',request_id:body.request_id,skill_id:'search',input:{requests:[{query:'Find gardens',count:1}]}}});});
    await page.route('**/v1/apps/web/skills/search',(route:any)=>route.fulfill({json:{success:true,data:{results:[{results:[{type:'search_result',title:'Garden notification context',url:'https://example.test/garden'}]}]}}}));
    await page.route('**/v1/workflows/input/stream',(route:any)=>{workflowPosts++;return route.fulfill({status:422,json:{detail:[{type:'string_too_long',loc:['body','text'],msg:'String should have at most 20000 characters'}]}});});
    await page.goto(getE2EDebugUrl('/#apps/web'),{waitUntil:'domcontentloaded'});const composer=requestComposer(page);await expect(composer).toBeVisible({timeout:30000});await composer.getByTestId('apps-request-textarea').fill('Find gardens');await composer.getByTestId('apps-request-submit').click();
    const fullscreen=page.getByTestId('apps-result-fullscreen');await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Garden notification context');
    await fullscreen.getByTestId('search-template-create-workflow').click();
    await expect.poll(()=>workflowPosts).toBe(1);await expect(page.getByTestId('notification').filter({hasText:'The workflow could not be created. Please try again.'})).toBeVisible();
    await expect(page.getByTestId('workflows-error')).toHaveCount(0);await expect(page.getByText(/Workflow request failed with HTTP/)).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
  test('fullscreen followups refine the prior search or start a new search using current context',async({page}:{page:any})=>{
    await fixtureSkillDetails(page,{app_id:'web',skill_id:'search',name:'Search web',primary_fields:['query'],anonymous_allowed:true,requestEnvelope:true});
    await page.route('**/v1/anonymous/apps/web/skills/search/availability',(route:any)=>route.fulfill({json:{allowed:true}}));const interpreted:any[]=[];const posted:any[]=[];
    await page.route('**/v1/apps/workspace/interpret',(route:any)=>{
      const body=route.request().postDataJSON();interpreted.push(body);const query=body.text==='Find gardens'?'gardens':body.text==='Only gardens open Sundays'?'gardens open Sundays':body.text==='Find libraries'?'libraries':'museums';
      return route.fulfill({json:{action:'execute',request_id:body.request_id,skill_id:'search',input:{requests:[{query,count:1}]}}});
    });
    await page.route('**/v1/anonymous/apps/web/skills/search',(route:any)=>{const body=route.request().postDataJSON();posted.push(body);return route.fulfill({json:{success:true,data:{results:[{results:[{type:'search_result',title:`Result for ${body.requests[0].query}`,url:'https://example.test/refined'}]}]}}});});
    await page.goto(getE2EDebugUrl('/#apps/web'),{waitUntil:'domcontentloaded'});const composer=requestComposer(page);await expect(composer).toBeVisible({timeout:30000});await composer.getByTestId('apps-request-textarea').fill('Find gardens');await composer.getByTestId('apps-request-submit').click();
    const fullscreen=page.getByTestId('apps-result-fullscreen');await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Result for gardens');const firstRoot=new URL(page.url()).hash;
    await fullscreen.getByTestId('apps-request-textarea').fill('Only gardens open Sundays');await fullscreen.getByTestId('apps-request-submit').click();await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Result for gardens open Sundays');
    expect(interpreted[1].context.input.requests[0].query).toBe('gardens');expect(JSON.stringify(interpreted[1].context.result)).toContain('Result for gardens');expect(interpreted[1].context.embed_id).toMatch(/^[0-9a-f-]{36}$/i);expect(new URL(page.url()).hash).not.toBe(firstRoot);
    await fullscreen.getByTestId('apps-request-textarea').fill('Start a new search for museums');await fullscreen.getByTestId('apps-request-submit').click();await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Result for museums');
    expect(interpreted[2].context.input.requests[0].query).toBe('gardens open Sundays');expect(posted.map(input=>input.requests[0].query)).toEqual(['gardens','gardens open Sundays','museums']);
    await fullscreen.getByTestId('embed-minimize').click();
    const home = requestComposer(page); await expect(home).toBeVisible();
    await home.getByTestId('apps-request-textarea').fill('Find libraries'); await home.getByTestId('apps-request-submit').click();
    await expect(fullscreen.getByTestId('search-template-grid')).toContainText('Result for libraries');
    expect(interpreted).toHaveLength(4); expect(interpreted[3]).not.toHaveProperty('context');
    expect(posted[3]).toEqual({ requests: [{ query: 'libraries', count: 1 }] });
  });

});
