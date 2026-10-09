/* eslint-disable @typescript-eslint/no-require-imports -- The shared browser helpers use CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { landingAppExamples } from '../../../packages/public-site/src/components/landing/landingPageContent';
import { ALL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
import type { ExampleChat } from '../../../packages/ui/src/demo_chats/types';

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

async function inspectChat(page: Page, chat: ExampleChat, checkpoint: string, exerciseFollowUps = false): Promise<{ messages: number; embeds: number; suggestions: number }> {
  await closeSidebar(page);
  const history = page.getByTestId('chat-history-content');
  await expect(history).toBeVisible({ timeout: 30_000 });
  const visibleMessages = chat.messages.filter(message => message.role === 'user' || message.role === 'assistant');
  await expect(history).toHaveAttribute('data-source-message-count', String(chat.messages.length));
  for (const message of visibleMessages) {
    const rendered = history.locator(`[data-message-id="${message.id}"]`);
    await expect(rendered, `${checkpoint}: ${chat.slug} message ${message.id}`).toHaveCount(1);
    await expect(rendered).not.toHaveAttribute('data-status', /^(streaming|processing|sending)$/);
    await expect(rendered.getByTestId('message-content').first()).not.toBeEmpty();
  }
  const text = await history.innerText();
  for (const marker of forbidden) expect(text, `${checkpoint}: ${chat.slug}: ${marker}`).not.toContain(marker);
  expect(text).not.toMatch(/(?:^|\n)\s*(?:app_id|skill_id|embed_ref):\s*[^\n]+/m);
  expect(text).not.toMatch(/\{\s*"type"\s*:\s*"(?:app_skill_use|focus_mode_activation)"/);
  await expect(page.getByTestId('active-chat-history-loading')).toHaveCount(0);

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
  const embedPreviews = history.getByTestId('embed-preview');
  const embedCount = await embedPreviews.count();
  if (artifactEmbeds.length > 0) {
    expect(embedCount, `${chat.slug}: saved embeds need a visible preview`).toBeGreaterThan(0);
    const pdfArtifact = artifactEmbeds.find(embed => embed.type === 'pdf');
    const documentArtifact = artifactEmbeds.find(embed => embed.type === 'document');
    const recordingArtifact = artifactEmbeds.find(embed => embed.type === 'audio-recording');
    const musicArtifact = chat.chat_id === 'example-community-garden-welcome-melody'
      ? artifactEmbeds.find(embed => embed.type === 'app_skill_use') : undefined;
    const selectedArtifact = pdfArtifact ?? documentArtifact ?? recordingArtifact ?? musicArtifact;
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
    if (checkpoint === 'direct' && musicArtifact) {
      const player = fullscreen.getByTestId('music-generate-fullscreen-audio');
      await expect(player).toBeVisible();
      await expect.poll(() => player.evaluate((audio: HTMLAudioElement) => audio.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
      const duration = await player.evaluate((audio: HTMLAudioElement) => audio.duration);
      expect(duration, `${chat.slug}: real music should have a measurable duration`).toBeGreaterThan(1);
      await player.evaluate(async (audio: HTMLAudioElement) => { audio.muted = true; await audio.play(); });
      await expect.poll(() => player.evaluate((audio: HTMLAudioElement) => audio.currentTime), { timeout: 5_000 }).toBeGreaterThan(0);
      await player.evaluate((audio: HTMLAudioElement) => audio.pause());
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
    const focusBackdrop = page.getByTestId('chat-composer-focus-backdrop');
    if (await focusBackdrop.isVisible()) {
      await focusBackdrop.click({ timeout: 5_000 });
      await expect(focusBackdrop).toBeHidden({ timeout: 5_000 });
      await expect(restoredDraft).toContainText(draftText);
    }
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

export async function admitLandingExample(
  page: Page, request: APIRequestContext, testInfo: TestInfo,
  appId: string, chat: ExampleChat, viewport: LandingViewport
): Promise<void> {
  const size = viewport === 'phone' ? { width: 390, height: 844 } : { width: 1440, height: 1000 };
  await page.setViewportSize(size);
  const observation: Record<string, unknown> = {
    appId, slug: chat.slug, chatId: chat.chat_id, viewport, status: 'started', checkpoint: 'seo'
  };
  try {
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
      return inspectChat(page, chat, 'direct');
    });
    observation.checkpoint = 'reload';
    const reloaded = await test.step('reloaded chat keeps its transcript and follow-up controls', async () => {
      await page.reload({ waitUntil: 'domcontentloaded' });
      return inspectChat(page, chat, 'reload', true);
    });
    Object.assign(observation, { status: 'passed', checkpoint: 'complete', first, reloaded });
  } finally {
    await testInfo.attach(`landing-app-example-${appId}-${viewport}.json`, {
      body: Buffer.from(JSON.stringify(observation, null, 2)), contentType: 'application/json'
    });
  }
}
