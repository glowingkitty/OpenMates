// playwright-account: not_required reason=public_logged_out_example_admission
// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
/* eslint-disable @typescript-eslint/no-require-imports -- The shared browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { landingAppExamples } from '../../../packages/public-site/src/components/landing/landingPageContent';
import { tedTalkTranscriptSummaryChat } from '../../../packages/ui/src/demo_chats/data/example_chats/ted-talk-transcript-summary';
import englishMessages from '../../../packages/ui/src/i18n/locales/en.json';
import { admitLandingExample, type LandingViewport } from './landing-app-example-admission';

const { test, expect } = require('./helpers/cookie-audit');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

const chat = tedTalkTranscriptSummaryChat;
const videoId = '8S0FDjFBj8o';
const originalRequest = 'Get the transcript for this TED talk and summarize the core argument in five bullets:';

for (const viewport of ['phone', 'laptop'] as LandingViewport[]) {
  // contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  test(`Videos landing example admits its real transcript and input video on ${viewport}`, async (
    { page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo
  ) => {
    test.setTimeout(180_000);
    expect(landingAppExamples.videos).toBe(chat.chat_id);
    expect(chat.metadata.app_skill_examples).toContain('videos.get_transcript');
    expect(chat.follow_up_suggestions).toHaveLength(6);

    const userMessage = chat.messages.find(message => message.role === 'user');
    const assistantMessage = chat.messages.find(message => message.role === 'assistant');
    const video = chat.embeds.find(embed => embed.type === 'videos-video');
    const transcript = chat.embeds.find(embed => embed.type === 'app_skill_use'
      && embed.content.includes('skill_id: get_transcript'));
    expect(userMessage).toBeDefined();
    expect(assistantMessage).toBeDefined();
    expect(video).toBeDefined();
    expect(transcript).toBeDefined();
    expect(video!.content).toContain(`video_id: ${videoId}`);
    expect(video!.content).toContain(`https://www.youtube.com/watch?v=${videoId}`);
    expect(transcript!.content).toContain(`https://www.youtube.com/watch?v=${videoId}`);
    expect(transcript!.content).toContain('[00:00:19.513] Hear that?');
    expect(transcript!.content).toContain("[00:00:21.762] That's nothing.");
    const savedTranscriptCounts = transcript!.content.match(/,(\d+),(\d+),English,[0-9a-f]+\nresult_count:/);
    expect(savedTranscriptCounts, 'saved transcript result includes its authored word and character counts').not.toBeNull();
    const savedWordCount = Number(savedTranscriptCounts![1]);
    expect(savedWordCount).toBeGreaterThan(100);
    const authoredRef = video!.content.match(/^embed_ref: ([^\n]+)$/m)?.[1];
    expect(authoredRef).toBeTruthy();
    const savedRequest = englishMessages.example_chats.ted_talk_transcript_summary.message_1.text;
    expect(savedRequest).toBe(`${originalRequest} [!](embed:${authoredRef})`);

    // Covers logged-out SEO entry, inline and fullscreen video thumbnail pixels,
    // completed activity, safe transcript, six follow-ups, and reload.
    await admitLandingExample(page, request, testInfo, 'videos', chat, viewport);

    // The helper exercises a follow-up signup action; reload to inspect the
    // untouched, persisted public chat after that interaction.
    await page.reload({ waitUntil: 'domcontentloaded' });
    const history = page.getByTestId('chat-history-content');
    await expect(history).toHaveAttribute('data-source-message-count', String(chat.messages.length));
    const renderedUser = history.locator(`[data-message-id="${userMessage!.id}"]`);
    await expect(renderedUser.getByTestId('message-content')).toContainText(originalRequest);
    await expect(renderedUser.getByTestId('message-content')).not.toContainText(`[!](embed:${authoredRef})`);
    const inputCard = renderedUser.locator(`[data-testid="embed-preview"][data-embed-id="${video!.embed_id}"]`);
    await expect(inputCard).toBeVisible();
    const inlineThumbnail = inputCard.locator('img.video-thumbnail');
    await expect(inlineThumbnail).toBeVisible();
    await expect.poll(() => inlineThumbnail.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0),
      { message: `${viewport}: real input-video thumbnail pixels after reload` }).toBe(true);

    const answer = history.locator(`[data-message-id="${assistantMessage!.id}"]`).getByTestId('message-content');
    await expect(answer).toContainText(/Will Stephen['’]s satirical TEDx presentation/);
    await expect(answer).toContainText('Here is the core argument summarized in five points:');
    const corePoints = answer.getByRole('list').first().getByRole('listitem');
    await expect(corePoints).toHaveCount(5);
    await expect(corePoints.first()).toContainText('Delivery Creates the Illusion of Substance');
    await expect(corePoints.last()).toContainText('Emotional Crescendos Can Be Manufactured');
    // The saved example retains all six authored suggestions. The composer
    // deliberately shows only the first four at once.
    const visibleSuggestions = page.getByTestId('follow-up-suggestion-item');
    await expect(visibleSuggestions).toHaveCount(4);
    const expectedVisibleSuggestions = [
      englishMessages.example_chats.ted_talk_transcript_summary.follow_up_1.text,
      englishMessages.example_chats.ted_talk_transcript_summary.follow_up_2.text,
      englishMessages.example_chats.ted_talk_transcript_summary.follow_up_3.text,
      englishMessages.example_chats.ted_talk_transcript_summary.follow_up_4.text,
    ];
    for (const [index, suggestion] of expectedVisibleSuggestions.entries()) {
      await expect(visibleSuggestions.nth(index)).toContainText(suggestion);
    }

    for (const toggle of await history.getByTestId('assistant-activity-toggle').all()) {
      if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
    }
    const transcriptPreview = history.getByTestId('message-assistant')
      .locator(`[data-testid="embed-preview"][data-embed-id="${transcript!.embed_id}"]`).first();
    await expect(transcriptPreview).toBeVisible();
    const fullscreen = await openFullscreen(page, transcriptPreview);
    await expect(fullscreen.getByTestId('transcript-word-count')).toContainText(String(savedWordCount));
    await expect(fullscreen.getByTestId('transcript-box')).toContainText('Hear that?');
    await expect(fullscreen.getByTestId('transcript-box')).toContainText(/That['’]s nothing\./);
    await expect(fullscreen.getByTestId('transcript-box').locator('.timestamp').first()).toBeVisible();
    await closeFullscreen(page, fullscreen);
  });
}
