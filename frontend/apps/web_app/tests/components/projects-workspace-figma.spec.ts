import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const preview = (width: number, variant?: string) =>
  `/dev/preview/projects/ProjectsPage?theme=light&background=%23f3f3f3&width=${width}&chrome=0${variant ? `&variant=${variant}` : ''}`;

async function waitForLexend(page: import('@playwright/test').Page): Promise<void> {
  await page.waitForFunction(() => document.documentElement.dataset.uiFont === 'lexend');
  const loadedFaceCount = await page.evaluate(async () => (await document.fonts.load('500 16px "Lexend Deca Variable"')).length);
  expect(loadedFaceCount).toBeGreaterThan(0);
  await page.waitForFunction(() => document.fonts.check('500 16px "Lexend Deca Variable"'));
}

async function waitForProjectsPreview(page: import('@playwright/test').Page): Promise<void> {
  await waitForComponentPreview(page);
  // ProjectsPage fills its application host. Give the bare preview the same
  // bounded height so scrolling and split-pane geometry match the real shell.
  await page.locator('.component-mount').evaluate((element) => {
    element.style.height = 'calc(100vh - 64px)';
  });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener('project-workspace-preview-action', (event) => {
      const detail = (event as CustomEvent<{ action: string; target?: unknown }>).detail;
      document.documentElement.dataset.projectWorkspaceAction = detail.action;
      document.documentElement.dataset.projectWorkspaceTarget = JSON.stringify(detail.target ?? null);
    });
  });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('keeps the Figma project header and icon tabs while switching workspace panels', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(preview(1512));
  await waitForProjectsPreview(page);
  await waitForLexend(page);

  const header = page.getByTestId('project-workspace-header');
  await expect(header).toBeVisible();
  await expect(header).toHaveAttribute('data-header-system', 'workspace-detail');
  await expect(header).toHaveCSS('font-family', /Lexend Deca Variable/);
  const headerBox = await header.boundingBox();
  expect(headerBox).not.toBeNull();
  expect(headerBox!.height).toBeGreaterThanOrEqual(400);
  const mainBox = await page.getByTestId('project-management').boundingBox();
  const tabsBox = await page.getByTestId('project-tabs').boundingBox();
  const selectedTabPillBox = await page.getByTestId('project-tabs').locator('.settings-tabs-pill').boundingBox();
  const panelBox = await page.getByTestId('project-overview-panel').boundingBox();
  expect(mainBox).not.toBeNull();
  expect(tabsBox).not.toBeNull();
  expect(selectedTabPillBox).not.toBeNull();
  expect(panelBox).not.toBeNull();
  expect(Math.abs(headerBox!.x - mainBox!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(headerBox!.y - mainBox!.y)).toBeLessThanOrEqual(1);
  expect(Math.abs((headerBox!.x + headerBox!.width) - (mainBox!.x + mainBox!.width))).toBeLessThanOrEqual(1);
  expect(tabsBox!.width).toBeLessThanOrEqual(220);
  expect(Math.abs((selectedTabPillBox!.y + selectedTabPillBox!.height / 2) - panelBox!.y)).toBeLessThanOrEqual(1);
  expect(panelBox!.width).toBeLessThanOrEqual(1024);

  await page.getByTestId('project-more-button').click();
  const projectSettingsButton = page.getByTestId('project-settings-button');
  const projectDeleteButton = page.getByTestId('project-delete-button');
  await expect(projectSettingsButton).toBeVisible();
  await expect(projectDeleteButton).toBeVisible();
  const settingsPillBox = await projectSettingsButton.locator('..').boundingBox();
  const deletePillBox = await projectDeleteButton.locator('..').boundingBox();
  expect(settingsPillBox).not.toBeNull();
  expect(deletePillBox).not.toBeNull();
  expect(Math.abs(settingsPillBox!.x - deletePillBox!.x)).toBeLessThanOrEqual(1);
  expect(settingsPillBox!.width).toBeLessThan(deletePillBox!.width);
  await expect(header.getByTestId('project-upload-button')).toHaveCount(0);
  await expect(header.getByTestId('project-folder-create-menu-button')).toHaveCount(0);

  const started = await page.getByTestId('project-started-date').boundingBox();
  expect(started).not.toBeNull();
  expect(started!.y + started!.height).toBeGreaterThan(headerBox!.y + headerBox!.height - 50);
  await expect(page.getByTestId('project-overview-panel')).toBeVisible();
  await expect(page.getByTestId('project-empty-items')).toBeAttached();
  await expect(page.getByTestId('project-tab-folders')).toHaveAttribute('aria-label', 'Files');
  await testInfo.attach('projects-overview-desktop', { body: await page.getByTestId('projects-page').screenshot(), contentType: 'image/png' });

  await page.getByTestId('project-tab-folders').click();
  await expect(page.getByTestId('project-folders-panel')).toBeVisible();
  await expect(page.getByTestId('project-folder-search')).toBeVisible();
  await expect(page.getByTestId('project-folder-actions')).toBeVisible();
  await expect(page.getByTestId('project-folder-card')).toHaveCount(2);
  await expect(page.getByTestId('project-folder-sort')).toContainText('Most recent first');
  await expect(page.getByTestId('project-folder-child')).toHaveCount(5);
  await expect(page.getByTestId('project-item-card')).toHaveCount(3);
  const sharedPreviews = page.getByTestId('project-item-card').locator('.unified-embed-preview');
  await expect(sharedPreviews).toHaveCount(3);
  await expect(sharedPreviews.nth(0)).toHaveAttribute('data-app-id', 'code');
  await expect(sharedPreviews.nth(1)).toHaveAttribute('data-app-id', 'docs');
  await expect(sharedPreviews.nth(2)).toHaveAttribute('data-app-id', 'pdf');
  await expect(sharedPreviews.nth(2)).toHaveAttribute('data-skill-id', 'read');
  await expect(sharedPreviews.nth(2)).toContainText('architecture.pdf');
  await expect(sharedPreviews.nth(2)).toContainText('12 pages');
  await expect(page.getByTestId('project-item-card').getByTestId('project-remote-cloud-badge')).toHaveCount(0);
  await expect(page.getByTestId('project-item-card').locator('.basic-infos-bar.desktop')).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    const previewBox = await sharedPreviews.nth(index).boundingBox();
    const cardBox = await page.getByTestId('project-item-card').nth(index).boundingBox();
    expect(previewBox).not.toBeNull();
    expect(cardBox).not.toBeNull();
    expect(previewBox!.width).toBeGreaterThanOrEqual(299);
    expect(previewBox!.height).toBeGreaterThanOrEqual(199);
    expect(cardBox!.height).toBeGreaterThanOrEqual(previewBox!.height);
  }
  const folderPreviews = page.getByTestId('project-folder-card').locator('.unified-embed-preview');
  await expect(folderPreviews).toHaveCount(2);
  await expect(folderPreviews.nth(0)).toHaveAttribute('data-app-id', 'files');
  await expect(page.getByTestId('project-folder-card').locator('.basic-infos-bar.desktop')).toHaveCount(2);
  await expect(page.getByTestId('project-remote-sources-section')).toHaveCount(0);
  await expect(page.getByTestId('project-folder-name-input')).toHaveCount(0);

  const searchIconBox = await page.locator('.folder-search .search-icon').boundingBox();
  const searchInputBox = await page.getByTestId('project-folder-search').boundingBox();
  const sortIconBox = await page.locator('.sort-button .sort-icon').boundingBox();
  expect(searchIconBox).not.toBeNull();
  expect(searchInputBox).not.toBeNull();
  expect(sortIconBox).not.toBeNull();
  expect(searchInputBox!.x - (searchIconBox!.x + searchIconBox!.width)).toBeLessThanOrEqual(16);
  expect(Math.abs(sortIconBox!.width - sortIconBox!.height)).toBeLessThanOrEqual(1);

  const uploadButtonBox = await page.getByTestId('project-upload-button').boundingBox();
  const uploadIconBox = await page.getByTestId('project-upload-button').locator('.upload-icon').boundingBox();
  const createButton = page.getByTestId('project-folder-create-menu-button');
  const createButtonBox = await createButton.boundingBox();
  const createIcon = createButton.locator('.clickable-icon.icon_create');
  const createIconBox = await createIcon.boundingBox();
  expect(uploadButtonBox).not.toBeNull();
  expect(uploadIconBox).not.toBeNull();
  expect(createButtonBox).not.toBeNull();
  expect(createIconBox).not.toBeNull();
  expect(Math.abs((uploadIconBox!.x + uploadIconBox!.width / 2) - (uploadButtonBox!.x + uploadButtonBox!.width / 2))).toBeLessThanOrEqual(1);
  expect(Math.abs((createIconBox!.x + createIconBox!.width / 2) - (createButtonBox!.x + createButtonBox!.width / 2))).toBeLessThanOrEqual(1);

  await testInfo.attach('projects-files-desktop', { body: await page.getByTestId('project-folders-panel').screenshot(), contentType: 'image/png' });

  await sharedPreviews.first().click();
  const viewer = page.getByTestId('project-embed-viewer');
  await expect(viewer).toBeVisible();
  const splitProjectBox = await page.getByTestId('projects-page').boundingBox();
  const viewerBox = await viewer.boundingBox();
  expect(splitProjectBox).not.toBeNull();
  expect(viewerBox).not.toBeNull();
  expect(splitProjectBox!.width).toBeLessThanOrEqual(401);
  expect(viewerBox!.x).toBeGreaterThanOrEqual(splitProjectBox!.x + splitProjectBox!.width);
  await page.getByTestId('embed-minimize').click();
  await expect(viewer).toHaveCount(0);

  await folderPreviews.first().click();
  await expect(page.getByLabel('Project folder path').getByText('Backend', { exact: true })).toBeVisible();
  await page.getByTestId('project-folder-create-menu-button').click();
  await page.getByTestId('project-create-chat').click();
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-action', 'chat');
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-target', /"folderId":"backend"/);
  await page.getByTestId('project-folder-create-menu-button').click();
  await page.getByTestId('project-create-workflow').click();
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-action', 'workflow');
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-target', /"folderId":"backend"/);
  await page.getByTestId('project-folder-create-menu-button').click();
  await page.getByTestId('project-create-plan').click();
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-action', 'plan');
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-target', /"projectId":"preview-project"/);
  await page.getByRole('button', { name: 'Project root' }).click();
  await expect(page.getByTestId('project-folder-card')).toHaveCount(2);
  await expect(page.getByTestId('project-folder-name-input')).toHaveCount(0);
  await testInfo.attach('projects-workspace-figma-desktop', { body: await page.getByTestId('project-folders-panel').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('contains the project workspace on a phone and retains every tab', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 393, height: 659 });
  await page.goto(preview(393));
  await waitForProjectsPreview(page);
  await waitForLexend(page);

  const pageSurface = page.getByTestId('projects-page');
  const header = page.getByTestId('project-workspace-header');
  await expect(pageSurface).toBeVisible();
  await expect(header).toBeVisible();
  const metrics = await pageSurface.evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);
  await expect(page.getByTestId('project-tab-overview')).toBeVisible();
  await expect(page.getByTestId('project-tab-folders')).toBeVisible();
  await expect(page.getByTestId('project-tab-tasks')).toBeVisible();
  await expect(page.getByTestId('project-readme-upload')).toBeVisible();
  await expect(page.getByTestId('project-readme-create')).toBeVisible();
  await testInfo.attach('projects-workspace-figma-mobile', { body: await pageSurface.screenshot(), contentType: 'image/png' });

  await page.getByTestId('project-tab-folders').click();
  const mobilePreview = page.getByTestId('project-item-card').locator('.unified-embed-preview').first();
  await expect(mobilePreview).toBeVisible();
  await mobilePreview.click();
  const mobileViewer = page.getByTestId('project-embed-viewer');
  await expect(mobileViewer).toBeVisible();
  const mobilePageBox = await pageSurface.boundingBox();
  const mobileViewerBox = await mobileViewer.boundingBox();
  expect(mobilePageBox).not.toBeNull();
  expect(mobileViewerBox).not.toBeNull();
  expect(Math.abs(mobileViewerBox!.x - mobilePageBox!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(mobileViewerBox!.width - mobilePageBox!.width)).toBeLessThanOrEqual(1);
  await testInfo.attach('projects-embed-overlay-mobile', { body: await mobileViewer.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('opens a shared embed beside the Project workspace on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(preview(1512, 'folders'));
  await waitForProjectsPreview(page);

  await page.getByTestId('project-item-card').first().locator('.unified-embed-preview').click();
  const viewer = page.getByTestId('project-embed-viewer');
  await expect(viewer).toBeVisible();
  const projectBox = await page.getByTestId('projects-page').boundingBox();
  const viewerBox = await viewer.boundingBox();
  expect(projectBox).not.toBeNull();
  expect(viewerBox).not.toBeNull();
  expect(projectBox!.width).toBeLessThanOrEqual(401);
  expect(viewerBox!.x).toBeGreaterThanOrEqual(projectBox!.x + projectBox!.width);
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('opens a virtual connected-source preview beside the Project workspace', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(preview(1512, 'connectedSource'));
  await waitForProjectsPreview(page);

  await page.getByTestId('project-connected-source-root').locator('.unified-embed-preview').click();
  await expect(page.getByTestId('project-remote-browser')).toBeVisible();
  const remoteSharedPreview = page.getByTestId('project-remote-preview-card').locator('.unified-embed-preview');
  await expect(remoteSharedPreview).toBeVisible();
  await remoteSharedPreview.click();
  const viewer = page.getByTestId('project-embed-viewer');
  await expect(viewer).toBeVisible();
  const fullscreenOverlay = viewer.getByTestId('embed-fullscreen-overlay');
  await expect(fullscreenOverlay).toBeVisible();
  await expect(fullscreenOverlay).toHaveClass(/host-presented/);
  const fullscreenCode = viewer.getByTestId('code-fullscreen-code');
  await expect(fullscreenCode).toBeVisible();
  await expect(fullscreenCode).toBeInViewport();
  await expect(fullscreenCode).toContainText('Connected project file');
  await expect(viewer.getByTestId('embed-header-provenance')).toHaveText('Streamed from OpenMates repository');
  await expect(viewer.getByTestId('embed-header-provenance-icon')).toBeVisible();
  const remoteBrowser = page.getByTestId('project-remote-browser');
  await expect(remoteBrowser).toBeVisible();
  await expect(page.getByTestId('project-folder-actions')).toBeVisible();
  await expect(page.getByTestId('project-folder-actions').getByRole('button')).toHaveCount(3);
  await expect(page.getByTestId('project-folder-actions').getByRole('button').first()).toHaveCSS('filter', 'none');
  await expect.poll(async () => {
    const actions = await page.getByTestId('project-folder-actions').boundingBox();
    const pane = await page.getByTestId('projects-page').boundingBox();
    return actions && pane ? actions.y - pane.y : Number.POSITIVE_INFINITY;
  }).toBeLessThanOrEqual(28);
  await expect(page.getByTestId('project-remote-parent')).toBeHidden();
  await expect(page.getByTestId('project-remote-search-input')).toBeHidden();
  await expect(page.getByTestId('project-connected-source-root')).toBeHidden();
  await expect(page.getByTestId('project-remote-preview-meta')).toHaveCount(0);
  await expect(page.getByTestId('project-remote-preview-card').locator('.unified-embed-preview')).toBeVisible();
  const localCardBox = await page.getByTestId('project-item-card').first().locator('.unified-embed-preview').boundingBox();
  const remoteCardBox = await page.getByTestId('project-remote-preview-card').locator('.unified-embed-preview').boundingBox();
  expect(localCardBox).not.toBeNull();
  expect(remoteCardBox).not.toBeNull();
  expect(Math.abs(localCardBox!.x - remoteCardBox!.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(localCardBox!.width - remoteCardBox!.width)).toBeLessThanOrEqual(2);
  expect(await remoteBrowser.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  const projectBox = await page.getByTestId('projects-page').boundingBox();
  const viewerBox = await viewer.boundingBox();
  const overlayBox = await fullscreenOverlay.boundingBox();
  expect(projectBox).not.toBeNull();
  expect(viewerBox).not.toBeNull();
  expect(overlayBox).not.toBeNull();
  expect(projectBox!.width).toBeLessThanOrEqual(401);
  expect(viewerBox!.x).toBeGreaterThanOrEqual(projectBox!.x + projectBox!.width);
  expect(Math.abs(overlayBox!.x - viewerBox!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(overlayBox!.y - viewerBox!.y)).toBeLessThanOrEqual(1);
  expect(Math.abs(overlayBox!.width - viewerBox!.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(overlayBox!.height - viewerBox!.height)).toBeLessThanOrEqual(1);
  await testInfo.attach('projects-virtual-remote-split', { body: await page.locator('.projects-workspace-layout').screenshot(), contentType: 'image/png' });
  await testInfo.attach('projects-virtual-remote-viewer', { body: await viewer.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('opens a connected source inside the Files grid with shared folder previews', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 600 });
  await page.goto(preview(1512, 'connectedSource'));
  await waitForProjectsPreview(page);

  const sourceRoot = page.getByTestId('project-connected-source-root');
  await expect(sourceRoot.locator('.unified-embed-preview')).toHaveAttribute('data-app-id', 'files');
  await expect(sourceRoot.getByTestId('project-remote-cloud-badge')).toBeVisible();
  await sourceRoot.locator('.unified-embed-preview').click();
  await expect(page.getByTestId('project-remote-browser')).toBeVisible();
  await expect(page.getByTestId('project-remote-search-input')).toBeVisible();
  await expect(page.getByTestId('project-remote-entry')).toHaveCount(2);
  await expect(page.getByTestId('project-remote-entry').getByTestId('project-remote-cloud-badge')).toHaveCount(2);
  await expect(page.getByTestId('project-remote-entry').filter({ has: page.locator('.unified-embed-preview') })).toHaveCount(2);
  await expect(page.getByTestId('project-remote-entry').filter({ has: page.getByTestId('project-remote-preview-card') })).toHaveCount(1);
  const remoteFileCardBox = await page.getByTestId('project-remote-preview-card').boundingBox();
  expect(remoteFileCardBox).not.toBeNull();
  expect(remoteFileCardBox!.width).toBeLessThanOrEqual(301);

  await page.getByTestId('project-folder-card').first().locator('.unified-embed-preview').click();
  await expect(page.getByTestId('project-remote-browser')).toHaveCount(0);
  await expect(page.getByLabel('Project folder path').getByText('Backend', { exact: true })).toBeVisible();
  await page.getByTestId('project-folder-create-menu-button').click();
  await page.getByTestId('project-create-chat').click();
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-target', /"folderId":"backend"/);
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-target', /"sourceId":null/);

  await page.getByRole('button', { name: 'Project root' }).click();
  await expect(page.getByTestId('project-remote-browser')).toHaveCount(0);
  await page.getByTestId('project-folder-create-menu-button').click();
  await page.getByTestId('project-create-workflow').click();
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-target', /"folderId":null/);
  await expect(page.locator('html')).toHaveAttribute('data-project-workspace-target', /"sourceId":null/);

  const projectMain = page.getByTestId('project-management');
  const projectTabs = page.getByTestId('project-tabs');
  const initialTabsBox = await projectTabs.boundingBox();
  expect(initialTabsBox).not.toBeNull();
  await expect(projectTabs).toHaveCSS('position', 'relative');
  await page.getByTestId('project-connected-source-root').locator('.unified-embed-preview').click();
  const remoteBrowser = page.getByTestId('project-remote-browser');
  await expect(remoteBrowser).toBeVisible();
  await projectMain.evaluate((element) => { element.scrollTop = Math.min(500, element.scrollHeight - element.clientHeight); });
  await expect.poll(() => projectMain.evaluate((element) => element.scrollTop)).toBeGreaterThan(100);
  const scrolledTabsBox = await projectTabs.boundingBox();
  const remoteBrowserBox = await remoteBrowser.boundingBox();
  expect(scrolledTabsBox).not.toBeNull();
  expect(remoteBrowserBox).not.toBeNull();
  expect(scrolledTabsBox!.y).toBeLessThan(initialTabsBox!.y - 100);
  const tabsOverlapRemote = scrolledTabsBox!.x < remoteBrowserBox!.x + remoteBrowserBox!.width
    && scrolledTabsBox!.x + scrolledTabsBox!.width > remoteBrowserBox!.x
    && scrolledTabsBox!.y < remoteBrowserBox!.y + remoteBrowserBox!.height
    && scrolledTabsBox!.y + scrolledTabsBox!.height > remoteBrowserBox!.y;
  expect(tabsOverlapRemote).toBe(false);
  await testInfo.attach('projects-connected-source-scrolled', { body: await page.getByTestId('projects-page').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('keeps the Project overview readable in dark mode', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto('/dev/preview/projects/ProjectsPage?theme=dark&background=%23171717&width=1512&chrome=0');
  await waitForProjectsPreview(page);
  await waitForLexend(page);

  await expect(page.getByTestId('project-workspace-header')).toBeVisible();
  const panel = page.getByTestId('project-overview-panel');
  await expect(panel).toBeAttached();
  await expect(panel).toHaveCSS('background-color', /rgb\(/);
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('keeps shared folder and embed previews readable in dark mode', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto('/dev/preview/projects/ProjectsPage?theme=dark&background=%23171717&width=1512&chrome=0&variant=folders');
  await waitForProjectsPreview(page);
  await waitForLexend(page);

  await expect(page.getByTestId('project-folders-panel')).toBeVisible();
  await expect(page.getByTestId('project-tab-folders').locator('.tab-icon')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
  const darkSelectedTabPillBox = await page.getByTestId('project-tabs').locator('.settings-tabs-pill').boundingBox();
  const darkFilesPanelBox = await page.getByTestId('project-folders-panel').boundingBox();
  expect(darkSelectedTabPillBox).not.toBeNull();
  expect(darkFilesPanelBox).not.toBeNull();
  expect(Math.abs((darkSelectedTabPillBox!.y + darkSelectedTabPillBox!.height / 2) - darkFilesPanelBox!.y)).toBeLessThanOrEqual(1);
  await expect(page.getByTestId('project-folder-card').locator('.unified-embed-preview')).toHaveCount(2);
  await expect(page.getByTestId('project-item-card').locator('.unified-embed-preview')).toHaveCount(3);
  await expect(page.getByTestId('project-folder-name-input')).toHaveCount(0);
  await expect(page.getByTestId('project-remote-sources-section')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,tasks.surface.semantic-parity,tasks.lifecycle.visible
test('embeds the same five-status task board without legacy compact forms', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(preview(1512, 'tasks'));
  await waitForProjectsPreview(page);
  await waitForLexend(page);

  await expect(page.getByTestId('project-tasks-panel')).toBeVisible();
  await expect(page.getByTestId('project-tasks-page')).toBeVisible();
  await expect(page.getByTestId('project-task-toolbar')).toBeVisible();
  await expect(page.getByTestId('project-task-filter-tags')).toContainText('#OpenMates');
  await expect(page.getByTestId('task-board')).toBeVisible();
  for (const status of ['backlog', 'todo', 'in_progress', 'blocked', 'done']) {
    await expect(page.getByTestId(`task-column-${status}`)).toBeAttached();
  }
  await expect(page.getByTestId('project-task-workspace-composer')).toBeVisible();
  await page.getByTestId('project-task-search-input').fill('Design 3D model');
  await expect(page.getByTestId('task-card')).toHaveCount(1);
  await page.getByTestId('project-task-search-input').fill('');
  await page.getByTestId('project-task-search-input').evaluate((element) => (element as HTMLInputElement).blur());
  const pageBox = await page.getByTestId('projects-page').boundingBox();
  const tasksPanelBox = await page.getByTestId('project-tasks-panel').boundingBox();
  const composerBox = await page.getByTestId('project-task-workspace-composer').boundingBox();
  expect(pageBox).not.toBeNull();
  expect(tasksPanelBox).not.toBeNull();
  expect(composerBox).not.toBeNull();
  expect(tasksPanelBox!.width).toBeLessThanOrEqual(1024);
  expect(Math.abs((tasksPanelBox!.x + tasksPanelBox!.width / 2) - (pageBox!.x + pageBox!.width / 2))).toBeLessThan(3);
  expect(Math.abs((composerBox!.x + composerBox!.width / 2) - (pageBox!.x + pageBox!.width / 2))).toBeLessThan(3);
  await expect(page.getByTestId('linked-plans-section')).toHaveCount(0);
  await expect(page.getByTestId('task-create-form')).toHaveCount(0);
  await expect(page.getByTestId('task-extract-card')).toHaveCount(0);
  await testInfo.attach('projects-tasks-figma-desktop', { body: await page.getByTestId('projects-page').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('uses the chat sidebar list pattern for project navigation', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 760 });
  await page.goto(preview(360, 'sidebar'));
  await waitForProjectsPreview(page);
  await waitForLexend(page);

  await expect(page.getByTestId('projects-sidebar')).toBeVisible();
  await expect(page.getByTestId('project-list')).toBeVisible();
  await expect(page.getByTestId('project-card')).toHaveCount(1);
  await expect(page.getByTestId('project-detail-link')).toHaveAttribute('aria-label', 'Open OpenMates');
  await expect(page.getByTestId('project-management')).toHaveCount(0);
});
