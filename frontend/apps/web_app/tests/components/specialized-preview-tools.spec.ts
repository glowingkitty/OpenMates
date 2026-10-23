import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

for (const { width, isMobile } of [{ width: 390, isMobile: false }, { width: 1280, isMobile: false }, { width: 390, isMobile: true }]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,chats.layout.responsive-history
  test(`content default and generic execution classification at ${width}, mobile=${isMobile}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const props = encodeURIComponent(JSON.stringify({ isMobile }));
    await page.goto(`/dev/preview/embeds/UnifiedEmbedPreview?chrome=0&context=chat&width=${width}&props=${props}`);
    await waitForComponentPreview(page);
    const content = page.getByTestId('embed-preview');
    await expect(content).toHaveAttribute('data-skill-id', 'future_output_type');
    await expect(content).toHaveAttribute('role', 'group');
    await expect(content.locator('.result-corner')).toBeVisible();
    await expect(content.getByTestId('embed-result-identity')).toContainText('Automatic result.txt');
    await expect(content.getByTestId('embed-basic-infos-bar')).toHaveCount(0);
    await expect(content.getByTestId('automatic-result-body')).toBeVisible();
    await expect(content.getByTestId('result-preview-more')).toBeVisible();
    await expect(content.getByTestId('result-preview-expand')).toBeVisible();
    expect((await content.boundingBox())!.height).toBeLessThanOrEqual(isMobile ? 290 : width > 401 ? 400 : 200);
    await expect(content).not.toContainText('Ready');
    if (width < 401) await expect(content).toHaveCSS('width', isMobile ? '150px' : '300px');
    await testInfo.attach(`automatic-content-${width}-mobile-${isMobile}`, { body: await content.screenshot(), contentType: 'image/png' });

    // The fallback component establishes execution context itself, even though
    // this future skill has no registry entry or component-preview metadata.
    const genericProps = encodeURIComponent(JSON.stringify({ id: 'legacy-generic-execution-preview',
      appId: 'code', skillId: 'future_unregistered_skill', status: 'finished', provider: 'Fixture', resultCount: 3, isMobile }));
    await page.goto(`/dev/preview/embeds/app_skill/GenericAppSkillEmbedPreview?chrome=0&context=chat&width=${width}&props=${genericProps}`);
    await waitForComponentPreview(page);
    const execution = page.getByTestId('embed-preview');
    await expect(execution).toHaveAttribute('data-skill-id', 'future_unregistered_skill');
    await expect(execution.getByTestId('embed-basic-infos-bar')).toBeVisible();
    await expect(execution.getByTestId('embed-result-identity')).toHaveCount(0);
    await expect(execution.locator('.result-corner')).toHaveCount(0);
    await expect(execution).toContainText('Future Unregistered Skill');
    await expect(execution.getByRole('button', { name: /^(Previous|Next)$/ })).toHaveCount(0);

    const registryRoute = '/dev/preview/apps/AppsEmbedPreview';
    const parentProps = encodeURIComponent(JSON.stringify({ embedId: 'registry-parent-preview', appId: 'web', skillId: 'search',
      embedType: 'app_skill_use', status: 'finished', content: { app_id: 'web', skill_id: 'search', query: 'Shared registry search', provider: 'Brave Search', result_count: 2, embed_ids: [] } }));
    await page.goto(`${registryRoute}?chrome=0&context=chat&width=${width}&props=${parentProps}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('embed-preview').getByTestId('embed-basic-infos-bar')).toBeVisible();
    await expect(page.getByTestId('embed-preview').locator('.result-corner')).toHaveCount(0);

    // Older saved code can have app metadata without a concrete type. The
    // registry's wildcard content adapter must still receive result chrome.
    const legacyProps = encodeURIComponent(JSON.stringify({ embedId: 'registry-code-preview', appId: 'code', skillId: 'snippet',
      embedType: '', status: 'finished', content: { app_id: 'code', skill_id: 'snippet', filename: 'legacy.py', language: 'python', code: 'print(42)', line_count: 1 } }));
    await page.goto(`${registryRoute}?chrome=0&context=chat&width=${width}&props=${legacyProps}`);
    await waitForComponentPreview(page);
    const legacy = page.getByTestId('embed-preview');
    await expect(legacy.getByTestId('embed-result-identity')).toContainText('legacy.py');
    await expect(legacy.locator('.result-corner')).toBeVisible();
    await expect(legacy.getByTestId('embed-basic-infos-bar')).toHaveCount(0);
    await expect(legacy.locator('.code-preview-container')).toContainText('print(42)');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  test(`specialized previews retain their editor layout with explicit tools at ${width}, mobile=${isMobile}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
        writeText: async (value: string) => { (window as unknown as Record<string, unknown>).__previewCopied = value; },
        write: async (items: ClipboardItem[]) => {
          const value = await (await items[0].getType('text/plain')).text();
          (window as unknown as Record<string, unknown>).__previewCopied = value;
        },
      } });
      document.addEventListener('embed-context-menu', () => { (window as unknown as Record<string, unknown>).__previewMore = true; });
    });
    for (const entry of [
      { path: 'code/CodeEmbedPreview', content: '.code-preview-container', selected: 'code', copied: "import { onMount }" },
      { path: 'docs/DocsEmbedPreview', content: '.doc-page-content', selected: 'h1', copied: '' },
      { path: 'sheets/SheetEmbedPreview', content: '.preview-table', selected: 'th', copied: 'Name\tRole\tDepartment\tStart Date' },
    ]) {
      let expanded = 0;
      const listener = (message: { text(): string }) => { if (message.text() === '[Preview] specialized expanded') expanded++; };
      page.on('console', listener);
      const props = encodeURIComponent(JSON.stringify({ isMobile }));
      await page.goto(`/dev/preview/embeds/${entry.path}?chrome=0&context=chat&variant=tools&width=${width}&props=${props}`);
      await waitForComponentPreview(page);
      const card = page.getByTestId('embed-preview');
      await expect(card).toHaveAttribute('role', 'group');
      await expect(card.getByTestId('embed-basic-infos-bar')).toHaveCount(0);
      await expect(card.getByTestId('embed-result-identity')).toBeVisible();
      await expect(card.locator('.result-corner')).toBeVisible();
      await expect(card.locator('.result-corner span')).not.toHaveCSS('mask-image', 'none');
      await expect(card.locator('.details-section')).toBeVisible();
      if (width < 401 || isMobile) await expect(card).toHaveCSS('width', isMobile ? '150px' : '300px');
      else expect((await card.boundingBox())!.width).toBeGreaterThan(300);
      expect((await card.boundingBox())!.height).toBeLessThanOrEqual(isMobile ? 290 : width > 401 ? 400 : 200);
      await expect(card).toHaveCSS('border-radius', '30px');
      const layout = await card.evaluate(element => {
        const rect = (selector: string) => {
          const box = element.querySelector(selector)!.getBoundingClientRect();
          return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height };
        };
        return { card: element.getBoundingClientRect().toJSON(), tools: rect('[data-testid="preview-tools"]'), title: rect('.result-identity-title'), status: rect('.result-identity-status'), text: rect('.result-identity-text'), body: rect('.details-section'), identity: rect('[data-testid="embed-result-identity"]') };
      });
      expect(layout.title.width).toBeGreaterThan(0);
      expect(layout.title.height).toBeGreaterThan(0);
      expect(layout.status.width).toBeGreaterThan(0);
      expect(layout.status.height).toBeGreaterThan(0);
      expect(layout.identity.x).toBeGreaterThanOrEqual(layout.card.x);
      expect(layout.identity.right).toBeLessThanOrEqual(layout.card.right + 1);
      expect(layout.identity.bottom).toBeLessThanOrEqual(layout.body.y + 1);
      expect(layout.body.height).toBeGreaterThan(0);
      expect(layout.body.bottom).toBeLessThanOrEqual(layout.card.bottom + 1);
      expect(layout.tools.x).toBeGreaterThanOrEqual(layout.card.x - 1);
      expect(layout.tools.right).toBeLessThanOrEqual(layout.card.right + 1);
      expect(layout.tools.bottom).toBeLessThanOrEqual(layout.body.y + 1);
      if (isMobile) {
        expect(layout.text.bottom).toBeLessThanOrEqual(layout.tools.y + 1);
      } else expect(layout.title.right).toBeLessThanOrEqual(layout.tools.x + 1);
      await expect(card.getByTestId('result-card-content')).toHaveCount(0);
      const content = card.locator(entry.content);
      await expect(content).toBeVisible();
      const text = content.locator(entry.selected).first();
      await expect(text).toHaveCSS('user-select', 'text');
      await expect(text).toHaveCSS('pointer-events', 'auto');
      await text.click({ position: { x: 2, y: 2 } });
      expect(expanded).toBe(0);
      const selection = await text.evaluate(element => {
        const range = document.createRange(); range.selectNodeContents(element);
        const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
        return selection.toString();
      });
      expect(selection.length).toBeGreaterThan(0);
      if (entry.copied) {
        await card.getByTestId('preview-copy').click();
        await expect.poll(() => page.evaluate(() => (window as unknown as Record<string, unknown>).__previewCopied)).toContain(entry.copied);
        expect(expanded).toBe(0);
      }
      await card.getByTestId('result-preview-more').click();
      await expect.poll(() => page.evaluate(() => (window as unknown as Record<string, unknown>).__previewMore)).toBe(true);
      await card.getByTestId('result-preview-expand').focus();
      await page.keyboard.press('Enter');
      await expect.poll(() => expanded).toBe(1);
      await testInfo.attach(`${entry.path.split('/')[0]}-tools-${width}-mobile-${isMobile}`, { body: await page.screenshot(), contentType: 'image/png' });
      page.off('console', listener);
    }
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  test(`short code and tables use natural height within their size cap at ${width}, mobile=${isMobile}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    for (const entry of [
      { path: 'code/CodeEmbedPreview', body: '.code-preview-container', content: 'print("Hello")', rows: undefined },
      { path: 'sheets/SheetEmbedPreview', body: '.preview-table', content: 'Second', rows: 2 },
    ]) {
      const props = encodeURIComponent(JSON.stringify({ isMobile }));
      await page.goto(`/dev/preview/embeds/${entry.path}?chrome=0&context=chat&variant=shortContent&width=${width}&props=${props}`);
      await waitForComponentPreview(page);
      const card = page.getByTestId('embed-preview');
      const body = card.locator(entry.body);
      await expect(body).toBeVisible();
      await expect(body).toContainText(entry.content);
      if (entry.rows) await expect(body.locator('tbody tr')).toHaveCount(entry.rows);
      const geometry = await card.evaluate((element, selector) => {
        const card = element.getBoundingClientRect();
        const body = element.querySelector(selector)!.getBoundingClientRect();
        const identity = element.querySelector('[data-testid="embed-result-identity"]')!.getBoundingClientRect();
        return { height: card.height, minHeight: getComputedStyle(element).minHeight,
          bodyHeight: body.height, bodyTop: body.top, bodyBottom: body.bottom,
          identityBottom: identity.bottom, bottom: card.bottom };
      }, entry.body);
      const cap = isMobile ? 290 : width > 401 ? 400 : 200;
      expect(geometry.height).toBeLessThan(cap - 8);
      expect(geometry.minHeight).toBe('0px');
      expect(geometry.bodyHeight).toBeGreaterThan(0);
      expect(geometry.bodyTop).toBeGreaterThanOrEqual(geometry.identityBottom - 1);
      expect(geometry.bodyBottom).toBeLessThanOrEqual(geometry.bottom + 1);
      expect(geometry.bottom - geometry.bodyBottom).toBeLessThanOrEqual(16);
      await expect(card.locator('.result-corner')).toBeVisible();
      await expect(card.getByTestId('result-preview-more')).toBeVisible();
      await expect(card.getByTestId('result-preview-expand')).toBeVisible();
      await testInfo.attach(`${entry.path.split('/')[0]}-short-${width}-mobile-${isMobile}`, { body: await card.screenshot(), contentType: 'image/png' });
    }
  });
}

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  test(`real short code groups shrink active carousel flow and keep corner navigation clear at ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1100 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(`/dev/preview/embeds/GroupedResultPreviewHarness?chrome=0&context=chat&variant=shortCode&width=${width}`);
    await waitForComponentPreview(page);
    const fixture = page.getByTestId('grouped-result-fixture');
    await expect(fixture).toHaveAttribute('data-ready', 'true');

    const compact = fixture.getByTestId('compact-group');
    const compactItems = compact.locator('.embed-group-item');
    const compactFirst = compactItems.first().getByTestId('embed-preview');
    await expect(compactFirst).toContainText('one.py');
    expect((await compactFirst.boundingBox())!.height).toBeLessThan(192);
    const compactBody = (await compactFirst.locator('.code-preview-container').boundingBox())!;
    const compactBox = (await compactFirst.boundingBox())!;
    expect(compactBody.x - compactBox.x).toBeGreaterThanOrEqual(48);
    expect(compactBox.x + compactBox.width - compactBody.x - compactBody.width).toBeGreaterThanOrEqual(48);
    await compactItems.first().getByTestId('grouped-preview-next').click();
    const scroller = compact.locator('.group-scroll-container');
    await expect.poll(() => scroller.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
    await compactItems.nth(1).getByTestId('grouped-preview-previous').click();
    await expect.poll(() => scroller.evaluate(element => element.scrollLeft)).toBeLessThan(2);

    const large = fixture.getByTestId('large-group');
    await large.scrollIntoViewIfNeeded();
    const shell = large.getByTestId('embed-preview-large');
    const firstCard = shell.getByTestId('embed-preview');
    const previous = large.getByRole('button', { name: 'Previous', exact: true });
    const next = large.getByRole('button', { name: 'Next', exact: true });
    const assertActiveFlow = async (card: import('@playwright/test').Locator) => {
      await expect.poll(async () => {
        const outer = (await shell.boundingBox())!;
        const active = (await card.boundingBox())!;
        return Math.abs(outer.y + outer.height - active.y - active.height);
      }).toBeLessThan(1);
      const bounds = (await card.boundingBox())!;
      expect((await shell.boundingBox())!.height).toBeLessThan((width > 401 ? 400 : 200) - 8);
      const body = (await card.locator('.code-preview-container').boundingBox())!;
      expect(body.x - bounds.x).toBeGreaterThanOrEqual(48);
      expect(bounds.x + bounds.width - body.x - body.width).toBeGreaterThanOrEqual(48);
      for (const [control, label] of [[previous, 'Previous'], [next, 'Next']] as const) {
        const button = (await control.boundingBox())!;
        expect(bounds.y + bounds.height - button.y - button.height).toBeCloseTo(10, 0);
        await expect.poll(() => page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest('button')?.getAttribute('aria-label'),
          { x: button.x + button.width / 2, y: button.y + button.height / 2 })).toBe(label);
      }
      return bounds.height;
    };
    await expect(firstCard).toContainText('one.py');
    const firstHeight = await assertActiveFlow(firstCard);
    await next.click();
    const active = large.locator('.embed-preview-large-overlay:not(.embed-preview-large-overlay--hidden)').getByTestId('embed-preview');
    await expect(active).toContainText('two.py');
    const secondHeight = await assertActiveFlow(active);
    expect(secondHeight).toBeGreaterThan(firstHeight);
    await large.getByRole('tab', { name: 'Go to slide 3 of 3' }).click();
    await expect(active).toContainText('three.py');
    await assertActiveFlow(active);
    await large.getByRole('tab', { name: 'Go to slide 1 of 3' }).click();
    await assertActiveFlow(firstCard);
    await expect(page.getByTestId('embed-fullscreen-overlay')).toHaveCount(0);
    await testInfo.attach(`short-code-carousel-${width}`, { body: await large.screenshot(), contentType: 'image/png' });
  });
}
