/**
 * frontend/packages/ui/src/components/embeds/images/svgDraft.ts
 *
 * Pure helpers for the live SVG drawing shown by generated-image embeds while
 * the vector author is still working (status "processing" + `svg_draft`).
 */

export type SvgDraftStage = 'drawing' | 'checking' | 'correcting';

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
    rawStage === 'drawing' || rawStage === 'checking' || rawStage === 'correcting' ? rawStage : undefined;
  const attempt = typeof content.draft_attempt === 'number' ? content.draft_attempt : undefined;
  return { draft, stage, attempt };
}

/** The drawing replaces the skeleton only while processing and when there is source to draw. */
export function shouldShowSvgDraft(status: string, draft: string): boolean {
  return status === 'processing' && draft.trim().length > 0;
}

/** i18n key for the status label, or null while simply drawing. */
export function svgDraftStageLabelKey(stage: SvgDraftStage | undefined): string | null {
  if (stage === 'checking') return 'embeds.image_generate.checking';
  if (stage === 'correcting') return 'embeds.image_generate.correcting';
  return null;
}
