/**
 * Start-screen row composition shared by the Chats and Workflows start screens.
 *
 * The horizontal row shows only items of the screen's own kind (chats on Chats,
 * workflows on Workflows) as large cards. Daily inspirations of that kind are
 * interleaved with a fixed rhythm: the first two cards are the user's own items,
 * then one inspiration after every third own item (own 1-2, inspiration, own 3-5,
 * inspiration, ...). A user without own items sees only inspirations.
 *
 * Spec: specifications/features/daily-inspiration (daily-inspiration.start-row-rhythm)
 * Docs: docs/architecture/frontend/daily-inspiration.md
 */
import type { DailyInspiration } from '../stores/dailyInspirationStore';

/** Own items shown before the first inspiration. */
export const START_ROW_LEADING_OWN_ITEMS = 2;
/** Own items between two inspirations after the leading group. */
export const START_ROW_OWN_ITEMS_BETWEEN_INSPIRATIONS = 3;
/** Most recent own items shown in the row; inspirations come on top. */
export const START_ROW_MAX_OWN_ITEMS = 10;

/** Content types of chat inspirations allowed in the Chats row (each starts a chat). */
const CHAT_ROW_CONTENT_TYPES = new Set(['video', 'wiki']);
/** Content type of a recommended workflow inspiration (Workflows row hook). */
export const WORKFLOW_RECOMMENDATION_CONTENT_TYPE = 'workflow';

export type StartRowEntry<Own, Inspiration> =
  | { kind: 'own'; item: Own }
  | { kind: 'inspiration'; item: Inspiration };

/**
 * Interleave inspirations into the user's own items with the fixed rhythm.
 * Own items are capped at START_ROW_MAX_OWN_ITEMS; inspirations are used in order and
 * never repeated. With fewer than two own items, one inspiration follows them so the
 * row still offers a daily inspiration; with none, all inspirations are shown.
 */
export function interleaveStartRow<Own, Inspiration>(
  ownItems: readonly Own[],
  inspirations: readonly Inspiration[],
): StartRowEntry<Own, Inspiration>[] {
  const own = ownItems.slice(0, START_ROW_MAX_OWN_ITEMS);
  if (own.length === 0) return inspirations.map((item) => ({ kind: 'inspiration', item }));

  const entries: StartRowEntry<Own, Inspiration>[] = [];
  let nextInspiration = 0;
  own.forEach((item, index) => {
    entries.push({ kind: 'own', item });
    const ownCount = index + 1;
    const groupComplete =
      ownCount === START_ROW_LEADING_OWN_ITEMS ||
      (ownCount > START_ROW_LEADING_OWN_ITEMS &&
        (ownCount - START_ROW_LEADING_OWN_ITEMS) % START_ROW_OWN_ITEMS_BETWEEN_INSPIRATIONS === 0);
    if (groupComplete && nextInspiration < inspirations.length) {
      entries.push({ kind: 'inspiration', item: inspirations[nextInspiration++] });
    }
  });
  if (own.length < START_ROW_LEADING_OWN_ITEMS && nextInspiration < inspirations.length) {
    entries.push({ kind: 'inspiration', item: inspirations[nextInspiration] });
  }
  return entries;
}

/**
 * Chat inspirations that belong in the Chats row: video and article cards of the
 * Chats surface that have not been opened yet (an opened one is already a real chat).
 */
export function selectChatRowInspirations(inspirations: readonly DailyInspiration[]): DailyInspiration[] {
  return inspirations.filter(
    (inspiration) =>
      (inspiration.surface ?? 'chats') === 'chats' &&
      CHAT_ROW_CONTENT_TYPES.has(inspiration.content_type) &&
      !inspiration.is_opened,
  );
}

/**
 * Recommended-workflow inspirations for the Workflows row. None are generated yet;
 * records with surface "workflows", content_type "workflow" and a `workflow`
 * payload appear in the row automatically once they exist.
 */
export function selectWorkflowRowInspirations(inspirations: readonly DailyInspiration[]): DailyInspiration[] {
  return inspirations.filter(
    (inspiration) =>
      inspiration.surface === 'workflows' &&
      inspiration.content_type === WORKFLOW_RECOMMENDATION_CONTENT_TYPE &&
      !!inspiration.workflow &&
      !inspiration.is_opened,
  );
}
