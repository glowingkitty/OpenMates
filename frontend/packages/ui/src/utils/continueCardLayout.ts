/** Minimum free room for the greeting, a 200px card, and browse controls. */
export function hasRoomForLargeContinueCards(containerWidth: number, availableHeight: number): boolean {
  return containerWidth >= 550 && availableHeight >= 420;
}
