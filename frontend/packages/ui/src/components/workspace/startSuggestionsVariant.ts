/**
 * Placement of the start-screen suggestions above the input (Marco, 21 Nov, TASK dd6af963):
 * - 'right': the current look, lines right-aligned at the end of the block (variant A, live).
 * - 'input-width': a block as wide as the message input, centred, lines left-aligned (variant B).
 * Marco compares both on phone and desktop in the component preview before one becomes the default.
 */
export type StartSuggestionsVariant = 'right' | 'input-width';

/** Variant every start screen uses until Marco picks one. */
export const START_SUGGESTIONS_VARIANT: StartSuggestionsVariant = 'right';
