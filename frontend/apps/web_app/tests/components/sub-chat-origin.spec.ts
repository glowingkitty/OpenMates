// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

test.use({ viewport: { width: 900, height: 700 } });

// contract-test: supporting surface=gui.web assertions=plans.sub-chats.assumption-and-task-chats
test('A sub-chat starts with an origin event linking to the main chat and its work', async ({ page }, testInfo) => {
  await page.goto('/dev/preview/chats/SubChatOrigin?chrome=0');
  await waitForComponentPreview(page);
  const origin = page.getByTestId('sub-chat-origin');
  await expect(origin).toHaveAttribute('data-kind', 'assumption');
  await expect(origin).toContainText('Created as a sub-chat of Plan the product launch');
  await expect(page.getByTestId('sub-chat-origin-parent-link')).toHaveText('Plan the product launch');
  await expect(page.getByTestId('sub-chat-origin-work')).toHaveText('Checks: The announcement channel is available');
  await expect(page.getByTestId('sub-chat-work-link-back')).toHaveCount(0);
  await testInfo.attach('sub-chat-origin-checks', { body: await origin.screenshot(), contentType: 'image/png' });
  await page.getByTestId('sub-chat-origin-parent-link').click();
  expect(await page.evaluate(() => (window as unknown as { __openedParent?: boolean }).__openedParent)).toBe(true);

  await page.goto('/dev/preview/chats/SubChatOrigin?chrome=0&variant=task');
  await waitForComponentPreview(page);
  await expect(origin).toHaveAttribute('data-kind', 'task');
  await expect(page.getByTestId('sub-chat-origin-work')).toHaveText('Works on: Review the release checklist');
  await testInfo.attach('sub-chat-origin-works-on', { body: await origin.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=plans.sub-chats.assumption-and-task-chats
test('The chat header shows a Sub-chat pill', async ({ page }, testInfo) => {
  await page.goto('/dev/preview/ChatHeader?chrome=0&theme=light&width=600&variant=subChat');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('sub-chat-header-pill')).toHaveText('Sub-chat');
  await testInfo.attach('sub-chat-header-pill', { body: await page.getByTestId('sub-chat-header-pill').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=plans.sub-chats.assumption-and-task-chats
for (const variant of ['', 'inlineCompact']) {
  test(`The message input has no sibling toggle and keeps its hint centred ${variant || 'default'}`, async ({ page }, testInfo) => {
    await page.goto(`/dev/preview/enter_message/MessageInput?chrome=0&theme=light${variant ? `&variant=${variant}` : ''}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('sub-chat-broadcast-toggle')).toHaveCount(0);
    const field = page.getByTestId('message-field');
    const empty = field.getByTestId('message-editor').locator('p[data-placeholder]').first();
    await expect(empty).toBeVisible();
    // The unfocused input alternates every 8 s between its base text and the Ctrl+Shift+M hint
    // (focusing hides the hint), so wait for the hint without touching the input.
    await expect.poll(() => empty.evaluate((el) => getComputedStyle(el, '::before').content), {
      message: 'the input shows the Ctrl+Shift+M hint', timeout: 20_000, intervals: [250],
    }).toContain('Ctrl');
    const measure = async () => {
      const f = (await field.boundingBox())!;
      const hint = await empty.evaluate((el) => {
        const s = getComputedStyle(el, '::before');
        const r = el.getBoundingClientRect();
        const lh = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.6;
        const h = parseFloat(s.height);
        const top = s.position === 'absolute' ? r.top + parseFloat(s.top) : r.top;
        return { align: s.textAlign, content: s.content, centreY: top + (Number.isNaN(h) || h === 0 ? lh : h) / 2, centreX: r.left + r.width / 2 };
      });
      return { f, hint };
    };
    const m = await measure();
    expect(m.hint.align).toBe('center');
    expect(m.hint.content).toContain('Ctrl');
    expect(Math.abs(m.hint.centreY - (m.f.y + m.f.height / 2))).toBeLessThanOrEqual(variant ? 4 : 8);
    expect(Math.abs(m.hint.centreX - (m.f.x + m.f.width / 2))).toBeLessThanOrEqual(8);
    await testInfo.attach(`message-input-hint-${variant || 'default'}`, { body: await field.screenshot(), contentType: 'image/png' });
  });
}
