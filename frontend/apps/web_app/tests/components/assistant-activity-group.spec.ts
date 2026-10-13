// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
const preview = (variant = '', theme = 'light', width = 820, language = 'en') => `/dev/preview/AssistantActivityGroup?${new URLSearchParams({ variant, theme, width: String(width), language, background: '#dbeafe', chrome: '0' })}`;

async function summaryLineCount(page: import('@playwright/test').Page): Promise<number> {
  await page.evaluate(async () => { await document.fonts.ready; });
  return page.getByTestId('assistant-activity-summary-text').evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    return range.getClientRects().length;
  });
}

test.describe('Completed assistant activity disclosure', () => {
  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,chat-processing-feedback.accessible-responsive
  test('uses completed app grammar and down/up disclosure arrows', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview());
    await waitForComponentPreview(page);
    const toggle = page.getByTestId('assistant-activity-toggle');
    await expect(toggle).toHaveText('Used the Code app');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(await toggle.locator('.activity-arrow').evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).b)).toBeGreaterThan(0);
    await toggle.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('assistant-activity-body')).toBeVisible();
    expect(await toggle.locator('.activity-arrow').evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).b)).toBeLessThan(0);
    await page.keyboard.press('Space');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await page.goto(preview('multiple'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('assistant-activity-toggle')).toHaveText('Used the Web, News & Images apps');
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,chat-processing-feedback.accessible-responsive
  test('uses canonical Code, Events, and thinking circle gradients in both themes', async ({ page }) => {
    for (const theme of ['light', 'dark']) {
      await page.goto(preview('gradients', theme));
      await waitForComponentPreview(page);
      const icons = page.getByTestId('assistant-skill-app-icon').locator('.icon');
      for (const [index, appId] of ['code', 'events', 'ai'].entries()) {
        const surface = await icons.nth(index).evaluate((el, id) => {
          const probe = document.createElement('span');
          probe.style.background = `var(--color-app-${id})`;
          document.body.append(probe);
          const expected = getComputedStyle(probe).backgroundImage;
          probe.remove();
          return { actual: getComputedStyle(el).backgroundImage, expected, glyph: getComputedStyle(el, '::before').backgroundImage };
        }, appId);
        expect(surface.expected).toContain('linear-gradient');
        expect(surface.actual).toBe(surface.expected);
        expect(surface.glyph).not.toBe('none');
      }
    }
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,chat-processing-feedback.accessible-responsive
  test('names the first three of six apps and caps overlapping circles at three', async ({ page }) => {
    await page.goto(preview('manyApps'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('assistant-activity-summary-text')).toHaveText('Used the Web, News, Images + 3 more apps.');
    const circles = page.getByTestId('assistant-activity-icons').locator(':scope > [data-app-id]');
    await expect(circles).toHaveCount(3);
    const layout = await circles.evaluateAll((elements) => elements.map((element) => {
      const box = element.getBoundingClientRect();
      return { x: box.x, y: box.y, width: box.width, z: Number(getComputedStyle(element).zIndex) };
    }));
    for (let index = 1; index < layout.length; index += 1) {
      const previous = layout[index - 1];
      const current = layout[index];
      expect(current.x).toBeGreaterThan(previous.x);
      expect(previous.x + previous.width - current.x).toBeGreaterThanOrEqual(6);
      expect(previous.x + previous.width - current.x).toBeLessThanOrEqual(10);
      expect(Math.abs(current.y - previous.y)).toBeLessThan(2);
      expect(previous.z).toBeGreaterThan(current.z);
    }
    expect(await summaryLineCount(page)).toBe(1);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary
  test('uses singular grammar when one app remains after the first three', async ({ page }) => {
    await page.goto(preview('fourApps'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('assistant-activity-summary-text')).toHaveText('Used the Web, News, Images + 1 more app.');
    await expect(page.getByTestId('assistant-activity-icons').locator(':scope > [data-app-id]')).toHaveCount(3);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,chat-processing-feedback.accessible-responsive
  test('uses one front AI circle within the three-circle limit when thinking', async ({ page }) => {
    await page.goto(preview('manyAppsThinking'));
    await waitForComponentPreview(page);
    const icons = page.getByTestId('assistant-activity-icons');
    await expect(icons.locator(':scope > [data-app-id]')).toHaveCount(3);
    await expect(icons.getByTestId('assistant-thinking-app-icon')).toHaveCount(1);
    await expect(icons.getByTestId('assistant-skill-app-icon')).toHaveCount(2);
    await expect(icons.locator(':scope > [data-app-id]').first()).toHaveAttribute('data-app-id', 'ai');
    const frontZ = await icons.getByTestId('assistant-thinking-app-icon').evaluate((element) => Number(getComputedStyle(element).zIndex));
    const nextZ = await icons.getByTestId('assistant-skill-app-icon').first().evaluate((element) => Number(getComputedStyle(element).zIndex));
    expect(frontZ).toBeGreaterThan(nextZ);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.transparency.loaded-set,chat-processing-feedback.completed-processing-summary
  test('counts app use with a loaded Memory and puts its pill above activity content', async ({ page }) => {
    await page.goto(preview('loadedMemorySkills'));
    await waitForComponentPreview(page);
    const summary = page.getByTestId('assistant-activity-summary-text');
    await expect(summary).toContainText(/Loaded.*Flowchart.*memory.*used 1 app/i);
    await expect(summary).not.toContainText('Diagrams');
    await page.getByTestId('assistant-activity-toggle').click();
    const body = page.getByTestId('assistant-activity-body');
    const pill = body.getByTestId('loaded-memory-pill');
    await expect(pill).toBeVisible();
    await expect(pill).toContainText('Flowchart');
    await expect(body.getByTestId('embed-preview')).toBeVisible();
    const pillBox = await pill.boundingBox();
    const activityBox = await body.getByTestId('embed-preview').boundingBox();
    expect(pillBox!.y + pillBox!.height).toBeLessThanOrEqual(activityBox!.y);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.accessible-responsive,app-memories.transparency.loaded-set
  test('keeps long mixed summaries within one desktop line and two mobile lines in English and German', async ({ page }) => {
    for (const language of ['en', 'de']) {
      await page.goto(preview('longMixed', 'light', 820, language));
      await waitForComponentPreview(page);
      const summary = page.getByTestId('assistant-activity-summary-text');
      await expect(summary).toContainText('6');
      if (language === 'de') {
        await expect(page.locator('html')).toHaveAttribute('lang', 'de');
        await expect(summary).not.toContainText(/Loaded|Used/);
      }
      expect(await summaryLineCount(page)).toBeLessThanOrEqual(1);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(preview('longMixed', 'light', 390, language));
      await waitForComponentPreview(page);
      await expect(page.getByTestId('assistant-activity-summary-text')).toContainText('6');
      expect(await summaryLineCount(page)).toBeLessThanOrEqual(2);
      await page.setViewportSize({ width: 820, height: 844 });
    }
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,chat-processing-feedback.turn-lifecycle
  test('keeps focus countdown and activation acknowledgement visible, then collapses completed sub chats', async ({ page }) => {
    await page.clock.install({ time: new Date('2026-10-11T19:00:00Z') });
    await page.goto(preview('liveFocusAndSubChats'));
    await waitForComponentPreview(page);
    const toggle = page.getByTestId('assistant-activity-toggle');
    const body = page.getByTestId('assistant-activity-body');
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    // Complete real fixture storage/rendering before freezing lifecycle time.
    await page.evaluate(async () => {
      const detail: { completion?: Promise<void> } = {};
      document.dispatchEvent(new CustomEvent('preview:seed-sub-chats', { detail }));
      if (!detail.completion) throw new Error('Sub-chat fixture listener did not mount');
      await detail.completion;
    });
    await expect(body.getByTestId('sub-chat-card')).toHaveCount(2);
    await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1000));
    await page.evaluate(() => document.dispatchEvent(new Event('preview:start-focus-countdown')));
    await page.clock.runFor(100);
    await expect(body.getByTestId('focus-progress-bar')).toBeVisible();
    await expect(body.getByTestId('focus-status-value')).toContainText('4');
    // Real catalog activation leaves its countdown entry in the pending store.
    await page.evaluate(() => document.dispatchEvent(new Event('preview:activate-focus')));
    await expect(body.getByTestId('focus-status-value')).toContainText('activated');
    await page.clock.runFor(999);
    await expect(body.getByTestId('focus-mode-bar')).toBeVisible();
    await page.clock.runFor(1);
    await expect(body.getByTestId('focus-mode-bar')).toHaveCount(0);
    // A stale countdown must not reopen an already acknowledged activation.
    await page.evaluate(() => document.dispatchEvent(new Event('preview:deactivate-focus')));
    await expect(body.getByTestId('focus-mode-bar')).toHaveCount(0);
    await page.clock.resume();
    await expect(body.getByTestId('sub-chat-card')).toHaveCount(2);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('subChatProgress', { detail: {
      type: 'sub_chat_progress', chat_id: 'another-chat', task_id: 'preview-live-task', status: 'completed',
    } })));
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('subChatProgress', { detail: {
      type: 'sub_chat_progress', chat_id: 'preview-live-activity-parent', task_id: 'preview-live-task', status: 'completed',
    } })));
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(toggle).toHaveText("Activated 'Deep research' & worked in sub chats.");
    await expect(body).toHaveCount(0);
    await toggle.click();
    await expect(body.getByTestId('focus-mode-bar')).toBeVisible();
    await expect(body.getByTestId('sub-chat-status-completed')).toHaveCount(2);
  });

  // contract-test: direct surface=gui.web assertions=focus-modes.countdown,chat-processing-feedback.turn-lifecycle
  test('keeps a delayed Project card mounted through its client acceptance and full acknowledgement', async ({ page }) => {
    await page.goto(preview('liveProjectFocus'));
    await waitForComponentPreview(page);
    const toggle = page.getByTestId('assistant-activity-toggle');
    const bar = page.getByTestId('assistant-activity-body').getByTestId('focus-mode-bar');
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    // Initial fixture is approval-only. Freeze after the real card mounts, then
    // start a fresh delayed request so its timer owns the activation transition.
    await page.clock.install({ time: new Date(await page.evaluate(() => Date.now())) });
    await page.clock.pauseAt(await page.evaluate(() => Date.now()));
    await page.evaluate(() => document.dispatchEvent(new Event('preview:start-project-countdown')));
    await page.clock.runFor(100);
    await expect(bar.getByTestId('focus-progress-bar')).toBeVisible();
    expect(await page.evaluate(() => document.body.dataset.projectAcceptCount ?? '0')).toBe('0');

    await page.clock.runFor(3900);
    await expect.poll(() => page.evaluate(() => document.body.dataset.projectAcceptCount)).toBe('1');
    await expect(bar.getByTestId('focus-status-value')).toContainText('activated');
    await page.clock.runFor(999);
    await expect(bar).toBeVisible();
    await page.clock.runFor(1);
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('assistant-activity-body')).toHaveCount(0);
    expect(await page.evaluate(() => document.body.dataset.projectAcceptCount)).toBe('1');
  });

  // contract-test: direct surface=gui.web assertions=focus-modes.countdown
  test('expires an unapproved Project request without accepting it', async ({ page }) => {
    await page.clock.install();
    await page.goto(preview('liveProjectFocus'));
    await waitForComponentPreview(page);
    const toggle = page.getByTestId('assistant-activity-toggle');
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('assistant-activity-body').getByTestId('focus-mode-bar')).toBeVisible();
    await page.clock.pauseAt(await page.evaluate(() => Date.now()));
    await page.clock.runFor(60_000);
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(toggle).toHaveText('Cancelled focus activation');
    await expect(page.getByTestId('assistant-activity-body')).toHaveCount(0);
    expect(await page.evaluate(() => document.body.dataset.projectAcceptCount ?? '0')).toBe('0');
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,chat-processing-feedback.accessible-responsive
  test('nests the thinking disclosure above skills and shows the latest lines during streaming', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview('streamingThinking'));
    await waitForComponentPreview(page);
    const thinking = page.getByTestId('thinking-content');
    await expect(thinking).toBeVisible();
    await expect(thinking).toContainText('Reasoning line 18.');
    await expect.poll(() => thinking.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(3);
    expect((await thinking.boundingBox())!.height).toBeLessThanOrEqual(201);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview('thinking', 'dark', 390));
    await waitForComponentPreview(page);
    const toggle = page.getByTestId('assistant-activity-toggle');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await toggle.click();
    const body = page.getByTestId('assistant-activity-body');
    const inner = body.getByTestId('thinking-header');
    await expect(inner).toHaveAttribute('aria-expanded', 'false');
    await expect(body.getByTestId('thinking-content')).toHaveCount(0);
    await expect(body.getByTestId('embed-preview')).toHaveCount(3);
    const skillScroll = body.getByTestId('app-skill-embed-group-scroll');
    await expect(skillScroll).toBeVisible();
    expect(await skillScroll.evaluate((el) => el.scrollWidth)).toBeGreaterThan(await skillScroll.evaluate((el) => el.clientWidth));
    await inner.click();
    await expect(inner).toHaveAttribute('aria-expanded', 'true');
    await expect(body.getByTestId('thinking-content')).toContainText('Reasoning line 1.');
    await expect(body.getByTestId('thinking-content')).toContainText('Reasoning line 18.');
    const box = (await toggle.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(390);
    await inner.click();
    await expect(inner).toHaveAttribute('aria-expanded', 'false');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });
});
