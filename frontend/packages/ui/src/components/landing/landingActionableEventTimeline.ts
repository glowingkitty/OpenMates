/**
 * Shared timing contract for the logged-out Actionable event demo.
 * The component and parent carousel consume the same values so the progress
 * bar reaches 100% when the one-shot animation completes.
 */

export const ACTIONABLE_STAGE_SEQUENCE = [
  { id: 'user-request', durationMs: 1800 },
  { id: 'assistant-response', durationMs: 1800 },
  { id: 'event-preview', durationMs: 2700 },
  { id: 'luma-cta', durationMs: 2200 },
] as const;

export type ActionableStage = (typeof ACTIONABLE_STAGE_SEQUENCE)[number]['id'];

export const ACTIONABLE_DEMO_DURATION_MS = ACTIONABLE_STAGE_SEQUENCE.reduce(
  (total, stage) => total + stage.durationMs,
  0,
);

export const ACTIONABLE_PREVIEW_POINTER_TARGET_MS = 1000;
export const ACTIONABLE_PREVIEW_CLICK_MS = 1800;
export const ACTIONABLE_CTA_POINTER_TARGET_MS = 700;
export const ACTIONABLE_CTA_CLICK_MS = 1450;
