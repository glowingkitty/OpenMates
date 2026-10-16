import { expect, test } from './helpers/cookie-audit';
import { getUpcomingOpenMatesEventCards } from '../../../packages/public-site/src/data/events';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { getE2EDebugUrl } = require('./signup-flow-helpers');

test.beforeEach(async ({ page }) => {
  await page.route('**/v1/settings/server-status', async route => {
    // Keep the app's full status response when navigation starts its services.
    if (new URL(route.request().frame().url()).pathname !== '/landing') {
      await route.continue();
      return;
    }
    await route.fulfill({ json: { anonymous_free_usage: { active: true, can_send_text: true } } });
  });
});

// contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.feature-layout,marketing-landing.six-feature-viewport,marketing-landing.destinations,marketing-landing.real-screenshots,marketing-landing.public-content,workflows-ui.workspace.guest-template-preview
test('public landing server-renders and opens real app workspaces', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const htmlResponse = await page.request.get(getE2EDebugUrl('/landing'));
  expect(htmlResponse.ok()).toBe(true);
  expect(htmlResponse.headers()['content-type']).toContain('text/html');
  const html = await htmlResponse.text();
  expect(html).toContain('Your privacy first');
  for (const id of ['actionable', 'privacy', 'model-choice', 'workflows', 'devices', 'open-source']) {
    expect(html).toContain(`id="${id}"`);
  }
  expect(html).toMatch(/<meta[^>]+name="description"[^>]+content="[^"]*actionable chats/i);

  const privateBootstrap: string[] = [];
  const sockets: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname !== '/v1/settings/server-status' && ['fetch', 'xhr'].includes(request.resourceType()) && /\/v1\/(?:auth|chats|sync|settings|websocket)(?:\/|$)/.test(new URL(request.url()).pathname)) {
      privateBootstrap.push(request.url());
    }
  });
  page.on('websocket', socket => sockets.push(socket.url()));
  await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'networkidle' });
  await expect(page.getByTestId('landing-page')).toBeVisible();
  await expect(page.getByTestId('landing-hero')).toBeVisible();
  expect(privateBootstrap).toEqual([]);
  expect(sockets).toEqual([]);

  const railImages = page.getByTestId('landing-hero').locator('.rail-icon img.rail-glyph');
  await expect.poll(async () => railImages.count()).toBeGreaterThanOrEqual(8);
  await expect.poll(async () => railImages.evaluateAll(nodes => nodes.every(node => {
    const image = node as HTMLImageElement;
    return Boolean(image.getAttribute('src')?.trim()) && image.complete && image.naturalWidth > 0
      && image.getBoundingClientRect().width > 0;
  }))).toBe(true);

  const heroIcon = page.getByTestId('landing-hero-ai-icon');
  await expect(heroIcon).toBeVisible();
  await expect(heroIcon.locator('.hero-ai-glyph')).toHaveCSS('mask-image', /ai\.svg/);
  const origin = new URL(page.url()).origin;
  for (const [testId, fragment, workspace] of [
    ['landing-explore-apps', '#apps', 'apps-daily-inspiration-area'],
    ['landing-explore-workflows', '#workflows', 'workflows-start-screen'],
  ] as const) {
    const link = page.getByTestId(testId);
    await expect(link).toHaveAttribute('href', `${origin}/${fragment}`);
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', /noopener/);
    const ownerRequests: string[] = [];
    const recordOwnerRequest = (request: import('@playwright/test').Request) => {
      if (/\/v1\/workflows(?:\/|$)/.test(new URL(request.url()).pathname)) ownerRequests.push(request.url());
    };
    page.context().on('request', recordOwnerRequest);
    const [popup] = await Promise.all([page.waitForEvent('popup'), link.click()]);
    await expect(popup).toHaveURL(new RegExp(`/#${fragment.slice(1)}$`));
    await expect(popup.getByTestId(workspace)).toBeVisible({ timeout: 30_000 });
    if (fragment === '#workflows') {
      await expect(popup.getByTestId('workflows-daily-inspiration-area')).toBeVisible();
      await expect(popup.getByTestId('daily-inspiration-banner')).toBeVisible();
      await expect(popup.getByTestId('all-workflows-grid')).toHaveCount(0);
      const continuation = popup.getByTestId('workflows-workspace-continue');
      await expect(continuation).toBeVisible();
      await expect(continuation.getByTestId('workflow-landing-card')).toHaveCount(5);
      await expect(popup.getByTestId('workflow-input-composer')).toHaveCount(0);
      await continuation.getByTestId('workflow-landing-card').filter({ hasText: 'Weekly Berlin AI events' }).click();
      await expect(popup.getByTestId('workflow-management')).toBeVisible();
      await expect(popup.getByTestId('workspace-detail-title')).toHaveText('Weekly Berlin AI events');
      await expect(popup.getByTestId('workflow-template-panel')).toBeVisible();
      await expect(popup.getByTestId('workflow-graph-renderer')).toHaveAttribute('data-read-only', 'true');
      for (const id of ['workflow-input-composer', 'run-workflow', 'delete-workflow', 'workflow-share', 'workflow-export']) {
        await expect(popup.getByTestId(id)).toHaveCount(0);
      }
      expect(ownerRequests).toEqual([]);
    }
    await popup.close();
    page.context().off('request', recordOwnerRequest);
  }
  const upcoming = getUpcomingOpenMatesEventCards(new Date(), origin);
  const cards = page.getByTestId('landing-event-card');
  await expect(cards).toHaveCount(upcoming.length);
  for (let i = 0; i < upcoming.length; i++) {
    await expect(cards.nth(i)).toHaveAttribute('href', upcoming[i].href);
    await expect(cards.nth(i)).toHaveAttribute('target', '_blank');
  }
  await expect(page.getByTestId('landing-events').getByRole('link', { name: /browse/i })).toHaveCount(0);
});
