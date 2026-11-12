/**
 * Preview fixtures for VideoGenerateEmbedFullscreen: composed video with five named
 * parts, generative clips with and without extend, an older video without a stored
 * timeline and a second version. The small public example video really plays.
 * Access at: /dev/preview/embeds/videos/VideoGenerateEmbedFullscreen?variant=composed
 */
const VIDEO = '/store-examples/video-generate-1.mp4';
const POSTER = '/store-examples/video-generate-1-poster.webp';

type Part = { id: string; label: string; from: number; duration_in_frames: number; kind: string; texts: { id: string; value: string }[] };
const scene = (id: string, label: string, from: number, duration: number, texts: Part['texts'] = []): Part =>
  ({ id, label, from, duration_in_frames: duration, kind: 'scene', texts });

const composedTimeline = {
  fps: 30, duration_in_frames: 600, width: 1280, height: 720,
  tracks: [
    { id: 'video', name: 'Video', kind: 'visual', parts: [
      scene('scene-1', 'Intro', 0, 90, [{ id: 'title', value: 'This week in the city' }]),
      scene('scene-2', 'Budget vote', 90, 150, [{ id: 'headline', value: 'Council approves the budget' }, { id: 'subline', value: 'Vote ends 7 to 2' }]),
      scene('scene-3', 'Transit plan', 240, 150, [{ id: 'headline', value: 'New tram line opens in spring' }]),
      scene('scene-4', 'Weather', 390, 120, [{ id: 'headline', value: 'Sunny weekend ahead' }]),
      scene('scene-5', 'Outro', 510, 90, [{ id: 'title', value: 'See you next week' }]),
    ] },
    { id: 'texts', name: 'Texts', kind: 'text', parts: [
      { id: 'lower-third', label: 'Source line', from: 90, duration_in_frames: 300, kind: 'text', texts: [{ id: 'source', value: 'Sources: city news desk' }] },
      { id: 'closing-line', label: 'Closing line', from: 480, duration_in_frames: 120, kind: 'text', texts: [{ id: 'line', value: 'Subscribe for the next recap' }] },
    ] },
  ],
};

const generativeTimeline = {
  fps: 30, duration_in_frames: 240, width: 1280, height: 720,
  tracks: [{ id: 'video', name: 'Video', kind: 'visual', parts: [
    { id: 'clip-1', label: 'Alpine sunrise', from: 0, duration_in_frames: 240, kind: 'clip', texts: [] },
  ] }],
};

const base = {
  model: 'gemini-omni-1.2-flash',
  resolution: '720p',
  previewVideoUrl: VIDEO,
  previewImageUrl: POSTER,
  fps: 30, width: 1280, height: 720, version: 1,
};

const composed = {
  ...base, made_by: 'composed', prompt: 'A 20 second recap of this week\'s city news', model: 'composed',
  duration_seconds: 20, timeline: composedTimeline, remotion_source: 'export const Recap = () => null;',
  can_extend_start: false, can_extend_end: false, source_titles: ['Council approves the budget', 'New tram line opens in spring'],
};
const generative = {
  ...base, made_by: 'generative', prompt: 'Sunrise over an alpine meadow', duration_seconds: 8, timeline: generativeTimeline,
  can_extend_start: true, can_extend_end: true,
};

/** The component takes the data-driven shape: decoded content plus the stored embed. */
function fixture(content: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    data: { decodedContent: content, embedData: { status: 'finished' }, attrs: { app_id: 'videos' } },
    onClose: () => {},
    ...extra,
  };
}

const defaultProps = fixture(composed);
export default defaultProps;

export const variants = {
  loading: fixture({ ...composed, previewVideoUrl: '' }),
  composed: fixture(composed),
  generative: fixture(generative),
  generativeNoExtend: fixture({ ...generative, can_extend_start: false, can_extend_end: false }),
  /** Extend at the end only (a model that cannot lead into a given frame). */
  generativeEndOnly: fixture({ ...generative, can_extend_start: false }),
  /** Older video without a stored timeline: one clip from the loaded length. */
  legacy: fixture({ prompt: 'Sunrise over an alpine meadow', model: 'gemini-omni-1.2-flash', resolution: '720p', previewVideoUrl: VIDEO, previewImageUrl: POSTER }),
  version2: fixture({ ...composed, version: 2 }, { embedId: '33333333-3333-4333-8333-333333333333', versionCount: 2 }),
  withNavigation: fixture(composed, { hasPreviousEmbed: true, hasNextEmbed: true, onNavigatePrevious: () => {}, onNavigateNext: () => {} }),
};
