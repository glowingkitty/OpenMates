/* eslint-disable @typescript-eslint/no-require-imports */
import { expect, test } from './helpers/cookie-audit';
import { getTestAccount, getE2EDebugUrl } from './signup-flow-helpers';
import { skipWithoutCredentials } from './helpers/env-guard';
import { seedViaPairedCli, type Seed } from './helpers/owned-encrypted-embed-fixture';
import { openChatAfterContextSync } from './helpers/chat-hydration';
import { closeSettingsPanel } from './helpers/settings-readiness';
import { waitForComponentMotion } from './helpers/component-preview';
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
  runWorkflowCli, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');

const credentials = getTestAccount();
test.use({ actionTimeout: 15_000 });

// contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen,settings-ui.shell.lifecycle-and-routing,chats.persistence.client-encrypted
test('app settings open the original encrypted embed over every workspace and return to the same list', async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
  const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('app-embeds-workspace');
  let source: Seed | undefined;
  const panelStates: string[] = [];
  page.on('console', message => {
    const value = message.text();
    if (/^\[AppEmbedsPanel\] (Found \d+ embeds for app_id: [a-z_]+|Validation complete: \d+ of \d+ embeds are valid)$/.test(value)) panelStates.push(value);
    if (/^\[AppEmbedsPanel\].*failed validation: cannot decrypt$/.test(value)) panelStates.push('cannot_decrypt');
    if (/^\[AppEmbedsPanel\].*failed validation: cannot render preview$/.test(value)) panelStates.push('cannot_render_preview');
  });
  try {
    // Start with cleared client stores and a reload before signing in. The
    // fixture must be restored from the isolated backend, without inference.
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Storage.clearDataForOrigin', {
      origin: new URL(page.url()).origin, storageTypes: 'indexeddb,local_storage',
    });
    await cdp.detach();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await loginWorkflowCliViaPair(page, apiUrl, home, 'APP_EMBEDS_WORKSPACE');
    await closeSettingsPanel(page, testInfo);
    source = seedViaPairedCli(apiUrl, home, 'event');
    await page.goto(getE2EDebugUrl(`/#chat-id=${source.chatId}`), { waitUntil: 'domcontentloaded' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await openChatAfterContextSync(page, source.chatId, testInfo);
    await expect(page.getByRole('link', { name: 'Freelance Barcamp Berlin', exact: true })).toBeVisible({ timeout: 60_000 });
    await page.evaluate(async ({ chatId, embedIds }) => {
      const prepare = (window as Window & {
        __openmatesE2EPrepareEmbedCache?: (input: { chatId: string; embedIds: string[]; indexByApp: boolean }) => Promise<{ indexedCount?: number }>;
      }).__openmatesE2EPrepareEmbedCache;
      if (!prepare) throw new Error('Owned encrypted embed fixture hook unavailable');
      const prepared = await prepare({ chatId, embedIds, indexByApp: true });
      if (prepared.indexedCount !== embedIds.length) throw new Error('Owned fixture app index is incomplete');
    }, { chatId: source.chatId, embedIds: [source.embedId, source.childId] });

    const flows = [
      { workspace: '#apps/events', width: 1366 },
      { workspace: '#tasks', width: 1366 },
      { workspace: '#projects', width: 1366 },
      { workspace: '#workflows', width: 1366 },
      { workspace: `#chat-id=${source.chatId}`, width: 1366 },
      { workspace: '#apps/events', width: 390 },
    ];
    for (const { workspace, width } of flows) {
      await test.step(`Open and close app embed over ${workspace.split('=')[0]} at ${width}px`, async () => {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate(hash => { window.location.hash = hash; }, workspace);
        await expect.poll(() => new URL(page.url()).hash).toBe(workspace);
        await expect(page.getByTestId('global-header')).toBeVisible();
        const isChat = workspace.startsWith('#chat-id=');
        if (isChat) {
          await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', source!.chatId);
        } else {
          const surface = workspace === '#tasks' ? page.locator('#main-tasks')
            : workspace === '#projects' ? page.locator('#main-projects')
            : workspace === '#workflows' ? page.getByTestId('workflows-page') : page.getByTestId('apps-workspace');
          await expect(surface).toBeVisible();
          await expect(page.getByTestId('active-chat-container')).toHaveCount(0);
        }
        if (workspace.startsWith('#apps/')) {
          await page.getByTestId('apps-settings-open').click();
        } else {
          // Exercise the normal Settings navigation event while retaining the
          // workspace; selecting Apps from global navigation would leave it.
          await page.evaluate(() => window.dispatchEvent(new CustomEvent('openSettingsMenu', {
            detail: { returnTo: 'apps/events' },
          })));
        }
        const settings = page.getByTestId('settings-menu').filter({ visible: true });
        await expect(settings).toHaveAttribute('data-active-view', 'apps/events');
        const row = settings.getByTestId(`app-embed-${source!.childId}`);
        await expect(row).toBeVisible({ timeout: 30_000 });
        const before = page.url();
        expect(new URL(before).hash.split('&')[0]).toBe(workspace);
        await row.getByTestId('embed-preview').click();
        const viewer = page.getByTestId('standalone-embed-fullscreen');
        await expect(viewer).toBeVisible();
        await expect(viewer.getByTestId('event-description')).toHaveText('Recovered encrypted event details');
        await expect(viewer.getByTestId('event-venue-card')).toContainText('Original encrypted event venue');
        expect(page.url()).toBe(before);
        await waitForComponentMotion(viewer.getByTestId('embed-fullscreen-overlay'));
        await viewer.getByTestId('embed-minimize').click();
        await expect(viewer).toHaveCount(0);
        await expect(row).toBeVisible();
        expect(page.url()).toBe(before);
        await closeSettingsPanel(page, testInfo);
      });
    }
  } finally {
    await testInfo.attach('workspace-embed-fixture', {
      body: JSON.stringify({ encryptedServerFixture: Boolean(source), inference: false, panelStates }), contentType: 'application/json',
    });
    try {
      if (source) {
        const deletion = await runWorkflowCli(apiUrl, home, ['chats', 'delete', source.chatId, '--yes'], 15_000);
        expect(deletion.code, deletion.stderr).toBe(0);
      }
    } finally { removeWorkflowCliHome(home); }
  }
});
