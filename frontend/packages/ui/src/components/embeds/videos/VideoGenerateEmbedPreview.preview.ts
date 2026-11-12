/**
 * Preview fixtures for VideoGenerateEmbedPreview: finished composed and
 * generative videos, a long title, each running step, running changes of an
 * earlier video (edit, extend at the end) and a failed request.
 * Access at: /dev/preview/embeds/videos/VideoGenerateEmbedPreview?chrome=0&variant=composed
 * Clicking the play button records `data-video-generate-fullscreen-opens` on <body>.
 */
import { embedStore } from '../../../services/embedStore';

const POSTER = '/store-examples/video-generate-1-poster.webp';
/** Title card frame of a composed video: a real, non-black still image. */
const COMPOSED_THUMBNAIL = `data:image/svg+xml;utf8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">'
  + '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1f6feb"/><stop offset="1" stop-color="#8a3ffc"/></linearGradient></defs>'
  + '<rect width="1280" height="720" fill="url(#g)"/><rect x="96" y="470" width="620" height="12" rx="6" fill="#ffd166"/>'
  + '<text x="96" y="400" font-family="Arial, sans-serif" font-size="88" font-weight="700" fill="#ffffff">This week in the city</text>'
  + '<text x="96" y="560" font-family="Arial, sans-serif" font-size="44" fill="#e8ecff">Council approves the budget</text></svg>',
)}`;

/** The video a running change request changes; resolved by id from the embed store. */
export const SOURCE_EMBED_ID = '7a1c9e2b-4d3f-4b8a-9c6e-1f2a3b4c5d6e';
embedStore.registerStaticEmbed({
  embedId: SOURCE_EMBED_ID,
  type: 'generated_video',
  appId: 'videos',
  skillId: 'generate',
  content: JSON.stringify({
    type: 'generated_video', app_id: 'videos', skill_id: 'generate', status: 'finished', made_by: 'composed',
    prompt: 'A 20 second recap of this week\'s city news', author_model: 'gpt-6.1-sol', previewImageUrl: COMPOSED_THUMBNAIL,
  }),
});

const onFullscreen = () => {
  document.body.dataset.videoGenerateFullscreenOpens = String(Number(document.body.dataset.videoGenerateFullscreenOpens ?? 0) + 1);
};

const composed = {
  id: 'preview-generated-video-composed',
  prompt: 'A 20 second recap of this week\'s city news',
  model: 'gpt-6.1-sol',
  authorModel: 'gpt-6.1-sol',
  madeBy: 'composed',
  durationSeconds: 20,
  resolution: '1280 x 720',
  previewImageUrl: COMPOSED_THUMBNAIL,
  status: 'finished' as const,
  onFullscreen,
};

const generative = {
  id: 'preview-generated-video',
  prompt: 'Sunrise over an alpine meadow',
  model: 'gemini-omni-1.2-flash',
  madeBy: 'generative',
  durationSeconds: 8,
  resolution: '720p',
  previewImageUrl: POSTER,
  status: 'finished' as const,
  onFullscreen,
};

const processing = (progressStage: string, progressAttempt = 1) => ({
  ...composed, status: 'processing' as const, previewImageUrl: '', durationSeconds: undefined, progressStage, progressAttempt,
});

const defaultProps = generative;
export default defaultProps;

export const variants = {
  composed,
  generative,
  /** Older video without a stored thumbnail: neutral surface with the play button. */
  noThumbnail: { ...generative, previewImageUrl: '' },
  longTitle: {
    ...composed,
    prompt: 'Supercalifragilisticexpialidociousvideoaboutthecitycouncilbudgetvoteandthenewtramlinewithoutanyspaces and then a very long description of every scene in the recap that keeps going well past two lines of text',
  },
  processingDeciding: processing('deciding'),
  processingWriting: processing('writing'),
  processingRendering: processing('rendering'),
  processingCorrecting: processing('correcting', 2),
  processingGenerating: { ...processing('generating'), madeBy: 'generative', model: 'gemini-omni-1.2-flash', prompt: 'Sunrise over an alpine meadow' },
  changeEdit: {
    ...processing('writing'), prompt: 'Make the headline of the budget scene bigger and use a warmer color',
    change: 'edit', sourceEmbedId: SOURCE_EMBED_ID,
  },
  changeExtendEnd: {
    ...processing('generating'), prompt: 'Continue with the sun rising over the mountains',
    change: 'extend_end', sourceEmbedId: SOURCE_EMBED_ID,
  },
  /** The video being changed is not on this device: label and instruction still show. */
  changeUnresolved: {
    ...processing('rendering'), prompt: 'Remove the closing line',
    change: 'edit', sourceEmbedId: '00000000-0000-4000-8000-00000000dead',
  },
  error: { ...generative, status: 'error' as const, previewImageUrl: '', error: 'Video generation failed' },
};
