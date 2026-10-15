// Use the same generated, metadata-selected examples as the public landing rail.
// Resolve from the live catalog each time; browser chat caches never choose defaults.
import landingExamples from '../generated/landingExampleChats.generated.json';

export function selectDefaultGuestExampleChats<T>(
  examples: readonly T[],
  getId: (example: T) => string,
): T[] {
  const byId = new Map(examples.map(example => [getId(example), example]));
  return landingExamples
    .map(({ chatId }) => byId.get(chatId))
    .filter((example): example is T => example !== undefined);
}
