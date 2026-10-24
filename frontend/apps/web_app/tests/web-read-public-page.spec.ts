/* eslint-disable @typescript-eslint/no-require-imports */
/** Real public-page transport and encrypted import/persistence, without inference.
 * Direct requests use the existing authenticated prompt-injection-model opt-out.
 * ASCII cleanup remains active; this does not claim default model-safety coverage.
 */
import { test, expect } from './helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { apiTarget } from './helpers/provider-boundary';
import { INPUT, fixtureAudit, npmRead, pipRead, runJson } from './helpers/web-read-public-page';
const { createHash } = require('node:crypto');
const path = require('node:path');
const { runCli, parseCliJson, expectCliSuccess, CLI_DIST } = require('./helpers/cli-test-helpers');
const { seedViaPairedCli } = require('./helpers/owned-encrypted-embed-fixture');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair, workflowCliEnv, runWorkflowCli } = require('./helpers/workflow-cli-e2e-helpers');
const { waitForEmbedFinished, openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

test.setTimeout(240_000);
function usable(response: any) {
  const data = response.data ?? response;
  const result = data.results[0].results[0];
  expect(result.read_status).toBe('usable');
  expect(result.markdown.length).toBeGreaterThan(30000);
  expect(result.markdown).toContain('PUBLIC ARTICLE BEGIN');
  expect(result.markdown).toContain('PUBLIC ARTICLE END 7f531b');
  expect(result.markdown.match(/Section \d{3}:/g)).toHaveLength(240);
  return result;
}

async function expandSavedReadActivity(page: Page, chatId: string) {
  const message = page.locator('.mate-message-content').filter({ hasText: `Saved public page ${chatId}` });
  await expect(message).toBeVisible();
  const activity = message.getByTestId('assistant-activity-group');
  const toggle = activity.getByTestId('assistant-activity-toggle');
  await expect(toggle).toHaveAttribute('aria-expanded', /^(true|false)$/);
  if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(activity.getByTestId('assistant-activity-body')).toBeVisible();
}

// contract-test: direct surface=rest_api assertions=web-read.public-page,web-read.crawler-exclusions,web-read.transport-boundary
test('real API extracts the full allowed article and respects robots, blocks and private redirects', async ({ request }) => {
  const { base, headers } = apiTarget();
  const allowed = await request.post(`${base}/v1/apps/web/skills/read`, { headers, data: INPUT });
  expect(allowed.status()).toBe(200);
  usable(await allowed.json());
  for (const [route, code] of [['robots-denied', 'robots_denied'], ['blocked', 'http_error'], ['redirect-private', 'unsafe_address']]) {
    const denied = await request.post(`${base}/v1/apps/web/skills/read`, {
      headers, data: { security: { prompt_injection_protection: 'disabled' }, requests: [{ id: route, url: `https://read-page.ci.test/${route}` }] },
    });
    expect(denied.status()).toBe(200);
    const response = await denied.json();
    const group = (response.data ?? response).results[0];
    expect(group.error_code).toBe(code);
    if (route === 'blocked') expect(group.http_status).toBe(403);
    expect(group.results).toEqual([]);
    expect(group.usage.credits_charged).toBe(0);
    expect(response.credits_charged).toBe(0);
  }
  const audit = await fixtureAudit();
  expect(audit.counts['/robots-denied'] || 0).toBe(0);
  expect(audit.counts['/blocked']).toBe(1);
  expect(audit.counts['/redirect-private']).toBe(1);
  expect(audit.counts['/private'] || 0).toBe(0);
  expect(audit.headers.every(row => !row.has_authorization && !row.has_cookie)).toBe(true);
  expect(audit.headers.every(row => row.user_agent.startsWith('OpenMates'))).toBe(true);
});

// contract-test: direct surface=cli assertions=web-read.public-page,web-read.saved-full-text
test('CLI skill command returns full extracted markdown', async () => {
  const { base } = apiTarget();
  const response = await runCli(base, ['apps', 'web', 'read', '--input', JSON.stringify(INPUT), '--json'], 90_000, {
    env: { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'web-read-public-page.spec.ts' },
  });
  expect(response.recording, 'A real terminal recording is required; a headless browser video is not CLI proof').toBeTruthy();
  expectCliSuccess(response);
  usable(parseCliJson(response));
});

// contract-test: direct surface=sdks.npm assertions=web-read.public-page
test('npm SDK executes the actual public-page reader', async () => {
  const { base } = apiTarget();
  usable(npmRead(base, process.env.OPENMATES_TEST_ACCOUNT_API_KEY!));
});

// contract-test: direct surface=sdks.pip assertions=web-read.public-page
test('pip SDK executes the actual public-page reader', async () => {
  const { base } = apiTarget();
  usable(pipRead(base, process.env.OPENMATES_TEST_ACCOUNT_API_KEY!));
});

// contract-test: direct surface=gui.web assertions=web-read.saved-full-text,web-read.public-page
test('actual extraction survives encrypted saved history, reload and the full fullscreen article', async ({ page, request }) => {
  const { base, headers } = apiTarget();
  const response = await request.post(`${base}/v1/apps/web/skills/read`, { headers, data: INPUT });
  expect(response.status()).toBe(200);
  const result = usable(await response.json());
  const home = createWorkflowCliHome('public-page-read');
  let seed: any;
  try {
    await loginWorkflowCliViaPair(page, base, home, 'public-page-read');
    seed = seedViaPairedCli(base, home, 'read', 0, false, result);
    const checksum = runJson('node', ['--input-type=module', '-e', `
      const {OpenMatesClient}=await import(${JSON.stringify(path.join(path.dirname(CLI_DIST), 'index.js'))});
      const {createHash}=await import('node:crypto');
      const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
      await client.ensureSynced(true,[${JSON.stringify(seed.chatId)}],{personal:true});
      const saved=await client.getEmbed(${JSON.stringify(seed.embedId)},{preferCache:false,chatId:${JSON.stringify(seed.chatId)}});
      console.log(JSON.stringify({sha256:createHash('sha256').update(saved.content.results[0].markdown).digest('hex')}));
    `], workflowCliEnv(base, home));
    expect(checksum.sha256).toBe(createHash('sha256').update(result.markdown).digest('hex'));
    await page.goto(`${process.env.PLAYWRIGHT_TEST_BASE_URL}/#chat-id=${seed.chatId}`);
    await expandSavedReadActivity(page, seed.chatId);
    await waitForEmbedFinished(page, 'web', 'read');
    await page.reload();
    await expandSavedReadActivity(page, seed.chatId);
    const card = await waitForEmbedFinished(page, 'web', 'read');
    const fullscreen = await openFullscreen(page, card);
    const article = fullscreen.locator('.markdown-content');
    await expect(article).toContainText('PUBLIC ARTICLE BEGIN');
    await expect(article).toContainText('PUBLIC ARTICLE END 7f531b');
    expect((await article.innerText()).match(/Section \d{3}:/g)).toHaveLength(240);
    await test.info().attach('saved-article-start', { body: await page.screenshot(), contentType: 'image/png' });
    await article.getByText('PUBLIC ARTICLE END 7f531b', { exact: true }).scrollIntoViewIfNeeded();
    await test.info().attach('saved-article-end', { body: await page.screenshot(), contentType: 'image/png' });
    await closeFullscreen(page, fullscreen);
  } catch (error) {
    // Capture the failing state before cleanup removes the saved test chat.
    try {
      await test.info().attach('saved-article-failure-before-cleanup', { body: await page.screenshot(), contentType: 'image/png' });
      await test.info().attach('saved-article-context-before-cleanup', { body: await page.locator('body').innerText(), contentType: 'text/plain' });
    } catch (captureError) {
      await test.info().attach('saved-article-capture-error', { body: String(captureError), contentType: 'text/plain' });
    }
    throw error;
  } finally {
    if (seed) await runWorkflowCli(base, home, ['chats', 'delete', seed.chatId, '--yes'], 30_000);
    removeWorkflowCliHome(home);
  }
});
