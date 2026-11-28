import type { Browser, Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { expect, test } from './helpers/cookie-audit';
import * as live from './helpers/live-collab';
// eslint-disable-next-line @typescript-eslint/no-require-imports -- The shared signup helper exports CommonJS.
const { getTestAccount } = require('./signup-flow-helpers');

const cell = (page: Page) => page.getByTestId('sheet-live-cell').and(page.locator('[data-cell-id="r1:c1"]'));
const toolbar = (page: Page) => page.getByTestId('sheet-format-toolbar');
const bold = (page: Page) => toolbar(page).getByRole('button', { name: 'Bold', exact: true });

test.afterEach(async () => {
  await live.attachLiveDiagnostics();
});

// contract-test: direct surface=gui.web assertions=rich-sheets.editing.toolbar-and-layout,rich-sheets.collaboration.shared-history,rich-sheets.exchange.workbook-and-csv
test('Team members format one cell together, undo locally and restore its formatted version', async ({ page, browser }: { page: Page; browser: Browser }) => {
  test.setTimeout(420_000);
  const owner = getTestAccount(1);
  const member = getTestAccount(2);
  if (!owner.email || !member.email || owner.email === member.email) {
    throw new Error('Rich sheet collaboration needs two isolated Team members');
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await live.enableLiveFlag(page.context());
  await live.loginToTestAccount(page, undefined, undefined, { credentials: owner });
  const setup = await live.openLivePair(page, browser, owner, member, 'sheet', 'Garden supplies', 'Supply budget');
  const remote = setup.member;
  const memberVideo = remote.video();

  try {
    const viewers = [page, remote];
    for (const viewer of viewers) {
      await expect(cell(viewer)).toBeVisible({ timeout: 30_000 });
      await expect(viewer.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved');
      await expect(viewer.getByTestId('sheet-pin-cover')).toHaveCount(0);
    }
    await cell(page).getByRole('button').click();
    const input = page.getByTestId('sheet-live-cell-input');
    await input.fill('42');
    await input.press('Enter');
    await expect(cell(remote)).toContainText('42');

    await cell(remote).getByRole('button').click();
    const italic = toolbar(remote).getByRole('button', { name: 'Italic', exact: true });
    await Promise.all([bold(page).click(), italic.click()]);
    for (const viewer of viewers) {
      await expect(cell(viewer)).toHaveCSS('font-weight', '700');
      await expect(cell(viewer)).toHaveCSS('font-style', 'italic');
      await expect(cell(viewer)).toContainText('42');
    }

    await toolbar(page).getByRole('button', { name: 'Undo formatting', exact: true }).click();
    for (const viewer of viewers) {
      await expect(cell(viewer)).not.toHaveCSS('font-weight', '700');
      await expect(cell(viewer)).toHaveCSS('font-style', 'italic');
    }
    await live.shot(page, 'undo-keeps-the-other-editors-style');

    await bold(page).click();
    await toolbar(page).getByText('Sheet layout', { exact: true }).click();
    const freeze = toolbar(page).getByLabel('Frozen rows');
    await freeze.fill('1');
    await freeze.blur();
    for (const viewer of viewers) {
      await expect(cell(viewer)).toHaveCSS('font-weight', '700');
      await expect(viewer.getByTestId('sheet-live-header').first()).toHaveCSS('position', 'sticky');
    }
    await live.shot(page, 'owner-formatted-and-froze-sheet');
    await live.shot(remote, 'member-received-the-same-formatting');

    const viewer = page.getByTestId('project-embed-viewer');
    const csvButton = viewer.getByTestId('sheet-download-csv');
    if (!(await csvButton.isVisible())) await viewer.getByRole('button', { name: 'More', exact: true }).click();
    const [csv] = await Promise.all([page.waitForEvent('download'), csvButton.click()]);
    expect(csv.suggestedFilename()).toMatch(/\.csv$/);
    expect(await readFile(await csv.path(), 'utf8')).toContain('\r\n42,,\r\n');

    const timeline = page.getByTestId('embed-version-timeline');
    const edit = page.getByTestId('sheet-edit-toggle');
    await edit.click();
    await expect(timeline.getByTestId('version-dot-2')).toBeVisible({ timeout: 30_000 });
    await live.startLiveEditing(page, 'sheet');
    await cell(page).getByRole('button').click();
    await expect(bold(page)).toHaveAttribute('aria-pressed', 'true');
    await bold(page).click();
    await expect(cell(remote)).not.toHaveCSS('font-weight', '700');
    await edit.click();
    await expect(timeline.getByTestId('version-dot-3')).toBeVisible({ timeout: 30_000 });

    await timeline.getByTestId('version-dot-2').click();
    const restore = timeline.getByTestId('restore-version-btn');
    await expect(restore).toBeEnabled();
    await restore.click();
    await restore.click();
    await expect(timeline.getByTestId('version-dot-4')).toBeVisible({ timeout: 30_000 });
    const restored = page.getByTestId('formatted-sheet-cell').and(page.locator('[data-cell="A2"]'));
    await expect(page.getByTestId('sheet-pin-cover')).toHaveCount(0);
    await expect(restored).toHaveCSS('font-weight', '700');
    await expect(restored).toHaveText('42');
    await expect(cell(remote)).toHaveCSS('font-weight', '700');
    await expect(cell(remote)).toHaveCSS('font-style', 'italic');
    await live.shot(page, 'owner-restored-the-formatted-version');
    await live.shot(remote, 'member-received-the-restored-formatting');
  } finally {
    await live.cleanupTeam(page, setup);
    if (memberVideo) {
      await test.info().attach('member-browser-video', {
        path: await memberVideo.path(), contentType: 'video/webm',
      });
    }
  }
});
