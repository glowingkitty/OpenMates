/**
 * frontend/packages/ui/src/components/embeds/images/imageDraft.ts
 *
 * Pure helpers for the progress of images.modify shown by generated-image
 * embeds: current step, attempt counter, computed draft picture and the
 * review result of a finished edit. Drafts are never stored chat content.
 */

export type ImageModifyStage = 'writing' | 'running' | 'checking' | 'correcting';
export type ImageModifyReviewStatus = 'accepted' | 'corrected' | 'unmet_delivered' | 'skipped' | 'unavailable';

export interface ImageModifyState {
  stage: ImageModifyStage | undefined;
  /** 1-based attempt number; undefined when not announced */
  attempt: number | undefined;
  /** Base64 JPEG without data: prefix; empty when no draft picture exists */
  draft: string;
}

export const EMPTY_IMAGE_MODIFY: ImageModifyState = { stage: undefined, attempt: undefined, draft: '' };

/** Draft pictures are at most 60 KB of JPEG, which is below 82 KB of base64 text. */
const MAX_DRAFT_BASE64_CHARS = 90_000;
const BASE64_PATTERN = /^[A-Za-z0-9+/]+={0,2}$/;

export function isModifySkill(skillId: unknown): boolean {
  return skillId === 'modify';
}

/** True only for well-formed base64 of plausible size. */
export function isValidBase64(value: string): boolean {
  return value.length > 0 && value.length <= MAX_DRAFT_BASE64_CHARS && value.length % 4 === 0 && BASE64_PATTERN.test(value);
}

/** `data:` URL for a valid base64 JPEG draft, otherwise null. */
export function imageDraftUrl(draft: string | null | undefined): string | null {
  return typeof draft === 'string' && isValidBase64(draft) ? `data:image/jpeg;base64,${draft}` : null;
}

/** Read the modify progress fields from decoded embed content. */
export function readImageModify(content: Record<string, unknown> | null | undefined): ImageModifyState {
  if (!content) return EMPTY_IMAGE_MODIFY;
  const raw = content.draft_stage;
  const stage = raw === 'writing' || raw === 'running' || raw === 'checking' || raw === 'correcting' ? raw : undefined;
  const attempt = typeof content.draft_attempt === 'number' && Number.isInteger(content.draft_attempt) && content.draft_attempt >= 1
    ? content.draft_attempt : undefined;
  const draft = typeof content.image_draft === 'string' && isValidBase64(content.image_draft) ? content.image_draft : '';
  return { stage, attempt, draft };
}

/**
 * Merge a processing update: a stage-only update keeps the earlier picture, a new
 * picture replaces it, and a restarted writing step starts without a stale picture.
 */
export function mergeImageModify(prev: ImageModifyState, next: ImageModifyState): ImageModifyState {
  if (!next.stage && !next.draft) return prev;
  const draft = next.draft || (next.stage === 'writing' ? '' : prev.draft);
  return { stage: next.stage ?? prev.stage, attempt: next.attempt ?? prev.attempt, draft };
}

export function imageModifyStageKey(stage: ImageModifyStage | undefined): string | null {
  return stage ? `embeds.image_modify.${stage}` : null;
}

/** The attempt counter is only shown from the second attempt on. */
export function showsAttempt(attempt: number | undefined): attempt is number {
  return typeof attempt === 'number' && attempt >= 2;
}

/** Plain list of unmet requirements; only for an edit delivered with unmet requirements. */
export function readUnmetRequirements(content: Record<string, unknown> | null | undefined): string[] {
  if (!content || content.review_status !== 'unmet_delivered' || !Array.isArray(content.unmet_requirements)) return [];
  return content.unmet_requirements
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    .map((item) => item.trim());
}
