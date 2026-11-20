/** Free height a start screen needs below its banner for the greeting, a 200px card row and browse controls. */
export const LARGE_CONTINUE_CARDS_MIN_HEIGHT = 420;

/** Minimum free room for the greeting, a 200px card, and browse controls. */
export function hasRoomForLargeContinueCards(containerWidth: number, availableHeight: number): boolean {
  return containerWidth >= 550 && availableHeight >= LARGE_CONTINUE_CARDS_MIN_HEIGHT;
}
