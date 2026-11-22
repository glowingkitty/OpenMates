/**
 * Progress of a running design.embroidery request, shown on its parent card (TASK-1610).
 *
 * Processing updates of the result child carry `progress_stage`, `prompt` and
 * `input_embed_ids` (wire contract: backend/apps/design/embroidery/progress.py).
 * Specification: specifications/features/app-skills/design-embroidery/specification.yml
 * Assertion: design-embroidery.progress.input-and-stages
 */

export const EMBROIDERY_PROGRESS_STAGES = ['reading', 'checking', 'adjusting', 'stitching', 'saving'] as const;
export type EmbroideryProgressStage = (typeof EMBROIDERY_PROGRESS_STAGES)[number];

export function isEmbroiderySkill(appId: unknown, skillId: unknown): boolean {
  return appId === 'design' && skillId === 'embroidery';
}

/** The stage of a processing update, or `prev` when the update names none. */
export function readEmbroideryStage(
  content: Record<string, unknown> | null | undefined,
  prev?: EmbroideryProgressStage,
): EmbroideryProgressStage | undefined {
  const stage = content?.progress_stage;
  return typeof stage === 'string' && (EMBROIDERY_PROGRESS_STAGES as readonly string[]).includes(stage)
    ? (stage as EmbroideryProgressStage)
    : prev;
}

/** i18n key of the stage label, or undefined before the first stage arrives. */
export function embroideryStageLabelKey(stage: EmbroideryProgressStage | undefined): string | undefined {
  return stage ? `embeds.design.embroidery.progress_${stage}` : undefined;
}
