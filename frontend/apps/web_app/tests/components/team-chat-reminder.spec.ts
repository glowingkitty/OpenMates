// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { scrollChatHistoryToStart } from '../helpers/chat-scroll';

for (const width of [350, 740]) {
  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  test(`Team AI reminder fits ${width}px and opens Mates settings`, async ({ page }) => {
    await page.setViewportSize({ width: width + 40, height: 844 });
    await page.goto(`/dev/preview/teams/TeamChatReminder?chrome=0&theme=light&background=%23dbeafe&width=${width}`);
    await waitForComponentPreview(page);
    const reminder = page.getByTestId('team-chat-ai-reminder');
    await expect(reminder).toHaveAttribute('role', 'note');
    await expect(reminder).toContainText('Mention @openmates or a specific Mate');
    const link = reminder.getByRole('button', { name: '@openmates' });
    await expect(link).toHaveCSS('background-image', /linear-gradient/);
    const geometry = await reminder.evaluate(element => ({ width: element.clientWidth, scrollWidth: element.scrollWidth }));
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
    await link.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('html')).toHaveAttribute('data-team-reminder-settings-path', 'mates');
  });
}

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
  test(`Team history places the system reminder before human messages at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/dev/preview/ChatHistory?chrome=0&theme=light&background=%23dbeafe&width=${width}&variant=teamReminder`);
    await waitForComponentPreview(page);
    const history = page.getByTestId('chat-history-content');
    const container = page.getByTestId('chat-history-container');
    expect((await container.boundingBox())!.height).toBeGreaterThan(400);
    const messages = history.getByTestId('remote-human-message');
    await expect(messages).toHaveCount(2);
    await expect(messages.last()).toContainText('invitation for our volunteers');
    const reminder = page.getByTestId('team-chat-ai-reminder');
    await expect(reminder).toContainText('Mention @openmates');
    await scrollChatHistoryToStart(page, test.info());
    await expect(messages.first()).toBeInViewport({ ratio: 1 });
    await expect(messages.last()).toBeInViewport({ ratio: 1 });
    const [messageBox, reminderBox] = await Promise.all([messages.first().boundingBox(), reminder.boundingBox()]);
    expect(reminderBox!.y + reminderBox!.height).toBeLessThanOrEqual(messageBox!.y);
    const paragraphBox = await reminder.locator('p').boundingBox();
    const containerBox = await container.boundingBox();
    expect(paragraphBox!.y - containerBox!.y).toBeGreaterThanOrEqual(30);
    const geometry = await reminder.evaluate(element => ({ width: element.clientWidth, scrollWidth: element.scrollWidth }));
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
    const link = reminder.getByRole('button', { name: '@openmates' });
    await expect(link).toBeInViewport({ ratio: 1 });
    expect(await link.evaluate(element => {
      const box = element.getBoundingClientRect();
      return element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
    })).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`team-history-reminder-${width}.png`) });
  });
}

// contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
test('Team system reminder stays at the start of overflowing history', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 360 });
  await page.goto('/dev/preview/ChatHistory?chrome=0&theme=light&background=%23dbeafe&width=390&variant=teamReminder');
  await waitForComponentPreview(page);
  const container = page.getByTestId('chat-history-container');
  const reminder = page.getByTestId('team-chat-ai-reminder');
  await expect(reminder).toContainText('Mention @openmates');
  await scrollChatHistoryToStart(page, test.info());
  expect(await container.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(0);
  await container.evaluate(element => element.scrollTo({ top: element.scrollHeight, behavior: 'instant' }));
  await expect(reminder).not.toBeInViewport({ ratio: 1 });
  await scrollChatHistoryToStart(page, test.info());
  const [reminderBox, firstMessageBox] = await Promise.all([
    reminder.boundingBox(), page.getByTestId('remote-human-message').first().boundingBox(),
  ]);
  expect(reminderBox!.y + reminderBox!.height).toBeLessThanOrEqual(firstMessageBox!.y);
  // The expanded title header fills this short viewport. Read the first notice
  // by scrolling it into view, just as with any message below that header.
  await reminder.scrollIntoViewIfNeeded();
  await expect(reminder).toBeInViewport({ ratio: 1 });
  const [paragraphBox, containerBox] = await Promise.all([reminder.locator('p').boundingBox(), container.boundingBox()]);
  expect(paragraphBox!.y - containerBox!.y).toBeGreaterThanOrEqual(30);
  const link = reminder.getByRole('button', { name: '@openmates' });
  expect(await link.evaluate(element => {
    const box = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
  })).toBe(true);
});

// contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
test('Existing system messages use the shared notice surface', async ({ page }) => {
  await page.setViewportSize({ width: 780, height: 844 });
  const props = encodeURIComponent(JSON.stringify({ role: 'system', content: 'This conversation is ready for collaboration.' }));
  await page.goto(`/dev/preview/ChatMessage?chrome=0&theme=light&background=%23dbeafe&width=740&props=${props}`);
  await waitForComponentPreview(page);
  const notice = page.getByRole('note');
  await expect(notice).toContainText('This conversation is ready for collaboration.');
  await expect(notice).toBeInViewport({ ratio: 1 });
});
