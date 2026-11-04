import { readFile } from 'node:fs/promises';
import { decode } from '@toon-format/toon';
import type { Locator, Page } from '@playwright/test';
import { expect, test } from './helpers/cookie-audit';
import { focusComposer, dismissComposerFocus } from './helpers/composer-focus';
import { ALL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
import type { ExampleChatEmbed } from '../../../packages/ui/src/demo_chats/types';

// playwright-account: not_required reason=real_static_public_example_logged_out
const SLUG = 'fosdem-2027';
const LICENCE = 'https://creativecommons.org/licenses/by/3.0/';
const privateMarkers = ['vault:v1:', 'vault_wrapped_aes_key', 'vault_key_id', 'aes_key:', 'aes_nonce:', 'dev-openmates-chatfiles', 'chatfiles/', '#key=', 'encrypted_content'];

function savedContent(embed: ExampleChatEmbed): Record<string, unknown> {
  const value = embed.content.trim().startsWith('{') ? JSON.parse(embed.content) : decode(embed.content, {strict:false});
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`Invalid saved embed ${embed.embed_id}`);
  return value as Record<string, unknown>;
}
async function closeSidebar(page: Page) {
  const sidebar = page.getByTestId('activity-history-wrapper');
  if (await sidebar.isVisible()) await page.getByTestId('sidebar-toggle').click();
  await expect(sidebar).toBeHidden();
}
async function publicImage(image: Locator) {
  await expect(image).toBeVisible();
  await expect(image).toHaveCSS('object-fit', 'contain');
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
  const src = await image.getAttribute('src');
  expect(src).toBeTruthy();
  const transport = new URL(src!, image.page().url());
  const publicUrl = new URL(transport.searchParams.get('url') ?? transport.href);
  expect(publicUrl.protocol).toBe('https:');
  expect(publicUrl.username + publicUrl.password).toBe('');
  for (const marker of privateMarkers) expect(publicUrl.href).not.toContain(marker);
}

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=authored-results.demonstrations.proven-capability,authored-results.actions.truthful-and-explicit,authored-results.media.safe-and-attributed,public-example-chats.seo.crawlable,public-example-chats.transcript.safe-rendering,public-example-chats.admission.reviewed-complete,public-example-chats.surface.semantic-parity
  test(`real FOSDEM 2027 example retains its sourced event and calendar at ${width}px`, async ({page, request}, testInfo) => {
    test.setTimeout(120_000);
    // This resolves only the real converted/admitted example. No fallback transcript.
    const chat = ALL_EXAMPLE_CHATS.find(item => item.slug === SLUG);
    expect(chat, 'Publish the reviewed real CLI conversation before running this spec').toBeTruthy();
    if (!chat) throw new Error('The real fosdem-2027 example has not been registered');
    const events = chat.embeds.map(embed => ({embed, content:savedContent(embed)})).filter(({content}) => {
      const authoring = content.authoring as {kind?:string} | undefined;
      return authoring?.kind === 'events.event' && /FOSDEM.*2027/i.test(String(content.title));
    });
    expect(events).toHaveLength(1);
    const {embed:child, content:event} = events[0];
    expect(event.date_start).toBe('2027-01-30');
    expect(event.date_end).toBe('2027-01-31');
    expect(Object.values(chat.public_speech ?? {}).flat()).toHaveLength(0);
    expect(chat.follow_up_suggestions.length).toBeGreaterThan(0);
    const authoring = event.authoring as {origin:string; sources:Array<{url?:string}>};
    expect(authoring.origin).toBe('researched');
    const sources = authoring.sources.flatMap(source => source.url && /^https:\/\/fosdem\.org\/2027\//.test(source.url) ? [source.url] : []);
    expect(sources.length).toBeGreaterThan(0);

    const speechRequests: string[] = [];
    page.on('request', entry => {
      if (entry.resourceType() === 'media' || /\/v1\/(?:[^?#]*\/)?(?:speech|speak)(?:[/?]|$)/.test(entry.url())) speechRequests.push(entry.url());
    });
    page.on('websocket', socket => socket.on('framesent', frame => {
      if (/audio[.:/]speak|"skill_id"\s*:\s*"speak"/.test(String(frame.payload))) speechRequests.push('WebSocket speech request');
    }));
    await page.setViewportSize({width,height:width === 390 ? 844 : 1000});
    const seo = await request.get(`/example/${SLUG}?lang=en`);
    expect(seo.status()).toBe(200);
    const html = await seo.text();
    const visibleMessages = chat.messages.filter(message => message.role === 'user' || message.role === 'assistant');
    const ssrMessages = [...html.matchAll(/class="([^"]*)"/g)].filter(([,classes]) => /\bmessage\b/.test(classes) && /\b(?:user|assistant)-message\b/.test(classes));
    expect(ssrMessages).toHaveLength(visibleMessages.length);
    expect(html).toContain(`/#chat-id=${encodeURIComponent(chat.chat_id)}`);
    for (const marker of privateMarkers) expect(html).not.toContain(marker);
    await page.goto(`/example/${SLUG}?lang=en`, {waitUntil:'domcontentloaded'});
    await expect(page).toHaveURL(new RegExp(`#chat-id=${encodeURIComponent(chat.chat_id)}$`));
    await page.goto(`/?lang=en#chat-id=${encodeURIComponent(chat.chat_id)}`, {waitUntil:'domcontentloaded'});
    await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
    await closeSidebar(page);

    const inspectTranscript = async () => {
      const history = page.getByTestId('chat-history-content');
      await expect(history).toHaveAttribute('data-source-message-count', String(chat.messages.length));
      for (const message of visibleMessages) {
        const rendered = history.locator(`[data-message-id="${message.id}"]`);
        await expect(rendered).toHaveCount(1);
        await rendered.scrollIntoViewIfNeeded();
        await expect(rendered.getByTestId('message-content').first()).not.toBeEmpty();
        await expect(rendered).not.toHaveAttribute('data-status', /^(streaming|processing|sending)$/);
      }
      await expect(history).not.toContainText(/openmates_embeds|ai_authored_results|vault_wrapped_aes_key|content_commitment|\[object Object\]/);
      for (const marker of privateMarkers) await expect(history).not.toContainText(marker);
      await expect(page.getByTestId('assistant-message-speak')).toHaveCount(0);
    };
    await inspectTranscript();
    const card = page.locator(`[data-testid="embed-preview"][data-embed-id="${child.embed_id}"]`);
    const openEvent = async () => {
      await expect(card).toHaveCount(1);
      await card.scrollIntoViewIfNeeded();
      await expect(card).toContainText(String(event.title));
      await expect(card.getByTestId('authored-result-context')).toHaveAttribute('data-origin', 'researched');
      await publicImage(card.getByRole('img', {name:String(event.title),exact:true}));
      if (await card.getAttribute('role') === 'button') {
        // Authored collection entries are complete result-card buttons.
        await card.focus();
        await expect(card).toBeFocused();
        await card.press('Enter');
      } else {
        await expect(card).toHaveAttribute('role','group');
        const expand = card.getByTestId('result-preview-expand');
        await card.hover();
        await expect(expand).toBeVisible();
        await expand.click();
      }
      const fullscreen = page.getByTestId('embed-fullscreen-overlay').last();
      await expect(fullscreen).toBeVisible();
      await expect(fullscreen.getByTestId('embed-header-title')).toHaveText(String(event.title));
      await expect(fullscreen.getByTestId('event-date-label')).toContainText('2027');
      await expect(fullscreen.getByTestId('event-time-range')).toHaveCount(0);
      await expect(fullscreen.getByTestId('event-venue-card')).toContainText(/ULB.*Solbosch/i);
      await expect(fullscreen).toContainText('Brussels');
      for (const source of sources) await expect(fullscreen.locator(`a[href="${source}"]`).first()).toBeVisible();
      await expect(fullscreen).toContainText(/Jndemi/i);
      await expect(fullscreen).toContainText(/illustrative/i);
      await expect(fullscreen).toContainText(/CC\s*BY\s*3\.0/i);
      await expect(fullscreen.locator(`a[href="${LICENCE}"]`).first()).toBeVisible();
      await publicImage(fullscreen.locator('img.event-image'));
      const eventUrl = String(event.url ?? event.source_url ?? '');
      if (/^https?:\/\//.test(eventUrl)) {
        // The open action names the event's own site, never a generic label.
        const domain = new URL(eventUrl).hostname.replace(/^www\./i, '');
        await expect(fullscreen.getByTestId('external-provider-cta')).toContainText(`Open ${domain}`);
      }
      return fullscreen;
    };
    let fullscreen = await openEvent();
    const [download] = await Promise.all([page.waitForEvent('download'),fullscreen.getByTestId('embed-calendar-button').click()]);
    expect(download.suggestedFilename()).toMatch(/\.ics$/);
    const path = await download.path();
    expect(path).toBeTruthy();
    const ics = (await readFile(path!, 'utf8')).replace(/\r\n[ \t]/g,'');
    expect(ics).toContain(`UID:${child.embed_id}@openmates`);
    expect(ics).toContain('DTSTART;VALUE=DATE:20270130');
    expect(ics).toContain('DTEND;VALUE=DATE:20270201');
    expect(ics).not.toMatch(/^DTSTART:|^DURATION:/m);
    await page.screenshot({path:testInfo.outputPath(`fosdem-event-${width}.png`)});
    await fullscreen.getByRole('button', {name:'Close',exact:true}).click();
    await expect(fullscreen).toBeHidden();
    fullscreen = await openEvent();
    await fullscreen.getByRole('button', {name:'Close',exact:true}).click();
    await expect(fullscreen).toBeHidden();
    await page.reload({waitUntil:'domcontentloaded'});
    await closeSidebar(page);
    await inspectTranscript();
    await expect(card).toHaveAttribute('data-embed-id',child.embed_id);

    const suggestions = page.getByTestId('follow-up-suggestion-item');
    await expect(suggestions.first()).toBeVisible();
    await focusComposer(page);
    const editor = page.getByTestId('message-editor').getByRole('textbox');
    await editor.fill('What should I know before visiting the campus?');
    await expect(editor).toBeFocused();
    await expect(editor).toContainText('What should I know before visiting the campus?');
    await editor.fill('');
    await dismissComposerFocus(page);
    // Guest quick-send intentionally requests signup; it does not claim to send
    // an AI turn or provide an unsupported editable-prefill action.
    await page.evaluate(() => {
      document.documentElement.dataset.fosdemSignupRequested = 'false';
      window.addEventListener('openSignupInterface', () => {document.documentElement.dataset.fosdemSignupRequested = 'true';}, {once:true});
    });
    await suggestions.first().click();
    await expect(page.locator('html')).toHaveAttribute('data-fosdem-signup-requested','true');
    await expect(page.getByTestId('assistant-message-speak')).toHaveCount(0);
    expect(speechRequests).toEqual([]);
  });
}
