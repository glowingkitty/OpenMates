// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
const chatId = '7341f901-c361-4077-bdad-ae87aaf1faee';
const preview = (component: string, width: number, variant?: string, theme = 'light') =>
  `/dev/preview/projects/${component}?${new URLSearchParams({ theme, background: theme === 'dark' ? '#161616' : '#dbeafe', width: String(width), chrome: '0', ...(variant ? { variant } : {}) })}`;

// contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.files.connected-embed-previews,projects.surface.semantic-parity
test('interleaves linked chats with connected files and folders in the same alphabetical grid', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto(preview('ProjectsPage', 1100, 'mixedRemoteChats'));
  await waitForComponentPreview(page);
  const grid = page.getByTestId('project-remote-directory-results');
  const keys = () => grid.locator('[data-project-entry]').evaluateAll(elements => elements.map(element => element.getAttribute('data-project-entry')));
  await expect.poll(keys).toEqual(['remote:architecture.pdf', 'chat:remote-chat-budget-chat', 'remote:README.md', 'remote:Research', `chat:remote-chat-${chatId}`]);
  await expect(grid.getByTestId('project-chat-card')).toHaveCount(2);
  await expect(grid.getByTestId('project-chat-card').first()).toHaveCSS('height', '200px');
  await expect(grid.getByTestId('project-remote-entry').filter({ hasText: 'architecture.pdf' })).toHaveCSS('height', '200px');
  await page.getByTestId('project-folders-panel').screenshot({ path: test.info().outputPath('mixed-project-grid.png') });
  await grid.getByTestId('project-remote-entry').filter({ hasText: 'Research' }).getByRole('button').click();
  await grid.getByTestId('project-remote-entry').filter({ hasText: 'Q4' }).getByRole('button').click();
  await expect(grid.getByTestId('project-chat-card')).toContainText('Q4 planning');
  await expect(grid.getByTestId('project-remote-entry')).toContainText('notes.md');
  await page.getByRole('button', { name: 'List', exact: true }).click();
  await expect(grid.getByTestId('project-chat-card')).toHaveCSS('height', '78px');
  await expect.poll(keys).toEqual(['remote:Research/Q4/notes.md', 'chat:remote-chat-nested-chat']);
  await page.getByLabel('Project folder path').getByRole('button', { name: 'Research', exact: true }).click();
  await grid.getByTestId('project-chat-folder').filter({ hasText: 'Planning' }).click();
  await grid.getByTestId('project-chat-folder').filter({ hasText: 'Deep' }).click();
  await expect(grid.getByTestId('project-chat-card')).toContainText('Planning review');
  await expect(page.getByTestId('project-remote-error')).toHaveCount(0);
  await page.getByLabel('Project folder path').getByRole('button', { name: 'Planning', exact: true }).click();
  await expect(grid.getByTestId('project-chat-folder')).toContainText('Deep');
  await expect(page.getByTestId('project-remote-error')).toHaveCount(0);
  await page.getByTestId('project-source-root').click();
  await expect(grid.getByTestId('project-chat-card')).toHaveCount(2);
  await expect.poll(keys).toEqual(['remote:architecture.pdf', 'chat:remote-chat-budget-chat', 'remote:README.md', 'remote:Research', `chat:remote-chat-${chatId}`]);
});

// contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.files.connected-embed-previews,projects.surface.semantic-parity
test('keeps linked chats and deep folder paths reachable offline without remote requests', async ({ page }) => {
  const remoteRequests: string[] = [];
  page.on('request', request => { if (/\/projects\/[^/]+\/sources\/[^/]+\/requests/.test(request.url())) remoteRequests.push(request.url()); });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(preview('ProjectsPage', 390, 'offlineRemoteChats', 'dark'));
  await waitForComponentPreview(page);
  const grid = page.getByTestId('project-remote-directory-results');
  await expect(page.getByTestId('project-remote-error')).toContainText('offline');
  await expect(grid.getByTestId('project-chat-card')).toHaveCount(2);
  await expect(grid.getByTestId('project-remote-entry')).toHaveCount(0);
  await grid.getByTestId('project-chat-folder').filter({ hasText: 'Research' }).getByRole('button').click();
  await grid.getByTestId('project-chat-folder').filter({ hasText: 'Q4' }).getByRole('button').click();
  const chat = grid.getByTestId('project-chat-card');
  await expect(chat).toContainText('Q4 planning');
  await expect(chat).toHaveAttribute('href', '/#chat-id=nested-chat');
  await expect(page.getByLabel('Project folder path')).toContainText('Research');
  await expect(page.getByLabel('Project folder path')).toContainText('Q4');
  await expect(grid.getByTestId('project-remote-cloud-badge')).toHaveCount(0);
  expect(remoteRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByTestId('project-folders-panel').screenshot({ path: test.info().outputPath('offline-nested-chat.png') });
  await page.getByLabel('Project folder path').getByRole('button', { name: 'Research', exact: true }).click();
  await expect(grid.getByTestId('project-chat-folder').filter({ hasText: 'Q4' })).toBeVisible();
  await page.getByTestId('project-source-root').click();
  await expect(grid.getByTestId('project-chat-card')).toHaveCount(2);
  expect(remoteRequests).toEqual([]);
  await grid.getByTestId('project-chat-folder').filter({ hasText: 'Research' }).getByRole('button').click();
  await page.getByLabel('Project folder path').getByRole('button', { name: 'Project root' }).click();
  const source = page.getByTestId('project-connected-source-root');
  await expect(source).toHaveAttribute('data-status', 'offline');
  await source.getByRole('button').click();
  await expect(grid.getByTestId('project-chat-card')).toHaveCount(2);
  expect(remoteRequests).toEqual([]);
});

// contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.files.connected-embed-previews,projects.surface.semantic-parity
test('pages a mixed remote grid without dropping chats at cursor boundaries', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto(preview('ProjectsPage', 1100, 'pagedRemoteChats'));
  await waitForComponentPreview(page);
  const grid = page.getByTestId('project-remote-directory-results');
  const entries = grid.locator('[data-project-entry]');
  const keys = () => entries.evaluateAll(elements => elements.map(element => element.getAttribute('data-project-entry')));
  const controls = page.getByTestId('project-remote-page-controls');
  const seen: (string | null)[] = [];
  await expect(entries).toHaveCount(48);
  const first = await keys();
  expect(first[0]).toBe('chat:remote-chat-first-chat');
  seen.push(...first);
  await controls.getByRole('button', { name: 'Next' }).click();
  await expect(controls).toContainText('Page 2');
  await expect(entries).toHaveCount(48);
  await expect(grid.getByTestId('project-chat-card')).toContainText('remote-file-047.ts');
  seen.push(...await keys());
  await controls.getByRole('button', { name: 'Next' }).click();
  await expect(controls).toContainText('Page 3');
  await expect(entries).toHaveCount(33);
  await expect(grid.getByTestId('project-chat-card')).toContainText('z chat');
  await expect(controls.getByRole('button', { name: 'Next' })).toBeDisabled();
  seen.push(...await keys());
  expect(new Set(seen).size).toBe(129);
  expect(seen.filter(key => key?.startsWith('chat:'))).toHaveLength(3);
  await controls.getByRole('button', { name: 'Previous' }).click();
  await controls.getByRole('button', { name: 'Previous' }).click();
  await expect.poll(keys).toEqual(first);
});

for (const [width, theme] of [[400, 'light'], [280, 'dark']] as const) {
  // contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.links.openmates-only-encrypted
  test(`linked chat uses the continuation style at ${width}px in ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(preview('ProjectChatPreview', width, undefined, theme));
    await waitForComponentPreview(page);
    const card = page.getByTestId('project-chat-card');
    await expect(card).toHaveClass(/workspace-continue-card/);
    await expect(card).toContainText('Website launch');
    await expect(card).toContainText('Plan launch copy');
    await expect(card).not.toContainText('Earlier title');
    await expect(card).toHaveAttribute('href', `/#chat-id=${chatId}`);
    await expect(card).toHaveCSS('height', '200px');
    await expect(card).toHaveCSS('border-radius', '30px');
    await expect(card.locator('.resume-large-icon svg')).toBeVisible();
    const geometry = await card.boundingBox();
    expect(geometry!.width).toBeLessThanOrEqual(300);
    expect(geometry!.width).toBeGreaterThan(200);
    if (width === 400) expect(geometry!.width).toBe(300);
    await card.hover();
    await expect(card).not.toHaveCSS('transform', 'none');
    await page.mouse.move(0, 0);
    await card.focus(); await expect(card).toBeFocused();
    await expect(card).toHaveCSS('outline-style', 'solid');
    await card.screenshot({ path: test.info().outputPath(`chat-${width}-${theme}.png`) });
    await card.press('Enter');
    await expect(page).toHaveURL(new RegExp(`#chat-id=${chatId}$`));
  });
}

// contract-test: supporting surface=gui.web assertions=chat-navigation.activity.global-running,projects.surface.semantic-parity
test('processing replaces the gradient and icons with a readable wheel', async ({ page }) => {
  await page.goto(preview('ProjectChatPreview', 400, 'running'));
  await waitForComponentPreview(page);
  const card = page.getByTestId('project-chat-card');
  await expect(card.getByTestId('chat-processing-wheel')).toBeVisible();
  await expect(card.locator('.resume-large-orbs, .resume-large-deco')).toHaveCount(0);
  await expect(card).toHaveCSS('background-image', 'none');
  await expect(card).toContainText('Website launch');
  expect(await card.locator('.resume-chat-kind-badge').evaluate(element => getComputedStyle(element).color)).not.toBe('rgba(255, 255, 255, 0.94)');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(card.getByTestId('chat-processing-wheel')).toHaveCSS('animation-name', 'none');
  await card.screenshot({ path: test.info().outputPath('running-chat.png') });
});

// contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
test('unavailable links hide saved titles and long content remains clipped', async ({ page }) => {
  await page.goto(preview('ProjectChatPreview', 280, 'unavailable'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-chat-state')).toBeVisible();
  await expect(page.getByTestId('project-chat-card')).toHaveCount(0);
  await expect(page.getByTestId('project-chat-preview')).not.toContainText('Earlier title');
  await page.goto(preview('ProjectChatPreview', 280, 'long'));
  await waitForComponentPreview(page);
  const card = page.getByTestId('project-chat-card');
  await expect(card).toHaveCSS('height', '200px');
  await expect(card.locator('.resume-large-title')).toHaveCSS('-webkit-line-clamp', '2');
  const summary = card.locator('.resume-large-summary');
  await expect(summary).toHaveCSS('overflow', 'hidden');
  const clipping = await summary.evaluate(element => ({ client: element.clientHeight, scroll: element.scrollHeight }));
  expect(clipping.scroll).toBeGreaterThan(clipping.client);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await card.screenshot({ path: test.info().outputPath('long-chat-narrow.png') });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.links.openmates-only-encrypted
test('Project overview and Files tiles share the card while list rows stay compact', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto(preview('ProjectsPage', 1100, 'chats'));
  await waitForComponentPreview(page);
  await page.locator('.component-mount').evaluate(element => { element.style.height = 'calc(100vh - 64px)'; });
  const section = page.getByTestId('project-chats-section');
  await expect(section.getByRole('heading', { name: 'Chats' })).toBeVisible();
  await expect(section.getByTestId('project-chat-card')).toContainText('Website launch');
  await section.screenshot({ path: test.info().outputPath('project-overview-chats.png') });
  await page.getByTestId('project-tab-folders').click();
  await expect(page.getByTestId('project-chat-card')).toHaveCSS('height', '200px');
  await expect(page.getByTestId('project-chat-card')).toHaveAttribute('href', `/#chat-id=${chatId}`);
  await page.getByTestId('project-file-select').click();
  await page.getByTestId('project-chat-card').click();
  await expect(page.getByTestId('project-chat-card')).toHaveCSS('outline-style', 'solid');
  await expect(page.getByTestId('project-chat-card')).toHaveCSS('border-radius', '30px');
  await expect(page).toHaveURL(/\/dev\/preview\/projects\/ProjectsPage/);
  await expect(page.getByTestId('project-file-move-selected')).toBeEnabled();
  await page.getByTestId('project-file-cancel-selection').click();
  await page.goto(preview('ProjectBrowserItem', 400, 'list'));
  await waitForComponentPreview(page);
  const row = page.getByTestId('project-chat-card');
  await expect(row).toContainText('Website launch');
  await expect(row).toHaveAttribute('href', '/#chat-id=preview-chat');
  expect((await row.boundingBox())!.height).toBeLessThanOrEqual(90);
  await row.focus(); await expect(row).toBeFocused();
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('chat section renders its linked cards and omits an empty section', async ({ page }) => {
  await page.goto(preview('ProjectChatsSection', 700));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-chat-card')).toHaveCount(2);
  await expect(page.getByTestId('project-chat-card').nth(1)).toContainText('Audience research');
  await page.goto(preview('ProjectChatsSection', 280, 'empty'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-chats-section')).toHaveCount(0);
});
