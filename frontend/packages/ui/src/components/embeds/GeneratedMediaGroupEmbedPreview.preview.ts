/** A completed generation invocation remains visible as a parent card. */
// Registers the same static child embeds the fullscreen fixture resolves, so the
// parent card loads real thumbnails and the prompt like it does in a chat.
import './GeneratedMediaGroupEmbedFullscreen.preview';
// Registers the video a running change request changes (SOURCE_EMBED_ID).
import { SOURCE_EMBED_ID } from './videos/VideoGenerateEmbedPreview.preview';
import { embedStore } from '../../services/embedStore';
import { FOX_PREPARED_SVG } from './design/embroideryFixtures';

/** Uploaded SVG passed to design.embroidery; shown as the card's input graphic. */
export const EMBROIDERY_SOURCE_EMBED_ID = '3f6d2a8e-5b1c-4e7a-9d2f-8c4b6a1e0f37';
embedStore.registerStaticEmbed({
  embedId: EMBROIDERY_SOURCE_EMBED_ID,
  type: 'code',
  appId: 'code', skillId: 'code',
  content: JSON.stringify({ type: 'code', status: 'finished', language: 'svg', filename: 'fox.svg', code: FOX_PREPARED_SVG }),
});
const embroideryRun = {
  id: 'b4e1c7a2-9d3f-4a6b-8e2c-5f7a1d9c3b60', appId: 'design', skillId: 'embroidery',
  status: 'processing' as const, resultCount: 0, childEmbedIds: [] as string[],
  prompt: 'Red fox patch', inputEmbedIds: [EMBROIDERY_SOURCE_EMBED_ID], onFullscreen: () => {},
};

const defaultProps = {
  id: '0e29d61f-c88d-489c-b4a0-d471d37ea365',
  appId: 'images', skillId: 'generate', status: 'finished' as const,
  resultCount: 2,
  prompt: 'A golden retriever puppy wearing a tiny yellow raincoat, jumping over a puddle in a sunlit Berlin street, soft film grain, shallow depth of field',
  childEmbedIds: ['9c02483d-faba-4467-85ef-26167a7ad64e', '462d4ad2-2712-4f6f-b779-b10348d7f94d'],
  onFullscreen: () => {},
};
export default defaultProps;
export const variants = {
  videoProgress: {
    ...defaultProps, appId: 'videos', status: 'processing' as const, resultCount: 0, childEmbedIds: [],
    prompt: 'A 20 second recap of this week\'s news', progressStage: 'rendering',
  },
  videoCorrecting: {
    ...defaultProps, appId: 'videos', status: 'processing' as const, resultCount: 0, childEmbedIds: [],
    prompt: 'A 20 second recap of this week\'s news', progressStage: 'correcting', progressAttempt: 2,
  },
  processingAudioSpeech: {
    ...defaultProps, appId: 'videos', status: 'processing' as const, resultCount: 0, childEmbedIds: [],
    prompt: 'A 20 second recap of this week\'s news', progressStage: 'audio', progressAudio: ['speech'],
  },
  processingAudioAll: {
    ...defaultProps, appId: 'videos', status: 'processing' as const, resultCount: 0, childEmbedIds: [],
    prompt: 'A 20 second recap of this week\'s news', progressStage: 'audio', progressAudio: ['speech', 'sound', 'music'],
  },
  videoChange: {
    ...defaultProps, appId: 'videos', status: 'processing' as const, resultCount: 0, childEmbedIds: [],
    prompt: 'Make the headline of the budget scene bigger and use a warmer color', progressStage: 'writing',
    change: 'edit', sourceEmbedId: SOURCE_EMBED_ID,
  },
  imageRequest: {
    ...defaultProps, status: 'processing' as const, resultCount: 0, childEmbedIds: [],
    prompt: 'A pair of stylised mountain peaks at sunrise, flat shapes, warm orange and deep blue palette, thin outline, centred composition',
    model: 'claude-sonnet-4-6', inputEmbedIds: ['9c02483d-faba-4467-85ef-26167a7ad64e'],
  },
  // The backend's first update is the reading step (backend/apps/design/embroidery/progress.py).
  embroideryStarted: { ...embroideryRun, embroideryStage: 'reading' as const },
  embroideryStitching: { ...embroideryRun, embroideryStage: 'stitching' as const },
  embroiderySaving: { ...embroideryRun, embroideryStage: 'saving' as const },
  svgStreaming: {
    ...defaultProps, status: 'processing' as const, resultCount: 0, childEmbedIds: [],
    prompt: 'A pair of stylised mountain peaks at sunrise', model: 'claude-sonnet-4-6', draftStage: 'drawing' as const,
    svgDraft: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60"><rect width="100" height="60" fill="#fde68a"/><path d="M0 60 L30 20 L55 60 Z" fill="#1d4ed8"/><path d="M40 60 L70 25 L100 60 Z" fill="#1e3a8a"/><circle cx="78" cy="14" r="7" fill="#f97316"/',
  },
};
