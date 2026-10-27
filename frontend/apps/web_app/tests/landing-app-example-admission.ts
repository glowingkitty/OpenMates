/* eslint-disable @typescript-eslint/no-require-imports -- The shared browser helpers use CommonJS. */
// contract-test-file: infrastructure
import type { Page, APIRequestContext, TestInfo, Locator } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { landingAppExamples, landingAppOrder } from '../../../packages/public-site/src/components/landing/landingPageContent';
import { ALL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
import type { ExampleChat, ExampleChatEmbed } from '../../../packages/ui/src/demo_chats/types';
import englishMessages from '../../../packages/ui/src/i18n/locales/en.json';
import { getModelDisplayName } from '../../../packages/ui/src/utils/modelDisplayName';
import { parseMarkdownTable } from '../../../packages/ui/src/components/embeds/sheets/sheetEmbedContent';
import { waitForComponentMotion } from './helpers/component-preview';
import { dismissComposerFocus } from './helpers/composer-focus';

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

const byId = new Map<string, ExampleChat>(ALL_EXAMPLE_CHATS.map(chat => [chat.chat_id, chat]));
const cases = Object.entries(landingAppExamples).sort(([a], [b]) => a.localeCompare(b)).map(([appId, chatId]) => {
  const chat = byId.get(chatId);
  if (!chat) throw new Error(`Landing ${appId} example ${chatId} is not registered`);
  return { appId, chat };
});

const forbidden = [
  'vault:v1:', 'vault_wrapped_aes_key', 'aes_key:', 'aes_nonce:',
  'dev-openmates-chatfiles', 'chatfiles/', 's3_key:', 'docx_s3_key:',
  'screenshot_s3_keys:', 'Presigned URL request failed',
  '[Interactive Question - Invalid JSON]', '[object Object]'
];

async function closeSidebar(page: Page): Promise<void> {
  const sidebar = page.getByTestId('activity-history-wrapper');
  if (await sidebar.isVisible().catch(() => false)) {
    await page.getByTestId('sidebar-toggle').click();
  }
  await expect(sidebar).toBeHidden();
}

async function inspectSeoEntry(request: APIRequestContext, chat: ExampleChat): Promise<void> {
  const response = await request.get(`/example/${chat.slug}`);
  expect(response.status(), chat.slug).toBe(200);
  const html = await response.text();
  const visibleMessages = chat.messages.filter(message => message.role === 'user' || message.role === 'assistant');
  const renderedMessages = [...html.matchAll(/class="([^"]*)"/g)].filter(([, classAttribute]) => {
    const classes = new Set(classAttribute.split(/\s+/));
    return classes.has('message') && (classes.has('user-message') || classes.has('assistant-message'));
  });
  expect(renderedMessages.length, chat.slug).toBe(visibleMessages.length);
  expect(html).toContain(`/#chat-id=${encodeURIComponent(chat.chat_id)}`);
  expect(html).toContain('Open this conversation in OpenMates');
  for (const marker of forbidden) expect(html, `${chat.slug}: ${marker}`).not.toContain(marker);
}

async function expandCompletedActivity(history: Locator, context: string): Promise<void> {
  // Finished skill runs mount their saved previews only after the user opens
  // the activity disclosure. Message hydration is checked by the caller first.
  const groups = history.getByTestId('assistant-activity-group');
  for (let i = 0, count = await groups.count(); i < count; i++) {
    const group = groups.nth(i);
    const toggle = group.getByTestId('assistant-activity-toggle');
    await expect(toggle, `${context}: activity ${i} disclosure state`).toHaveAttribute('aria-expanded', /^(true|false)$/);
    if (await toggle.getAttribute('aria-expanded') === 'false') {
      await toggle.click();
    }
    await expect(toggle, `${context}: activity ${i} opens`).toHaveAttribute('aria-expanded', 'true');
    await expect(group.getByTestId('assistant-activity-body'), `${context}: activity ${i} body`).toBeVisible();
  }
}

async function collapseCompletedActivity(history: Locator, context: string): Promise<void> {
  const toggles = history.getByTestId('assistant-activity-toggle');
  for (let i = 0, count = await toggles.count(); i < count; i++) {
    const toggle = toggles.nth(i);
    if (await toggle.getAttribute('aria-expanded') === 'true') await toggle.click();
    await expect(toggle, `${context}: completed activity collapsed`).toHaveAttribute('aria-expanded', 'false');
  }
}

function sourceMessage(content: string): string {
  const value = content.split('.').reduce<unknown>((node, key) =>
    node && typeof node === 'object' ? (node as Record<string, unknown>)[key] : undefined, englishMessages);
  if (typeof value === 'string') return value;
  const text = value && typeof value === 'object' ? (value as Record<string, unknown>).text : undefined;
  return typeof text === 'string' ? text : content;
}

const generatedMediaApps = new Set(['audio', 'images', 'models3d', 'music', 'videos']);

function embedField(embed: ExampleChatEmbed, field: string): string | undefined {
  try {
    const parsed: unknown = JSON.parse(embed.content);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const value = (parsed as Record<string, unknown>)[field];
      return typeof value === 'string' ? value : undefined;
    }
  } catch { /* TOON source follows. */ }
  const line = embed.content.split('\n').find(candidate => candidate.startsWith(`${field}:`));
  const value = line?.slice(field.length + 1).trim();
  if (value?.startsWith('"') && value.endsWith('"')) {
    try {
      const decoded: unknown = JSON.parse(value);
      if (typeof decoded === 'string') return decoded;
    } catch { /* Legacy unquoted values follow. */ }
  }
  if (value === 'null') return undefined;
  return value?.replace(/^"|"$/g, '');
}

/** Current persisted TOON flattens primitive galleries to a pipe-separated scalar. */
function savedHomeGallery(embed: ExampleChatEmbed): string[] {
  const gallery = embedField(embed, 'image_urls')?.split('|').map(url => url.trim()).filter(Boolean) ?? [];
  const primary = embedField(embed, 'image_url');
  return [...new Set([...(primary ? [primary] : []), ...gallery])];
}

export type FixtureImageProxyObservation = {
  url: string;
  resourceType: string;
  forwardedReferer?: string;
  fetchStatus?: number;
  contentType?: string;
  fetchError?: string;
};

export async function configureFixtureImageProxy(
  page: Page, chat: ExampleChat, routeObservations?: FixtureImageProxyObservation[]
): Promise<void> {
  const imageUrls = new Set<string>();
  for (const embed of chat.embeds) {
    for (const field of ['image_url', 'thumbnail_url', 'media_url', 'preview_url', 'poster_url',
      'cover_url', 'cover_image_url', 'thumbnail', 'channel_thumbnail', 'avatar_url']) {
      const url = embedField(embed, field);
      if (url?.startsWith('https://')) imageUrls.add(url);
    }
    if (embed.type === 'listing' && embedField(embed, 'app_id') === 'home') {
      for (const url of savedHomeGallery(embed)) if (url.startsWith('https://')) imageUrls.add(url);
    }
    const videoId = embedField(embed, 'video_id');
    if (videoId && /^[A-Za-z0-9_-]{11}$/.test(videoId)) {
      for (const quality of ['hqdefault', 'maxresdefault']) {
        imageUrls.add(`https://img.youtube.com/vi/${videoId}/${quality}.jpg`);
      }
    }
  }
  // The runner's localhost page has no owned OpenMates origin. Keep the real
  // public image proxy and bytes; declare the app Referer for these fixture
  // images only. Deployed public checks use their actual first-party Referer.
  await page.route(url => url.origin === 'https://preview.openmates.org'
    && url.pathname === '/api/v1/image' && imageUrls.has(url.searchParams.get('url') ?? ''), async route => {
    if (!['localhost', '127.0.0.1', '[::1]'].includes(new URL(page.url()).hostname)) {
      await route.continue();
      return;
    }
    const observation: FixtureImageProxyObservation = {
      url: route.request().url(),
      resourceType: route.request().resourceType(),
      forwardedReferer: route.request().method() === 'GET' && route.request().resourceType() === 'image'
        ? 'https://app.dev.openmates.org/' : undefined,
    };
    routeObservations?.push(observation);
    if (route.request().method() !== 'GET' || route.request().resourceType() !== 'image') {
      await route.continue();
      return;
    }
    try {
      // Chromium's direct HTTP/2 continuation fails for this public proxy in
      // isolated CI. Fetch the real response from the runner, then pass its
      // status, headers and bytes through to the browser unchanged.
      const response = await route.fetch({
        headers: { ...route.request().headers(), referer: 'https://app.dev.openmates.org/' }
      });
      observation.fetchStatus = response.status();
      observation.contentType = response.headers()['content-type'];
      await route.fulfill({ response });
    } catch (error) {
      observation.fetchError = String(error);
      await route.abort('failed');
    }
  });
}

function assistantPreview(history: Locator, embed: ExampleChatEmbed): Locator {
  return history.getByTestId('message-assistant')
    .locator(`[data-testid="embed-preview"][data-embed-id="${embed.embed_id}"]`);
}

async function selectInlineEmbedPreview(history: Locator, embed: ExampleChatEmbed, context: string): Promise<Locator> {
  const previews = assistantPreview(history, embed);
  const activePreview = async (): Promise<Locator | null> => {
    for (let i = 0, count = await previews.count(); i < count; i++) {
      const preview = previews.nth(i);
      if (!await preview.isVisible()) continue;
      const inactiveSlide = await preview.evaluate(element => Boolean(element.closest(
        '.embed-preview-large-content--hidden, .embed-preview-large-overlay--hidden',
      )));
      if (!inactiveSlide) return preview;
    }
    return null;
  };

  const initiallyActive = await activePreview();
  if (initiallyActive) return initiallyActive;
  const carousels = history.getByRole('tablist', { name: 'Carousel position' });
  for (let carouselIndex = 0, carouselCount = await carousels.count(); carouselIndex < carouselCount; carouselIndex++) {
    const tabs = carousels.nth(carouselIndex).getByRole('tab');
    for (let tabIndex = 0, tabCount = await tabs.count(); tabIndex < tabCount; tabIndex++) {
      const tab = tabs.nth(tabIndex);
      await tab.click();
      await expect(tab, `${context}: carousel slide ${tabIndex + 1} selected`).toHaveAttribute('aria-selected', 'true');
      const selected = await activePreview();
      if (selected) return selected;
    }
  }
  throw new Error(`${context}: inline embed ${embed.embed_id} did not appear on any carousel slide`);
}

async function inspectGeneratedMediaGraph(page: Page, history: Locator, chat: ExampleChat, appId: string): Promise<void> {
  if (!generatedMediaApps.has(appId)
    || !chat.metadata.app_skill_examples?.some(example => example.startsWith(`${appId}.generate`))) return;
  const parents = chat.embeds.filter(embed => embed.type === 'app_skill_use'
    && embedField(embed, 'app_id') === appId && embedField(embed, 'skill_id')?.startsWith('generate')
    && !embed.parent_embed_id);
  expect(parents.length, `${chat.slug}: saved ${appId} generation parent`).toBeGreaterThan(0);
  await collapseCompletedActivity(history, chat.slug);
  for (const parent of parents) {
    const childIds = parent.embed_ids ?? [];
    expect(childIds.length, `${chat.slug}: generation ${parent.embed_id} needs saved results`).toBeGreaterThan(0);
    for (const childId of childIds) {
      const child = chat.embeds.find(embed => embed.embed_id === childId);
      expect(child, `${chat.slug}: missing saved generation child ${childId}`).toBeDefined();
      expect(child?.parent_embed_id, `${chat.slug}: child points to generation parent`).toBe(parent.embed_id);
      const prompt = embedField(child!, 'prompt');
      const model = embedField(child!, 'model') ?? embedField(child!, 'provider_model');
      expect(prompt, `${chat.slug}: child ${childId} complete prompt`).toBeTruthy();
      expect(model, `${chat.slug}: child ${childId} actual model`).toBeTruthy();
      const mediaField = appId === 'images' ? 'previewImageUrl'
        : appId === 'videos' ? 'previewVideoUrl'
          : appId === 'models3d' ? 'modelUrl' : 'previewAudioUrl';
      const mediaUrl = embedField(child!, mediaField);
      expect(mediaUrl, `${chat.slug}: child ${childId} reviewed public ${mediaField}`).toMatch(
        /^https:\/\/(?:dev-)?openmates-public-examples\.nbg1\.your-objectstorage\.com\/reviewed-media\//,
      );
      const preview = await selectInlineEmbedPreview(history, child!,
        `${chat.slug}: generated child ${childId}`);
      await expect(preview, `${chat.slug}: generation child visible in assistant reply with activity collapsed`).toBeVisible();
      const fullscreen = await openFullscreen(page, preview);
      await expect(fullscreen).toContainText(prompt!);
      await expect(fullscreen).toContainText(['audio', 'images', 'music'].includes(appId)
        ? getModelDisplayName(model!) : model!);
      if (appId === 'audio' || appId === 'music' || appId === 'videos') {
        const media = fullscreen.locator(appId === 'videos' ? 'video' : 'audio').first();
        await expect(media).toHaveCount(1);
        if (appId === 'audio') {
          await expect(fullscreen.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
        } else {
          await expect(media).toBeVisible();
        }
        await expect.poll(() => media.evaluate((element: HTMLMediaElement) => element.readyState),
          { message: `${chat.slug}: ${appId} fullscreen media loads` }).toBeGreaterThanOrEqual(1);
        expect(await media.evaluate((element: HTMLMediaElement) => element.currentSrc)).toBe(mediaUrl);
        expect(await media.evaluate((element: HTMLMediaElement) => element.duration)).toBeGreaterThan(0);
        await media.evaluate((element: HTMLMediaElement) => { element.muted = true; });
        if (appId === 'audio') {
          await fullscreen.getByRole('button', { name: 'Play', exact: true }).click();
        } else {
          await media.evaluate(async (element: HTMLMediaElement) => { await element.play(); });
        }
        await expect.poll(() => media.evaluate((element: HTMLMediaElement) => element.currentTime),
          { message: `${chat.slug}: ${appId} fullscreen media plays` }).toBeGreaterThan(0);
        await media.evaluate((element: HTMLMediaElement) => element.pause());
      } else if (appId === 'models3d') {
        await expect(fullscreen.getByTestId('models3d-download-model')).toHaveAttribute('href', mediaUrl!);
        if (embedField(child!, 'posterUrl')) {
          const poster = fullscreen.locator('.model-fullscreen img');
          await expect(poster).toBeVisible();
          await expect.poll(() => poster.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
        }
      } else {
        const image = fullscreen.locator('.full-image').first();
        await expect(image).toBeVisible();
        await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth),
          { message: `${chat.slug}: ${appId} fullscreen image loads` }).toBeGreaterThan(0);
      }
      await closeFullscreen(page, fullscreen);
    }
  }
  await expandCompletedActivity(history, `${chat.slug}: generated skill activity`);
  for (const parent of parents) {
    await expect(assistantPreview(history, parent).filter({ visible: true }).first(),
      `${chat.slug}: generation invocation available in completed activity`).toBeVisible();
  }
}

async function inspectIconAsset(page: Page, icon: Locator, expectedName: string, context: string): Promise<void> {
  await expect(icon, `${context}: icon has a visible box`).toBeVisible();
  const iconUrl = await icon.evaluate(element => {
    const own = getComputedStyle(element);
    const after = getComputedStyle(element, '::after');
    const image = [own.maskImage, own.backgroundImage, after.maskImage, after.backgroundImage]
      .find(value => value && value !== 'none');
    return image?.match(/^url\(["']?(.*?)["']?\)$/)?.[1] ?? null;
  });
  expect(iconUrl, `${context}: icon has its actual SVG asset`).toBeTruthy();
  const url = new URL(iconUrl!, page.url());
  if (url.protocol === 'data:') {
    // Vite inlines small icons. Verify the shipped glyph as well as drawable
    // SVG content; an arbitrary inline SVG must not pass the icon check.
    expect(url.href, `${context}: inline asset is SVG`).toMatch(/^data:image\/svg\+xml(?:;base64)?,/);
    const comma = url.href.indexOf(',');
    const svg = url.href.slice(0, comma).endsWith(';base64')
      ? Buffer.from(url.href.slice(comma + 1), 'base64').toString('utf8')
      : decodeURIComponent(url.href.slice(comma + 1));
    const glyphs: Record<string, string> = {
      book: 'M24 40a21.072 21.072',
      pcbdesign: 'M14 19.828l12 12V47',
    };
    expect(glyphs[expectedName], `${context}: known shipped glyph`).toBeTruthy();
    expect(svg, `${context}: correct inline app icon`).toContain(glyphs[expectedName]);
    expect(svg, `${context}: SVG contains drawable paths`).toMatch(/<(?:path|rect|circle|polygon|polyline|line|ellipse)\b/);
    return;
  }
  expect(url.pathname, `${context}: correct app icon`).toMatch(new RegExp(`/${expectedName}[.-]`));
  const response = await page.request.get(url.href);
  expect(response.ok(), `${context}: SVG asset loads`).toBe(true);
  expect(await response.text(), `${context}: SVG contains drawable paths`).toMatch(/<(?:path|rect|circle|polygon|polyline|line|ellipse)\b/);
}

async function inspectReportedHeaderRegressions(page: Page, history: Locator, chat: ExampleChat, appId: string): Promise<void> {
  if (appId === 'books') {
    await expandCompletedActivity(history, `${chat.slug}: book focus activation`);
    const icon = history.getByTestId('focus-mode-bar').locator('.app-icon-circle .icon_rounded').first();
    await inspectIconAsset(page, icon, 'book', `${chat.slug}: book focus activation`);
  }
  if (appId === 'models3d') {
    const request = sourceMessage(chat.messages.find(message => message.role === 'user')!.content);
    expect(request, `${chat.slug}: landing request asks for plural models`).toMatch(/3D[ -]printable[^.]*models\b/i);
  }
  if (appId !== 'health' && appId !== 'electronics') return;
  await expandCompletedActivity(history, `${chat.slug}: reported result regression`);
  const parent = chat.embeds.find(embed => embed.type === 'app_skill_use' && embedField(embed, 'app_id') === appId)!;
  expect(parent, `${chat.slug}: saved search invocation`).toBeDefined();
  const preview = assistantPreview(history, parent).filter({ visible: true }).first();
  await expect(preview).toBeVisible();
  if (appId === 'electronics') {
    await inspectIconAsset(page, preview.locator('[data-app-icon="electronics"] > div').first(),
      'pcbdesign', `${chat.slug}: skill preview`);
  }
  const fullscreen = await openFullscreen(page, preview);
  const resultCards = fullscreen.getByTestId('search-template-grid').getByTestId('embed-preview');
  await expect(resultCards.first()).toBeVisible();
  if (appId === 'electronics') {
    await inspectIconAsset(page, resultCards.first().locator('[data-app-icon="electronics"] > div').first(),
      'pcbdesign', `${chat.slug}: component result preview`);
  } else {
    const appointment = chat.embeds.find(embed => embed.type === 'appointment'
      && embedField(embed, 'insurance') === 'unknown' && embedField(embed, 'provider_platform') === 'ExampleClinicA')!;
    expect(appointment, `${chat.slug}: source unknown-insurance ExampleClinicA appointment`).toBeDefined();
    const card = fullscreen.locator(`[data-testid="embed-preview"][data-embed-id="${appointment.embed_id}"]`);
    const verifiedLabel = sourceMessage('embeds.health.insurance_verify_on_provider').replace('{provider}', 'ExampleClinicA');
    await expect(card.locator('.insurance-unknown-badge')).toHaveText(verifiedLabel);
    await expect(card).not.toContainText(/verify on ExampleClinicB/i);
    await card.click();
    const child = page.locator('.child-embed-overlay .unified-embed-fullscreen-overlay').last();
    await expect(child).toBeVisible();
    await expect(child.locator('.insurance-unknown-badge')).toHaveText(verifiedLabel);
    await expect(child).not.toContainText(/verify on ExampleClinicB/i);
    await closeFullscreen(page, child);
  }
  await closeFullscreen(page, fullscreen);
}

async function inspectSavedResultGraph(page: Page, history: Locator, chat: ExampleChat, appId: string): Promise<void> {
  if (appId === 'home' && chat.slug === 'furnished-apartments-berlin') {
    const parents = chat.embeds.filter(embed => embed.type === 'app_skill_use'
      && embedField(embed, 'app_id') === 'home' && embedField(embed, 'skill_id') === 'search'
      && embedField(embed, 'status') === 'finished');
    expect(parents.length, `${chat.slug}: genuine finished home search output`).toBeGreaterThan(0);
    const parent = parents.find(candidate => chat.embeds.some(embed => embed.type === 'listing'
      && embed.parent_embed_id === candidate.embed_id && savedHomeGallery(embed).length > 1));
    expect(parent, `${chat.slug}: real search must include a multi-photo apartment`).toBeDefined();
    const listings = chat.embeds.filter(embed => embed.type === 'listing' && embed.parent_embed_id === parent!.embed_id);
    expect(parent!.embed_ids, `${chat.slug}: saved parent retains listing references`).toEqual(expect.arrayContaining(listings.map(listing => listing.embed_id)));
    const hasCoordinates = (listing: ExampleChatEmbed): boolean => {
      const lat = embedField(listing, 'latitude'); const lon = embedField(listing, 'longitude');
      return lat !== undefined && lon !== undefined && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon)) && Math.abs(Number(lat)) <= 90 && Math.abs(Number(lon)) <= 180;
    };
    const located = listings.filter(hasCoordinates);
    expect(located.length, `${chat.slug}: actual listings supply overview map pins`).toBeGreaterThan(0);
    await expandCompletedActivity(history, `${chat.slug}: home results`);
    const searchPreview = await selectInlineEmbedPreview(history, parent!, `${chat.slug}: activate home search result slide`);
    await expect(searchPreview.getByTestId('search-no-results-message')).toHaveCount(0);
    await expect(searchPreview.getByTestId('home-search-result-count')).toHaveAttribute('data-count', String(listings.length));
    await expect(searchPreview.locator('img.listing-thumbnail')).toHaveCount(Math.min(3, listings.filter(listing => embedField(listing, 'image_url')).length));
    const search = await openFullscreen(page, searchPreview);
    await waitForComponentMotion(search);
    const cards = search.getByTestId('search-template-grid').getByTestId('embed-preview');
    const markers = search.locator('.leaflet-marker-icon[data-marker-ref]');
    await expect(cards).toHaveCount(listings.length);
    await expect(markers).toHaveCount(located.length);
    for (const listing of located) await expect(search.locator(`.leaflet-marker-icon[data-marker-ref="${listing.embed_id}"]`)).toHaveCount(1);
    const launcher = search.getByTestId('search-template-filter-button');
    const panel = search.getByTestId('search-template-filter-menu');
    await expect(launcher).toHaveAttribute('aria-expanded', 'false');
    await expect(search.getByTestId('home-filter-max-price')).toHaveCount(0);
    await launcher.click();
    await expect(panel).toBeVisible();
    await expect(launcher).toHaveAttribute('data-icon', 'close');
    // Compute the advertised-price boundary from source data, never from DOM or mocked output.
    const priced = listings.filter(listing => embedField(listing, 'price') !== undefined && Number.isFinite(Number(embedField(listing, 'price'))));
    expect(priced.length, `${chat.slug}: actual advertised numeric prices`).toBeGreaterThan(0);
    const minimum = Math.min(...priced.map(listing => Number(embedField(listing, 'price'))));
    const affordable = priced.filter(listing => Number(embedField(listing, 'price')) <= minimum);
    await search.getByTestId('home-filter-max-price').fill(String(minimum));
    await expect(cards).toHaveCount(affordable.length);
    await expect(markers).toHaveCount(affordable.filter(hasCoordinates).length);
    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
    await expect(search).toBeVisible();
    await expect(launcher).toHaveAttribute('aria-expanded', 'false');
    await launcher.click();
    await search.getByTestId('search-template-clear-filters').click();
    await launcher.click();
    await expect(cards).toHaveCount(listings.length);
    await expect(markers).toHaveCount(located.length);
    // City fallbacks may share coordinates; the topmost rendered pin remains selectable.
    const selectedMarker = markers.last();
    const markerRef = await selectedMarker.getAttribute('data-marker-ref');
    const markerListing = located.find(listing => listing.embed_id === markerRef)!;
    expect(markerListing, `${chat.slug}: clicked pin references a saved apartment`).toBeDefined();
    await selectedMarker.click();
    let child = page.locator('.child-embed-overlay .unified-embed-fullscreen-overlay').last();
    await expect(child.getByTestId('home-location-evidence')).toBeVisible();
    await expect(child).toContainText(embedField(markerListing, 'title')!);
    await closeFullscreen(page, child);
    const listing = listings.find(item => savedHomeGallery(item).length > 1)!;
    const photos = savedHomeGallery(listing);
    const title = embedField(listing, 'title')!;
    await search.getByTestId('search-template-filter').fill(title);
    const titleMatches = listings.filter(item => embedField(item, 'title')?.includes(title));
    await expect(cards).toHaveCount(titleMatches.length);
    await expect(markers).toHaveCount(titleMatches.filter(hasCoordinates).length);
    await search.locator(`[data-testid="embed-preview"][data-embed-id="${listing.embed_id}"]`).click();
    child = page.locator('.child-embed-overlay .unified-embed-fullscreen-overlay').last();
    const gallery = child.getByTestId('home-gallery');
    const counter = child.getByTestId('home-gallery-counter');
    const image = child.getByTestId('home-gallery-image');
    await expect(counter).toHaveText(`1 / ${photos.length}`);
    await expect(gallery.getByRole('group').getByRole('button')).toHaveCount(photos.length);
    const thumbnailSources = await gallery.getByRole('group').locator('img').evaluateAll((images: HTMLImageElement[]) => images.map(image => new URL(image.src).searchParams.get('url')));
    expect(thumbnailSources, `${chat.slug}: every supplied gallery URL remains in source order`).toEqual(photos);
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    await gallery.getByRole('button', {name: 'Next photo', exact: true}).click();
    await expect(counter).toHaveText(`2 / ${photos.length}`);
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    expect(new URL((await image.getAttribute('src'))!, page.url()).searchParams.get('url')).toBe(photos[1]);
    await gallery.getByRole('button', {name: 'Previous photo', exact: true}).click();
    await expect(counter).toHaveText(`1 / ${photos.length}`);
    await gallery.getByRole('group').getByRole('button').last().click();
    await expect(counter).toHaveText(`${photos.length} / ${photos.length}`);
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    const description = embedField(listing, 'description');
    expect(description?.trim().length, `${chat.slug}: source apartment description`).toBeGreaterThan(0);
    await expect(child.locator('.description')).toHaveText(description!);
    for (const id of ['home-listing-facts', 'home-amenities', 'home-match-evidence', 'home-visual-evidence', 'home-location-evidence', 'home-neighborhood-evidence']) {
      await child.getByTestId(id).scrollIntoViewIfNeeded();
      await expect(child.getByTestId(id), `${chat.slug}: rich listing section ${id}`).not.toBeEmpty();
    }
    expect(embedField(listing, 'match_evidence_status'), `${chat.slug}: persisted match evidence`).toBeDefined();
    expect(embedField(listing, 'visual_assessment_status'), `${chat.slug}: persisted visual assessment`).toBeDefined();
    expect(embedField(listing, 'neighborhood_source'), `${chat.slug}: sourced neighborhood evidence`).toBeDefined();
    await expect(child.getByTestId('home-match-evidence')).toContainText(sourceMessage(`home_listing.status_${embedField(listing, 'match_evidence_status')}`));
    await expect(child.getByTestId('home-visual-evidence')).toContainText(`${embedField(listing, 'visual_assessment_photo_count') ?? 0} / ${embedField(listing, 'visual_assessment_total_photo_count') ?? photos.length}`);
    await expect(child.getByTestId('home-neighborhood-evidence')).toContainText(embedField(listing, 'neighborhood_source')!);
    await closeFullscreen(page, child);
    await search.getByTestId('search-template-filter').fill('');
    await closeFullscreen(page, search);
    // Compare bounded real summary Sheets as well as the housing result graph.
    for (const sheet of chat.embeds.filter(embed => embed.type === 'sheet').slice(0, 2)) {
      const markdown = embedField(sheet, 'table') ?? embedField(sheet, 'code');
      expect(markdown?.trim().length, `${chat.slug}: saved Sheet contains its actual table`).toBeGreaterThan(0);
      const expectedTable = parseMarkdownTable(markdown!);
      expect(expectedTable.rowCount, `${chat.slug}: saved Sheet data rows`).toBeGreaterThan(0);
      expect(expectedTable.colCount, `${chat.slug}: saved Sheet columns`).toBeGreaterThan(0);
      const sheetPreview = await selectInlineEmbedPreview(history, sheet, `${chat.slug}: activate apartment summary Sheet`);
      const sheetFullscreen = await openFullscreen(page, sheetPreview);
      await waitForComponentMotion(sheetFullscreen);
      const table = sheetFullscreen.locator('table.spreadsheet');
      await expect(table).toBeVisible();
      const visibleLabel = (content: string): string => content.replace(/\[([^\]]*)\]\((?:embed|wiki):[^)]+\)/g, '$1');
      await expect(table.locator('thead .col-header-text')).toHaveText(expectedTable.headers.map(header => visibleLabel(header.content)));
      const rows = table.locator('tbody tr');
      await expect(rows).toHaveCount(expectedTable.rowCount);
      await expect(rows.first().locator('td:not(.row-num)')).toHaveCount(expectedTable.colCount);
      // Up to 48 real source cells per Sheet; counts above still cover the full table.
      for (let row = 0; row < Math.min(expectedTable.rowCount, 6); row++) {
        const cells = rows.nth(row).locator('td:not(.row-num)');
        for (let column = 0; column < Math.min(expectedTable.colCount, 8); column++) {
          await expect(cells.nth(column), `${chat.slug}: saved Sheet row ${row + 1}, column ${column + 1}`)
            .toHaveText(visibleLabel(expectedTable.rows[row][column].content));
        }
      }
      await closeFullscreen(page, sheetFullscreen);
    }
  }
  if (appId === 'shopping' && chat.slug === 'air-fryers-retail-germany') {
    const parents = chat.embeds.filter(embed => embed.type === 'app_skill_use'
      && embedField(embed, 'app_id') === 'shopping'
      && embedField(embed, 'skill_id') === 'search_products'
      && embedField(embed, 'status') === 'finished');
    expect(parents, `${chat.slug}: finished ExampleRetail product search`).toHaveLength(1);
    const parent = parents[0];
    expect(embedField(parent, 'provider'), `${chat.slug}: ExampleRetail search provider`).toMatch(/^ExampleRetail$/i);
    expect(embedField(parent, 'country'), `${chat.slug}: German search market`).toBe('de');
    const products = chat.embeds.filter(embed => embed.type === 'product' && embed.parent_embed_id === parent.embed_id);
    expect(products.length, `${chat.slug}: saved ExampleRetail product results`).toBeGreaterThanOrEqual(3);
    expect(parent.embed_ids, `${chat.slug}: search parent lists every product`).toEqual(
      expect.arrayContaining(products.map(product => product.embed_id))
    );
    for (const product of products) {
      expect(embedField(product, 'provider'), `${chat.slug}: ${product.embed_id} provider`).toMatch(/^ExampleRetail$/i);
      expect(embedField(product, 'country'), `${chat.slug}: ${product.embed_id} market`).toBe('de');
      expect(embedField(product, 'purchase_url'), `${chat.slug}: ${product.embed_id} purchase destination`)
        .toMatch(/^https:\/\/www\.ExampleRetail\.de\//);
      expect(embedField(product, 'image_url'), `${chat.slug}: ${product.embed_id} source image`)
        .toMatch(/^https:\/\/m\.media-ExampleRetail\.com\//);
    }

    const selectedRefs = ['philips-airfryer-2000-fay', 'cosori-airfryer-turboblaze-3zH', 'philips-airfryer-dual-pjD'];
    const selected = selectedRefs.map(ref => {
      const product = products.find(item => embedField(item, 'embed_ref') === ref);
      expect(product, `${chat.slug}: selected product ${ref} has a saved result`).toBeDefined();
      return product!;
    });
    const activityToggles = history.getByTestId('assistant-activity-toggle');
    expect(await activityToggles.count(), `${chat.slug}: saved completed activity disclosure`).toBeGreaterThan(0);
    for (let i = 0, count = await activityToggles.count(); i < count; i++) {
      const toggle = activityToggles.nth(i);
      if (await toggle.getAttribute('aria-expanded') === 'true') await toggle.click();
      await expect(toggle, `${chat.slug}: completed activity collapsed before inline product review`)
        .toHaveAttribute('aria-expanded', 'false');
    }
    for (const product of selected) {
      const preview = await selectInlineEmbedPreview(history, product,
        `${chat.slug}: ${embedField(product, 'embed_ref')} with activity collapsed`);
      await expect(preview.locator('.product-preview.large'),
        `${chat.slug}: selected product card visible on its carousel slide`).toBeVisible();
    }

    await expandCompletedActivity(history, `${chat.slug}: shopping results`);
    const searchPreview = assistantPreview(history, parent).filter({ visible: true }).first();
    await expect(searchPreview, `${chat.slug}: finished search preview in expanded activity`).toBeVisible();
    const searchFullscreen = await openFullscreen(page, searchPreview);
    const resultCards = searchFullscreen.getByTestId('search-template-grid').getByTestId('embed-preview');
    await expect(resultCards.first(), `${chat.slug}: search fullscreen shows result cards`).toBeVisible();
    expect(await resultCards.count()).toBeGreaterThanOrEqual(selected.length);
    await closeFullscreen(page, searchFullscreen);

    for (const product of selected) {
      const preview = await selectInlineEmbedPreview(history, product,
        `${chat.slug}: ${embedField(product, 'embed_ref')} fullscreen source`);
      const fullscreen = await openFullscreen(page, preview);
      await expect(fullscreen.locator('.product-fullscreen .title')).toContainText(embedField(product, 'title')!);
      await expect(fullscreen.locator('.product-fullscreen .price')).toContainText(embedField(product, 'price')!);
      const purchase = fullscreen.locator('a.embed-header-cta');
      await expect(purchase, `${chat.slug}: product purchase link`).toHaveAttribute('href', embedField(product, 'purchase_url')!);
      await expect(purchase).toHaveAttribute('target', '_blank');
      const image = fullscreen.locator('.product-fullscreen img.product-image');
      await expect(image, `${chat.slug}: product image`).toBeVisible();
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth),
        { message: `${chat.slug}: ${product.embed_id} image loads` }).toBeGreaterThan(0);
      await closeFullscreen(page, fullscreen);
    }
  }
  if (appId === 'design') {
    const icons = chat.embeds.filter(embed => embed.parent_embed_id
      && embedField(embed, 'app_id') === 'design' && embedField(embed, 'svg_path'));
    expect(icons.length, `${chat.slug}: saved home/settings icon results`).toBeGreaterThanOrEqual(2);
    const answers = chat.messages.filter(message => message.role === 'assistant')
      .map(message => sourceMessage(message.content)).join('\n');
    const selected = icons.filter(icon => [icon.embed_id, embedField(icon, 'embed_ref')]
      .filter(Boolean).some(ref => answers.includes(`[!](embed:${ref})`)));
    expect(selected.length, `${chat.slug}: selected icons have visual inline previews`).toBeGreaterThanOrEqual(2);
    await collapseCompletedActivity(history, chat.slug);
    for (const icon of selected) {
      const preview = await selectInlineEmbedPreview(history, icon, `${chat.slug}: recommended icon`);
      await preview.scrollIntoViewIfNeeded();
      const image = preview.locator('.icon-art img');
      await expect(image).toBeVisible();
      await expect(image).toBeInViewport();
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth),
        { message: `${chat.slug}: icon preview has pixels` }).toBeGreaterThan(0);
      const fullscreen = await openFullscreen(page, preview);
      const stage = fullscreen.getByTestId('design-icon-result-fullscreen').locator('.icon-stage');
      await expect(stage).toBeVisible();
      await expect.poll(async () => {
        const svg = stage.locator('svg');
        if (await svg.count()) {
          return svg.evaluate(element => element.querySelectorAll('path,rect,circle,polygon,polyline,line,ellipse').length > 0
            && element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height > 0);
        }
        const image = stage.locator('img');
        return await image.count() === 1 && image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0);
      }, { message: `${chat.slug}: fullscreen icon actually renders` }).toBe(true);
      await closeFullscreen(page, fullscreen);
    }
  }
  if (appId === 'nutrition') {
    const recipes = chat.embeds.filter(embed => embed.type === 'recipe' && embed.parent_embed_id);
    expect(recipes.length, `${chat.slug}: saved nutrition recipe children`).toBeGreaterThan(0);
    const parent = chat.embeds.find(embed => embed.embed_id === recipes[0].parent_embed_id);
    expect(parent?.embed_ids, `${chat.slug}: recipe parent includes all saved results`).toEqual(
      expect.arrayContaining(recipes.map(recipe => recipe.embed_id)));
    await collapseCompletedActivity(history, chat.slug);
    const answers = chat.messages.filter(message => message.role === 'assistant')
      .map(message => sourceMessage(message.content)).join('\n');
    const selected = recipes.filter(recipe => [recipe.embed_id, embedField(recipe, 'embed_ref')]
      .filter(Boolean).some(ref => answers.includes(`[!](embed:${ref})`)
        || [...answers.matchAll(/```json\s*([\s\S]*?)```/g)].some(([, block]) => {
          try { return JSON.parse(block).embed_id === ref; } catch { return false; }
        })));
    expect(selected.length, `${chat.slug}: multiple recommendations reference actual saved recipe previews`)
      .toBeGreaterThanOrEqual(Math.min(recipes.length, 2));
    for (const recipe of selected) {
      const preview = await selectInlineEmbedPreview(history, recipe,
        `${chat.slug}: recommended recipe ${recipe.embed_id}`);
      await expect(preview, `${chat.slug}: recommended recipe visible with activity collapsed`).toBeVisible();
      const servings = Number(embedField(recipe, 'servings'));
      expect(Number.isFinite(servings) && servings > 0,
        `${chat.slug}: source recipe has a positive serving count`).toBe(true);
      const nutrientCodes = ['ENERC_KCAL', 'PROCNT', 'FAT', 'CHOCDF'];
      const perServingValues = nutrientCodes.map((code, index) => {
        const total = Number(embedField(recipe, `nutrition_${code}_quantity`));
        expect(Number.isFinite(total) && total >= 0,
          `${chat.slug}: source recipe has ${code} total`).toBe(true);
        expect(embedField(recipe, `nutrition_${code}_unit`)).toBe(index === 0 ? 'kcal' : 'g');
        return `${Number((total / servings).toFixed(1))}${index === 0 ? '' : 'g'}`;
      });
      const recipeFullscreen = await openFullscreen(page, preview);
      await expect(recipeFullscreen).toContainText(embedField(recipe, 'title')!);
      await expect(recipeFullscreen.getByTestId('nutrition-recipe-details'))
        .toContainText(`${servings} ${sourceMessage('embeds.nutrition.servings')}`);
      const image = recipeFullscreen.getByTestId('nutrition-recipe-image');
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth),
        { message: `${chat.slug}: recommended recipe image loads` }).toBeGreaterThan(0);
      const macros = recipeFullscreen.locator('.nutrition-grid');
      await expect(macros.locator('.nutrition-value'),
        `${chat.slug}: calories and macros use the source serving count`).toHaveText(perServingValues);
      await macros.scrollIntoViewIfNeeded();
      for (const item of await macros.locator('.nutrition-item').all()) {
        await expect(item.locator('.nutrition-value')).toBeInViewport({ ratio: 1 });
        await expect(item.locator('.nutrition-label')).toBeInViewport({ ratio: 1 });
      }
      await closeFullscreen(page, recipeFullscreen);
    }
    await expandCompletedActivity(history, `${chat.slug}: recipe search activity`);
    const preview = assistantPreview(history, parent!).filter({ visible: true }).first();
    await expect(preview, `${chat.slug}: saved recipe search available in completed activity`).toBeVisible();
    const fullscreen = await openFullscreen(page, preview);
    const recipeCards = fullscreen.getByTestId('search-template-grid').getByTestId('embed-preview');
    await expect(recipeCards.first()).toBeVisible();
    await expect(recipeCards, `${chat.slug}: search fullscreen renders every saved recipe`).toHaveCount(recipes.length);
    await closeFullscreen(page, fullscreen);
  }
  if (appId === 'social_media') {
    const userMessage = chat.messages.find(message => message.role === 'user');
    expect(userMessage?.content, `${chat.slug}: saved original social request`).toBeTruthy();
    const renderedUser = history.locator(`[data-message-id="${userMessage?.id}"]`);
    const userContent = renderedUser.getByTestId('message-content');
    await expect(userContent).not.toBeEmpty();
    const originalRequest = sourceMessage(userMessage!.content);
    if (originalRequest.includes('\n')) {
      expect(await userContent.locator('br').count() + await userContent.locator('p').count(),
        `${chat.slug}: source line breaks render as line or paragraph boundaries`).toBeGreaterThan(1);
    }
    if (/\n[ \t]*\n/.test(originalRequest)) {
      expect(await userContent.locator('p').count(),
        `${chat.slug}: source empty line renders as paragraph boundary`).toBeGreaterThan(1);
    }
    const posts = chat.embeds.filter(embed => embed.type === 'social_post' && embed.parent_embed_id);
    expect(posts.length, `${chat.slug}: saved social post children`).toBeGreaterThan(0);
    const postsWithMedia = posts.filter(post => {
      const url = embedField(post, 'media_url') ?? embedField(post, 'thumbnail_url');
      return Boolean(url && /^https?:\/\//.test(url));
    });
    expect(postsWithMedia.length, `${chat.slug}: returned post images survive provider mapping and conversion`)
      .toBeGreaterThan(0);
    const firstParent = chat.embeds.find(embed => embed.embed_id === posts[0].parent_embed_id);
    expect(firstParent?.embed_ids, `${chat.slug}: post parent includes saved child`).toContain(posts[0].embed_id);
    await collapseCompletedActivity(history, chat.slug);
    const answers = chat.messages.filter(message => message.role === 'assistant')
      .map(message => sourceMessage(message.content)).join('\n');
    const citations = [...answers.matchAll(/\[([^\]]+)\]\(embed:([^)]+)\)/g)]
      .filter(([, label]) => label !== '!');
    if (citations.length > 0) {
      // Ordinary source citations render as inline links; only [!] requests a card.
      // Follow each distinct saved post while its completed skill activity is hidden.
      const citedRefs = new Set<string>();
      for (const [, label, ref] of citations) {
        if (citedRefs.has(ref)) continue;
        citedRefs.add(ref);
        const post = posts.find(item => item.embed_id === ref || embedField(item, 'embed_ref') === ref);
        expect(post, `${chat.slug}: source citation ${ref} resolves to a saved social post`).toBeDefined();
        const citation = history.getByTestId('message-assistant').getByRole('link', { name: label, exact: true }).first();
        await expect(citation, `${chat.slug}: cited post ${ref} remains visible with activity collapsed`).toBeVisible();
        const postFullscreen = await openFullscreen(page, citation);
        const originalBody = postFullscreen.locator('.original-post-card .post-content > p');
        await expect(originalBody).toBeVisible();
        expect(await originalBody.textContent(), `${chat.slug}: citation opens its exact saved post body`)
          .toBe(embedField(post!, 'body'));
        await expect(originalBody).toHaveCSS('white-space', 'pre-wrap');
        const sourceLink = postFullscreen.locator('a.embed-header-cta');
        await expect(sourceLink, `${chat.slug}: citation opens the saved post source`).toBeVisible();
        await expect(sourceLink).toHaveAttribute('href', embedField(post!, 'url')!);
        if (postsWithMedia.some(item => item.embed_id === post!.embed_id)) {
          const originalImage = postFullscreen.locator('.original-post-card img.media');
          await expect(originalImage).toBeVisible();
          await expect.poll(() => originalImage.evaluate((element: HTMLImageElement) => element.naturalWidth),
            { message: `${chat.slug}: cited original social post image loads` }).toBeGreaterThan(0);
        }
        await closeFullscreen(page, postFullscreen);
        await expect(citation).toBeVisible();
      }
    } else {
      const visibleResults = assistantPreview(history, firstParent!).or(history.getByTestId('message-assistant')
        .locator(posts.map(post => `[data-testid="embed-preview"][data-embed-id="${post.embed_id}"]`).join(',')))
        .filter({ visible: true }).first();
      await expect(visibleResults, `${chat.slug}: social result previews remain visible with activity collapsed`).toBeVisible();
    }
    await expandCompletedActivity(history, `${chat.slug}: social search activity`);
    for (const parentId of new Set(postsWithMedia.map(post => post.parent_embed_id))) {
      const parent = chat.embeds.find(embed => embed.embed_id === parentId);
      expect(parent, `${chat.slug}: parent of saved imaged post`).toBeDefined();
      const fullscreen = await openFullscreen(page, assistantPreview(history, parent!).filter({ visible: true }).first());
      for (const post of postsWithMedia.filter(item => item.parent_embed_id === parentId)) {
        expect(parent?.embed_ids, `${chat.slug}: post parent includes imaged child`).toContain(post.embed_id);
        const postCard = fullscreen.locator(`[data-testid="embed-preview"][data-embed-id="${post.embed_id}"]`);
        await expect(postCard).toBeVisible();
        const image = postCard.locator('.post-image');
        await expect(image).toBeVisible();
        await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth),
          { message: `${chat.slug}: saved social post ${post.embed_id} image loads` }).toBeGreaterThan(0);
        await postCard.click();
        const childOverlay = page.locator('.child-embed-overlay');
        await expect(childOverlay).toBeVisible();
        const childFullscreen = childOverlay.locator('.unified-embed-fullscreen-overlay').last();
        const originalBody = childFullscreen.locator('.original-post-card .post-content > p');
        await expect(originalBody).toBeVisible();
        expect(await originalBody.textContent(), `${chat.slug}: original post preserves source line breaks`)
          .toBe(embedField(post, 'body'));
        await expect(originalBody).toHaveCSS('white-space', 'pre-wrap');
        const originalImage = childFullscreen.locator('.original-post-card img.media');
        await expect(originalImage).toBeVisible();
        await expect.poll(() => originalImage.evaluate((element: HTMLImageElement) => element.naturalWidth),
          { message: `${chat.slug}: original social post fullscreen image loads` }).toBeGreaterThan(0);
        await closeFullscreen(page, childFullscreen);
        await expect(postCard).toBeVisible();
      }
      await closeFullscreen(page, fullscreen);
    }
  }
}

type SavedWebChat = Pick<ExampleChat, 'chat_id' | 'messages' | 'embeds'>;

async function expectWebActivityCollapsed(history: Locator, chat: SavedWebChat, context: string): Promise<void> {
  for (const message of chat.messages.filter(message => message.role === 'assistant')) {
    const content = sourceMessage(message.content);
    const webCalls = chat.embeds.filter(embed => embedField(embed, 'app_id') === 'web' && embed.type === 'app_skill_use');
    if (!webCalls.some(embed => content.includes(embed.embed_id))) continue;
    const rendered = history.locator(`[data-message-id="${message.id}"]`);
    const groups = rendered.getByTestId('assistant-activity-group');
    await expect(groups, `${context}: ${message.id} saved activity groups`).not.toHaveCount(0);
    await expect(rendered.locator('[data-testid="assistant-skill-app-icon"][data-app-id="web"]'),
      `${context}: saved web skill is represented in the collapsed summary`).not.toHaveCount(0);
    for (let index = 0, count = await groups.count(); index < count; index++) {
      const group = groups.nth(index);
      await expect(group.getByTestId('assistant-activity-toggle'), `${context}: activity ${index} collapsed`)
        .toHaveAttribute('aria-expanded', 'false');
      await expect(group.getByTestId('assistant-activity-summary-text')).toBeVisible();
      await expect(group.getByTestId('assistant-activity-summary-text')).not.toBeEmpty();
      await expect(group.getByTestId('assistant-activity-body')).toHaveCount(0);
      await expect(group.getByTestId('embed-preview')).toHaveCount(0);
    }
    await expect(rendered.getByTestId('thinking-section')).toHaveCount(0);
    await expect(rendered.getByTestId('message-content').first()).not.toBeEmpty();
  }
}

async function inspectSavedWebThinking(history: Locator, chat: SavedWebChat, context: string): Promise<void> {
  const normalize = (text: string): string => text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim().replace(/\s+/g, ' ');
  for (const message of chat.messages.filter(message => message.role === 'assistant' && message.has_thinking)) {
    expect(message.has_thinking, `${context}: ${message.id} actual saved thinking`).toBe(true);
    expect(message.thinking_content?.trim(), `${context}: ${message.id} saved thinking key`).toBeTruthy();
    const saved = sourceMessage(message.thinking_content!);
    expect(saved, `${context}: thinking translation resolves`).not.toBe(message.thinking_content);
    const expectedOpening = normalize(saved).split(' ').slice(0, 24).join(' ');
    expect(expectedOpening.length, `${context}: saved thinking has substantive content`).toBeGreaterThan(30);
    const rendered = history.locator(`[data-message-id="${message.id}"]`);
    const section = rendered.getByTestId('thinking-section');
    await expect(section, `${context}: one response-wide saved thinking disclosure`).toHaveCount(1);
    const toggle = section.getByTestId('thinking-header');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(section.getByTestId('thinking-content')).toHaveCount(0);
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const content = section.getByTestId('thinking-content');
    await expect(content).toBeVisible();
    expect(normalize(await content.innerText()), `${context}: actual saved thinking renders`).toContain(expectedOpening);
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(content).toHaveCount(0);
  }
}

// Pin the actual root: a dynamic nth locator or a reduction in the global
// overlay count does not prove that this Web tool/result finished closing.
async function closeSavedWebFullscreen(fullscreen: Locator): Promise<void> {
  await expect(fullscreen).toHaveCount(1);
  await expect(fullscreen).toHaveClass(/\banimating-in\b/);
  const root = await fullscreen.elementHandle();
  expect(root, 'saved Web fullscreen has its own mounted root').not.toBeNull();
  try {
    await fullscreen.getByTestId('embed-minimize').click();
    await expect.poll(() => root!.evaluate(element => element.isConnected),
      { message: 'the intended Web fullscreen root is unmounted', timeout: 10_000 }).toBe(false);
  } finally {
    await root?.dispose();
  }
}

async function inspectSavedWebSkills(page: Page, history: Locator, chat: SavedWebChat, requireSearch = false, exerciseFullscreen = true): Promise<void> {
  const researchParents = chat.embeds.filter(embed => embed.type === 'app_skill_use'
    && embedField(embed, 'app_id') === 'web'
    && ['search', 'read'].includes(embedField(embed, 'skill_id') ?? ''));
  expect(researchParents.length, `${chat.chat_id}: saved web search or read tools`).toBeGreaterThan(0);
  if (requireSearch) {
    expect(researchParents.some(parent => embedField(parent, 'skill_id') === 'search'
      && Number(embedField(parent, 'result_count')) > 0), `${chat.chat_id}: actual nonempty research search`).toBe(true);
  }
  for (const parent of researchParents) {
    const skill = embedField(parent, 'skill_id');
    expect(embedField(parent, 'status'), `${chat.chat_id}: saved web.${skill} terminal status`).toBe('finished');
    const resultCount = Number(embedField(parent, 'result_count'));
    expect(Number.isInteger(resultCount) && resultCount >= 0, `${chat.chat_id}: saved result count`).toBe(true);
    const preview = assistantPreview(history, parent);
    await expect(preview, `${chat.chat_id}: rendered web.${skill} preview`).toBeVisible();
    await expect(preview).toHaveAttribute('data-status', 'finished');
    if (skill === 'search') {
      expect(parent.embed_ids, `${chat.chat_id}: search references preserve actual count`).toHaveLength(resultCount);
      for (const id of parent.embed_ids ?? []) {
        expect(chat.embeds.find(embed => embed.embed_id === id)?.parent_embed_id,
          `${chat.chat_id}: saved search child ${id} points to parent`).toBe(parent.embed_id);
      }
      if (resultCount === 0) await expect(preview.getByTestId('search-no-results-message')).toBeVisible();
    } else {
      // Successful reads save inline results; they need not have child embed IDs.
      const inlineCount = Number(parent.content.match(/^results\[(\d+)\]:/m)?.[1] ?? 0);
      expect(inlineCount, `${chat.chat_id}: actual inline read results match saved count`).toBe(resultCount);
      if (resultCount === 0) expect(parent.embed_ids, `${chat.chat_id}: empty read has no invented children`).toEqual([]);
    }
    if (!exerciseFullscreen) continue;
    // Web visits each tool sequentially; a closing root must be gone before
    // openFullscreen takes its visible-overlay baseline for the next tool.
    await expect(page.locator('.unified-embed-fullscreen-overlay')).toHaveCount(0);
    const fullscreen = await openFullscreen(page, preview);
    await expect(fullscreen).toHaveClass(/\banimating-in\b/);
    if (skill === 'search' && resultCount > 0) {
      const grid = fullscreen.getByTestId('search-template-grid');
      await expect(grid.getByTestId('embed-preview')).toHaveCount(resultCount);
      const resultCard = grid.getByTestId('embed-preview').first();
      await expect(resultCard).toBeVisible();
      await resultCard.click();
      const resultOverlay = page.locator('.child-embed-overlay');
      await expect(resultOverlay).toBeVisible();
      await expect(resultOverlay).not.toBeEmpty();
      await closeSavedWebFullscreen(resultOverlay.locator('.unified-embed-fullscreen-overlay'));
      await expect(grid).toBeVisible();
    } else if (skill === 'search') {
      await expect(fullscreen.getByTestId('search-template-empty')).toBeVisible();
      await expect(fullscreen.getByTestId('search-no-results-message')).not.toBeEmpty();
      await expect(fullscreen.getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(0);
    } else if (resultCount === 0) {
      await expect(fullscreen.locator('.web-read-fullscreen-content .no-results')).toBeVisible();
      await expect(fullscreen.locator('.web-read-fullscreen-content .no-results')).not.toBeEmpty();
      await expect(fullscreen.locator('.result-content')).toHaveCount(0);
      await expect(fullscreen.locator('.text-preview-label')).toHaveCount(0);
    } else {
      await expect(fullscreen.locator('.result-content')).toHaveCount(resultCount);
      await expect(fullscreen.locator('.markdown-content')).toHaveCount(resultCount);
      for (let index = 0; index < resultCount; index++) {
        await expect(fullscreen.locator('.markdown-content').nth(index)).toBeVisible();
        await expect(fullscreen.locator('.markdown-content').nth(index)).not.toBeEmpty();
      }
      await expect(fullscreen.locator('.text-preview-label')).toBeVisible();
    }
    await closeSavedWebFullscreen(fullscreen);
  }
}

async function inspectChat(page: Page, chat: ExampleChat, appId: string, checkpoint: string, exerciseFollowUps = false): Promise<{ messages: number; embeds: number; suggestions: number }> {
  await closeSidebar(page);
  const history = page.getByTestId('chat-history-content');
  await expect(history).toBeVisible({ timeout: 30_000 });
  const visibleMessages = chat.messages.filter(message => message.role === 'user' || message.role === 'assistant');
  await expect(history).toHaveAttribute('data-source-message-count', String(chat.messages.length));
  for (const message of visibleMessages) {
    const rendered = history.locator(`[data-message-id="${message.id}"]`);
    await expect(rendered, `${checkpoint}: ${chat.slug} message ${message.id}`).toHaveCount(1);
    await expect(rendered).not.toHaveAttribute('data-status', /^(streaming|processing|sending)$/);
    // ReadOnlyMessage initializes its editor when this message enters the viewport.
    await rendered.scrollIntoViewIfNeeded();
    await expect(rendered.getByTestId('message-content').first(),
      `${checkpoint}: ${chat.slug} message ${message.id} renders after scrolling into view`).not.toBeEmpty();
    if (message.role === 'assistant') {
      await expect(rendered.getByTestId('chat-mate-name')).not.toHaveText('Assistant');
      const category = message.category || chat.category;
      await expect(rendered.getByTestId('mate-profile').first()).toHaveClass(new RegExp(`\\b${category}\\b`));
    }
  }
  await expect(page.getByTestId('active-chat-history-loading')).toHaveCount(0);
  if (appId === 'politics') {
    const firstSourceAnswer = chat.messages.find(message => message.role === 'assistant');
    expect(firstSourceAnswer, `${chat.slug}: source assistant answer`).toBeDefined();
    const firstAnswer = history.locator(`[data-message-id="${firstSourceAnswer!.id}"]`);
    await expect(firstAnswer, `${chat.slug}: first focus response asks the user directly`).toContainText('?');
  }
  if (checkpoint === 'direct') {
    await inspectGeneratedMediaGraph(page, history, chat, appId);
    await inspectSavedResultGraph(page, history, chat, appId);
    await inspectReportedHeaderRegressions(page, history, chat, appId);
  }
  if (appId === 'web') {
    await expectWebActivityCollapsed(history, chat, `${checkpoint}: ${chat.slug}: initial`);
  }
  await expandCompletedActivity(history, `${checkpoint}: ${chat.slug}`);
  if (appId === 'web') {
    await inspectSavedWebThinking(history, chat, `${checkpoint}: ${chat.slug}`);
    await inspectSavedWebSkills(page, history, chat, true, checkpoint === 'direct');
    await test.info().attach(`web-search-results-${checkpoint}.png`, { body: await page.screenshot({ fullPage: false }), contentType: 'image/png' });
  }
  const text = await history.innerText();
  for (const marker of forbidden) expect(text, `${checkpoint}: ${chat.slug}: ${marker}`).not.toContain(marker);
  expect(text).not.toMatch(/(?:^|\n)\s*(?:app_id|skill_id|embed_ref):\s*[^\n]+/m);
  expect(text).not.toMatch(/\{\s*"type"\s*:\s*"(?:app_skill_use|focus_mode_activation)"/);

  const isFocusActivation = (type: string) => type === 'focus-mode-activation' || type === 'focus_mode_activation';
  const focusActivations = chat.embeds.filter(embed => isFocusActivation(embed.type));
  if (focusActivations.length > 0) {
    const focusBars = history.getByTestId('focus-mode-bar');
    await expect(focusBars).toHaveCount(focusActivations.length);
    for (let i = 0; i < focusActivations.length; i++) {
      const focusBar = focusBars.nth(i);
      const focusId = focusActivations[i].content.match(/(?:^|\n)focus_id:\s*"?([^\n"]+)/)?.[1]?.trim();
      expect(focusId, `${chat.slug}: focus activation requires its saved focus ID`).toBeTruthy();
      await expect(focusBar).toBeVisible();
      await expect(focusBar).toHaveAttribute('data-focus-id', String(focusId));
      await expect(focusBar.getByTestId('focus-status-label')).not.toBeEmpty();
      await expect(focusBar.getByTestId('focus-status-value')).toHaveCount(1);
    }
  }

  const artifactEmbeds = chat.embeds.filter(embed => !isFocusActivation(embed.type));
  if (chat.metadata.app_skill_examples?.includes('code.application') || chat.embeds.some(embed => embed.type === 'application')) {
    expect(chat.follow_up_suggestions.length, `${chat.slug}: Code needs source follow-up suggestions`).toBeGreaterThan(0);
    const screenshot = history.getByTestId('application-preview-screenshot-image').first();
    await expect(screenshot).toBeVisible();
    await expect.poll(() => screenshot.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0),
      { message: `${chat.slug}: real application screenshot must load` }).toBe(true);
    const preview = history.locator('[data-testid="embed-preview"]:has([data-testid="application-preview-screenshot-image"])').first();
    const chatScroller = page.getByTestId('chat-history-container');
    await expect(chatScroller).toBeVisible();
    // The fixed composer can cover a CSS-visible card below the chat viewport.
    // Scroll the real chat pane as a user would, then require a reachable card.
    const paneBox = await chatScroller.boundingBox();
    expect(paneBox, `${chat.slug}: chat scroll pane has a viewport`).not.toBeNull();
    await page.mouse.move(paneBox!.x + paneBox!.width / 2, paneBox!.y + paneBox!.height / 2);
    let previewReachable = false;
    for (let attempt = 0; attempt < 12; attempt += 1) {
      previewReachable = await screenshot.evaluate((image: HTMLImageElement) => {
        const pane = image.closest('[data-testid="chat-history-container"]');
        const card = image.closest('[data-testid="embed-preview"]');
        if (!pane || !card) return false;
        const paneRect = pane.getBoundingClientRect();
        const imageRect = image.getBoundingClientRect();
        const x = imageRect.left + imageRect.width / 2;
        const y = imageRect.top + imageRect.height / 2;
        return y > paneRect.top && y < paneRect.bottom
          && card.contains(document.elementFromPoint(x, y));
      });
      if (previewReachable) break;
      const paneHeight = await chatScroller.evaluate((pane: HTMLElement) => pane.clientHeight);
      await page.mouse.wheel(0, Math.max(280, Math.round(paneHeight * 0.7)));
      await page.waitForTimeout(60);
    }
    expect(previewReachable, `${chat.slug}: application card reachable after scrolling chat`).toBe(true);
    await expect(preview).toBeInViewport({ ratio: 0.3 });
    const fullscreen = await openFullscreen(page, preview);
    const fullImage = fullscreen.getByTestId('application-fullscreen-screenshot').locator('img');
    await expect(fullImage).toBeVisible();
    await expect.poll(() => fullImage.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
    await closeFullscreen(page, fullscreen);
  }
  if (chat.metadata.app_skill_examples?.includes('videos.get_transcript')) {
    const userVideo = history.getByTestId('message-user').getByTestId('embed-preview').first();
    await expect(userVideo, `${chat.slug}: input video needs its own preview`).toBeVisible();
    const fullscreen = await openFullscreen(page, userVideo);
    const thumbnail = fullscreen.locator('.video-thumbnail').first();
    await expect(thumbnail).toBeVisible();
    await expect.poll(() => thumbnail.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
    await expect(fullscreen.getByRole('button', { name: /play/i }).first()).toBeVisible();
    await closeFullscreen(page, fullscreen);
  }
  const embedPreviews = history.getByTestId('embed-preview');
  if (artifactEmbeds.length > 0) {
    await expect(embedPreviews, `${checkpoint}: ${chat.slug}: saved embeds need a rendered preview`)
      .not.toHaveCount(0, { timeout: 15_000 });
  }
  const embedCount = await embedPreviews.count();
  if (artifactEmbeds.length > 0 && appId !== 'web') {
    expect(embedCount, `${chat.slug}: saved embeds need a visible preview`).toBeGreaterThan(0);
    const pdfArtifact = artifactEmbeds.find(embed => embed.type === 'pdf');
    const documentArtifact = artifactEmbeds.find(embed => embed.type === 'document');
    const recordingArtifact = artifactEmbeds.find(embed => embed.type === 'audio-recording');
    const selectedArtifact = pdfArtifact ?? documentArtifact ?? recordingArtifact;
    const preview = selectedArtifact
      ? history.locator(`[data-testid="embed-preview"][data-embed-id="${selectedArtifact.embed_id}"]`)
      : embedPreviews.first();
    await expect(preview).toBeVisible();
    const previewContent = (await preview.innerText()).trim();
    const imageCount = await preview.locator('img, svg, canvas').count();
    expect(previewContent.length > 0 || imageCount > 0, `${chat.slug}: blank embed preview`).toBe(true);
    const fullscreen = await openFullscreen(page, preview);
    await expect(fullscreen).toBeVisible();
    const links = fullscreen.getByRole('link');
    for (let i = 0, count = Math.min(await links.count(), 3); i < count; i++) {
      const href = await links.nth(i).getAttribute('href');
      if (href?.startsWith('blob:')) {
        expect(new URL(href).origin, `${chat.slug}: fullscreen blob link ${i}`).toBe(new URL(page.url()).origin);
      } else {
        expect(href, `${chat.slug}: fullscreen link ${i}`).toMatch(/^(?:https?:\/\/|\/|#\w)/);
      }
    }
    if (checkpoint === 'direct' && pdfArtifact) {
      const pageImage = fullscreen.getByTestId('pdf-public-page');
      await expect(pageImage).toBeVisible();
      await expect.poll(() => pageImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
      const downloadLink = fullscreen.getByTestId('pdf-public-download');
      await expect(downloadLink).toHaveAttribute('href', /\.pdf$/i);
      const downloadPromise = page.waitForEvent('download', { timeout: 20_000 });
      await downloadLink.click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toMatch(/\.pdf$/i);
      const pdfBytes = readFileSync((await download.path())!);
      expect(pdfBytes.length).toBeGreaterThan(100);
      expect(pdfBytes.subarray(0, 4).toString('ascii')).toBe('%PDF');
    }
    if (checkpoint === 'direct' && recordingArtifact) {
      const player = fullscreen.locator('.recording-fullscreen audio');
      await expect(player).toHaveCount(1);
      await expect.poll(() => player.evaluate((audio: HTMLAudioElement) => audio.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
      const duration = await player.evaluate((audio: HTMLAudioElement) => audio.duration);
      expect(duration, `${chat.slug}: saved recording should have a measurable duration`).toBeGreaterThan(1);
      await player.evaluate(async (audio: HTMLAudioElement) => { audio.muted = true; await audio.play(); });
      await expect.poll(() => player.evaluate((audio: HTMLAudioElement) => audio.currentTime), { timeout: 5_000 }).toBeGreaterThan(0);
      await player.evaluate((audio: HTMLAudioElement) => audio.pause());
    }
    if (checkpoint === 'direct' && documentArtifact) {
      const downloadButton = fullscreen.getByTestId('embed-download-button');
      if (!(await downloadButton.isVisible().catch(() => false))) {
        await fullscreen.locator('.embed-top-bar .more-trigger').click({ timeout: 5_000 });
      }
      await expect(downloadButton).toBeVisible();
      const downloadPromise = page.waitForEvent('download', { timeout: 20_000 });
      await downloadButton.click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toMatch(/\.docx$/i);
      const documentPath = await download.path();
      expect(documentPath).toBeTruthy();
      const documentBytes = readFileSync(documentPath!);
      expect(documentBytes.length, `${chat.slug}: downloaded DOCX must contain real content`).toBeGreaterThan(1_000);
      expect(documentBytes.subarray(0, 2).toString('ascii')).toBe('PK');
    }
    await closeFullscreen(page, fullscreen);
  }

  const editor = page.getByTestId('message-editor');
  await expect(editor).toBeVisible();
  const editable = editor.locator('[contenteditable="true"]');
  await expect(editable).toHaveCount(1);
  const suggestionCount = await page.getByTestId('follow-up-suggestion-item').count();
  if (chat.follow_up_suggestions.length > 0) {
    expect(suggestionCount, `${chat.slug}: saved follow-ups should render`).toBeGreaterThan(0);
    await expect(page.getByTestId('follow-up-suggestion-item').first()).not.toBeEmpty();
  }
  const draftText = 'Could you explain one detail?';
  const restoredDraft = page.getByTestId('message-draft-summary');
  if (await restoredDraft.isVisible()) {
    await expect(restoredDraft).toContainText(draftText);
    await page.getByTestId('message-field').click();
  }
  await expect(editable).toBeVisible({ timeout: 5_000 });
  await editable.fill(draftText, { timeout: 10_000 });
  await expect(editor).toContainText(draftText);
  if (exerciseFollowUps && suggestionCount > 0) {
    await dismissComposerFocus(page);
    await expect(restoredDraft).toContainText(draftText);
  }
  if (appId === 'web') {
    // Filling the draft opens the composer focus layer on the direct visit.
    // Dismiss it before interacting with the activity controls behind it.
    if (await page.getByTestId('message-field').getAttribute('data-focused') === 'true') {
      await dismissComposerFocus(page);
    }
    await collapseCompletedActivity(history, `${checkpoint}: ${chat.slug}`);
    await expectWebActivityCollapsed(history, chat, `${checkpoint}: ${chat.slug}: closed`);
  }
  if (exerciseFollowUps && suggestionCount > 0) {
    await page.evaluate(() => {
      (window as typeof window & { landingFollowUpSignup?: boolean }).landingFollowUpSignup = false;
      window.addEventListener('openSignupInterface', () => {
        (window as typeof window & { landingFollowUpSignup?: boolean }).landingFollowUpSignup = true;
      }, { once: true });
    });
    await page.getByTestId('follow-up-suggestion-item').first().click({ timeout: 5_000 });
    await expect.poll(() => page.evaluate(() =>
      (window as typeof window & { landingFollowUpSignup?: boolean }).landingFollowUpSignup)).toBe(true);
  }
  return { messages: visibleMessages.length, embeds: embedCount, suggestions: suggestionCount };
}

export type LandingViewport = 'phone' | 'laptop';

export function landingAdmissionCases(shard: 0 | 1): typeof cases {
  return cases.filter((_, index) => index % 2 === shard);
}

const replacementAppIds = new Set(['travel', 'maps', 'audio', 'videos']);

export function landingReplacementCases(): typeof cases {
  const selected = cases.filter(({ appId }) => replacementAppIds.has(appId));
  if (selected.length !== replacementAppIds.size) {
    throw new Error(`Expected ${replacementAppIds.size} landing replacement apps, found ${selected.length}`);
  }
  return selected;
}

export async function admitLandingExample(
  page: Page, request: APIRequestContext, testInfo: TestInfo,
  appId: string, chat: ExampleChat, viewport: LandingViewport,
  routeObservations?: FixtureImageProxyObservation[]
): Promise<void> {
  const size = viewport === 'phone' ? { width: 390, height: 844 } : { width: 1440, height: 1000 };
  await page.setViewportSize(size);
  const observation: Record<string, unknown> = {
    appId, slug: chat.slug, chatId: chat.chat_id, viewport, status: 'started', checkpoint: 'seo'
  };
  try {
    await configureFixtureImageProxy(page, chat, routeObservations);
    observation.checkpoint = 'landing header';
    await test.step('landing header opens the selected real example', async () => {
      await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
      const rail = page.getByTestId('landing-app-rail');
      const prompt = page.getByTestId('landing-prompt');
      await expect(rail).toBeVisible();
      // Use the public keyboard interaction. It selects and holds each app,
      // including icons outside the clipped rail viewport.
      for (let step = 0; step < landingAppOrder.length; step++) {
        if (await prompt.getAttribute('data-active-app') === appId) break;
        await rail.press('ArrowRight');
      }
      await expect(prompt).toHaveAttribute('data-active-app', appId);
      if (appId === 'web') await expect(prompt).toHaveText('Search the web');
      if (appId === 'models3d') await expect(prompt).toHaveText('Find 3D models');
      const expectedExampleUrl = new URL(`/#chat-id=${encodeURIComponent(chat.chat_id)}`, page.url());
      const displayedLanguage = await page.getByTestId('landing-page').getAttribute('lang');
      expect(displayedLanguage).toMatch(/^(en|de)$/);
      expectedExampleUrl.searchParams.set('lang', displayedLanguage!);
      await expect(prompt).toHaveAttribute('href', expectedExampleUrl.href);
      await expect(prompt).toHaveAttribute('target', '_blank');
      await expect(prompt).toHaveCSS('opacity', '1');
      const popupPromise = page.waitForEvent('popup');
      await prompt.click();
      const popup = await popupPromise;
      try {
        await expect(popup).toHaveURL(new RegExp(`#chat-id=${encodeURIComponent(chat.chat_id)}$`));
        await expect(popup.getByTestId('example-chat-badge')).toBeVisible({ timeout: 30_000 });
        await expect(popup.getByTestId('message-assistant').first()).toBeVisible({ timeout: 30_000 });
      } finally {
        await popup.close();
      }
    });
    observation.checkpoint = 'seo';
    await test.step('SEO entry', async () => {
      await inspectSeoEntry(request, chat);
    });
    observation.checkpoint = 'SEO redirect';
    await test.step('SEO redirect opens the interactive chat', async () => {
      await page.goto(getE2EDebugUrl(`/example/${chat.slug}`), { waitUntil: 'domcontentloaded' });
      await expect(page).toHaveURL(new RegExp(`#chat-id=${encodeURIComponent(chat.chat_id)}$`));
      await expect(page.getByTestId('message-assistant').first()).toBeVisible({ timeout: 30_000 });
    });
    observation.checkpoint = 'direct chat';
    const first = await test.step('direct chat has complete safe transcript and usable artifacts', async () => {
      await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chat.chat_id)}`), { waitUntil: 'domcontentloaded' });
      return inspectChat(page, chat, appId, 'direct');
    });
    observation.checkpoint = 'reload';
    const reloaded = await test.step('reloaded chat keeps its transcript and follow-up controls', async () => {
      await page.reload({ waitUntil: 'domcontentloaded' });
      return inspectChat(page, chat, appId, 'reload', true);
    });
    Object.assign(observation, { status: 'passed', checkpoint: 'complete', first, reloaded });
  } finally {
    await testInfo.attach(`landing-app-example-${appId}-${viewport}.json`, {
      body: Buffer.from(JSON.stringify(observation, null, 2)), contentType: 'application/json'
    });
  }
}
