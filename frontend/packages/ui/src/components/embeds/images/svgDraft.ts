/**
 * frontend/packages/ui/src/components/embeds/images/svgDraft.ts
 *
 * Pure helpers for the live SVG drawing shown by generated-image embeds while
 * the vector author is still working (status "processing" + `svg_draft`).
 */

export type SvgDraftStage = 'drawing' | 'checking' | 'correcting' | 'scripting';

export interface SvgDraftState {
  /** Partial or complete SVG source; empty when no draft is available */
  draft: string;
  stage: SvgDraftStage | undefined;
  attempt: number | undefined;
}

export const EMPTY_SVG_DRAFT: SvgDraftState = { draft: '', stage: undefined, attempt: undefined };

/** Read the draft fields from decoded embed content. A shorter text replaces the old one (restarted drawing). */
export function readSvgDraft(content: Record<string, unknown> | null | undefined): SvgDraftState {
  if (!content) return EMPTY_SVG_DRAFT;
  const draft = typeof content.svg_draft === 'string' ? content.svg_draft : '';
  const rawStage = content.draft_stage;
  const stage =
    rawStage === 'drawing' ||
    rawStage === 'checking' ||
    rawStage === 'correcting' ||
    rawStage === 'scripting'
      ? rawStage : undefined;
  const attempt = typeof content.draft_attempt === 'number' ? content.draft_attempt : undefined;
  return { draft, stage, attempt };
}

/** The drawing replaces the skeleton only while processing and when there is source to draw. */
export function shouldShowSvgDraft(status: string, draft: string): boolean {
  return status === 'processing' && draft.trim().length > 0;
}

const DRAWABLE_SVG_ELEMENT = /<(path|rect|circle|ellipse|polygon|polyline|line|text|image|use)\b[^>]*>/i;

/**
 * True once the draft holds at least one complete drawable element. The first
 * draft chunks carry only the `<svg>` header, which renders as an empty box, so
 * the card keeps showing the request until there is something to look at.
 */
export function hasDrawableSvg(draft: string): boolean {
  return DRAWABLE_SVG_ELEMENT.test(draft);
}

/** What the skill was asked to do, as announced by a processing update. */
export interface GenerationRequestInfo {
  prompt: string;
  /** Short model id as known to the model metadata; empty while unknown */
  model: string;
  /** Embeds passed as input images (a modification when not empty) */
  inputEmbedIds: string[];
}

export const EMPTY_GENERATION_REQUEST: GenerationRequestInfo = { prompt: '', model: '', inputEmbedIds: [] };

/** Read the announced request; fields missing in this update keep their earlier value. */
export function readGenerationRequest(
  content: Record<string, unknown> | null | undefined,
  prev: GenerationRequestInfo = EMPTY_GENERATION_REQUEST,
): GenerationRequestInfo {
  if (!content) return prev;
  const prompt = typeof content.prompt === 'string' && content.prompt.trim() ? content.prompt.trim() : prev.prompt;
  const model = typeof content.model === 'string' && content.model ? content.model : prev.model;
  const ids = Array.isArray(content.input_embed_ids)
    ? content.input_embed_ids.filter((id): id is string => typeof id === 'string' && id.length > 0)
    : [];
  return { prompt, model, inputEmbedIds: ids.length > 0 ? ids : prev.inputEmbedIds };
}

/** i18n key for the status label, or null while simply drawing. */
export function svgDraftStageLabelKey(stage: SvgDraftStage | undefined): string | null {
  if (stage === 'checking') return 'embeds.image_generate.checking';
  if (stage === 'correcting') return 'embeds.image_generate.correcting';
  if (stage === 'scripting') return 'embeds.image_generate.scripting';
  return null;
}

/**
 * Merge a processing update into the current draft state. A stage-only update
 * (empty draft) updates the stage but keeps the earlier picture; only the
 * `scripting` stage clears it, because a new script attempt has no picture yet.
 */
export function mergeSvgDraft(prev: SvgDraftState, next: SvgDraftState): SvgDraftState {
  if (next.draft || next.stage === 'scripting') return next;
  if (!next.stage) return prev;
  return { draft: prev.draft, stage: next.stage, attempt: next.attempt ?? prev.attempt };
}

/** True while processing with no picture to draw but a stage label to show (scripting). */
export function shouldShowDraftStatusOnly(status: string, draft: string, stage: SvgDraftStage | undefined): boolean {
  return status === 'processing' && draft.trim().length === 0 && svgDraftStageLabelKey(stage) !== null;
}

/**
 * Plain TOON content of a live draft that belongs to this card, or null.
 *
 * Drafts are sent as `processing` updates of the child image embed, while the
 * card on screen is its parent skill placeholder, so the card accepts updates
 * addressed to itself or to one of its children.
 */
export function childDraftContent(
  detail: { embed_id?: unknown; parent_embed_id?: unknown; status?: unknown; content?: unknown } | null | undefined,
  cardEmbedId: string,
): string | null {
  if (!detail || detail.status !== 'processing' || !cardEmbedId) return null;
  if (detail.parent_embed_id !== cardEmbedId || detail.embed_id === cardEmbedId) return null;
  return typeof detail.content === 'string' && detail.content.length > 0 ? detail.content : null;
}
