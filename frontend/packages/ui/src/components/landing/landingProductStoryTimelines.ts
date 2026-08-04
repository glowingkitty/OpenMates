/**
 * Shared timing contract for the logged-out landing product stories.
 * Each component and the parent carousel consume these constants so visual
 * stages, progress, and automatic advancement finish at the same moment.
 */

export const PRODUCT_STORY_HEADING_DELAY_MS = 1500;
export const PRODUCT_STORY_HEADING_FADE_OUT_MS = 420;
export const PRODUCT_STORY_HEADING_FADE_IN_MS = 420;
export const PRODUCT_STORY_HEADING_SWAP_MS = PRODUCT_STORY_HEADING_FADE_OUT_MS
  + PRODUCT_STORY_HEADING_FADE_IN_MS;

export const PRIVACY_STORY_STAGES = [
  { id: 'saved-data-copy', durationMs: 1600 },
  { id: 'encryption-lock', durationMs: 3000 },
  { id: 'pii-copy', durationMs: 1600 },
  { id: 'pii-detection', durationMs: 2400 },
  { id: 'originals-copy', durationMs: 1600 },
  { id: 'pii-reveal', durationMs: 2400 },
  { id: 'personalized-copy', durationMs: 1600 },
  { id: 'trip-request', durationMs: 1800 },
  { id: 'memory-permission', durationMs: 4000 },
] as const;

export const MATES_FOCUS_STORY_STAGES = [
  { id: 'mates', durationMs: 6000 },
  { id: 'focus', durationMs: 6000 },
] as const;

export const PEOPLE_EXPERIENCE_STORY_STAGES = [
  { id: 'providers', durationMs: 6000 },
  { id: 'access', durationMs: 6000 },
] as const;

export type PrivacyStoryStage = (typeof PRIVACY_STORY_STAGES)[number]['id'];
export type MatesFocusStoryStage = (typeof MATES_FOCUS_STORY_STAGES)[number]['id'];
export type PeopleExperienceStoryStage = (typeof PEOPLE_EXPERIENCE_STORY_STAGES)[number]['id'];

export const PRIVACY_STORY_DURATION_MS = PRIVACY_STORY_STAGES.reduce(
  (total, stage) => total + stage.durationMs,
  0,
);

export const MATES_FOCUS_STORY_DURATION_MS = MATES_FOCUS_STORY_STAGES.reduce(
  (total, stage) => total + stage.durationMs,
  0,
);

export const PEOPLE_EXPERIENCE_STORY_DURATION_MS = PEOPLE_EXPERIENCE_STORY_STAGES.reduce(
  (total, stage) => total + stage.durationMs,
  0,
);

export const PRIVACY_STORY_CAROUSEL_DURATION_MS = PRODUCT_STORY_HEADING_DELAY_MS
  + PRODUCT_STORY_HEADING_SWAP_MS
  + PRIVACY_STORY_DURATION_MS;

export const MATES_FOCUS_STORY_CAROUSEL_DURATION_MS = PRODUCT_STORY_HEADING_DELAY_MS
  + PRODUCT_STORY_HEADING_SWAP_MS
  + MATES_FOCUS_STORY_DURATION_MS;

export const PEOPLE_EXPERIENCE_STORY_CAROUSEL_DURATION_MS = PRODUCT_STORY_HEADING_DELAY_MS
  + PRODUCT_STORY_HEADING_SWAP_MS
  + PEOPLE_EXPERIENCE_STORY_DURATION_MS;
