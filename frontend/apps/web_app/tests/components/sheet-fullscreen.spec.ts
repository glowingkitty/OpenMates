import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/sheets/SheetEmbedFullscreen';

for (const width of [390, 1000]) {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  test(`sheet citation headings stay readable in preview and fullscreen at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    const query = `?theme=light&background=%23dbeafe&width=${width}&chrome=0&variant=citationHeaders`;
    await page.goto(`/dev/preview/embeds/sheets/SheetEmbedPreview${query}`);
    await waitForComponentPreview(page);
    const preview = page.locator('table.preview-table');
    await expect(preview.locator('thead th').first()).toHaveText('Employer');
    await expect(preview).not.toContainText('embed:');
    await expect(preview.locator('tbody tr').first()).toContainText('voize');
    await expect(preview.locator('thead th').first()).toBeVisible();
    await testInfo.attach(`sheet-citation-preview-${width}`, {
      body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png'
    });

    await page.goto(`${PREVIEW}${query}`);
    await waitForComponentPreview(page);
    const table = page.locator('table.spreadsheet');
    await expect(table.locator('.col-header-text')).toHaveText(['Employer', 'Location']);
    await expect(table).not.toContainText('embed:');
    await expect(table.locator('tbody tr')).toHaveCount(2);
    await page.getByRole('button', { name: 'Toggle column filters', exact: true }).click();
    const employerFilter = page.getByPlaceholder('Employer', { exact: true });
    await expect(employerFilter).toBeVisible();
    await expect(page.getByPlaceholder('Location', { exact: true })).toBeVisible();
    await employerFilter.fill('voize');
    await expect(table.locator('tbody tr')).toHaveCount(1);
    await expect(table.locator('tbody tr').first()).toContainText('voize');
    await testInfo.attach(`sheet-citation-fullscreen-${width}`, {
      body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png'
    });
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  test(`sheet gutter filter stays compact and sorting/filtering work at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${PREVIEW}?theme=light&background=%23dbeafe&width=${width}&chrome=0`);
    await waitForComponentPreview(page);
    const table = page.locator('table.spreadsheet');
    const toggle = page.getByRole('button', { name: 'Toggle column filters', exact: true });
    const rows = table.locator('tbody tr');
    await expect(rows).toHaveCount(8);
    await expect(toggle.locator('svg')).toBeVisible();

    const assertCompactGutter = async () => {
      await expect.poll(async () => toggle.evaluate((button) => {
        const rect = button.getBoundingClientRect();
        const gutter = button.closest('th')!.getBoundingClientRect();
        const style = getComputedStyle(button);
        return {
          width: Math.round(rect.width * 100) / 100,
          height: Math.round(rect.height * 100) / 100,
          contained: rect.left >= gutter.left && rect.right <= gutter.right &&
            rect.top >= gutter.top && rect.bottom <= gutter.bottom,
          padding: style.padding,
          filter: style.filter,
        };
      })).toEqual({ width: 22, height: 22, contained: true, padding: '0px', filter: 'none' });
    };

    await assertCompactGutter();
    await toggle.hover();
    await assertCompactGutter();
    await toggle.focus();
    await page.keyboard.press('Tab');
    await page.keyboard.press('Shift+Tab');
    await expect(toggle).toBeFocused();
    await expect.poll(() => toggle.evaluate((button) => getComputedStyle(button).outlineStyle)).not.toBe('none');
    await toggle.press('Space');
    await expect(page.getByPlaceholder('Name', { exact: true })).toBeVisible();
    await assertCompactGutter();

    await page.getByPlaceholder('Name', { exact: true }).fill('carol');
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText('Carol Williams');
    await page.getByRole('button', { name: 'Clear all filters', exact: true }).click();
    await expect(rows).toHaveCount(8);
    await expect(page.getByPlaceholder('Name', { exact: true })).toHaveValue('');

    const nameHeader = table.locator('th.col-header').filter({ hasText: 'Name' });
    await nameHeader.click();
    await expect(rows.first()).toContainText('Alice Johnson');
    await nameHeader.click();
    await expect(rows.first()).toContainText('Henry Davis');
    await nameHeader.click();
    await expect(rows.first()).toContainText('Alice Johnson');
    await expect(nameHeader.locator('.sort-icon-active')).toHaveCount(0);

    await page.getByPlaceholder('Name', { exact: true }).fill('missing person');
    await expect(table.getByText('No rows match the current filters', { exact: true })).toBeVisible();
    await toggle.hover();
    await page.mouse.down();
    try {
      await assertCompactGutter();
    } finally {
      await page.mouse.up();
    }
    await expect(page.getByPlaceholder('Name', { exact: true })).toHaveCount(0);
    await expect(rows).toHaveCount(8);
    await assertCompactGutter();
  });
}

// Edit toggle + formula visibility + sticky header geometry (demo sheet: inputs then formulas).
for (const width of [390, 1000]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  test(`sheet edit toggle sits before Share, header stays on top, formulas are visible at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 560 });
    await page.goto(`${PREVIEW}?theme=light&background=%23dbeafe&width=${width}&chrome=0&variant=editableFormulas`);
    await waitForComponentPreview(page);
    // The overlay slides in; measure the header row only once it has settled.
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
    const topBar = page.locator('.embed-top-bar');
    const toggle = topBar.getByTestId('sheet-edit-toggle');
    const wrapper = page.locator('.spreadsheet-wrapper');
    // The shared content area (banner + sheet) is the ONE scroll surface.
    const scroller = page.locator('.content-area');
    const banner = page.locator('.content-area > .embed-header');
    const table = page.locator('table.spreadsheet');

    // Round pen button in the header action row; Report Issue lives in More.
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await expect(toggle.getByTestId('embed-edit-icon')).toBeVisible();
    const pill = toggle.locator('xpath=..');
    const pillBox = (await pill.boundingBox())!;
    expect(Math.abs(pillBox.width - pillBox.height)).toBeLessThanOrEqual(1);
    await expect(topBar.getByTestId('embed-report-issue-button')).toHaveCount(0);
    const more = topBar.locator('.more-trigger');
    const next = width >= 460 ? topBar.getByTestId('embed-share-button') : more;
    const nextBox = (await next.boundingBox())!;
    const toggleBox = (await toggle.boundingBox())!;
    expect(toggleBox.x).toBeLessThan(nextBox.x);
    expect(Math.abs(toggleBox.y + toggleBox.height / 2 - (nextBox.y + nextBox.height / 2))).toBeLessThanOrEqual(1);
    expect(Math.abs(pillBox.height - (await more.locator('xpath=..').boundingBox())!.height)).toBeLessThanOrEqual(1);
    await more.click();
    await expect(topBar.getByTestId('embed-report-issue-button')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(topBar.getByTestId('embed-report-issue-button')).toHaveCount(0);

    // View mode: calculated cells are marked and expose their formula.
    const b4 = table.locator('[data-testid="sheet-cell"][data-cell="B4"]');
    await expect(b4).toHaveText('29');
    await expect(b4).toHaveAttribute('data-formula', '=SUM(B1:B3)');
    await expect(b4).toHaveAttribute('title', '=SUM(B1:B3)');
    const tokenColor = await page.evaluate(() => {
      const probe = document.createElement('span');
      probe.style.color = 'var(--color-sheet-formula)';
      document.body.appendChild(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    });
    expect(tokenColor).not.toBe('rgba(0, 0, 0, 0)');
    await expect(b4).toHaveCSS('color', tokenColor);
    const b1 = table.locator('[data-cell="B1"]');
    await expect(b1).not.toHaveAttribute('data-formula', /./);
    expect(await b1.evaluate((el) => getComputedStyle(el).color)).not.toBe(tokenColor);
    expect(await table.locator('[data-cell="A4"]').evaluate((el) => getComputedStyle(el).color)).not.toBe(tokenColor);

    // Header rows stay pinned to the grid's top edge, before and after scrolling.
    const scrollTo = (top: 'start' | 'end') => scroller.evaluate((el, where) => {
      el.scrollTop = where === 'end' ? el.scrollHeight : 0;
    }, top);
    const assertHeaderOnTop = async (label: string) => {
      const geo = await wrapper.evaluate((el) => {
        const area = document.querySelector('.content-area')!.getBoundingClientRect();
        // Pinned header sticks below the floating top bar (--sheet-pin-top).
        const pin = parseFloat(getComputedStyle(document.querySelector('.sheet-fullscreen')!).getPropertyValue('--sheet-pin-top'));
        const top = Math.max(el.getBoundingClientRect().top, area.top + pin);
        const letter = el.querySelector('.col-letter-row th')!.getBoundingClientRect();
        const header = el.querySelector('thead tr:nth-child(2) th.col-header')!.getBoundingClientRect();
        const probeX = header.left + header.width / 2;
        const at = (y: number) => document.elementFromPoint(probeX, y);
        const headerOnTop = !!at(top + 2)?.closest('thead') && !!at(header.top + 2)?.closest('thead');
        // Nothing but the cover/surface may show in the band above the pinned header.
        const noRowsAbove = [area.top + 2, top - 3].every((y) => !at(y)?.closest('tbody'));
        return { delta: Math.round(letter.top - top), stacked: Math.round(header.top - letter.bottom), headerOnTop, noRowsAbove };
      });
      expect(Math.abs(geo.delta), `${label}: letter row at grid top`).toBeLessThanOrEqual(1);
      expect(Math.abs(geo.stacked), `${label}: name row directly below letter row`).toBeLessThanOrEqual(1);
      expect(geo.headerOnTop, `${label}: header cells cover the grid top, no data rows above them`).toBe(true);
      expect(geo.noRowsAbove, `${label}: scrolled rows never show above the pinned header`).toBe(true);
    };
    // The table keeps its natural height: the wrapper is not an inner scroll
    // area and the whole grid lives in the single content-area scroll surface.
    const assertFullHeightSingleScroll = async (label: string) => {
      const m = await page.evaluate(() => {
        const wrap = document.querySelector('.spreadsheet-wrapper') as HTMLElement;
        const tbl = document.querySelector('table.spreadsheet') as HTMLElement;
        const area = document.querySelector('.content-area') as HTMLElement;
        const cs = getComputedStyle(wrap);
        return {
          overflowY: cs.overflowY,
          wrapperScrolls: wrap.scrollHeight > wrap.clientHeight + 1,
          wrapperHeight: Math.round(wrap.getBoundingClientRect().height),
          tableHeight: Math.round(tbl.getBoundingClientRect().height),
          areaScrolls: area.scrollHeight > area.clientHeight + 1,
          areaHeight: area.clientHeight,
          bannerHeight: Math.round(document.querySelector('.content-area > .embed-header')!.getBoundingClientRect().height),
        };
      });
      expect(m.overflowY, `${label}: wrapper is not an inner scroller`).toBe('visible');
      expect(m.wrapperScrolls, `${label}: wrapper has no inner scroll`).toBe(false);
      expect(Math.abs(m.wrapperHeight - m.tableHeight), `${label}: wrapper height equals table height`).toBeLessThanOrEqual(1);
      // Banner + table must overflow the surface together; an inner grid
      // viewport (the old bug) would cap the table well below its natural height.
      expect(m.tableHeight + m.bannerHeight, `${label}: banner and table scroll as one surface`).toBeGreaterThan(m.areaHeight);
      expect(m.areaScrolls, `${label}: content area scrolls the table`).toBe(true);
    };
    const assertBannerScrolledAway = async (label: string) => {
      await scrollTo('start');
      const topVisible = await banner.evaluate((el) => {
        const area = document.querySelector('.content-area')!.getBoundingClientRect();
        const r = el.getBoundingClientRect();
        return r.bottom > area.top + 1 && r.top < area.bottom;
      });
      expect(topVisible, `${label}: banner visible at scroll top`).toBe(true);
      await scrollTo('end');
      const away = await banner.evaluate((el) => {
        const area = document.querySelector('.content-area')!.getBoundingClientRect();
        return el.getBoundingClientRect().bottom <= area.top + 1;
      });
      expect(away, `${label}: banner scrolled out of view`).toBe(true);
      // Close control is a floating overlay, so it stays reachable while scrolled.
      await expect(page.getByTestId('embed-minimize'), `${label}: close stays visible`).toBeVisible();
      const lastRow = table.locator('[data-cell="A16"]');
      await expect(lastRow, `${label}: last row reachable`).toBeInViewport();
    };
    // Short viewport so the banner can scroll fully out of view above the table.
    await page.setViewportSize({ width, height: 400 });
    await assertHeaderOnTop('view, top');
    await assertFullHeightSingleScroll('view');
    await assertBannerScrolledAway('view');
    await assertHeaderOnTop('view, scrolled');
    expect((await scroller.evaluate((el) => el.scrollTop)) > 0, 'content area must scroll in this viewport').toBe(true);
    await testInfo.attach(`sheet-view-scrolled-${width}`, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
    await scrollTo('start');

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await expect(pill).toHaveClass(/edit-active/);
    await assertHeaderOnTop('edit, top');
    await testInfo.attach(`sheet-edit-mode-${width}`, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
    await b4.click();
    const input = page.getByTestId('sheet-cell-input');
    await expect(input).toHaveValue('=SUM(B1:B3)');
    await expect(table.locator('[data-cell="B10"]')).toHaveCSS('color', tokenColor);
    await testInfo.attach(`sheet-edit-formula-${width}`, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
    await input.press('Escape');
    await expect(table.locator('[data-cell="B4"]')).toHaveText('29');
    await assertFullHeightSingleScroll('edit');
    await assertBannerScrolledAway('edit');
    await assertHeaderOnTop('edit, scrolled');
    await testInfo.attach(`sheet-edit-scrolled-${width}`, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  });
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('sheet chat preview marks calculated cells with their formula', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  await page.goto('/dev/preview/embeds/sheets/SheetEmbedPreview?theme=light&background=%23dbeafe&width=1000&chrome=0&variant=formulas');
  await waitForComponentPreview(page);
  const cell = page.locator('table.preview-table td[data-formula="=SUM(B1:B2)"]');
  await expect(cell).toHaveText('132');
  await expect(cell).toHaveAttribute('title', '=SUM(B1:B2)');
  await expect(cell).toHaveClass(/sheet-cell-formula/);
  const plain = page.locator('table.preview-table td').filter({ hasText: /^12$/ });
  expect(await cell.evaluate((el) => getComputedStyle(el).color))
    .not.toBe(await plain.evaluate((el) => getComputedStyle(el).color));
  await expect(page.locator('table.preview-table td').filter({ hasText: /^12$/ })).not.toHaveAttribute('data-formula', /./);
});
